.pragma library
// OmniPal 共享设计 token：插件里不要再写死颜色和尺寸，统一从这里取。
// 优先跟随 Omarchy 主题（Color.*），这里只做缺省值和语义色。
var mode = { windows: "#0078d4", mac: "#a2aaad", omarchy: "#a3be8c",
             custom: ["#b48ead", "#ebcb8b", "#88c0d0", "#d08770", "#81a1c1"] };
var semantic = { accent: "#88c0d0", ok: "#a3be8c", warn: "#ebcb8b", danger: "#bf616a", info: "#d08770" };
var radius = { sm: 4, md: 8, lg: 14, pill: 999 };
var motion = { fast: 120, normal: 140, slow: 220 };
function modeColor(id, index) { return mode[id] || mode.custom[(index || 0) % mode.custom.length]; }
function accent(Color) { return (Color && Color.accent) ? Color.accent : semantic.accent; }
