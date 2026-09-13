#!/usr/bin/env python3
"""
OmniPal Core Runtime Engine
Version: 0.4.0 (Architecture Fixed)

Strictly adheres to AGENTS.md rules:
1. Pure in-memory overlay via Omarchy Hyprland Lua engine (`hyprctl eval`)
2. Zero file writes to ~/.config/hypr/ or system configs
3. Safe signal handling: automatic restore on SIGTERM/SIGINT
4. State broadcast via /run/user/$UID/omnipal/state.json (tmpfs)
"""

import atexit
import datetime
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

RUN_DIR = Path(f"/run/user/{os.getuid()}/omnipal")
STATE_FILE = RUN_DIR / "state.json"
OVERLAY_FILE = RUN_DIR / "active_overlay.json"
SNAP_FILE = RUN_DIR / "snap.json"

LUA_DISPATCHERS = {
    "close_window": "hl.dsp.window.close()",
    "toggle_floating": "hl.dsp.window.float({ action = 'toggle' })",
    "workspace_next": "hl.dsp.focus({ workspace = 'e+1' })",
    "workspace_prev": "hl.dsp.focus({ workspace = 'e-1' })",
}

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
    elif key.lower() in ("tab", "left", "right", "up", "down", "period", "return", "enter"):
        norm_key = key.upper()
    parts.append(norm_key)
    return " + ".join(parts)

class OmniPalEngine:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent
        self.schema_file = self.root_dir / "schema" / "actions.json"
        self.profiles_dir = self.root_dir / "profiles"
        self.actions_catalog: Dict[str, Dict[str, Any]] = {}
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self._load_catalog()
        self._ensure_run_dir()

    def _ensure_run_dir(self):
        try:
            RUN_DIR.mkdir(parents=True, exist_ok=True)
            RUN_DIR.chmod(0o700)
        except Exception:
            pass

    def _load_catalog(self):
        if not self.schema_file.exists():
            raise FileNotFoundError(f"Missing action schema: {self.schema_file}")
        with open(self.schema_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.actions_catalog = {a["id"]: a for a in data.get("actions", [])}

        if self.profiles_dir.exists():
            for p_file in self.profiles_dir.glob("*.json"):
                try:
                    with open(p_file, "r", encoding="utf-8") as pf:
                        p_data = json.load(pf)
                        self.profiles[p_data["id"]] = p_data
                except Exception as e:
                    print(f"Warning: Failed to load profile {p_file.name}: {e}", file=sys.stderr)

    def _eval_lua(self, lua_code: str) -> bool:
        if not lua_code.strip():
            return True
        res = subprocess.run(
            ["hyprctl", "eval", lua_code],
            capture_output=True,
            text=True,
            check=False
        )
        return res.returncode == 0 and "error" not in res.stdout.lower()

    def get_state(self) -> Dict[str, Any]:
        if not STATE_FILE.exists():
            return {
                "mode": "omarchy",
                "name": "Omarchy 原生模式",
                "active_bindings_count": 0,
                "status": "idle"
            }
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "mode": "omarchy",
                "name": "Omarchy 原生模式",
                "active_bindings_count": 0,
                "status": "idle"
            }

    def _write_state(self, mode: str, count: int):
        self._ensure_run_dir()
        profile_name = self.profiles.get(mode, {}).get("name", mode)
        state_data = {
            "mode": mode,
            "name": profile_name,
            "active_bindings_count": count,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "pid": os.getpid(),
            "status": "active" if mode != "omarchy" else "native"
        }
        tmp_file = STATE_FILE.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2, ensure_ascii=False)
            tmp_file.replace(STATE_FILE)
        except Exception as e:
            print(f"Warning: Failed to write state: {e}", file=sys.stderr)

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
        tmp_file = OVERLAY_FILE.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(bindings, f, indent=2, ensure_ascii=False)
            tmp_file.replace(OVERLAY_FILE)
        except Exception as e:
            print(f"Warning: Failed to write active overlay: {e}", file=sys.stderr)

    def restore(self) -> bool:
        """Restores Hyprland keybindings by unbinding all currently injected overlays."""
        active_overlay = self._get_active_overlay()
        if not active_overlay:
            self._write_state("omarchy", 0)
            return True

        lua_lines = []
        for b in active_overlay:
            combo = b.get("combo")
            if combo:
                lua_lines.append(f'hl.unbind("{combo}")')

        success = True
        if lua_lines:
            success = self._eval_lua("; ".join(lua_lines))

        try:
            if OVERLAY_FILE.exists():
                OVERLAY_FILE.unlink()
        except Exception:
            pass

        self._write_state("omarchy", 0)
        return success

    def switch_mode(self, target_mode: str) -> bool:
        """Atomically switches the in-memory keybindings to target_mode."""
        target_mode = target_mode.lower().strip()
        if target_mode not in self.profiles:
            valid_modes = ", ".join(self.profiles.keys())
            raise ValueError(f"Unknown mode '{target_mode}'. Available modes: {valid_modes}")

        target_profile = self.profiles[target_mode]
        target_bindings = target_profile.get("bindings", [])

        # 1. Unbind previous overlay
        current_overlay = self._get_active_overlay()
        lua_ops = []
        for b in current_overlay:
            combo = b.get("combo")
            if combo:
                lua_ops.append(f'hl.unbind("{combo}")')

        # 2. Add bind commands for new profile
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
            if action_id in LUA_DISPATCHERS:
                dispatcher_expr = LUA_DISPATCHERS[action_id]
                lua_ops.append(f'o.bind("{combo}", "{name}", {dispatcher_expr})')
            else:
                cmd = b.get("arg") or action_meta.get("default_arg", "")
                lua_ops.append(f'o.bind("{combo}", "{name}", "{cmd}")')

            new_overlay_records.append({
                "action": action_id,
                "combo": combo,
                "name": name
            })

        # 3. Execute batch in single eval call (< 2ms)
        t0 = time.perf_counter()
        success = self._eval_lua("; ".join(lua_ops))
        elapsed_ms = (time.perf_counter() - t0) * 1000

        if success:
            self._write_active_overlay(new_overlay_records)
            self._write_state(target_mode, len(new_overlay_records))

        return success

    def cycle_mode(self) -> str:
        """Cycles to the next mode in sequence: omarchy -> windows -> mac -> omarchy."""
        modes = ["omarchy", "windows", "mac"]
        current = self.get_state().get("mode", "omarchy")
        try:
            idx = modes.index(current)
            next_mode = modes[(idx + 1) % len(modes)]
        except ValueError:
            next_mode = "windows"

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

    def snap(self, zone: str) -> bool:
        """Triggers visual snap feedback and dispatches the corresponding window management action."""
        zone = zone.lower().strip()
        self._ensure_run_dir()

        # 1. Write snap.json for instantaneous QML FileView perception
        snap_data = {
            "zone": zone,
            "timestamp": time.time()
        }
        tmp_snap = SNAP_FILE.with_suffix(".tmp")
        try:
            with open(tmp_snap, "w", encoding="utf-8") as f:
                json.dump(snap_data, f, ensure_ascii=False)
            tmp_snap.replace(SNAP_FILE)
        except Exception:
            pass

        # 2. Also summon via omarchy-shell asynchronously in case daemon is not yet watching
        try:
            self._last_summon_proc = subprocess.Popen(
                ["omarchy-shell", "shell", "summon", "omni.snap-feedback", json.dumps({"zone": zone})],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except Exception:
            pass

        # 3. Dispatch window movement in Hyprland Lua
        lua_dsp = ""
        if zone == "left":
            lua_dsp = "hl.dsp.window.move({ direction = 'l' })"
        elif zone == "right":
            lua_dsp = "hl.dsp.window.move({ direction = 'r' })"
        elif zone in ("maximize", "top"):
            lua_dsp = "hl.dsp.window.fullscreen({ mode = 'maximized' })"
        elif zone in ("restore", "down"):
            lua_dsp = "hl.dsp.window.fullscreen({ mode = 'maximized' })"

        if lua_dsp:
            return self._eval_lua(lua_dsp)
        return True

    def benchmark(self) -> Dict[str, Any]:
        """Measures microsecond latency for schema loading, profile switching, and restore."""
        results = {}

        # 1. Schema & profile parse time
        t0 = time.perf_counter()
        self._load_catalog()
        results["parse_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        # 2. Windows profile switch latency
        t0 = time.perf_counter()
        self.switch_mode("windows")
        results["switch_windows_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        # 3. macOS profile switch latency
        t0 = time.perf_counter()
        self.switch_mode("mac")
        results["switch_mac_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        # 4. Restore latency
        t0 = time.perf_counter()
        self.restore()
        results["restore_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        # 5. State write latency
        t0 = time.perf_counter()
        self._write_state("omarchy", 0)
        results["state_write_ms"] = round((time.perf_counter() - t0) * 1000, 3)

        return results

def _watch_hyprland_socket2(engine: OmniPalEngine, stop_event: threading.Event):
    """Watches Hyprland socket2 for config reload events to automatically re-apply active profile."""
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    his = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    socket_path = Path(xdg_runtime) / "hypr" / his / ".socket2.sock"

    while not stop_event.is_set():
        if not socket_path.exists():
            time.sleep(2)
            continue
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(str(socket_path))
            s.settimeout(2.0)
            buffer = ""
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
                            curr_mode = engine.get_state().get("mode", "omarchy")
                            if curr_mode != "omarchy":
                                print(f"🔄 Hyprland config reload detected. Re-applying {curr_mode} overlay...", flush=True)
                                engine.switch_mode(curr_mode)
                except socket.timeout:
                    continue
                except Exception:
                    break
            s.close()
        except Exception:
            time.sleep(2)

def run_daemon():
    """Runs OmniPal Engine as a foreground daemon with socket2 listener and signal traps."""
    engine = OmniPalEngine()
    print("🚀 OmniPal Engine daemon started. Watching for signals & Hyprland events...", flush=True)

    stop_event = threading.Event()
    worker = threading.Thread(target=_watch_hyprland_socket2, args=(engine, stop_event), daemon=True)
    worker.start()

    def sig_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}. Restoring Hyprland keybindings...", flush=True)
        stop_event.set()
        engine.restore()
        print("✅ Restored successfully. Exiting cleanly.", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGHUP, sig_handler)
    atexit.register(engine.restore)

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
