"""Profile/action catalog loading, key-forward specs, window classifiers."""

import atexit
import datetime
import json
import contextlib
import fcntl
import io
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from engine.omnipal.paths import (app_rules_file_path)
from engine.omnipal.util import (_debug, lua_str)

FORWARD_ACTION = "forward_shortcut"
TERMINAL_CLASSES = (
    "alacritty", "kitty", "foot", "footclient", "ghostty", "com.mitchellh.ghostty",
    "org.wezfurlong.wezterm", "wezterm", "xterm", "konsole", "org.kde.konsole",
    "gnome-terminal", "org.gnome.terminal", "org.gnome.ptyxis", "tilix", "terminator",
)
_FORWARD_MOD_RE = re.compile(r"^[A-Za-z]+$")
_FORWARD_KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,24}$")


def parse_forward(spec: str):
    """'CTRL SHIFT T' -> (['CTRL','SHIFT'], 'T'). Raises ValueError on bad input."""
    parts = str(spec or "").replace("+", " ").split()
    if not parts:
        raise ValueError("empty forward shortcut")
    *mods, key = parts
    mods = [m.upper() for m in mods]
    for m in mods:
        if not _FORWARD_MOD_RE.match(m):
            raise ValueError(f"bad modifier: {m!r}")
    if not _FORWARD_KEY_RE.match(key):
        raise ValueError(f"bad key: {key!r}")
    return mods, (key.upper() if len(key) == 1 else key)


def load_terminal_patterns() -> List[str]:
    """Built-in terminals plus ~/.config/omnipal/terminals.json (a JSON list of window
    classes; a trailing '*' means prefix match). Lower-cased, deduped."""
    pats = list(TERMINAL_CLASSES)
    try:
        path = app_rules_file_path().parent / "terminals.json"
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for x in raw if isinstance(raw, list) else []:
                if isinstance(x, str) and x.strip():
                    pats.append(x.strip().lower())
    except (OSError, ValueError) as e:
        print(f"Warning: Failed to read terminals.json: {e}", file=sys.stderr)
    return list(dict.fromkeys(pats))


def is_terminal_class(window_class: str, patterns: Optional[List[str]] = None) -> bool:
    wc = (window_class or "").strip().lower()
    if not wc:
        return False
    for p in (patterns if patterns is not None else load_terminal_patterns()):
        if (p.endswith("*") and wc.startswith(p[:-1])) or wc == p:
            return True
    return False


def forward_lua(mods: List[str], key: str, patterns: List[str]) -> str:
    """Pure-Lua forward: checks Omarchy terminal tags and window classes, adds SHIFT
    for terminals, and dispatches using down/up pulse (send_key_state + 50ms timer)
    to prevent modifier sticking on Hyprland, with send_shortcut fallback."""
    exact = ", ".join(f"[{lua_str(p)}] = true" for p in patterns if not p.endswith("*"))
    prefix = ", ".join(lua_str(p[:-1]) for p in patterns if p.endswith("*"))
    term_mods = mods + ["SHIFT"] if "CTRL" in mods and "SHIFT" not in mods else mods
    return ("function() local w = hl.get_active_window(); "
            "local t = false; "
            "if w and w.tags then for _, tag in ipairs(w.tags) do "
            "if string.gsub(tag, '%*$', '') == 'terminal' then t = true break end end end; "
            "if not t then "
            "local c = string.lower((w and w.class) or ''); "
            f"t = ({{ {exact} }})[c] or false; "
            f"if not t then for _, p in ipairs({{ {prefix} }}) do if c:sub(1, #p) == p then t = true break end end end "
            "end; "
            f"local m = t and {lua_str(' '.join(term_mods))} or {lua_str(' '.join(mods))}; "
            f"local k = {lua_str(key)}; "
            "if hl.dsp and hl.dsp.send_key_state and hl.timer then "
            "hl.dispatch(hl.dsp.send_key_state({ mods = m, key = k, state = 'down' })); "
            "hl.timer(function() hl.dispatch(hl.dsp.send_key_state({ mods = m, key = k, state = 'up' })) end, { timeout = 50, type = 'oneshot' }) "
            "else "
            "hl.dispatch(hl.dsp.send_shortcut({ mods = m, key = k })) "
            "end end")


def forward_for_class(spec: str, window_class: str, tags: Optional[List[str]] = None):
    """Terminals keep Ctrl+W / Ctrl+C for the shell, so they get Ctrl+Shift instead."""
    mods, key = parse_forward(spec)
    is_term = False
    if tags:
        is_term = any(str(t).rstrip("*") == "terminal" for t in tags)
    if not is_term and is_terminal_class(window_class):
        is_term = True
    if is_term and "CTRL" in mods and "SHIFT" not in mods:
        mods = mods + ["SHIFT"]
    return mods, key


RETIRED_MODES = ("kde",)  # removed built-in modes; saved references migrate to MIGRATION_FALLBACK_MODE
MIGRATION_FALLBACK_MODE = "windows"

VALID_WINDOW_POLICIES = {"tiled", "floating", "follow-profile"}
WINDOW_POLICY_ALIASES = {
    "tile": "tiled",
    "tiled": "tiled",
    "float": "floating",
    "floating": "floating",
    "follow": "follow-profile",
    "follow-profile": "follow-profile",
    "follow_profile": "follow-profile",
}

def normalize_window_policy(policy: Optional[str]) -> Optional[str]:
    if not policy:
        return None
    return WINDOW_POLICY_ALIASES.get(str(policy).lower().strip())

# Apps that choose their own window size / aspect ratio: never resized by the floating policy.
OWN_SIZE_CLASSES = ("scrcpy", "mpv", "imv", "vlc", "org.gnome.loupe", "feh")

DIALOG_KEYWORDS = (
    "polkit",
    "pinentry",
    "portal",
    "calc",
    "about",
    "dialog",
    "prompt",
    "steam_app_",
    "wlogout",
    "rofi",
)

def is_pip_window(cls_name: str = "", title: str = "") -> bool:
    """Checks if a window is Picture-in-Picture based on class or title."""
    c = str(cls_name or "").lower()
    t = str(title or "").lower()
    if any(p in t for p in ("picture-in-picture", "picture in picture")):
        return True
    if any(p in c for p in ("picture-in-picture", "picture in picture")):
        return True
    parts = re.split(r"[-_.\s]+", c)
    if "pip" in parts or c == "pip":
        return True
    return False

def is_scratchpad_workspace(ws_name: str = "", ws_id: Optional[Union[int, str]] = None) -> bool:
    """Checks if workspace is a scratchpad / special workspace (starts with 'special:' or id < 0)."""
    name = str(ws_name or "").strip()
    if name.startswith("special"):
        return True
    if ws_id is not None:
        try:
            if int(ws_id) < 0:
                return True
        except (ValueError, TypeError):
            pass
    if name.startswith("-"):
        try:
            if int(name) < 0:
                return True
        except (ValueError, TypeError):
            pass
    return False

def is_dialog_window(cls_name: str = "", title: str = "") -> bool:
    """Checks if a window is a dialog, prompt, or popup based on class or title.

    Short keywords (<=4 chars) match whole tokens only: "calc" matches class/title
    token "calc" but not the substring inside "chatgpt"."""
    c = str(cls_name or "").lower()
    t = str(title or "").lower()
    parts_c = re.split(r"[-_.\s]+", c)
    parts_t = re.split(r"[-_.\s]+", t)
    for k in DIALOG_KEYWORDS:
        if k == "calc":
            # calculator apps: token "calc", or "calculator"/"galculator" substring
            if "calc" in parts_c or "calc" in parts_t:
                return True
            if "calculator" in c or "calculator" in t or "galculator" in c or "galculator" in t:
                return True
            continue
        if len(k) <= 4:
            if k in parts_c or k in parts_t:
                return True
        elif k in c or k in t:
            return True
    return False

def is_micro_window(size: Optional[Union[List[int], Tuple[int, ...]]]) -> bool:
    """Checks if window size is unusually small (micro-window / tooltip / transient element)."""
    if not size or len(size) < 2:
        return False
    try:
        w, h = int(size[0]), int(size[1])
        return (0 < w < 300 or 0 < h < 200)
    except (ValueError, TypeError):
        return False

def is_special_window(
    cls_name: str = "",
    title: str = "",
    ws_name: str = "",
    ws_id: Optional[Union[int, str]] = None,
    size: Optional[Union[List[int], Tuple[int, ...]]] = None
) -> Tuple[bool, bool]:
    """
    Classifies whether a window is special or a dialog.
    Returns (skip_cascade, is_dialog):
    - skip_cascade is True if PiP, scratchpad, or micro-window (completely skip resizing and cascading).
    - is_dialog is True if dialog/prompt/popup (center window without resizing).
    """
    if is_pip_window(cls_name, title):
        return True, False
    if is_scratchpad_workspace(ws_name, ws_id):
        return True, False
    if is_micro_window(size):
        return True, False
    if is_dialog_window(cls_name, title):
        return False, True
    return False, False

def load_fixed_bindings(root_dir: Path) -> List[Dict[str, Any]]:
    """Mode-independent OmniPal entry points (schema/fixed_bindings.json), injected in every mode."""
    try:
        data = json.loads((Path(root_dir) / "schema" / "fixed_bindings.json").read_text(encoding="utf-8"))
        return [b for b in data.get("bindings", []) if b.get("action") and b.get("key")]
    except (OSError, ValueError) as e:
        # Corrupt fixed_bindings.json must not kill startup; fixed entry
        # points simply stay uninjected until the file is repaired.
        _debug(f"Failed to load fixed_bindings.json: {e}")
        return []


# ---------- protected system keybindings (schema/protected_bindings.json) ----------
# Single home for the protected-combos rules: shared by the consistency checker
# (scripts/check_consistency.py), `omni-profile import`, engine.doctor() and the
# switch-time filter in engine.switch_mode(), so all four agree on what counts
# as a protected combination.

def combo_key(mod: str, key: str) -> str:
    """Normalized combo key: modifiers upper-cased and sorted, joined with the key.

    'SUPER ALT'+'space', 'ALT SUPER'+'SPACE' and 'alt+super + space' all map to
    the same string, so every caller detects the same violations."""
    mods = [m.upper() for m in str(mod or "").replace("+", " ").split()]
    return "+".join(sorted(mods) + [str(key or "").upper()])


def load_protected_combos(root_dir) -> dict:
    """combo_key -> reason, from schema/protected_bindings.json.

    Raises FileNotFoundError when the schema file is missing and ValueError on
    a malformed entry; callers that treat this as non-fatal must catch it."""
    protected_file = Path(root_dir) / "schema" / "protected_bindings.json"
    protected = json.loads(protected_file.read_text(encoding="utf-8")).get("bindings", [])
    combos = {}
    for b in protected:
        if not isinstance(b.get("mod"), str) or not isinstance(b.get("key"), str):
            raise ValueError(f"protected_bindings.json entry has non-str mod/key: {b!r}")
        combos[combo_key(b["mod"], b["key"])] = b.get("reason", "")
    return combos


def find_protected_violations(root_dir, profiles: dict) -> list:
    """Scan loaded profiles ({profile_id: profile_dict}) for bindings on protected
    system combos. Returns [(profile_id, mod, key, reason), ...].

    A missing or unreadable protected_bindings.json yields no violations
    (callers that must hard-fail on that use validate_protected_bindings)."""
    try:
        combos = load_protected_combos(root_dir)
    except Exception:
        return []
    out = []
    for p_id, p_data in (profiles or {}).items():
        for b in (p_data or {}).get("bindings", []):
            if not isinstance(b, dict):
                continue
            ck = combo_key(b.get("mod", ""), b.get("key", ""))
            if ck in combos:
                out.append((p_id, b.get("mod", ""), b.get("key", ""), combos[ck]))
    return out


def validate_protected_bindings(root_dir, profile_files) -> bool:
    """System-critical combos (e.g. the Omarchy menu key) that no profile
    may override. A violation is a hard error, not a warning: overriding
    one of these silently breaks the user's way back into the menu/settings."""
    try:
        combos = load_protected_combos(root_dir)
    except FileNotFoundError:
        print("❌ Missing schema/protected_bindings.json (system-critical combos)", file=sys.stderr)
        return False
    except Exception as e:
        print(f"❌ Invalid protected_bindings.json: {e}", file=sys.stderr)
        return False
    profiles = {}
    for p_file in profile_files:
        try:
            profiles[Path(p_file).name] = json.loads(Path(p_file).read_text(encoding="utf-8"))
        except Exception:
            continue
    ok = True
    for p_name, mod, key, reason in find_protected_violations(root_dir, profiles):
        print(f"❌ [{p_name}] {mod} {key} is a protected system "
              f"entry ({reason}); profiles must not override it", file=sys.stderr)
        ok = False
    if ok:
        print(f"✅ Protected system entries ({len(combos)}) not overridden by any profile")
    return ok
