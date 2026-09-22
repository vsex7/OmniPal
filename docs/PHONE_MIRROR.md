# OmniPal 手机同屏协同

手机同屏是 OmniPal 的可选功能，通过 `scrcpy` 和 Android Debug Bridge 管理一台或多台手机。它不参与 Hyprland 绑定逻辑，核心快捷键模式在未安装 `scrcpy`/`adb` 时仍可正常使用。

## 依赖与配置

Arch Linux 可安装：

```bash
sudo pacman -S scrcpy android-tools
```

配置文件位于 `~/.config/omnipal/devices.json`。读取 `status`、`list`、`doctor` 或 `config` 不会自动创建该文件；需要投屏时再显式创建。示例：

```json
{
  "auto_wifi": true,
  "default_bitrate": "4M",
  "stay_awake": true,
  "notify": true,
  "devices": [
    {
      "id": "my-phone",
      "name": "My Phone",
      "serial": "USB_SERIAL",
      "ip": "192.0.2.10",
      "geometry": { "x": 1200, "y": 160, "width": 405, "height": 900 }
    }
  ]
}
```

`geometry` 完全可选。USB 已连接时优先使用序列号；仅当 `auto_wifi` 未关闭且配置的 Wi-Fi 端口可达时才回退到无线 ADB。

## 命令

```bash
omni-profile phone doctor
omni-profile phone list
omni-profile phone status
omni-profile phone start [device-id]
omni-profile phone stop [device-id]
omni-profile phone toggle [device-id]
omni-profile phone config
```

省略 `device-id` 时，`start`、`stop` 和 `toggle` 作用于全部配置设备。所有 JSON 输出命令均支持 `--json`（`toggle` 为状态变更命令，不提供 JSON 输出）。

## 安全与卸载

- PID 记录只接受命令行为 `scrcpy` 且窗口标题匹配 OmniPal 管理标题的进程。
- 停止操作只终止经过校验的 PID，不使用按标题匹配的宽泛 `pkill`。
- `devices.json` 以 `0600` 权限原子写入，不包含任何内置个人设备信息。
- `scripts/uninstall.sh` 会先执行 `phone stop`，随后删除运行时 PID 文件和 `devices.json`。

## 验收状态

自动化测试覆盖空配置、只读状态、CLI 成功/失败退出码、离线设备、启动重试、损坏配置降级、PID 身份校验以及 scrcpy 窗口保护。2026-09-22 已在 Redmi Note 10 Lite 上完成单设备 USB 启动、状态、Hyprland 窗口和停止闭环。当前另有设备在线；双设备并发、第二台设备、Wi-Fi 投屏、音视频质量与断线恢复仍需确认目标设备后验收。
