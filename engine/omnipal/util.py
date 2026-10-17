"""Small shared helpers: Lua escaping, JSON atomic writes, locks, debug."""

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

from engine.omnipal.paths import (LOCK_FILE, _resolve_run_dir)

def compositor_mutation_disabled() -> bool:
    """Returns True when tests or maintenance tools request a non-mutating dry run."""
    return os.environ.get("OMNIPAL_DRY_RUN", "").strip().lower() in ("1", "true", "yes")

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
    except (OSError, TimeoutError):
        # TimeoutError is raised above when the lock cannot be acquired in
        # time; the fd must still be closed before propagating.
        if f:
            try:
                f.close()
            except OSError:
                pass  # best-effort cleanup
        raise

    _lock_local.depth = 1
    try:
        yield
    finally:
        _lock_local.depth = 0
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass  # best-effort unlock; nothing sensible to do on failure
        if f:
            try:
                f.close()
            except OSError:
                pass  # best-effort cleanup

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
    except (OSError, ValueError, TypeError) as e:
        print(f"Warning: Failed to atomic write {path}: {e}", file=sys.stderr)
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass  # best-effort cleanup of the temp file
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
    except (OSError, ValueError, TypeError) as e:
        print(f"Warning: Failed to write state {path}: {e}", file=sys.stderr)
        return False


def _debug(msg) -> None:
    """Prints swallowed errors to stderr when OMNIPAL_DEBUG=1."""
    if os.environ.get("OMNIPAL_DEBUG") == "1":
        import traceback
        caller = traceback.extract_stack(limit=2)[0]
        print(f"[omnipal debug] {caller.name}:{caller.lineno}: {msg!r}", file=sys.stderr)


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


# Sentinel: keep the current auto-switch marker only if it still describes the target mode.
_KEEP = object()


def notify_user(title: str, body: str = "") -> None:
    """Short desktop notice via notify-send (mako on Omarchy). Silent no-op when unavailable."""
    if compositor_mutation_disabled() or not shutil.which("notify-send"):
        return
    try:
        subprocess.Popen(["notify-send", "-a", "OmniPal", "-t", "5000", title] + ([body] if body else []),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        # notify-send missing or failed to spawn; desktop notice is best-effort.
        _debug(e)


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

_FLAG_OPTS = (("locked", "locked"), ("repeat", "repeating"), ("non_consuming", "non_consuming"))


def bind_key_name(b: Dict[str, Any]) -> str:
    """Key of a `hyprctl binds -j` entry as a combo key: the keysym, else `code:N`, else ""
    (Omarchy's code:NN binds can show key "" with keycode 0: such binds can't be identified)."""
    key = str(b.get("key", "") or "")
    if key:
        return key
    try:
        code = int(b.get("keycode", 0) or 0)
    except (TypeError, ValueError):
        code = 0
    return f"code:{code}" if code > 0 else ""


def bind_signature(b: Dict[str, Any]) -> Optional[Tuple[int, str]]:
    """(modmask, KEY) comparable with combo_signature(); None for binds we can't identify."""
    key = bind_key_name(b)
    if not key:
        return None
    return (int(b.get("modmask", 0) or 0), key.upper())


_MODMASK_NAMES = ((64, "SUPER"), (4, "CTRL"), (8, "ALT"), (1, "SHIFT"))


def _sig_combo(sig: Tuple[int, str]) -> str:
    mask, key = sig
    mods = [n for bit, n in _MODMASK_NAMES if mask & bit]
    return " + ".join(mods + [key])


def find_duplicate_binds(binds: List[Dict[str, Any]]) -> Dict[Tuple[int, str], int]:
    """(modmask, KEY) -> extra copies of an identical bind (same handler description/dispatcher/flags).

    Distinct binds sharing a key (e.g. Omarchy's two ALT + TAB entries) are not duplicates."""
    groups: Dict[Tuple[Any, ...], int] = {}
    for b in binds:
        if not isinstance(b, dict) or b.get("mouse") or b.get("release") or b.get("submap"):
            continue
        sig = bind_signature(b)
        if sig is None:  # key "" and keycode 0: never assume two of these are the same combo
            continue
        k = (sig, b.get("description") or "", b.get("dispatcher") or "",
             "" if b.get("dispatcher") == "__lua" else str(b.get("arg", "")),
             tuple(bool(b.get(f)) for f, _ in _FLAG_OPTS))
        groups[k] = groups.get(k, 0) + 1
    out: Dict[Tuple[int, str], int] = {}
    for k, n in groups.items():
        if n > 1:
            out[k[0]] = out.get(k[0], 0) + n - 1
    return out
