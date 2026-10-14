pragma ComponentBehavior: Bound
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Icons.js" as Icons
import "CheatSheetData.js" as SheetData
import "Takeovers.js" as Takeovers

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

  // ---- Theme ----------------------------------------------------------------
  // Chrome is 100% native: qs.Commons Color.menu.* / Style.* + qs.Ui OverlayWindow,
  // BorderSurface, Button, TextField, PanelSectionHeader, PanelSeparator — the same
  // kit omarchy.emojis / omarchy.menu use. Only the five native colour roles.

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
  // 接管的原生快捷键（omni-profile doctor --json -> takeovers），见 Takeovers.js
  property var doctorData: null
  property var takeover: ({ status: "unknown", items: [], hint: "" })
  // 上手指南：首次登录自动显示一次（omni-profile onboarding claim），之后按 G 或菜单重新打开
  property bool guideShown: false

  // Live Modifier Highlight 状态：按住 Super/Alt/Ctrl/Shift 时高亮关联行与键帽
  property var liveMods: ({})
  property bool modsActive: false

  // 顶部 Profile 快速预览胶囊（只有模式 id 与装饰图标，键位真值仍归 Engine，铁律 3）
  readonly property var previewModes: [
    { id: "windows", label: "windows" },
    { id: "mac", label: "macos" },
    { id: "kde", label: "kde" },
    { id: "omarchy", label: "omarchy" }
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
    var groups = SheetData.groupByCategory(rows)
    root.takeover = Takeovers.forMode(root.doctorData, root.displayMode)
    if (root.filterCategory === "all" && root.takeover.items.length > 0) {
      var q = query.toLowerCase()
      var items = []
      for (var t = 0; t < root.takeover.items.length; t++) {
        var e = root.takeover.items[t]
        var row = { key: e.key, name: e.name + (e.fixed ? "（固定入口）" : ""), description: "原来的功能：" + e.was }
        if (!q || (row.key + " " + e.combo + " " + row.name + " " + row.description).toLowerCase().indexOf(q) >= 0) items.push(row)
      }
      if (items.length > 0) groups.push({ id: "takeover", label: "接管的 Omarchy 原生快捷键", items: items })
    }
    root.groups = groups
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
  readonly property string doctorMark: "<<<OMNI_DOCTOR>>>"
  readonly property string statusMark: "<<<OMNI_STATUS>>>"
  readonly property string sheetMark: "<<<OMNI_SHEET>>>"
  readonly property string rcMark: "<<<OMNI_RC>>>"

  // ------------------------------------------------------------ theming
  // 复用 [menu] 表面令牌（与 omarchy.emojis 完全一致）：任何为 Omarchy 菜单配色的
  // 主题会同时给 HUD 配色。
  // Solid card: no reliance on Hyprland blur behind a translucent surface.
  readonly property color _menuBg: Commons.Color.menu.background
  property color background: Qt.rgba(_menuBg.r, _menuBg.g, _menuBg.b, 1)
  property color foreground: Commons.Color.menu.text
  property color border: Commons.Color.menu.border
  property var borderSpec: Border.surfaceSpec("menu", "border", border, Math.max(1, Style.space(2)))
  property color scrim: Commons.Color.menu.scrim
  property color accent: Commons.Color.menu.selectedText
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
  // 接管信息读不到（source none / 出错）时，列表上方一行灰色提示
  readonly property bool takeoverNoteShown: root.filterCategory === "all" && root.errorKind === ""
    && !root.loading && root.rawRows.length > 0
    && (root.takeover.status === "none" || root.takeover.status === "error" || root.takeover.status === "unknown")
  readonly property int takeoverNoteHeight: takeoverNoteShown ? Style.font.body + Style.space(8) : 0
  readonly property int chromeHeight: card.contentTopInset + card.contentBottomInset
    + titleHeight + blockGap * 3 + footerHeight + 1 + categoryBarHeight + categoryBarGap + takeoverNoteHeight
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

  // 首次登录：Shell 加载插件几秒后问 Engine 要一次「是否显示上手指南」。
  // claim 用 O_EXCL 创建 onboarding.json，只有第一次返回 show:true，以后不再弹出。
  Timer {
    id: onboardingTimer
    interval: 4000
    running: true
    repeat: false
    onTriggered: onboardingProc.running = true
  }

  Process {
    id: onboardingProc
    command: ["bash", "-c",
      "CLI=$(command -v omni-profile 2>/dev/null || echo \"$HOME/.local/bin/omni-profile\"); " +
      "[ -x \"$CLI\" ] && \"$CLI\" onboarding claim --json 2>/dev/null || echo '{}'"]
    stdout: StdioCollector {
      id: onboardingOut
      waitForEnd: true
    }
    onExited: function(exitCode) {
      var r = ({})
      try { r = JSON.parse(onboardingOut.text || "{}") } catch (e) { r = ({}) }
      if (r.show !== true) return
      if (root.shell && typeof root.shell.summon === "function") root.shell.summon(root.pluginId, '{"guide":true}')
      else root.open('{"guide":true}')
    }
  }

  FileView {
    path: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/app_rule.json"
    watchChanges: true
    printErrors: false
    onLoaded: { try { root.appRule = JSON.parse(text()) } catch (e) { root.appRule = null } }
    onLoadFailed: root.appRule = null
    onFileChanged: reload()
  }

  // 上手指南第 2 步的三个固定快捷键：取自 cheatsheet 输出里 fixed 的行（Engine 单一事实源）。
  readonly property var fixedRows: {
    var out = []
    for (var i = 0; i < root.rawRows.length; i++) {
      var r = root.rawRows[i]
      if (r && r.fixed === true) out.push({ combo: Takeovers.prettyCombo(r.key), name: String(r.name || "") })
    }
    return out
  }

  function fixedCombo(action) {
    for (var i = 0; i < root.rawRows.length; i++) {
      var r = root.rawRows[i]
      if (r && r.fixed === true && r.action === action) return Takeovers.prettyCombo(r.key)
    }
    return ""
  }

  function openSettings() {
    root.guideShown = false
    root.dismiss()
    if (root.shell && typeof root.shell.summon === "function") root.shell.summon("omni.settings", "{}")
    else Quickshell.execDetached(["omarchy-shell", "shell", "summon", "omni.settings", "{}"])
  }

  readonly property var guideSteps: [
    { title: "选模式", body: "打开设置" + (root.fixedCombo("omni_settings") ? "（" + root.fixedCombo("omni_settings") + "）" : "")
        + "，选一个和你习惯一样的模式：Windows、macOS 或 KDE。也可以在 Omarchy 菜单 Setup → 快捷键模式 里切换。" },
    { title: "记住三个固定快捷键", body: "下面三个键在所有模式里都一样：" },
    { title: "按应用自动切换", body: "每个模式自带平铺或浮动；在设置里添加应用规则，切到某个应用时自动换模式。" }
  ]

  // -------------------------------------------------------- data plumbing

  function open(payloadJson) {
    var payload = ({})
    try { payload = JSON.parse(payloadJson || "{}") } catch (e) { payload = ({}) }

    // 预览其它 Profile：{"mode":"windows"}。只接受裸 id，避免把额外参数
    // 塞进 CLI。
    var mode = typeof payload.mode === "string" ? payload.mode.trim().toLowerCase() : ""
    root.requestedMode = /^[a-z0-9][a-z0-9_-]*$/.test(mode) ? mode : ""
    root.guideShown = payload.guide === true

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
      "echo \"<<<OMNI_RC>>>$?\"; " +
      "echo '<<<OMNI_DOCTOR>>>'; \"$CLI\" doctor --json 2>/dev/null; exit 0",
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
    var doctorJson = ""
    var section = ""
    var lines = text.split("\n")
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i]
      if (line === root.statusMark) { section = "status"; continue }
      if (line === root.sheetMark) { section = "sheet"; continue }
      if (line === root.doctorMark) { section = "doctor"; continue }
      if (line.indexOf(root.rcMark) === 0) {
        sheetRc = parseInt(line.slice(root.rcMark.length), 10)
        continue
      }
      if (section === "status") statusJson += line
      else if (section === "sheet") sheetJson += line
      else if (section === "doctor") doctorJson += line + "\n"
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
        "读取快捷键失败（退出码 " + sheetRc + "）。请确认 Engine 与模式文件（profiles/*.json）完好。")
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
    root.doctorData = Takeovers.parseDoctor(doctorJson)
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

  // Native fullscreen overlay surface (focused monitor, scale-safe reveal, Overlay layer,
  // exclusive keyboard focus) — same as omarchy.emojis / omarchy.clipboard.
  OverlayWindow {
    id: panel
    shown: root.opened
    WlrLayershell.namespace: "omni-cheat-sheet"

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
      color: root.background
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
            if (root.guideShown) root.guideShown = false
            else root.dismiss()
            event.accepted = true
          } else if (event.key === Qt.Key_G) {
            root.guideShown = !root.guideShown
            event.accepted = true
          } else if (root.guideShown && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) {
            root.guideShown = false
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

            // Native ButtonGroup-style chip: bordered Button, selected = previewed mode.
            delegate: Button {
              id: previewPill
              required property var modelData
              readonly property bool engineActive: root.stateKnown
                && String(root.engineState.mode || "") === modelData.id

              iconText: Icons.mode(modelData.id)
              text: modelData.label
              bordered: true
              active: engineActive
              selected: root.displayMode === modelData.id
              foreground: root.foreground
              accent: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.body
              tooltipText: engineActive ? "Engine 当前生效模式" : ""
              onClicked: root.previewMode(previewPill.modelData.id)
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
            text: "快捷键速查表"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
          }

          Text {
            textFormat: Text.PlainText
            text: root.engineStatusText + " · 共 " + root.bindingCount + " 项"
            color: root.foreground
            opacity: 0.5
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }
        }

        // Native qs.Ui TextField (control fill/border state tokens, theme selection tint).
        TextField {
          id: searchInput
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(180)
          foreground: root.foreground
          accent: root.accent
          font.family: root.fontFamily
          placeholderText: "搜索 · /"
          selectByMouse: true
          Keys.onEscapePressed: function(event) {
            if (searchInput.text !== "") searchInput.text = ""
            else root.focusContent()
            event.accepted = true
          }
          onTextChanged: {
            root.filterText = text
            root.applyFilter()
            body.contentY = 0
          }
        }
      }

      PanelSeparator {
        id: headerRule
        anchors.top: header.bottom
        anchors.topMargin: root.blockGap
        anchors.left: parent.left
        anchors.leftMargin: card.contentLeftInset
        anchors.right: parent.right
        anchors.rightMargin: card.contentRightInset
        foreground: root.foreground
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

            delegate: Button {
              id: catPill
              required property var modelData

              text: modelData.label + "  " + modelData.count
              bordered: true
              selected: root.filterCategory === modelData.id
              foreground: root.foreground
              accent: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.body
              verticalPadding: Style.spacing.xs
              onClicked: root.selectCategory(catPill.modelData.id)
            }
          }
        }
      }

      Text {
        id: takeoverNote
        anchors.top: categoryBar.bottom
        anchors.topMargin: 0
        anchors.left: parent.left
        anchors.leftMargin: card.contentLeftInset
        anchors.right: parent.right
        anchors.rightMargin: card.contentRightInset
        height: root.takeoverNoteHeight
        visible: root.takeoverNoteShown
        textFormat: Text.PlainText
        text: root.takeover.hint
        color: Commons.Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
      }

      // ------------------------------------------------------------- body
      Flickable {
        id: body
        anchors.top: takeoverNote.bottom
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

              Item {
                id: groupHeader
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: root.groupHeaderHeight

                PanelSectionHeader {
                  anchors.left: parent.left
                  anchors.verticalCenter: parent.verticalCenter
                  text: group.modelData.label + "  ·  " + group.modelData.items.length
                  foreground: root.foreground
                  fontFamily: root.fontFamily
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

                    // Row state = Style hover-cursor / selected tokens (same as Button).
                    BorderSurface {
                      anchors.fill: parent
                      radius: root.cornerRadius
                      // Native menu selection: fg@0.08 fill, accent text, no border.
                      color: (bindingMouse.containsMouse || binding.rowLive) ? Util.alpha(root.foreground, 0.08) : "transparent"
                      borderSpec: Border.none()
                    }

                    Flow {
                      id: keyFlow
                      anchors.left: parent.left
                      anchors.verticalCenter: parent.verticalCenter
                      width: root.keyColumnWidth
                      spacing: Style.space(4)

                      Repeater {
                        model: SheetData.splitCombo(binding.modelData.key)

                        // Key cap: Omarchy has no keycap widget, so it is a BorderSurface
                        // painted with the shared control state tokens (normal / selected),
                        // i.e. it looks exactly like a bordered native Button chip.
                        delegate: BorderSurface {
                          id: keyCap
                          required property var modelData
                          readonly property bool capLive: root.modsActive
                            && SheetData.isModifierActive(String(keyCap.modelData), root.liveMods)

                          width: keyLabel.implicitWidth + Style.spacing.controlPaddingX * 2
                          height: Math.max(Style.space(21), Style.font.body + Style.spacing.controlPaddingY)
                          radius: Style.cornerRadius
                          // Square keycap = native bordered Button (1px fg@0.4, fg@0.04 fill, cornerRadius).
                          color: Style.normalFillFor(root.foreground, root.accent)
                          borderSpec: Border.controlSpec("normal", root.foreground, root.accent)

                          Text {
                            id: keyLabel
                            textFormat: Text.PlainText
                            anchors.centerIn: parent
                            text: SheetData.formatKeyCap(String(keyCap.modelData), root.displayMode)
                            color: (keyCap.capLive || binding.rowLive) ? root.accent : root.foreground
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.body
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
                      color: (bindingMouse.containsMouse || binding.rowLive) ? root.accent : root.foreground
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
                      font.pixelSize: Style.font.body
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
        anchors.top: takeoverNote.bottom
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
          }

          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(Style.space(460), placeholder.width)
            textFormat: Text.PlainText
            text: root.placeholderBody
            color: root.foreground
            opacity: 0.5
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
          }

          BorderSurface {
            visible: root.placeholderCommand !== ""
            anchors.horizontalCenter: parent.horizontalCenter
            width: commandLabel.implicitWidth + Style.spacing.controlPaddingX * 2
            height: Math.max(Style.space(22), Style.font.body + Style.spacing.controlPaddingY * 2)
            radius: Style.cornerRadius
            color: Style.normalFillFor(root.foreground, root.accent)
            borderSpec: Border.controlSpec("normal", root.foreground, root.accent)

            Text {
              id: commandLabel
              textFormat: Text.PlainText
              anchors.centerIn: parent
              text: root.placeholderCommand
              color: root.accent
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
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
          text: "Esc 关闭 · / 搜索 · Tab 切分类 · R 刷新 · G 上手指南 · 按住 Super/Alt/Ctrl/Shift 高亮关联键位"
          color: root.foreground
          opacity: 0.42
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
        }

        Text {
          textFormat: Text.PlainText
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          text: "OmniPal · " + root.displayMode
          color: root.foreground
          opacity: 0.32
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
        }
      }

      // ------------------------------------------------------- 上手指南
      // PopupCard 外观：popups 表面 + 2px accent 边框。覆盖在列表之上，Esc / Enter / 知道了 关闭。
      BorderSurface {
        id: guideCard
        visible: root.guideShown
        z: 10
        anchors.centerIn: parent
        width: Math.min(parent.width - Style.space(48), Style.space(520))
        height: guideCol.implicitHeight + Style.spacing.popupPadding * 2
        radius: root.cornerRadius
        color: Commons.Color.popups.background
        borderSpec: Border.localOrSurfaceSpec("popups", "border", Commons.Color.accent, Commons.Color.popups.border, Math.max(1, Style.space(2)))
        padding: Style.spacing.popupPadding

        MouseArea { anchors.fill: parent; onClicked: {} }

        Column {
          id: guideCol
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.spacing.popupPadding
          spacing: Style.space(12)

          Text {
            textFormat: Text.PlainText
            text: "上手指南"
            color: Commons.Color.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
          }

          Repeater {
            model: root.guideSteps

            delegate: Row {
              id: step
              required property var modelData
              required property int index
              width: guideCol.width
              spacing: Style.space(10)

              Text {
                id: stepNo
                textFormat: Text.PlainText
                text: String(step.index + 1)
                color: Commons.Color.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.subtitle
              }

              Column {
                width: step.width - stepNo.width - step.spacing
                spacing: Style.space(4)

                Text {
                  textFormat: Text.PlainText
                  text: step.modelData.title
                  color: Commons.Color.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.weight: Font.Medium
                }

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: step.modelData.body
                  color: Commons.Color.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  wrapMode: Text.Wrap
                }

                Repeater {
                  model: step.index === 1 ? root.fixedRows : []

                  delegate: Text {
                    required property var modelData
                    textFormat: Text.PlainText
                    text: modelData.combo + "　" + modelData.name
                    color: Commons.Color.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                  }
                }

                Text {
                  visible: step.index === 1 && root.fixedRows.length === 0
                  textFormat: Text.PlainText
                  text: "暂时读不到，可以在速查表的「OmniPal 固定入口」分组里查看。"
                  color: Commons.Color.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                }
              }
            }
          }

          Item {
            width: guideCol.width
            height: guideButtons.implicitHeight

            Text {
              anchors.left: parent.left
              anchors.right: guideButtons.left
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: "以后按 G，或在 Omarchy 菜单 Setup → 快捷键模式 → 上手指南 重新打开"
              color: Commons.Color.muted
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              wrapMode: Text.Wrap
            }

            Row {
              id: guideButtons
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(6)

              Button {
                text: "打开设置"
                bordered: true
                foreground: Commons.Color.foreground
                accent: Commons.Color.accent
                fontFamily: root.fontFamily
                fontSize: Style.font.body
                onClicked: root.openSettings()
              }

              Button {
                text: "知道了"
                bordered: true
                selected: true
                foreground: Commons.Color.foreground
                accent: Commons.Color.accent
                fontFamily: root.fontFamily
                fontSize: Style.font.body
                onClicked: root.guideShown = false
              }
            }
          }
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

  readonly property string placeholderBody: root.loading ? "正在向 Engine 读取当前模式。"
    : root.errorMessage !== "" ? root.errorMessage
    : root.groups.length > 0 ? ""
    : root.filterNoMatches ? "换一个搜索词，或点击「全部」分类胶囊重试。"
    : root.requestedMode !== "" ? "这个模式没有映射任何快捷键。"
    : "原生模式沿用 Omarchy 默认键位，没有任何覆盖。切换习惯模式后这里会自动列出对应快捷键。"

  readonly property string placeholderCommand: root.loading ? ""
    : root.errorCommand !== "" ? root.errorCommand
    : (root.requestedMode === "" && root.groups.length === 0 && root.rawRows.length === 0) ? "omni-profile switch windows" : ""
}
