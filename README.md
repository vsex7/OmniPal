<p align="center"><img src="docs/assets/banner.png" alt="OmniPal" width="100%"></p>

# OmniPal

在 Omarchy（Hyprland）上一条命令切换 Windows、macOS 或 KDE Plasma 的快捷键习惯。只在内存里生效，不改你现有的配置文件，随时切回原生键位。

<p align="center"><img src="docs/assets/demo.gif" alt="演示：切换模式与窗口吸附（示意动画）" width="80%"></p>

## 安装

```bash
git clone https://github.com/vsex7/OmniPal.git
cd OmniPal && bash scripts/install.sh
```

要求 **Omarchy 4.0.4 或更新版本**（每个插件的 `manifest.json` 里以 `minOmarchy` 声明）。安装脚本会通过 `pacman -Q omarchy`（或 `$OMARCHY_PATH/version`）检测版本：版本过旧会拒绝安装；无法检测时只给出警告并继续安装，装好后请运行 `omni-profile doctor`，其中「Omarchy 版本」一项会显示 正常 / 过旧 / 未知。

装好后不要移动这个目录。卸载请运行 `bash scripts/uninstall.sh`，会删掉安装时加上的所有文件。

## 用法

```bash
omni-profile switch windows   # Windows 11 习惯
omni-profile switch mac       # macOS 习惯
omni-profile switch kde       # KDE Plasma 习惯
omni-profile restore          # 回到 Omarchy 原生键位
omni-profile cheatsheet       # 当前模式的快捷键
omni-profile doctor           # 出问题时先跑这个
```

## 包含什么

- **三套习惯模式**：Windows（Alt+F4、Win+方向键吸附、Win+E）、macOS（Super+Q、Super+Space、Super+Shift+3/4）、KDE Plasma（Meta+方向键贴边、Alt+Space 搜索、Meta+W 概览）。
- **窗口吸附**：半屏、三分之一、三分之二、居中，`Win+Z` 呼出布局选择器。
- **Quickshell 插件**：顶栏模式指示器、快捷键速查表、设置中心、吸附反馈、任务视图、Dock。
- **自定义模式**：在 `~/.config/omnipal/profiles/` 放 JSON，或用 `omni-profile import` 导入别人分享的。

## 更多

- [按应用自动切换模式](docs/APP_RULES.md)
- [自定义 profile 编写指南](docs/PROFILE_GUIDE.md)
- [完整功能与命令参考](docs/REFERENCE.md)
- [常见问题](docs/FAQ.md)
- [更新日志](CHANGELOG.md)

需要 Omarchy 或 Hyprland。遇到问题请[提 issue](https://github.com/vsex7/OmniPal/issues)，附上 `OMNIPAL_DEBUG=1 omni-profile doctor` 的输出。
