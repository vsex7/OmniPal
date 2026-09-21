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
from typing import Any, Dict, List, Optional, Tuple, Union

VERSION = "1.8.0"

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
    global RUN_DIR, STATE_FILE, OVERLAY_FILE, SNAP_FILE, SNAP_LAYOUTS_FILE, PID_FILE, LOCK_FILE, APPLIED_WINDOW_MODE_FILE, BASELINE_FILE
    RUN_DIR = d
    STATE_FILE = d / "state.json"
    OVERLAY_FILE = d / "active_overlay.json"
    SNAP_FILE = d / "snap.json"
    SNAP_LAYOUTS_FILE = d / "snap_layouts.json"
    PID_FILE = d / "daemon.pid"
    LOCK_FILE = d / "engine.lock"
    APPLIED_WINDOW_MODE_FILE = d / "applied_window_mode"
    BASELINE_FILE = d / "baseline_bindings.json"
    return d

RUN_DIR = _resolve_run_dir()
STATE_FILE = RUN_DIR / "state.json"
OVERLAY_FILE = RUN_DIR / "active_overlay.json"
SNAP_FILE = RUN_DIR / "snap.json"
SNAP_LAYOUTS_FILE = RUN_DIR / "snap_layouts.json"
PID_FILE = RUN_DIR / "daemon.pid"
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
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

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

def _ensure_hyprland_instance():
    """Ensures HYPRLAND_INSTANCE_SIGNATURE is populated in os.environ for hyprctl."""
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        find_socket2_path()

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
        if "unittest" not in sys.modules:
            try:
                signal.signal(signal.SIGCHLD, signal.SIG_IGN)
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
        _ensure_hyprland_instance()
        try:
            res = subprocess.run(
                ["hyprctl", "eval", lua_code],
                capture_output=True,
                text=True,
                check=False,
                env=os.environ
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

    def _reinject_active_bindings(self, target_mode: str) -> bool:
        """Re-applies the active overlay bindings into Hyprland (e.g. after a config reload)."""
        if target_mode not in self.profiles or target_mode == "omarchy":
            return True
        target_profile = self.profiles[target_mode]
        target_bindings = target_profile.get("bindings", [])
        lua_ops = []
        new_overlay_records = []
        for b in target_bindings:
            action_id = b.get("action")
            action_meta = self.actions_catalog.get(action_id, {})
            name = action_meta.get("name", action_id)
            mod = b.get("mod", "").strip()
            key = b.get("key", "").strip()
            if not key:
                continue

            combo = format_combo(mod, key)
            esc_name = _escape_lua_string(name)
            if action_id in LUA_DISPATCHERS:
                dispatcher_expr = LUA_DISPATCHERS[action_id]
                lua_ops.append(f'o.bind("{combo}", "{esc_name}", {dispatcher_expr})')
            else:
                cmd = b.get("arg") or action_meta.get("default_arg", "")
                esc_cmd = _escape_lua_string(cmd)
                lua_ops.append(f'o.bind("{combo}", "{esc_name}", "{esc_cmd}")')

            new_overlay_records.append({
                "action": action_id,
                "combo": combo,
                "name": name
            })

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
            try:
                subprocess.run(
                    ["hyprctl", "reload", "config-only"],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=os.environ
                )
            except Exception:
                pass
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
            except Exception:
                pass
        return normalize_window_policy(getattr(self, "window_policy", None)) or "tiled"

    def set_window_policy(self, policy: str) -> bool:
        with engine_lock():
            norm = normalize_window_policy(policy)
            if not norm:
                return False
            self.window_policy = norm
            cur_state = self.get_state()
            cur_mode = cur_state.get("mode", "omarchy")
            count = cur_state.get("active_bindings_count", 0)
            self._write_state(cur_mode, count, policy=norm)
            if self.get_persistence_status()["enabled"]:
                self.set_persistence(True, window_policy=norm)
            try:
                self._apply_window_policy(force=True)
            except Exception:
                pass
            return True

    def get_state(self) -> Dict[str, Any]:
        cur_policy = self.get_window_policy()
        sock = find_socket2_path()
        compositor_connected = sock is not None and sock.exists()
        default_state = {
            "version": VERSION,
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
            except Exception:
                pass

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
                except Exception:
                    pass
            if not cur_policy:
                cur_policy = normalize_window_policy(getattr(self, "window_policy", None)) or "tiled"

        cur_policy = cur_policy or "tiled"
        self.window_policy = cur_policy
        effective_mode = self.get_effective_window_mode(mode, cur_policy)
        sock = find_socket2_path()
        compositor_connected = sock is not None and sock.exists()

        state_data = {
            "version": VERSION,
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

    def _build_dynamic_restore_lua(self) -> Optional[str]:
        """Builds Lua statements to restore the exact captured baseline bindings."""
        if not self.baseline_bindings:
            return None

        lua_ops = []
        lua_ops.append('local reg = debug.getregistry()')

        for combo, b in self.baseline_bindings.items():
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
                    lua_lines.append(f'hl.unbind("{combo}")')

            # Dynamic restore if snapshot exists, fallback to LUA_RESTORE_BASELINE
            if not self.baseline_bindings:
                self._load_baseline_cache()

            dynamic_lua = self._build_dynamic_restore_lua()
            if dynamic_lua:
                lua_lines.append(dynamic_lua)
            else:
                lua_lines.append(LUA_RESTORE_BASELINE)

            success = self._eval_lua("; ".join(lua_lines))

            try:
                if OVERLAY_FILE.exists():
                    OVERLAY_FILE.unlink()
            except Exception:
                pass

            if self._get_applied_window_mode() == "floating":
                try:
                    subprocess.run(
                        ["hyprctl", "reload", "config-only"],
                        capture_output=True,
                        text=True,
                        check=False,
                        env=os.environ
                    )
                except Exception:
                    pass
                self._set_applied_window_mode("tiled")

            self._write_state("omarchy", 0)
            return success

    def switch_mode(self, target_mode: str, record: bool = True) -> bool:
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

            target_profile = self.profiles[target_mode]
            target_bindings = target_profile.get("bindings", [])

            # Ensure baseline snapshot is captured before any new overlay is applied
            if not self.baseline_bindings:
                self._snapshot_baseline_bindings()

            # Stage 1: Unbind previous overlay
            current_overlay = self._get_active_overlay()
            lua_ops = []
            if current_overlay:
                for b in current_overlay:
                    combo = b.get("combo")
                    if combo:
                        lua_ops.append(f'hl.unbind("{combo}")')

                # Stage 2: Restore baseline bindings so non-overlapping native bindings
                # (e.g. Omarchy menu Super+Space or default binds unmapped by previous profile) are restored
                dynamic_lua = self._build_dynamic_restore_lua()
                if dynamic_lua:
                    lua_ops.append(dynamic_lua)
                else:
                    lua_ops.append(LUA_RESTORE_BASELINE)


            # Stage 3: Add bind commands for new profile
            new_overlay_records = []
            for b in target_bindings:
                action_id = b.get("action")
                action_meta = self.actions_catalog.get(action_id, {})
                name = action_meta.get("name", action_id)
                mod = b.get("mod", "").strip()
                key = b.get("key", "").strip()
                if not key:
                    continue

                combo = format_combo(mod, key)
                esc_name = _escape_lua_string(name)
                if action_id in LUA_DISPATCHERS:
                    dispatcher_expr = LUA_DISPATCHERS[action_id]
                    lua_ops.append(f'o.bind("{combo}", "{esc_name}", {dispatcher_expr})')
                else:
                    cmd = b.get("arg") or action_meta.get("default_arg", "")
                    esc_cmd = _escape_lua_string(cmd)
                    lua_ops.append(f'o.bind("{combo}", "{esc_name}", "{esc_cmd}")')

                new_overlay_records.append({
                    "action": action_id,
                    "combo": combo,
                    "name": name
                })

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
                unbind_new = [f'hl.unbind("{rec["combo"]}")' for rec in new_overlay_records]
                if unbind_new:
                    self._eval_lua("; ".join(unbind_new))
                print("Warning: Failed to apply overlay in Hyprland, rolling back to baseline...", file=sys.stderr)
                self.restore()

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
        """Cycles to the next mode in sequence: omarchy -> windows -> mac -> user profiles -> omarchy."""
        curated = ["omarchy", "windows", "mac"]
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
                "key": combo,
                "name": action_meta.get("name", action_id),
                "category": action_meta.get("category", "other"),
                "description": action_meta.get("description", "")
            })
        return sheet

    def get_windows(self) -> List[Dict[str, Any]]:
        """Queries all clients/windows from Hyprland via `hyprctl clients -j` safely."""
        try:
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
            cur_out = subprocess.check_output(["hyprctl", "cursorpos"], text=True, timeout=0.5).strip()
            if not cur_out or "," not in cur_out:
                return None
            cx, cy = [float(p.strip()) for p in cur_out.split(",")]

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

            if not no_hud:
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
                except Exception:
                    pass
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
        if not no_hud:
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
            except Exception:
                pass

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
        """Measures microsecond latency for schema loading, profile switching, and restore.

        Non-destructive: the session's active mode is restored at the end (unmeasured)
        and the benchmark switches never count toward local usage statistics."""
        results = {}
        prev_mode = self.get_state().get("mode", "omarchy")

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
        self.restore()
        results["restore_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        # 5. State write latency
        t0 = time.perf_counter()
        self._write_state("omarchy", 0)
        results["state_write_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        # 6. Restore the user's active mode without affecting the measured numbers.
        results["mode_restored"] = False
        if prev_mode != "omarchy" and prev_mode in self.profiles:
            self.switch_mode(prev_mode, record=False)
            results["mode_restored"] = True
        return results

    def doctor(self) -> Dict[str, Any]:
        """Runs comprehensive diagnostics on daemon, sockets, live binds, and state consistency."""
        report: Dict[str, Any] = {
            "healthy": True,
            "version": VERSION,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "daemon": {"running": False, "pid": None},
            "socket2": {"connected": False, "path": None},
            "state": self.get_state(),
            "overlay": {"count": 0, "verified_in_hyprland": 0, "missing": []},
            "consistency": False,
            "issues": []
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
            cascade_counter = 0

            # Settle & verify keybindings upon socket connection (cold boot or compositor recovery)
            curr_mode = engine.get_state().get("mode", "omarchy")
            if curr_mode != "omarchy":
                if not engine.verify_overlay_bindings():
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
                        if line == "configreloaded>>":
                            time.sleep(0.1)  # Debounce settle time
                            curr_mode = engine.get_state().get("mode", "omarchy")
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
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)
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
    except Exception:
        pass

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
        # Settle briefly so compositor finishes its startup Lua scripts before we apply overlay
        time.sleep(0.5)
        print(f"📦 Restoring persisted profile on startup: {persisted_mode}", flush=True)
        try:
            engine.switch_mode(persisted_mode)
        except Exception as e:
            print(f"Warning: Failed to restore persisted profile '{persisted_mode}': {e}", file=sys.stderr)
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
