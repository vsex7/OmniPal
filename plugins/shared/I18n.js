// I18n.js - shared internationalization dictionary and helper for OmniPal
.pragma library

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
  "运行时内存热切换引擎在线": "Runtime in-memory hot-switch engine active",

  // Settings Panel
  "OmniPal 控制中心": "OmniPal Control Center",
  "选项": "Options",
  "规则": "Rules",
  "固定入口（所有模式通用）：Super+Ctrl+/ 速查表 · Super+Alt+I 控制中心 · Super+Alt+O 概览": "Fixed shortcuts (all profiles): Super+Ctrl+/ Cheat Sheet · Super+Alt+I Settings · Super+Alt+O Overview",
  "配置持久化（关机/重启记忆）": "Configuration Persistence (Restore on boot)",
  "默认开启，关机或重启后自动恢复上次使用的模式与窗口策略；关闭时重启恢复默认。": "Enabled by default. Restores the last active profile and window policy on boot; disable to restore defaults.",
  "正在同步持久化状态…": "Syncing persistence state…",
  "已启用 · 自动记忆关机前配置：": "Enabled · Automatically remembers config before shutdown: ",
  "已禁用 · 关机/重启恢复默认，磁盘零残留": "Disabled · Restores default on reboot, zero disk footprint",
  "窗口贴靠快捷操作": "Snap Layout Quick Action",
  "无需记忆键位，随时呼出可视化贴靠布局菜单，纯键盘完成分屏贴靠。": "Invoke the visual snap layouts overlay at any time; position windows purely with keyboard.",
  "呼出贴靠布局菜单": "Invoke Snap Layouts Menu",
  "快捷键速查表 (S)": "Keybindings Cheat Sheet (S)",
  "按应用自动切换": "Auto Switch by Application",
  "已启用": "Enabled",
  "已停用": "Disabled",
  "没有匹配时：": "When no match:",
  "手动选择的模式": "Manually chosen profile",
  "精确": "Exact",
  "前缀": "Prefix",
  "正则": "Regex",
  "启用": "Enable",
  "停用": "Disable",
  "删除": "Delete",
  "窗口类名": "Window class",
  "添加规则": "Add Rule",
  "填入当前应用": "Fill active app",
  "添加": "Add",
  "取消": "Cancel",
  "切换": "Switch",
  "切换到 Omarchy 原生模式？将撤销全部快捷键覆盖。": "Switch to Omarchy Native profile? All keybinding overrides will be revoked.",
  "还没有规则。下面填好窗口类名和模式就能添加，比如 code 对应 mac。": "No rules yet. Enter window class and profile below to add one, e.g. code -> mac.",

  // Snap Feedback
  "按回车、点击或按对应数字直接贴靠": "Press Enter, click, or press number to snap",
  "1~6 模板": "1~6 Templates",
  "模板": "Templates",
  "贴靠": "Snap",
  "退出": "Exit",

  // Cheat Sheet
  "快捷键速查表": "Keybindings Cheat Sheet",
  "搜索 · /": "Search · /",
  "上手指南": "Onboarding Guide",
  "Esc 关闭 · / 搜索 · Tab 切分类 · R 刷新 · G 上手指南 · 按住 Super/Alt/Ctrl/Shift 高亮关联键位": "Esc: Close · /: Search · Tab: Category · R: Refresh · G: Guide · Hold Super/Alt/Ctrl/Shift to highlight",
  "知道了": "Got it"
};

function t(text, lang) {
  if (lang === "en" && TRANSLATIONS[text]) {
    return TRANSLATIONS[text];
  }
  return text;
}
