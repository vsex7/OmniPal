.pragma library
// OmniPal icon set: monochrome Nerd Font glyphs (JetBrainsMono Nerd Font is
// Omarchy's Style.font.family), rendered in foreground/accent only, never emoji.
// Mode identity in the UI = glyph + name, never colour. Profile JSON
// display.icon / display.color stay in the schema for compatibility but are
// not rendered.
// Single source: plugins/shared/Icons.js (copied by scripts/sync_tokens.py).

var glyph = {
  windows: "󰖳",
  mac: "󰀵",
  kde: "",
  omarchy: "󰕰",
  custom: "󰌌",
  cheat: "󰌌",
  settings: "󰒓",
  snap: "󰯌",
  overview: "󰕮",
  cycle: "󰓦",
  restore: "󰦛",
  doctor: "󰓷",
  close: "󰅖",
  save: "󰆓",
  search: "󰍉",
  browser: "󰖟",
  folder: "󰉋",
  terminal: "󰆍",
  music: "󰝚",
  chat: "󰍡",
  image: "󰋩",
  window: "󰖶",
  focus: "󰓾",
  plus: "󰐕",
  check: "󰄬",
  stats: "󰄨",
  rules: "󰘔",
  magnet: "󰌢",
  layout: "󰕰",
  warning: "󰀦",
  busy: "󰔟",
  pause: "󰏤",
  history: "󰋚",
  compass: "󰆋",
  trash: "󰩺",
  code: "󰅩",
  dot: "󰝥",
  keyboard: "󰌌",
  book: "󰂺",
}

function mode(id) {
  var k = String(id || "").toLowerCase()
  if (k === "windows" || k === "mac" || k === "kde" || k === "omarchy") return glyph[k]
  return glyph.custom
}

function appForClass(cls) {
  var c = String(cls || "").toLowerCase()
  if (!c) return glyph.window
  if (/chrome|firefox|chromium|zen|edge|brave/.test(c)) return glyph.browser
  if (/thunar|nautilus|dolphin|file/.test(c)) return glyph.folder
  if (/alacritty|kitty|foot|ghostty|terminal|wezterm/.test(c)) return glyph.terminal
  if (/code|cursor|zed|nvim/.test(c)) return glyph.code
  if (/settings|control|pavucontrol/.test(c)) return glyph.settings
  if (/spotify|music|sound/.test(c)) return glyph.music
  if (/discord|telegram|wechat|slack|qq|signal/.test(c)) return glyph.chat
  if (/image|gimp|photo|krita/.test(c)) return glyph.image
  return glyph.window
}
