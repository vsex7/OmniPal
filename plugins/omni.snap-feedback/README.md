# omni.snap-feedback

OmniPal 分屏/吸附视觉动效反馈插件（Quickshell 插件）。

## 特性

- **轻量即时**：无键盘焦点的极速 Overlay 浮层，不阻断正常输入与窗口响应。
- **动效高亮**：在触发 `snap_left`、`snap_right`、`maximize_window` 等操作时展示类似 Windows 11 的高亮区域边界与过渡淡出。
- **双通道触发**：支持 `omarchy-shell shell summon omni.snap-feedback '{"zone":"left"}'` 与 tmpfs 状态文件通知。

## 呼出/测试

```bash
omarchy-shell shell summon omni.snap-feedback '{"zone":"left"}'
omarchy-shell shell summon omni.snap-feedback '{"zone":"right"}'
omarchy-shell shell summon omni.snap-feedback '{"zone":"maximize"}'
```
