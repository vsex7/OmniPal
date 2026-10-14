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

## 出问题了怎么办？
请到 GitHub 提 issue，附上 Omarchy 版本和你切换的模式。
