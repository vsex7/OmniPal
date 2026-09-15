import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui
import "CheatSheetData.js" as SheetData

// OmniPal 快捷键 HUD（omni.cheat-sheet）
//
// 职责边界（AGENTS.md 铁律 1/2/3/5）：
//   • 只读展示：不注入绑定、不解绑、不写任何配置文件。
//   • 键位数据只来自 Engine：`omni-profile cheatsheet [mode] --json`（Engine 侧
//     再联合 schema/actions.json 与 profiles/*.json），当前模式与 Engine 状态来自
//     `omni-profile status --json`。本文件不存在任何键位列表副本。
//   • 一次 fetch.sh 调用同时拿两块数据：不轮询、不常驻。
//   • 拿不到数据时展示可操作的提示文本，不抛异常（优雅降级）。
Item {
  id: root

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

  function applyFilter() {
    var query = root.filterText.trim().toLowerCase()
    var filtered = root.rawRows
    if (query !== "") {
      filtered = root.rawRows.filter(function(item) {
        var k = String(item.key || "").toLowerCase()
        var n = String(item.name || "").toLowerCase()
        var d = String(item.description || "").toLowerCase()
        return k.indexOf(query) !== -1 || n.indexOf(query) !== -1 || d.indexOf(query) !== -1
      })
    }
    root.groups = SheetData.groupByCategory(filtered)
    root.bindingCount = filtered.length
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
  property var borderSpec: Border.surfaceSpec("menu", "border", border, Math.max(1, Style.space(2)))
  property color scrim: Color.menu.scrim
  property color accent: Color.menu.selectedText
  readonly property color glassColor: Util.alpha(Color.menu.background, 0.86)
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

  readonly property int chromeHeight: card.contentTopInset + card.contentBottomInset
    + titleHeight + blockGap * 3 + footerHeight + 1
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

  // -------------------------------------------------------- data plumbing

  // fetch.sh sits next to this file, so a plugin installed anywhere still
  // resolves its own helper without hardcoding a repo path.
  readonly property string fetchScript: {
    var url = String(Qt.resolvedUrl("fetch.sh"))
    return url.indexOf("file://") === 0 ? decodeURIComponent(url.slice(7)) : url
  }

  function open(payloadJson) {
    var payload = ({})
    try { payload = JSON.parse(payloadJson || "{}") } catch (e) { payload = ({}) }

    // 预览其它 Profile：{"mode":"windows"}。只接受裸 id，避免把额外参数
    // 塞进 CLI。
    var mode = typeof payload.mode === "string" ? payload.mode.trim().toLowerCase() : ""
    root.requestedMode = /^[a-z0-9][a-z0-9_-]*$/.test(mode) ? mode : ""

    root.filterText = ""
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
    if (!keyCatcher.activeFocus) focusRetry.restart()
  }

  function refresh() {
    root.errorKind = ""
    root.errorMessage = ""
    root.errorCommand = ""
    root.loading = true
    dataProc.command = ["bash", root.fetchScript, root.requestedMode]
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
      root.failWith("cli-failed", "bash " + root.fetchScript,
        "数据助手执行失败（退出码 " + exitCode + "）。")
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
    onTriggered: {
      keyCatcher.forceActiveFocus()
      if (keyCatcher.activeFocus || !root.opened) stop()
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
          var scrollFloor = 0
          var scrollCeil = Math.max(0, body.contentHeight - body.height)
          if (event.key === Qt.Key_Escape) {
            root.dismiss()
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

        Rectangle {
          id: modePill
          width: Math.min(modeLabel.implicitWidth + Style.space(18), Style.space(280))
          height: Style.space(24)
          radius: Math.min(root.cornerRadius, height / 2)
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          color: Util.alpha(root.accent, 0.12)
          border.color: Util.alpha(root.accent, 0.4)
          border.width: 1

          Text {
            id: modeLabel
            textFormat: Text.PlainText
            anchors.centerIn: parent
            width: modePill.width - Style.space(12)
            text: root.displayModeName
            color: root.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
          }
        }

        Column {
          id: titleColumn
          anchors.left: modePill.right
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
            text: root.engineStatusLabel + " · 共 " + root.bindingCount + " 项"
            color: root.foreground
            opacity: 0.5
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Row {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(10)

          Text {
            textFormat: Text.PlainText
            visible: root.requestedMode !== ""
            text: "预览模式"
            color: root.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            anchors.verticalCenter: parent.verticalCenter
          }

          BorderSurface {
            id: searchBox
            width: Style.space(160)
            height: Style.space(26)
            radius: height / 2
            color: Util.alpha(root.foreground, 0.06)
            borderSpec: root.borderSpec
            padding: Style.space(4)

            Row {
              anchors.fill: parent
              spacing: Style.space(6)

              Text {
                text: "🔍"
                font.pixelSize: 10
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
                  text: "搜索..."
                  visible: searchInput.text === ""
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  color: Util.alpha(root.foreground, 0.4)
                  anchors.verticalCenter: parent.verticalCenter
                }

                onTextChanged: {
                  root.filterText = text
                  root.applyFilter()
                }
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

      // ------------------------------------------------------------- body
      Flickable {
        id: body
        anchors.top: headerRule.bottom
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
                  radius: Math.min(2, width / 2)
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

                    width: group.width
                    height: root.rowHeight

                    Rectangle {
                      anchors.fill: parent
                      radius: Math.min(root.cornerRadius, Style.space(6))
                      color: bindingMouse.containsMouse ? Style.hoverFill : "transparent"
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
                          required property var modelData

                          width: keyLabel.implicitWidth + Style.space(12)
                          height: Math.max(Style.space(20), Style.font.body + Style.space(6))
                          radius: Math.min(root.cornerRadius, height / 2)
                          color: root.chipColor
                          border.color: root.hairline
                          border.width: 1

                          Text {
                            id: keyLabel
                            textFormat: Text.PlainText
                            anchors.centerIn: parent
                            text: modelData
                            color: root.foreground
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
                      textFormat: Text.PlainText
                      text: binding.modelData.name
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
                      textFormat: Text.PlainText
                      text: binding.modelData.description
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
        anchors.top: headerRule.bottom
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
          text: "Esc / 点击遮罩关闭 · R 刷新 · ↑↓ 滚动"
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
  readonly property string placeholderTitle: root.loading ? "正在读取…"
    : root.errorKind === "no-cli" ? "未找到 OmniPal 命令行工具"
    : root.errorKind === "cli-failed" ? "读取快捷键失败"
    : root.errorKind === "bad-json" ? "解析 Engine 输出失败"
    : root.errorKind === "mode-missing" ? "没有这个模式"
    : root.groups.length > 0 ? ""
    : root.requestedMode !== "" ? "模式 " + root.displayMode + " 没有可用定义"
    : "当前没有生效的快捷键覆盖"

  readonly property string placeholderBody: root.loading ? "正在向 Engine 读取当前 Profile。"
    : root.errorMessage !== "" ? root.errorMessage
    : root.groups.length > 0 ? ""
    : root.requestedMode !== "" ? "这个模式没有映射任何快捷键。"
    : "原生模式沿用 Omarchy 默认键位，没有任何覆盖。切换习惯模式后这里会自动列出对应快捷键。"

  readonly property string placeholderCommand: root.loading ? ""
    : root.errorCommand !== "" ? root.errorCommand
    : (root.requestedMode === "" && root.groups.length === 0) ? "omni-profile switch windows" : ""
}
