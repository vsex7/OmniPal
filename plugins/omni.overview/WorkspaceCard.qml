import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Rectangle {
  id: root

  required property var workspaceData
  required property var windowsList
  required property var monitorBox
  required property bool isActiveWorkspace
  required property string focusedAddress
  required property string selectedAddress

  signal workspaceClicked(int workspaceId)
  signal windowClicked(var windowData)
  signal windowCloseRequested(var windowData)

  readonly property int workspaceId: root.workspaceData ? root.workspaceData.id : 1
  readonly property string workspaceName: root.workspaceData ? (root.workspaceData.name || String(root.workspaceId)) : "1"
  readonly property bool isNewSlot: root.workspaceData && root.workspaceData.isNewSlot === true
  readonly property bool isDark: (Color.background.r * 0.299 + Color.background.g * 0.587 + Color.background.b * 0.114) < 0.5
  readonly property color accentColor: Color.accent || "#88c0d0"

  radius: 8
  color: root.isNewSlot
    ? (isDark ? Qt.rgba(0.08, 0.10, 0.13, 0.35) : Qt.rgba(0.92, 0.94, 0.97, 0.35))
    : (isDark ? Qt.rgba(0.10, 0.12, 0.15, 0.76) : Qt.rgba(0.92, 0.93, 0.96, 0.76))

  border.color: {
    if (root.isNewSlot) {
      return cardMouse.containsMouse ? root.accentColor : Qt.rgba(1, 1, 1, 0.16)
    }
    if (root.isActiveWorkspace) {
      return root.accentColor
    }
    return cardMouse.containsMouse ? Util.alpha(root.accentColor, 0.55) : Qt.rgba(1, 1, 1, 0.12)
  }
  border.width: root.isActiveWorkspace ? 2 : 1
  clip: true

  scale: cardMouse.containsMouse ? 1.006 : 1.0
  Behavior on scale { NumberAnimation { duration: 90 } }
  Behavior on border.color { ColorAnimation { duration: 100 } }
  Behavior on border.width { NumberAnimation { duration: 100 } }

  // 拟真壁纸半透明渐变
  Rectangle {
    anchors.fill: parent
    gradient: Gradient {
      GradientStop {
        position: 0.0
        color: Util.alpha(root.accentColor, root.isActiveWorkspace ? 0.14 : (root.isNewSlot ? 0.02 : 0.05))
      }
      GradientStop {
        position: 1.0
        color: "transparent"
      }
    }
  }

  // 活动工作区呼吸光晕外边框
  Rectangle {
    id: activeGlow
    anchors.fill: parent
    anchors.margins: -2
    radius: root.radius + 2
    color: "transparent"
    border.color: Util.alpha(root.accentColor, 0.55)
    border.width: 2
    visible: root.isActiveWorkspace && !root.isNewSlot
    z: -1

    SequentialAnimation on opacity {
      running: root.isActiveWorkspace && !root.isNewSlot
      loops: Animation.Infinite
      NumberAnimation { to: 0.90; duration: 1200; easing.type: Easing.InOutQuad }
      NumberAnimation { to: 0.25; duration: 1200; easing.type: Easing.InOutQuad }
    }
  }

  // 顶部工作区标头
  Item {
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.margins: 8
    height: 22
    z: 10
    visible: !root.isNewSlot

    // 工作区编号徽标
    Rectangle {
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      height: 20
      implicitWidth: wsBadgeRow.implicitWidth + 14
      radius: 4
      color: root.isActiveWorkspace ? root.accentColor : Qt.rgba(0, 0, 0, 0.55)
      border.color: root.isActiveWorkspace ? Qt.lighter(root.accentColor, 1.25) : Qt.rgba(1, 1, 1, 0.15)
      border.width: 1

      Row {
        id: wsBadgeRow
        anchors.centerIn: parent
        spacing: 5

        Rectangle {
          width: 5
          height: 5
          radius: 2.5
          anchors.verticalCenter: parent.verticalCenter
          color: root.isActiveWorkspace ? "#101315" : Qt.rgba(1, 1, 1, 0.6)
        }

        Text {
          id: wsText
          text: "桌面 " + root.workspaceName
          color: root.isActiveWorkspace ? "#101315" : "#ffffff"
          font.family: Style.font.family
          font.pixelSize: 10
          font.bold: true
          anchors.verticalCenter: parent.verticalCenter
        }
      }
    }

    // 窗口计数指示胶囊
    Rectangle {
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      visible: root.windowsList && root.windowsList.length > 0
      height: 18
      implicitWidth: countText.implicitWidth + 10
      radius: 3
      color: Qt.rgba(0, 0, 0, 0.40)
      border.color: Qt.rgba(1, 1, 1, 0.10)
      border.width: 1

      Text {
        id: countText
        anchors.centerIn: parent
        text: root.windowsList.length + " 个窗口"
        font.family: Style.font.family
        font.pixelSize: 9
        color: Util.alpha(Color.foreground, 0.65)
      }
    }
  }

  // 新建工作区专用插槽展现
  Item {
    anchors.fill: parent
    visible: root.isNewSlot

    Column {
      anchors.centerIn: parent
      spacing: 8

      Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        width: 38
        height: 38
        radius: 19
        color: cardMouse.containsMouse ? Util.alpha(root.accentColor, 0.20) : Qt.rgba(1, 1, 1, 0.06)
        border.color: cardMouse.containsMouse ? root.accentColor : Qt.rgba(1, 1, 1, 0.18)
        border.width: 1.5

        scale: cardMouse.containsMouse ? 1.12 : 1.0
        Behavior on scale { NumberAnimation { duration: 100 } }

        Text {
          anchors.centerIn: parent
          text: "+"
          font.pixelSize: 20
          font.bold: true
          color: cardMouse.containsMouse ? root.accentColor : Util.alpha(Color.foreground, 0.6)
        }
      }

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: "新建桌面 " + root.workspaceName
        font.family: Style.font.family
        font.pixelSize: 11
        font.bold: true
        color: cardMouse.containsMouse ? Color.foreground : Util.alpha(Color.foreground, 0.6)
      }

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: "快捷键 " + root.workspaceName
        font.family: Style.font.family
        font.pixelSize: 9
        color: Util.alpha(Color.foreground, 0.35)
      }
    }
  }

  // 空工作区提示（已有工作区但无窗口）
  Text {
    anchors.centerIn: parent
    visible: !root.isNewSlot && (!root.windowsList || root.windowsList.length === 0)
    text: "空桌面 · 点击前往"
    color: Util.alpha(Color.foreground, 0.35)
    font.family: Style.font.family
    font.pixelSize: 11
    font.bold: true
  }

  // 挂载工作区内的所有微缩窗口
  Repeater {
    model: root.windowsList

    delegate: OverviewWindow {
      required property var modelData

      windowData: modelData
      monitorBox: root.monitorBox
      cardWidth: root.width
      cardHeight: root.height
      isFocused: modelData.address === root.focusedAddress
      isSelected: modelData.address === root.selectedAddress

      onWindowClicked: function(w) { root.windowClicked(w) }
      onCloseRequested: function(w) { root.windowCloseRequested(w) }
    }
  }

  // 点击工作区空白处跳转至该工作区
  MouseArea {
    id: cardMouse
    anchors.fill: parent
    z: -1
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: root.workspaceClicked(root.workspaceId)
  }
}
