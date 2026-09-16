# omni.mode-indicator

OmniPal 状态栏托盘模式指示器与右键快捷控制面板。

## 功能特性

- **托盘常驻指示器 (BarWidget)**：
  - 实时显示当前激活的快捷键模式（`Windows` / `macOS` / `Omarchy` 及用户自定义模式）
  - 显示模式对应专属字形图标（`⊞` / `◆` / `⊡` / `◇`）与颜色标识
  - 毫秒级监听 `/run/user/$UID/omnipal/state.json`，零轮询开销
- **多功能鼠标交互**：
  - **左键单击**：快速轮转切换模式（`omni-profile cycle`）
  - **右键单击**：呼出/收起全新设计的 **右键快捷控制面板**（基于 Omarchy `PopupCard` 规范）
  - **中键单击**：直接打开 OmniPal 设置中心（`omarchy-shell shell toggle omni.settings`）
  - **悬浮提示 (Tooltip)**：显示当前模式详情、生效快捷键数量与按键提示
- **右键快捷控制面板 (Context Menu / Panel)**：
  1. **Hero 概览区**：当前模式图标、模式全名、模式缩写胶囊、生效绑定计数与 Compositor 连通状态，带关闭按钮
  2. **模式快速切换 (PROFILES)**：动态列出所有可用预设与自定义模式，当前活动模式带有 `✓` 标识与左侧颜色条，点击即切
  3. **窗口策略控制 (WINDOW POLICY)**：分段选择器快速切换平铺（Tiled）、浮动（Floating）或跟随模式（Follow-Profile），并动态呈现生效说明
  4. **快捷功能入口 (ACTIONS)**：
     - 📖 快捷键速查表 (Cheat Sheet)
     - ⚙️ OmniPal 控制中心 (Settings)
     - 🗂️ 任务视图 (Task View)
     - 🪟 触发布局吸附 (Snap Layout)
  5. **系统与控制 (SYSTEM)**：
     - ↻ 轮转切换下一模式
     - ↺ 还原原生快捷键（零残留热恢复）
     - 🩺 运行系统健康诊断 (Doctor)
- **优雅降级**：
  - Engine 未运行时显示 `⊘ OFF`，颜色置灰
  - 右键面板支持点击外部区域通过 `HyprlandFocusGrab` 自动平滑关闭
  - 与 Omarchy 状态栏弹窗管理机制（`bar.requestPopout`）深度集成，互斥协调

## 架构与数据源

- **单一事实源 (SSOT)**：
  - 模式列表 100% 来源于 `omni-profile list --json`
  - 窗口策略来源于 `state.json` tmpfs 广播，支持 CLI 与轻量 IPC 同步
  - 模式外观（`display.icon`, `display.brief`, `display.color`）由 Profile 声明定义
- **IPC 调用接口 (`omni.mode-indicator`)**：
  ```bash
  omarchy-shell omni.mode-indicator cycle                  # 正向轮转
  omarchy-shell omni.mode-indicator cycleReverse           # 反向轮转
  omarchy-shell omni.mode-indicator togglePanel            # 呼出/收起右键面板
  omarchy-shell omni.mode-indicator openPanel              # 打开右键面板
  omarchy-shell omni.mode-indicator closePanel             # 关闭右键面板
  omarchy-shell omni.mode-indicator getMode                # 获取当前模式标识
  omarchy-shell omni.mode-indicator switchMode mac         # 切换至指定模式
  omarchy-shell omni.mode-indicator getWindowPolicy        # 获取当前窗口策略 (tiled / floating / follow-profile)
  omarchy-shell omni.mode-indicator getEffectiveWindowMode # 获取实际生效窗口模式
  omarchy-shell omni.mode-indicator setWindowPolicy floating # 切换窗口策略
  ```

## 铁律遵守 (Hard Stops)

- 严守 H-1：不写入 `~/.config/hypr/`，所有操作经由 `omni-profile` CLI 或内存 IPC
- 严守 H-2：零像素截屏，纯几何与矢状绘制
- 严守 SSOT：不维护第二份模式或键位数据
