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
command -v hyprctl >/dev/null 2>&1 || { echo "❌ 缺少依赖: hyprctl。OmniPal 只支持运行在 Hyprland 上的 Omarchy，请在 Omarchy 桌面里安装。"; exit 1; }

# 2. 预先校验一致性
echo "🔍 运行 Profile 与 Schema 一致性校验..."
python3 "${PROJECT_ROOT}/scripts/check_consistency.py"

# 2.5 提醒：服务和软链接都指向当前目录，移动或删除它会让 OmniPal 失效
case "${PROJECT_ROOT}" in
    /tmp/*|"${HOME}/Downloads"/*)
        echo "⚠️  OmniPal 位于临时目录 ${PROJECT_ROOT}，删除后服务会失效。建议先移到 ~/.local/share/omnipal 再安装。" ;;
esac
echo "ℹ️  安装后请不要移动或删除 ${PROJECT_ROOT}；如需移动，请先卸载再重新安装。"

# 3. 创建 CLI 符号链接
# 记录本次安装新建的目录，卸载时只删除这些目录（且仅在为空时）
CREATED_DIRS_FILE="${HOME}/.local/share/omnipal/created-dirs"
record_dir() {
    mkdir -p "$(dirname "${CREATED_DIRS_FILE}")"
    echo "$1" >> "${CREATED_DIRS_FILE}"
}
# 把 mkdir -p 会连带新建的每一级上级目录都记下来（由外到内），卸载时由内到外删除
track_mkdir() {
    local missing=() d="$1"
    while [ ! -d "${d}" ] && [ "${d}" != "${HOME}" ] && [ "${d}" != "/" ]; do
        missing=("${d}" "${missing[@]}")
        d="$(dirname "${d}")"
    done
    [ ${#missing[@]} -eq 0 ] && return 0
    mkdir -p "$1"
    for d in "${missing[@]}"; do record_dir "${d}"; done
}
# 记录文件自身所在的目录也要算作新建
track_mkdir "$(dirname "${CREATED_DIRS_FILE}")"

track_mkdir "${HOME}/.local/bin"
ln -sf "${PROJECT_ROOT}/bin/omni-profile" "${BIN_TARGET}"
chmod +x "${PROJECT_ROOT}/bin/omni-profile"
echo "✅ CLI 链接已创建: ${BIN_TARGET}"

# 4. 安装 Quickshell 插件（符号链接至 ~/.config/omarchy/plugins/）
OMARCHY_PLUGINS_DIR="${HOME}/.config/omarchy/plugins"
track_mkdir "${OMARCHY_PLUGINS_DIR}"
echo "🧩 部署 OmniPal Quickshell 插件..."
for p_path in "${PROJECT_ROOT}/plugins"/omni.*; do
    if [ -d "${p_path}" ]; then
        p_name="$(basename "${p_path}")"
        ln -sfn "${p_path}" "${OMARCHY_PLUGINS_DIR}/${p_name}"
        echo "  ✅ 已挂载插件: ${p_name} -> ${OMARCHY_PLUGINS_DIR}/${p_name}"
    fi
done

# 5. 创建可选的 systemd 用户守护进程（用于在会话退出时自动触发 restore）
track_mkdir "${SYSTEMD_USER_DIR}"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=OmniPal Runtime Hot-Switching Daemon
Documentation=https://github.com/vsex7/OmniPal
PartOf=graphical-session.target
ConditionPathExists=${PROJECT_ROOT}/bin/omni-profile
StartLimitIntervalSec=60
StartLimitBurst=3
After=graphical-session.target

[Service]
Type=simple
ExecStart="${PROJECT_ROOT}/bin/omni-profile" daemon
ExecStop="${PROJECT_ROOT}/bin/omni-profile" restore
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF

systemctl --user daemon-reload 2>/dev/null || echo "⚠️ systemd 用户会话不可用（SSH/无 DBUS）：服务文件已生成，登录图形会话后自动生效"
systemctl --user enable --now omnipal.service 2>/dev/null || true
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
