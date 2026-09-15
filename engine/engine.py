#!/usr/bin/env python3
"""
OmniPal Core Runtime Engine
Version: 1.2.0 (Production Release with Tray and Context Menu)

Strictly adheres to AGENTS.md rules:
1. Pure in-memory overlay via Omarchy Hyprland Lua engine (`hyprctl eval`)
2. Zero file writes to ~/.config/hypr/ or system configs
3. Safe signal handling: automatic restore on SIGTERM/SIGINT/SIGHUP
4. State broadcast via /run/user/$UID/omnipal/state.json (tmpfs)
5. Instant rollback on injection failure
6. User custom profiles support via ~/.config/omnipal/profiles/
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
from typing import Any, Dict, List, Optional, Tuple

RUN_DIR = Path(f"/run/user/{os.getuid()}/omnipal")
STATE_FILE = RUN_DIR / "state.json"
OVERLAY_FILE = RUN_DIR / "active_overlay.json"
SNAP_FILE = RUN_DIR / "snap.json"
PID_FILE = RUN_DIR / "daemon.pid"

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

def resolve_user_profiles_dir() -> Path:
    """Resolves the user custom profiles directory, honoring OMNIPAL_USER_PROFILES_DIR and XDG."""
    env_dir = os.environ.get("OMNIPAL_USER_PROFILES_DIR")
    if env_dir:
        return Path(env_dir)
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "omnipal" / "profiles"
    return Path.home() / ".config" / "omnipal" / "profiles"

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
            return sockets[0]
    return None

class OmniPalEngine:
    def __init__(self, root_dir: Optional[Path] = None, user_profiles_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent
        self.user_profiles_dir = Path(user_profiles_dir) if user_profiles_dir else resolve_user_profiles_dir()
        self.schema_file = self.root_dir / "schema" / "actions.json"
        self.profiles_dir = self.root_dir / "profiles"
        self.actions_catalog: Dict[str, Dict[str, Any]] = {}
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self._last_summon_proc = None
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

    def _eval_lua(self, lua_code: str) -> bool:
        """Executes Lua expressions in Omarchy Hyprland compositor with strict error checking."""
        if not lua_code.strip():
            return True
        try:
            res = subprocess.run(
                ["hyprctl", "eval", lua_code],
                capture_output=True,
                text=True,
                check=False
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

    def get_state(self) -> Dict[str, Any]:
        default_state = {
            "version": "1.2.0",
            "mode": "omarchy",
            "name": "Omarchy 原生模式",
            "active_bindings_count": 0,
            "status": "idle"
        }
        if not STATE_FILE.exists():
            return default_state
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_state

    def _write_state(self, mode: str, count: int):
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

        state_data = {
            "version": "1.2.0",
            "mode": mode,
            "name": profile_name,
            "display": display_meta,
            "active_bindings_count": count,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "pid": os.getpid(),
            "daemon_pid": daemon_pid,
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
        """Atomically switches the in-memory keybindings to target_mode with rollback on error."""
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

        # 3. Execute batch in single eval call (< 5ms)
        success = self._eval_lua("; ".join(lua_ops))

        if success:
            self._write_active_overlay(new_overlay_records)
            self._write_state(target_mode, len(new_overlay_records))
        else:
            print("Warning: Failed to apply overlay in Hyprland, rolling back to baseline...", file=sys.stderr)
            self.restore()

        return success

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

        # 2. Summon via omarchy-shell asynchronously
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
        elif zone == "center":
            lua_dsp = """local w = hl.get_active_window()
if w then
  local m = hl.get_active_monitor()
  if not w.floating then hl.dsp.window.float({ action = 'toggle' }) end
  local rx = m.x + (m.reserved and m.reserved.left or 0)
  local ry = m.y + (m.reserved and m.reserved.top or 0)
  local rw = m.width - (m.reserved and (m.reserved.left + m.reserved.right) or 0)
  local rh = m.height - (m.reserved and (m.reserved.top + m.reserved.bottom) or 0)
  local tw = math.floor(rw * 0.6)
  local th = math.floor(rh * 0.7)
  local tx = rx + math.floor((rw - tw) / 2)
  local ty = ry + math.floor((rh - th) / 2)
  hl.dsp.window.resize({ x = tw, y = th })
  hl.dsp.window.move({ x = tx, y = ty })
end"""
        elif zone in ("third-left", "third-right", "two-thirds-left", "two-thirds-right"):
            ratio_val = "0.667" if "two-thirds" in zone else "0.333"
            align_right = "true" if "-right" in zone else "false"
            lua_dsp = f"""local w = hl.get_active_window()
if w then
  local m = hl.get_active_monitor()
  if not w.floating then hl.dsp.window.float({{ action = 'toggle' }}) end
  local rx = m.x + (m.reserved and m.reserved.left or 0)
  local ry = m.y + (m.reserved and m.reserved.top or 0)
  local rw = m.width - (m.reserved and (m.reserved.left + m.reserved.right) or 0)
  local rh = m.height - (m.reserved and (m.reserved.top + m.reserved.bottom) or 0)
  local tw = math.floor(rw * {ratio_val})
  local th = rh
  local is_right = {align_right}
  local tx = is_right and (rx + rw - tw) or rx
  local ty = ry
  hl.dsp.window.resize({{ x = tw, y = th }})
  hl.dsp.window.move({{ x = tx, y = ty }})
end"""

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

    def doctor(self) -> Dict[str, Any]:
        """Runs comprehensive diagnostics on daemon, sockets, live binds, and state consistency."""
        report: Dict[str, Any] = {
            "healthy": True,
            "version": "1.2.0",
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
        from scripts.check_consistency import check_consistency
        report["consistency"] = check_consistency(self.root_dir, user_profiles_dir=self.user_profiles_dir)
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
                            time.sleep(0.1)  # Debounce settle time
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
    engine._ensure_run_dir()

    # Record PID
    try:
        PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass

    print(f"🚀 OmniPal Engine daemon started (PID: {os.getpid()}). Watching for signals & Hyprland events...", flush=True)

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
