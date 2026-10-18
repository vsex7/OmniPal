import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland

// Local fallback for qs.Ui OverlayWindow, which Omarchy main has but 4.0.4 lacks.
// On main the explicit `import qs.Ui` wins over this implicit same-directory type;
// on 4.0.4 this one is used. Same API subset the plugins rely on (shown,
// shownLayer, shownKeyboardFocus, targetScreen) and the same fullscreen
// layer-shell surface 4.0.4's own overlays (plugins/menu) use, on the focused
// monitor. Main's scale-wait reveal is omitted: it depends on Quickshell APIs
// (devicePixelRatio, Hyprland.refreshMonitors) not guaranteed on 4.0.4.
// Single source: plugins/shared/OverlayWindow.qml (symlinked into each plugin as ../shared/OverlayWindow.qml).
PanelWindow {
  id: window

  // Whether the overlay is showing. Drive this instead of visible.
  property bool shown: false
  property int shownLayer: WlrLayer.Overlay
  property int shownKeyboardFocus: WlrKeyboardFocus.Exclusive
  property var targetScreen: null

  function focusedScreen() {
    var monitor = Hyprland.focusedMonitor
    var name = monitor ? String(monitor.name || "") : ""
    for (var i = 0; i < Quickshell.screens.length; i++) {
      if (Quickshell.screens[i].name === name) return Quickshell.screens[i]
    }
    return Quickshell.screens.length > 0 ? Quickshell.screens[0] : null
  }

  onShownChanged: targetScreen = shown ? focusedScreen() : null

  Connections {
    target: Quickshell
    function onScreensChanged() {
      if (window.shown && Quickshell.screens.indexOf(window.targetScreen) < 0) {
        window.targetScreen = null
        Qt.callLater(function() {
          if (window.shown && !window.targetScreen) window.targetScreen = window.focusedScreen()
        })
      }
    }
  }

  visible: shown && !!targetScreen
  screen: targetScreen
  anchors { top: true; left: true; bottom: true; right: true }
  color: "transparent"
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.layer: shownLayer
  WlrLayershell.keyboardFocus: shownKeyboardFocus
}
