# omni.settings

OmniPal 模式控制中心与设置面板（Quickshell 插件）。

## 特性

- **三分类 Tab 控制中心**：顶部平滑滑动的分类导航——🎯 模式方案 / ⚙️ 高级选项 / 📊 使用洞察，切换带淡入缩放过渡。
- **模式卡片网格**：从 `omni-profile list --json` 动态枚举内置与用户自定义模式；活动模式高亮外边框 + “当前激活”标签，卡片悬停阴影升起，点击一键内存热切换，展示生效按键数与配置来源。
- **可选配置持久化**：iOS/macOS 风格滑动开关，经 `omni-profile persist status|enable|disable` 读写；开启后重启自动载入首选模式，关闭时保证磁盘零配置文件残留（默认零污染，符合 H-1）。
- **窗口吸附快捷操作**：一键呼出 Snap 布局菜单（以 `{"zone":"layouts"}` 载荷召唤 `omni.snap-feedback`）。
- **系统原生还原入口**：`omni-profile restore` 撤销全部内存覆盖，零残留恢复 Omarchy 原生按键。
- **使用洞察**：`omni-profile stats --json` 本地统计——累计总操作数 / 上次更新 / 上次重置摘要、模式切换排行与常用吸附区域 Top 榜（进度条可视化），支持一键 `stats --reset`。完全本地聚合计数，零按键内容记录。
- **状态感知**：实时监听 `/run/user/1000/omnipal/state.json`，展示引擎 PID、生效按键数量与当前模式。
- **键盘直达**：
  - `1 ~ N`: 切换至第 N 个习惯模式（自动跳回模式方案页）
  - `Tab`: 循环切换三个分类页
  - `S`: 打开快捷键速查表
  - `R`: 一键还原原生模式
  - `Esc`: 退出面板

## 呼出方式

```bash
omarchy-shell shell toggle omni.settings
```
