#!/usr/bin/env bash
# OmniPal Installation Script
# Adheres strictly to AGENTS.md: zero config pollution, non-root, user-scoped.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BIN_TARGET="${HOME}/.local/bin/omni-profile"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
SERVICE_FILE="${SYSTEMD_USER_DIR}/omnipal.service"

echo "=== OmniPal 安装程序 ==="
echo "项目路径: ${PROJECT_ROOT}"

# 1. 依赖检查
command -v python3 >/dev/null 2>&1 || { echo "❌ 缺少依赖: python3"; exit 1; }
command -v hyprctl >/dev/null 2>&1 || { echo "❌ 缺少依赖: hyprctl (Hyprland)"; exit 1; }

# 2. 预先校验一致性
echo "🔍 运行 Profile 与 Schema 一致性校验..."
python3 "${PROJECT_ROOT}/scripts/check-consistency.py"

# 3. 创建 CLI 符号链接
mkdir -p "${HOME}/.local/bin"
ln -sf "${PROJECT_ROOT}/bin/omni-profile" "${BIN_TARGET}"
chmod +x "${PROJECT_ROOT}/bin/omni-profile"
echo "✅ CLI 链接已创建: ${BIN_TARGET}"

# 4. 创建可选的 systemd 用户守护进程（用于在会话退出时自动触发 restore）
mkdir -p "${SYSTEMD_USER_DIR}"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=OmniPal Runtime Hot-Switching Daemon
Documentation=https://github.com/abyss/OmniPal
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=${PROJECT_ROOT}/bin/omni-profile daemon
ExecStop=${PROJECT_ROOT}/bin/omni-profile restore
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF

systemctl --user daemon-reload
echo "✅ 用户守护服务已生成: ${SERVICE_FILE}"

echo ""
echo "🎉 OmniPal 安装完成！"
echo "使用说明:"
echo "  omni-profile status               # 查看当前快捷键模式"
echo "  omni-profile switch windows       # 切换至 Windows 11 习惯模式"
echo "  omni-profile switch mac           # 切换至 macOS 习惯模式"
echo "  omni-profile cycle                # 轮转切换模式"
echo "  omni-profile cheatsheet           # 查看当前模式快捷键速查表"
echo "  omni-profile restore              # 恢复系统原始快捷键"
