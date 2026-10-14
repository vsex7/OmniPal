pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// OmniPal Overview - GTA V 战术武器扇区卡片 (高精细节打磨)
Item {
  id: cardRoot
  property OmniTheme theme: OmniTheme {}

  required property var windowData
  required property int cardIndex
  required property bool isSelected
  signal activated(string address)
  signal closeRequested(string address)

  readonly property var slot: cardRoot.windowData || ({})
  readonly property string appName: (slot.appName || "")
  readonly property string winTitle: slot.title || appName
  readonly property string winAddress: slot.address || ""
  readonly property string shortcutKey: slot.shortcutKey || String(cardRoot.cardIndex + 1)
  readonly property string iconName: slot.iconName || "application-x-executable"
  readonly property real cardScale: slot.cardScale || 1.0

  width: 176
  height: 100

  // density scale only (many windows); no hover lift.
  scale: cardRoot.cardScale

  Column {
    anchors.centerIn: parent
    spacing: 5

    // 原生应用高光矢量图标 (GTA 5 武器白模/高质感剪影)
    Item {
      width: 44
      height: 44
      anchors.horizontalCenter: parent.horizontalCenter

      // 选中态：Omarchy selected fill
      // Same fill/border tokens a selected native Button paints.
      BorderSurface {
        anchors.centerIn: parent
        width: 38
        height: 38
        radius: Style.cornerRadius
        // Native selection: fg@0.08 fill, no border.
        color: cardRoot.isSelected ? Util.alpha(cardRoot.theme.text, 0.08) : "transparent"
        borderSpec: Border.none()
      }

      Image {
        anchors.centerIn: parent
        width: 36
        height: 36
        source: Quickshell.iconPath(cardRoot.iconName, true)
        fillMode: Image.PreserveAspectFit
      }
    }

    // 应用名：常规字重、原样大小写
    Text {
      text: cardRoot.appName
      color: cardRoot.isSelected ? cardRoot.theme.accent : cardRoot.theme.text
      font.pixelSize: Style.font.body
      font.family: Style.font.family
      anchors.horizontalCenter: parent.horizontalCenter
      elide: Text.ElideRight
      width: Math.min(implicitWidth, 168)
    }

    // 状态标识 (选中时为亮橙加亮 ACTIVE，未选中为快捷键 [1])
    Text {
      text: cardRoot.isSelected ? "active" : cardRoot.shortcutKey
      color: cardRoot.isSelected ? cardRoot.theme.selectedText : cardRoot.theme.textMuted
      font.pixelSize: Style.font.caption
      font.family: Style.font.family
      anchors.horizontalCenter: parent.horizontalCenter
    }
  }
}
