#!/usr/bin/env bash
# OmniPal cheat-sheet 插件的只读数据助手。
#
# 插件不重复 Engine 的绑定格式化 / overlay×schema 关联逻辑（单一事实源），
# 所以这里一次 bash 启动里跑两条 CLI，输出带标记的 JSON 块：
#
#   <<<OMNI_STATUS>>>{status JSON}
#   <<<OMNI_SHEET>>>{cheatsheet JSON 数组}
#   <<<OMNI_RC>>>{cheatsheet 退出码}
#
# CLI 缺失时只输出 "NO_CLI" 并以 0 退出，好让 UI 区分“没装 OmniPal”和
# “Engine 出错”。CLI 自身的 stderr 会原样透传，便于排查。
set -u

CLI="${OMNIPAL_PROFILE_CLI:-}"
if [ -n "$CLI" ] && [ ! -x "$CLI" ]; then
  # 覆盖值也可能是 PATH 上的命令名，两种写法都接受。
  CLI="$(command -v "$CLI" 2>/dev/null)" || CLI=""
fi
if [ -z "$CLI" ]; then
  for c in omni-profile "$HOME/.local/bin/omni-profile" /usr/local/bin/omni-profile /usr/bin/omni-profile; do
    if [ "$c" = "omni-profile" ]; then
      c="$(command -v omni-profile 2>/dev/null)" || continue
    fi
    if [ -n "$c" ] && [ -x "$c" ]; then CLI="$c"; break; fi
  done
fi
if [ -z "$CLI" ]; then
  echo NO_CLI
  exit 0
fi

MODE="${1:-}"
echo '<<<OMNI_STATUS>>>'
"$CLI" status --json
echo '<<<OMNI_SHEET>>>'
if [ -n "$MODE" ]; then
  "$CLI" cheatsheet "$MODE" --json
  rc=$?
else
  "$CLI" cheatsheet --json
  rc=$?
fi
echo "<<<OMNI_RC>>>${rc}"
