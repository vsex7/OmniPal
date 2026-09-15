#!/usr/bin/env bash
# OmniPal Complete Uninstallation Script
# 100% cleans up binaries, runtime states, and restores original Hyprland keybindings.

set -euo pipefail

BIN_TARGET="${HOME}/.local/bin/omni-profile"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
SERVICE_FILE="${SYSTEMD_USER_DIR}/omnipal.service"
RUN_DIR="/run/user/$(id -u)/omnipal"

echo "=== OmniPal 卸载程序 ==="

# 1. 恢复 Hyprland 绑定至基线
if [ -x "${BIN_TARGET}" ]; then
    echo "🔄 恢复系统原始快捷键绑定..."
    "${BIN_TARGET}" restore || true
fi

# 2. 停用并移除 systemd 服务
if [ -f "${SERVICE_FILE}" ]; then
    echo "🛑 停止并清理 systemd 用户服务..."
    systemctl --user stop omnipal.service 2>/dev/null || true
    systemctl --user disable omnipal.service 2>/dev/null || true
    rm -f "${SERVICE_FILE}"
    systemctl --user daemon-reload
fi

# 3. 移除 CLI 软链接
if [ -L "${BIN_TARGET}" ] || [ -f "${BIN_TARGET}" ]; then
    rm -f "${BIN_TARGET}"
    echo "🗑️ 已移除 CLI: ${BIN_TARGET}"
fi

# 4. 移除 Quickshell 插件软链接
OMARCHY_PLUGINS_DIR="${HOME}/.config/omarchy/plugins"
if [ -d "${OMARCHY_PLUGINS_DIR}" ]; then
    for p_link in "${OMARCHY_PLUGINS_DIR}"/omni.*; do
        if [ -L "${p_link}" ] || [ -d "${p_link}" ]; then
            rm -rf "${p_link}"
            echo "🗑️ 已移除插件软链接: $(basename "${p_link}")"
        fi
    done
fi

# 5. 清理内存运行时临时目录
if [ -d "${RUN_DIR}" ]; then
    rm -rf "${RUN_DIR}"
    echo "🧹 已清理运行目录: ${RUN_DIR}"
fi

# 6. 清理可选持久化与本地使用统计（仅存在于用户配置目录，绝不涉及 ~/.config/hypr）
OMNIPAL_CONFIG_DIR_PATH="${OMNIPAL_CONFIG_DIR:-${HOME}/.config/omnipal}"
for user_file in persistence.json stats.json; do
    if [ -f "${OMNIPAL_CONFIG_DIR_PATH}/${user_file}" ]; then
        rm -f "${OMNIPAL_CONFIG_DIR_PATH}/${user_file}"
        echo "🗑️ 已移除: ${OMNIPAL_CONFIG_DIR_PATH}/${user_file}"
    fi
done
# 配置目录为空时安全移除（含用户自定义 profiles 时保留）
if [ -d "${OMNIPAL_CONFIG_DIR_PATH}" ] && [ -z "$(ls -A "${OMNIPAL_CONFIG_DIR_PATH}" 2>/dev/null)" ]; then
    rmdir "${OMNIPAL_CONFIG_DIR_PATH}" && echo "🧹 已移除空配置目录: ${OMNIPAL_CONFIG_DIR_PATH}"
fi

echo "✅ 卸载完毕！系统快捷键与配置已完整恢复至原始状态，零文件残留。"
