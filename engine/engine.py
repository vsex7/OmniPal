#!/usr/bin/env python3
"""
OmniPal Core Runtime Engine
Version: 1.8.0 (Obsidian Snap HUD, Window Policy, and Hardening Release)

Strictly adheres to AGENTS.md rules:
1. Pure in-memory overlay via Omarchy Hyprland Lua engine (`hyprctl eval`)
2. Zero file writes to ~/.config/hypr/ or system configs
3. Safe signal handling: automatic restore on SIGTERM/SIGINT/SIGHUP
4. State broadcast via /run/user/$UID/omnipal/state.json (tmpfs)
5. Instant rollback on injection failure
6. User custom profiles support via ~/.config/omnipal/profiles/
7. Opt-in profile persistence ONLY to ~/.config/omnipal/persistence.json (default disabled, zero writes)
8. Fully local usage statistics in ~/.config/omnipal/stats.json (aggregate counters only, no keylogging, no network I/O)
"""

import atexit
import datetime
import json
import contextlib
import fcntl
import io
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

__version__ = "1.8.0"
VERSION = __version__


def compositor_mutation_disabled() -> bool:
    """Returns True when tests or maintenance tools request a non-mutating dry run."""
    return os.environ.get("OMNIPAL_DRY_RUN", "").strip().lower() in ("1", "true", "yes")

def _resolve_run_dir() -> Path:
    custom = os.environ.get("OMNIPAL_RUN_DIR")
    if custom:
        d = Path(custom)
    else:
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg:
            d = Path(xdg) / "omnipal"
        else:
            d = Path(f"/run/user/{os.getuid()}/omnipal")
    global RUN_DIR, STATE_FILE, OVERLAY_FILE, SNAP_FILE, SNAP_LAYOUTS_FILE, PID_FILE, LOCK_FILE, APPLIED_WINDOW_MODE_FILE, BASELINE_FILE, APP_RULE_STATE_FILE
    RUN_DIR = d
    STATE_FILE = d / "state.json"
    OVERLAY_FILE = d / "active_overlay.json"
    SNAP_FILE = d / "snap.json"
    SNAP_LAYOUTS_FILE = d / "snap_layouts.json"
    PID_FILE = d / "daemon.pid"
    LOCK_FILE = d / "engine.lock"
    APPLIED_WINDOW_MODE_FILE = d / "applied_window_mode"
    BASELINE_FILE = d / "baseline_bindings.json"
    APP_RULE_STATE_FILE = d / "app_rule.json"
    return d

RUN_DIR = _resolve_run_dir()
STATE_FILE = RUN_DIR / "state.json"
OVERLAY_FILE = RUN_DIR / "active_overlay.json"
SNAP_FILE = RUN_DIR / "snap.json"
SNAP_LAYOUTS_FILE = RUN_DIR / "snap_layouts.json"
PID_FILE = RUN_DIR / "daemon.pid"
APP_RULE_STATE_FILE = RUN_DIR / "app_rule.json"

def lua_str(value: Any) -> str:
    """Returns a safely quoted Lua string literal (prevents broken batches and Lua injection)."""
    text = "" if value is None else str(value)
    out = []
    for ch in text:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 32 or o == 127:
            out.append("\\%03d" % o)
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'
LOCK_FILE = RUN_DIR / "engine.lock"
APPLIED_WINDOW_MODE_FILE = RUN_DIR / "applied_window_mode"
BASELINE_FILE = RUN_DIR / "baseline_bindings.json"

_lock_local = threading.local()

@contextlib.contextmanager
def engine_lock(timeout: float = 3.0):
    """Acquires a re-entrant inter-process lock on LOCK_FILE using fcntl.flock."""
    depth = getattr(_lock_local, "depth", 0)
    if depth > 0:
        _lock_local.depth = depth + 1
        try:
            yield
        finally:
            _lock_local.depth -= 1
        return

    run_dir = _resolve_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    f = None
    try:
        f = open(LOCK_FILE, "a+")
        start_time = time.time()
        acquired = False
        while time.time() - start_time < timeout:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                time.sleep(0.02)
        if not acquired:
            raise TimeoutError(f"Failed to acquire engine lock on {LOCK_FILE} within {timeout}s")
    except Exception:
        if f:
            try:
                f.close()
            except Exception:
                pass
        raise

    _lock_local.depth = 1
    try:
        yield
    finally:
        _lock_local.depth = 0
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        if f:
            try:
                f.close()
            except Exception:
                pass

def _escape_lua_string(s: str) -> str:
    """Escapes string content safely for embedding in Lua double-quoted literals."""
    return lua_str(s)[1:-1]

LUA_RESTORE_BASELINE = (
    'local mods = {"applications", "clipboard", "media", "tiling", "utilities", "voxtype"}; '
    'for _, m in ipairs(mods) do '
    '  package.loaded["default.hypr.bindings." .. m] = nil; '
    '  pcall(require, "default.hypr.bindings." .. m); '
    'end; '
    'package.loaded["hypr.bindings"] = nil; '
    'pcall(require, "hypr.bindings")'
)


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> bool:
    """Atomically writes JSON to path using a process-unique temporary file."""
    tmp_path = path.parent / f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        tmp_path.replace(path)
        return True
    except Exception as e:
        print(f"Warning: Failed to atomic write {path}: {e}", file=sys.stderr)
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return False


def write_state_json(path: Path, data: Any, indent: int = 2) -> bool:
    """Writes JSON to path in-place preserving inode for inotify / QFileSystemWatcher."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, indent=indent, ensure_ascii=False)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception as e:
        print(f"Warning: Failed to write state {path}: {e}", file=sys.stderr)
        return False


LUA_DISPATCHERS = {
    "close_window": "hl.dsp.window.close()",
    "toggle_floating": "hl.dsp.window.float({ action = 'toggle' })",
    "workspace_next": "hl.dsp.focus({ workspace = 'm+1' })",
    "workspace_prev": "hl.dsp.focus({ workspace = 'm-1' })",
    # Single-expression Lua so they embed directly into o.bind(combo, name, <expr>).
    # Without these, maximize/restore fall through to an empty default_arg and bind a no-op.
    "maximize_window": "hl.dsp.window.fullscreen({ mode = 'maximized' })",
    "restore_window": ("function() local w = hl.get_active_window() "
                      "if w then local is_fs = (w.fullscreen == true or w.fullscreen == 1 or w.fullscreen == 2) "
                      "if is_fs then hl.dispatch(hl.dsp.window.fullscreen({ mode = 'maximized' })) "
                      "elseif w.floating then hl.dispatch(hl.dsp.window.float({ action = 'toggle' })) end end end"),
}

# Actions that forward a shortcut to the focused app (Hyprland `sendshortcut`).
# Their combo usually collides with an Omarchy native bind, so the native bind is
# unbound while the overlay is active and restored via `hyprctl reload`.
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
    except Exception as e:
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
    """Pure-Lua forward: reads the focused window class, adds SHIFT for terminals,
    then dispatches send_shortcut. Every dynamic value goes through lua_str()."""
    exact = ", ".join(f"[{lua_str(p)}] = true" for p in patterns if not p.endswith("*"))
    prefix = ", ".join(lua_str(p[:-1]) for p in patterns if p.endswith("*"))
    term_mods = mods + ["SHIFT"] if "CTRL" in mods and "SHIFT" not in mods else mods
    return ("function() local w = hl.get_active_window(); "
            "local c = string.lower((w and w.class) or ''); "
            f"local t = ({{ {exact} }})[c] or false; "
            f"for _, p in ipairs({{ {prefix} }}) do if c:sub(1, #p) == p then t = true end end; "
            f"hl.dispatch(hl.dsp.send_shortcut({{ mods = t and {lua_str(' '.join(term_mods))} or {lua_str(' '.join(mods))}, "
            f"key = {lua_str(key)} }})) end")


def forward_for_class(spec: str, window_class: str):
    """Terminals keep Ctrl+W / Ctrl+C for the shell, so they get Ctrl+Shift instead."""
    mods, key = parse_forward(spec)
    if is_terminal_class(window_class) and "CTRL" in mods and "SHIFT" not in mods:
        mods = mods + ["SHIFT"]
    return mods, key


def _debug(msg) -> None:
    """Prints swallowed errors to stderr when OMNIPAL_DEBUG=1."""
    if os.environ.get("OMNIPAL_DEBUG") == "1":
        import traceback
        caller = traceback.extract_stack(limit=2)[0]
        print(f"[omnipal debug] {caller.name}:{caller.lineno}: {msg!r}", file=sys.stderr)


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
    """Checks if a window is a dialog, prompt, or popup based on class or title."""
    c = str(cls_name or "").lower()
    t = str(title or "").lower()
    return any(k in c or k in t for k in DIALOG_KEYWORDS)

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

_MODMASK = {"SHIFT": 1, "CAPS": 2, "CTRL": 4, "CONTROL": 4, "ALT": 8, "MOD2": 16,
            "MOD3": 32, "SUPER": 64, "WIN": 64, "MOD4": 64, "LOGO": 64, "MOD5": 128}


def combo_signature(combo: str) -> Tuple[int, str]:
    """(modmask, KEY) for a combo like 'SUPER + SHIFT + TAB', comparable with `hyprctl binds -j`."""
    parts = [p.strip() for p in str(combo or "").split("+") if p.strip()]
    if not parts:
        return (0, "")
    mask = 0
    for m in parts[:-1]:
        mask |= _MODMASK.get(m.upper(), 0)
    return (mask, parts[-1].upper())


def format_combo(mod: str, key: str) -> str:
    parts = []
    if mod:
        for m in mod.replace("+", " ").split():
            parts.append(m.upper())
    norm_key = key
    if len(key) == 1:
        norm_key = key.upper()
    elif key.upper().startswith("F") and key[1:].isdigit():
        norm_key = key.upper()
    elif key.lower() == "space":
        norm_key = "SPACE"
    elif key.lower() in ("tab", "left", "right", "up", "down", "period", "return", "enter", "comma", "slash"):
        norm_key = key.upper()
    parts.append(norm_key)
    return " + ".join(parts)

def resolve_user_profiles_dir() -> Path:
    """Resolves the user custom profiles directory, honoring OMNIPAL_USER_PROFILES_DIR and XDG."""
    env_dir = os.environ.get("OMNIPAL_USER_PROFILES_DIR")
    if env_dir:
        return Path(env_dir)
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "omnipal" / "profiles"
    return Path.home() / ".config" / "omnipal" / "profiles"

def resolve_config_dir() -> Path:
    """Resolves the OmniPal user config directory, honoring OMNIPAL_CONFIG_DIR and XDG."""
    env_dir = os.environ.get("OMNIPAL_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "omnipal"
    return Path.home() / ".config" / "omnipal"

def persistence_file_path() -> Path:
    """The single explicit opt-in persistence file. Never touched unless the user enables it."""
    return resolve_config_dir() / "persistence.json"

def app_rules_file_path() -> Path:
    """Per-app auto-switch rules. Only written when the user adds a rule."""
    return resolve_config_dir() / "app_rules.json"

def stats_file_path() -> Path:
    """The fully local usage statistics file: aggregate counters only, never leaves the machine."""
    return resolve_config_dir() / "stats.json"

def find_socket2_path() -> Optional[Path]:
    """Dynamically resolves Hyprland socket2 path without assuming fixed instance signature."""
    xdg_runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    his = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    if his:
        sock = xdg_runtime / "hypr" / his / ".socket2.sock"
        if sock.exists():
            return sock

    hypr_dir = xdg_runtime / "hypr"
    if hypr_dir.is_dir():
        sockets = list(hypr_dir.glob("*/.socket2.sock"))
        if sockets:
            sockets.sort(key=lambda s: s.stat().st_mtime, reverse=True)
            res_sock = sockets[0]
            if res_sock.parent and res_sock.parent.name:
                os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = res_sock.parent.name
            return res_sock
    return None

def derive_hyprland_instance_signature() -> Optional[str]:
    """Derives the Hyprland instance signature from $XDG_RUNTIME_DIR/hypr/<sig>/.

    Picks the newest instance directory that holds a live control socket
    (.socket.sock) or event socket (.socket2.sock)."""
    xdg_runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    hypr_dir = xdg_runtime / "hypr"
    if not hypr_dir.is_dir():
        return None
    candidates = []
    try:
        for d in hypr_dir.iterdir():
            if not d.is_dir():
                continue
            socks = [d / ".socket.sock", d / ".socket2.sock"]
            mtimes = []
            for sk in socks:
                try:
                    if sk.exists():
                        mtimes.append(sk.stat().st_mtime)
                except OSError:
                    pass
            if mtimes:
                candidates.append((max(mtimes), d.name))
    except OSError:
        return None
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]

def _ensure_hyprland_instance() -> Optional[str]:
    """Central pre-hyprctl hook: makes sure HYPRLAND_INSTANCE_SIGNATURE is set in os.environ.

    Under uwsm the systemd user service can start before uwsm exports the signature into the
    user manager environment, so the daemon process never inherits it and every hyprctl call
    fails with "HYPRLAND_INSTANCE_SIGNATURE not set". We derive it from the runtime socket dir
    (also replacing a stale signature whose directory no longer exists) so subprocesses inherit it."""
    cur = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    if cur:
        xdg_runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        inst = xdg_runtime / "hypr" / cur
        if not (xdg_runtime / "hypr").is_dir() or inst.is_dir():
            return cur
    sig = derive_hyprland_instance_signature()
    if sig:
        if sig != cur:
            print(f"ℹ️ Derived HYPRLAND_INSTANCE_SIGNATURE={sig} from runtime dir", file=sys.stderr, flush=True)
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = sig
        return sig
    return cur or None

def hyprland_socket_ready() -> bool:
    """True when a Hyprland instance socket exists (signature env is populated as a side effect)."""
    return bool(derive_hyprland_instance_signature()) and bool(_ensure_hyprland_instance())

_FLAG_OPTS = (("locked", "locked"), ("repeat", "repeating"), ("non_consuming", "non_consuming"))


def _native_stash_lua(combo: str, natives: List[Dict[str, Any]], expected: int) -> Optional[str]:
    """Lua that copies the handlers of a combo's native Lua binds into the registry stash.

    Only `__lua` binds (Omarchy's Lua config) can be stashed: their arg is the registry ref of the
    handler. Returns None when any native can't be captured, so restore falls back to a reload."""
    if len(natives) != expected or not natives:
        return None
    entries = []
    for nb in natives:
        if nb.get("dispatcher") != "__lua" or not str(nb.get("arg", "")).isdigit():
            return None
        opts = [f'description = {lua_str(nb.get("description") or "")}']
        opts += [f"{lua} = true" for js, lua in _FLAG_OPTS if nb.get(js)]
        entries.append(f'{{ h = R[{int(nb["arg"])}], o = {{ {", ".join(opts)} }} }}')
    c = lua_str(combo)
    return (f'do local R = debug.getregistry(); R.omnipal_stash = R.omnipal_stash or {{}}; '
            f'if R.omnipal_stash[{c}] == nil then R.omnipal_stash[{c}] = {{ {", ".join(entries)} }} end end')


def _native_unstash_lua(combo: str) -> str:
    """Lua that rebinds a combo's stashed native handlers; raises if the stash is gone."""
    c = lua_str(combo)
    return (f'do local R = debug.getregistry(); local S = R.omnipal_stash and R.omnipal_stash[{c}]; '
            f'if not S then error("omnipal: no stashed native for " .. {c}) end; '
            f'for _, e in ipairs(S) do if e.h == nil then error("omnipal: lost native handler") end; '
            f'hl.bind({c}, e.h, e.o) end; R.omnipal_stash[{c}] = nil end')


class OmniPalEngine:
    def __init__(self, root_dir: Optional[Path] = None, user_profiles_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent
        self.user_profiles_dir = Path(user_profiles_dir) if user_profiles_dir else resolve_user_profiles_dir()
        self.schema_file = self.root_dir / "schema" / "actions.json"
        self.snap_schema_file = self.root_dir / "schema" / "snap_layouts.json"
        self.profiles_dir = self.root_dir / "profiles"
        self.actions_catalog: Dict[str, Dict[str, Any]] = {}
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self.snap_zones: Dict[str, Dict[str, Any]] = {}
        self.snap_layouts: List[Dict[str, Any]] = []
        self._last_summon_proc = None
        self.window_policy: str = "tiled"
        self._ensure_run_dir()
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    _st = json.load(f)
                    pol = normalize_window_policy(_st.get("window_policy"))
                    if pol:
                        self.window_policy = pol
            except Exception:
                pass
        else:
            try:
                persisted_pol = self.get_persisted_window_policy()
                if persisted_pol:
                    self.window_policy = persisted_pol
            except Exception:
                pass
        self._load_catalog()
        self._load_snap_schema()
        self._write_snap_layouts_cache()
        self.baseline_bindings: Dict[str, Dict[str, Any]] = {}
        self._load_baseline_cache()
        if not self.baseline_bindings and not self._get_active_overlay():
            self._snapshot_baseline_bindings()
        # Ensure default signal handling for child processes so subprocesses
        # do not inherit SIG_IGN and fail on waitpid.
        if "unittest" not in sys.modules:
            try:
                signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            except (ValueError, AttributeError, OSError):
                pass

    def _ensure_run_dir(self):
        try:
            run_dir = _resolve_run_dir()
            run_dir.mkdir(parents=True, exist_ok=True)
            run_dir.chmod(0o700)
        except Exception:
            pass

    def _load_snap_schema(self):
        if self.snap_schema_file.exists():
            try:
                with open(self.snap_schema_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.snap_zones = data.get("zones", {})
                    self.snap_layouts = data.get("templates", [])
            except Exception as e:
                print(f"Warning: Failed to load snap schema {self.snap_schema_file.name}: {e}", file=sys.stderr)

    def _write_snap_layouts_cache(self):
        self._ensure_run_dir()
        data = {
            "zones": self.snap_zones,
            "templates": self.snap_layouts
        }
        atomic_write_json(SNAP_LAYOUTS_FILE, data)

    def get_snap_layouts(self) -> List[Dict[str, Any]]:
        return self.snap_layouts

    def get_snap_zones(self) -> Dict[str, Dict[str, Any]]:
        return self.snap_zones

    def _get_hypr_gap(self) -> int:
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(["hyprctl", "getoption", "general:gaps_out", "-j"], capture_output=True, text=True, timeout=0.3)
            data = json.loads(res.stdout)
            css = data.get("css", "10").split()
            return int(css[0]) if css else 10
        except Exception:
            return 10

    def _load_catalog(self):
        if not self.schema_file.exists():
            raise FileNotFoundError(f"Missing action schema: {self.schema_file}")
        with open(self.schema_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.actions_catalog = {a["id"]: a for a in data.get("actions", [])}

        self.profiles = {}

        # 1. Project built-in profiles (sorted)
        if self.profiles_dir.exists():
            for p_file in sorted(self.profiles_dir.glob("*.json")):
                try:
                    with open(p_file, "r", encoding="utf-8") as pf:
                        p_data = json.load(pf)
                        p_data["_source"] = "project"
                        p_data["_file"] = str(p_file)
                        p_data["_override"] = False
                        self.profiles[p_data["id"]] = p_data
                except Exception as e:
                    print(f"Warning: Failed to load profile {p_file.name}: {e}", file=sys.stderr)

        # 2. User custom profiles (merge and override by id)
        if self.user_profiles_dir.exists():
            for p_file in sorted(self.user_profiles_dir.glob("*.json")):
                try:
                    with open(p_file, "r", encoding="utf-8") as pf:
                        p_data = json.load(pf)
                        p_id = p_data.get("id")
                        if not p_id:
                            continue
                        p_data["_source"] = "user"
                        p_data["_file"] = str(p_file)
                        p_data["_override"] = p_id in self.profiles
                        self.profiles[p_id] = p_data
                except Exception as e:
                    print(f"Warning: Failed to load user profile {p_file.name}: {e}", file=sys.stderr)

    def list_profiles(self) -> List[Dict[str, Any]]:
        """Returns structured metadata for all available profiles (built-in and user)."""
        res = []
        for p_id, p_data in self.profiles.items():
            res.append({
                "id": p_id,
                "name": p_data.get("name", p_id),
                "description": p_data.get("description", ""),
                "bindings_count": len(p_data.get("bindings", [])),
                "display": p_data.get("display", {}),
                "source": p_data.get("_source", "project"),
                "override": p_data.get("_override", False),
                "file": p_data.get("_file", "")
            })
        return res

    # --- Configuration persistence (~/.config/omnipal/persistence.json; default enabled to remember last state) ---

    def get_persistence_status(self) -> Dict[str, Any]:
        """Returns the persistence state: {enabled, profile, window_policy, path, updated_at}.
        By default, configuration persistence is enabled to preserve user choice across reboots,
        unless explicitly disabled in ~/.config/omnipal/persistence.json."""
        path = persistence_file_path()
        status: Dict[str, Any] = {
            "enabled": True,
            "profile": None,
            "window_policy": None,
            "path": str(path),
            "updated_at": None
        }
        if not path.exists():
            return status
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return status
        if isinstance(data, dict):
            status["enabled"] = data.get("enabled", True) is not False
            status["profile"] = data.get("profile") if status["enabled"] else None
            status["window_policy"] = (
                normalize_window_policy(data.get("window_policy"))
                if status["enabled"]
                else None
            )
            status["updated_at"] = data.get("updated_at")
        return status

    def get_persisted_profile(self) -> Optional[str]:
        """Returns the enabled persisted profile id for daemon/startup use, or None."""
        status = self.get_persistence_status()
        profile = status.get("profile")
        if status["enabled"] and profile in self.profiles:
            return profile
        return None

    def get_persisted_window_policy(self) -> Optional[str]:
        """Returns the enabled persisted window policy for daemon/startup use, or None."""
        status = self.get_persistence_status()
        policy = status.get("window_policy")
        if status["enabled"] and policy in ("tiled", "floating"):
            return policy
        return None

    def set_persistence(
        self,
        enabled: bool,
        profile: Optional[str] = None,
        window_policy: Optional[str] = None
    ) -> bool:
        """Enables/disables profile and window policy persistence. Writes ONLY ~/.config/omnipal/persistence.json (H-1)."""
        path = persistence_file_path()

        if not enabled:
            data = {
                "enabled": False,
                "profile": None,
                "window_policy": None,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                return atomic_write_json(path, data)
            except Exception as e:
                print(f"Warning: Failed to write disabled persistence config {path}: {e}", file=sys.stderr)
                return False

        cur_persisted = self.get_persistence_status()

        # Resolve target profile:
        # passed profile -> existing persisted profile -> active mode in state -> "windows"
        target_profile = (
            profile
            or cur_persisted.get("profile")
            or self.get_state().get("mode")
            or "windows"
        ).lower().strip()

        if target_profile not in self.profiles:
            valid = ", ".join(sorted(self.profiles.keys()))
            print(f"Error: Unknown profile '{target_profile}' for persistence. Available profiles: {valid}", file=sys.stderr)
            return False

        # Resolve target window policy:
        # passed policy -> existing persisted policy -> current window policy -> "tiled"
        raw_policy = (
            window_policy
            or cur_persisted.get("window_policy")
            or self.get_window_policy()
            or "tiled"
        )
        target_policy = normalize_window_policy(raw_policy) or "tiled"

        data = {
            "enabled": True,
            "profile": target_profile,
            "window_policy": target_policy,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Warning: Failed to create config dir {path.parent}: {e}", file=sys.stderr)
            return False

        return atomic_write_json(path, data)

    # --- Fully local usage statistics (zero-overhead, silently fault-tolerant) ---

    def get_stats(self) -> Dict[str, Any]:
        """Returns the canonical local usage stats structure; empty buckets when file is missing or corrupt."""
        path = stats_file_path()
        stats: Dict[str, Any] = {"switches": {}, "snaps": {}, "actions": {}, "last_updated": None, "last_reset": None}
        if not path.exists():
            return stats
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return stats
        if isinstance(data, dict):
            for bucket in ("switches", "snaps", "actions"):
                raw = data.get(bucket)
                if isinstance(raw, dict):
                    stats[bucket] = {
                        str(k): int(v)
                        for k, v in raw.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                    }
            stats["last_updated"] = data.get("last_updated")
            stats["last_reset"] = data.get("last_reset")
        return stats

    def reset_stats(self) -> bool:
        """Clears all local usage statistics and stamps the reset time."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        ok = self._write_stats({
            "switches": {},
            "snaps": {},
            "actions": {},
            "last_updated": None,
            "last_reset": now
        })
        if not ok:
            print(f"Warning: Failed to reset stats file {stats_file_path()}", file=sys.stderr)
        return ok

    def record_switch(self, mode_id: str) -> None:
        """Counts a successful mode switch. Any stats failure stays silent: never affects live switching."""
        self._record_stat("switches", mode_id)

    def record_snap(self, zone: str) -> None:
        """Counts a snap invocation (left, right, layouts, center, ...). Silent on any failure."""
        self._record_stat("snaps", zone)

    def record_action(self, action_id: str) -> None:
        """Counts an action trigger. Silent on any failure."""
        self._record_stat("actions", action_id)

    def _record_stat(self, bucket: str, key: str) -> None:
        try:
            key = (key or "").strip().lower()
            if not key:
                return
            with engine_lock(timeout=0.5):
                stats = self.get_stats()
                stats[bucket][key] = stats[bucket].get(key, 0) + 1
                stats["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                self._write_stats(stats)
        except Exception:
            pass

    def _write_stats(self, data: Dict[str, Any]) -> bool:
        path = stats_file_path()
        return atomic_write_json(path, data)

    def _eval_lua(self, lua_code: str) -> bool:
        """Executes Lua expressions in Omarchy Hyprland compositor with strict error checking."""
        if not lua_code.strip():
            return True
        if compositor_mutation_disabled():
            return True
        _ensure_hyprland_instance()
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(
                ["hyprctl", "eval", lua_code],
                capture_output=True,
                text=True,
                check=False,
                env=os.environ,
                timeout=3.0
            )
            if res.returncode != 0:
                print(f"Hyprland eval failed (exit {res.returncode}): {res.stdout.strip()}", file=sys.stderr)
                return False
            out = res.stdout.strip()
            if out.startswith("error:") or "runtime error:" in out.lower():
                print(f"Hyprland eval error: {out}", file=sys.stderr)
                return False
            return True
        except Exception as e:
            print(f"Hyprland eval exception: {e}", file=sys.stderr)
            return False

    def _eval_lua_strict(self, lua_code: str) -> bool:
        """Like _eval_lua, but only `ok` from hyprctl counts as success (catches Lua error())."""
        if compositor_mutation_disabled():
            return True
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(["hyprctl", "eval", lua_code], capture_output=True, text=True,
                                 check=False, env=os.environ, timeout=3.0)
            out = res.stdout.strip()
            if res.returncode == 0 and out == "ok":
                return True
            print(f"Hyprland strict eval failed: rc={res.returncode} stdout={res.stdout!r} "
                  f"stderr={res.stderr!r} code={lua_code[:400]!r}", file=sys.stderr)
        except Exception as e:
            print(f"Hyprland eval exception: {e}", file=sys.stderr)
        return False

    def _reload_config_only(self, timeout: float = 3.0) -> bool:
        """Reloads compositor config and reports whether the mutation completed."""
        if compositor_mutation_disabled():
            return True
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(
                ["hyprctl", "reload", "config-only"],
                capture_output=True,
                text=True,
                check=False,
                env=os.environ,
                timeout=timeout,
            )
            output = f"{res.stdout}\n{res.stderr}".lower()
            return res.returncode == 0 and "error" not in output
        except Exception as e:
            print(f"Hyprland config reload failed: {e}", file=sys.stderr)
            return False

    def _get_applied_window_mode(self) -> str:
        if APPLIED_WINDOW_MODE_FILE.exists():
            try:
                val = APPLIED_WINDOW_MODE_FILE.read_text(encoding="utf-8").strip()
                if val in ("floating", "tiled"):
                    return val
            except Exception:
                pass
        return "tiled"

    def _set_applied_window_mode(self, mode: str):
        self._ensure_run_dir()
        try:
            APPLIED_WINDOW_MODE_FILE.write_text(mode, encoding="utf-8")
        except Exception:
            pass

    def _live_bind_counts(self) -> Dict[Tuple[int, str], int]:
        """How many compositor key binds sit on each (modmask, KEY); empty if hyprctl can't be queried."""
        counts: Dict[Tuple[int, str], int] = {}
        if compositor_mutation_disabled():
            return counts
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(["hyprctl", "binds", "-j"], capture_output=True, text=True,
                                 check=True, timeout=2.0, env=os.environ)
            for b in json.loads(res.stdout or "[]"):
                if not isinstance(b, dict) or b.get("mouse") or b.get("release"):
                    continue
                if b.get("submap"):
                    continue
                sig = (int(b.get("modmask", 0) or 0), str(b.get("key", "")).upper())
                counts[sig] = counts.get(sig, 0) + 1
        except Exception as e:
            _debug(f"binds query failed: {e}")
        return counts

    def _live_bind_details(self) -> Dict[Tuple[int, str], List[Dict[str, Any]]]:
        """Live keyboard binds grouped by (modmask, KEY), with handler/arg/flags from hyprctl."""
        out: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
        if compositor_mutation_disabled():
            return out
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(["hyprctl", "binds", "-j"], capture_output=True, text=True,
                                 check=True, timeout=2.0, env=os.environ)
            for b in json.loads(res.stdout or "[]"):
                if not isinstance(b, dict) or b.get("mouse") or b.get("release") or b.get("submap"):
                    continue
                sig = (int(b.get("modmask", 0) or 0), str(b.get("key", "")).upper())
                out.setdefault(sig, []).append(b)
        except Exception as e:
            _debug(f"binds detail query failed: {e}")
        return out

    def _native_details(self, own_overlay: Optional[List[Dict[str, Any]]] = None) -> Dict[Tuple[int, str], List[Dict[str, Any]]]:
        """Live bind details minus binds OmniPal's own overlay injected (matched by description)."""
        details = self._live_bind_details()
        for b in own_overlay or []:
            sig = combo_signature(b.get("combo", ""))
            lst = details.get(sig)
            if not lst:
                continue
            name = b.get("name", "")
            for i, nb in enumerate(lst):
                if (nb.get("description") or "") == name:
                    del lst[i]
                    break
            else:
                lst.pop()
        return details

    def _native_counts(self, own_overlay: Optional[List[Dict[str, Any]]] = None) -> Dict[Tuple[int, str], int]:
        """Live binds minus the ones `own_overlay` (OmniPal's currently injected binds) put there."""
        counts = self._live_bind_counts()
        for b in own_overlay or []:
            sig = combo_signature(b.get("combo", ""))
            if counts.get(sig, 0) > 0:
                counts[sig] -= 1
        return counts

    def _build_bind_ops(self, target_bindings: List[Dict[str, Any]],
                        native_counts: Optional[Dict[Tuple[int, str], int]] = None,
                        native_details: Optional[Dict[Tuple[int, str], List[Dict[str, Any]]]] = None) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Builds unbind-then-bind Lua ops (incl. shortcut forwarding) and overlay records for bindings.

        native_counts (from _native_counts) marks combos that displace a live native Omarchy bind:
        those are unbound once per native bind (a combo can carry several, e.g. ALT + TAB) and the
        record gets native_unbound=True so restore() reloads Hyprland to bring the natives back."""
        native_counts = native_counts or {}
        native_details = native_details or {}
        lua_ops: List[str] = []
        records: List[Dict[str, Any]] = []
        terminals = None
        for b in target_bindings:
            action_id = b.get("action")
            action_meta = self.actions_catalog.get(action_id, {})
            name = action_meta.get("name", action_id)
            mod = b.get("mod", "").strip()
            key = b.get("key", "").strip()
            if not key:
                continue
            combo = format_combo(mod, key)
            sig = combo_signature(combo)
            n_native = native_counts.get(sig, 0)
            unbind_native = n_native > 0
            # Stash the native handlers in the Lua registry before unbinding them, so restore()
            # can rebind them exactly instead of reloading all of Hyprland (screen flash).
            restorable = True
            if n_native > 0:
                stash = _native_stash_lua(combo, native_details.get(sig, []), n_native)
                if stash:
                    lua_ops.append(stash)
                else:
                    restorable = False
            # Extra unbinds for combos carrying more than one native bind (first one is below).
            for _ in range(max(0, n_native - 1)):
                lua_ops.append(f'hl.unbind({lua_str(combo)})')
            if action_id == FORWARD_ACTION:
                try:
                    mods, fkey = parse_forward(b.get("forward", ""))
                except ValueError as e:
                    print(f"Skipping forward binding {combo}: {e}", file=sys.stderr)
                    continue
                if terminals is None:
                    terminals = load_terminal_patterns()
                lua_ops.append(f'hl.unbind({lua_str(combo)})')
                lua_ops.append(f'o.bind({lua_str(combo)}, {lua_str(name)}, {forward_lua(mods, fkey, terminals)})')
                unbind_native = True
                # With no live bind table we can't prove no native was dropped: keep the reload path.
                if not native_counts:
                    restorable = False
            elif action_id in LUA_DISPATCHERS:
                lua_ops.append(f'hl.unbind({lua_str(combo)})')
                lua_ops.append(f'o.bind({lua_str(combo)}, {lua_str(name)}, {LUA_DISPATCHERS[action_id]})')
            else:
                cmd = b.get("arg") or action_meta.get("default_arg", "")
                lua_ops.append(f'hl.unbind({lua_str(combo)})')
                lua_ops.append(f'o.bind({lua_str(combo)}, {lua_str(name)}, {lua_str(cmd)})')
            records.append({
                "action": action_id,
                "combo": combo,
                "name": name,
                **({"native_unbound": True} if unbind_native else {}),
                **({"native_restorable": restorable, "native_count": n_native} if unbind_native else {}),
            })
        return lua_ops, records

    def _reinject_active_bindings(self, target_mode: str) -> bool:
        """Re-applies the active overlay bindings into Hyprland (e.g. after a config reload)."""
        if target_mode not in self.profiles or target_mode == "omarchy":
            return True
        target_profile = self.profiles[target_mode]
        target_bindings = target_profile.get("bindings", [])
        # Called after a config reload: the overlay is gone and natives are back, so live == native.
        live = self._live_bind_counts()
        lua_ops, new_overlay_records = self._build_bind_ops(target_bindings, live, self._live_bind_details())
        if lua_ops:
            lua_ops.insert(0, 'debug.getregistry().omnipal_stash = nil')

        if lua_ops:
            ok = self._eval_lua("; ".join(lua_ops))
            if ok:
                self._write_active_overlay(new_overlay_records)
            return ok
        return True

    def _apply_golden_cascade_geometry(
        self,
        addr: str,
        step: int = 0,
        is_dialog: bool = False,
        monitor: Optional[Union[int, str, Dict[str, Any]]] = None
    ):
        """Applies mature golden dimensions (0.618 x 0.70) and terraced cascading placement to a floating window."""
        clean_addr = _escape_lua_string(addr)

        target_mon_lua = "nil"
        if isinstance(monitor, dict):
            mx = monitor.get("x", 0)
            my = monitor.get("y", 0)
            mw = monitor.get("width", 1920)
            mh = monitor.get("height", 1080)
            res = monitor.get("reserved", [0, 0, 0, 0])
            if isinstance(res, list):
                r_left = res[0] if len(res) > 0 else 0
                r_top = res[1] if len(res) > 1 else 0
                r_right = res[2] if len(res) > 2 else 0
                r_bottom = res[3] if len(res) > 3 else 0
            elif isinstance(res, dict):
                r_left = res.get("left", 0)
                r_top = res.get("top", 0)
                r_right = res.get("right", 0)
                r_bottom = res.get("bottom", 0)
            else:
                r_left = r_top = r_right = r_bottom = 0
            target_mon_lua = (
                f"{{ x = {mx}, y = {my}, width = {mw}, height = {mh}, "
                f"reserved = {{ left = {r_left}, top = {r_top}, right = {r_right}, bottom = {r_bottom} }} }}"
            )
        elif isinstance(monitor, int):
            target_mon_lua = str(int(monitor))
        elif isinstance(monitor, str) and monitor.strip():
            target_mon_lua = f'"{_escape_lua_string(monitor.strip())}"'

        lua_code = f"""
local addr = "{clean_addr}"
local step = {int(step)}
local is_dialog = {1 if is_dialog else 0}
local target_mon = {target_mon_lua}

local m = nil
if type(target_mon) == "table" and target_mon.width and target_mon.height then
  m = target_mon
end

if not m and type(hl) == "table" and type(hl.get_windows) == "function" and type(hl.get_monitors) == "function" then
  local win_mon = nil
  local win_ws_id = nil
  for _, win in ipairs(hl.get_windows()) do
    if win.address == addr then
      win_mon = win.monitor
      if type(win.workspace) == "table" then
        win_ws_id = win.workspace.id
      elseif type(win.workspace) == "number" or type(win.workspace) == "string" then
        win_ws_id = win.workspace
      end
      break
    end
  end

  local mon_to_match = (target_mon ~= nil and target_mon ~= "") and target_mon or win_mon
  if mon_to_match ~= nil then
    for _, mon in ipairs(hl.get_monitors()) do
      if mon.id == mon_to_match or mon.name == mon_to_match or tostring(mon.id) == tostring(mon_to_match) then
        m = mon
        break
      end
    end
  end

  if not m and win_ws_id ~= nil then
    for _, mon in ipairs(hl.get_monitors()) do
      if type(mon.activeWorkspace) == "table" and (mon.activeWorkspace.id == win_ws_id or mon.activeWorkspace.name == tostring(win_ws_id)) then
        m = mon
        break
      end
    end
  end
end

if not m and type(hl) == "table" and type(hl.get_active_monitor) == "function" then
  m = hl.get_active_monitor()
end
if not m then return end

local gap = 12
local rx = m.x + (m.reserved and m.reserved.left or 0) + gap
local ry = m.y + (m.reserved and m.reserved.top or 0) + gap
local rw = m.width - (m.reserved and (m.reserved.left + m.reserved.right) or 0) - gap * 2
local rh = m.height - (m.reserved and (m.reserved.top + m.reserved.bottom) or 0) - gap * 2

if type(hl) == "table" and type(hl.dispatch) == "function" and type(hl.dsp) == "table" and type(hl.dsp.window) == "table" then
  hl.dispatch(hl.dsp.window.float({{ action = "enable", window = "address:" .. addr }}))

  if is_dialog == 1 then
    hl.dispatch(hl.dsp.window.center({{ window = "address:" .. addr }}))
  else
    -- Mature Golden Dimensions (成熟黄金比例: ~61.8% x ~70%)
    local gw = math.floor(rw * 0.618)
    local gh = math.floor(rh * 0.70)

    -- Ergonomic bounds clamping
    if gw < 800 and rw >= 800 then gw = 800 end
    if gw > rw - 40 then gw = rw - 40 end
    if gh < 550 and rh >= 550 then gh = 550 end
    if gh > rh - 40 then gh = rh - 40 end

    -- Base centered origin
    local cx = rx + math.floor((rw - gw) / 2)
    local cy = ry + math.floor((rh - gh) / 2)

    -- Terraced cascading offset (梯田叠式阶梯偏移: 每步 38px，6 步一循环)
    local delta = 38
    local max_steps = 6
    local offset_idx = step % max_steps
    local ox = math.floor((offset_idx - 2.5) * delta)
    local oy = math.floor((offset_idx - 2.5) * delta)

    local tx = cx + ox
    local ty = cy + oy

    -- Screen boundary protection
    if tx < rx then tx = rx end
    if (tx + gw) > (rx + rw) then tx = rx + rw - gw end
    if ty < ry then ty = ry end
    if (ty + gh) > (ry + rh) then ty = ry + rh - gh end

    hl.dispatch(hl.dsp.window.resize({{ x = gw, y = gh, window = "address:" .. addr }}))
    hl.dispatch(hl.dsp.window.move({{ x = tx, y = ty, window = "address:" .. addr }}))
  end
end
"""
        self._eval_lua(lua_code)

    def _float_existing_windows(self):
        """Floats existing non-floating client windows and arranges them in golden terraced cascade."""
        try:
            clients = self.get_windows()
            step = 0
            for c in clients:
                if not c.get("mapped", True) or c.get("hidden", False):
                    continue
                addr = c.get("address")
                if not addr:
                    continue
                if c.get("pinned", False) or c.get("fullscreen", 0):
                    continue

                cls_name = str(c.get("class", ""))
                title = str(c.get("title", ""))
                ws = c.get("workspace", {})
                ws_name = str(ws.get("name", ""))
                ws_id = ws.get("id")
                size = c.get("size", [0, 0])
                mon = c.get("monitor")

                skip, is_dlg = is_special_window(
                    cls_name=cls_name,
                    title=title,
                    ws_name=ws_name,
                    ws_id=ws_id,
                    size=size
                )
                if skip:
                    continue

                self._apply_golden_cascade_geometry(addr, step=step, is_dialog=is_dlg, monitor=mon)
                if not is_dlg:
                    step = (step + 1) % 6
        except Exception:
            pass

    def _unfloat_existing_windows(self):
        """Unfloats existing floating client windows in the active workspace when returning to tiled mode."""
        try:
            clients = self.get_windows()
            if not clients:
                return

            active_ws_ids = set()
            try:
                _ensure_hyprland_instance()
                mon_out = subprocess.check_output(["hyprctl", "monitors", "-j"], text=True, timeout=0.5)
                monitors = json.loads(mon_out)
                for m in monitors:
                    ws = m.get("activeWorkspace")
                    if ws and "id" in ws:
                        active_ws_ids.add(ws["id"])
            except Exception:
                pass

            if not active_ws_ids:
                try:
                    _ensure_hyprland_instance()
                    act_out = subprocess.check_output(["hyprctl", "activeworkspace", "-j"], text=True, timeout=0.5)
                    act = json.loads(act_out)
                    if "id" in act:
                        active_ws_ids.add(act["id"])
                except Exception:
                    pass

            to_unfloat = []
            for c in clients:
                if not c.get("mapped", True) or c.get("hidden", False):
                    continue
                if not c.get("floating", False):
                    continue
                if c.get("pinned", False) or c.get("fullscreen", 0):
                    continue

                ws = c.get("workspace", {})
                ws_id = ws.get("id")
                ws_name = str(ws.get("name", ""))

                if active_ws_ids and ws_id not in active_ws_ids:
                    continue

                cls_name = str(c.get("class", ""))
                title = str(c.get("title", ""))
                size = c.get("size", [0, 0])

                skip, is_dlg = is_special_window(
                    cls_name=cls_name,
                    title=title,
                    ws_name=ws_name,
                    ws_id=ws_id,
                    size=size
                )
                # Do not unfloat special windows (PiP, scratchpad, micro-windows) or dialogs
                if skip or is_dlg:
                    continue

                addr = c.get("address")
                if addr:
                    to_unfloat.append(addr)

            if not to_unfloat:
                return

            lua_ops = []
            for addr in to_unfloat:
                esc_addr = _escape_lua_string(addr)
                lua_ops.append(
                    f'if type(hl) == "table" and type(hl.dispatch) == "function" and type(hl.dsp) == "table" and type(hl.dsp.window) == "table" then '
                    f'hl.dispatch(hl.dsp.window.float({{ action = "off", window = "address:{esc_addr}" }})) end'
                )
            ok = self._eval_lua("; ".join(lua_ops))
            if not ok:
                for addr in to_unfloat:
                    try:
                        _ensure_hyprland_instance()
                        subprocess.run(
                            ["hyprctl", "dispatch", "togglefloating", f"address:{addr}"],
                            capture_output=True,
                            timeout=0.5
                        )
                    except Exception:
                        pass
        except Exception:
            pass

    def _apply_window_policy(self, force: bool = False) -> bool:
        """Applies the current effective window policy (tiled vs floating) to Hyprland."""
        _ensure_hyprland_instance()
        sock = find_socket2_path()
        if not sock or not sock.exists():
            return True

        target_mode = self.get_effective_window_mode()
        cur_applied = self._get_applied_window_mode()

        if target_mode == "floating":
            if not force and cur_applied == "floating":
                return True
            lua_code = (
                'if type(hl) == "table" and type(hl.window_rule) == "function" then '
                'hl.window_rule({ match = {}, float = true, center = true }); '
                'hl.window_rule({ match = { class = ".*" }, float = true, center = true }); '
                'hl.window_rule({ match = { tag = "chromium-based-browser" }, float = true, center = true }); '
                'hl.window_rule({ match = { tag = "terminal" }, float = true, center = true }) '
                'end; '
                'if type(o) == "table" and type(o.window) == "function" then '
                'o.window(".*", { float = true, center = true }); '
                'o.window({ tag = "chromium-based-browser" }, { float = true, center = true }); '
                'o.window({ tag = "terminal" }, { float = true, center = true }) '
                'end'
            )
            ok = self._eval_lua(lua_code)
            if ok:
                self._set_applied_window_mode("floating")
                self._float_existing_windows()
            return ok
        else:
            # target_mode == "tiled"
            if not force and cur_applied != "floating":
                return True
            if not self._reload_config_only():
                return False
            self._unfloat_existing_windows()
            self._set_applied_window_mode("tiled")

            st = self.get_state()
            active_m = st.get("mode", "omarchy")
            if active_m != "omarchy":
                self._reinject_active_bindings(active_m)
            return True

    def get_effective_window_mode(self, mode: Optional[str] = None, policy: Optional[str] = None) -> str:
        pol = normalize_window_policy(policy) or self.get_window_policy()
        if pol == "follow-profile":
            if mode is None:
                cur_m = (self.get_state().get("mode") if hasattr(self, "get_state") else "omarchy")
            else:
                cur_m = mode
            m = str(cur_m).lower().strip()
            return "floating" if m == "mac" else "tiled"
        return "floating" if pol == "floating" else "tiled"

    def get_window_policy(self) -> str:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        pol = normalize_window_policy(data.get("window_policy"))
                        if pol:
                            self.window_policy = pol
                            return pol
            except Exception as _e:
                _debug(_e)
        return normalize_window_policy(getattr(self, "window_policy", None)) or "tiled"

    def set_window_policy(self, policy: str) -> bool:
        with engine_lock():
            norm = normalize_window_policy(policy)
            if not norm:
                return False
            previous_policy = self.get_window_policy()
            self.window_policy = norm
            cur_state = self.get_state()
            cur_mode = cur_state.get("mode", "omarchy")
            count = cur_state.get("active_bindings_count", 0)
            self._write_state(cur_mode, count, policy=norm)
            try:
                applied = self._apply_window_policy(force=True)
            except Exception as e:
                print(f"Warning: Failed to apply window policy '{norm}': {e}", file=sys.stderr)
                applied = False
            if not applied:
                self.window_policy = previous_policy
                self._write_state(cur_mode, count, policy=previous_policy)
                print(f"Warning: Compositor rejected window policy '{norm}'; previous policy restored", file=sys.stderr)
                return False
            if self.get_persistence_status()["enabled"]:
                self.set_persistence(True, window_policy=norm)
            return True

    def get_state(self) -> Dict[str, Any]:
        cur_policy = self.get_window_policy()
        sock = find_socket2_path()
        compositor_connected = sock is not None and sock.exists()
        default_state = {
            "version": __version__,
            "mode": "omarchy",
            "name": "Omarchy 原生模式",
            "display": self.profiles.get("omarchy", {}).get("display", {"icon": "⊡", "brief": "OMA", "color": "#a3be8c"}),
            "active_bindings_count": 0,
            "status": "idle",
            "window_policy": cur_policy,
            "effective_window_mode": self.get_effective_window_mode("omarchy", cur_policy),
            "compositor_connected": compositor_connected
        }
        if not STATE_FILE.exists():
            return default_state
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return default_state
                pol = normalize_window_policy(data.get("window_policy")) or cur_policy
                self.window_policy = pol
                data["window_policy"] = pol
                cur_m = data.get("mode", "omarchy")
                data["effective_window_mode"] = self.get_effective_window_mode(cur_m, pol)
                data["compositor_connected"] = compositor_connected
                if "display" not in data or not data["display"]:
                    data["display"] = self.profiles.get(cur_m, {}).get("display", {})
                return data
        except Exception:
            return default_state

    def _write_state(self, mode: str, count: int, policy: Optional[str] = None):
        self._ensure_run_dir()
        profile_data = self.profiles.get(mode, {})
        profile_name = profile_data.get("name", mode)
        display_meta = profile_data.get("display", {})
        daemon_pid = None
        if PID_FILE.exists():
            try:
                daemon_pid = int(PID_FILE.read_text().strip())
            except Exception as _e:
                _debug(_e)

        if policy:
            cur_policy = normalize_window_policy(policy)
        else:
            cur_policy = None
            if STATE_FILE.exists():
                try:
                    with open(STATE_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            cur_policy = normalize_window_policy(data.get("window_policy"))
                except Exception as _e:
                    _debug(_e)
            if not cur_policy:
                cur_policy = normalize_window_policy(getattr(self, "window_policy", None)) or "tiled"

        cur_policy = cur_policy or "tiled"
        self.window_policy = cur_policy
        effective_mode = self.get_effective_window_mode(mode, cur_policy)
        sock = find_socket2_path()
        compositor_connected = sock is not None and sock.exists()

        state_data = {
            "version": __version__,
            "mode": mode,
            "name": profile_name,
            "display": display_meta,
            "active_bindings_count": count,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "pid": os.getpid(),
            "daemon_pid": daemon_pid,
            "status": "active" if mode != "omarchy" else "native",
            "window_policy": cur_policy,
            "effective_window_mode": effective_mode,
            "compositor_connected": compositor_connected,
        }
        write_state_json(STATE_FILE, state_data)
        if not compositor_mutation_disabled():
            try:
                subprocess.Popen(
                    ["omarchy-shell", "-q", "omni.mode-indicator", "refresh"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass


    def _get_active_overlay(self) -> List[Dict[str, str]]:
        if not OVERLAY_FILE.exists():
            return []
        try:
            with open(OVERLAY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _write_active_overlay(self, bindings: List[Dict[str, str]]):
        self._ensure_run_dir()
        atomic_write_json(OVERLAY_FILE, bindings)

    def _load_baseline_cache(self) -> Dict[str, Dict[str, Any]]:
        """Loads cached baseline bindings from BASELINE_FILE if present."""
        if BASELINE_FILE.exists():
            try:
                with open(BASELINE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.baseline_bindings = data
                        return self.baseline_bindings
            except Exception:
                pass
        return self.baseline_bindings

    def _snapshot_baseline_bindings(self, force: bool = False) -> Dict[str, Dict[str, Any]]:
        """Snapshots compositor keybindings that overlap with OmniPal profiles/actions.

        Captures native or user-customized bindings prior to applying any overlay.
        Stores them in memory (self.baseline_bindings) and caches to BASELINE_FILE."""
        if not force and self.baseline_bindings:
            return self.baseline_bindings

        if not force and BASELINE_FILE.exists():
            loaded = self._load_baseline_cache()
            if loaded:
                return loaded

        # If an active overlay is currently applied and force is not requested,
        # avoid capturing OmniPal's own injected bindings as baseline.
        if not force:
            active_overlay = self._get_active_overlay()
            if active_overlay:
                return self.baseline_bindings

        _ensure_hyprland_instance()
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(
                ["hyprctl", "binds", "-j"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
                env=os.environ
            )
            if res.returncode != 0 or not res.stdout.strip():
                return self.baseline_bindings
            binds = json.loads(res.stdout)
            if not isinstance(binds, list):
                return self.baseline_bindings
        except Exception:
            return self.baseline_bindings

        # Collect all combos in loaded profiles
        overlapping_combos = set()
        for p in self.profiles.values():
            for b in p.get("bindings", []):
                combo = format_combo(b.get("mod", ""), b.get("key", ""))
                if combo:
                    overlapping_combos.add(combo)

        # Common Omarchy native baseline combos that can be customized
        omarchy_core_combos = {
            "SUPER + W", "SUPER + SPACE", "SUPER + T", "SUPER + F", "SUPER + J",
            "SUPER + RETURN", "SUPER + E", "SUPER + L", "SUPER + V", "SUPER + Q"
        }

        # Collect action metadata for semantic overlap matching
        action_matchers = set()
        for a_id, a in self.actions_catalog.items():
            action_matchers.add(a_id.lower())
            if a.get("name"):
                action_matchers.add(a["name"].strip().lower())
            disp_cmd = a.get("dispatcher", "").strip().lower()
            if disp_cmd and disp_cmd != "exec":
                action_matchers.add(disp_cmd)

        semantic_keywords = (
            "close window", "killactive", "togglefloating", "fullscreen",
            "launcher", "menu", "terminal", "file manager", "lock screen",
            "clipboard", "screenshot", "emoji", "cheatsheet", "overview"
        )

        captured: Dict[str, Dict[str, Any]] = {}
        for b in binds:
            if not isinstance(b, dict):
                continue
            modmask = b.get("modmask", 0)
            key = b.get("key", "")
            if not key and b.get("keycode", 0) > 0:
                key = f"code:{b.get('keycode')}"
            if not key:
                continue

            mods = []
            if modmask & 64:
                mods.append("SUPER")
            if modmask & 4:
                mods.append("CTRL")
            if modmask & 8:
                mods.append("ALT")
            if modmask & 1:
                mods.append("SHIFT")

            combo = format_combo(" ".join(mods), key)
            desc = (b.get("description") or "").strip()
            disp = (b.get("dispatcher") or "").strip()
            desc_lower = desc.lower()

            is_overlap = (
                combo in overlapping_combos
                or combo in omarchy_core_combos
                or desc_lower in action_matchers
                or (disp and disp.lower() in action_matchers)
                or any(kw in desc_lower for kw in semantic_keywords)
            )
            if is_overlap:
                captured[combo] = {
                    "combo": combo,
                    "mod": " ".join(mods),
                    "key": key,
                    "modmask": modmask,
                    "description": desc,
                    "dispatcher": disp,
                    "arg": str(b.get("arg", "")),
                    "submap": b.get("submap", "")
                }

        if captured:
            self.baseline_bindings = captured
            self._ensure_run_dir()
            atomic_write_json(BASELINE_FILE, captured)

        return self.baseline_bindings

    def _build_dynamic_restore_lua(self, filter_combos: Optional[Set[str]] = None) -> Optional[str]:
        """Builds Lua statements to restore the exact captured baseline bindings.
        If filter_combos is specified, only restores bindings for those combos."""
        if not self.baseline_bindings:
            return None

        lua_ops = []
        lua_ops.append('local reg = debug.getregistry()')

        for combo, b in self.baseline_bindings.items():
            if filter_combos is not None and combo not in filter_combos:
                continue
            disp = b.get("dispatcher", "")
            arg = str(b.get("arg", "")).strip()
            desc = _escape_lua_string(b.get("description", ""))
            esc_combo = _escape_lua_string(combo)

            if disp == "__lua" and arg.isdigit():
                arg_num = int(arg)
                lua_ops.append(
                    f'local fn_{arg_num} = reg and reg[{arg_num}]; '
                    f'if type(fn_{arg_num}) == "function" then '
                    f'hl.bind("{esc_combo}", fn_{arg_num}, {{ description = "{desc}" }}) '
                    f'end'
                )
            elif disp == "exec" and arg:
                esc_arg = _escape_lua_string(arg)
                lua_ops.append(f'o.bind("{esc_combo}", "{desc}", "{esc_arg}")')
            elif disp in LUA_DISPATCHERS:
                lua_ops.append(f'o.bind("{esc_combo}", "{desc}", {LUA_DISPATCHERS[disp]})')
            elif disp == "killactive":
                lua_ops.append(f'o.bind("{esc_combo}", "{desc}", hl.dsp.window.close())')
            elif disp == "togglefloating":
                lua_ops.append(f'o.bind("{esc_combo}", "{desc}", hl.dsp.window.float({{ action = "toggle" }}))')
            elif disp == "fullscreen":
                lua_ops.append(f'o.bind("{esc_combo}", "{desc}", hl.dsp.window.fullscreen({{ mode = "fullscreen" }}))')
            elif arg:
                esc_arg = _escape_lua_string(arg)
                lua_ops.append(f'o.bind("{esc_combo}", "{desc}", "{esc_arg}")')

        if len(lua_ops) <= 1:
            return None

        return "; ".join(lua_ops)

    def restore(self) -> bool:
        """Restores Hyprland keybindings by unbinding all currently injected overlays and re-registering baseline."""
        with engine_lock():
            active_overlay = self._get_active_overlay()
            lua_lines = []
            for b in active_overlay:
                combo = b.get("combo")
                if combo:
                    lua_lines.append(f'hl.unbind({lua_str(combo)})')

            # Dynamic restore if snapshot exists, fallback to LUA_RESTORE_BASELINE
            if not self.baseline_bindings:
                self._load_baseline_cache()

            # Combos whose natives were stashed are rebound from the stash below; skip them here
            # (their baseline registry refs were freed by the unbind and must not be reused).
            stashed = {b.get("combo") for b in active_overlay
                       if b.get("native_unbound") and b.get("native_count", 0) > 0}
            filt = None
            if stashed and self.baseline_bindings:
                filt = set(self.baseline_bindings) - stashed
            dynamic_lua = self._build_dynamic_restore_lua(filter_combos=filt)
            if dynamic_lua:
                lua_lines.append(dynamic_lua)
            elif not stashed:
                lua_lines.append(LUA_RESTORE_BASELINE)

            success = self._eval_lua("; ".join(lua_lines))

            # Never discard the active overlay while the compositor still reports a failure.
            # Keeping it allows a later daemon reconnect or explicit retry to finish Restore.
            if not success:
                print("Warning: Restore evaluation failed; retaining active overlay for retry", file=sys.stderr)
                return False

            policy_restored = True
            if self._get_applied_window_mode() == "floating":
                policy_restored = self._reload_config_only()
                if policy_restored:
                    self._set_applied_window_mode("tiled")
            if not policy_restored:
                print("Warning: Restore window policy reload failed; retaining active overlay for retry", file=sys.stderr)
                return False

            try:
                if OVERLAY_FILE.exists():
                    OVERLAY_FILE.unlink()
            except Exception:
                pass

            self._write_state("omarchy", 0)
            # State is already "omarchy", so the reload watcher won't re-apply an overlay.
            # Natives we unbound are rebound from the Lua stash; reload only if that isn't possible.
            unbound = [b for b in active_overlay if b.get("native_unbound")]
            if not unbound:
                return True
            if all(b.get("native_restorable", False) for b in unbound):
                restore_ops = [_native_unstash_lua(b["combo"]) for b in unbound
                               if b.get("native_count", 0) > 0]
                if not restore_ops or self._eval_lua_strict("; ".join(restore_ops)):
                    return True
                print("Native rebind from stash failed; falling back to hyprctl reload", file=sys.stderr)
            return self._reload_hyprland()

    def _reload_hyprland(self) -> bool:
        if compositor_mutation_disabled():
            return True
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(["hyprctl", "reload"], capture_output=True, text=True, check=False)
            return res.returncode == 0
        except Exception as e:
            print(f"hyprctl reload failed: {e}", file=sys.stderr)
            return False

    def send_shortcut(self, spec: str, window_class: Optional[str] = None) -> bool:
        """Forwards a shortcut to the focused window, adjusted for terminals."""
        if window_class is None:
            window_class = ""
            try:
                _ensure_hyprland_instance()
                res = subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True, text=True, check=False)
                window_class = (json.loads(res.stdout or "{}") or {}).get("class", "") or ""
            except Exception as e:
                _debug(e)
        try:
            mods, key = forward_for_class(spec, window_class)
        except ValueError as e:
            print(f"Invalid shortcut: {e}", file=sys.stderr)
            return False
        arg = f"{' '.join(mods)}, {key}, activewindow"
        _ensure_hyprland_instance()
        res = subprocess.run(["hyprctl", "dispatch", "sendshortcut", arg], capture_output=True, text=True, check=False)
        return res.returncode == 0 and "error" not in (res.stdout or "").lower()

    def switch_mode(self, target_mode: str, record: bool = True, _rollback: bool = False) -> bool:
        """Atomically switches the in-memory keybindings to target_mode with rollback on error.

        record=False skips the local-usage-stats increment (used by the non-destructive
        benchmark, which measures switches without changing the user's real session)."""
        with engine_lock():
            target_mode = target_mode.lower().strip()
            if target_mode not in self.profiles:
                valid_modes = ", ".join(self.profiles.keys())
                raise ValueError(f"Unknown mode '{target_mode}'. Available modes: {valid_modes}")

            # Switching to omarchy mode means clearing all overlays and restoring system baseline
            if target_mode == "omarchy":
                ok = self.restore()
                if ok and record:
                    self.record_switch("omarchy")
                if ok and self.get_persistence_status()["enabled"]:
                    self.set_persistence(True, profile="omarchy")
                return ok

            previous_mode = self.get_state().get("mode", "omarchy")
            target_profile = self.profiles[target_mode]
            target_bindings = target_profile.get("bindings", [])

            # A previous overlay that unbound natives needs a restore first (exact rebind, reload only as fallback)
            if any(b.get("native_unbound") for b in self._get_active_overlay()):
                if not self.restore():
                    return False

            # Ensure baseline snapshot is captured before any new overlay is applied
            if not self.baseline_bindings:
                self._snapshot_baseline_bindings()

            # Stage 1: Unbind previous overlay
            current_overlay = self._get_active_overlay()
            lua_ops = []
            if current_overlay:
                current_combos = set()
                for b in current_overlay:
                    combo = b.get("combo")
                    if combo:
                        current_combos.add(combo)
                        lua_ops.append(f'hl.unbind({lua_str(combo)})')

                # Stage 2: Restore baseline bindings only for combos released by previous profile
                target_combos = {
                    format_combo(b.get("mod", "").strip(), b.get("key", "").strip())
                    for b in target_bindings
                    if b.get("key", "").strip()
                }
                released_combos = current_combos - target_combos
                if released_combos:
                    dynamic_lua = self._build_dynamic_restore_lua(filter_combos=released_combos)
                    if dynamic_lua:
                        lua_ops.append(dynamic_lua)


            # Stage 3: Unbind-before-bind for every target combo (incl. forwarded shortcuts)
            # Native binds = live binds minus those our current overlay injected.
            native_counts = self._native_counts(current_overlay)
            native_details = self._native_details(current_overlay)
            bind_ops, new_overlay_records = self._build_bind_ops(target_bindings, native_counts, native_details)
            lua_ops.extend(bind_ops)

            # Execute batch in single eval call (< 5ms)
            success = self._eval_lua("; ".join(lua_ops))

            if success:
                self._write_active_overlay(new_overlay_records)
                self._write_state(target_mode, len(new_overlay_records))
                if record:
                    self.record_switch(target_mode)
                # Configuration persistence: mirror the successful switch when persistence is enabled.
                if self.get_persistence_status()["enabled"]:
                    self.set_persistence(True, profile=target_mode)
                try:
                    self._apply_window_policy()
                except Exception:
                    pass
            else:
                # The batched eval is not atomic at the compositor level: new combos bound
                # before the failure point would otherwise leak as untracked live bindings.
                unbind_new = [f'hl.unbind({lua_str(rec["combo"])})' for rec in new_overlay_records]
                if unbind_new:
                    self._eval_lua("; ".join(unbind_new))
                print("Warning: Failed to apply overlay in Hyprland, rolling back...", file=sys.stderr)
                self.restore()
                # Re-apply the mode the user had before, instead of dropping to baseline.
                if not _rollback and previous_mode != "omarchy" and previous_mode != target_mode and previous_mode in self.profiles:
                    if not self.switch_mode(previous_mode, record=False, _rollback=True):
                        print(f"Warning: Could not re-apply previous mode '{previous_mode}'.", file=sys.stderr)

            return success

    def verify_overlay_bindings(self) -> bool:
        """Verifies whether active profile overlay keybindings are currently registered in Hyprland.
        Returns True if all overlay bindings are present, or if active mode is 'omarchy' (native baseline).
        Returns False if any overlay binding is missing or if query fails.
        """
        curr_mode = self.get_state().get("mode", "omarchy")
        if curr_mode == "omarchy":
            return True
        overlay = self._get_active_overlay()
        if not overlay:
            return False
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(["hyprctl", "binds", "-j"], capture_output=True, text=True, check=True, timeout=1.5)
            live_binds = json.loads(res.stdout)
            live_descriptions = {b.get("description") for b in live_binds if b.get("description")}
            for item in overlay:
                item_name = item.get("name")
                if item_name and item_name not in live_descriptions:
                    return False
            return True
        except Exception:
            return False

    def cycle_mode(self, reverse: bool = False) -> str:
        """Cycles to the next mode in sequence: omarchy -> windows -> mac -> kde -> user profiles -> omarchy."""
        curated = ["omarchy", "windows", "mac", "kde"]
        user_modes = sorted([m for m in self.profiles if m not in curated])
        modes = [m for m in curated if m in self.profiles] + user_modes
        if not modes:
            modes = ["omarchy"]

        current = self.get_state().get("mode", "omarchy")
        step = -1 if reverse else 1
        try:
            idx = modes.index(current)
            next_mode = modes[(idx + step) % len(modes)]
        except ValueError:
            next_mode = "windows" if "windows" in self.profiles else modes[0]

        self.switch_mode(next_mode)
        return next_mode

    # ---------------- Per-app auto switching ----------------
    def load_app_rules(self) -> Dict[str, Any]:
        """Returns {"enabled": bool, "default_mode": str|None, "rules": [...]}; missing file means no rules."""
        data: Dict[str, Any] = {"enabled": True, "default_mode": None, "rules": []}
        path = app_rules_file_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    data["enabled"] = bool(raw.get("enabled", True))
                    dm = raw.get("default_mode")
                    data["default_mode"] = dm if dm in self.profiles else None
                    data["rules"] = [r for r in raw.get("rules", []) if isinstance(r, dict) and r.get("class") and r.get("mode")]
            except Exception as e:
                print(f"Warning: Failed to read app rules {path}: {e}", file=sys.stderr)
        return data

    def save_app_rules(self, data: Dict[str, Any]) -> None:
        for r in data.get("rules", []):
            if r.get("mode") not in self.profiles:
                raise ValueError(f"Unknown mode '{r.get('mode')}' in rule for '{r.get('class')}'")
            if r.get("match", "exact") not in ("exact", "prefix", "regex"):
                raise ValueError(f"Invalid match type '{r.get('match')}'")
            if r.get("match") == "regex":
                import re
                re.compile(r["class"])
        dm = data.get("default_mode")
        if dm is not None and dm not in self.profiles:
            raise ValueError(f"Unknown default mode '{dm}'")
        path = app_rules_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / (path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(path)

    def match_app_rule(self, window_class: str, rules: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """First enabled rule whose class matches wins. Matching is case-insensitive."""
        import re
        rules = rules if rules is not None else self.load_app_rules()
        if not rules.get("enabled", True) or not window_class:
            return None
        wc = window_class.strip().lower()
        for r in rules.get("rules", []):
            if not r.get("enabled", True):
                continue
            pat = str(r["class"]).strip()
            kind = r.get("match", "exact")
            try:
                if (kind == "exact" and wc == pat.lower()) or \
                   (kind == "prefix" and wc.startswith(pat.lower())) or \
                   (kind == "regex" and re.search(pat, window_class, re.IGNORECASE)):
                    return r
            except re.error as e:
                _debug(e)
        return None

    def apply_app_rule(self, window_class: str) -> Optional[str]:
        """Called on focus change. Switches to the rule's mode, or back to the base mode when
        no rule matches. Returns the mode switched to, or None if nothing changed."""
        rules = self.load_app_rules()
        rule = self.match_app_rule(window_class, rules)
        current = self.get_state().get("mode", "omarchy")
        if rule is None and getattr(self, "_auto_active", False) is False:
            self._write_app_rule_state(window_class, None)
            return None
        auto_target = getattr(self, "_auto_target", None)
        if getattr(self, "_auto_active", False) and auto_target and current != auto_target:
            # The user switched by hand while a rule was active: respect it as the new base.
            self._base_mode = current
            self._auto_active = False
            self._auto_target = None
            if rule is not None and rule["mode"] == auto_target:
                self._write_app_rule_state(window_class, rule)
                return None
        if rule is not None:
            if not getattr(self, "_auto_active", False):
                # Remember what the user picked by hand, so we can return to it.
                self._base_mode = current
            self._auto_active = True
            target = rule["mode"]
        else:
            self._auto_active = False
            target = rules.get("default_mode") or getattr(self, "_base_mode", None) or current
        self._write_app_rule_state(window_class, rule)
        self._auto_target = target if rule is not None else None
        if target == current or target not in self.profiles:
            return None
        if target == "omarchy":
            ok = self.restore()
        else:
            ok = self.switch_mode(target)
        return target if ok else None

    def _write_app_rule_state(self, window_class: str, rule: Optional[Dict[str, Any]]) -> None:
        """Broadcasts the currently matched rule for the settings UI and cheat sheet."""
        try:
            self._ensure_run_dir()
            tmp = APP_RULE_STATE_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"window_class": window_class, "rule": rule}, f, ensure_ascii=False)
            tmp.replace(APP_RULE_STATE_FILE)
        except Exception as e:
            _debug(e)

    def cheatsheet(self, mode: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns structured cheatsheet data from single source of truth."""
        mode = (mode or self.get_state().get("mode", "omarchy")).lower().strip()
        profile = self.profiles.get(mode)
        if not profile:
            return []

        sheet = []
        for b in profile.get("bindings", []):
            action_id = b.get("action")
            action_meta = self.actions_catalog.get(action_id, {})
            combo = format_combo(b.get("mod", ""), b.get("key", ""))
            sheet.append({
                "action": action_id,
                "key": combo,
                "name": action_meta.get("name", action_id),
                "category": action_meta.get("category", "other"),
                "description": action_meta.get("description", "")
            })
        return sheet

    def get_windows(self) -> List[Dict[str, Any]]:
        """Queries all clients/windows from Hyprland via `hyprctl clients -j` safely."""
        try:
            _ensure_hyprland_instance()
            cli_out = subprocess.check_output(["hyprctl", "clients", "-j"], text=True, timeout=0.5).strip()
            if not cli_out:
                return []
            clients = json.loads(cli_out)
            return clients if isinstance(clients, list) else []
        except Exception:
            return []

    def get_window_under_cursor(self) -> Optional[Dict[str, Any]]:
        """Finds the visible window on the active workspace under the cursor, or None."""
        try:
            _ensure_hyprland_instance()
            cur_out = subprocess.check_output(["hyprctl", "cursorpos"], text=True, timeout=0.5).strip()
            if not cur_out or "," not in cur_out:
                return None
            cx, cy = [float(p.strip()) for p in cur_out.split(",")]

            _ensure_hyprland_instance()
            mon_out = subprocess.check_output(["hyprctl", "monitors", "-j"], text=True, timeout=0.5)
            monitors = json.loads(mon_out)
            active_ws_ids = {m.get("activeWorkspace", {}).get("id") for m in monitors if "activeWorkspace" in m}

            clients = self.get_windows()

            candidates = []
            for c in clients:
                if not c.get("mapped", True) or c.get("hidden", False):
                    continue
                ws_id = c.get("workspace", {}).get("id")
                if ws_id not in active_ws_ids:
                    continue
                at = c.get("at", [0, 0])
                sz = c.get("size", [0, 0])
                x, y = at[0], at[1]
                w, h = sz[0], sz[1]
                if x <= cx <= x + w and y <= cy <= y + h:
                    candidates.append(c)

            if not candidates:
                return None
            candidates.sort(key=lambda item: item.get("focusHistoryID", 9999))
            return candidates[0]
        except Exception:
            return None

    def get_active_window(self) -> Optional[Dict[str, Any]]:
        """Queries the active window in Hyprland, returning its client dict or None."""
        try:
            _ensure_hyprland_instance()
            out = subprocess.check_output(["hyprctl", "activewindow", "-j"], text=True, timeout=0.5).strip()
            if not out:
                return None
            data = json.loads(out)
            return data if isinstance(data, dict) and data.get("address") else None
        except Exception:
            return None

    def snap(self, zone: str, target_address: Optional[str] = None, no_hud: bool = False) -> bool:
        """Triggers visual snap feedback and dispatches the corresponding window management action."""
        zone = zone.lower().strip()
        valid_special_zones = {"layouts", "picker", "menu", "restore", "unmax"}
        if zone not in valid_special_zones and zone not in self.snap_zones:
            print(f"Error: Unknown snap zone '{zone}'. Valid zones: {', '.join(sorted(self.snap_zones.keys()))}", file=sys.stderr)
            return False

        # Sanitize target_address with strict regex
        clean_target_address: Optional[str] = None
        if target_address:
            stripped = str(target_address).strip()
            if re.match(r"^0x[0-9a-fA-F]+$", stripped):
                clean_target_address = stripped

        self.record_snap(zone)
        self._ensure_run_dir()
        gap = self._get_hypr_gap()

        # 1. Check for interactive layout picker request (Win+Z Snap Layouts flyout)
        if zone in ("layouts", "picker", "menu"):
            target_addr = clean_target_address
            target_title = ""
            target_class = ""
            cursor_win = None

            if not target_addr:
                # 1. Prefer active window
                active = self.get_active_window()
                if active and active.get("address"):
                    target_addr = active["address"]
                    target_title = active.get("title", "")
                    target_class = active.get("class", "")
                else:
                    # 2. Fallback to window under cursor
                    cursor_win = self.get_window_under_cursor()
                    if cursor_win and cursor_win.get("address"):
                        target_addr = cursor_win["address"]
                        target_title = cursor_win.get("title", "")
                        target_class = cursor_win.get("class", "")
                        if target_addr and re.match(r"^0x[0-9a-fA-F]+$", str(target_addr)):
                            self._eval_lua(f'hl.dispatch(hl.dsp.focus({{ window = "address:{_escape_lua_string(str(target_addr))}" }}))')

            if target_addr and (not target_title or not target_class):
                for w in self.get_windows():
                    if w.get("address") == target_addr:
                        if not target_title:
                            target_title = w.get("title", "")
                        if not target_class:
                            target_class = w.get("class", "")
                        break

            snap_data = {
                "zone": "layouts",
                "interactive": True,
                "target_window": target_addr,
                "target_title": target_title,
                "target_class": target_class,
                "gap": gap,
                "timestamp": time.time()
            }
            atomic_write_json(SNAP_FILE, snap_data)

            if not no_hud and not compositor_mutation_disabled():
                try:
                    payload = {"interactive": True}
                    if target_addr:
                        payload["target_window"] = target_addr
                    if target_title:
                        payload["target_title"] = target_title
                    if target_class:
                        payload["target_class"] = target_class
                    self._last_summon_proc = subprocess.Popen(
                        ["omarchy-shell", "shell", "summon", "omni.snap-feedback", json.dumps(payload)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                except Exception as _e:
                    _debug(_e)
            return True

        # 2. Write snap.json for state/event observation
        snap_data = {
            "zone": zone,
            "interactive": False,
            "target_window": clean_target_address,
            "gap": gap,
            "timestamp": time.time()
        }
        atomic_write_json(SNAP_FILE, snap_data)

        # 3. Summon via omarchy-shell asynchronously if not suppressed
        if not no_hud and not compositor_mutation_disabled():
            try:
                summon_payload = {"zone": zone, "interactive": False}
                if clean_target_address:
                    summon_payload["target_window"] = clean_target_address
                self._last_summon_proc = subprocess.Popen(
                    ["omarchy-shell", "shell", "summon", "omni.snap-feedback", json.dumps(summon_payload)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            except Exception as _e:
                _debug(_e)

        find_w_lua = "local w = hl.get_active_window()\n"
        if clean_target_address:
            clean_addr = _escape_lua_string(clean_target_address)
            find_w_lua = f"""local target_addr = "{clean_addr}"
if target_addr ~= "" then
  hl.dispatch(hl.dsp.focus({{ window = "address:" .. target_addr }}))
end
local w = nil
if target_addr ~= "" then
  for _, win in ipairs(hl.get_windows()) do
    if win.address == target_addr then
      w = win
      break
    end
  end
end
if not w then
  w = hl.get_active_window()
end
"""

        # 4. Smart restore: unmaximize if fullscreen, unfloat to tiling if floating
        if zone in ("restore", "unmax"):
            lua_restore = f"""{find_w_lua}if w then
  local is_fs = (w.fullscreen == true or w.fullscreen == 1 or w.fullscreen == 2)
  if is_fs then
    hl.dispatch(hl.dsp.window.fullscreen({{ mode = 'maximized' }}))
  elseif w.floating then
    hl.dispatch(hl.dsp.window.float({{ action = 'toggle' }}))
  end
end"""
            return self._eval_lua(lua_restore)

        # 5. Apply geometric move & resize using dynamic schema zones (including 100% full screen with margin/gap reservations)
        if zone in self.snap_zones:
            z_meta = self.snap_zones[zone]
            xr = float(z_meta.get("xr", 0.0))
            yr = float(z_meta.get("yr", 0.0))
            wr = float(z_meta.get("wr", 0.5))
            hr = float(z_meta.get("hr", 1.0))

            lua_dsp = f"""{find_w_lua}if w then
  local m = hl.get_active_monitor()
  local is_fs = (w.fullscreen == true or w.fullscreen == 1 or w.fullscreen == 2)
  if is_fs then hl.dispatch(hl.dsp.window.fullscreen({{ mode = 'maximized' }})) end
  if not w.floating then hl.dispatch(hl.dsp.window.float({{ action = 'toggle' }})) end
  local gap = {gap}
  local rx = m.x + (m.reserved and m.reserved.left or 0) + gap
  local ry = m.y + (m.reserved and m.reserved.top or 0) + gap
  local rw = m.width - (m.reserved and (m.reserved.left + m.reserved.right) or 0) - gap * 2
  local rh = m.height - (m.reserved and (m.reserved.top + m.reserved.bottom) or 0) - gap * 2
  local is_left_edge = {1 if xr == 0.0 else 0}
  local is_right_edge = {1 if (xr + wr) >= 0.99 else 0}
  local is_top_edge = {1 if yr == 0.0 else 0}
  local is_bottom_edge = {1 if (yr + hr) >= 0.99 else 0}
  local tw = math.floor(rw * {round(wr, 3)}) - math.floor(gap * (1 - is_right_edge * is_left_edge) / 2)
  local th = math.floor(rh * {round(hr, 3)}) - math.floor(gap * (1 - is_top_edge * is_bottom_edge) / 2)
  local tx = rx + math.floor(rw * {round(xr, 3)}) + math.floor(gap * (1 - is_left_edge) / 2)
  local ty = ry + math.floor(rh * {round(yr, 3)}) + math.floor(gap * (1 - is_top_edge) / 2)
  hl.dispatch(hl.dsp.window.resize({{ x = math.floor(tw), y = math.floor(th) }}))
  hl.dispatch(hl.dsp.window.move({{ x = math.floor(tx), y = math.floor(ty) }}))
end"""
            return self._eval_lua(lua_dsp)
        return True

    def benchmark(self) -> Dict[str, Any]:
        """Measures millisecond latency for schema loading, profile switching, and restore.

        Non-destructive: the session's active mode is restored at the end (unmeasured)
        and the benchmark switches never count toward local usage statistics."""
        results: Dict[str, Any] = {}
        initial_state = self.get_state()
        prev_mode = initial_state.get("mode", "omarchy")
        prev_policy = initial_state.get("window_policy", self.get_window_policy())
        results["initial_mode"] = prev_mode

        try:
            # 1. Schema & profile parse time
            t0 = time.perf_counter()
            self._load_catalog()
            results["parse_ms"] = round((time.perf_counter() - t0) * 1000, 3)

            # 2. Windows profile switch latency
            t0 = time.perf_counter()
            self.switch_mode("windows", record=False)
            results["switch_windows_ms"] = round((time.perf_counter() - t0) * 1000, 3)

            # 3. macOS profile switch latency
            t0 = time.perf_counter()
            self.switch_mode("mac", record=False)
            results["switch_mac_ms"] = round((time.perf_counter() - t0) * 1000, 3)

            # 4. Restore latency
            t0 = time.perf_counter()
            results["restore_ok"] = self.restore()
            results["restore_ms"] = round((time.perf_counter() - t0) * 1000, 3)

            # 5. State write latency
            t0 = time.perf_counter()
            self._write_state("omarchy", 0)
            results["state_write_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        finally:
            # Restore both pieces of session state, even when a benchmark step fails.
            results["mode_restored"] = False
            if prev_mode != "omarchy" and prev_mode in self.profiles:
                results["mode_restored"] = self.switch_mode(prev_mode, record=False)
            elif prev_mode == "omarchy":
                self._write_state("omarchy", 0, policy=prev_policy)

            current_policy = self.get_window_policy()
            results["policy_restored"] = True
            if prev_mode == "omarchy" and prev_policy == "floating":
                results["policy_restored"] = self.set_window_policy(prev_policy)
            elif prev_policy != current_policy:
                results["policy_restored"] = self.set_window_policy(prev_policy)

        return results

    def check_installation(self, home: Optional[Path] = None) -> Dict[str, Any]:
        """Checks what install.sh set up and returns each problem with a concrete fix."""
        home = Path(home) if home else Path.home()
        root = self.root_dir.resolve()
        reinstall = f"bash {root}/scripts/install.sh"
        problems: List[Dict[str, str]] = []
        info: Dict[str, Any] = {"cli": "missing", "plugins": {}, "service": "missing", "tokens_in_sync": True}

        # CLI link
        cli = home / ".local" / "bin" / "omni-profile"
        if cli.is_symlink() or cli.exists():
            if not cli.exists():
                info["cli"] = "broken"
                problems.append({"problem": f"CLI link {cli} is broken (points to a moved or deleted checkout)", "fix": reinstall})
            elif cli.resolve() != (root / "bin" / "omni-profile"):
                info["cli"] = "other"
                problems.append({"problem": f"CLI link {cli} points to another checkout: {cli.resolve()}", "fix": reinstall})
            else:
                info["cli"] = "ok"
        else:
            problems.append({"problem": f"CLI link {cli} is missing", "fix": reinstall})

        # Plugin links
        plugins_dir = home / ".config" / "omarchy" / "plugins"
        for src in sorted((root / "plugins").glob("omni.*")):
            if not src.is_dir():
                continue
            link = plugins_dir / src.name
            if not (link.is_symlink() or link.exists()):
                state = "missing"
            elif not link.exists():
                state = "broken"
            elif link.resolve() != src:
                state = "other"
            else:
                state = "ok"
            info["plugins"][src.name] = state
            if state != "ok":
                problems.append({"problem": f"Plugin {src.name} link is {state} in {plugins_dir}", "fix": reinstall})

        # systemd user unit
        unit = home / ".config" / "systemd" / "user" / "omnipal.service"
        if unit.exists():
            text = unit.read_text(encoding="utf-8", errors="replace")
            if str(root / "bin" / "omni-profile") not in text:
                info["service"] = "stale"
                problems.append({"problem": f"{unit} points to a different checkout path", "fix": reinstall})
            else:
                info["service"] = "installed"
                try:
                    res = subprocess.run(["systemctl", "--user", "is-active", "omnipal.service"],
                                         capture_output=True, text=True, timeout=3)
                    status = res.stdout.strip()
                    if status in ("active", "inactive", "failed", "activating", "deactivating"):
                        info["service"] = status
                    if status == "failed":
                        problems.append({"problem": "omnipal.service is in failed state",
                                         "fix": "journalctl --user -u omnipal.service -n 50; systemctl --user restart omnipal.service"})
                except Exception as e:
                    _debug(f"systemctl query failed: {e}")
        # A missing unit is fine: the daemon is optional.

        # Tokens.js copies
        try:
            from scripts.sync_tokens import out_of_sync
            bad = out_of_sync(root)
        except Exception as e:
            _debug(f"token sync check failed: {e}")
            bad = []
        if bad:
            info["tokens_in_sync"] = False
            problems.append({"problem": f"Tokens.js out of sync in {len(bad)} plugin(s)",
                             "fix": f"python3 {root}/scripts/sync_tokens.py"})

        info["problems"] = problems
        return info

    def doctor(self) -> Dict[str, Any]:
        """Runs comprehensive diagnostics on daemon, sockets, live binds, and state consistency."""
        report: Dict[str, Any] = {
            "healthy": True,
            "version": __version__,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "daemon": {"running": False, "pid": None},
            "socket2": {"connected": False, "path": None},
            "state": self.get_state(),
            "overlay": {"count": 0, "verified_in_hyprland": 0, "missing": []},
            "consistency": False,
            "issues": [],
            "fixes": []
        }

        # 1. Check daemon PID
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                os.kill(pid, 0)
                report["daemon"] = {"running": True, "pid": pid}
            except (ProcessLookupError, ValueError):
                report["issues"].append("Daemon PID file exists but process is not running (stale pidfile)")
            except PermissionError:
                report["daemon"] = {"running": True, "pid": pid}

        # 2. Check Socket2
        sock_path = find_socket2_path()
        if sock_path and sock_path.exists():
            report["socket2"]["path"] = str(sock_path)
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect(str(sock_path))
                s.close()
                report["socket2"]["connected"] = True
            except Exception as e:
                report["issues"].append(f"Socket2 exists at {sock_path} but cannot connect: {e}")
        else:
            report["issues"].append("Hyprland socket2 could not be located")

        # 3. Verify Live Hyprland Binds
        overlay = self._get_active_overlay()
        report["overlay"]["count"] = len(overlay)
        if overlay:
            try:
                _ensure_hyprland_instance()
                res = subprocess.run(["hyprctl", "binds", "-j"], capture_output=True, text=True, check=True)
                live_binds = json.loads(res.stdout)
                live_descriptions = {b.get("description") for b in live_binds if b.get("description")}

                verified = 0
                for item in overlay:
                    if item.get("name") in live_descriptions:
                        verified += 1
                    else:
                        report["overlay"]["missing"].append(item.get("combo"))
                report["overlay"]["verified_in_hyprland"] = verified

                if report["overlay"]["missing"]:
                    report["issues"].append(f"Mismatch: {len(report['overlay']['missing'])} binds declared in overlay are absent from compositor")
            except Exception as e:
                report["issues"].append(f"Failed to query hyprctl binds: {e}")

        # 3.5 Overlay combos that still share their key with a native bind fire twice
        report["conflicts"] = []
        if overlay:
            counts = self._live_bind_counts()
            for item in overlay:
                combo = item.get("combo")
                if combo and counts.get(combo_signature(combo), 0) > 1:
                    report["conflicts"].append(combo)
            if report["conflicts"]:
                report["issues"].append(
                    f"Conflict: {len(report['conflicts'])} overlay combos also have a native bind (fire twice): "
                    + ", ".join(report["conflicts"]))
                report["fixes"].append("omni-profile switch <当前模式>（会自动解绑冲突的原生快捷键）")

        # 4. Installation self-check (CLI link, plugin links, systemd unit, token copies)
        install = self.check_installation()
        report["install"] = install
        for item in install["problems"]:
            report["issues"].append(item["problem"])
        report["fixes"] += [item["fix"] for item in install["problems"]]

        # 4.5 Omarchy version gate (shared with scripts/install.sh)
        try:
            from engine.omarchy_version import check_omarchy_version
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from omarchy_version import check_omarchy_version  # type: ignore
        ov = check_omarchy_version(self.root_dir)
        report["omarchy"] = ov
        if ov["status"] == "too_old":
            report["issues"].append(f"Omarchy {ov['detected']} is older than required {ov['minimum']}; plugins will fail to load")
            report["fixes"].append("Run omarchy-update to upgrade Omarchy")

        # 4. Consistency check
        # Run quietly so `omni-profile doctor --json` stays pure JSON on stdout.
        try:
            from scripts.check_consistency import check_consistency as _check_consistency
        except ImportError:
            _check_consistency = None

        if _check_consistency is not None:
            with contextlib.redirect_stdout(io.StringIO()):
                report["consistency"] = _check_consistency(self.root_dir, user_profiles_dir=self.user_profiles_dir)
        else:
            # Module not importable (e.g. daemon started from another CWD outside the repo root):
            # fall back to running the consistency script directly, quietly.
            script = self.root_dir / "scripts" / "check_consistency.py"
            try:
                res = subprocess.run([sys.executable, str(script)], capture_output=True, timeout=120)
                report["consistency"] = res.returncode == 0
            except Exception as run_err:
                report["issues"].append(f"Failed to run consistency check: {run_err}")
                report["consistency"] = False
        if not report["consistency"]:
            report["issues"].append("Schema or profile consistency validation failed")

        if report["issues"]:
            report["healthy"] = False

        return report

def wait_for_hyprland(timeout: float = 30.0, interval: float = 0.5, stop_event: Optional[threading.Event] = None) -> bool:
    """Bounded wait for a Hyprland instance socket to appear under $XDG_RUNTIME_DIR/hypr/."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if hyprland_socket_ready():
            return True
        if time.monotonic() >= deadline or (stop_event is not None and stop_event.is_set()):
            return False
        time.sleep(interval)

def resolve_reapply_mode(engine: "OmniPalEngine") -> str:
    """Mode the daemon should (re-)apply: the live state written by a successful switch in this
    session, else the persisted profile. A missing state file (fresh tmpfs after reboot, or a
    failed startup restore) must not hide the persisted profile."""
    if STATE_FILE.exists():
        mode = engine.get_state().get("mode", "omarchy")
        if mode in engine.profiles:
            return mode
    persisted = engine.get_persisted_profile()
    if persisted and persisted in engine.profiles:
        return persisted
    return "omarchy"

def restore_persisted_profile(engine: "OmniPalEngine", attempts: int = 4, base_delay: float = 1.0,
                              wait_timeout: float = 30.0, sleep=time.sleep) -> bool:
    """Waits for Hyprland, then applies the persisted profile with retry + exponential backoff."""
    mode = engine.get_persisted_profile()
    if not mode or mode == "omarchy":
        return True
    if not wait_for_hyprland(timeout=wait_timeout):
        print(f"⚠️ Hyprland socket not found after {wait_timeout:.0f}s; will restore '{mode}' when the socket appears.", file=sys.stderr, flush=True)
        return False
    print(f"🔌 Hyprland ready (HYPRLAND_INSTANCE_SIGNATURE={os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')}).", flush=True)
    delay = base_delay
    for attempt in range(1, attempts + 1):
        print(f"📦 Restoring persisted profile on startup: {mode} (attempt {attempt}/{attempts})", flush=True)
        try:
            if engine.switch_mode(mode):
                print(f"✅ Restored persisted profile '{mode}'.", flush=True)
                return True
        except Exception as e:
            print(f"Warning: Failed to restore persisted profile '{mode}': {e}", file=sys.stderr, flush=True)
        if attempt < attempts:
            print(f"Warning: restore of '{mode}' failed; retrying in {delay:.1f}s", file=sys.stderr, flush=True)
            sleep(delay)
            delay *= 2
    print(f"❌ Giving up restoring persisted profile '{mode}' after {attempts} attempts.", file=sys.stderr, flush=True)
    return False

def _watch_hyprland_socket2(engine: OmniPalEngine, stop_event: threading.Event):
    """Watches Hyprland socket2 for config reload events to automatically re-apply active profile."""
    while not stop_event.is_set():
        socket_path = find_socket2_path()
        if not socket_path or not socket_path.exists():
            os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
            time.sleep(2)
            continue
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(str(socket_path))
            s.settimeout(2.0)
            buffer = ""
            last_class = None
            cascade_counter = 0
            last_reload_time = 0.0

            # Settle & verify keybindings upon socket connection (cold boot or compositor recovery)
            curr_mode = resolve_reapply_mode(engine)
            if curr_mode != "omarchy":
                if engine.get_state().get("mode") != curr_mode or not engine.verify_overlay_bindings():
                    print(f"🔄 Socket connected: verified overlay bindings missing for '{curr_mode}'. Re-applying...", flush=True)
                    engine.switch_mode(curr_mode)
                    eff_mode = engine.get_effective_window_mode()
                    if eff_mode == "floating":
                        engine._set_applied_window_mode("tiled")
                        engine._apply_window_policy(force=True)
                    else:
                        engine._apply_window_policy(force=True)

            while not stop_event.is_set():
                try:
                    data = s.recv(4096)
                    if not data:
                        break
                    buffer += data.decode("utf-8", errors="ignore")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line.startswith("activewindow>>"):
                            win_class = line[len("activewindow>>"):].split(",", 1)[0]
                            if win_class and win_class != last_class:
                                last_class = win_class
                                switched = engine.apply_app_rule(win_class)
                                if switched:
                                    print(f"🎯 {win_class} -> {switched}", flush=True)
                        elif line == "configreloaded>>":
                            now = time.monotonic()
                            if now - last_reload_time < 1.0:
                                continue
                            last_reload_time = now
                            time.sleep(0.1)  # Debounce settle time
                            curr_mode = resolve_reapply_mode(engine)
                            if curr_mode != "omarchy":
                                print(f"🔄 Hyprland config reload detected. Re-applying {curr_mode} overlay...", flush=True)
                                engine.switch_mode(curr_mode)
                            else:
                                engine._snapshot_baseline_bindings(force=True)
                            eff_mode = engine.get_effective_window_mode()
                            if eff_mode == "floating":
                                print("🔄 Hyprland config reload detected. Re-applying floating window rule...", flush=True)
                                engine._set_applied_window_mode("tiled")
                                engine._apply_window_policy(force=True)
                        elif line.startswith("openwindow>>"):
                            eff_mode = engine.get_effective_window_mode()
                            if eff_mode == "floating":
                                payload = line[len("openwindow>>"):].strip()
                                parts = payload.split(",", 3)
                                if parts:
                                    raw_addr = parts[0].strip()
                                    ws_name = parts[1].strip() if len(parts) > 1 else ""
                                    cls_name = parts[2].strip() if len(parts) > 2 else ""
                                    win_title = parts[3].strip() if len(parts) > 3 else ""
                                    if raw_addr:
                                        addr = f"0x{raw_addr}" if not raw_addr.startswith("0x") else raw_addr
                                        skip, is_dlg = is_special_window(
                                            cls_name=cls_name,
                                            title=win_title,
                                            ws_name=ws_name
                                        )
                                        if skip:
                                            continue
                                        engine._apply_golden_cascade_geometry(addr, step=cascade_counter, is_dialog=is_dlg)
                                        if not is_dlg:
                                            cascade_counter = (cascade_counter + 1) % 6
                except socket.timeout:
                    continue
                except Exception:
                    break
            s.close()
        except Exception:
            os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
            time.sleep(2)

def run_daemon():
    """Runs OmniPal Engine as a foreground daemon with socket2 listener and signal traps."""
    try:
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    except (ValueError, AttributeError, OSError):
        pass

    _resolve_run_dir()
    engine = OmniPalEngine()
    engine._ensure_run_dir()

    # Enforce single instance daemon lock
    if PID_FILE.exists():
        try:
            existing_pid = int(PID_FILE.read_text().strip())
            os.kill(existing_pid, 0)
            print(f"⚠️ OmniPal Engine daemon is already running (PID: {existing_pid}). Exiting cleanly.", flush=True)
            return
        except (ValueError, ProcessLookupError):
            pass
        except PermissionError:
            print("⚠️ OmniPal Engine daemon is already running. Exiting cleanly.", flush=True)
            return

    # Record PID
    try:
        PID_FILE.write_text(str(os.getpid()))
    except Exception as _e:
        _debug(_e)

    print(f"🚀 OmniPal Engine daemon started (PID: {os.getpid()}). Watching for signals & Hyprland events...", flush=True)

    # Check and restore persisted window policy and profile on startup
    persisted_status = engine.get_persistence_status()
    persisted_policy = engine.get_persisted_window_policy()
    persisted_mode = engine.get_persisted_profile()

    if persisted_policy:
        print(f"📦 Restoring persisted window policy on startup: {persisted_policy}", flush=True)
        engine.set_window_policy(persisted_policy)
    elif persisted_status.get("enabled"):
        engine.set_persistence(True, window_policy=engine.get_window_policy())

    if persisted_mode and persisted_mode != "omarchy":
        restore_persisted_profile(engine)
    elif persisted_mode == "omarchy":
        engine._write_state("omarchy", 0, policy=engine.get_window_policy())
    elif persisted_status.get("enabled"):
        cur_mode = engine.get_state().get("mode") or "windows"
        engine.set_persistence(True, profile=cur_mode)

    # Enforce active window policy on startup
    if engine.get_effective_window_mode() == "floating":
        try:
            engine._apply_window_policy(force=True)
        except Exception:
            pass

    stop_event = threading.Event()
    worker = threading.Thread(target=_watch_hyprland_socket2, args=(engine, stop_event), daemon=True)
    worker.start()

    restored = False
    def cleanup():
        nonlocal restored
        if not restored:
            restored = True
            stop_event.set()
            try:
                if PID_FILE.exists():
                    PID_FILE.unlink()
            except Exception:
                pass
            curr = engine.get_state().get("mode", "omarchy")
            cur_app = engine._get_applied_window_mode()
            if curr != "omarchy" or cur_app == "floating" or engine._get_active_overlay():
                engine.restore()

    def sig_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}. Restoring Hyprland keybindings...", flush=True)
        cleanup()
        print("✅ Restored successfully. Exiting cleanly.", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGHUP, sig_handler)
    atexit.register(cleanup)

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        sig_handler(signal.SIGINT, None)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        run_daemon()
    else:
        eng = OmniPalEngine()
        print(json.dumps(eng.get_state(), indent=2, ensure_ascii=False))
