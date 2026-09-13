**OmniPal：从当前状态到最终成品的开发文档**

**文档性质**：开发用（非用户手册）  
**基准**：仓库当前状态（v0.4，Phase 0–2 已提交）  
**目标**：可发布、可维护、真机可验收的最终成品（v1.0）

---

### 1. 当前状态评估

根据 https://github.com/vsex7/OmniPal 公开内容：

| 已具备 | 状态 |
|--------|------|
| Phase 0 引擎 / schema / profiles / CLI / 基础测试 | 已提交 |
| Phase 1 插件（indicator / cheat-sheet / settings） | 已提交 |
| Phase 2 插件（snap-feedback / overview / mac-dock） | 已提交 |
| install / uninstall / AGENTS / README | 已提交 |
| 提交历史 | 仅 3 次，同日完成 |
| Release / 外部验证 | 无 |
| Stars / 真实用户反馈 | 无 |

**判断**：功能骨架与文档方向已齐，距离「最终成品」差的是**验证、打磨、发布与长期可维护性**，而不是再堆大功能。

---

### 2. 最终成品定义（v1.0 Definition of Done）

同时满足以下全部条件，才算最终成品：

1. **功能闭环**  
   - 三模式切换可用、可 cycle、可 restore  
   - 6 个插件可独立启用，无 Engine 时优雅降级  
   - 安装后开箱可用，卸载后系统干净  

2. **质量门槛**  
   - 切换延迟有可复现基准（目标 < 5ms，记录实测）  
   - `restore` / `uninstall` 后无残留 bind、无服务残留  
   - 一致性检查 100% 通过（schema ↔ profiles ↔ 插件数据）  
   - 核心路径有自动化测试 + 真机验收清单通过  

3. **发布门槛**  
   - 有正式 tag（如 `v1.0.0`）  
   - README / 安装 / 卸载 / 故障排除与真实行为一致  
   - 在干净 Omarchy 环境从零安装可完成主流程  

4. **边界不回退**  
   - 仍遵守：默认零写 `~/.config/hypr/`、插件不改绑定、不引入 Omapala 式重型配置系统  

---

### 3. 缺口清单（从当前 → 成品必须补的）

#### A. 验证类（最高优先）

| 编号 | 工作项 | 产出 |
|------|--------|------|
| V-1 | 真机切换延迟基准 | `docs/BENCHMARK.md` 或测试输出，含测量方法 |
| V-2 | Restore / 崩溃 / SIGTERM 恢复验收 | 检查清单 + 通过记录 |
| V-3 | 干净环境冷安装验收 | 新用户路径逐步记录 |
| V-4 | 卸载残留检查 | 文件、服务、bind、插件链接清单 |
| V-5 | 无 Engine 插件降级验收 | 6 插件均不崩、有提示 |
| V-6 | 多显示器 / 缩放（若宣称支持） | Snap、overview、dock 行为确认 |

#### B. 稳定性与工程类

| 编号 | 工作项 | 说明 |
|------|--------|------|
| S-1 | Engine 常驻方式固定 | systemd user 服务行为、崩溃拉起、日志位置 |
| S-2 | hyprctl/eval 失败回滚 | 半切换状态禁止长期存在 |
| S-3 | 状态文件/广播可靠性 | 断连重连、启动竞态 |
| S-4 | 测试补强 | 幂等 apply/restore、一致性、关键回归 |
| S-5 | 去掉绝对路径 / 本机假设 | README 中 `/home/abyss/...` 等改为通用说明 |

#### C. 产品与发布类

| 编号 | 工作项 | 说明 |
|------|--------|------|
| R-1 | 版本与 CHANGELOG | v1.0.0 与变更说明 |
| R-2 | 发布检查脚本 | 一键跑校验 + 测试 + 基础静态检查 |
| R-3 | 文档与代码对齐 | 快捷键表、命令、插件 IPC 与实现一致 |
| R-4 | 已知问题列表 | README 或 ISSUES 中写清限制 |
| R-5 | （可选）最小截图/录屏 | 切换、HUD、设置各一张说明 |

#### D. 明确不做（防止再次膨胀）

- 重做 Omapala 式配置事务编译器  
- 默认持久化写 bindings  
- 应用内键重映射、keyd 默认依赖  
- 大范围新功能（自定义 Profile 编辑器等可进 v1.1 backlog）  

---

### 4. 到 v1.0 的开发阶段

#### Phase P（Polish，当前 → 可验收）

**目标**：现有功能在真机上可靠，而不是加功能。

- 完成 V-1～V-6 验收项  
- 完成 S-1～S-5 稳定性项  
- 修安装脚本、路径、错误提示  
- 统一日志与 `status` 输出  

**准出**：主路径真机清单全部勾选通过。

#### Phase Q（Quality / 发布准备）

**目标**：可打 tag 对外用。

- R-1～R-4  
- `scripts/release-check.sh`（或等价）一键门禁  
- README 安装路径通用化  
- 确认 uninstall 与 Hard Stop 仍成立  

**准出**：干净机器按 README 安装 → 使用 → 卸载，全程无手工补救。

#### Phase v1.0（冻结）

- 打 `v1.0.0`  
- 冻结大功能，只收 blocker 级 bug  
- Backlog 挪到 v1.1（自定义 Profile、可选持久化等）  

---

### 5. 真机验收清单（开发必用）

复制到 Issue / 表格中逐项打勾：

**引擎**
- [ ] `switch windows/mac/omarchy` 均立即生效  
- [ ] `cycle` 顺序正确  
- [ ] `restore` 后绑定与安装前一致  
- [ ] kill Engine / SIGTERM 后自动恢复  
- [ ] 重复 switch/restore 10 次无异常  
- [ ] `status` 信息与真实模式一致  

**插件**
- [ ] indicator 显示正确，点击可切换  
- [ ] cheat-sheet 内容与当前 Profile 一致  
- [ ] settings 可切换并预览  
- [ ] snap-feedback 在吸附时可见  
- [ ] overview / mac-dock 可打开关闭，无 QML 崩  
- [ ] 停掉 Engine 后插件降级，不拖垮 shell  

**安装卸载**
- [ ] 新 clone + `install.sh` 成功  
- [ ] 服务/CLI/插件就位  
- [ ] `uninstall.sh` 后无 CLI、无插件链接、无覆盖绑定、无残留状态目录  

**边界**
- [ ] 运行期未写入 `~/.config/hypr/`（除你明确允许的可选功能外）  
- [ ] 未改 `/usr/share/omarchy/`、`shell.json`  

---

### 6. 建议的开发任务拆解（可直接当 Issue）

1. **基准测试**：为 `switch`/`restore` 写可重复测量脚本并记录结果  
2. **恢复路径审计**：所有退出路径必须调用同一 Restore  
3. **安装脚本去本机化**：去掉硬编码 home 路径  
4. **release-check**：schema 校验 + 单元测试 + 插件 manifest validate  
5. **文档对齐**：KEYBINDINGS / README 命令与代码一致  
6. **已知问题页**：写明当前限制（环境、Hyprland 版本等）  
7. **v1.0.0 tag + CHANGELOG**  

---

### 7. 成功标准（开发视角）

| 维度 | 标准 |
|------|------|
| 功能 | 文档宣称的核心能力均有真机证据 |
| 质量 | 主路径无已知 blocker；卸载干净 |
| 架构 | 未重新引入重型配置写盘主路径 |
| 发布 | 有 tag、有 CHANGELOG、有一键检查 |
| 维护 | AGENTS.md 仍约束后续改动不膨胀 |

---

### 8. v1.1 Backlog（成品之后，不阻塞 v1.0）

- 自定义 Profile  
- 可选持久化（默认关）  
- 更丰富 Snap 布局  
- 更细的冲突提示  
- 性能与日志可观测性增强  

---

### 9. 一句话路线

> **当前不是缺大功能，而是缺：可复现验证、失败回滚、通用安装、发布门禁与文档对齐。**  
> 把上述 P → Q → v1.0 做完，即为最终成品；期间禁止把项目重新做成 Omapala 式重型配置系统。

---

如需下一步，我可以直接输出：
1. `docs/ROADMAP_TO_V1.md` 可粘贴全文，或  
2. 按上面编号拆成的 GitHub Issue 标题列表。
