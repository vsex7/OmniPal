# OmniPal 术语表（UI 文案规范）

适用范围：所有用户可见文案——插件 QML 界面、`omni-profile` 的帮助与输出、profiles/*.json 的 `name` / `description`。
**不适用**：代码标识符、JSON 键、CLI 子命令与参数（如 `profile`、`window-policy`、`follow-profile`、`snap`），它们保持英文以兼容脚本。

| 概念 | UI 用词 | 不要再用 | 说明 |
|---|---|---|---|
| profile / mode | **模式** | Profile、方案、配置模式 | 例：「macOS 习惯模式」「切换模式」。文件本身可称「模式文件（profiles/*.json）」 |
| Omarchy 默认（无覆盖） | **Omarchy 原生模式** | 系统原生还原、恢复原生快捷键 | 「还原」动作即切换到原生模式 |
| Snap / snap layouts | **贴靠**、**贴靠布局（菜单）** | Snap、Snap Layouts、吸附、贴边 | 例：「Super+方向键贴靠」「呼出贴靠布局菜单」 |
| window policy | **窗口策略** | Window Policy、窗口布局策略 | 固定为跟随模式：由各模式自带的 window_mode 决定平铺或浮动，无全局覆盖 |
| tiled / floating | **平铺** / **浮动** | tile、float | 模式文件的 window_mode 取值 |
| follow-profile | **跟随模式** | follow-profile（仅作 CLI 参数出现） | 由当前模式决定平铺或浮动 |
| overview / task view | **概览** | Overview、任务视图 | |
| cheat sheet | **速查表**（快捷键速查表） | Cheat Sheet、速查 | |
| per-app rules | **应用规则** | | 按应用自动切换模式 |

## 按键写法

- 修饰键一律用英文：`Super`、`Ctrl`、`Alt`、`Shift`；**不用** Win、Meta、⌘、Cmd。
- 普通键用英文首字母大写：`Space`、`Tab`、`Enter`、`Esc`、`F4`、`Left`；**不写**「空格」「回车键」。
  （「方向键」作为一组键的统称可保留。）
- 组合键用 `+` 连接，顺序为 `Super+Ctrl+Alt+Shift+键`，两侧不加空格：`Super+Space`、`Ctrl+Alt+L`、`Super+Shift+4`。

## 字号

界面最小字号 12px：使用 `Style.font.body`（随 Omarchy `[font] base-size` 缩放），不要使用 `Style.font.caption` / `Style.font.bodySmall`。
