import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Item {
  id: root

  required property var windowData
  required property var monitorBox
  required property int cardWidth
  required property int cardHeight
  required property bool isFocused
  required property bool isSelected

  signal windowClicked(var windowData)
  signal closeRequested(var windowData)

  readonly property bool isDark: (Color.background.r * 0.299 + Color.background.g * 0.587 + Color.background.b * 0.114) < 0.5
  readonly property color accentColor: Color.accent || "#88c0d0"
  readonly property string appClass: (root.windowData && (root.windowData.initialClass || root.windowData.class)) || ""
  readonly property string appTitle: (root.windowData && (root.windowData.title || root.appClass)) || "Window"
  readonly property bool isFloating: (root.windowData && root.windowData.floating) === true

  readonly property var appMeta: Model.resolveAppDetails(root.appClass)
  readonly property color glyphColor: root.appMeta.color || root.accentColor
  readonly property string glyphIcon: root.appMeta.icon || "🗔"

  readonly property color windowSurface: isDark ? Qt.rgba(0.12, 0.14, 0.18, 0.92) : Qt.rgba(0.96, 0.96, 0.98, 0.92)
  readonly property color windowBorder: (root.isSelected || root.isFocused)
    ? root.glyphColor
    : (winMouse.containsMouse ? Qt.lighter(root.glyphColor, 1.2) : (isDark ? Qt.rgba(1, 1, 1, 0.18) : Qt.rgba(0, 0, 0, 0.18)))

  readonly property var scaledGeom: Model.scaleWindowGeometry(
    {
      x: (root.windowData && root.windowData.at) ? root.windowData.at[0] : 0,
      y: (root.windowData && root.windowData.at) ? root.windowData.at[1] : 0,
      width: (root.windowData && root.windowData.size) ? root.windowData.size[0] : 800,
      height: (root.windowData && root.windowData.size) ? root.windowData.size[1] : 600
    },
    root.monitorBox,
    root.cardWidth,
    root.cardHeight
  )

  x: scaledGeom.x
  y: scaledGeom.y
  width: scaledGeom.width
  height: scaledGeom.height
  z: (root.isSelected || root.isFocused) ? 30 : (winMouse.containsMouse ? 20 : 1)

  // 窗口微阴影
  Rectangle {
    anchors.fill: parent
    anchors.margins: -1
    radius: 5
    color: Qt.rgba(0, 0, 0, (root.isSelected || root.isFocused) ? 0.45 : 0.25)
    z: -1
  }

  // 窗口外发光光晕（高亮选定时）
  Rectangle {
    anchors.fill: parent
    anchors.margins: -3
    radius: 7
    visible: root.isSelected || root.isFocused
    color: "transparent"
    border.color: Util.alpha(root.glyphColor, 0.45)
    border.width: 2
    z: -1

    Behavior on opacity { NumberAnimation { duration: 100 } }
  }

  Rectangle {
    id: windowFrame
    anchors.fill: parent
    radius: 4
    color: root.windowSurface
    border.color: root.windowBorder
    border.width: (root.isSelected || root.isFocused) ? 2 : (winMouse.containsMouse ? 2 : 1)
    clip: true

    Behavior on border.color { ColorAnimation { duration: 80 } }
    Behavior on scale { NumberAnimation { duration: 80 } }
    scale: winMouse.pressed ? 0.98 : ((root.isSelected || winMouse.containsMouse) ? 1.03 : 1.0)

    // 窗口顶部微型标题栏
    Rectangle {
      id: titleBar
      anchors.top: parent.top
      anchors.left: parent.left
      anchors.right: parent.right
      height: Math.min(22, Math.floor(parent.height * 0.38))
      color: Qt.rgba(0.06, 0.08, 0.11, 0.90)

      Item {
        anchors.fill: parent
        anchors.leftMargin: 5
        anchors.rightMargin: 5

        Text {
          id: glyphText
          text: root.glyphIcon
          font.pixelSize: Math.max(9, titleBar.height - 8)
          color: root.glyphColor
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
        }

        Text {
          text: root.appTitle
          font.family: Style.font.family
          font.pixelSize: Math.max(8, titleBar.height - 9)
          font.bold: root.isSelected || root.isFocused
          color: (root.isSelected || root.isFocused) ? "#ffffff" : Qt.rgba(1, 1, 1, 0.85)
          elide: Text.ElideRight
          anchors.left: glyphText.right
          anchors.leftMargin: 4
          anchors.right: closeBtn.left
          anchors.rightMargin: 2
          anchors.verticalCenter: parent.verticalCenter
        }

        // 快捷关闭小红叉
        Rectangle {
          id: closeBtn
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: titleBar.height - 4
          height: titleBar.height - 4
          radius: 2
          color: closeMouse.containsMouse ? "#bf616a" : "transparent"

          Text {
            text: "✕"
            font.pixelSize: 8
            font.bold: true
            color: closeMouse.containsMouse ? "#ffffff" : Qt.rgba(1, 1, 1, 0.5)
            anchors.centerIn: parent
          }

          MouseArea {
            id: closeMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.closeRequested(root.windowData)
          }
        }
      }
    }

    // 窗口微缩展示体
    Item {
      anchors.top: titleBar.bottom
      anchors.bottom: parent.bottom
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.margins: 4

      Text {
        anchors.centerIn: parent
        visible: parent.height > 24 && parent.width > 60
        text: root.appClass
        font.pixelSize: 9
        font.family: Style.font.family
        color: Util.alpha(Color.foreground, 0.35)
        elide: Text.ElideRight
        width: parent.width - 4
        horizontalAlignment: Text.AlignHCenter
      }

      // 浮动窗口小徽标
      Rectangle {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        visible: root.isFloating && parent.width > 50 && parent.height > 28
        width: floatText.implicitWidth + 6
        height: 14
        radius: 2
        color: Qt.rgba(0.82, 0.53, 0.44, 0.25)
        border.color: "#d08770"
        border.width: 1

        Text {
          id: floatText
          text: "浮动"
          font.pixelSize: 8
          font.bold: true
          color: "#d08770"
          anchors.centerIn: parent
        }
      }
    }

    MouseArea {
      id: winMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.windowClicked(root.windowData)
    }
  }
}
