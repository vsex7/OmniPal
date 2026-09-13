import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui

// OmniPal 任务视图 / 多窗口概览（omni.overview）
//
// 架构与约束铁律（Hard Stop H-2）：
// 1. 绝对不抓取像素截图（Zero Pixel Screenshots），完全基于 hyprctl clients -j 元数据构建。
// 2. 毫秒级展示所有打开的窗口卡片、所属工作区、应用类别与窗口标题。
// 3. 点击卡片或回车即执行 `hyprctl dispatch focuswindow address:...` 聚焦窗口。
// 4. 支持实时搜索过滤窗口，支持卡片右上角快捷关闭。
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  readonly property string pluginId: (root.manifest && root.manifest.id) || "omni.overview"

  property var rawWindows: []
  property var filteredWindows: []
  property int selectedIndex: 0
  property string filterText: ""

  // 样式令牌（对齐 Omarchy 菜单与表面）
  property color background: Color.menu.background
  property color foreground: Color.menu.text
  property color border: Color.menu.border
  property var borderSpec: Border.surfaceSpec("menu", "border", border, Math.max(1, Style.space(2)))
  property color scrim: Color.menu.scrim
  readonly property color glassColor: Util.alpha(Color.menu.background, 0.92)
  readonly property int cornerRadius: Style.cornerRadius

  function open(payloadJson) {
    root.opened = true
    root.filterText = ""
    root.selectedIndex = 0
    fetchClients()
    Qt.callLater(function() { searchInput.forceActiveFocus() })
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

  function fetchClients() {
    clientsProc.running = true
  }

  function activateWindow(addr) {
    if (!addr) return
    root.dismiss()
    dispatchProc.command = ["hyprctl", "dispatch", "focuswindow", "address:" + addr]
    dispatchProc.running = true
  }

  function closeWindow(addr) {
    if (!addr) return
    dispatchProc.command = ["hyprctl", "dispatch", "closewindow", "address:" + addr]
    dispatchProc.running = true
    // 延迟稍许刷新列表
    refreshTimer.restart()
  }

  Timer {
    id: refreshTimer
    interval: 80
    repeat: false
    onTriggered: root.fetchClients()
  }

  function updateFiltered() {
    var query = root.filterText.trim().toLowerCase()
    var out = []
    for (var i = 0; i < root.rawWindows.length; i++) {
      var w = root.rawWindows[i]
      if (!w || !w.mapped) continue
      var title = String(w.title || "").toLowerCase()
      var cls = String(w.class || "").toLowerCase()
      var initCls = String(w.initialClass || "").toLowerCase()
      if (query === "" || title.indexOf(query) !== -1 || cls.indexOf(query) !== -1 || initCls.indexOf(query) !== -1) {
        out.push(w)
      }
    }
    root.filteredWindows = out
    if (root.selectedIndex >= out.length) {
      root.selectedIndex = Math.max(0, out.length - 1)
    }
  }

  Process {
    id: clientsProc
    command: ["hyprctl", "clients", "-j"]
    running: false
    stdout: SplitParser {
      onRead: function(data) {
        try {
          var parsed = JSON.parse(data)
          if (Array.isArray(parsed)) {
            // 过滤有效窗口，并按焦点历史排序
            var valid = parsed.filter(function(item) {
              return item && item.mapped && item.title !== ""
            })
            valid.sort(function(a, b) {
              return (a.focusHistoryID || 0) - (b.focusHistoryID || 0)
            })
            root.rawWindows = valid
            root.updateFiltered()
          }
        } catch (e) {}
      }
    }
  }

  Process {
    id: dispatchProc
    command: ["true"]
    running: false
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omni-overview"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    // 背景半透明遮罩（点击空白处关闭）
    Rectangle {
      anchors.fill: parent
      color: root.scrim

      MouseArea {
        anchors.fill: parent
        onClicked: root.dismiss()
      }
    }

    // 主容器
    Item {
      anchors.fill: parent
      anchors.margins: Style.space(36)

      // 顶部搜索过滤栏
      Row {
        id: searchBar
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(Style.space(680), parent.width)
        height: Style.space(48)
        spacing: Style.space(12)

        BorderSurface {
          anchors.fill: parent
          radius: Style.cornerRadius
          color: root.glassColor
          borderSpec: root.borderSpec
          padding: Style.space(10)

          Row {
            anchors.fill: parent
            spacing: Style.space(10)

            Text {
              text: "🔍"
              font.pixelSize: Style.font.body
              color: root.foreground
              anchors.verticalCenter: parent.verticalCenter
            }

            TextInput {
              id: searchInput
              width: parent.width - Style.space(70)
              font.pixelSize: Style.font.body
              font.family: Style.font.family
              color: root.foreground
              anchors.verticalCenter: parent.verticalCenter
              selectByMouse: true
              activeFocusOnTab: true

              // 占位符提示
              Text {
                text: "搜索窗口标题或应用名称... (Esc 退出，↑↓←→ 选择，Enter 切换)"
                visible: searchInput.text === ""
                font.pixelSize: Style.font.body
                font.family: Style.font.family
                color: Util.alpha(root.foreground, 0.4)
                anchors.verticalCenter: parent.verticalCenter
              }

              onTextChanged: {
                root.filterText = text
                root.updateFiltered()
              }

              Keys.onEscapePressed: root.dismiss()

              Keys.onPressed: function(event) {
                var cols = Math.max(1, Math.floor(grid.width / (grid.cellWidth || 280)))
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                  if (root.filteredWindows.length > 0 && root.selectedIndex < root.filteredWindows.length) {
                    root.activateWindow(root.filteredWindows[root.selectedIndex].address)
                  }
                } else if (event.key === Qt.Key_Left) {
                  root.selectedIndex = Math.max(0, root.selectedIndex - 1)
                  event.accepted = true
                } else if (event.key === Qt.Key_Right) {
                  root.selectedIndex = Math.min(root.filteredWindows.length - 1, root.selectedIndex + 1)
                  event.accepted = true
                } else if (event.key === Qt.Key_Up) {
                  root.selectedIndex = Math.max(0, root.selectedIndex - cols)
                  event.accepted = true
                } else if (event.key === Qt.Key_Down) {
                  root.selectedIndex = Math.min(root.filteredWindows.length - 1, root.selectedIndex + cols)
                  event.accepted = true
                }
              }
            }

            // 清除按钮
            Text {
              visible: searchInput.text !== ""
              text: "✕"
              font.pixelSize: Style.font.caption
              color: Util.alpha(root.foreground, 0.6)
              anchors.verticalCenter: parent.verticalCenter

              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                  searchInput.text = ""
                  searchInput.forceActiveFocus()
                }
              }
            }
          }
        }
      }

      // 窗口网格卡片展示区
      Item {
        anchors.top: searchBar.bottom
        anchors.topMargin: Style.space(24)
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right

        // 空结果提示
        Text {
          visible: root.filteredWindows.length === 0
          text: root.filterText === "" ? "当前没有打开的窗口" : "未找到匹配的窗口"
          font.pixelSize: Style.font.heading
          color: Util.alpha(root.foreground, 0.5)
          anchors.centerIn: parent
        }

        GridView {
          id: grid
          anchors.fill: parent
          clip: true
          cellWidth: Math.max(Style.space(260), Math.floor(width / Math.max(1, Math.floor(width / Style.space(320)))))
          cellHeight: Style.space(160)
          model: root.filteredWindows

          delegate: Item {
            id: cardWrapper
            required property var modelData
            required property int index

            readonly property bool isSelected: root.selectedIndex === index
            width: grid.cellWidth
            height: grid.cellHeight

            Rectangle {
              id: cardRect
              anchors.fill: parent
              anchors.margins: Style.space(8)
              radius: Style.cornerRadius
              color: cardHover.containsMouse || isSelected
                ? Util.alpha(root.foreground, 0.12)
                : Util.alpha(root.foreground, 0.05)
              border.width: isSelected ? 2 : 1
              border.color: isSelected ? Color.accent : Util.alpha(root.foreground, 0.12)

              Column {
                anchors.fill: parent
                anchors.margins: Style.space(12)
                spacing: Style.space(8)

                // 顶栏：应用类名与工作区标签
                Row {
                  width: parent.width
                  spacing: Style.space(8)

                  // 应用标识
                  Rectangle {
                    width: Style.space(26)
                    height: Style.space(26)
                    radius: 4
                    color: Util.alpha(Color.accent, 0.2)
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                      text: (modelData.class && modelData.class.length > 0) ? modelData.class.charAt(0).toUpperCase() : "🗔"
                      font.pixelSize: 13
                      font.bold: true
                      color: Color.accent
                      anchors.centerIn: parent
                    }
                  }

                  Text {
                    text: modelData.class || "App"
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    color: root.foreground
                    elide: Text.ElideRight
                    width: parent.width - Style.space(100)
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  // 工作区标签
                  Rectangle {
                    width: wsTag.implicitWidth + 8
                    height: wsTag.implicitHeight + 4
                    radius: 3
                    color: Util.alpha(root.foreground, 0.1)
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                      id: wsTag
                      text: "WS " + ((modelData.workspace && modelData.workspace.id) || "1")
                      font.pixelSize: 9
                      color: Util.alpha(root.foreground, 0.8)
                      anchors.centerIn: parent
                    }
                  }

                  // 窗口关闭按钮
                  Rectangle {
                    width: Style.space(20)
                    height: Style.space(20)
                    radius: 3
                    color: closeHover.containsMouse ? "#bf616a" : "transparent"
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                      text: "✕"
                      font.pixelSize: 10
                      color: closeHover.containsMouse ? "#ffffff" : Util.alpha(root.foreground, 0.5)
                      anchors.centerIn: parent
                    }

                    MouseArea {
                      id: closeHover
                      anchors.fill: parent
                      hoverEnabled: true
                      cursorShape: Qt.PointingHandCursor
                      onClicked: root.closeWindow(modelData.address)
                    }
                  }
                }

                // 窗口标题展示
                Text {
                  width: parent.width
                  height: Style.space(48)
                  text: modelData.title || "Untitled Window"
                  font.pixelSize: Style.font.body
                  color: root.foreground
                  wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                  elide: Text.ElideRight
                  maximumLineCount: 2
                }

                // 底部几何信息（零截图设计）
                Row {
                  width: parent.width
                  spacing: Style.space(8)

                  Text {
                    text: "尺寸: " + (modelData.size ? (modelData.size[0] + "×" + modelData.size[1]) : "auto")
                    font.pixelSize: 10
                    font.family: "monospace"
                    color: Util.alpha(root.foreground, 0.5)
                  }

                  Text {
                    text: modelData.floating ? "[浮动]" : "[平铺]"
                    font.pixelSize: 10
                    color: modelData.floating ? "#d08770" : "#a3be8c"
                  }
                }
              }

              MouseArea {
                id: cardHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.activateWindow(modelData.address)
              }
            }
          }
        }
      }
    }
  }
}
