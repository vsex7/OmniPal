# omni.overview

OmniPal 任务视图与多窗口概览插件（Quickshell 插件）。

## 架构与铁律遵守

- **Hard Stop H-2 绝对遵守**：**零像素截图（Zero Pixel Screenshots）**。不调用 `grim`、`slurp`、`screencopy`，不占用 GPU 纹理缓存。
- **纯元数据驱动**：基于 `hyprctl clients -j` 实时获取窗口地址、标题、所属应用、工作区、尺寸与平铺状态。
- **极速响应**：毫秒级呼出，即时展示全部窗口卡片。
- **交互功能**：
  - 支持键盘上下左右箭头导航与 Enter 聚焦。
  - 支持按 Esc 退出。
  - 顶部集成实时搜索输入栏，快速按窗口标题/类名模糊过滤。
  - 鼠标左键点击卡片立即执行 `hyprctl dispatch focuswindow address:...` 并收起。
  - 卡片右上角 [✕] 按钮可快速关闭指定窗口。

## 呼出方式

```bash
omarchy-shell shell toggle omni.overview
```
也可以通过 Windows 模式下的 `Super+Tab` 呼出。
