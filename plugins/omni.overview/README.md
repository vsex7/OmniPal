# OmniPal Overview (`omni.overview`)

现代化多任务全景空间概览与任务切换器（Exposé / Windows 11 Task View 风格）。

## 功能特性

- **高保真视觉设计**：参考现代任务切换舱设计，具有半透明磨砂遮罩、macOS 标题栏、应用矢量骨架图与纯白发光选中框。
- **零像素抓取 (Zero Pixel Screenshots)**：严格遵循 AGENTS.md H-5 铁律，纯基于 Compositor 矢量元数据渲染，零开销、零延迟。
- **全键盘流操作**：
  - `Tab` / `Shift+Tab` / 方向键：在窗口间平滑穿梭
  - `Enter` / `Space`：聚焦选定窗口并退出概览
  - `Esc`：关闭概览
  - `Backspace` / `Delete` / `Q`：立即关闭当前选中的窗口
  - 数字键 `1-9`：直达第 N 个窗口
  - 鼠标左键：直接点击窗口聚焦激活；悬停卡片右上角快捷关闭
- **多显示器支持**：自动适配所有连接的输出屏幕。

## 快捷键

- Windows 模式：`Super + Tab`
- macOS 模式：`Super + Tab`
- 命令行唤出：`omarchy-shell shell toggle omni.overview`
