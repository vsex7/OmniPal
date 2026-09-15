# omni.cheat-sheet — OmniPal 快捷键速查 HUD

按下热键呼出的内存化覆盖层：按 `category` 分组列出**当前生效模式**的快捷键，
键位数据全部来自 Engine，插件本体不含任何键位副本。头部胶囊可无缝预览各 Profile，
分类胶囊 + 搜索双维过滤，物理质感键帽按模式渲染原生字符（⌘ / ⊞ Win / Super），
按住修饰键即可实时高亮所有使用该键的条目（键盘肌肉记忆训练器）。

对应 `docs/features.md` 的 HUD 功能项，遵守 `AGENTS.md` 铁律 1/2/3/5 与 H-1/H-6/H-7。

## 边界

- 只读：不调用 `hyprctl keyword`，不注入/解绑任何绑定，不写 `~/.config/hypr/`、
  `/usr/share/omarchy/`、`~/.config/omarchy/shell.json`。
- 无常驻逻辑：只在打开时跑一次数据助手，不轮询、不监听文件。
- 拿不到数据时只显示提示文案，不抛异常。

## 数据流

```
CheatSheet.qml ──Process──▶ fetch.sh ──▶ omni-profile status    --json
   (一次 bash 启动)              └────▶ omni-profile cheatsheet [mode] --json
                                        ▲
                                        └─ Engine 联合 active_overlay.json × schema/actions.json
```

`fetch.sh` 输出三段，以标记分隔（CLI 缺失时只输出 `NO_CLI` 并以 0 退出）：

```
<<<OMNI_STATUS>>>{status JSON}
<<<OMNI_SHEET>>>{cheatsheet JSON 数组}
<<<OMNI_RC>>>{cheatsheet 退出码}
```

插件不重复 Engine 的 `format_combo` 与 overlay×schema 关联逻辑，也不读
`state.json` / `active_overlay.json`，避免第二事实源。

## 文件

| 文件 | 职责 |
|---|---|
| `manifest.json` | 插件清单，`kinds: ["overlay"]`、`keepLoaded: true` |
| `CheatSheet.qml` | 展示层：PanelWindow + 遮罩 + Profile 预览胶囊 + 分类过滤条 + 键帽行列表 + 实时修饰键高亮 + 降级状态 |
| `CheatSheetData.js` | 纯函数：分类标题映射、分组、组合键拆分、高度计算、`formatKeyCap` 键帽转译、`extractCategories` 分类计数、`filterRows` 查询×分类过滤、`isModifierActive` 按下修饰键匹配 |
| `fetch.sh` | 只读数据助手（唯一的外部命令入口） |

## 宿主契约

Omarchy shell 注入 `omarchyPath` / `shell` / `manifest`，并调用：

| 方法 | 行为 |
|---|---|
| `open(payloadJson)` | 显示并刷新。payload 支持 `{"mode":"windows"}` 预览其它 Profile |
| `close()` | 隐藏 |
| `dismiss()` | 隐藏并通知宿主 `shell.hide(id)` |
| `toggle()` | 无 payload 的开合 |
| 属性 `opened` | 宿主据此维护打开状态集合 |

`preview` 的 mode 只接受 `^[a-z0-9][a-z0-9_-]*$`，非法值退回当前模式；mode 作为
argv 传递，绝不拼进命令行字符串。

## 界面

居中卡片（毛玻璃：半透明表面 + 合成器 blur，无额外 shader pass）：

- 头部：🪟 Windows 11 / 🍎 macOS / ⊡ Omarchy 原生**预览胶囊组**（点击即切换查看对应
  Profile；Engine 当前生效模式带绿点标记，预览≠生效一目了然）· 「快捷键速查」·
  `Engine 运行中 · 覆盖生效 | 原生模式 | 未运行 | 状态未知` · 条目数 · 搜索框
- 分类筛选胶囊条：`extractCategories` 按当前搜索词实时计数
  （如「全部 19」「窗口吸附 6」），点击即过滤，`Tab` / `Shift+Tab` 键盘循环；
  分类少于两项时自动收起不占高度
- 主体：按 profile 中的 category 出现顺序分组；每组 = 分类标题 + 行
  （组合键键帽 / 动作名 / 描述），超出高度可滚动
- 键帽行：真实立体按键质感（纵向渐变 + 顶部高光 + 底部阴影凹槽），
  `formatKeyCap(part, mode)` 按模式渲染物理键帽字符——mac：`⌘ ⌥ ⌃ ⇧ ↵ ⎋ ⌫ ⇥ ␣ ←↓↑→`；
  windows：`⊞ Win / Alt / Ctrl / Shift / ↵ Enter / ⇥ Tab`；omarchy/通用：`Super / Alt / Ctrl / Shift`。
  未知按键原样回退，绝不丢条目
- 实时按键高亮反馈（Live Modifier Highlight）：在 HUD 中按住 Super / Alt / Ctrl / Shift，
  所有包含该修饰键的行泛起主题色底、对应键帽边框呼吸闪烁（`isModifierActive`），
  松手即复原——把速查表变成肌肉记忆训练器
- 底部：操作提示

配色与尺寸全部取 `qs.Commons` 的 `[menu]` 主题令牌（`Color.menu.*`、
`Style.space/font/cornerRadius/hoverFill`、`Border.surfaceSpec`），跟随 Omarchy
主题，不自定义色值（键帽高光/阴影的中性白黑除外）。

键盘：`Esc` / 点击遮罩关闭 · `/` 聚焦搜索 · `Tab` / `Shift+Tab` 切换分类胶囊 ·
`R` 重新读取 · `↑↓ PgUp PgDn Home End` 滚动 · 按住修饰键触发高亮反馈。
卡片内 `keyCatcher`（`Keys.priority: Keys.BeforeItem`）与 `WlrKeyboardFocus.Exclusive`
的写法和 `omarchy.emojis` / `omarchy.clipboard` / `omarchy.reminders` 一致。

## 启用

```bash
# 1) 安装 Engine 与 CLI（若未安装）
./scripts/install.sh

# 2) 放置插件
mkdir -p ~/.config/omarchy/plugins
ln -sfn "$PWD/plugins/omni.cheat-sheet" ~/.config/omarchy/plugins/omni.cheat-sheet

# 3) 用户自行在 ~/.config/omarchy/shell.json 增加（插件不会代改）
#    "plugins": [ { "id": "omni.cheat-sheet" } ]

omarchy-shell reload   # 或注销重登
```

绑定到按键（示例，交给 Hyprland / Engine，不由本插件写入）：

```bash
omarchy-shell shell toggle omni.cheat-sheet '{}'
omarchy-shell shell summon omni.cheat-sheet '{"mode":"mac"}'
omarchy-shell shell hide   omni.cheat-sheet
```

## 降级矩阵

| 情况 | 表现 |
|---|---|
| 未安装 / 找不到 `omni-profile` | 「未找到 OmniPal 命令行工具」+ 安装提示，提示命令 `omni-profile status` |
| CLI 非零退出 | 「读取快捷键失败（退出码 N）」+ `omni-profile cheatsheet …` |
| 输出不是 JSON 数组 | 「解析 Engine 输出失败」+ 版本一致性提示 |
| 预览的 Profile 不存在（退出码 2） | 「没有这个模式」+ 该模式的读取命令 |
| 原生模式（0 条覆盖） | 「当前没有生效的快捷键覆盖」+ `omni-profile switch windows` |
| 搜索词 × 分类过滤后无结果 | 「没有匹配的条目」+ 换词 / 点「全部」重试提示（原始列表仍在，清空即恢复） |
| `status` 不可读但 cheatsheet 可读 | 列表照常显示，头部标注「Engine 状态未知」 |

未知 `category` 会以 schema 原始 id 显示（`CheatSheetData.js` 的 `CATEGORY_LABELS`
只是展示用中文名，不含键位），因此新增分类无需改插件。

## 开发

`OMNIPAL_PROFILE_CLI=/path/to/bin/omni-profile` 可覆盖 CLI 解析（默认按
`command -v omni-profile` → `~/.local/bin` → `/usr/local/bin` → `/usr/bin`）。
