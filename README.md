# OmniPal

> **肌肉记忆无缝漫游，零 Hyprland 配置污染的跨系统快捷键适配框架**
> 专为 **Omarchy / Hyprland** 深度定制 · 正式版本 **v1.8.0**

OmniPal 为习惯了 **Windows 11** 或 **macOS** 桌面快捷键与操作习惯的用户，在 Omarchy (Arch Linux + Hyprland + Quickshell) 上提供瞬时、无感、零 Hyprland 配置污染的肌肉记忆还原方案。

---

## 🌟 核心特性

- **纯内存热加载（Zero Config Pollution）**：
  - 基于 Omarchy Hyprland Lua 引擎（`hyprctl eval`）进行底层按键绑定与解绑。
  - 热态切换典型延迟 **< 5ms**，发布门禁允许含首次冷启动的单次路径最高 10ms，无屏幕闪烁。
  - **绝不写入任何文件** 至 `~/.config/hypr/`，退出或还原时 100% 恢复基线状态（Hard Stop H-1/H-8 保证）。
- **三大内置习惯模式 + 自定义配置支持**：
  - **Windows 11 习惯模式 (`windows`)**：Alt+F4 关闭窗口、Win+方向键智能吸附、Win+E 文件管理器、Win+Tab 任务视图、Win+V 剪贴板、Win+I 设置中心等。
  - **macOS 习惯模式 (`mac`)**：Super+Q 退出程序、Super+空格启动器、Super+Shift+3/4 截图、Super+Up 调度中心、Super+Opt+D 呼出 Dock、Super+, 偏好设置等。
  - **Omarchy 原生模式 (`omarchy`)**：零拦截、零覆盖，纯粹的 Hyprland 原生平铺体验。
  - **用户自定义与覆盖模式**：支持 `~/.config/omnipal/profiles/*.json`，可任意添加专属模式（如 KDE Plasma、Vim 风格）或按 `id` 覆盖内置预设，支持自动无缝轮转。
- **丰富窗口吸附布局（Rich Snap Layouts）**：
  - 提供 `left`、`right`、`up`、`down`、`center`（60%x70% 居中展示）、`third-left` / `third-right`（1/3 屏幕分屏）、`two-thirds-left` / `two-thirds-right`（2/3 屏幕分屏）。
  - 基于 Compositor 级 Lua 几何运算，自动扣除 Omarchy 顶栏 `reserved` 区域，执行延迟低于 1ms。
- **可视化吸附布局选择器（Snap Layouts Picker）**：
  - **Windows 11 Snap Layouts 风格两级交互**：`Win+Z`（Windows 模式）/ `Super+Alt+Z`（macOS 模式）呼出布局菜单，数字键 `1-6` 选模板、方向键聚焦分区、回车吸附、`Esc` 取消。
  - 单一事实源 `schema/snap_layouts.json`：37 个规范分区 + 6 套布局模板，经 tmpfs 缓存由插件响应式渲染，QML 零硬编码。
- **内存级状态广播（tmpfs）**：
  - 运行时状态存储于 `/run/user/$UID/omnipal/state.json`。
  - Quickshell 插件通过 `Quickshell.Io.FileView` 响应更新，无需后台密集轮询。
- **配置持久化（Persistence，默认开启）**：
  - 默认开启以保证关机与重启后体验一致（自动记忆关机前的 Profile 与 Window Policy），严格隔离保存于 `~/.config/omnipal/persistence.json`（绝不写入 `~/.config/hypr/`，符合 H-1 铁律）；支持 `OMNIPAL_CONFIG_DIR` 重定向。
  - `switch` / `window-policy` 调整后自动同步；亦可随时执行 `omni-profile persist disable` 关闭并保持纯内存零写入。
- **本地使用统计（Local Usage Statistics，纯本地零上传）**：
  - 仅记录模式切换、吸附区域与动作触发的聚合计数，写入 `~/.config/omnipal/stats.json`，零按键内容、零网络通信。
  - 统计读写全程静默容错，任何异常都不影响热切换与吸附执行（延迟指标 < 10ms 不回归）。
- **全套 Quickshell 专属插件**：
  1. `omni.mode-indicator`：Omarchy Top Bar 托盘模式指示器与右键快捷控制面板。左键循环轮转模式、右键弹出精致快捷面板（模式一键切换、快捷入口、系统诊断与控制）、中键设置，深度集成 `PopupCard` 与焦点自动收起。
  2. `omni.cheat-sheet`：快捷键 HUD 速查层，根据单一事实源动态渲染当前有效键位，支持按分类检索与按键说明。
  3. `omni.settings`：图形化控制中心，可视化切换模式，预览按键覆盖并提供快捷动作。
  4. `omni.snap-feedback`：分屏动效反馈 HUD，触发窗口吸附时在屏幕边缘渲染平滑高亮过渡动画。
  5. `omni.mac-dock`：macOS 风格底部浮动 Dock 栏，实时展示运行中应用图标、运行指示圆点与平滑悬停动效。
  6. `omni.overview`：零截图的多工作区空间概览，仅使用 Hyprland 窗口元数据。

---

## 🚀 快速上手

### 1. 一键安装部署

```bash
git clone https://github.com/vsex7/OmniPal.git
cd OmniPal
bash scripts/install.sh
```

安装程序会自动执行：
- 校验 JSON Schema、按键定义与所有 Quickshell 插件完整性
- 创建 CLI 软链接至 `~/.local/bin/omni-profile`
- 挂载全套 6 个 Quickshell 插件至 `~/.config/omarchy/plugins/`
- 配置可选的 systemd 用户常驻单元 `omnipal.service`

### 2. 命令行使用

```bash
# 列出所有可用模式（内置与用户自定义）
omni-profile list

# 查看当前生效模式与按键数量
omni-profile status

# 切换至 Windows 11 习惯模式
omni-profile switch windows

# 切换至 macOS 习惯模式
omni-profile switch mac

# 轮转切换模式 (Omarchy -> Windows -> macOS -> 用户自定义 -> Omarchy)
omni-profile cycle

# 查看当前模式的快捷键速查表（终端高亮输出）
omni-profile cheatsheet

# 窗口智能吸附（支持 left/right/up/down/center/third-left/third-right/two-thirds-left/two-thirds-right）
omni-profile snap center

# 列出规范吸附布局编目（6 模板 × 30 分区，--json 机器可读输出）
omni-profile snap-layouts

# 执行系统健康诊断与一致性校验
omni-profile doctor

# 执行微秒级性能基准测试
omni-profile benchmark

# 查看配置持久化状态（默认开启，自动记住关机前配置）
omni-profile persist status

# 显式设置持久化（可指定模式与窗口策略）
omni-profile persist enable mac --policy floating

# 关闭持久化（切换为纯内存零写入模式，重启后恢复默认原生）
omni-profile persist disable

# 查看本地使用统计（模式切换频次排行、吸附区域 Top 榜，完全本地零上传）
omni-profile stats

# 一键清空并重置本地统计
omni-profile stats --reset

# 瞬间还原至 Omarchy 原生快捷键
omni-profile restore

# 手机同屏协同（需安装 scrcpy 与 adb，并在 devices.json 中配置设备）
omni-profile phone doctor
omni-profile phone list
omni-profile phone start [device-id]
omni-profile phone stop [device-id]
omni-profile phone toggle [device-id]
```

手机同屏的配置字段、安全边界与验收状态详见 [docs/PHONE_MIRROR.md](docs/PHONE_MIRROR.md)。

### 3. Quickshell 交互呼出

```bash
# 呼出模式控制中心
omarchy-shell shell toggle omni.settings

# 呼出快捷键速查表 HUD
omarchy-shell shell toggle omni.cheat-sheet

# 呼出 macOS 底部 Dock 栏（macOS 下按 Super+Alt+D 亦可直达）
omarchy-shell shell toggle omni.mac-dock

# 测试分屏高亮反馈
omarchy-shell shell summon omni.snap-feedback '{"zone":"left"}'

# 呼出可视化吸附布局选择器（等同 Win+Z / Super+Alt+Z 快捷键）
omarchy-shell shell summon omni.snap-feedback '{"zone":"layouts"}'
```

---

## 🏗️ 目录结构与单一事实源

```
OmniPal/
├── schema/
│   ├── actions.json          # 动作编目（单一事实源，定义 action_id、调度命令与默认参数）
│   └── snap_layouts.json     # 吸附分区与布局模板编目（布局几何单一事实源）
├── profiles/
│   ├── omarchy.json          # 原生模式（0 覆盖）
│   ├── windows.json          # Windows 11 习惯模式（14 覆盖）
│   └── mac.json              # macOS 习惯模式（19 覆盖）
├── engine/
│   ├── engine.py             # 核心运行时引擎（Lua 批量求值、信号捕获与 tmpfs 广播）
│   └── phone_runner.py       # 可选 scrcpy 多设备会话管理
├── bin/
│   └── omni-profile          # 用户主 CLI 工具
├── plugins/
│   ├── omni.mode-indicator/  # 顶栏模式指示器
│   ├── omni.cheat-sheet/     # 快捷键 HUD 速查表
│   ├── omni.settings/        # 图形控制中心面板
│   ├── omni.snap-feedback/   # 窗口吸附视觉反馈 HUD
│   ├── omni.overview/        # 多任务视图（零截图设计）
│   └── omni.mac-dock/        # macOS 风格底部 Dock 栏
├── scripts/
│   ├── install.sh            # 安装部署脚本
│   ├── uninstall.sh          # 干净卸载与还原脚本
│   └── check_consistency.py  # 模式、按键与插件一致性校验工具
├── tests/
│   └── test_omni.py          # 自动化单元测试套件
└── docs/                     # 架构规范与功能说明文档
```

---

## 🛡️ 严格设计约束与安全保证

根据 Omarchy 架构规范与 Hard Stop 铁律：
1. **[H-1] 零 Hyprland 配置篡改**：运行态绝不向 `~/.config/hypr/` 写入任何配置文件；持久化与本地统计严格保存在独立的 `~/.config/omnipal/`（纯本地，零上传），且用户可随时通过 `persist disable` 关闭。
2. **[H-5] 零像素截图**：`omni.overview` 与所有插件均通过 `hyprctl` 元数据渲染，避免截屏权限与 GPU 显存浪费。
3. **[H-3] 单一事实源**：键位逻辑全部收敛于 `schema/actions.json`，QML 插件内绝无按键硬编码。
4. **[H-7] Shell 配置文件隔离**：绝不篡改 `~/.config/omarchy/shell.json`，插件仅以标准符号链接安装在 `~/.config/omarchy/plugins/` 供 shell 动态挂载。
5. **[H-8] 100% 信号安全恢复**：引擎接收 `SIGINT`、`SIGTERM`、`SIGHUP` 信号或会话终止时，自动清空注入覆盖，无缝回退。

---

## 🧹 卸载

想要完全卸载 OmniPal 并还原一切：

```bash
bash scripts/uninstall.sh
```

卸载程序会：
1. 立即清除所有 Hyprland 内存键位覆盖
2. 停用并移除 systemd 守护进程
3. 移除 `~/.local/bin/omni-profile`
4. 移除 `~/.config/omarchy/plugins/` 下的所有软链接
5. 清理 `/run/user/$UID/omnipal` 运行时临时目录
6. 停止受管 `scrcpy` 进程，并清理 `persistence.json` / `stats.json` / `devices.json`（配置目录为空时一并移除）

保证系统零文件残留，还原至完全初始状态。
