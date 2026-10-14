import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui

// OmniPal Overview - GTA V 战术武器扇区卡片 (高精细节打磨)
Item {
  id: cardRoot

  required property var windowData
  required property int cardIndex
  required property bool isSelected
  signal activated(string address)
  signal closeRequested(string address)

  readonly property var slot: cardRoot.windowData || ({})
  readonly property string appName: (slot.appName || "").toUpperCase()
  readonly property string winTitle: slot.title || appName
  readonly property string winAddress: slot.address || ""
  readonly property string shortcutKey: slot.shortcutKey || String(cardRoot.cardIndex + 1)
  readonly property string iconName: slot.iconName || "application-x-executable"
  readonly property real cardScale: slot.cardScale || 1.0

  width: 176
  height: 100

  // 选中态微凸起动效 (GTA 5 扇区浮升感与高亮)
  scale: (cardRoot.isSelected ? 1.10 : 1.0) * cardRoot.cardScale
  Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

  Column {
    anchors.centerIn: parent
    spacing: 5

    // 原生应用高光矢量图标 (GTA 5 武器白模/高质感剪影)
    Item {
      width: 44
      height: 44
      anchors.horizontalCenter: parent.horizontalCenter

      // 选中时的微弱环境背光
      Rectangle {
        anchors.centerIn: parent
        width: 38
        height: 38
        radius: 19
        color: cardRoot.isSelected ? Qt.rgba(255, 255, 255, 0.12) : "transparent"
      }

      Image {
        anchors.centerIn: parent
        width: 36
        height: 36
        source: Quickshell.iconPath(cardRoot.iconName, true)
        fillMode: Image.PreserveAspectFit
      }
    }

    // 粗体全大写应用名 (GTA 5 经典战术排版：高字间距、粗黑对比)
    Text {
      text: cardRoot.appName
      color: cardRoot.isSelected ? "#ffffff" : "#b0b8c4"
      font.pixelSize: 13
      font.bold: true
      font.family: Style.font.family
      font.letterSpacing: 0.8
      anchors.horizontalCenter: parent.horizontalCenter
      elide: Text.ElideRight
      width: Math.min(implicitWidth, 168)
    }

    // 状态标识 (选中时为亮橙加亮 ACTIVE，未选中为快捷键 [1])
    Text {
      text: cardRoot.isSelected ? "ACTIVE" : ("[" + cardRoot.shortcutKey + "]")
      color: cardRoot.isSelected ? "#ff7700" : "#64748b"
      font.pixelSize: 10
      font.bold: true
      font.family: "monospace"
      font.letterSpacing: 1
      anchors.horizontalCenter: parent.horizontalCenter
    }
  }
}
