# OmniPal 完整参考

> **肌肉记忆无缝漫游，零配置污染的跨系统快捷键适配框架**  
> 专为 **Omarchy / Hyprland** 深度定制 · 正式版本 **v1.9.0**

OmniPal 为习惯了 **Windows 11** 或 **macOS** 桌面快捷键与操作习惯的用户，在 Omarchy (Arch Linux + Hyprland + Quickshell) 上提供瞬时、无感、零污染的肌肉记忆还原方案。

---

## 🌟 核心特性

- **纯内存热加载（Zero Config Pollution）**：
  - 基于 Omarchy Hyprland Lua 引擎（`hyprctl eval`）进行底层按键绑定与解绑。
  - 极速切换延迟 **< 5ms**，无屏幕闪烁，无需 reload 配置。
  - **绝不写入任何文件** 至 `~/.config/hypr/`，退出或还原时 100% 恢复基线状态（Hard Stop H-1/H-8 保证）。
- **三大内置习惯模式 + 自定义配置支持**：
  - **Windows 11 习惯模式 (`windows`)**：Alt+F4 关闭窗口、Win+方向键智能吸附、Win+E 文件管理器、Win+Tab 任务视图、Win+V 剪贴板、Win+I 设置中心等。
  - **macOS 习惯模式 (`mac`)**：Super+Q 退出程序、Super+空格启动器、Super+Shift+3/4 截图、Super+Up 调度中心、Super+Opt+D 呼出 Dock、Super+, 偏好设置等。
  - **Omarchy 原生模式 (`omarchy`)**：零拦截、零覆盖，纯粹的 Hyprland 原生平铺体验。
  - **用户自定义与覆盖模式**：支持 `~/.config/omnipal/profiles/*.json`，可任意添加专属模式（如 Vim 风格）或按 `id` 覆盖内置预设，支持自动无缝轮转。
- **丰富窗口吸附布局（Rich Snap Layouts）**：
  - 提供 `left`、`right`、`up`、`down`、`center`（60%x70% 居中展示）、`third-left` / `third-right`（1/3 屏幕分屏）、`two-thirds-left` / `two-thirds-right`（2/3 屏幕分屏）。
  - 基于 Compositor 级 Lua 几何运算，自动扣除 Omarchy 顶栏 `reserved` 区域，执行延迟低于 1ms。
- **可视化吸附布局选择器（Snap Layouts Picker）**：
  - **Windows 11 Snap Layouts 风格两级交互**：`Win+Z`（Windows 模式）/ `Super+Alt+Z`（macOS 模式）呼出布局菜单，数字键 `1-6` 选模板、方向键聚焦分区、回车吸附、`Esc` 取消。
  - 单一事实源 `schema/snap_layouts.json`：30 个规范分区 + 6 套布局模板，经 tmpfs 缓存由插件响应式渲染，QML 零硬编码。
- **内存级状态广播（tmpfs）**：
  - 运行时状态存储于 `/run/user/$UID/omnipal/state.json`。
  - Quickshell 插件通过 `Quickshell.Io.FileView` 响应更新，无需后台密集轮询。
- **配置持久化（Persistence，默认开启）**：
  - v1.9.0 起持久化默认开启：`switch` / `cycle` / `restore` / `window-policy set` 成功后，自动把当前模式（profile）与窗口策略（window policy）写入唯一文件 `~/.config/omnipal/persistence.json`（支持 `OMNIPAL_CONFIG_DIR` 重定向；字段：`enabled` / `profile` / `window_policy` / `updated_at`），重启后 daemon 据此恢复上次配置。可用 `omni-profile persist disable` 关闭（写入 `enabled:false` 标记，禁用后不再记录）。
  - 持久化仅写该一个文件（纯本地，零上传）；`persist enable`（缺省记录当前模式，可指定模式名；非法模式将被拒绝）可重新开启并快照指定模式/策略。
- **全套 Quickshell 专属插件**：
  1. `omni.mode-indicator`：Omarchy Top Bar 托盘模式指示器与右键快捷控制面板。左键循环轮转模式、右键弹出精致快捷面板（模式一键切换、快捷入口、系统诊断与控制）、中键设置，深度集成 `PopupCard` 与焦点自动收起。
  2. `omni.cheat-sheet`：快捷键 HUD 速查层，根据单一事实源动态渲染当前有效键位，支持按分类检索与按键说明。
  3. `omni.settings`：图形化控制中心，可视化切换模式，预览按键覆盖并提供快捷动作。
  4. `omni.snap-feedback`：分屏动效反馈 HUD，触发窗口吸附时在屏幕边缘渲染平滑高亮过渡动画。
  5. `omni.overview`：空间多工作区任务视图。工作区按 16:9 画布卡片自动平铺，窗口依 Compositor 矢量元数据（`hyprctl --batch`）映射真实相对位置，**严守 Hard Stop H-5，零像素截图**，支持 `1-9` 直达桌面、`Shift+1-9` 跨桌面瞬移与实时搜索。
  （注：底部 Dock 由 Omarchy 4.5 官方原生提供并深度集成，无需第三方插件）。

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
- 挂载全套 5 个 Quickshell 插件至 `~/.config/omarchy/plugins/`
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

# 列出规范吸附布局编目（6 模板 × 37 分区，--json 机器可读输出）
omni-profile snap-layouts

# 执行系统健康诊断与一致性校验
omni-profile doctor

# 解除置顶固定窗口（支持当前焦点窗口、指定窗口地址或 --all 解除全部）
omni-profile unpin
omni-profile unpin --all

# 执行微秒级性能基准测试
omni-profile benchmark

# 查看配置持久化状态（默认开启；禁用后写入 enabled:false 标记）
omni-profile persist status

# 启用/重新启用持久化（缺省记录当前模式，可指定模式名；非法模式将被拒绝）
omni-profile persist enable mac
omni-profile persist enable mac --policy floating   # 同时记住窗口策略（follow-profile / tiled / scrolling / floating）

# 窗口策略：查看；设置为 跟随模式 / 平铺 / 滚动 / 浮动（平铺、滚动或浮动会覆盖各模式自带的设置，UI 标注「已覆盖」）
omni-profile window-policy
omni-profile window-policy set follow-profile

# 关闭持久化（写入 enabled:false 标记，不再自动记录模式与策略）
omni-profile persist disable

# 瞬间还原至 Omarchy 原生快捷键
omni-profile restore

# 把一组快捷键转发给当前窗口（终端自动改为 Ctrl+Shift，如 omni-profile send CTRL W）
omni-profile send <修饰键> <按键> [--class <窗口类名>]

# 列出某个模式会接管哪些 Omarchy 原生快捷键（及它们原来的功能，--json 机器可读输出）
omni-profile diff <模式>

# 按应用自动切换模式的规则管理（详见 docs/APP_RULES.md）
omni-profile rules list
omni-profile rules add <应用类名> <模式>
omni-profile rules remove <应用类名>
omni-profile rules test <应用类名>

# 导出 / 导入自定义模式（导入含自定义命令的模式时需确认，或加 -y）
omni-profile export <模式>
omni-profile import <文件> [-y]

# 在 Omarchy 菜单（Super+Space）的 Setup 下注册/移除「快捷键模式」、查看状态
omni-profile menu install|uninstall|status

# 首次上手指南：查看状态 / 下次登录再显示 / 标记已显示（插件调用）
omni-profile onboarding status|reset|claim

# 前台运行守护进程（监听 Hyprland 事件、配置重载后自动恢复模式；通常由 systemd 服务启动）
omni-profile daemon
```

### 3. Quickshell 交互呼出

```bash
# 呼出模式控制中心
omarchy-shell shell toggle omni.settings

# 呼出快捷键速查表 HUD
omarchy-shell shell toggle omni.cheat-sheet

# 呼出多任务概览（Windows 下按 Super+Tab，macOS 下按 Super+Up 亦可直达）
omarchy-shell shell toggle omni.overview

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
│   ├── windows.json          # Windows 11 习惯模式（18 覆盖）
│   └── mac.json              # macOS 习惯模式（21 覆盖）
├── engine/
│   └── engine.py             # 核心运行时引擎（Lua 批量求值、信号捕获与 tmpfs 广播）
├── bin/
│   └── omni-profile          # 用户主 CLI 工具
├── plugins/
│   ├── omni.mode-indicator/  # 顶栏模式指示器
│   ├── omni.cheat-sheet/     # 快捷键 HUD 速查表
│   ├── omni.settings/        # 图形控制中心面板
│   ├── omni.snap-feedback/   # 窗口吸附视觉反馈 HUD
│   └── omni.overview/        # 多任务视图（零截图设计）
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
1. **[H-1] 零配置篡改**：运行态绝不向 `~/.config/hypr/` 写入任何配置文件；持久化默认开启，仅写 `~/.config/omnipal/persistence.json`（纯本地，零上传），可用 `omni-profile persist disable` 关闭。
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
6. 清理持久化配置 `~/.config/omnipal/persistence.json`（以及旧版本遗留的 `stats.json`）（配置目录为空时一并移除）

保证系统零文件残留，还原至完全初始状态。
