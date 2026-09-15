import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// OmniPal 任务视图与空间多工作区概览 (omni.overview)
//
// 架构规范：
// 1. 空间多工作区 16:9 画布平铺：直观还原物理桌面与窗口在屏幕上的相对空间排布。
// 2. 严守 Hard Stop H-5（零像素截图）：基于 Compositor 矢量元数据绘制，响应快、极轻量、绝无隐私泄露。
// 3. 键盘流极速调度：Tab/方向键轮转窗口、1-9 直达桌面、Shift+1-9 跨桌面瞬移、回车聚焦、Del 关闭、Esc 退出。
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  readonly property string pluginId: (root.manifest && root.manifest.id) || "omni.overview"

  property var rawWorkspaces: []
  property var rawClients: []
  property var rawMonitors: []
  property var activeWorkspaces: []
  property var allWindows: []
  property string focusedWindowAddress: ""
  property string selectedWindowAddress: ""
  property int activeWorkspaceId: 1
  property int navigationIndex: 0
  property string filterText: ""

  readonly property var monitorBox: {
    if (root.rawMonitors && root.rawMonitors.length > 0) {
      var m = root.rawMonitors[0]
      return { x: m.x || 0, y: m.y || 0, width: m.width || 1920, height: m.height || 1080 }
    }
    return { x: 0, y: 0, width: panel.width || 1920, height: panel.height || 1080 }
  }

  function open(payloadJson) {
    root.opened = true
    root.filterText = ""
    fetchData()
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

  function fetchData() {
    if (dataProc.running) dataProc.running = false
    dataProc.running = true
  }

  function activateWindow(addr) {
    if (!addr) return
    root.dismiss()
    dispatchProc.command = ["hyprctl", "dispatch", "hl.dsp.focus({ window = \"address:" + addr + "\" })"]
    dispatchProc.running = true
  }

  function switchToWorkspace(wsId) {
    if (!wsId) return
    root.dismiss()
    dispatchProc.command = ["hyprctl", "dispatch", "hl.dsp.focus({ workspace = \"" + String(wsId) + "\" })"]
    dispatchProc.running = true
  }

  function moveWindowToWorkspace(addr, wsId) {
    if (!addr || !wsId) return
    dispatchProc.command = ["hyprctl", "dispatch", "hl.dsp.window.move({ workspace = \"" + String(wsId) + "\", follow = false, window = \"address:" + addr + "\" })"]
    dispatchProc.running = true
    refreshTimer.restart()
  }

  function closeWindow(addr) {
    if (!addr) return
    dispatchProc.command = ["hyprctl", "dispatch", "hl.dsp.window.close({ window = \"address:" + addr + "\" })"]
    dispatchProc.running = true
    refreshTimer.restart()
  }

  function cycleWindow(delta) {
    if (!root.allWindows || root.allWindows.length === 0) return
    root.navigationIndex = Model.navigateIndex(root.navigationIndex, delta, root.allWindows.length)
    var target = root.allWindows[root.navigationIndex]
    if (target) {
      root.selectedWindowAddress = target.address
    }
  }

  Timer {
    id: refreshTimer
    interval: 90
    repeat: false
    onTriggered: root.fetchData()
  }

  Process {
    id: dataProc
    command: ["hyprctl", "-j", "--batch", "workspaces ; clients ; monitors ; activewindow"]
    running: false

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() {
        var rawText = text
        if (!rawText || rawText.trim() === "") return
        try {
          var parts = rawText.split("\n\n").map(function(s) { return s.trim() }).filter(function(s) { return s.length > 0 })
          if (parts.length >= 4) {
            root.rawWorkspaces = JSON.parse(parts[0])
            root.rawClients = JSON.parse(parts[1])
            root.rawMonitors = JSON.parse(parts[2])
            var aw = JSON.parse(parts[3])
            if (aw && aw.address) {
              root.focusedWindowAddress = aw.address
              if (aw.workspace && aw.workspace.id) {
                root.activeWorkspaceId = aw.workspace.id
              }
            }
            root.refreshWorkspaces()
          }
        } catch (e) {}
      }
    }
  }

  function refreshWorkspaces() {
    var wsMap = {}
    var list = []
    var allWins = []

    // 0. 解析显示器映射表
    var monMap = {}
    for (var m = 0; m < root.rawMonitors.length; m++) {
      var mon = root.rawMonitors[m]
      if (mon && mon.name) {
        monMap[mon.name] = { x: mon.x || 0, y: mon.y || 0, width: mon.width || 1920, height: mon.height || 1080 }
      }
    }

    // 1. 收集已存在的所有工作区
    for (var i = 0; i < root.rawWorkspaces.length; i++) {
      var ws = root.rawWorkspaces[i]
      if (ws && ws.id > 0) {
        var wsMon = (ws.monitor && monMap[ws.monitor]) ? monMap[ws.monitor] : root.monitorBox
        wsMap[ws.id] = { id: ws.id, name: ws.name || String(ws.id), monitorBox: wsMon, windows: [] }
      }
    }

    // 2. 保证当前活动工作区必定存在
    if (!wsMap[root.activeWorkspaceId] && root.activeWorkspaceId > 0) {
      wsMap[root.activeWorkspaceId] = { id: root.activeWorkspaceId, name: String(root.activeWorkspaceId), monitorBox: root.monitorBox, windows: [] }
    }

    // 3. 将窗口分配至各自工作区
    var query = root.filterText.trim().toLowerCase()
    for (var j = 0; j < root.rawClients.length; j++) {
      var c = root.rawClients[j]
      if (c && c.mapped && c.workspace && c.workspace.id > 0) {
        var wTitle = String(c.title || "").toLowerCase()
        var wClass = String(c.class || "").toLowerCase()
        if (query !== "" && wTitle.indexOf(query) === -1 && wClass.indexOf(query) === -1) {
          continue
        }

        var tId = c.workspace.id
        if (!wsMap[tId]) {
          wsMap[tId] = { id: tId, name: String(tId), monitorBox: root.monitorBox, windows: [] }
        }
        wsMap[tId].windows.push(c)
        allWins.push(c)
      }
    }

    // 4. 按工作区 ID 排序
    var sortedIds = Object.keys(wsMap).map(Number).sort(function(a, b) { return a - b })
    var maxId = 0
    for (var k = 0; k < sortedIds.length; k++) {
      var sid = sortedIds[k]
      list.push(wsMap[sid])
      if (sid > maxId) maxId = sid
    }

    // 5. 若未在搜索过滤状态且工作区编号小于 9，提供新建桌面插槽 (+)
    if (maxId < 9 && query === "") {
      list.push({
        id: maxId + 1,
        name: String(maxId + 1),
        monitorBox: root.monitorBox,
        windows: [],
        isNewSlot: true
      })
    }

    root.activeWorkspaces = list
    root.allWindows = allWins

    // 同步当前选中的活动窗口
    if (root.selectedWindowAddress === "" || !allWins.some(function(w) { return w.address === root.selectedWindowAddress })) {
      root.selectedWindowAddress = root.focusedWindowAddress || (allWins.length > 0 ? allWins[0].address : "")
    }
  }

  Process {
    id: dispatchProc
    command: ["true"]
    running: false
  }

  IpcHandler {
    target: "omni.overview"
    function open(): void { root.open("{}") }
    function close(): void { root.dismiss() }
    function toggle(): void { root.toggle() }
    function next(): void { root.cycleWindow(1) }
    function prev(): void { root.cycleWindow(-1) }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omni-overview"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    // 背景暗色遮罩（点击空白关闭）
    Rectangle {
      anchors.fill: parent
      color: Util.alpha(Color.menu.scrim || "#000000", 0.65)
      opacity: root.opened ? 1.0 : 0.0
      Behavior on opacity { NumberAnimation { duration: 120 } }

      MouseArea {
        anchors.fill: parent
        onClicked: root.dismiss()
      }
    }

    // 主容器：带平滑入场微缩放与透明度渐变
    Item {
      id: mainContainer
      anchors.fill: parent
      opacity: root.opened ? 1.0 : 0.0
      scale: root.opened ? 1.0 : 0.98
      Behavior on opacity { NumberAnimation { duration: 140; easing.type: Easing.OutQuad } }
      Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutQuad } }

      // 全局键盘导航捕获器
      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Escape) {
            root.dismiss()
            event.accepted = true
          } else if (event.key === Qt.Key_Tab) {
            var isShift = (event.modifiers & Qt.ShiftModifier) !== 0
            root.cycleWindow(isShift ? -1 : 1)
            event.accepted = true
          } else if (event.key === Qt.Key_Right || event.key === Qt.Key_Down) {
            root.cycleWindow(1)
            event.accepted = true
          } else if (event.key === Qt.Key_Left || event.key === Qt.Key_Up) {
            root.cycleWindow(-1)
            event.accepted = true
          } else if (event.key >= Qt.Key_1 && event.key <= Qt.Key_9) {
            var num = event.key - Qt.Key_0
            if ((event.modifiers & Qt.ShiftModifier) !== 0) {
              if (root.selectedWindowAddress !== "") {
                root.moveWindowToWorkspace(root.selectedWindowAddress, num)
                event.accepted = true
                return
              }
            } else {
              root.switchToWorkspace(num)
              event.accepted = true
              return
            }
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
            if (root.selectedWindowAddress !== "") {
              root.activateWindow(root.selectedWindowAddress)
            } else {
              root.switchToWorkspace(root.activeWorkspaceId)
            }
            event.accepted = true
          } else if (event.key === Qt.Key_Delete || event.key === Qt.Key_Backspace) {
            if (root.selectedWindowAddress !== "") {
              root.closeWindow(root.selectedWindowAddress)
              event.accepted = true
            }
          } else if (event.key === Qt.Key_Slash) {
            searchInput.forceActiveFocus()
            event.accepted = true
          } else if (event.text && event.text.length > 0 && event.key !== Qt.Key_Space && event.key !== Qt.Key_Tab && event.key !== Qt.Key_Escape) {
            searchInput.forceActiveFocus()
            searchInput.text += event.text
            event.accepted = true
          }
        }
      }

      // 顶部标头栏与快捷提示
      Item {
        id: headerBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Style.space(20)
        height: Style.space(36)
        z: 20

        // 左侧主标头徽章
        Rectangle {
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          height: Style.space(32)
          implicitWidth: headerText.implicitWidth + Style.space(24)
          radius: Style.cornerRadius
          color: Qt.rgba(0.08, 0.10, 0.13, 0.85)
          border.color: Util.alpha(Color.accent || "#88c0d0", 0.4)
          border.width: 1

          Row {
            id: headerRow
            anchors.centerIn: parent
            spacing: Style.space(8)

            Text {
              text: "🖥️"
              font.pixelSize: Style.font.body
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              id: headerText
              text: "任务视图 · 空间多工作区概览"
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              color: "#ffffff"
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }

        // 中间快捷操作提示胶囊
        Rectangle {
          anchors.centerIn: parent
          height: Style.space(32)
          implicitWidth: hintText.implicitWidth + Style.space(24)
          radius: Style.cornerRadius
          color: Qt.rgba(0.08, 0.10, 0.13, 0.70)
          border.color: Qt.rgba(1, 1, 1, 0.15)
          border.width: 1

          Text {
            id: hintText
            anchors.centerIn: parent
            text: "Tab: 轮转 · 1–9: 切换桌面 · Shift+1–9: 移至桌面 · 回车: 聚焦 · Del: 关窗 · Esc: 退出"
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            color: Util.alpha(Color.foreground, 0.8)
          }
        }

        // 右侧极速过滤搜索框
        Rectangle {
          id: searchBox
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          height: Style.space(32)
          width: searchInput.activeFocus || searchInput.text !== "" ? Style.space(240) : Style.space(130)
          radius: Style.cornerRadius
          color: Qt.rgba(0.08, 0.10, 0.13, 0.85)
          border.color: searchInput.activeFocus ? (Color.accent || "#88c0d0") : Qt.rgba(1, 1, 1, 0.15)
          border.width: 1

          Behavior on width { NumberAnimation { duration: 120 } }

          Row {
            anchors.fill: parent
            anchors.leftMargin: Style.space(8)
            anchors.rightMargin: Style.space(8)
            spacing: Style.space(6)

            Text {
              text: "🔍"
              font.pixelSize: Style.font.caption
              color: Util.alpha(Color.foreground, 0.6)
              anchors.verticalCenter: parent.verticalCenter
            }

            TextInput {
              id: searchInput
              width: parent.width - Style.space(32)
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              color: Color.foreground
              anchors.verticalCenter: parent.verticalCenter
              selectByMouse: true

              Text {
                visible: searchInput.text === "" && !searchInput.activeFocus
                text: "按 / 或键入搜索..."
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                color: Util.alpha(Color.foreground, 0.4)
                anchors.verticalCenter: parent.verticalCenter
              }

              onTextChanged: {
                root.filterText = text
                root.refreshWorkspaces()
              }

              Keys.onEscapePressed: {
                if (text !== "") {
                  text = ""
                } else {
                  keyCatcher.forceActiveFocus()
                }
              }

              Keys.onReturnPressed: {
                if (root.allWindows && root.allWindows.length > 0) {
                  root.activateWindow(root.selectedWindowAddress || root.allWindows[0].address)
                }
              }
            }

            // 清空搜索图标
            Text {
              visible: searchInput.text !== ""
              text: "✕"
              font.pixelSize: 10
              color: Util.alpha(Color.foreground, 0.5)
              anchors.verticalCenter: parent.verticalCenter

              MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                  searchInput.text = ""
                  keyCatcher.forceActiveFocus()
                }
              }
            }
          }
        }
      }

      // 核心区域：16:9 空间多工作区画布网格
      Item {
        id: canvasArea
        anchors.top: headerBar.bottom
        anchors.bottom: bottomBar.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Style.space(24)

        readonly property var gridCalc: Model.calculateGrid(
          Math.max(1, root.activeWorkspaces.length),
          canvasArea.width,
          canvasArea.height,
          { gap: Style.space(24), padding: Style.space(16), aspectRatio: 16.0 / 9.0 }
        )

        Repeater {
          model: root.activeWorkspaces

          delegate: WorkspaceCard {
            id: cardItem
            required property var modelData
            required property int index

            readonly property var cardGeom: {
              if (canvasArea.gridCalc && canvasArea.gridCalc.cards && canvasArea.gridCalc.cards[index]) {
                return canvasArea.gridCalc.cards[index]
              }
              return { x: 50 + index * 240, y: 50, width: 320, height: 180 }
            }

            x: cardGeom.x
            y: cardGeom.y
            width: cardGeom.width
            height: cardGeom.height

            workspaceData: modelData
            windowsList: modelData.windows || []
            monitorBox: modelData.monitorBox || root.monitorBox
            isActiveWorkspace: modelData.id === root.activeWorkspaceId
            focusedAddress: root.focusedWindowAddress
            selectedAddress: root.selectedWindowAddress

            onWorkspaceClicked: function(wsId) {
              root.switchToWorkspace(wsId)
            }

            onWindowClicked: function(w) {
              if (w && w.address) {
                root.activateWindow(w.address)
              }
            }

            onWindowCloseRequested: function(w) {
              if (w && w.address) {
                root.closeWindow(w.address)
              }
            }
          }
        }
      }

      // 底部状态统计栏
      Item {
        id: bottomBar
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Style.space(16)
        height: Style.space(24)

        Row {
          anchors.centerIn: parent
          spacing: Style.space(16)

          Text {
            text: "活跃桌面: " + root.activeWorkspaces.length
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            color: Util.alpha(Color.foreground, 0.5)
          }

          Text {
            text: "·"
            font.pixelSize: Style.font.caption
            color: Util.alpha(Color.foreground, 0.3)
          }

          Text {
            text: "打开窗口: " + root.allWindows.length
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            color: Util.alpha(Color.foreground, 0.5)
          }

          Text {
            text: "·"
            font.pixelSize: Style.font.caption
            color: Util.alpha(Color.foreground, 0.3)
          }

          Text {
            text: "模式: Windows 11 / 空间概览"
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            color: Util.alpha(Color.foreground, 0.4)
          }
        }
      }
    }
  }
}
