# OmniPal 已知限制与运行环境说明 (Known Issues & Limitations)

本文档列出 OmniPal v1.0.0 的设计边界、软硬件依赖要求及已知限制。

---

## 一、运行环境与系统依赖

| 组件 | 最低要求 | 说明 |
|:---|:---|:---|
| **操作系统** | Arch Linux / Omarchy | 目前深度针对 Omarchy 发行版架构优化 |
| **合成器 (WM)** | Hyprland >= 0.56.2 | 必须支持 Lua 脚本引擎 (`hyprctl eval`) |
| **显示服务** | Wayland 原生 | 不支持 X11 / Xwayland 独立窗管 |
| **Shell 框架** | Quickshell (Omarchy Shell) | 用于宿主运行 6 个 Quickshell 插件 |
| **Python 运行时** | Python >= 3.10 | 标准库即可，无任何三方 pip 依赖 |

---

## 二、架构设计与行为边界

### 1. 零持久化与配置零写入（Zero Config Pollution）
- **设计原则**：严格遵守 Hard Stop H-1，OmniPal **永远不写入** `~/.config/hypr/` 中的任何文件。
- **冷启动与重启行为**：当 Hyprland 完全关闭或系统重启后，内存中的按键覆盖自然消失。
- **自愈与保持**：建议启用 systemd 用户服务 `systemctl --user enable --now omnipal.service` 或运行 `omni-profile daemon`，通过 UNIX Socket 监听 Hyprland 重载事件并自动恢复生效模式。

### 2. 按键叠加与冲突机制（Takeover vs Coexistence）
- **Hyprland 行为**：Hyprland 在同一快捷键（如 `SUPER + LEFT`）上允许多个分发器同时注册。
- **OmniPal 对策**：
  - OmniPal 的模式 Profile（Windows / macOS）主要使用该系统特有的习惯组合（例如 `ALT + F4`、`SUPER + E`、`SUPER + Q` 等）。
  - 执行 `omni-profile restore` 时，会通过 `hl.unbind` 撤销 OmniPal 所注入的所有热绑定。
  - 用户可随时运行 `omni-profile doctor` 诊断当前生效热键与底层合成器的匹配状态。

### 3. 多显示器与缩放适配
- 插件（任务视图、窗口吸附反馈 HUD、Dock）依赖 Quickshell 提供的屏幕几何信息，在极端动态热插拔或多显示器异构缩放（Mixed DPI）场景下，窗口层可能有一过性的位置重新吸附过程。

---

## 三、故障排除指南 (Troubleshooting)

1. **按键没有生效？**
   - 运行 `omni-profile doctor` 检查 Hyprland Socket2 连通性以及当前生效状态。
   - 检查是否有其他应用占用了全局全局独占热键。
2. **快捷键失效后如何一键还原？**
   - 执行 `omni-profile restore`，或按下状态栏指示器切换回 `omarchy` 原生模式。
3. **插件无法显示？**
   - 确保执行过 `bash scripts/install.sh`，使插件软链接到 `~/.config/omarchy/plugins/`。
