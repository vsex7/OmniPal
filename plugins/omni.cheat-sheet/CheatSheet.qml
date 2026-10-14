import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui
import "CheatSheetData.js" as SheetData
import "Tokens.js" as Tokens

// OmniPal 快捷键 HUD（omni.cheat-sheet）
//
// 职责边界（AGENTS.md 铁律 1/2/3/5）：
//   • 只读展示：不注入绑定、不解绑、不写任何配置文件。
//   • 键位数据只来自 Engine：`omni-profile cheatsheet [mode] --json`（Engine 侧
//     再联合 schema/actions.json 与 profiles/*.json），当前模式与 Engine 状态来自
//     `omni-profile status --json`。本文件不存在任何键位列表副本。
//   • 一次进程调用同时拿两块数据：不轮询、不常驻。
//   • 拿不到数据时展示可操作的提示文本，不抛异常（优雅降级）。
Item {
  id: root

  // ---- Omarchy theme: Tokens.js is the single source of truth -------------
  // Follows the current Omarchy theme at runtime (colors.toml), tokyo-night fallback.
  property var themePalette: Tokens.fallback
  readonly property var theme: Tokens.build(Color, themePalette)
  FileView {
    id: omniThemeFile
    property bool legacy: false
    path: (Quickshell.env("HOME") || "") + (legacy ? Tokens.themeFiles.legacyRel : Tokens.themeFiles.stateRel)
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.themePalette = Tokens.mergePalette(Tokens.parseColorsToml(text()))
    onLoadFailed: if (!legacy) legacy = true
  }

  // ------------------------------------------------------- host contract
  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  // ---------------------------------------------------------- view state
  property bool opened: false
  // "" = 显示当前生效模式；非空 = 预览指定 Profile。
  property string requestedMode: ""

  property var engineState: ({})
  property bool stateKnown: false
  property var groups: []
  property int bindingCount: 0
  property bool loading: false
  property string errorKind: ""
  property string errorMessage: ""
  property string errorCommand: ""
  property var rawRows: []
  property string filterText: ""
  property string filterCategory: "all"
  property var categories: []

  // Live Modifier Highlight 状态：按住 Super/Alt/Ctrl/Shift 时高亮关联行与键帽
  property var liveMods: ({})
  property bool modsActive: false

  // 顶部 Profile 快速预览胶囊（只有模式 id 与装饰图标，键位真值仍归 Engine，铁律 3）
  readonly property var previewModes: [
    { id: "windows", label: "🪟 Windows 11" },
    { id: "mac", label: "🍎 macOS" },
    { id: "kde", label: "❖ KDE Plasma" },
    { id: "omarchy", label: "⊡ Omarchy 原生" }
  ]

  function applyFilter() {
    var query = root.filterText.trim()
    var queryRows = SheetData.filterRows(root.rawRows, query, "all")
    root.categories = SheetData.extractCategories(queryRows)
    var keep = false
    for (var i = 0; i < root.categories.length; i++) {
      if (root.categories[i].id === root.filterCategory) keep = true
    }
    if (!keep) root.filterCategory = "all"
    var rows = root.filterCategory === "all"
      ? queryRows
      : SheetData.filterRows(root.rawRows, query, root.filterCategory)
    root.groups = SheetData.groupByCategory(rows)
    root.bindingCount = rows.length
  }

  function selectCategory(id) {
    root.filterCategory = id
    root.applyFilter()
    body.contentY = 0
  }

  function cycleCategory(dir) {
    var cats = root.categories
    if (cats.length <= 1) return
    var idx = 0
    for (var i = 0; i < cats.length; i++) if (cats[i].id === root.filterCategory) idx = i
    root.filterCategory = cats[(idx + dir + cats.length) % cats.length].id
    root.applyFilter()
    body.contentY = 0
  }

  function previewMode(id) {
    if (root.requestedMode === id) return
    root.requestedMode = id
    root.filterCategory = "all"
    root.refresh()
  }

  function focusSearch() {
    searchInput.forceActiveFocus()
  }

  function syncMods(mask) {
    var mods = {
      super: (mask & Qt.MetaModifier) !== 0,
      alt: (mask & Qt.AltModifier) !== 0,
      ctrl: (mask & Qt.ControlModifier) !== 0,
      shift: (mask & Qt.ShiftModifier) !== 0
    }
    root.modsActive = mods.super || mods.alt || mods.ctrl || mods.shift
    root.liveMods = mods
  }

  function clearMods() {
    root.liveMods = ({})
    root.modsActive = false
  }

  readonly property string pluginId: (root.manifest && root.manifest.id) || "omni.cheat-sheet"
  readonly property string statusMark: "<<<OMNI_STATUS>>>"
  readonly property string sheetMark: "<<<OMNI_SHEET>>>"
  readonly property string rcMark: "<<<OMNI_RC>>>"

  // ------------------------------------------------------------ theming
  // 复用 [menu] 表面令牌：任何为 Omarchy 菜单配色的主题会同时给 HUD 配色。
  // 半透明卡片 + 遮罩由合成器（Hyprland blur）负责毛玻璃效果，这里不加额外的
  // ShaderEffect 通道，避免常驻 GPU 开销。
  property color foreground: Color.menu.text
  property color border: Color.menu.border
  property var borderSpec: Border.surfaceSpec("popups", "border", root.theme.popupBorder, Tokens.popup.border)
  property color scrim: root.theme.menuScrim
  property color accent: Color.menu.selectedText
  readonly property color glassColor: root.theme.popupBg  // Omarchy popups: opaque
  readonly property color hairline: Util.alpha(Color.menu.text, 0.14)
  readonly property color chipColor: Util.alpha(Color.menu.text, 0.07)
  readonly property string fontFamily: Style.font.menuFamily

  readonly property int cornerRadius: Style.cornerRadius
  readonly property int titleHeight: Math.max(Style.space(38), Style.font.heading + Style.space(18))
  readonly property int blockGap: Style.space(12)
  readonly property int footerHeight: Style.space(20)
  readonly property int rowHeight: Math.max(Style.space(26), Style.font.body + Style.space(12))
  readonly property int groupHeaderHeight: Style.space(30)
  readonly property int groupGap: Style.space(14)
  readonly property int placeholderHeight: Style.space(104)
  readonly property int contentMargin: Style.spacing.panelPadding

  // 卡片尺寸只由屏幕几何决定，不随分组数量变化，切模式时不会出现宽度跳动。
  readonly property int maxCardHeight: panel.height - Style.space(64)
  readonly property int cardWidth: Math.min(panel.width - Style.space(64),
    Math.max(Style.space(520), Math.min(Style.space(780), Math.round(panel.width * 0.5))))

  // 分类胶囊条仅在存在可过滤分类时贡献高度；Flow 按可用宽度决定行数，无循环依赖。
  readonly property bool categoryBarShown: root.categories.length > 1
  readonly property int categoryBarHeight: categoryBarShown ? pillFlow.implicitHeight : 0
  readonly property int categoryBarGap: categoryBarShown ? blockGap : 0
  readonly property int chromeHeight: card.contentTopInset + card.contentBottomInset
    + titleHeight + blockGap * 3 + footerHeight + 1 + categoryBarHeight + categoryBarGap
  readonly property int bodyContentHeight: root.groups.length > 0
    ? SheetData.contentHeight(root.groups, root.rowHeight, root.groupHeaderHeight, root.groupGap)
    : root.placeholderHeight
  readonly property int bodyViewportHeight: Math.min(root.bodyContentHeight,
    Math.max(Style.space(60), root.maxCardHeight - root.chromeHeight))
  readonly property int cardHeight: root.chromeHeight + root.bodyViewportHeight
  readonly property int keyColumnWidth: Math.max(Style.space(120), Math.round(root.cardWidth * 0.28))
  readonly property int nameColumnWidth: Math.max(Style.space(120), Math.round(root.cardWidth * 0.26))

  readonly property string displayMode: root.requestedMode || String(root.engineState.mode || "omarchy")
  readonly property string displayModeName: !root.requestedMode && root.stateKnown && root.engineState.name
    ? String(root.engineState.name) : root.displayMode
  readonly property string engineStatusLabel: !root.stateKnown ? "Engine 状态未知"
    : String(root.engineState.status || "") === "active" ? "Engine 运行中 · 覆盖生效"
    : String(root.engineState.status || "") === "native" ? "Engine 运行中 · 原生模式"
    : "Engine 未运行"
  // 按应用自动切换：当前应用命中的规则（来自运行目录下的 app_rule.json）
  property var appRule: null
  readonly property string appRuleLabel: root.appRule && root.appRule.rule
    ? ("应用规则 · " + String(root.appRule.window_class) + " → " + String(root.appRule.rule.mode)) : ""
  readonly property string engineStatusText: root.appRuleLabel !== ""
    ? (root.engineStatusLabel + " · " + root.appRuleLabel) : root.engineStatusLabel

  FileView {
    path: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/app_rule.json"
    watchChanges: true
    printErrors: false
    onLoaded: { try { root.appRule = JSON.parse(text()) } catch (e) { root.appRule = null } }
    onLoadFailed: root.appRule = null
    onFileChanged: reload()
  }

  // -------------------------------------------------------- data plumbing

  function open(payloadJson) {
    var payload = ({})
    try { payload = JSON.parse(payloadJson || "{}") } catch (e) { payload = ({}) }

    // 预览其它 Profile：{"mode":"windows"}。只接受裸 id，避免把额外参数
    // 塞进 CLI。
    var mode = typeof payload.mode === "string" ? payload.mode.trim().toLowerCase() : ""
    root.requestedMode = /^[a-z0-9][a-z0-9_-]*$/.test(mode) ? mode : ""

    root.filterText = ""
    root.filterCategory = "all"
    root.categories = []
    root.clearMods()
    if (searchInput) searchInput.text = ""
    root.opened = true
    root.refresh()
    root.focusContent()
  }

  function close() {
    root.opened = false
  }

  function dismiss() {
    root.opened = false
    if (root.shell && typeof root.shell.hide === "function") root.shell.hide(root.pluginId)
  }

  function toggle() {
    if (root.opened) root.dismiss()
    else root.open("{}")
  }

  // The surface is created lazily on the first summon, so requesting focus
  // inside open() can land before the window is mapped. Retry until the key
  // catcher actually owns focus, otherwise Esc/r would be dead.
  function focusContent() {
    keyCatcher.forceActiveFocus()
    if (!keyCatcher.activeFocus) {
      focusRetry.retryCount = 0
      focusRetry.restart()
    }
  }

  function refresh() {
    root.errorKind = ""
    root.errorMessage = ""
    root.errorCommand = ""
    root.loading = true
    dataProc.command = [
      "bash", "-c",
      "CLI=$(command -v omni-profile 2>/dev/null || echo \"$HOME/.local/bin/omni-profile\"); " +
      "if [ ! -x \"$CLI\" ]; then echo NO_CLI; exit 0; fi; " +
      "echo '<<<OMNI_STATUS>>>'; \"$CLI\" status --json 2>/dev/null || echo '{}'; " +
      "echo '<<<OMNI_SHEET>>>'; if [ -n \"$0\" ]; then \"$CLI\" cheatsheet \"$0\" --json 2>/dev/null || echo '[]'; else \"$CLI\" cheatsheet --json 2>/dev/null || echo '[]'; fi; " +
      "echo \"<<<OMNI_RC>>>$?\"",
      root.requestedMode
    ]
    dataProc.running = true
  }

  function commandFor(mode) {
    return mode ? "omni-profile cheatsheet " + mode + " --json" : "omni-profile cheatsheet --json"
  }

  function failWith(kind, command, message) {
    root.errorKind = kind
    root.errorCommand = command
    root.errorMessage = message
    root.groups = []
    root.bindingCount = 0
  }

  function applyFetch(exitCode, raw) {
    root.loading = false
    var text = String(raw || "")

    // Sentinel beats exit code: the helper can only exit non-zero for the CLI
    // itself, and `bash fetch.sh` exiting 127 would otherwise read as "CLI
    // broken" instead of "CLI missing".
    if (text.indexOf("NO_CLI") !== -1) {
      root.stateKnown = false
      root.failWith("no-cli", "omni-profile status",
        "请先安装 OmniPal（项目内执行 ./scripts/install.sh），再启用本插件。")
      return
    }

    var statusJson = ""
    var sheetJson = ""
    var sheetRc = -1
    var section = ""
    var lines = text.split("\n")
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i]
      if (line === root.statusMark) { section = "status"; continue }
      if (line === root.sheetMark) { section = "sheet"; continue }
      if (line.indexOf(root.rcMark) === 0) {
        sheetRc = parseInt(line.slice(root.rcMark.length), 10)
        continue
      }
      if (section === "status") statusJson += line
      else if (section === "sheet") sheetJson += line
    }

    // Status is best-effort: the list still renders without it, the header just
    // stops claiming to know the Engine state.
    var state = null
    try { state = statusJson.trim() ? JSON.parse(statusJson) : null } catch (e) { state = null }
    if (state && typeof state === "object" && !Array.isArray(state)) {
      root.engineState = state
      root.stateKnown = true
    } else {
      root.engineState = ({})
      root.stateKnown = false
    }

    if (exitCode !== 0) {
      root.failWith("cli-failed", root.commandFor(root.requestedMode),
        "数据读取执行失败（退出码 " + exitCode + "）。")
      return
    }
    // omni-profile 用退出码 2 表示“没有这个 Profile”。
    if (sheetRc === 2) {
      root.failWith("mode-missing", root.commandFor(root.requestedMode),
        "没有名为 " + (root.requestedMode || root.displayMode) + " 的模式定义。profiles/ 目录里有什么，这里就能显示什么。")
      return
    }
    if (sheetRc !== 0) {
      root.failWith("cli-failed", root.commandFor(root.requestedMode),
        "读取快捷键失败（退出码 " + sheetRc + "）。请确认 Engine 与 profile 文件完好。")
      return
    }
    if (!sheetJson.trim()) {
      root.failWith("bad-json", root.commandFor(root.requestedMode),
        "cheatsheet 没有输出任何内容。omni-profile 与插件需要同版本。")
      return
    }

    var rows = null
    try { rows = JSON.parse(sheetJson) } catch (e) { rows = null }
    if (!Array.isArray(rows)) {
      root.failWith("bad-json", root.commandFor(root.requestedMode),
        "cheatsheet 的输出不是 JSON 数组。omni-profile 与插件需要同版本。")
      return
    }

    root.rawRows = rows
    root.applyFilter()
    root.errorKind = ""
    root.errorCommand = ""
    root.errorMessage = ""
  }

  Process {
    id: dataProc
    stdout: StdioCollector {
      id: dataOut
      waitForEnd: true
    }
    onExited: function(exitCode) {
      root.applyFetch(exitCode, dataOut.text)
    }
  }

  Timer {
    id: focusRetry
    interval: 40
    repeat: true
    property int retryCount: 0
    onTriggered: {
      retryCount++
      keyCatcher.forceActiveFocus()
      if (keyCatcher.activeFocus || !root.opened || retryCount >= 25) {
        retryCount = 0
        stop()
      }
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omni-cheat-sheet"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
    }

    // 点击遮罩任意位置关闭。
    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: root.cardHeight
      radius: root.cornerRadius
      anchors.centerIn: parent
      color: root.glassColor
      borderSpec: root.borderSpec
      padding: root.contentMargin

      // 卡片内的点击被吞掉，避免误触遮罩关闭。
      MouseArea { anchors.fill: parent; onClicked: {} }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
          root.syncMods(event.modifiers)
          var scrollFloor = 0
          var scrollCeil = Math.max(0, body.contentHeight - body.height)
          if (event.key === Qt.Key_Escape) {
            root.dismiss()
            event.accepted = true
          } else if (event.key === Qt.Key_Tab) {
            root.cycleCategory((event.modifiers & Qt.ShiftModifier) !== 0 ? -1 : 1)
            event.accepted = true
          } else if (event.key === Qt.Key_Backtab) {
            root.cycleCategory(-1)
            event.accepted = true
          } else if (event.key === Qt.Key_Slash) {
            root.focusSearch()
            event.accepted = true
          } else if (event.key === Qt.Key_R) {
            root.refresh()
            event.accepted = true
          } else if (event.key === Qt.Key_Up) {
            body.contentY = Math.max(scrollFloor, body.contentY - root.rowHeight)
            event.accepted = true
          } else if (event.key === Qt.Key_Down) {
            body.contentY = Math.min(scrollCeil, body.contentY + root.rowHeight)
            event.accepted = true
          } else if (event.key === Qt.Key_PageUp) {
            body.contentY = Math.max(scrollFloor, body.contentY - body.height)
            event.accepted = true
          } else if (event.key === Qt.Key_PageDown) {
            body.contentY = Math.min(scrollCeil, body.contentY + body.height)
            event.accepted = true
          } else if (event.key === Qt.Key_Home) {
            body.contentY = scrollFloor
            event.accepted = true
          } else if (event.key === Qt.Key_End) {
            body.contentY = scrollCeil
            event.accepted = true
          }
        }
        Keys.onReleased: function(event) {
          root.syncMods(event.modifiers)
        }
      }

      // ----------------------------------------------------------- header
      Item {
        id: header
        anchors.top: parent.top
        anchors.topMargin: card.contentTopInset
        anchors.left: parent.left
        anchors.leftMargin: card.contentLeftInset
        anchors.right: parent.right
        anchors.rightMargin: card.contentRightInset
        height: root.titleHeight

        // ---- 顶部 Profile 快速预览胶囊组：点击即切换查看对应模式速查 ----
        Row {
          id: previewPills
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(6)

          Repeater {
            model: root.previewModes

            delegate: Rectangle {
              id: previewPill
              required property var modelData
              readonly property bool selected: root.displayMode === modelData.id
              readonly property bool engineActive: root.stateKnown
                && String(root.engineState.mode || "") === modelData.id

              height: Style.space(26)
              width: pillInner.implicitWidth + Style.space(16)
              radius: Tokens.corner(Style)
              color: selected ? root.theme.selectedFill
                : pillHover.containsMouse ? Util.alpha(root.foreground, 0.08) : "transparent"
              border.width: selected ? Tokens.border.focus : Tokens.border.hair
              border.color: selected ? root.theme.selectedBorder : root.hairline
              Behavior on color { ColorAnimation { duration: Tokens.motion.normal } }
              Behavior on border.color { ColorAnimation { duration: Tokens.motion.normal } }

              Row {
                id: pillInner
                anchors.centerIn: parent
                spacing: Style.space(5)

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  textFormat: Text.PlainText
                  text: previewPill.modelData.label
                  color: previewPill.selected ? root.accent : Util.alpha(root.foreground, 0.82)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  font.bold: previewPill.selected
                }

                Rectangle {
                  // Engine 当前生效模式绿点标记（预览≠生效时一目了然）
                  visible: previewPill.engineActive
                  width: Style.space(5)
                  height: Style.space(5)
                  radius: Tokens.corner(Style)
                  color: root.theme.ok
                  anchors.verticalCenter: parent.verticalCenter
                }
              }

              MouseArea {
                id: pillHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.previewMode(previewPill.modelData.id)
              }
            }
          }
        }

        Column {
          id: titleColumn
          visible: root.cardWidth >= Style.space(620)
          anchors.left: previewPills.right
          anchors.leftMargin: Style.space(12)
          anchors.verticalCenter: parent.verticalCenter

          Text {
            textFormat: Text.PlainText
            text: "快捷键速查"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            font.bold: true
          }

          Text {
            textFormat: Text.PlainText
            text: root.engineStatusText + " · 共 " + root.bindingCount + " 项"
            color: root.foreground
            opacity: 0.5
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        BorderSurface {
          id: searchBox
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(160)
          height: Style.space(26)
          radius: Tokens.corner(Style)
          color: Util.alpha(root.foreground, 0.06)
          borderSpec: root.borderSpec
          padding: Style.space(4)

          Row {
            anchors.fill: parent
            spacing: Style.space(6)

            Text {
              font.family: Style.font.family
              text: "🔍"
              font.pixelSize: Style.font.caption
              color: Util.alpha(root.foreground, 0.5)
              anchors.verticalCenter: parent.verticalCenter
            }

            TextInput {
              id: searchInput
              width: parent.width - Style.space(24)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              color: root.foreground
              anchors.verticalCenter: parent.verticalCenter
              selectByMouse: true

              Text {
                text: "搜索 · /"
                visible: searchInput.text === ""
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                color: Util.alpha(root.foreground, 0.4)
                anchors.verticalCenter: parent.verticalCenter
              }

              onTextChanged: {
                root.filterText = text
                root.applyFilter()
                body.contentY = 0
              }
            }
          }
        }
      }

      Rectangle {
        id: headerRule
        anchors.top: header.bottom
        anchors.topMargin: root.blockGap
        anchors.left: parent.left
        anchors.leftMargin: card.contentLeftInset
        anchors.right: parent.right
        anchors.rightMargin: card.contentRightInset
        height: 1
        color: root.hairline
      }

      // ---- 分类筛选胶囊条（带数量徽章，Tab / Shift+Tab 键盘循环） ----
      Item {
        id: categoryBar
        anchors.top: headerRule.bottom
        anchors.topMargin: root.blockGap
        anchors.left: parent.left
        anchors.leftMargin: card.contentLeftInset
        anchors.right: parent.right
        anchors.rightMargin: card.contentRightInset
        height: root.categoryBarShown ? pillFlow.implicitHeight : 0

        Flow {
          id: pillFlow
          anchors.left: parent.left
          anchors.right: parent.right
          spacing: Style.space(6)

          Repeater {
            model: root.categories

            delegate: Rectangle {
              id: catPill
              required property var modelData
              readonly property bool selected: root.filterCategory === modelData.id

              width: catPillRow.implicitWidth + Style.space(14)
              height: Style.space(24)
              radius: Tokens.corner(Style)
              color: selected ? root.theme.selectedFill
                : catPillHover.containsMouse ? Util.alpha(root.foreground, 0.07) : "transparent"
              border.width: selected ? Tokens.border.focus : Tokens.border.hair
              border.color: selected ? root.theme.selectedBorder : root.hairline
              Behavior on color { ColorAnimation { duration: Tokens.motion.normal } }
              Behavior on border.color { ColorAnimation { duration: Tokens.motion.normal } }

              Row {
                id: catPillRow
                anchors.centerIn: parent
                spacing: Style.space(5)

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  textFormat: Text.PlainText
                  text: catPill.modelData.label
                  color: catPill.selected ? root.accent : Util.alpha(root.foreground, 0.82)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: catPill.selected
                }

                Rectangle {
                  anchors.verticalCenter: parent.verticalCenter
                  width: Math.max(Style.space(15), catCountLabel.implicitWidth + Style.space(6))
                  height: Style.space(14)
                  radius: Tokens.corner(Style)
                  color: catPill.selected ? Util.alpha(root.accent, 0.25) : root.chipColor

                  Text {
                    id: catCountLabel
                    anchors.centerIn: parent
                    textFormat: Text.PlainText
                    text: catPill.modelData.count
                    color: catPill.selected ? root.accent : Util.alpha(root.foreground, 0.6)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                  }
                }
              }

              MouseArea {
                id: catPillHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.selectCategory(catPill.modelData.id)
              }
            }
          }
        }
      }

      // ------------------------------------------------------------- body
      Flickable {
        id: body
        anchors.top: categoryBar.bottom
        anchors.topMargin: root.blockGap
        anchors.left: parent.left
        anchors.leftMargin: card.contentLeftInset
        anchors.right: parent.right
        anchors.rightMargin: card.contentRightInset
        height: root.bodyViewportHeight
        contentWidth: width
        contentHeight: root.bodyContentHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        visible: root.groups.length > 0
        interactive: contentHeight > height

        Column {
          width: body.width
          spacing: root.groupGap

          Repeater {
            model: root.groups

            delegate: Item {
              id: group
              required property var modelData
              required property int index

              width: body.width
              height: root.groupHeaderHeight + group.modelData.items.length * root.rowHeight

              Row {
                id: groupHeader
                anchors.left: parent.left
                anchors.top: parent.top
                height: root.groupHeaderHeight
                spacing: Style.space(7)

                Rectangle {
                  width: Style.space(3)
                  height: Style.font.subtitle
                  radius: Tokens.corner(Style)
                  anchors.verticalCenter: parent.verticalCenter
                  color: Util.alpha(root.accent, 0.75)
                }

                Text {
                  textFormat: Text.PlainText
                  anchors.verticalCenter: parent.verticalCenter
                  text: group.modelData.label
                  color: root.foreground
                  opacity: 0.92
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.subtitle
                  font.bold: true
                }

                Text {
                  textFormat: Text.PlainText
                  anchors.verticalCenter: parent.verticalCenter
                  text: group.modelData.items.length
                  color: root.foreground
                  opacity: 0.4
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              Column {
                anchors.top: groupHeader.bottom
                anchors.left: parent.left
                anchors.right: parent.right

                Repeater {
                  model: group.modelData.items

                  delegate: Item {
                    id: binding
                    required property var modelData
                    readonly property bool rowLive: root.modsActive
                      && SheetData.isModifierActive(binding.modelData.key, root.liveMods)

                    width: group.width
                    height: root.rowHeight

                    Rectangle {
                      anchors.fill: parent
                      radius: Math.min(root.cornerRadius, Style.space(6))
                      color: bindingMouse.containsMouse ? Style.hoverFill
                        : (binding.rowLive ? Util.alpha(root.accent, 0.10) : "transparent")
                      border.width: binding.rowLive ? 1 : 0
                      border.color: Util.alpha(root.accent, 0.35)
                      Behavior on color { ColorAnimation { duration: Tokens.motion.fast } }
                    }

                    Flow {
                      id: keyFlow
                      anchors.left: parent.left
                      anchors.verticalCenter: parent.verticalCenter
                      width: root.keyColumnWidth
                      spacing: Style.space(4)

                      Repeater {
                        model: SheetData.splitCombo(binding.modelData.key)

                        delegate: Rectangle {
                          id: keyCap
                          required property var modelData
                          readonly property bool capLive: root.modsActive
                            && SheetData.isModifierActive(String(keyCap.modelData), root.liveMods)

                          width: keyLabel.implicitWidth + Style.space(13)
                          height: Math.max(Style.space(21), Style.font.body + Style.space(7))
                          // Omarchy key-cap chip (Tokens): flat fill, 1px border, accent when held
                          radius: Tokens.corner(Style)
                          border.width: keyCap.capLive ? Tokens.border.focus : Tokens.border.hair
                          border.color: keyCap.capLive ? root.theme.accent : root.theme.chipBorder
                          color: keyCap.capLive ? root.theme.selectionFill : root.theme.chipFill

                          // 实时按键高亮反馈：按住修饰键时关联键帽闪烁
                          SequentialAnimation on border.color {
                            loops: Animation.Infinite
                            running: keyCap.capLive
                            ColorAnimation { to: Util.alpha(root.accent, 0.95); duration: Tokens.motion.slow }
                            ColorAnimation { to: Util.alpha(root.accent, 0.30); duration: Tokens.motion.slow }
                          }

                          Text {
                            id: keyLabel
                            textFormat: Text.PlainText
                            anchors.centerIn: parent
                            text: SheetData.formatKeyCap(String(keyCap.modelData), root.displayMode)
                            color: keyCap.capLive ? root.accent : root.foreground
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.bodySmall
                            font.bold: true
                          }
                        }
                      }
                    }

                    Text {
                      id: nameLabel
                      anchors.left: keyFlow.right
                      anchors.leftMargin: Style.space(12)
                      anchors.verticalCenter: parent.verticalCenter
                      width: root.nameColumnWidth
                      textFormat: root.filterText.trim() !== "" ? Text.StyledText : Text.PlainText
                      text: root.filterText.trim() !== ""
                        ? SheetData.highlightMatches(binding.modelData.name, root.filterText, String(root.accent))
                        : binding.modelData.name
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      elide: Text.ElideRight
                      verticalAlignment: Text.AlignVCenter
                    }

                    Text {
                      anchors.left: nameLabel.right
                      anchors.leftMargin: Style.space(12)
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      textFormat: root.filterText.trim() !== "" ? Text.StyledText : Text.PlainText
                      text: root.filterText.trim() !== ""
                        ? SheetData.highlightMatches(binding.modelData.description, root.filterText, String(root.accent))
                        : binding.modelData.description
                      color: root.foreground
                      opacity: 0.5
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.bodySmall
                      elide: Text.ElideRight
                      verticalAlignment: Text.AlignVCenter
                    }

                    MouseArea {
                      id: bindingMouse
                      anchors.fill: parent
                      hoverEnabled: true
                      acceptedButtons: Qt.NoButton
                    }
                  }
                }
              }
            }
          }
        }
      }

      // -------------------------------------------------- degraded states
      Item {
        id: placeholder
        anchors.top: categoryBar.bottom
        anchors.topMargin: root.blockGap
        anchors.left: parent.left
        anchors.leftMargin: card.contentLeftInset
        anchors.right: parent.right
        anchors.rightMargin: card.contentRightInset
        height: root.placeholderHeight
        visible: root.groups.length === 0

        Column {
          anchors.centerIn: parent
          spacing: Style.space(8)

          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            textFormat: Text.PlainText
            text: root.placeholderTitle
            color: root.foreground
            opacity: 0.9
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            font.bold: true
          }

          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(Style.space(460), placeholder.width)
            textFormat: Text.PlainText
            text: root.placeholderBody
            color: root.foreground
            opacity: 0.5
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
          }

          Rectangle {
            visible: root.placeholderCommand !== ""
            anchors.horizontalCenter: parent.horizontalCenter
            width: commandLabel.implicitWidth + Style.space(16)
            height: Math.max(Style.space(22), Style.font.body + Style.space(8))
            radius: Math.min(root.cornerRadius, height / 2)
            color: root.chipColor
            border.color: root.hairline
            border.width: 1

            Text {
              id: commandLabel
              textFormat: Text.PlainText
              anchors.centerIn: parent
              text: root.placeholderCommand
              color: root.accent
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }

      // ------------------------------------------------------------ footer
      Item {
        id: footer
        anchors.bottom: parent.bottom
        anchors.bottomMargin: card.contentBottomInset
        anchors.left: parent.left
        anchors.leftMargin: card.contentLeftInset
        anchors.right: parent.right
        anchors.rightMargin: card.contentRightInset
        height: root.footerHeight

        Text {
          textFormat: Text.PlainText
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          text: "Esc 关闭 · / 搜索 · Tab 切分类 · R 刷新 · ↑↓ 滚动 · 按住 Super/Alt/Ctrl/Shift 高亮关联键位"
          color: root.foreground
          opacity: 0.42
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          textFormat: Text.PlainText
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          text: "OmniPal · " + root.displayMode
          color: root.foreground
          opacity: 0.32
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  // 降级状态文案。只有文案，不含任何键位数据；列表有内容时全部为空串。
  readonly property bool filterNoMatches: !root.loading && root.errorKind === ""
    && root.groups.length === 0 && root.rawRows.length > 0

  readonly property string placeholderTitle: root.loading ? "正在读取…"
    : root.errorKind === "no-cli" ? "未找到 OmniPal 命令行工具"
    : root.errorKind === "cli-failed" ? "读取快捷键失败"
    : root.errorKind === "bad-json" ? "解析 Engine 输出失败"
    : root.errorKind === "mode-missing" ? "没有这个模式"
    : root.groups.length > 0 ? ""
    : root.filterNoMatches ? "没有匹配的条目"
    : root.requestedMode !== "" ? "模式 " + root.displayMode + " 没有可用定义"
    : "当前没有生效的快捷键覆盖"

  readonly property string placeholderBody: root.loading ? "正在向 Engine 读取当前 Profile。"
    : root.errorMessage !== "" ? root.errorMessage
    : root.groups.length > 0 ? ""
    : root.filterNoMatches ? "换一个搜索词，或点击「全部」分类胶囊重试。"
    : root.requestedMode !== "" ? "这个模式没有映射任何快捷键。"
    : "原生模式沿用 Omarchy 默认键位，没有任何覆盖。切换习惯模式后这里会自动列出对应快捷键。"

  readonly property string placeholderCommand: root.loading ? ""
    : root.errorCommand !== "" ? root.errorCommand
    : (root.requestedMode === "" && root.groups.length === 0 && root.rawRows.length === 0) ? "omni-profile switch windows" : ""
}
