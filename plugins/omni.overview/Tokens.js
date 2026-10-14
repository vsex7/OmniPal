.pragma library
// OmniPal 设计 token（唯一源头）。炭黑 / 米白 / 琥珀，平面、无渐变。
// 优先跟随 Omarchy 主题（Color.*），这里只做缺省值和语义色。
var base = { bg: "#16161a", surface: "#1e1e23", line: "#3a3a40",
             text: "#e6e1d6", muted: "#8a867d", accent: "#e2a03f" };
// 模式识别色：降饱和，和琥珀同一色温
var mode = { windows: "#6f93b8", mac: "#b5ada0", omarchy: "#8fa77a",
             custom: ["#a98bb0", "#c9a36a", "#7fa3a3", "#c08066", "#8a97b5"] };
var semantic = { accent: base.accent, ok: "#8fa77a", warn: "#e2a03f", danger: "#c4624f", info: "#7fa3a3" };
var radius = { none: 0, sm: 2, md: 4, lg: 6 };   // 键帽风格：直角为主
var stroke = { hair: 1, normal: 2 };
var motion = { fast: 100, normal: 140, slow: 200 };
var font = { mono: "JetBrains Mono" };
function modeColor(id, index) { return mode[id] || mode.custom[(index || 0) % mode.custom.length]; }
function accent(Color) { return (Color && Color.accent) ? Color.accent : semantic.accent; }
