#!/usr/bin/env bash
# Lint OmniPal plugin QML against the real Omarchy Shell Commons/Ui modules.
#   OMARCHY_SHELL  path to omarchy's shell/ dir (default: /workspace/ref/omarchy/shell,
#                  then /usr/share/omarchy/shell, then $OMARCHY_PATH/shell)
#   QMLLINT        qmllint binary (default /usr/lib/qt6/bin/qmllint)
# qs.* resolves through a generated import farm: <tmp>/qs/{Commons,Ui} -> $OMARCHY_SHELL/*.
# Quickshell itself is not installed on CI boxes, so tools/qmlstubs carries hand-written
# qmltypes stubs for the Quickshell types we (and Omarchy's Ui) use.
# Exit 1 on any finding in a "hard" category (see HARD below); other warnings are printed
# with --verbose only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QMLLINT="${QMLLINT:-/usr/lib/qt6/bin/qmllint}"
VERBOSE=0; [[ "${1:-}" == "--verbose" ]] && { VERBOSE=1; shift; }
if [[ -z "${OMARCHY_SHELL:-}" ]]; then
  for c in /workspace/ref/omarchy/shell /usr/share/omarchy/shell "${OMARCHY_PATH:-/nonexistent}/shell"; do
    [[ -f "$c/Commons/qmldir" ]] && { OMARCHY_SHELL="$c"; break; }
  done
fi
[[ -n "${OMARCHY_SHELL:-}" && -f "$OMARCHY_SHELL/Commons/qmldir" ]] || { echo "omarchy shell source not found (set OMARCHY_SHELL)" >&2; exit 2; }
[[ -x "$QMLLINT" ]] || { echo "qmllint not found at $QMLLINT" >&2; exit 2; }
FARM="$(mktemp -d)"; trap 'rm -rf "$FARM"' EXIT
mkdir -p "$FARM/qs"; ln -s "$OMARCHY_SHELL/Commons" "$FARM/qs/Commons"; ln -s "$OMARCHY_SHELL/Ui" "$FARM/qs/Ui"
# Hard failures: duplicate bindings, syntax, unknown ids/properties on our own or Omarchy types.
HARD='already been assigned|Duplicate|syntax|\[unqualified\]|\[unresolved-type\]|\[import\]|\[missing-property\]|\[required\]|\[signal-handler-parameters\]|\[unused-imports\]'
# Known false positives: Style.font/spacing are untyped QtObject groups in Commons/Style.qml,
# so member access on them can't be checked statically.
IGNORE='Member "[A-Za-z]+" not found on type "QObject"'
files=("$@"); [[ ${#files[@]} -eq 0 ]] && mapfile -t files < <(find "$ROOT/plugins" -path '*/omni.*/*.qml' | sort)
fail=0
for f in "${files[@]}"; do
  out="$("$QMLLINT" -I "$FARM" -I "$ROOT/tools/qmlstubs" -I "$(dirname "$f")" "$f" 2>&1 || true)"
  hard="$(grep -E '^(Warning|Error)' <<<"$out" | grep -E "$HARD" | grep -Ev "$IGNORE" || true)"
  if [[ -n "$hard" ]]; then echo "$hard"; fail=1; fi
  [[ $VERBOSE -eq 1 ]] && grep -E '^(Warning|Error)' <<<"$out" | grep -Ev "$HARD" || true
done
[[ $fail -eq 0 ]] && echo "qmllint: ${#files[@]} files clean (omarchy shell: $OMARCHY_SHELL)"
exit $fail
