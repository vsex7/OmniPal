# OmniPal

> **肌肉记忆无缝漫游，零配置污染的跨系统快捷键适配框架**  
> 专为 **Omarchy / Hyprland** 深度定制 · 架构版本 **v0.4**

OmniPal 为习惯了 **Windows 11** 或 **macOS** 桌面快捷键与操作习惯的用户，在 Omarchy (Arch Linux + Hyprland + Quickshell) 上提供瞬时、无感、零污染的肌肉记忆还原方案。

---

## 🌟 核心特性

- **纯内存热加载（Zero Config Pollution）**：
  - 基于 Omarchy Hyprland Lua 引擎（`hyprctl eval`）进行底层按键绑定与解绑。
  - 极速切换延迟 **< 2ms**，无屏幕闪烁，无需 reload 配置。
  - **绝不写入任何文件** 至 `~/.config/hypr/`，退出或还原时 100% 恢复基线状态（Hard Stop H-1/H-8 保证）。
- **三大习惯模式**：
  - **Windows 11 习惯模式 (`windows`)**：Alt+F4 关闭窗口、Win+方向键智能吸附、Win+E 文件管理器、Win+Tab 任务视图、Win+V 剪贴板、Win+I 设置中心等。
  - **macOS 习惯模式 (`mac`)**：Super+Q 退出程序、Super+空格启动器、Super+Shift+3/4 截图、Super+Up 调度中心、Super+Opt+D 呼出 Dock、Super+, 偏好设置等。
  - **Omarchy 原生模式 (`omarchy`)**：零拦截、零覆盖，纯粹的 Hyprland 原生平铺体验。
- **内存级状态广播（tmpfs）**：
  - 运行时状态存储于 `/run/user/$UID/omnipal/state.json`。
  - Quickshell 插件通过 `Quickshell.Io.FileView` 响应更新，无需后台密集轮询。
- **全套 Quickshell 专属插件（Phase 1 & 2）**：
  1. `omni.mode-indicator`：Omarchy Top Bar 状态栏指示器，展示当前模式，左键循环切换、右键速查表、中键设置。
  2. `omni.cheat-sheet`：快捷键 HUD 速查层，根据单一事实源动态渲染当前有效键位，支持按分类检索与按键说明。
  3. `omni.settings`：图形化控制中心，可视化切换模式，预览按键覆盖并提供快捷动作。
  4. `omni.snap-feedback`：分屏动效反馈 HUD，触发窗口吸附时在屏幕边缘渲染类 Windows 11 的高亮平滑过渡。
  5. `omni.overview`：多任务视图与窗口概览。纯元数据驱动（基于 `hyprctl clients -j`），**严守 Hard Stop H-2，零像素截图**，支持键盘选择与实时搜索。
  6. `omni.mac-dock`：macOS 风格底部浮动 Dock 栏，实时展示运行中应用图标、运行指示圆点与平滑悬停动效。

---

## 🚀 快速上手

### 1. 一键安装部署

```bash
cd /home/abyss/Projects/OmniPal
bash scripts/install.sh
```

安装程序会自动执行：
- 校验 JSON Schema、按键定义与所有 Quickshell 插件完整性
- 创建 CLI 软链接至 `~/.local/bin/omni-profile`
- 挂载全套 6 个 Quickshell 插件至 `~/.config/omarchy/plugins/`
- 配置可选的 systemd 用户常驻单元 `omnipal.service`

### 2. 命令行使用

```bash
# 查看当前生效模式与按键数量
omni-profile status

# 切换至 Windows 11 习惯模式
omni-profile switch windows

# 切换至 macOS 习惯模式
omni-profile switch mac

# 轮转切换模式 (Omarchy -> Windows -> macOS -> Omarchy)
omni-profile cycle

# 查看当前模式的快捷键速查表（终端高亮输出）
omni-profile cheatsheet

# 瞬间还原至 Omarchy 原生快捷键
omni-profile restore
```

### 3. Quickshell 交互呼出

```bash
# 呼出模式控制中心
omarchy-shell shell toggle omni.settings

# 呼出快捷键速查表 HUD
omarchy-shell shell toggle omni.cheat-sheet

# 呼出多任务概览（Windows 下按 Super+Tab，macOS 下按 Super+Up 亦可直达）
omarchy-shell shell toggle omni.overview

# 呼出 macOS 底部 Dock 栏（macOS 下按 Super+Alt+D 亦可直达）
omarchy-shell shell toggle omni.mac-dock

# 测试分屏高亮反馈
omarchy-shell shell summon omni.snap-feedback '{"zone":"left"}'
```

---

## 🏗️ 目录结构与单一事实源

```
OmniPal/
├── schema/
│   └── actions.json          # 动作编目（单一事实源，定义 action_id、调度命令与默认参数）
├── profiles/
│   ├── omarchy.json          # 原生模式（0 覆盖）
│   ├── windows.json          # Windows 11 习惯模式（13 覆盖）
│   └── mac.json              # macOS 习惯模式（12 覆盖）
├── engine/
│   └── engine.py             # 核心运行时引擎（Lua 批量求值、信号捕获与 tmpfs 广播）
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
1. **[H-1] 零配置篡改**：运行态绝不向 `~/.config/hypr/` 写入任何配置文件。
2. **[H-2] 零像素截图**：`omni.overview` 与所有插件均通过 `hyprctl clients -j` 元数据渲染，避免截屏权限与 GPU 显存浪费。
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
保证系统零文件残留，还原至完全初始状态。
