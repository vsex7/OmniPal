pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "Safety.js" as Safety

// OmniPal Overview - GTA V 战术武器轮盘多任务视界 (终极精细打磨版)
Item {
  id: root

  // ---- Theme ----------------------------------------------------------------
  // Native first: qs.Commons Color/Style + qs.Ui widgets wherever Omarchy has one.
  // `theme` (OmniTheme.qml) resolves the remaining custom-surface roles straight from
  // qs.Commons; the colors.toml palette below only feeds the extended status hues.
  readonly property OmniTheme theme: OmniTheme {}

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  property var allClients: []
  property var workspaces: []
  property int activeWorkspaceId: 1
  property int selectedIndex: 0
  property string activeAddress: ""
  property int monitorWidth: 2560
  property int monitorHeight: 1440
  property string searchQuery: ""

  // 拖拽至黑洞状态追踪
  property bool isDraggingCard: false
  property string draggedAddress: ""
  property var draggedSlotData: null
  property real dragGlobalX: 0
  property real dragGlobalY: 0

  readonly property string pluginId: (root.manifest && root.manifest.id) || "omni.overview"

  readonly property var fetchCommand: [
    "bash", "-c",
    "echo '<<<ACTIVE>>>'; hyprctl -j activewindow 2>/dev/null || echo '{}'; echo '<<<CLIENTS>>>'; hyprctl -j clients 2>/dev/null || echo '[]'; echo '<<<WORKSPACES>>>'; hyprctl -j workspaces 2>/dev/null || echo '[]'; echo '<<<MONITORS>>>'; hyprctl -j monitors 2>/dev/null || echo '[]'"
  ]

  // 目标转移工作区
  readonly property int targetTransferWorkspaceId: {
    if (root.activeWorkspaceId === 1) return 2
    return (root.activeWorkspaceId === 2) ? 1 : (root.activeWorkspaceId + 1)
  }

  // 当前画布上可见的窗口列表：仅限当前活动工作区真实窗口
  readonly property var visibleWindows: {
    if (!root.allClients || root.allClients.length === 0) return []
    var curWsList = []
    for (var i = 0; i < root.allClients.length; i++) {
      if (root.allClients[i].workspaceId === root.activeWorkspaceId) {
        curWsList.push(root.allClients[i])
      }
    }
    return curWsList
  }

  // 模糊搜索过滤
  readonly property var filteredWindows: Model.filterWindows(root.visibleWindows, root.searchQuery)

  // GTA V 经典武器轮盘极坐标几何排布
  readonly property var layoutWindows: Model.calculateGtaWheelLayout(
    root.filteredWindows,
    panel ? panel.width : 2560,
    panel ? panel.height : 1440
  )

  readonly property var currentSelectedWin: (root.layoutWindows && root.selectedIndex >= 0 && root.selectedIndex < root.layoutWindows.length) ? root.layoutWindows[root.selectedIndex] : null

  onSelectedIndexChanged: {
    if (gtaCanvas) gtaCanvas.requestPaint()
  }

  onLayoutWindowsChanged: {
    if (root.selectedIndex >= root.layoutWindows.length || root.selectedIndex < 0) {
      root.selectedIndex = 0
    }
    if (gtaCanvas) gtaCanvas.requestPaint()
  }

  Process {
    id: dataProc
    command: root.fetchCommand
    stdout: StdioCollector {
      id: outCollector
      waitForEnd: true
      onStreamFinished: function() {
        var str = outCollector.text ? outCollector.text : ""
        var parsed = Model.parseFetchOutput(str)
        root.allClients = parsed.clients || []
        root.activeAddress = parsed.activeAddress || ""
        root.activeWorkspaceId = parsed.activeWorkspaceId || 1
        root.workspaces = parsed.workspaces || []
        if (parsed.monitorWidth > 0 && parsed.monitorHeight > 0) {
          root.monitorWidth = parsed.monitorWidth
          root.monitorHeight = parsed.monitorHeight
        }

        if (root.selectedIndex >= root.layoutWindows.length || root.selectedIndex < 0) {
          root.selectedIndex = 0
        }
        if (gtaCanvas) gtaCanvas.requestPaint()
      }
    }
  }

  function refresh() {
    dataProc.running = false
    dataProc.command = root.fetchCommand
    dataProc.running = true
  }

  function open(payloadJson) {
    root.opened = true
    root.searchQuery = ""
    root.isDraggingCard = false
    root.draggedAddress = ""
    root.draggedSlotData = null
    root.refresh()
    Qt.callLater(function() {
      if (keyCatcher) keyCatcher.forceActiveFocus()
      if (gtaCanvas) gtaCanvas.requestPaint()
    })
  }

  function dismiss() {
    root.opened = false
    root.searchQuery = ""
    root.disarmClose()
    root.isDraggingCard = false
    if (root.shell && typeof root.shell.hide === "function") {
      root.shell.hide(root.pluginId)
    }
  }

  function close() {
    root.opened = false
    root.searchQuery = ""
    root.isDraggingCard = false
  }

  function toggle() {
    if (root.opened) {
      root.dismiss()
    } else {
      root.open("{}")
    }
  }

  function focusWindow(address) {
    if (address) {
      var addrStr = (address.indexOf("address:") === 0) ? address : ("address:" + address)
      var luaCmd = "hl.dsp.focus({ window = \"" + addrStr + "\" })"
      Quickshell.execDetached(["hyprctl", "dispatch", luaCmd])
      Quickshell.execDetached(["hyprctl", "dispatch", "focuswindow", addrStr])
    }
    root.dismiss()
  }

  // ---- close confirmation: no undo, so arm first, close on second press within Safety.CONFIRM_MS
  property string closeArmedAddress: ""

  function requestClose(address) {
    if (!address) return
    if (Safety.isArmed(root.closeArmedAddress, address)) {
      root.disarmClose()
      root.closeWindow(address)
    } else {
      root.closeArmedAddress = address
      closeArmTimer.restart()
    }
  }

  function disarmClose() {
    root.closeArmedAddress = ""
    closeArmTimer.stop()
  }

  Timer {
    id: closeArmTimer
    interval: Safety.CONFIRM_MS
    onTriggered: root.closeArmedAddress = ""
  }

  function closeWindow(address) {
    if (!address) return
    var addrStr = (address.indexOf("address:") === 0) ? address : ("address:" + address)
    var luaCmd = "hl.dsp.window.close({ window = \"" + addrStr + "\" })"
    Quickshell.execDetached(["hyprctl", "dispatch", luaCmd])
    Quickshell.execDetached(["hyprctl", "dispatch", "closewindow", addrStr])
    refreshTimer.restart()
  }

  function moveWindowToWorkspace(address, targetWs) {
    if (!address) return
    var addrStr = (address.indexOf("address:") === 0) ? address : ("address:" + address)
    var wsStr = String(targetWs)
    var dspCmd = "hl.dsp.window.move({ window = \"" + addrStr + "\", workspace = \"" + wsStr + "\", silent = true })"
    var evalCmd = "return hl.dispatch(hl.dsp.window.move({ window = \"" + addrStr + "\", workspace = \"" + wsStr + "\", silent = true }))"
    Quickshell.execDetached(["hyprctl", "dispatch", dspCmd])
    Quickshell.execDetached(["hyprctl", "eval", evalCmd])
    Quickshell.execDetached(["hyprctl", "dispatch", "movetoworkspacesilent", wsStr + "," + addrStr])

    if (portalHole) {
      portalHole.triggerAbsorption()
    }
    refreshTimer.restart()
  }

  Timer {
    id: refreshTimer
    interval: 120
    repeat: false
    onTriggered: {
      if (root.opened) {
        root.refresh()
      }
    }
  }

  IpcHandler {
    target: "omni.overview"
    function toggle(): void { root.toggle() }
    function open(): void { root.open("{}") }
    function close(): void { root.dismiss() }
    function refresh(): void { root.refresh() }
  }

  // Native qs.Ui OverlayWindow: focused-monitor fullscreen layer, Overlay layer,
  // exclusive keyboard focus while shown, scale-safe first frame.
  OverlayWindow {
    id: panel
    shown: root.opened
    WlrLayershell.namespace: "omni-overview"

    // 背景：GTA 5 经典子弹时间慢动作电影暗角与景深晕映
    Rectangle {
      id: backdrop
      anchors.fill: parent
      color: root.theme.scrim
      opacity: root.opened ? 1.0 : 0.0

      Behavior on opacity {
        NumberAnimation { duration: root.theme.duration(140); easing.type: Easing.OutCubic }
      }

      // ----------------------------------------------------
      // 全局统一鼠标手势控制器 (兼顾极速推选、点击聚焦、按住拖拽入黑洞)
      // ----------------------------------------------------
      MouseArea {
        id: flickArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: root.isDraggingCard ? Qt.ClosedHandCursor : (pressed ? Qt.ClosedHandCursor : Qt.PointingHandCursor)

        property real pressX: 0
        property real pressY: 0
        property bool isPressedDown: false
        property int pressSlotIdx: -1

        onPressed: function(mouse) {
          pressX = mouse.x
          pressY = mouse.y
          isPressedDown = true
          root.isDraggingCard = false

          var cx = width / 2
          var cy = height / 2
          var dx = mouse.x - cx
          var dy = mouse.y - cy
          var dist = Math.sqrt(dx * dx + dy * dy)

          if (dist <= 500 && root.layoutWindows.length > 0) {
            var angle = Math.atan2(dy, dx)
            var clickedIdx = (dist > 75) ? Model.getWedgeIndexFromAngle(angle, root.layoutWindows.length) : root.selectedIndex
            if (clickedIdx >= 0 && clickedIdx < root.layoutWindows.length) {
              pressSlotIdx = clickedIdx
              root.selectedIndex = clickedIdx
            } else {
              pressSlotIdx = -1
            }
          } else {
            pressSlotIdx = -1
          }
        }

        onPositionChanged: function(mouse) {
          var cx = width / 2
          var cy = height / 2

          // 1. 如果按下并发生位移（> 6px），并且按在有效窗口上，触发向黑洞拖拽
          if (isPressedDown && pressSlotIdx >= 0 && pressSlotIdx < root.layoutWindows.length) {
            var dxP = mouse.x - pressX
            var dyP = mouse.y - pressY
            if (!root.isDraggingCard && (Math.abs(dxP) > 6 || Math.abs(dyP) > 6)) {
              root.isDraggingCard = true
              var targetWin = root.layoutWindows[pressSlotIdx]
              root.draggedAddress = targetWin.address
              root.draggedSlotData = targetWin
              if (portalHole) portalHole.isDraggingAny = true
            }
          }

          // 2. 如果正在拖拽中，更新跟随坐标并检测黑洞引力场
          if (root.isDraggingCard) {
            root.dragGlobalX = mouse.x
            root.dragGlobalY = mouse.y
            if (portalHole) {
              var holePt = portalHole.mapFromItem(backdrop, mouse.x, mouse.y)
              portalHole.isDragOver = portalHole.checkContains(holePt)
            }
            return
          }

          // 3. 悬浮未按下时的推选手势 (GTA 5 武器推选感)
          var dx = mouse.x - cx
          var dy = mouse.y - cy
          var dist = Math.sqrt(dx * dx + dy * dy)

          if (dist >= 75 && dist <= 500 && root.layoutWindows.length > 0) {
            var angle = Math.atan2(dy, dx)
            var targetIdx = Model.getWedgeIndexFromAngle(angle, root.layoutWindows.length)
            if (targetIdx >= 0 && targetIdx < root.layoutWindows.length) {
              if (targetIdx !== root.selectedIndex) {
                root.selectedIndex = targetIdx
              }
            }
          }
        }

        onReleased: function(mouse) {
          var wasDragging = root.isDraggingCard
          var hadPressSlot = (pressSlotIdx >= 0 && pressSlotIdx < root.layoutWindows.length)
          var slotWin = hadPressSlot ? root.layoutWindows[pressSlotIdx] : null

          isPressedDown = false
          pressSlotIdx = -1

          // 如果是在拖拽状态下松手
          if (wasDragging) {
            var holePt = portalHole ? portalHole.mapFromItem(backdrop, mouse.x, mouse.y) : null
            if (portalHole && holePt && portalHole.checkContains(holePt)) {
              root.moveWindowToWorkspace(root.draggedAddress, root.targetTransferWorkspaceId)
            }
            root.isDraggingCard = false
            root.draggedAddress = ""
            root.draggedSlotData = null
            if (portalHole) {
              portalHole.isDraggingAny = false
              portalHole.isDragOver = false
            }
            return
          }

          // 如果未拖拽（轻点/单击），执行聚焦
          var cx = width / 2
          var cy = height / 2
          var dx = mouse.x - cx
          var dy = mouse.y - cy
          var dist = Math.sqrt(dx * dx + dy * dy)

          if (dist <= 500 && root.layoutWindows.length > 0) {
            var chosenWin = slotWin ? slotWin : root.layoutWindows[root.selectedIndex]
            if (chosenWin && chosenWin.address) {
              root.focusWindow(chosenWin.address)
              return
            }
          }

          // 点击在最外侧空白处退出
          root.dismiss()
        }
      }

      // 键盘事件捕获器
      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Escape) {
            event.accepted = true
            if (root.closeArmedAddress !== "") {
              root.disarmClose()
            } else if (root.searchQuery.length > 0) {
              root.searchQuery = ""
              root.selectedIndex = 0
            } else {
              root.dismiss()
            }
            return
          }

          var total = root.layoutWindows.length

          var alt = (event.modifiers & Qt.AltModifier) && !(event.modifiers & Qt.ControlModifier)

          // 槽位直达 Alt+1-9（与控制中心 1-9 统一；纯数字键进入搜索）
          if (alt && event.key >= Qt.Key_1 && event.key <= Qt.Key_9) {
            var targetIdx = event.key - Qt.Key_1
            event.accepted = true
            if (targetIdx < total && root.layoutWindows[targetIdx]) {
              root.focusWindow(root.layoutWindows[targetIdx].address)
            }
            return
          }

          // 轮盘步进：方向键 / Tab，或 Alt+h/j/k/l（纯字母永远进入搜索）
          if (event.key === Qt.Key_Tab || event.key === Qt.Key_Right || event.key === Qt.Key_Down || (alt && (event.key === Qt.Key_L || event.key === Qt.Key_J))) {
            event.accepted = true
            root.disarmClose()
            if (total > 0) {
              root.selectedIndex = (root.selectedIndex + 1) % total
            }
            return
          }

          if (event.key === Qt.Key_Backtab || event.key === Qt.Key_Left || event.key === Qt.Key_Up || (alt && (event.key === Qt.Key_H || event.key === Qt.Key_K))) {
            event.accepted = true
            root.disarmClose()
            if (total > 0) {
              root.selectedIndex = (root.selectedIndex - 1 + total) % total
            }
            return
          }

          // 回车：确认聚焦窗口
          if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            event.accepted = true
            if (root.currentSelectedWin && root.currentSelectedWin.address) {
              root.focusWindow(root.currentSelectedWin.address)
            }
            return
          }

          // 关闭当前窗口 (Delete / Alt+x)：首次按下提示“再按一次关闭”，~2s 内再按才关闭（无撤销）
          if (event.key === Qt.Key_Delete || (alt && event.key === Qt.Key_X)) {
            event.accepted = true
            if (root.currentSelectedWin && root.currentSelectedWin.address) {
              root.requestClose(root.currentSelectedWin.address)
            }
            return
          }

          // 发送到另一个工作区 (Alt+m 触发黑洞传送)
          if (alt && event.key === Qt.Key_M) {
            event.accepted = true
            if (root.currentSelectedWin && root.currentSelectedWin.address) {
              root.moveWindowToWorkspace(root.currentSelectedWin.address, root.targetTransferWorkspaceId)
            }
            return
          }

          // 退格：仅删除搜索字符（不再关闭窗口）
          if (event.key === Qt.Key_Backspace) {
            event.accepted = true
            if (root.searchQuery.length > 0) {
              root.searchQuery = root.searchQuery.substring(0, root.searchQuery.length - 1)
              root.selectedIndex = 0
            }
            return
          }

          // 其他 Alt 组合不进入搜索
          if (alt) return

          // 实时打字搜索
          if (event.text && event.text.length === 1 && !event.isAutoRepeat) {
            var ch = event.text
            if (ch.charCodeAt(0) >= 32 && ch.charCodeAt(0) <= 126) {
              event.accepted = true
              root.searchQuery += ch
              root.selectedIndex = 0
              return
            }
          }
        }
      }

      // ==========================================
      // 1. GTA 5 武器圆环轮盘本体 (Canvas 硬件加速渲染)
      // ==========================================
      Canvas {
        id: gtaCanvas
        anchors.fill: parent

        onPaint: {
          var ctx = getContext("2d")
          var w = width
          var h = height
          var cx = w / 2
          var cy = h / 2

          ctx.clearRect(0, 0, w, h)

          var wins = root.layoutWindows || []
          var total = wins.length

          // 1.1 绘制全底盘暗色战术深轨环
          ctx.beginPath()
          ctx.arc(cx, cy, 475, 0, 2 * Math.PI)
          ctx.arc(cx, cy, 195, 0, 2 * Math.PI, true)
          ctx.fillStyle = root.theme.scrim
          ctx.fill()

          // 1.2 绘制每个真实活动窗口扇区
          for (var i = 0; i < total; i++) {
            var item = wins[i]
            var isSel = (i === root.selectedIndex)
            var rIn = item.rInner || 215
            var rOut = isSel ? (item.rOuterHover || 480) : (item.rOuter || 450)

            // 扇区几何路径
            ctx.beginPath()
            ctx.arc(cx, cy, rOut, item.startAngle, item.endAngle, false)
            ctx.arc(cx, cy, rIn, item.endAngle, item.startAngle, true)
            ctx.closePath()

            if (isSel) {
              // 选中态：GTA 5 标志性战术亮橙高能渐变填充
                            ctx.fillStyle = root.theme.selectedFill
              ctx.fill()

              // Omarchy 选中态：2px accent 描边，无外发光
              ctx.lineWidth = Math.max(1, Style.space(2))
              ctx.strokeStyle = root.theme.accent
              ctx.stroke()

              // 扇区两端高光刻度线 (GTA 武器槽位精密咬合锁扣)
              var midA = item.midAngle
              ctx.lineWidth = 3
              ctx.strokeStyle = root.theme.accent
              var notchR1 = rIn + 10
              var notchR2 = rIn + 26
              ctx.beginPath()
              ctx.moveTo(cx + notchR1 * Math.cos(midA), cy + notchR1 * Math.sin(midA))
              ctx.lineTo(cx + notchR2 * Math.cos(midA), cy + notchR2 * Math.sin(midA))
              ctx.stroke()

            } else {
              // 普通活动窗口槽位：深灰黑哑光硬质机甲表面
                            ctx.fillStyle = root.theme.popupBg
              ctx.fill()

              ctx.lineWidth = Math.max(1, Style.normalBorderWidth)
              ctx.strokeStyle = root.theme.line
              ctx.stroke()
            }
          }

          // 1.3 绘制外圈 GTA 5 战术准星圆点与刻度 (Crosshair Reticles)
          if (total > 0) {
            ctx.strokeStyle = root.theme.lineStrong
            ctx.lineWidth = 1.2
            var reticleR = 490
            var angles = [0, Math.PI / 2, Math.PI, 3 * Math.PI / 2]
            for (var k = 0; k < angles.length; k++) {
              var a = angles[k]
              var rx = cx + reticleR * Math.cos(a)
              var ry = cy + reticleR * Math.sin(a)
              ctx.beginPath()
              ctx.arc(rx, ry, 4, 0, 2 * Math.PI)
              ctx.stroke()
              ctx.beginPath()
              ctx.moveTo(rx - 9, ry); ctx.lineTo(rx + 9, ry)
              ctx.moveTo(rx, ry - 9); ctx.lineTo(rx, ry + 9)
              ctx.stroke()
            }
          }
        }
      }

      // ==========================================
      // 2. GTA 5 中心英雄核心与状态属性面板 (Center Hero HUD)
      // ==========================================
      Item {
        id: centerHeroHub
        anchors.centerIn: parent
        width: 370
        height: 370

        // 中心深黑大圆盘底座 (带多层倒角金属轮廓)
        BorderSurface {
          anchors.fill: parent
          radius: Style.cornerRadius
          color: root.theme.bg
          // [menu] surface border when a window is picked, normal control border otherwise.
          borderSpec: root.currentSelectedWin
            ? Border.surfaceSpec("menu", "border", Commons.Color.menu.border, Math.max(1, Style.space(2)))
            : Border.controlSpec("normal", root.theme.text, root.theme.accent)


          // 核心内容排版
          Column {
            anchors.centerIn: parent
            width: parent.width - 56
            spacing: 8

            // 顶部横条：ACTIVE WINDOW: [APP_NAME]
            BorderSurface {
              height: Math.max(Style.space(24), Style.font.bodySmall + Style.spacing.controlPaddingY * 2)
              width: parent.width
              radius: Style.cornerRadius
              color: Util.alpha(root.theme.text, root.currentSelectedWin ? 0.08 : 0.04)
              borderSpec: Border.none()

              Text {
                anchors.centerIn: parent
                text: root.currentSelectedWin ? String(root.currentSelectedWin.activeName) : "no window"
                color: root.currentSelectedWin ? root.theme.accent : root.theme.textMuted
                font.pixelSize: Style.font.bodySmall
                font.family: Style.font.family
                elide: Text.ElideRight
                width: parent.width - 16
                horizontalAlignment: Text.AlignHCenter
              }
            }

            // 当前窗口大图标 (带环境光晕)
            Item {
              width: 56
              height: 56
              anchors.horizontalCenter: parent.horizontalCenter

              Rectangle {
                anchors.centerIn: parent
                width: 48
                height: 48
                radius: Style.cornerRadius
                color: root.currentSelectedWin ? Util.alpha(root.theme.accent, 0.12) : "transparent"
              }

              Image {
                anchors.centerIn: parent
                width: 44
                height: 44
                source: Quickshell.iconPath(root.currentSelectedWin ? (root.currentSelectedWin.iconName || "application-x-executable") : "omarchy", true)
                fillMode: Image.PreserveAspectFit
              }
            }

            // 真实窗口标题
            Text {
              text: (root.currentSelectedWin && (root.currentSelectedWin.title || root.currentSelectedWin.appName)) ? String(root.currentSelectedWin.title || root.currentSelectedWin.appName) : "no window selected"
              color: root.theme.textStrong
              font.pixelSize: Style.font.body
              font.family: Style.font.family
              horizontalAlignment: Text.AlignHCenter
              maximumLineCount: 2
              wrapMode: Text.Wrap
              elide: Text.ElideRight
              width: parent.width
              lineHeight: 1.15
            }

            // Terse key/value lines (lowercase, muted labels, single colour).
            Column {
              width: parent.width
              spacing: Style.spacing.xs

              Repeater {
                model: [
                  { k: "workspace", v: root.currentSelectedWin ? String(root.currentSelectedWin.workspaceId) : "-" },
                  { k: "layout", v: root.currentSelectedWin ? String(root.currentSelectedWin.layoutMode || "").toLowerCase() : "-" },
                  { k: "pid", v: root.currentSelectedWin ? (String(root.currentSelectedWin.pid) + " · " + (root.currentSelectedWin.resolutionStr || "")) : "-" }
                ]
                delegate: Row {
                  id: statLine
                  required property var modelData
                  spacing: Style.spacing.lg
                  Text { text: statLine.modelData.k; width: Style.space(64); color: root.theme.textMuted; font.pixelSize: Style.font.caption; font.family: Style.font.family }
                  Text { text: statLine.modelData.v; color: root.theme.text; font.pixelSize: Style.font.caption; font.family: Style.font.family }
                }
              }
            }
            }
          }
        }
      }

      // ==========================================
      // 3. 轮盘扇区内容覆盖层 (Wedge Slot Repeater)
      // ==========================================
      Repeater {
        model: root.layoutWindows

        delegate: OverviewCard {
          theme: root.theme
          required property var modelData
          required property int index

          windowData: modelData
          cardIndex: index
          isSelected: (root.selectedIndex === index)

          x: Math.round(modelData.anchorX - width / 2)
          y: Math.round(modelData.anchorY - height / 2)

          z: isSelected ? 100 : (10 + index)
        }
      }

      // ==========================================
      // 4. 轮盘右侧黑洞传送门 (Black Hole Event Horizon Portal)
      // ==========================================
      BlackHole {
        id: portalHole
        theme: root.theme
        visible: root.opened && backdrop.opacity > 0.05
        anchors.right: parent.right
        anchors.rightMargin: Math.max(70, (parent.width - 1020) / 4)
        anchors.verticalCenter: parent.verticalCenter
        targetWorkspaceId: root.targetTransferWorkspaceId
        isDraggingAny: root.isDraggingCard
        z: 150
      }

      // ==========================================
      // 5. 拖拽跟随幻影 (Drag Ghost Proxy)
      // ==========================================
      BorderSurface {
        id: dragGhost
        visible: root.isDraggingCard && root.draggedSlotData !== null
        width: 155
        height: 82
        radius: Style.cornerRadius
        color: root.theme.popupBg
        borderSpec: portalHole.isDragOver
          ? Border.flat(root.theme.accent, Math.max(1, Style.space(2)))
          : Border.surfaceSpec("popups", "border", Commons.Color.popups.border, Math.max(1, Style.space(2)))
        z: 999

        x: root.dragGlobalX - width / 2
        y: root.dragGlobalY - height / 2

        Row {
          anchors.centerIn: parent
          spacing: 10

          Image {
            width: 34
            height: 34
            source: Quickshell.iconPath(root.draggedSlotData ? (root.draggedSlotData.iconName || "application-x-executable") : "", true)
            fillMode: Image.PreserveAspectFit
            anchors.verticalCenter: parent.verticalCenter
          }

          Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
              text: root.draggedSlotData ? String(root.draggedSlotData.appName || "") : ""
              color: root.theme.textStrong
              font.pixelSize: Style.font.bodySmall
              font.family: Style.font.family
              elide: Text.ElideRight
              width: 85
            }
            Text {
              text: portalHole.isDragOver ? "release to move" : "dragging"
              color: portalHole.isDragOver ? root.theme.accent : root.theme.textMuted
              font.pixelSize: Style.font.caption
              font.family: Style.font.family
            }
          }
        }
      }

      // ==========================================
      // 6. 底部操作提示
      // ==========================================
      // Hint strip = [menu] surface card, same chrome as the overlay cards.
      BorderSurface {
        id: gtaFooter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Style.spacing.panelPadding + Style.gapsOut
        anchors.horizontalCenter: parent.horizontalCenter
        padding: Style.spacing.controlPaddingY
        leftPadding: Style.spacing.popupPadding
        rightPadding: Style.spacing.popupPadding
        width: footerRow.implicitWidth + contentLeftInset + contentRightInset
        height: footerRow.implicitHeight + contentTopInset + contentBottomInset
        radius: Style.cornerRadius
        color: root.theme.bg
        borderSpec: Border.surfaceSpec("menu", "border", Commons.Color.menu.border, Math.max(1, Style.space(2)))

        // Single muted caption line, one colour (designer gap list).
        Text {
          id: footerRow
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: root.closeArmedAddress !== ""
            ? (Safety.CLOSE_AGAIN_TEXT + " · esc 取消")
            : ("type to search · arrows select · enter focus · alt+1-9 jump · alt+m move to workspace " + root.targetTransferWorkspaceId + " · del close · esc exit")
          color: root.closeArmedAddress !== "" ? root.theme.danger : root.theme.textMuted
          font.pixelSize: Style.font.caption
          font.family: Style.font.family
        }
      }
    }
  }
