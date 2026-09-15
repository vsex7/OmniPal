# OmniPal 更新日志 (Changelog)

所有关键变更遵循语义化版本规范 (SemVer)。

---

## [v1.6.0] - 2026-09-15

### 🎛️ 界面升级：三 Tab 控制中心与 Dock 物理动效 — Milestone 4
- **omni.settings 三分类控制中心**：面板重构为 🎯 模式方案 / ⚙️ 高级选项 / 📊 使用洞察三分类导航，滑动指示胶囊与淡入缩放切页动效；模式页从 `omni-profile list --json` 动态枚举内置与用户自定义模式，卡片网格高亮活动模式（边框强化 + “当前激活”标签）、悬停阴影升起，展示生效按键数与配置来源，点击即内存热切换；新增数字键 `1~N` 直达切换与 `Tab` 循环切页。
- **持久化可视化控制**：iOS/macOS 风格滑动开关子进程直调 `omni-profile persist status --json / enable / disable`，操作后自动回读状态；文案明确“开启后重启自动载入首选模式；关闭时保证磁盘零配置文件残留”，默认零污染契约不变（H-1）。
- **使用洞察可视化**：`omni-profile stats --json` 呈现概览摘要（累计总操作数 / 上次更新 / 上次重置）、模式切换排行与常用吸附区域 Top 榜（按模式着色的进度条），`stats --reset` 一键重置后实时刷新；仅展示聚合计数，零按键内容记录。
- **快捷操作入口**：高级选项页集成“呼出 Snap 布局菜单”（以 `{"zone":"layouts"}` 载荷召唤 `omni.snap-feedback`，无 shell 时回退 `omarchy-shell` 通道）与“恢复 Omarchy 原生”还原卡片（`omni-profile restore`）。
- **omni.mac-dock 鱼眼波浪放大**：鼠标 X 坐标驱动高斯衰减连续缩放波（中心 1.35×、相邻按距离递减、自底边向上生长），跨格间隙 90ms 宽限期防抖，离开 Dock 时 `SpringAnimation` 弹簧衰减回落基线。
- **多窗口实例角标与轮转聚焦**：`rebuildItems()` 按应用 class 聚合窗口总数、地址列表与标题列表，实例数 > 1 时右上角胶囊角标；左键按顺序轮转聚焦窗口；右键弹出上下文动作卡片（聚焦前台 / 轮转下一窗口 / 新开实例 / 关闭该应用，多实例经 `hyprctl --batch` 批量 `dispatch closewindow`），`Esc` 或点击外部自动收起。
- **物理弹跳反馈**：点击激活 / 启动应用触发纵向 -13px 起跳 + OutElastic 阻尼回落弹跳，上下文卡片动作与主点击路径反馈一致；动作后 400ms 轻量回刷窗口列表。
- **规范与验证**：Dock 纯窗口元数据渲染（H-5）；设置面板从不直接修改绑定，所有写操作经 `omni-profile` 唯一修改权通道（§2 铁律）；`qmllint` 两面板零语法 / 零未知信号错误，`check_consistency.py` 100% 通过。

---

## [v1.5.0] - 2026-09-15

### 📊 本地使用统计 (Local Usage Statistics) — Milestone 3
- **隐私优先、纯本地**：使用数据仅写入 `~/.config/omnipal/stats.json`（支持 `OMNIPAL_CONFIG_DIR` 隔离），只记录模式/吸附区域/动作的聚合计数，**零按键内容记录、零网络上传**；绝不触碰 `~/.config/hypr/`（Hard Stop H-1）。
- **零开销容错**：`record_switch` / `record_snap` / `record_action` 全部异常静默吞掉，统计读写失败绝不阻塞或影响 `switch_mode` 与 `snap`；真机基准 Windows 切换 5.7ms / macOS 切换 4.8ms，持续满足 < 10ms 门禁。
- **引擎层统计 API**：
  - `stats_file_path()` 统一统计路径解析，遵循 `OMNIPAL_CONFIG_DIR` → `XDG_CONFIG_HOME` → `~/.config/omnipal` 优先级；
  - `get_stats()` 返回规范结构 `{switches, snaps, actions, last_updated, last_reset}`，文件缺失或损坏时安全回退全空结构；
  - `reset_stats()` 原子重置全部计数并记录 `last_reset`；
  - `switch_mode` 成功后自动累计对应模式计数；`snap` 每次触发按区域（`left` / `right` / `layouts` / `center` 等）自增。
- **CLI 统计命令**：`omni-profile stats [--json]` 输出模式切换频次排行、常用吸附区域 Top 榜与动作触发排行；`omni-profile stats --reset` 一键清空。
- **干净卸载承诺**：`scripts/uninstall.sh` 清理步骤扩展覆盖 `stats.json`（支持 `OMNIPAL_CONFIG_DIR` 重定向），配置目录为空时一并安全移除。
- **测试覆盖**：新增 `TestUsageStatistics`（6 项）：初始空结构零文件创建、switch/snap 自增、动作计数、reset、`OMNIPAL_CONFIG_DIR` 读写隔离，以及“统计目标不可写时 switch/snap 完全不受影响”的零影响保证；全套 31 项测试 100% 通过。

---

## [v1.4.0] - 2026-09-15

### 💾 可选配置持久化 (Opt-in Profile Persistence) — Milestone 2
- **默认零污染铁律不变（Hard Stop H-1）**：持久化默认关闭，运行时仍是纯内存热切换；仅在用户显式执行 `omni-profile persist enable` 后，才写入唯一文件 `~/.config/omnipal/persistence.json`，绝不触碰 `~/.config/hypr/`。
- **配置目录统一解析 (`resolve_config_dir()`)**：优先 `OMNIPAL_CONFIG_DIR` 环境变量（测试隔离），其次 `XDG_CONFIG_HOME`，默认 `~/.config/omnipal`。
- **引擎层持久化 API**：
  - `get_persistence_status()` 返回规范结构 `{enabled, profile, path, updated_at}`；
  - `set_persistence(enabled, profile)` 原子写入（tmp + rename）：profile 缺省时取当前激活模式（仍为空则回退 `windows`），非法/未知模式一律拒绝写入；关闭时彻底清理持久化文件；
  - `get_persisted_profile()` 供守护进程与启动项检测已启用的持久化模式。
- **切换自动同步**：`switch_mode` 成功后，若持久化已启用则自动将最新模式镜像更新至 `persistence.json`；未启用时保持零文件写入。
- **CLI 子命令**：新增 `omni-profile persist status [--json]` / `omni-profile persist enable [profile]` / `omni-profile persist disable`，人类可读输出与规范 JSON 双模式。
- **干净卸载承诺**：`scripts/uninstall.sh` 新增持久化清理步骤，删除 `persistence.json`（支持 `OMNIPAL_CONFIG_DIR` 重定向），配置目录为空时一并安全移除。
- **测试覆盖**：新增 `TestPersistenceManager`（`TemporaryDirectory` + `OMNIPAL_CONFIG_DIR` 隔离），覆盖默认禁用、enable/disable 往返、非法模式阻断、`switch_mode` 自动同步与环境变量读写隔离；全套 25 项测试 100% 通过。

---

## [v1.3.0] - 2026-09-15

### 📐 可视化窗口吸附布局与选择器 (Snap Layouts Picker)
- **Windows 11 Snap Layouts 风格两级交互**：`omni.snap-feedback` 升级为可视化吸附布局选择器——第一级横向并列展示布局模板，第二级在选中模板内高亮聚焦分区。数字键 `1-6` 直选模板、方向键切换模板/分区、回车执行吸附、`Esc` 取消，全程纯键盘流。
- **单一事实源布局编目 (`schema/snap_layouts.json`)**：收录 30 个规范吸附分区（半屏、四象限、1/3 与 2/3 分屏、居中浮窗、最大化/还原等）与 6 套布局模板（左右对半、主从分屏、三列均分、居中聚焦、四象限、反向主从），QML 零硬编码副本，符合 AGENTS.md 单一事实源铁律。
- **tmpfs 布局缓存分发**：引擎启动时把 zones/templates 写入 `/run/user/$UID/omnipal/snap_layouts.json`，插件经 `Quickshell.Io.FileView` 响应式加载，热切换零轮询。
- **CLI 编目查看**：新增 `omni-profile snap-layouts [--json]`，终端可枚举全部模板与分区几何。
- **吸附动作注册与还原安全**：`snap_layouts` 动作在 `windows` / `mac` 模式注册为运行时快捷键，Restore 路径完整清理，0 残留。

### 🌌 空间多工作区任务视图 (Spatial Workspace Overview)
- **`omni.overview` 空间化重构**：工作区以 16:9 画布卡片自动多行多列平铺（`Model.js calculateGrid`），窗口按显示器有效分辨率等比映射真实相对位置（`scaleWindowGeometry`），直观还原物理桌面空间排布。
- **矢量元数据渲染**：严守 Hard Stop H-5，零像素截图，基于 `hyprctl --batch` 一次批量取数（workspaces / clients / monitors / activewindow），零进程分叉、极轻量。
- **跨桌面键盘调度**：`Tab`/方向键轮转窗口、`1-9` 直达桌面、`Shift+1-9` 跨桌面瞬移、`Enter` 聚焦、`Del` 关闭、`Esc` 退出。

### ⌨️ 快捷键编目扩充
- 动作编目扩展至 32 项：新增 `snap_layouts`（布局选择器）、`snap_top` / `snap_bottom` 上下半屏、`snap_third_center` 中列三分屏、四象限 `snap_top_left` / `snap_top_right` / `snap_bottom_left` / `snap_bottom_right` 等。
- `windows` 模式：`Win+Z` 呼出吸附布局选择器；`mac` 模式：`Super+Alt+Z` 呼出选择器，`Super+Alt+↑ / ↓` 直达 `snap_top` / `snap_bottom`。

### 🛡️ 一致性校验器全面覆盖 snap_layouts.json
- `scripts/check_consistency.py` 新增布局编目深度校验：文件存在性与 JSON 合法性；每个 zone 的 `xr/yr/wr/hr` 必须落于 `[0.0, 1.0]` 且 `xr+wr <= 1.01`、`yr+hr <= 1.01`，`icon` / `label` 非空；每个 template 的 `id` 与 `key` 全局唯一、`title` / `hint` 非空、`slots` 数组非空；每个 slot 的 `id`、`label` 与坐标比例逐项合法。
- 任一异常即输出精确定位信息（zone/模板/槽位序号 + 字段）并以非零退出码阻断，发布门禁 Gate 1 与单元测试同步拦截。

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
