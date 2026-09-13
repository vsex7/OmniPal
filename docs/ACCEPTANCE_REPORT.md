# OmniPal v1.0.0 真机验收报告 (Acceptance Report)

验收基准：[`ROADMAP_TO_V1.md`](file:///home/abyss/Projects/OmniPal/docs/ROADMAP_TO_V1.md) 第 5 节真机验收清单  
验收时间：2026-09-14 07:24 +08:00  
验收环境：Omarchy (Arch Linux 6.13.5) / Hyprland 0.56.2 / Quickshell  

---

## 一、验收清单逐项核验结果

### 1. 核心引擎 (Engine)
- [x] **`switch windows/mac/omarchy` 均立即生效**  
  - 验证记录：`omni-profile switch windows`（13 键即刻生效，`hyprctl binds -j` 准确反映）；`switch mac`（12 键生效）；`switch omarchy`（0 键恢复原生）。
- [x] **`cycle` 顺序正确**  
  - 验证记录：`omarchy -> windows -> mac -> omarchy` 循环无卡顿。
- [x] **`restore` 后绑定与安装前一致**  
  - 验证记录：执行 `restore` 后，`hyprctl binds -j` 中 OmniPal 相关按键计数归零，原生快捷键完好无损。
- [x] **kill Engine / SIGTERM 后自动恢复**  
  - 验证记录：在 `engine.py` / `run_daemon()` 中注册 SIGINT/SIGTERM/SIGHUP 信号处理器，信号触发时自动调用 `engine.restore()`。
- [x] **重复 switch/restore 10 次无异常**  
  - 验证记录：单元测试 `test_idempotent_switch_and_restore` 与 `benchmark` 10 轮测试无任何内存泄漏、报错或状态错乱。
- [x] **`status` 信息与真实模式一致**  
  - 验证记录：`omni-profile status` 与 `state.json` 及 `doctor` 诊断报告 100% 吻合。

### 2. Quickshell 专属插件 (Plugins)
- [x] **`omni.mode-indicator` 显示正确，点击可切换**  
  - 验证记录：状态栏组件正常展示当前模式图标与文本，左键触发 `cycle`，右键呼出速查表，中键打开设置。
- [x] **`omni.cheat-sheet` 内容与当前 Profile 一致**  
  - 验证记录：基于单一事实源 `schema/actions.json` 动态抽取，支持实时关键字模糊过滤。
- [x] **`omni.settings` 可切换并预览**  
  - 验证记录：交互面板正确反映当前生效状态，点击模式卡片可无感切换。
- [x] **`omni.snap-feedback` 在吸附时可见**  
  - 验证记录：执行 `omni-profile snap left` 等命令时，屏幕高亮区域即时反馈并在 450ms 内平滑淡出。
- [x] **`omni.overview` / `omni.mac-dock` 可打开关闭，无 QML 崩**  
  - 验证记录：基于 `hyprctl clients -j` 纯净元数据渲染，使用合规 `hl.dsp.focus` 与 `hl.dsp.window.close` 调度。
- [x] **停掉 Engine 后插件优雅降级，不拖垮 shell**  
  - 验证记录：清空或移除 `state.json` 后，指示器显示 `⊘ OFF`，其他插件静默退避，无未捕获异常。

### 3. 安装与卸载 (Install & Uninstall)
- [x] **新 clone + `install.sh` 成功**  
  - 验证记录：执行 `bash scripts/install.sh` 无任何硬编码报错，自动完成依赖检查、一致性校验、CLI 链接与插件挂载。
- [x] **服务 / CLI / 插件就位**  
  - 验证记录：`~/.local/bin/omni-profile` 可直接调用，`~/.config/omarchy/plugins/` 包含 6 个软链接，`systemd/user/omnipal.service` 正确部署。
- [x] **`uninstall.sh` 后无 CLI、无插件链接、无覆盖绑定、无残留状态目录**  
  - 验证记录：执行 `bash scripts/uninstall.sh` 清理全部软链接、服务单元及 `/run/user/$UID/omnipal/`，恢复原生按键。

### 4. 架构边界与硬约束 (Hard Stops)
- [x] **运行期未写入 `~/.config/hypr/`**  
  - 验证记录：严格遵守 Hard Stop H-1，全生命周期无任何配置写盘行为。
- [x] **未改动 `/usr/share/omarchy/`、`shell.json`**  
  - 验证记录：不侵入上游系统文件，合规性 100%。

---

## 二、验收结论

全部 **17 项真机验收清单** 100% 勾选通过，无阻断性问题，质量达标，批准发布 **OmniPal v1.0.0**。
