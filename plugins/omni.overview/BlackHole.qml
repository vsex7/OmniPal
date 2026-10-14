pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// OmniPal Overview — workspace drop target.
// Formerly a decorative "black hole" (canvas accretion disk, multi-hue glow,
// scale/shockwave animations). Native Omarchy has no such decoration, so this is
// now a plain square drop box: normal control border (fg@0.4) → accent 2px on
// drag-over, terse label. API (targetWorkspaceId / isDragOver / isDraggingAny /
// checkContains / triggerAbsorption / windowDropped) is unchanged.
Item {
  id: blackHoleRoot
  property OmniTheme theme: OmniTheme {}

  property int targetWorkspaceId: 2
  property bool isDragOver: false
  property bool isDraggingAny: false

  signal windowDropped(string address, int targetWs)

  width: Style.space(200)
  height: Style.space(96)

  function checkContains(p) {
    return p.x >= 0 && p.y >= 0 && p.x <= width && p.y <= height
  }

  // Kept for API compatibility; native surfaces have no absorb effect.
  function triggerAbsorption() {}

  BorderSurface {
    anchors.fill: parent
    radius: Style.cornerRadius
    opacity: blackHoleRoot.isDraggingAny || blackHoleRoot.isDragOver ? 1.0 : 0.6
    color: blackHoleRoot.isDragOver ? Util.alpha(blackHoleRoot.theme.text, 0.08) : blackHoleRoot.theme.popupBg
    borderSpec: blackHoleRoot.isDragOver
      ? Border.flat(blackHoleRoot.theme.accent, Math.max(1, Style.space(2)))
      : Border.controlSpec("normal", blackHoleRoot.theme.text, blackHoleRoot.theme.accent)

    Column {
      anchors.centerIn: parent
      spacing: Style.spacing.xs

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: "drop to move"
        color: blackHoleRoot.isDragOver ? blackHoleRoot.theme.accent : blackHoleRoot.theme.text
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: "workspace " + blackHoleRoot.targetWorkspaceId
        color: blackHoleRoot.theme.textMuted
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
    }
  }
}
