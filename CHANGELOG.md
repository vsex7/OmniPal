# OmniPal 更新日志 (Changelog)

所有关键变更遵循语义化版本规范 (SemVer)。

---

## [v1.2.0] - 2026-09-15

### 🎛️ 托盘指示器与右键快捷面板 (System Tray & Context Menu Panel)
- **全面升级 `omni.mode-indicator`**：
  - 托盘常驻图标：集成字形图标与缩写标签，左键轮转模式、右键展开快捷面板、中键打开设置。
  - 右键快捷控制面板：基于 Omarchy `PopupCard` 容器规范深度定制，支持点击外部区域自动收起（`HyprlandFocusGrab`），与状态栏弹窗互斥协调（`bar.requestPopout`）。
  - 四大功能区块：
    - **Hero 概览区**：当前活动模式专属图标、全名、状态健康指示灯及生效快捷键计数。
    - **模式快速切换区 (PROFILES)**：基于单一事实源 `omni-profile list --json` 动态枚举所有内置与自定义模式，当前活动项带对勾高亮，支持一键热切换。
    - **快捷功能入口 (ACTIONS)**：快速呼出速查表 (`omni.cheat-sheet`)、控制中心 (`omni.settings`)、任务视图 (`omni.overview`) 及窗口吸附反馈 (`omni.snap-feedback`)。
    - **系统与控制 (SYSTEM)**：支持正反向模式轮转、系统原生按键还原（0 残留）、健康诊断 (`omni-profile doctor`)。
- **配置显示元数据标准 (SSOT Display Metadata)**：
  - `profiles/*.json` 引入可选 `"display": {"icon": "...", "brief": "...", "color": "..."}`，彻底消除前端硬编码。
  - `engine.py` 与 `scripts/check_consistency.py` 全面支持与校验 `display` 元数据。
  - `Model.js` 纯函数模块提供基于 ID 哈希的优雅图标、缩写与主色调降级演算。
- **反向模式轮转 (`omni-profile cycle --reverse`)**：
  - 引擎与 CLI 工具扩展 `--reverse` 参数，支持逆向模式快速切换。

---

## [v1.1.0] - 2026-09-14

### 👤 用户自定义与模式覆盖 (User Custom Profiles)
- **用户配置目录支持**：支持从 `~/.config/omnipal/profiles/*.json`（支持 `OMNIPAL_USER_PROFILES_DIR` 环境变量覆盖）自动加载自定义配置模式。
- **配置覆盖与新模式扩展**：同名 `id` 自动优先覆盖系统内置预设，新 `id` 自动注册为可切换与可循环模式。
- **配置文件编目查看**：新增 `omni-profile list [--json]` 命令，输出所有模式元数据、来源渠道（project/user）及覆盖标记。
- **动态模式轮转**：`cycle_mode` 与顶栏指示器动态感知所有用户模式，顺序为 `omarchy -> windows -> mac -> [自定义模式按字典序] -> omarchy`。
- **顶栏指示器适配**：`omni.mode-indicator` 针对未知自定义模式提供优雅图标降级（`◇`）与前缀大写缩写。
- **校验工具增强**：`scripts/check_consistency.py` 与自动化单元测试全面覆盖用户配置文件的合法性验证与错误阻断。

### 🪟 丰富窗口吸附布局 (Rich Snap Layouts)
- **五种全新窗口吸附动作**：
  - `snap_center` (`omni-profile snap center`)：窗口居中展示（屏幕有效区域 60% 宽、70% 高度浮动展示）。
  - `snap_third_left` (`omni-profile snap third-left`)：窗口吸附并缩放至左侧 1/3。
  - `snap_third_right` (`omni-profile snap third-right`)：窗口吸附并缩放至右侧 1/3。
  - `snap_two_thirds_left` (`omni-profile snap two-thirds-left`)：窗口吸附并缩放至左侧 2/3。
  - `snap_two_thirds_right` (`omni-profile snap two-thirds-right`)：窗口吸附并缩放至右侧 2/3。
- **纯 Compositor 级 Lua 几何计算**：基于 Hyprland Lua 原生 `hl.dsp.window.resize` 与 `hl.dsp.window.move`，实时感知显示器 `reserved` 保留区域（避开 Omarchy 26px 顶栏），零延迟执行，坚守 Hard Stop H-1（零文件写入）。
- **HUD 吸附视觉反馈同步**：`omni.snap-feedback` 新增对居中、1/3 与 2/3 区域的高亮动效几何演算，平滑半透明过渡。

---

## [v1.0.0] - 2026-09-14

### 🚀 核心架构与运行时 (Phase 0)
- **纯内存热加载引擎**：通过 Omarchy Hyprland Lua 引擎 (`hyprctl eval`) 实施按键动态注入与解绑，热切换延迟低于 5ms。
- **单源标准 Schema (`schema/actions.json`)**：统一归一化 19 项窗口、分屏、导航、应用及系统主控动作。
- **三大习惯模式 Profile**：
  - `windows`：Windows 11 习惯模式（Alt+F4、Win+方向键、Win+E、Ctrl+Shift+Esc 等）。
  - `mac`：macOS 习惯模式（Super+Q、Super+Space、Super+Shift+3/4、Super+Up 等）。
  - `omarchy`：原生无拦截平铺模式。
- **原子状态广播**：运行时状态位于 `/run/user/$UID/omnipal/state.json` (tmpfs)，实现 Quickshell 与 CLI 的零轮询通信。
- **信号安全恢复机制**：捕获 SIGINT/SIGTERM/SIGHUP 与 atexit，异常退出自动回退至基线。

### 🧩 Quickshell 专属插件 (Phase 1 & Phase 2)
- **`omni.mode-indicator`**：Top Bar 状态栏指示器，展示当前习惯模式与状态，支持左/中/右键交互。
- **`omni.cheat-sheet`**：快捷键 HUD 速查层，支持按分类检索与实时模糊搜索。
- **`omni.settings`**：图形化设置与配置面板，支持模式切换、状态监测与一键还原。
- **`omni.snap-feedback`**：分屏视觉高亮反馈 HUD，支持半透明动画与 400ms 自动平滑淡出。
- **`omni.overview`**：基于 `hyprctl clients` 的零截图任务视图，符合 Hard Stop H-2，支持工作区筛选与 Del 关闭。
- **`omni.mac-dock`**：居中悬浮 Dock 栏，支持已运行窗口聚合与一键聚焦。

### 🛡️ 深度打磨与稳定性加固 (Phase P)
- **Hyprland Socket2 动态解析与自愈守护**：实时监听 `configreloaded>>`，重载配置后自动重新覆盖活动快捷键。
- **失败回滚 (Rollback on Error)**：`switch_mode` 若遇底层执行异常，自动回滚至基线，杜绝半应用状态。
- **系统诊断工具 (`omni-profile doctor`)**：一键检查 Daemon、Socket2 连通性、Live Binds 匹配度与 Schema 一致性。
- **去本机化规范**：移除所有硬编码绝对路径，规范化安装脚本与文档。

### 📊 质量门禁与工程化验证 (Phase Q)
- **一键发布门禁脚本 (`scripts/release-check.sh`)**：涵盖一致性、单元测试、基准延迟门禁与静态合规。
- **详尽基准测试报告 (`docs/BENCHMARK.md`)**：提供 10 轮测试数据与毫秒级图表。
- **已知限制说明书 (`docs/KNOWN_ISSUES.md`)**：说明环境依赖与边界。
- **验收报告 (`docs/ACCEPTANCE_REPORT.md`)**：全项完成真机清单验收。
