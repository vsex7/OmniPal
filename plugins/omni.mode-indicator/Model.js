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
  "windows": "Windows 11",
  "mac":     "macOS",
  "omarchy": "原生"
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

function resolveName(item, lang) {
  var isEn = (lang === "en");
  if (!item) return (isEn ? "Native" : "原生");
  var key = String(item.id || item.mode || "").toLowerCase();
  if (key === "omarchy") return (isEn ? "Native" : "原生");
  if (key === "windows") return "Windows 11";
  if (key === "mac") return "macOS";
  if (item.name) {
    if (isEn && (item.name === "原生" || item.name === "Omarchy 原生模式")) return "Native";
    return item.name;
  }
  return DEFAULT_NAMES[key] || item.id || (isEn ? "Unknown Mode" : "未知模式");
}

// Fallback shown only when the engine is unreachable. This is a copy of the
// profiles/ data (the single source of truth); test_omni.py asserts the
// counts and descriptions stay in sync with profiles/*.json.
function fallbackProfiles() {
  return [
    {
      "id": "windows",
      "name": "Windows 11",
      "description": "还原 Windows 11 常用快捷键（Alt+F4 关闭窗口、Super+方向键贴靠、Super+E 文件管理器等；锁屏沿用 Omarchy 自带的 Super+Ctrl+L）",
      "bindings_count": 18,
      "display": { "icon": "⊞", "brief": "WIN", "color": "#3892d6" }
    },
    {
      "id": "mac",
      "name": "macOS",
      "description": "还原 macOS 常用快捷键（Cmd 键转发、Super+Shift+4 区域截图、Super+Ctrl+Q 锁屏、Super+Up 任务概览等）",
      "bindings_count": 37,
      "display": { "icon": "◆", "brief": "MAC", "color": "#d8dee9" }
    },
    {
      "id": "omarchy",
      "name": "原生",
      "description": "Omarchy 原生快捷键，不做任何覆盖，适合学习与对照",
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
    "id": "scrolling",
    "name": "滚动",
    "english": "Scrolling",
    "icon": "▥",
    "desc": "新常规窗口横向滚动排列"
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
    "name": "跟随模式",
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
  if (key === "scroll" || key === "scrolling") return "scrolling";
  if (key === "tile" || key === "tiled") return "tiled";
  return "follow-profile";
}

function resolvePolicyName(id, lang) {
  var key = normalizePolicy(id);
  var isEn = (lang === "en");
  for (var i = 0; i < DEFAULT_POLICIES.length; i++) {
    if (DEFAULT_POLICIES[i].id === key) {
      return (isEn && DEFAULT_POLICIES[i].english) ? DEFAULT_POLICIES[i].english : DEFAULT_POLICIES[i].name;
    }
  }
  return (isEn ? "Tiled" : "平铺");
}

function resolvePolicyIcon(id) {
  var key = normalizePolicy(id);
  for (var i = 0; i < DEFAULT_POLICIES.length; i++) {
    if (DEFAULT_POLICIES[i].id === key) return DEFAULT_POLICIES[i].icon;
  }
  return "◫";
}

function effWindowModeLabel(mode, lang) {
  var isEn = (lang === "en");
  if (mode === "floating") return (isEn ? "Floating" : "浮动");
  if (mode === "scrolling") return (isEn ? "Scrolling" : "滚动");
  return (isEn ? "Tiled" : "平铺");
}

var TRANSLATIONS = {
  // Modes & Profiles
  "模式": "Profiles",
  "原生": "Native",
  "Omarchy 原生模式": "Omarchy Native",
  "Windows 11": "Windows 11",
  "macOS": "macOS",
  "未知模式": "Unknown Mode",

  // Window Policies & Window Modes
  "窗口策略": "Window Policy",
  "跟随模式": "Follow",
  "平铺": "Tiled",
  "浮动": "Floating",
  "滚动": "Scrolling",
  "生效": "Effective",
  "生效：": "Effective: ",
  "生效: ": "effective: ",
  "已覆盖": "overridden",
  "已覆盖 · ": "overridden · ",
  "当前跟随 ": "Follows ",

  // Quick Actions & System
  "快捷入口": "Quick Actions",
  "系统": "System",
  "打开设置": "Open Settings",
  "速查表": "Cheat Sheet",
  "首次使用引导": "Onboarding Guide",
  "贴靠布局": "Snap Layouts",
  "概览": "Overview",
  "窗口标题栏": "Window Titlebars",
  "Dock 栏 (底栏)": "Dock",
  "还原 Omarchy 原生模式": "Restore Native Keybindings",
  "健康诊断": "System Diagnostics",
  "环境自检 (Doctor)": "System Diagnostics (Doctor)",

  // Status & Hints
  "当前": "Current",
  "自动": "Auto",
  "离开后回到": "returns to",
  "开启": "On",
  "关闭": "Off",
  "自动隐藏": "Autohide",
  "常驻": "Docked",
  "再按一次还原": "Click again to restore",
  "再按一次关闭": "Press again to close",
  "引擎": "Engine",
  "引擎已停止": "Engine stopped",
  "引擎未运行": "Engine not running",
  "OmniPal Engine 未运行": "OmniPal Engine Stopped",
  "原生零覆盖": "Zero native bindings overridden",
  "项快捷键已覆盖": "active bindings",
  "项快捷键": "bindings",
  "Hyprland 连通": "Hyprland connected",
  "未连接 Compositor": "Compositor disconnected",
  "运行时内存热切换引擎在线": "Runtime in-memory hot-switch engine active"
};

function t(text, lang) {
  if (lang === "en" && TRANSLATIONS[text]) {
    return TRANSLATIONS[text];
  }
  return text;
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

// 模式自带的 window_mode（跟随模式时生效）。profiles 为 omni-profile list --json 的结果；
// 缺省时 mac 为浮动，其余平铺。
function effectiveWindowMode(currentMode, profiles) {
  var key = String(currentMode || "").toLowerCase().trim();
  var list = profiles || [];
  for (var i = 0; i < list.length; i++) {
    if (list[i] && list[i].id === key) {
      var wm = list[i].window_mode;
      if (wm === "floating" || wm === "tiled" || wm === "scrolling") return wm;
    }
  }
  return key === "mac" ? "floating" : "tiled";
}

// 全局窗口策略：跟随模式时由模式自带的 window_mode 决定；平铺/浮动/滚动时全局覆盖。
function computeEffectiveMode(policy, currentMode, profiles) {
  var p = normalizePolicy(policy);
  if (p === "follow-profile") return effectiveWindowMode(currentMode, profiles);
  if (p === "floating") return "floating";
  if (p === "scrolling") return "scrolling";
  return "tiled";
}
