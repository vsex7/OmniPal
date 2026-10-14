# omni.settings

OmniPal 模式控制中心与设置面板（Quickshell 插件）。

## 特性

- **三分类 Tab 控制中心**：顶部平滑滑动的分类导航——🎯 模式方案 / ⚙️ 高级选项 / 📊 使用洞察，切换带淡入缩放过渡。
- **模式卡片网格**：从 `omni-profile list --json` 动态枚举内置与用户自定义模式；活动模式高亮外边框 + “当前激活”标签，卡片悬停阴影升起，点击一键内存热切换，展示生效按键数与配置来源。
- **可选配置持久化**：iOS/macOS 风格滑动开关，经 `omni-profile persist status|enable|disable` 读写；开启后重启自动载入首选模式，关闭时保证磁盘零配置文件残留（默认零污染，符合 H-1）。
- **窗口吸附快捷操作**：一键呼出 Snap 布局菜单（以 `{"zone":"layouts"}` 载荷召唤 `omni.snap-feedback`）。
- **完整入口**：所有控制都在这里；状态栏右键菜单也提供模式、窗口策略、速查表、贴靠布局、概览、还原等常用功能，两处都可用。
- **窗口策略**：模式页内置 跟随模式 / 平铺 / 浮动 选择器（`omni-profile window-policy set …`），非跟随模式时标注「已覆盖」，模式卡片标注「已覆盖：全局平铺/浮动」。
- **Omarchy 原生模式 = 还原**：选择该模式卡片（经确认）即执行 `omni-profile restore`，不再有单独的还原按钮。
- **状态感知**：实时监听 `/run/user/1000/omnipal/state.json`，展示引擎 PID、生效按键数量与当前模式。
- **键盘直达**：
  - `1 ~ N`: 切换至第 N 个习惯模式（自动跳回模式方案页）
  - `Tab`: 循环切换三个分类页
  - `S`: 打开快捷键速查表
  - `Shift+R`: 切换到 Omarchy 原生模式（还原，需确认）
  - `Esc`: 退出面板

## 呼出方式

```bash
omarchy-shell shell toggle omni.settings
```
