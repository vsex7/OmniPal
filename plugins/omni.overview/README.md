# OmniPal Overview (`omni.overview`)

现代化多任务全景空间概览与任务切换器（Exposé / Windows 11 Task View 风格）。

## 功能特性

- **高保真视觉设计**：参考现代任务切换舱设计，具有半透明磨砂遮罩、macOS 标题栏、应用矢量骨架图与纯白发光选中框。
- **零像素抓取 (Zero Pixel Screenshots)**：严格遵循 AGENTS.md H-5 铁律，纯基于 Compositor 矢量元数据渲染，零开销、零延迟。
- **全键盘流操作**：
  - 直接打字：任何字母/数字/空格都进入搜索（与 Omarchy 启动器一致，输入 `kitty`、`xterm` 不会触发动作）
  - `Tab` / `Shift+Tab` / 方向键（或 `Alt+h/j/k/l`）：在窗口间平滑穿梭
  - `Enter`：聚焦选定窗口并退出概览
  - `Esc`：取消待确认的关闭 → 清空搜索 → 关闭概览
  - `Delete` / `Alt+x`：关闭选中窗口——首次按下提示“再按一次关闭”，约 2 秒内再按才真正关闭（关闭无法撤销）
  - `Alt+m`：把选中窗口发送到另一个工作区
  - `Alt+1-9`：直达第 N 个窗口（与控制中心模式 `1-9` 同一范围；纯数字进入搜索）
  - `Backspace`：只删除搜索字符，不会关闭窗口
  - 鼠标左键：直接点击窗口聚焦激活
- **多显示器支持**：自动适配所有连接的输出屏幕。

## 快捷键

- Windows 模式：`Super + Tab`
- macOS 模式：`Super + Tab`
- 命令行唤出：`omarchy-shell shell toggle omni.overview`
