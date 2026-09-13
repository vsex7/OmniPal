# omni.settings

OmniPal 模式控制中心与设置面板（Quickshell 插件）。

## 特性

- **图形化模式切换**：一键在 Windows 11 / macOS / Omarchy 原生快捷键模式之间无缝切换。
- **内存热载无刷新**：通过 `omni-profile switch` 调度 Hyprland Lua 引擎，< 2ms 内存极速生效。
- **状态感知**：实时监听 `/run/user/1000/omnipal/state.json`，展示当前生效按键数量及引擎状态。
- **键盘直达**：
  - `1`: 切换至 Windows 11 习惯模式
  - `2`: 切换至 macOS 习惯模式
  - `3`: 切换至 Omarchy 原生模式
  - `S`: 打开快捷键速查表
  - `R`: 一键还原原生模式
  - `Esc`: 退出面板

## 呼出方式

```bash
omarchy-shell shell toggle omni.settings
```
