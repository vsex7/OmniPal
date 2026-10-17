import QtQuick
import qs.Commons
import qs.Commons as Commons

// OmniPal semantic roles for the few *custom* surfaces Omarchy has no widget for
// (overview wheel canvas, snap zone previews, dock tiles, black-hole portal).
// Every role resolves straight from Omarchy Shell's own qs.Commons singletons —
// Color.menu.* (the overlay surface family omarchy.emojis/menu use), Color.popups.*,
// Color.accent/urgent/muted and Style's interactive-state helpers — so a theme
// change, a shell.toml [menu]/[controls] override, or Style.reduceMotion reaches
// these surfaces exactly like first-party ones.
//
// Colour discipline (designer gap list): ONLY the five native roles —
// foreground / background / accent / urgent / muted(dim). Legacy status role
// names (ok/warn/info/special/highlight) are kept as aliases onto those roles
// so no custom hue can reach the UI.
// Anything that has a native widget (Button, TextField, ToggleSwitch, PanelHero,
// PanelSectionHeader, PanelSeparator, ...) must use that widget instead of this.
//
// Single source: plugins/shared/OmniTheme.qml, symlinked into each plugin as
// ../shared/OmniTheme.qml (install.sh also links plugins/shared itself, so the
// relative links keep resolving after per-plugin symlinked installs).
QtObject {
  id: t

  // Kept for API compatibility only; no longer used for rendering.
  property var palette: ({})

  // ---- surfaces (Color.menu = overlay family, Color.popups = bar panels)
  readonly property color bg: Commons.Color.menu.background
  readonly property color popupBg: Commons.Color.popups.background
  readonly property color popupText: Commons.Color.popups.text
  readonly property color popupBorder: Commons.Color.popups.border
  readonly property color surface: Commons.Color.popups.background
  readonly property color surfaceAlt: Style.normalFillFor(t.text, t.accent)
  readonly property color sunken: Qt.darker(Commons.Color.background, 1.25)
  readonly property color scrim: Commons.Color.menu.scrim
  readonly property color menuScrim: Commons.Color.menu.scrim
  readonly property color shadow: "transparent" // native: no shadows

  // ---- text (dim = the Qt.darker(fg, 1.4) first-party panels use for meta text)
  readonly property color text: Commons.Color.menu.text
  readonly property color textStrong: Commons.Color.menu.text
  readonly property color textMuted: Qt.darker(Commons.Color.menu.text, 1.4)

  // ---- accent & state (Style [controls] tokens)
  readonly property color accent: Commons.Color.accent
  readonly property color onAccent: Commons.Color.background
  readonly property color selectedText: Commons.Color.menu.selectedText
  readonly property color selectedFill: Commons.Color.menu.selectedBackground
  readonly property color selectedBorder: Style.selectedBorderFor(t.text, t.accent)
  readonly property color selection: Style.selectionFillFor(t.text, t.accent)
  readonly property color selectionFill: Style.selectionFillFor(t.text, t.accent)
  readonly property color hoverFill: Style.hoverFillFor(t.text, t.accent)
  readonly property color chipFill: Style.normalFillFor(t.text, t.accent)
  readonly property color chipBorder: Style.normalBorderFor(t.text, t.accent)
  readonly property color line: Util.alpha(t.text, 0.16)
  readonly property color lineStrong: Style.normalBorderFor(t.text, t.accent)

  // ---- status hues
  readonly property color danger: Commons.Color.urgent
  readonly property color onDanger: Commons.Color.background
  readonly property color ok: Commons.Color.accent
  readonly property color warn: Commons.Color.urgent
  readonly property color info: Commons.Color.accent
  readonly property color special: t.textMuted
  readonly property color highlight: Commons.Color.accent
  readonly property color white: Commons.Color.foreground
  readonly property color black: Commons.Color.background

  // ---- geometry (all native)
  readonly property int radius: Style.cornerRadius
  // Surface border = what OverlayWindow/KeyboardPanel cards use for [menu]/[popups].
  readonly property int borderStrong: Math.max(1, Style.space(2))
  readonly property int borderHair: Math.max(1, Style.normalBorderWidth)

  // ---- motion: Style.reduceMotion / Style.duration() only exist on Omarchy main;
  // Omarchy 4.0.4 has neither, so read them dynamically and fall back to full motion.
  function styleFlag(name) { return Style[name] === true }
  readonly property bool reduceMotion: t.styleFlag("reduceMotion")
  function duration(ms) { return t.reduceMotion ? 0 : ms }
}
