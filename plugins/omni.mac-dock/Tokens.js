.pragma library
// OmniPal design tokens — the ONLY place in plugins/ allowed to contain colour literals.
// Omarchy visual language: flat dark surfaces, 0 corner radius (Hyprland `rounding = 0`),
// 2px borders in the accent colour (Hyprland `border_size = 2`, active_border = accent),
// monospace type, keyboard-first focus states.
//
// Runtime theme: each plugin root reads the current Omarchy theme's colors.toml
//   ~/.local/state/omarchy/current/theme/colors.toml   (current omarchy)
//   ~/.config/omarchy/current/theme/colors.toml         (legacy location, tried on load failure)
// via a FileView, passes the text to parseColorsToml(), and calls build(Color, palette).
// The host's qs.Commons Color (which also reads colors.toml/shell.toml) wins for the core
// roles (background/foreground/accent); this palette supplies the rest (red/green/...).

// Fallback: Omarchy themes/tokyo-night/colors.toml (basecamp/omarchy).
var fallback = {
  accent: "#7aa2f7", selection: "#292e42", muted: "#414868",
  background: "#1a1b26", dark_background: "#13141c", darker_background: "#0e0e14",
  lighter_background: "#24283b",
  foreground: "#a9b1d6", dark_foreground: "#565f89", light_foreground: "#b4bee6",
  bright_foreground: "#c0caf5",
  red: "#f7768e", yellow: "#e0af68", orange: "#eb927b", green: "#9ece6a",
  cyan: "#449dab", blue: "#7aa2f7", magenta: "#ad8ee6",
  black: "#000000", white: "#ffffff"
};

var themeFiles = {
  stateRel: "/.local/state/omarchy/current/theme/colors.toml",
  legacyRel: "/.config/omarchy/current/theme/colors.toml"
};

// Minimal colors.toml parser: `key = "#rrggbb"` pairs (what Omarchy themes ship).
function parseColorsToml(text) {
  var out = {};
  if (!text) return out;
  var lines = String(text).split(/\r?\n/);
  var section = "";
  for (var i = 0; i < lines.length; i++) {
    var l = lines[i].trim();
    if (!l || l.charAt(0) === "#") continue;
    var s = l.match(/^\[([^\]]+)\]$/);
    if (s) { section = s[1].trim(); continue; }
    var m = l.match(/^([A-Za-z0-9_\-]+)\s*=\s*["']([^"']*)["']/);
    if (!m) continue;
    out[section ? section + "." + m[1] : m[1]] = m[2].trim();
  }
  return out;
}

function _isColor(v) { return typeof v === "string" && /^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(v); }

function mergePalette(parsed) {
  var p = {};
  for (var k in fallback) p[k] = fallback[k];
  if (parsed) for (var k2 in parsed) if (_isColor(parsed[k2])) p[k2] = parsed[k2];
  return p;
}

function alpha(c, a) {
  var q = Qt.color(c);
  return Qt.rgba(q.r, q.g, q.b, a);
}

var radius = { none: 0, sm: 0, md: 0, chip: 2 };      // Omarchy: rounding = 0
var border = { hair: 1, normal: 2, focus: 2 };        // Hyprland border_size = 2
var space = { xxs: 2, xs: 4, sm: 6, md: 10, lg: 14, xl: 20, xxl: 28 };
var type = { caption: 10, small: 11, body: 13, title: 15, display: 20 };
// Omarchy shell.toml [popups]/[menu]: border = hyprland active-border (accent), border_size 2,
// solid background (alpha 1.0), scrim = background @ 0.5, popup-padding 14.
var popup = { border: 2, padding: 14, scrimAlpha: 0.5 };
// Corner radius mirrors Hyprland decoration:rounding (host Style.cornerRadius; Omarchy default 0).
function corner(Style) { return (Style && Style.cornerRadius > 0) ? Style.cornerRadius : radius.none; }
var motion = { fast: 90, normal: 140, slow: 200 };
var font = { mono: "JetBrainsMono Nerd Font", fallback: "monospace" };

// Build the semantic theme. `Color` = host qs.Commons Color (may be null).
function build(Color, palette) {
  var p = palette || fallback;
  var bg = (Color && Color.background) ? Color.background : p.background;
  var fg = (Color && Color.foreground) ? Color.foreground : p.foreground;
  var acc = (Color && Color.accent) ? Color.accent : p.accent;
  return {
    bg: bg,
    surface: p.dark_background,
    surfaceAlt: p.lighter_background,
    sunken: p.darker_background,
    scrim: alpha(p.darker_background, 0.6),
    shadow: alpha(p.black, 0.35),
    line: alpha(fg, 0.16),
    lineStrong: alpha(fg, 0.32),
    text: fg,
    textStrong: p.bright_foreground,
    textMuted: p.dark_foreground,
    accent: acc,
    onAccent: p.darker_background,
    selection: p.selection,
    selectionFill: alpha(acc, 0.14),
    hoverFill: alpha(fg, 0.06),
    chipFill: alpha(fg, 0.07),
    chipBorder: alpha(fg, 0.22),
    ok: p.green, warn: p.yellow, danger: p.red, info: p.cyan,
    special: p.magenta, highlight: p.orange,
    onDanger: p.darker_background,
    white: p.white, black: p.black,
    // Omarchy native popup chrome (shell.toml [popups]/[menu]); host Color wins, palette is the fallback.
    popupBg: (Color && Color.popups && Color.popups.background) ? Color.popups.background : bg,
    popupText: (Color && Color.popups && Color.popups.text) ? Color.popups.text : fg,
    popupBorder: (Color && Color.popups && Color.popups.border) ? Color.popups.border : acc,
    menuScrim: (Color && Color.menu && Color.menu.scrim) ? Color.menu.scrim : alpha(bg, popup.scrimAlpha),
    selectedFill: alpha(fg, 0.08),
    selectedText: acc,
    selectedBorder: acc
  };
}

// Mode identity colours, derived from the palette so they re-skin with the theme.
function modeColors(palette) {
  var p = palette || fallback;
  return { windows: p.blue, mac: p.light_foreground, omarchy: p.green, kde: p.cyan,
           custom: [p.magenta, p.yellow, p.cyan, p.orange, p.blue] };
}
var mode = modeColors(fallback);
var semantic = { accent: fallback.accent, ok: fallback.green, warn: fallback.yellow,
                 danger: fallback.red, info: fallback.cyan };
function modeColor(id, index) { return mode[id] || mode.custom[(index || 0) % mode.custom.length]; }
function accent(Color) { return (Color && Color.accent) ? Color.accent : semantic.accent; }
