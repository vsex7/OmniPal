# OmniPal 完整用户与参考文档

**项目名称**：OmniPal  
**文档版本**：v1.2.0  
**最后更新**：2026-09-15  
**对应开发文档**：OmniPal 完整开发文档

本文档合并了功能介绍、用户指南、安装说明、快捷键说明、项目对比与架构概览，方便用户与开发者一次性查阅。

---

## 1. 功能介绍

### OmniPal 是什么？

OmniPal 是专为从 Windows 或 macOS 迁移到 Omarchy 的用户设计的肌肉记忆迁移工具。

它让你在 Linux 桌面上继续使用熟悉的快捷键和操作习惯，同时提供完整的图形界面支持，包括状态栏指示器、快捷键提示、设置面板等。

### 核心特点

- **极速切换**：模式切换在 5 毫秒内完成，几乎无感知，不会出现屏幕闪烁。
- **零污染**：默认不修改任何系统或用户配置文件，用完可完全恢复。
- **完整界面**：保留状态栏模式指示、快捷键 HUD、设置面板等实用界面。
- **安全可靠**：退出或崩溃时自动恢复原始快捷键，支持一键干净卸载。
- **自定义与丰富布局**：支持自定义 Profile 目录与多样化窗口吸附布局。

### 支持的模式

- **Windows 模式**：还原 Windows 11 常用快捷键（Alt+F4 关闭、Super+方向键吸附、Super+E 文件管理器等）
- **macOS 模式**：还原 macOS 常用操作习惯（Super+Q 关闭、Super+空格启动器等）
- **Omarchy 原生模式**：完全使用系统默认快捷键，方便对比和学习
- **用户自定义模式**：在 `~/.config/omnipal/profiles/` 中自由扩展专属模式

---

## 2. 用户使用指南

### 2.1 基本使用

1. **查看当前模式**
   - 查看状态栏的模式指示器
   - 或运行命令：
     ```bash
     omni-profile status
     omni-profile list
     ```

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
   - 使用快捷键或入口唤出 HUD（Cheat Sheet）
   - 在设置面板中预览当前绑定

4. **恢复原始状态**
   ```bash
   omni-profile restore
   ```

5. **完全卸载**
   ```bash
   omni-profile restore
   omni-profile uninstall
   # 或运行
   ./scripts/uninstall.sh
   ```

### 2.2 常见问题

**Q：切换后快捷键没有反应？**  
A：先运行 `omni-profile status` 确认 Engine 是否在运行，然后执行 `restore` 后再重新切换。

**Q：会修改我的配置文件吗？**  
A：默认不会。OmniPal 只在内存中覆盖快捷键，退出或执行 restore 后即恢复原状。

**Q：与其他快捷键工具冲突怎么办？**  
A：建议先执行 `restore`，再决定是否继续使用 OmniPal。冲突时优先保留你的原有设置。

**Q：状态栏没有显示指示器？**  
A：确认插件已启用，并且 Engine 正在运行。若 Engine 未启动，指示器会显示禁用状态。

---

## 3. 安装与卸载

### 3.1 安装

```bash
git clone https://github.com/vsex7/OmniPal.git
cd OmniPal
./scripts/install.sh
```

安装内容包括：
- Engine 与 CLI 工具（`~/.local/bin/omni-profile`）
- 可选的 systemd 用户服务（实现开机自启）
- 核心插件同步到 Omarchy 插件目录

安装后建议执行：
```bash
omni-profile status
```
确认服务正常。

### 3.2 卸载

```bash
omni-profile restore          # 先恢复原始绑定
omni-profile uninstall        # 清理自身文件与服务
# 或直接运行
./scripts/uninstall.sh
```

卸载承诺：
- 恢复所有被覆盖的快捷键
- 删除 OmniPal 相关二进制、状态文件与插件
- 不残留对用户 Hyprland 配置的修改
- `hyprctl configerrors` 应为空

---

## 4. 快捷键说明（示例）

> 实际快捷键以中央 Profile 为准，以下为常见示例，便于快速了解。

### 4.1 Windows 模式（部分）

| 快捷键 | 功能 |
|--------|------|
| Alt + F4 | 关闭当前窗口 |
| Super + ← | 窗口靠左半屏 |
| Super + → | 窗口靠右半屏 |
| Super + ↑ | 最大化窗口 |
| Super + ↓ | 还原窗口 |
| Super + E | 打开文件管理器 |
| Super + L | 锁定屏幕 |
| Super + Tab | 任务视图 |
| Super + V | 剪贴板历史 |
| Super + Shift + S | 区域截图 |
| Super + Period | Emoji 选择器 |

### 4.2 macOS 模式（部分）

| 快捷键 | 功能 |
|--------|------|
| Super + Q | 关闭当前窗口 |
| Super + Space | 启动器 / 菜单 |
| Super + Ctrl + Q | 锁定屏幕 |
| Super + Ctrl + F | 全屏 |
| Super + Ctrl + ← / → | 切换工作区 |
| Super + Shift + 3 | 全屏截图 |
| Super + Shift + 4 | 区域截图 |
| Super + Up | 任务视图 / Mission Control |

### 4.3 Omarchy 原生模式

使用系统默认快捷键，不进行任何覆盖，方便用户对比和学习原生操作。

---

## 5. 与同类项目对比

| 对比项 | OmniPal | Omapala | AetherShift |
|--------|---------|---------|-------------|
| 切换方式 | 纯内存热切换 | 写配置 + 事务应用 | 纯内存热切换 |
| 切换速度 | < 5ms | 较慢，可能闪烁 | < 3–5ms |
| 配置污染 | 默认零污染 | 有文件写入 | 零污染 |
| 界面完整度 | 高（指示器 + HUD + 设置 + 后期 Dock 等） | 高 | 较低（偏 CLI） |
| 架构复杂度 | 低 | 高 | 低 |
| 主要定位 | 完整界面 + 干净热切换 | 完整 Omarchy 插件生态 | 极致性能热切换 |
| 适合人群 | 想要界面完整又干净的用户 | 深度 Omarchy 用户 | 追求极简与速度的用户 |

**OmniPal 的差异化定位**：  
在保留完整界面体验的同时，采用更干净的运行时架构，避免 Omapala 的过重与混乱问题，同时比 AetherShift 提供更完整的图形界面。

---

## 6. 架构概览（简要）

```
用户操作（点击 / 快捷键 / CLI）
        ↓
┌─────────────────────────────────────────┐
│           Quickshell 插件层              │
│  mode-indicator │ cheat-sheet │ settings │
│  （后期）snap-feedback │ dock │ overview  │
└──────────────────┬──────────────────────┘
                   │ 轻量 IPC / 命令
┌──────────────────▼──────────────────────┐
│          极简 Engine                     │
│  • Profile 内存管理                      │
│  • 热注入 / 撤销绑定                     │
│  • 当前状态广播                          │
│  • 退出自动 Restore                      │
└──────────────────┬──────────────────────┘
                   │ Hyprland Socket
┌──────────────────▼──────────────────────┐
│                 Hyprland                 │
└─────────────────────────────────────────┘
```

**核心设计要点**：
- 绑定修改只发生在内存中，默认不写配置文件
- Engine 职责极简，只负责切换、状态与恢复
- 插件只负责展示与触发，不直接修改绑定
- 所有键位数据来自中央 Profile（单一事实源）

---

## 7. 功能阶段一览

**Phase 0（核心必须）**
- 三模式热切换
- 自动恢复
- 基础 CLI
- 干净卸载

**Phase 1（核心界面）**
- 模式指示器
- 快捷键 HUD
- 简单设置面板
- 优雅降级

**Phase 2（体验增强 · 已交付）**
- 基础窗口吸附 + 视觉反馈 (omni.snap-feedback)
- mac-dock (omni.mac-dock)
- 任务视图 (omni.overview)
- 多显示器支持

**v1.1（功能扩展 · 已交付）**
- 自定义 Profile 目录支持 (~/.config/omnipal/profiles/)
- 丰富窗口吸附布局 (居中浮动、1/3 与 2/3 分屏)
- omni-profile list 编目查询

详细功能列表请参阅 [features.md](features.md)。

---

## 8. 安全与边界说明

- 默认不修改 `/usr/share/omarchy/` 和用户 Hyprland 主配置
- 只做窗口管理器（Compositor）级别的快捷键覆盖
- 不拦截应用内部快捷键（如复制粘贴）
- 不引入全局输入重映射工具作为默认依赖
- 支持一键完全恢复与卸载

---

## 9. 获取帮助

- 查看当前状态：`omni-profile status`
- 查看模式列表：`omni-profile list`
- 恢复原始绑定：`omni-profile restore`
- 项目问题反馈：请到代码仓库提交 Issue
- 开发相关文档：请参阅 `docs/` 目录下的其他文件

