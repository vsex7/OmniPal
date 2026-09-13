import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui

// OmniPal 分屏视觉反馈 HUD（omni.snap-feedback）
//
// 特性：
// 1. 无焦点轻量浮层（WlrKeyboardFocus.None，不打断窗口焦点和键盘输入）
// 2. 接收 snap 区域指令（left, right, top, maximize, top-left, etc.）
// 3. 产生柔和平滑的高亮动画，并在 400ms 后自动淡出
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  property string zone: "left"
  readonly property string pluginId: (root.manifest && root.manifest.id) || "omni.snap-feedback"

  property color snapColor: Color.accent ? Color.accent : "#0078d4"

  function open(payloadJson) {
    var p = ({})
    try { p = JSON.parse(payloadJson || "{}") } catch(e) { p = ({}) }
    if (p.zone) root.zone = String(p.zone).toLowerCase()
    else root.zone = "left"

    root.opened = true
    fadeAnim.restart()
    dismissTimer.restart()
  }

  function close() {
    root.opened = false
  }

  function dismiss() {
    root.opened = false
    if (root.shell && typeof root.shell.hide === "function") root.shell.hide(root.pluginId)
  }

  // IPC 接口
  IpcHandler {
    target: "omni.snap-feedback"
    function snap(z: string): void {
      root.open(JSON.stringify({ zone: z }))
    }
  }

  // 监听 tmpfs snap 触发文件（提供极速文件级通知通道）
  property string snapEventPath: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/snap.json"
  FileView {
    id: snapFile
    path: root.snapEventPath
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.handleEvent(text())
    onFileChanged: reload()
  }

  function handleEvent(rawText) {
    if (!rawText) return
    try {
      var d = JSON.parse(rawText)
      if (d.zone) root.open(JSON.stringify(d))
    } catch(e) {}
  }

  Timer {
    id: dismissTimer
    interval: 450
    repeat: false
    onTriggered: root.dismiss()
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omni-snap-feedback"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    // 区域高亮卡片
    Rectangle {
      id: highlightRect

      readonly property int gap: Style.space(12)

      // 计算目标几何边界
      readonly property real targetX: {
        switch (root.zone) {
          case "right":
          case "top-right":
          case "bottom-right":
            return panel.width / 2 + gap / 2
          case "third-right":
            return panel.width * (2.0 / 3.0) + gap / 2
          case "two-thirds-right":
            return panel.width / 3.0 + gap / 2
          case "center":
            return panel.width * 0.2
          default:
            return gap
        }
      }

      readonly property real targetY: {
        switch (root.zone) {
          case "bottom-left":
          case "bottom-right":
            return panel.height / 2 + gap / 2
          case "center":
            return panel.height * 0.15
          default:
            return gap
        }
      }

      readonly property real targetW: {
        switch (root.zone) {
          case "top":
          case "maximize":
            return panel.width - gap * 2
          case "third-left":
          case "third-right":
            return panel.width / 3.0 - gap * 1.5
          case "two-thirds-left":
          case "two-thirds-right":
            return panel.width * (2.0 / 3.0) - gap * 1.5
          case "center":
            return panel.width * 0.6
          default:
            return panel.width / 2 - gap * 1.5
        }
      }

      readonly property real targetH: {
        switch (root.zone) {
          case "top-left":
          case "top-right":
          case "bottom-left":
          case "bottom-right":
            return panel.height / 2 - gap * 1.5
          case "center":
            return panel.height * 0.7
          default:
            return panel.height - gap * 2
        }
      }

      x: targetX
      y: targetY
      width: targetW
      height: targetH

      radius: Style.cornerRadius ? Style.cornerRadius * 1.5 : 12
      color: Util.alpha(root.snapColor, 0.16)
      border.width: 2
      border.color: Util.alpha(root.snapColor, 0.6)

      // 边缘微发光装饰
      Rectangle {
        anchors.fill: parent
        anchors.margins: -2
        radius: parent.radius + 2
        color: "transparent"
        border.width: 1
        border.color: Util.alpha(root.snapColor, 0.25)
      }

      // 居中半透明提示小图标
      Rectangle {
        width: Style.space(40)
        height: Style.space(40)
        radius: Style.space(20)
        color: Util.alpha(root.snapColor, 0.3)
        anchors.centerIn: parent

        Text {
          text: {
            switch(root.zone) {
              case "left": return "◧"
              case "right": return "◨"
              case "top":
              case "maximize": return "□"
              case "top-left": return "◤"
              case "top-right": return "◥"
              case "bottom-left": return "◣"
              case "bottom-right": return "◢"
              default: return "◧"
            }
          }
          font.pixelSize: 20
          color: "#ffffff"
          anchors.centerIn: parent
        }
      }

      SequentialAnimation {
        id: fadeAnim
        NumberAnimation {
          target: highlightRect
          property: "opacity"
          from: 0.0
          to: 1.0
          duration: 120
          easing.type: Easing.OutCubic
        }
        PauseAnimation { duration: 180 }
        NumberAnimation {
          target: highlightRect
          property: "opacity"
          from: 1.0
          to: 0.0
          duration: 150
          easing.type: Easing.InQuad
        }
      }
    }
  }
}
