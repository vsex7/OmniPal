// Model.js - OmniPal Mode Indicator and Context Menu Pure Helper Functions
// Single Source of Truth helper for colors, icons, labels, and fallback profiles

.pragma library

var DEFAULT_ICONS = {
  "windows": "⊞",
  "mac":     "◆",
  "omarchy": "⊡"
};

var DEFAULT_BRIEFS = {
  "windows": "WIN",
  "mac":     "MAC",
  "omarchy": "OMA"
};

var DEFAULT_COLORS = {
  "windows": "#3892d6",
  "mac":     "#d8dee9",
  "omarchy": "#a3be8c"
};

var DEFAULT_NAMES = {
  "windows": "Windows 11 习惯模式",
  "mac":     "macOS 习惯模式",
  "omarchy": "Omarchy 原生模式"
};

function defaultIcon(id) {
  var key = String(id || "").toLowerCase();
  return DEFAULT_ICONS[key] || "◇";
}

function defaultBrief(id) {
  var key = String(id || "").toLowerCase();
  if (DEFAULT_BRIEFS[key]) return DEFAULT_BRIEFS[key];
  if (!id) return "OMA";
  return id.length > 4 ? id.substring(0, 3).toUpperCase() : id.toUpperCase();
}

function defaultColor(id) {
  var key = String(id || "").toLowerCase();
  if (DEFAULT_COLORS[key]) return DEFAULT_COLORS[key];
  // Stable color from id string hash
  var hash = 0;
  for (var i = 0; i < key.length; i++) {
    hash = key.charCodeAt(i) + ((hash << 5) - hash);
  }
  var hue = Math.abs(hash % 360);
  return "hsl(" + hue + ", 65%, 65%)";
}

function resolveIcon(item) {
  if (!item) return "◇";
  if (item.display && item.display.icon) return item.display.icon;
  return defaultIcon(item.id || item.mode);
}

function resolveBrief(item) {
  if (!item) return "OMA";
  if (item.display && item.display.brief) return item.display.brief;
  return defaultBrief(item.id || item.mode);
}

function resolveColor(item) {
  if (!item) return "#a3be8c";
  if (item.display && item.display.color) return item.display.color;
  return defaultColor(item.id || item.mode);
}

function resolveName(item) {
  if (!item) return "Omarchy 原生模式";
  if (item.name) return item.name;
  var key = String(item.id || item.mode || "").toLowerCase();
  return DEFAULT_NAMES[key] || item.id || "未知模式";
}

function fallbackProfiles() {
  return [
    {
      "id": "windows",
      "name": "Windows 11 习惯模式",
      "description": "还原 Windows 常用快捷键习惯（Alt+F4 关闭、Super+方向键吸附、Super+E 文件管理器等）",
      "bindings_count": 14,
      "display": { "icon": "⊞", "brief": "WIN", "color": "#3892d6" }
    },
    {
      "id": "mac",
      "name": "macOS 习惯模式",
      "description": "还原 macOS 常用操作快捷键（Super+Q 关闭、Super+空格启动器、Super+Shift+4 区域截图等）",
      "bindings_count": 19,
      "display": { "icon": "◆", "brief": "MAC", "color": "#d8dee9" }
    },
    {
      "id": "omarchy",
      "name": "Omarchy 原生模式",
      "description": "系统默认原生快捷键，无任何覆盖修改，适合学习与原生对比",
      "bindings_count": 0,
      "display": { "icon": "⊡", "brief": "OMA", "color": "#a3be8c" }
    }
  ];
}

var DEFAULT_POLICIES = [
  {
    "id": "tiled",
    "name": "平铺",
    "english": "Tiled",
    "icon": "◫",
    "desc": "新常规窗口自动平铺分屏"
  },
  {
    "id": "floating",
    "name": "浮动",
    "english": "Floating",
    "icon": "❐",
    "desc": "新常规窗口居中自由浮动"
  },
  {
    "id": "follow-profile",
    "name": "跟随",
    "english": "Follow",
    "icon": "⇄",
    "desc": "随快捷键模式决定平铺/浮动"
  }
];

function windowPolicies() {
  return DEFAULT_POLICIES;
}

function normalizePolicy(id) {
  var key = String(id || "").toLowerCase().trim();
  if (key === "follow" || key === "follow_profile" || key === "follow-profile") return "follow-profile";
  if (key === "float" || key === "floating") return "floating";
  if (key === "tile" || key === "tiled") return "tiled";
  return "tiled";
}

function resolvePolicyName(id) {
  var key = normalizePolicy(id);
  for (var i = 0; i < DEFAULT_POLICIES.length; i++) {
    if (DEFAULT_POLICIES[i].id === key) return DEFAULT_POLICIES[i].name;
  }
  return "平铺";
}

function resolvePolicyIcon(id) {
  var key = normalizePolicy(id);
  for (var i = 0; i < DEFAULT_POLICIES.length; i++) {
    if (DEFAULT_POLICIES[i].id === key) return DEFAULT_POLICIES[i].icon;
  }
  return "◫";
}

function resolvePolicyDesc(id, currentMode) {
  var key = normalizePolicy(id);
  if (key === "follow-profile") {
    var modeKey = String(currentMode || "").toLowerCase().trim();
    var eff = (modeKey === "mac") ? "浮动 (macOS 习惯)" : (modeKey === "windows" ? "平铺 (Windows 习惯)" : (modeKey === "omarchy" ? "平铺 (Omarchy 原生)" : "平铺 (默认习惯)"));
    return "当前跟随 " + eff;
  }
  for (var i = 0; i < DEFAULT_POLICIES.length; i++) {
    if (DEFAULT_POLICIES[i].id === key) return DEFAULT_POLICIES[i].desc;
  }
  return "新常规窗口自动平铺分屏";
}

function computeEffectiveMode(policy, currentMode) {
  var p = normalizePolicy(policy);
  if (p === "follow-profile") {
    return String(currentMode || "").toLowerCase().trim() === "mac" ? "floating" : "tiled";
  }
  if (p === "floating") return "floating";
  return "tiled";
}
