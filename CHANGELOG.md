# OmniPal 更新日志 (Changelog)

所有关键变更遵循语义化版本规范 (SemVer)。

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
