# omni.mode-indicator

OmniPal 状态栏模式指示器插件。

## 功能

- 显示当前激活的快捷键模式（`windows` / `mac` / `omarchy`）
- 实时反映 Engine 运行状态
- 左键点击：轮转切换模式（omarchy → windows → mac → omarchy）
- 右键点击：触发 `omni-profile cheatsheet` 查看当前模式快捷键速查表
- 悬浮提示：显示模式名称、生效快捷键数量、操作说明

## 状态来源

优先读取 Engine 广播的状态文件（快速路径）：
```
/run/user/$UID/omnipal/state.json
```

若状态文件不可用，回退到 CLI 命令：
```
omni-profile status --json
```

## 优雅降级

当 Engine 未运行时：
- 图标显示为 `⊘`（禁用符号），颜色为红色
- 标签显示 `OFF`
- 悬浮提示显示 "Engine 未运行" 及启动命令
- 不会抛出异常，不会导致 Shell 崩溃

## 视觉设计

| 模式 | 图标 | 主色调 | 标签 |
|------|------|--------|------|
| Windows | ⊞ | #0078d4 | WINDOWS |
| macOS | ◆ | #a2aaad | MAC |
| Omarchy | ⊡ | #a3be8c | OMARCHY |
| 禁用 | ⊘ | #bf616a | OFF |

## 安装

将 `plugins/omni.mode-indicator/` 目录复制到 Quickshell 插件加载路径，或在 bar 配置中引用 `ModeIndicator.qml`。

## 依赖

- `omni-profile` CLI（位于 PATH 中）
- OmniPal Engine（可选，未运行时优雅降级）
- Quickshell Io 模块（`Process`, `SplitParser`）

## 铁律遵守

- 不直接调用 `hyprctl`，不写入 `~/.config/hypr/`
- 仅通过 CLI 与 Engine 交互
- 不维护自己的键位副本
