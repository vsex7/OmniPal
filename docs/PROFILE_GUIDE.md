# 编写和分享自定义 profile

profile 是一个 JSON 文件，描述一套快捷键习惯。内置的 `windows`、`mac`、`omarchy` 在仓库的 `profiles/` 里，自己写的放在 `~/.config/omnipal/profiles/`（可用 `OMNIPAL_USER_PROFILES_DIR` 改位置）。和内置模式同 id 的自定义 profile 会覆盖内置的。

## 最快的起步：从内置模式改

```bash
omni-profile export mac -o my-mac.json   # 导出一份作为模板
# 编辑 my-mac.json
omni-profile import my-mac.json --id my-mac
```

## 文件结构

```json
{
  "id": "my-mac",
  "name": "我的 Mac 习惯",
  "description": "在 mac 模式基础上把截图改到 Super+Shift+S",
  "version": "1.0.0",
  "display": { "icon": "◆", "brief": "MY", "color": "#d8dee9" },
  "bindings": [
    { "action": "close_window",      "mod": "SUPER",       "key": "Q" },
    { "action": "screenshot_region", "mod": "SUPER SHIFT", "key": "S" },
    { "action": "app_launcher",      "mod": "SUPER",       "key": "space", "arg": "walker" }
  ]
}
```

- `id`：小写字母、数字、`-` 和 `_`，第一个字符必须是字母或数字，最长 32 位，不能和已有模式重名（除非导入时加 `--force`）。
- `display.brief`：模式指示器上显示的短名。
- `bindings`：每条把一个动作绑到一个组合键上。
  - `mod`：修饰键，空格分隔，如 `SUPER`、`SUPER SHIFT`、`SUPER CTRL`、`SUPER ALT`。
  - `key`：Hyprland 的按键名，如 `Q`、`space`、`Left`、`comma`、`slash`。
  - `arg`：可选。对执行命令类的动作（如 `app_launcher`、`file_manager`），用它替换默认命令。

同一个组合键不能绑两次，导入时会被拒绝。

## 可用的动作

窗口：`close_window` `maximize_window` `restore_window` `toggle_floating`

吸附：`snap_left` `snap_right` `snap_top` `snap_bottom` `snap_center` `snap_third_left` `snap_third_right` `snap_third_center` `snap_two_thirds_left` `snap_two_thirds_right` `snap_top_left` `snap_top_right` `snap_bottom_left` `snap_bottom_right` `snap_layouts`

应用和系统：`app_launcher` `file_manager` `lock_screen` `screenshot_region` `screenshot_fullscreen` `clipboard_history` `emoji_picker`

工作区：`task_view` `workspace_next` `workspace_prev`

OmniPal：`cheat_sheet` `toggle_dock` `omni_settings`

完整说明见 `schema/actions.json`。

## 分享给别人

1. `omni-profile export my-mac -o my-mac.json`，导出时会自动去掉内部字段。
2. 把文件发到 GitHub Gist 或仓库的 Discussions，附一句这套键位适合谁。
3. 对方运行 `omni-profile import my-mac.json`。

## 导入别人的 profile 前

带 `arg` 的绑定按下时会执行一条命令。导入时会把这些命令全部列出来让你确认，请逐条看清楚，看到 `curl ... | sh` 这类下载并执行的命令就不要导入。脚本里批量导入必须显式加 `--yes`。
