import QtQuick
import "Tokens.js" as Tokens
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui

// OmniPal Overview - 黑洞传送门组件 (Black Hole Event Horizon)
// 支持将窗口拖拽至黑洞，将程序静默吸入并移动至指定工作区
Item {
  id: blackHoleRoot
  property var theme: Tokens.build(null, Tokens.fallback)

  property int targetWorkspaceId: 2
  property bool isDragOver: false
  property bool isDraggingAny: false

  signal windowDropped(string address, int targetWs)

  width: 280
  height: 280

  function checkContains(pointInHoleCoords) {
    var cx = width / 2
    var cy = height / 2
    var dx = pointInHoleCoords.x - cx
    var dy = pointInHoleCoords.y - cy
    var dist = Math.sqrt(dx * dx + dy * dy)
    return dist <= 125
  }

  function triggerAbsorption() {
    absorbAnim.restart()
  }

  // 吸积盘旋转驱动器
  NumberAnimation {
    target: diskRotation
    property: "angle"
    from: 0
    to: 360
    duration: blackHoleRoot.isDragOver ? 2500 : (blackHoleRoot.isDraggingAny ? 6000 : 16000)
    loops: Animation.Infinite
    running: blackHoleRoot.visible && blackHoleRoot.opacity > 0.1
  }

  // 吸入时的超新星坍缩冲击波
  ParallelAnimation {
    id: absorbAnim
    NumberAnimation {
      target: shockwave
      property: "scale"
      from: 0.2
      to: 2.5
      duration: 450
      easing.type: Easing.OutCubic
    }
    NumberAnimation {
      target: shockwave
      property: "opacity"
      from: 1.0
      to: 0.0
      duration: 450
      easing.type: Easing.OutCubic
    }
    NumberAnimation {
      target: coreHole
      property: "scale"
      from: 0.4
      to: 1.0
      duration: 350
      easing.type: Easing.OutBack
    }
  }

  // 1. 引力场背光辉光 (Gravitational Glow)
  Rectangle {
    anchors.centerIn: parent
    width: blackHoleRoot.isDragOver ? 260 : 200
    height: width
    radius: width / 2
    color: "transparent"
    border.width: blackHoleRoot.isDragOver ? 3 : 1
    border.color: blackHoleRoot.isDragOver ? theme.danger : Tokens.alpha(theme.special, 0.25)

    Behavior on width { NumberAnimation { duration: Tokens.motion.slow; easing.type: Easing.OutCubic } }
    Behavior on border.color { ColorAnimation { duration: Tokens.motion.slow } }

    Rectangle {
      anchors.fill: parent
      radius: width / 2
      color: blackHoleRoot.isDragOver ? Tokens.alpha(theme.danger, 0.15) : Tokens.alpha(theme.special, 0.06)
      Behavior on color { ColorAnimation { duration: Tokens.motion.slow } }
    }
  }

  // 2. 动态旋转吸积盘 (Accretion Disk Canvas)
  Canvas {
    id: accretionCanvas
    anchors.fill: parent

    transform: Rotation {
      id: diskRotation
      origin.x: blackHoleRoot.width / 2
      origin.y: blackHoleRoot.height / 2
      angle: 0
    }

    onPaint: {
      var ctx = getContext("2d")
      var w = width
      var h = height
      var cx = w / 2
      var cy = h / 2

      ctx.clearRect(0, 0, w, h)

      var isOver = blackHoleRoot.isDragOver
      var grad = ctx.createRadialGradient(cx, cy, 35, cx, cy, 115)
      if (isOver) {
        grad.addColorStop(0, "rgba(255, 0, 128, 0.9)")
        grad.addColorStop(0.3, "rgba(255, 119, 0, 0.7)")
        grad.addColorStop(0.7, "rgba(168, 85, 247, 0.4)")
        grad.addColorStop(1, "rgba(0, 0, 0, 0)")
      } else {
        grad.addColorStop(0, "rgba(168, 85, 247, 0.6)")
        grad.addColorStop(0.4, "rgba(59, 130, 246, 0.4)")
        grad.addColorStop(0.8, "rgba(236, 72, 153, 0.2)")
        grad.addColorStop(1, "rgba(0, 0, 0, 0)")
      }

      ctx.beginPath()
      ctx.arc(cx, cy, 115, 0, 2 * Math.PI)
      ctx.fillStyle = grad
      ctx.fill()

      // 绘制引力透镜弯曲弧线
      ctx.lineWidth = 2
      var arcCount = 6
      for (var i = 0; i < arcCount; i++) {
        var a = (i * Math.PI * 2) / arcCount
        ctx.beginPath()
        ctx.arc(cx, cy, 75 + (i % 3) * 10, a, a + Math.PI * 0.45)
        ctx.strokeStyle = isOver ? "rgba(255, 230, 180, 0.8)" : "rgba(192, 132, 252, 0.5)"
        ctx.stroke()
      }
    }
  }

  // 3. 冲击波 (Shockwave)
  Rectangle {
    id: shockwave
    anchors.centerIn: parent
    width: 160
    height: 160
    radius: 80
    color: "transparent"
    border.width: 3
    border.color: theme.info
    opacity: 0
  }

  // 4. 事件视界中心深渊黑洞 (Event Horizon & Black Core)
  Rectangle {
    id: coreHole
    anchors.centerIn: parent
    width: blackHoleRoot.isDragOver ? 92 : 80
    height: width
    radius: width / 2
    color: theme.sunken
    border.width: blackHoleRoot.isDragOver ? 3.5 : 2
    border.color: blackHoleRoot.isDragOver ? theme.info : theme.textStrong

    Behavior on width { NumberAnimation { duration: Tokens.motion.normal; easing.type: Easing.OutCubic } }
    Behavior on border.color { ColorAnimation { duration: Tokens.motion.normal } }

    // 中心微型光子环 (Photon Ring)
    Rectangle {
      anchors.centerIn: parent
      width: parent.width * 0.55
      height: width
      radius: width / 2
      color: theme.shadow
      border.width: 1.5
      border.color: blackHoleRoot.isDragOver ? theme.accent : Tokens.alpha(theme.text, 0.4)
    }
  }

  // 5. 状态文字与战术标识
  Column {
    anchors.top: coreHole.bottom
    anchors.topMargin: 20
    anchors.horizontalCenter: parent.horizontalCenter
    spacing: 3

    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: 6

      Rectangle {
        width: 7
        height: 7
        radius: 3.5
        color: blackHoleRoot.isDragOver ? theme.danger : theme.special
        anchors.verticalCenter: parent.verticalCenter
        SequentialAnimation on opacity {
          loops: Animation.Infinite
          running: blackHoleRoot.visible && blackHoleRoot.opacity > 0.1
          NumberAnimation { from: 0.4; to: 1.0; duration: 600 }
          NumberAnimation { from: 1.0; to: 0.4; duration: 600 }
        }
      }

      Text {
        text: blackHoleRoot.isDragOver ? "EVENT HORIZON CAPTURE" : "BLACK HOLE PORTAL"
        color: blackHoleRoot.isDragOver ? theme.danger : theme.text
        font.pixelSize: 11
        font.bold: true
        font.family: Tokens.font.mono
      }
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      text: blackHoleRoot.isDragOver ? ("RELEASE → MOVE TO WORKSPACE [" + blackHoleRoot.targetWorkspaceId + "]") : ("DRAG HERE → WORKSPACE [" + blackHoleRoot.targetWorkspaceId + "]")
      color: blackHoleRoot.isDragOver ? theme.info : theme.textMuted
      font.pixelSize: 10
      font.bold: true
      font.family: Style.font.family
    }
  }
}
