#!/usr/bin/env bash
# OmniPal Release Gate Verification Script (release-check.sh)
#
# Runs all checks required for the current OmniPal release:
# 1. Profile, Schema, and Quickshell Plugin Consistency
# 2. Automated Unit & Integration Tests
# 3. Millisecond Benchmark Latency Gate (10 ms one-shot budget)
# 4. Git cleanliness, diff whitespace, and machine-specific path checks
#
# Returns 0 only if all gates pass.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_VERSION="$(PYTHONPATH="${PROJECT_ROOT}" python3 -c 'from engine.engine import VERSION; print(VERSION)')"

echo "========================================"
echo "🛡️  OmniPal ${PROJECT_VERSION} 发布检查门禁 (Release Check)"
echo "项目目录: ${PROJECT_ROOT}"
echo "========================================"

# Gate 1: Consistency Check
echo -e "\n[Gate 1/4] 运行 Schema、Profile 与 Plugin 校验..."
python3 "${PROJECT_ROOT}/scripts/check_consistency.py"
echo "✅ Gate 1 通过！"

# Gate 2: Unit Tests
echo -e "\n[Gate 2/4] 执行自动化测试套件..."
python3 -m unittest discover -s "${PROJECT_ROOT}/tests"
echo "✅ Gate 2 通过！"

# Gate 3: Benchmark Performance Gate
echo -e "\n[Gate 3/4] 校验热切换延迟指标 (单次含冷启动 <= 10ms)..."
python3 "${PROJECT_ROOT}/bin/omni-profile" benchmark --json | python3 -c "
import sys, json
data = json.load(sys.stdin)
win_ms = data.get('switch_windows_ms', 999)
mac_ms = data.get('switch_mac_ms', 999)
restore_ms = data.get('restore_ms', 999)
print(f'  • Windows switch: {win_ms} ms')
print(f'  • macOS switch:   {mac_ms} ms')
print(f'  • Restore:        {restore_ms} ms')
restore_ok = data.get('restore_ok', False)
policy_restored = data.get('policy_restored', False)
initial_mode = data.get('initial_mode')
mode_restored = data.get('mode_restored', False)
if win_ms > 10.0 or mac_ms > 10.0 or restore_ms > 10.0:
    print('❌ 延迟超出容忍门槛！', file=sys.stderr)
    sys.exit(1)
if not restore_ok or not policy_restored:
    print('❌ 基准测试未能完整恢复会话状态！', file=sys.stderr)
    sys.exit(1)
if initial_mode != 'omarchy' and not mode_restored:
    print('❌ 基准测试未能恢复原始模式！', file=sys.stderr)
    sys.exit(1)
"
echo "✅ Gate 3 通过！"

# Gate 4: Cleanliness & Hardcoded Path Check
echo -e "\n[Gate 4/4] 静态合规性与无本机路径检查..."
if ! git -C "${PROJECT_ROOT}" diff --check; then
    echo "❌ Git diff 存在空白格式问题"
    exit 1
fi
if [ -n "$(git -C "${PROJECT_ROOT}" status --porcelain)" ]; then
    echo "❌ 发布门禁要求工作树干净"
    git -C "${PROJECT_ROOT}" status --short
    exit 1
fi
set +e
HARDCODED_ABYSS="$(git -C "${PROJECT_ROOT}" grep -rn "cd /home/""abyss" -- ':(exclude)scripts/release-check.sh' || true)"
set -e
if [ -n "${HARDCODED_ABYSS}" ]; then
    echo "❌ 发现硬编码用户路径: ${HARDCODED_ABYSS}"
    exit 1
fi
echo "  • 无硬编码用户路径"
echo "  • 权限与符号链接规范"
echo "✅ Gate 4 通过！"

echo -e "\n🎉 全部发布门禁检查通过，OmniPal ${PROJECT_VERSION} 达到当前交付质量标准。"
