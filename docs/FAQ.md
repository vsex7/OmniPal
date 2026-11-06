# FAQ

## OmniPal 会改我的配置文件吗？
不会改你现有的配置。切换模式只在 Hyprland 内存里生效，不碰 hyprland.conf 和 shell.json。
安装时会在 ~/.config/omarchy/plugins/ 建插件软链接，在 ~/.local/bin/ 放 omni-profile，并装一个 systemd 用户服务。

## 怎么回到 Omarchy 原生键位？
切回 omarchy 模式即可。

## 怎么卸载？
运行 scripts/uninstall.sh，安装时加的文件都会被删除。

## 和 Toshy、keyd 有什么区别？
Toshy 和 keyd 在键盘层做重映射，覆盖面广，但需要额外的依赖或手写配置。
OmniPal 只面向 Omarchy，直接用 Hyprland 自己的绑定，没有第三方依赖，另外带窗口吸附和快捷键速查表。

## 自定义 profile 的命令里能用引号吗？
可以，v1.7.1 起命令会被正确转义。

## 怎么跑测试？
在仓库根目录运行 `python3 -m unittest discover -s tests`，不需要 pytest，也不需要 Hyprland（没有 `hyprctl` 时会自动用测试替身）。

## 窗口标题栏开关状态如何记忆？
在 v1.9.0 中，无论通过设置中心还是命令行 `omni-profile titlebars on|off|toggle` 切换标题栏，状态都会自动原子化持久写入 `~/.config/omnipal/persistence.json`，在系统冷启动、守护进程重连或执行 `hyprctl reload` 时全自动精准恢复。

## 为什么 Windows 模式下的 Super+I 不再打开控制中心？
Omarchy 4.5 将 `Super+I` 用作核心的系统输入法（中/英等）循环切换。为了保证打字切换的流畅性，OmniPal 控制中心统一使用全局固定入口 `Super+Alt+I`，并将 `Super+I` 纳入系统受保护键位表（`schema/protected_bindings.json`），禁止任何模式覆盖冲突。

## 怎么查看 Omarchy 4.5 原生核心特性与智能体快捷键？
- 在快捷键速查表（`Super+Ctrl+/`）中，原生模式下直接展示全部核心能力。
- 在其他模式下，可在终端运行 `omni-profile cheatsheet [mode] --with-omarchy`，即可同时并排查看该模式快捷键与 Omarchy 原生特性（如 Quake 智能体终端 `Super+~`、Superwhisper 语音输入 `Alt+Space` 等）。

## OmniPal 如何推荐适合我电脑的模式？
运行 `omni-profile doctor` 即可查看。OmniPal 引擎通过探测系统 DMI 厂商信息及 Asahi Linux Apple Silicon 设备树，自动识别是否为 Apple 硬件（推荐 `mac` 模式）或通用 PC 架构（推荐 `windows` 模式）。

## 出问题了怎么办？
请到 GitHub 提 issue，附上 `omni-profile doctor` 的输出。
