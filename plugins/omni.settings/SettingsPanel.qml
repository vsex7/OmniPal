import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui

// OmniPal 设置与配置面板（omni.settings）
//
// 提供直观的图形化交互：
// 1. 浏览与切换快捷键习惯模式（Windows 11 / macOS / Omarchy）
// 2. 查看当前引擎状态、生效按键数、运行 PID 与 tmpfs 缓存
// 3. 一键还原原生按键、呼出快捷键速查表
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  readonly property string pluginId: (root.manifest && root.manifest.id) || "omni.settings"

  property string statePath: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/state.json"
  property string currentMode: "omarchy"
  property string currentName: "Omarchy 原生模式"
  property int activeBindingsCount: 0
  property int enginePid: 0
  property string engineUpdatedAt: ""
  property string engineStatus: "native"
  property bool engineRunning: false

  // 模式元数据
  readonly property var modeItems: [
    {
      id: "windows",
      icon: "⊞",
      name: "Windows 11 习惯模式",
      desc: "Alt+F4 关闭窗口 · Win+方向键智能吸附 · Win+E 文件管理器 · Ctrl+Shift+Esc 任务管理器",
      count: 11,
      color: "#0078d4"
    },
    {
      id: "mac",
      icon: "◆",
      name: "macOS 习惯模式",
      desc: "Super+Q 退出程序 · Super+Space 聚焦搜索 · Super+Shift+3/4 截图 · Super+H 最小化",
      count: 9,
      color: "#a2aaad"
    },
    {
      id: "omarchy",
      icon: "⊡",
      name: "Omarchy 原生模式",
      desc: "纯粹的 Hyprland 原生平铺体验 · 无任何按键拦截与覆盖 · 极简高效",
      count: 0,
      color: "#a3be8c"
    }
  ]

  // 主题样式令牌（对齐 Omarchy 菜单设计）
  property color background: Color.menu.background
  property color foreground: Color.menu.text
  property color border: Color.menu.border
  property var borderSpec: Border.surfaceSpec("menu", "border", border, Math.max(1, Style.space(2)))
  property color scrim: Color.menu.scrim
  property color selectedBackground: Color.menu.selectedBackground
  property color selectedText: Color.menu.selectedText
  readonly property color glassColor: Util.alpha(Color.menu.background, 0.90)
  readonly property int cornerRadius: Style.cornerRadius

  readonly property int cardWidth: Math.min(Style.space(640), panel.width - Style.space(48))
  readonly property int cardHeight: Math.min(Style.space(560), panel.height - Style.space(48))

  function open(payloadJson) {
    root.opened = true
    stateFile.reload()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
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

  function switchMode(targetMode) {
    if (!targetMode) return
    switchProc.command = ["omni-profile", "switch", targetMode]
    switchProc.running = true
  }

  function restoreNative() {
    switchProc.command = ["omni-profile", "restore"]
    switchProc.running = true
  }

  function openCheatSheet() {
    root.dismiss()
    if (root.shell && typeof root.shell.summon === "function") {
      root.shell.summon("omni.cheat-sheet", "{}")
    } else {
      Quickshell.execDetached(["omarchy-shell", "shell", "summon", "omni.cheat-sheet", "{}"])
    }
  }

  function loadState(rawText) {
    if (!rawText || rawText.trim() === "") {
      root.engineRunning = false
      return
    }
    try {
      var d = JSON.parse(rawText)
      root.currentMode = d.mode || "omarchy"
      root.currentName = d.name || "Omarchy 原生模式"
      root.activeBindingsCount = d.active_bindings_count || 0
      root.enginePid = d.pid || 0
      root.engineUpdatedAt = d.updated_at || ""
      root.engineStatus = d.status || "native"
      root.engineRunning = true
    } catch (e) {
      root.engineRunning = false
    }
  }

  FileView {
    id: stateFile
    path: root.statePath
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.loadState(text())
    onLoadFailed: root.engineRunning = false
    onFileChanged: reload()
  }

  Process {
    id: switchProc
    command: ["omni-profile", "switch", "omarchy"]
    running: false
    onExited: stateFile.reload()
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omni-settings"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim

      MouseArea {
        anchors.fill: parent
        onClicked: root.dismiss()
      }
    }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: root.cardHeight
      radius: root.cornerRadius
      anchors.centerIn: parent
      color: root.glassColor
      borderSpec: root.borderSpec
      padding: Style.space(20)

      MouseArea {
        anchors.fill: parent
        onClicked: {} // 拦截点击穿透
      }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true

        Keys.onEscapePressed: root.dismiss()
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_1) root.switchMode("windows")
          else if (event.key === Qt.Key_2) root.switchMode("mac")
          else if (event.key === Qt.Key_3) root.switchMode("omarchy")
          else if (event.key === Qt.Key_R) root.restoreNative()
          else if (event.key === Qt.Key_S) root.openCheatSheet()
        }

        Column {
          anchors.fill: parent
          spacing: Style.space(16)

          // 标题栏
          Row {
            width: parent.width
            height: Style.space(32)

            Text {
              text: "OmniPal 控制中心"
              font.family: root.background ? Style.font.headingFamily : "sans-serif"
              font.pixelSize: Style.font.heading
              font.bold: true
              color: root.foreground
              anchors.verticalCenter: parent.verticalCenter
            }

            Rectangle {
              width: 1; height: 1
              Layout.fillWidth: true
            }

            // 右侧关闭按钮
            Rectangle {
              width: Style.space(28)
              height: Style.space(28)
              radius: 4
              color: closeHover.containsMouse ? Util.alpha(root.foreground, 0.12) : "transparent"
              anchors.verticalCenter: parent.verticalCenter
              anchors.right: parent.right

              Text {
                text: "✕"
                font.pixelSize: Style.font.body
                color: root.foreground
                anchors.centerIn: parent
              }

              MouseArea {
                id: closeHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.dismiss()
              }
            }
          }

          // 分隔线
          Rectangle {
            width: parent.width
            height: 1
            color: Util.alpha(root.foreground, 0.1)
          }

          // 模式卡片列表
          Text {
            text: "选择习惯按键模式（或按键盘数字键 1 / 2 / 3）："
            font.pixelSize: Style.font.caption
            color: Util.alpha(root.foreground, 0.7)
          }

          Column {
            width: parent.width
            spacing: Style.space(10)

            Repeater {
              model: root.modeItems

              delegate: Rectangle {
                id: modeRow
                required property var modelData
                required property int index

                readonly property bool isActive: root.currentMode === modelData.id
                width: parent.width
                height: Style.space(76)
                radius: Style.cornerRadius
                color: isActive
                  ? Util.alpha(modelData.color, 0.16)
                  : modeCardHover.containsMouse
                    ? Util.alpha(root.foreground, 0.08)
                    : Util.alpha(root.foreground, 0.03)

                border.width: isActive ? 2 : 1
                border.color: isActive ? modelData.color : Util.alpha(root.foreground, 0.12)

                Row {
                  anchors.fill: parent
                  anchors.margins: Style.space(12)
                  spacing: Style.space(14)

                  // 图标徽章
                  Rectangle {
                    width: Style.space(48)
                    height: Style.space(48)
                    radius: Style.cornerRadius
                    color: Util.alpha(modelData.color, 0.25)
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                      text: modelData.icon
                      font.pixelSize: 22
                      font.bold: true
                      color: modelData.color
                      anchors.centerIn: parent
                    }
                  }

                  // 文本与描述
                  Column {
                    width: parent.width - Style.space(170)
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(4)

                    Row {
                      spacing: Style.space(8)
                      Text {
                        text: (index + 1) + ". " + modelData.name
                        font.pixelSize: Style.font.body
                        font.bold: true
                        color: root.foreground
                      }
                      Rectangle {
                        visible: modeRow.isActive
                        width: activeTagText.implicitWidth + 10
                        height: activeTagText.implicitHeight + 4
                        radius: 3
                        color: modelData.color
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                          id: activeTagText
                          text: "当前生效"
                          font.pixelSize: 10
                          font.bold: true
                          color: "#ffffff"
                          anchors.centerIn: parent
                        }
                      }
                    }

                    Text {
                      text: modelData.desc
                      font.pixelSize: Style.font.caption
                      color: Util.alpha(root.foreground, 0.75)
                      elide: Text.ElideRight
                      width: parent.width
                    }
                  }

                  // 右侧动作按钮
                  Rectangle {
                    width: Style.space(80)
                    height: Style.space(32)
                    radius: Style.cornerRadius
                    anchors.verticalCenter: parent.verticalCenter
                    color: modeRow.isActive
                      ? "transparent"
                      : applyHover.containsMouse
                        ? modelData.color
                        : Util.alpha(modelData.color, 0.2)
                    border.width: modeRow.isActive ? 0 : 1
                    border.color: modelData.color

                    Text {
                      text: modeRow.isActive ? "已激活" : "应用"
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      color: modeRow.isActive
                        ? modelData.color
                        : applyHover.containsMouse ? "#ffffff" : modelData.color
                      anchors.centerIn: parent
                    }

                    MouseArea {
                      id: applyHover
                      anchors.fill: parent
                      hoverEnabled: true
                      cursorShape: Qt.PointingHandCursor
                      onClicked: root.switchMode(modelData.id)
                    }
                  }
                }

                MouseArea {
                  id: modeCardHover
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.switchMode(modelData.id)
                }
              }
            }
          }

          // 引擎状态指示区
          Rectangle {
            width: parent.width
            height: Style.space(48)
            radius: Style.cornerRadius
            color: Util.alpha(root.foreground, 0.04)
            border.width: 1
            border.color: Util.alpha(root.foreground, 0.08)

            Row {
              anchors.fill: parent
              anchors.margins: Style.space(12)
              spacing: Style.space(12)

              Rectangle {
                width: 8; height: 8; radius: 4
                color: root.engineRunning ? "#a3be8c" : "#bf616a"
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                text: root.engineRunning
                  ? ("Engine PID: " + root.enginePid + " · 当前覆盖: " + root.activeBindingsCount + " 组快捷键 · 毫秒级内存生效")
                  : "Engine 未检测到运行 · 执行 omni-profile daemon 启动常驻"
                font.pixelSize: Style.font.caption
                color: Util.alpha(root.foreground, 0.8)
                anchors.verticalCenter: parent.verticalCenter
              }
            }
          }

          // 底部快捷动作按钮
          Row {
            width: parent.width
            spacing: Style.space(12)

            // 速查表按钮
            Rectangle {
              width: (parent.width - Style.space(12)) / 2
              height: Style.space(38)
              radius: Style.cornerRadius
              color: sheetBtnHover.containsMouse ? Util.alpha(root.foreground, 0.12) : Util.alpha(root.foreground, 0.06)
              border.width: 1
              border.color: Util.alpha(root.foreground, 0.15)

              Row {
                anchors.centerIn: parent
                spacing: Style.space(6)
                Text {
                  text: "📖 快捷键速查表 (S)"
                  font.pixelSize: Style.font.body
                  color: root.foreground
                }
              }

              MouseArea {
                id: sheetBtnHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.openCheatSheet()
              }
            }

            // 还原原生按钮
            Rectangle {
              width: (parent.width - Style.space(12)) / 2
              height: Style.space(38)
              radius: Style.cornerRadius
              color: restoreBtnHover.containsMouse ? Util.alpha("#bf616a", 0.2) : Util.alpha(root.foreground, 0.06)
              border.width: 1
              border.color: restoreBtnHover.containsMouse ? "#bf616a" : Util.alpha(root.foreground, 0.15)

              Row {
                anchors.centerIn: parent
                spacing: Style.space(6)
                Text {
                  text: "↺ 还原 Omarchy 原生 (R)"
                  font.pixelSize: Style.font.body
                  color: restoreBtnHover.containsMouse ? "#bf616a" : root.foreground
                }
              }

              MouseArea {
                id: restoreBtnHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.restoreNative()
              }
            }
          }
        }
      }
    }
  }
}
