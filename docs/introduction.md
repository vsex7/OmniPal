**OmniPal 扩展文档集**

以下文档基于当前架构修正版（v0.4）编写，可直接放入项目 `docs/` 目录使用。

---

### 1. 功能介绍（面向用户）

**OmniPal 是什么？**

OmniPal 是一个专为从 Windows 或 macOS 迁移到 Omarchy 的用户设计的肌肉记忆迁移工具。

它让你在 Linux 桌面上继续使用熟悉的快捷键和操作习惯，同时提供完整的图形界面支持，包括状态栏指示器、快捷键提示、设置面板等。

**核心特点**：
- **极速切换**：模式切换在 5 毫秒内完成，几乎无感知，不会出现屏幕闪烁。
- **零污染**：默认不修改任何系统或用户配置文件，用完可完全恢复。
- **完整界面**：保留状态栏模式指示、快捷键 HUD、设置面板等实用界面。
- **安全可靠**：退出或崩溃时自动恢复原始快捷键，支持一键干净卸载。

**支持的模式**：
- **Windows 模式**：还原 Windows 11 常用快捷键（Alt+F4 关闭、Super+方向键吸附、Super+E 文件管理器等）
- **macOS 模式**：还原 macOS 常用操作习惯（Super+Q 关闭、Super+空格启动器等）
- **Omarchy 原生模式**：完全使用系统默认快捷键，方便对比和学习

---

### 2. 功能清单

#### 2.1 核心功能（Phase 0–1 必须交付）

| 功能 | 说明 | 状态目标 |
|------|------|----------|
| 模式热切换 | Windows / macOS / Omarchy 三模式瞬间切换 | 必须 |
| 自动恢复 | 退出、崩溃、手动 restore 时恢复原始绑定 | 必须 |
| 状态栏指示器 | 显示当前模式，左键切换，右键打开设置 | 必须 |
| 快捷键 HUD | 弹出当前模式的完整快捷键列表 | 必须 |
| 简单设置面板 | 可视化切换模式、预览绑定 | 必须 |
| 命令行工具 | switch / cycle / restore / status | 必须 |

#### 2.2 增强功能（Phase 2）

| 功能 | 说明 |
|------|------|
| 基础窗口吸附 | 支持左右半屏、最大化等常用布局 |
| 吸附视觉反馈 | 吸附时显示半透明几何预览 |
| mac-dock | 屏幕底部应用 Dock |
| 任务视图 | 类似 Windows 任务视图 / macOS Mission Control |

#### 2.3 后续可选功能

- 自定义 Profile 导入
- 可选配置持久化（默认关闭）
- 更丰富的吸附布局
- 本地使用习惯统计（完全隐私）

---

### 3. 用户使用指南（简版）

#### 安装后基本使用

1. **查看当前模式**
   - 看状态栏的模式指示器
   - 或运行：`omni-profile status`

2. **切换模式**
   - 点击状态栏指示器（左键循环切换）
   - 或使用命令：
     ```bash
     omni-profile switch windows
     omni-profile switch mac
     omni-profile switch omarchy
     omni-profile cycle
     ```

3. **查看快捷键**
   - 使用快捷键唤出 HUD，或点击相关入口
   - 命令：`omni-profile cheatsheet`（如实现）

4. **恢复原始状态**
   ```bash
   omni-profile restore
   ```

5. **完全卸载**
   ```bash
   omni-profile uninstall
   # 或运行项目提供的 uninstall.sh
   ```

#### 常见问题

**Q：切换后快捷键没反应？**  
A：先运行 `omni-profile status` 确认 Engine 是否在运行，再尝试 `restore` 后重新切换。

**Q：会不会改我的配置文件？**  
A：默认不会。OmniPal 只在内存中覆盖快捷键，退出即恢复。

**Q：和其他快捷键工具冲突怎么办？**  
A：建议先 `restore`，再决定是否使用 OmniPal。冲突时优先保留你的原有设置。

---

### 4. 与同类项目对比

| 对比项 | OmniPal | Omapala | AetherShift |
|--------|---------|---------|-------------|
| 切换方式 | 纯内存热切换 | 写配置 + 事务应用 | 纯内存热切换 |
| 切换速度 | < 5ms | 较慢，可能闪烁 | < 3–5ms |
| 配置污染 | 默认零污染 | 有文件写入 | 零污染 |
| 界面完整度 | 高（指示器+HUD+设置+后期Dock等） | 高 | 较低（偏 CLI） |
| 架构复杂度 | 低 | 高 | 低 |
| 主要定位 | 完整界面 + 干净热切换 | 完整 Omarchy 插件生态 | 极致性能热切换 |
| 适合人群 | 想要界面完整又干净的用户 | 深度 Omarchy 用户 | 追求极简与速度的用户 |

**OmniPal 的差异化**：  
在保留完整界面体验的同时，采用更干净的运行时架构，避免 Omapala 的过重与混乱问题。

---

### 5. 安装与卸载说明

#### 安装

```bash
git clone https://github.com/vsex7/OmniPal.git
cd OmniPal
./scripts/install.sh
```

安装程序会自动执行：
- 校验 JSON Schema、按键定义与所有 Quickshell 插件完整性
- 创建 CLI 软链接至 `~/.local/bin/omni-profile`
- 挂载全套 6 个 Quickshell 插件至 `~/.config/omarchy/plugins/`
- 配置可选的 systemd 用户常驻单元 `omnipal.service`

#### 卸载

```bash
omni-profile restore          # 先恢复绑定
omni-profile uninstall        # 清理自身文件
# 或直接运行
./scripts/uninstall.sh
```

卸载后系统 100% 回到初始基线状态，无残留绑定和文件。

---

### 6. 快捷键示例（Windows 模式部分）

| 快捷键 | 功能 |
|--------|------|
| Alt + F4 | 关闭当前窗口 |
| Super + ← / → | 窗口左右半屏吸附 |
| Super + ↑ | 最大化 |
| Super + ↓ | 还原 / 最小化相关操作 |
| Super + E | 打开文件管理器 |
| Super + L | 锁定屏幕 |
| Super + Tab | 任务视图 |
| Super + V | 剪贴板历史 |
| Super + Shift + S | 区域截图 |

（完整列表以实际 Profile 为准，由单一事实源 `schema/actions.json` 自动生成）

---

### 7. 开发者快速参考

**最重要的三条原则**：
1. 绑定修改只允许通过 Engine 进行，插件禁止直接操作。
2. 所有键位数据必须来自中央 Profile，禁止硬编码。
3. 默认路径下不得写入用户 Hyprland 配置文件。

**开发阶段与架构分工**：
1. 纯内存热切换 + 自动恢复（Phase 0）
2. 状态栏指示器、快捷键 HUD、设置面板（Phase 1）
3. 窗口吸附视觉反馈、Overview 任务视图、Mac-Dock（Phase 2）
4. 用户自定义 Profile 与更丰富吸附布局（v1.1）

---

### 8. 项目文档索引

```
docs/
├── introduction.md          # 项目整体功能介绍与设计规范（本文档）
├── features.md              # 完整功能清单与交付阶段标记
├── allm.md                  # 用户使用指南与综合参考手册
├── BENCHMARK.md             # 微秒级热切换性能基准实测报告
├── KNOWN_ISSUES.md          # 运行环境、依赖边界与已知限制说明
├── ACCEPTANCE_REPORT.md     # 真机全项验收报告与清单
└── ROADMAP_TO_V1.md         # 交付准出规范与路线图
```
