"""Daemon entry points: socket watcher, persisted-profile restore, run_daemon."""

import atexit
import os
import signal
import socket
import sys
import threading
import time
from typing import Optional

from engine.omnipal.paths import (PID_FILE, STATE_FILE, _resolve_run_dir)
from engine.omnipal.util import (_debug)
from engine.omnipal.hypr_ipc import (find_socket2_path, hyprland_socket_ready)
from engine.omnipal.profiles import (is_special_window)
from engine.omnipal.core import (OmniPalEngine)

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
        # Native mode still gets the fixed OmniPal entry points.
        if wait_for_hyprland(timeout=wait_timeout):
            engine.apply_fixed_bindings()
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
            # Broad: switch_mode() may raise arbitrary errors; the retry loop
            # must survive them to attempt the remaining attempts.
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
                    if eff_mode in ("floating", "scrolling"):
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
                                engine.apply_fixed_bindings()
                            eff_mode = engine.get_effective_window_mode()
                            if eff_mode in ("floating", "scrolling"):
                                print(f"🔄 Hyprland config reload detected. Re-applying {eff_mode} window rule...", flush=True)
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
                                        if OmniPalEngine.keeps_own_size(cls_name):
                                            # scrcpy etc.: float only; user's own size/move rules win
                                            engine._apply_golden_cascade_geometry(addr, keep_size=True)
                                        elif is_dlg:
                                            engine._apply_golden_cascade_geometry(addr, is_dialog=True)
                                        else:
                                            # Golden terraced cascade (like f0adc4f); no size cap for new windows
                                            engine._apply_golden_cascade_geometry(
                                                addr, step=cascade_counter, is_dialog=False)
                                            engine._remember_floated(addr)
                                            cascade_counter = (cascade_counter + 1) % 6
                except socket.timeout:
                    continue
                except Exception:
                    # Broad: any unexpected socket error tears down this
                    # connection; the outer handler below reconnects.
                    break
            s.close()
        except Exception:
            # Broad: the watcher must never die; drop the cached signature
            # and reconnect after a pause.
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
    except OSError as _e:
        _debug(_e)

    print(f"🚀 OmniPal Engine daemon started (PID: {os.getpid()}). Watching for signals & Hyprland events...", flush=True)

    # Retired modes (kde) fall back to windows; rules targeting them are dropped.
    for line in engine.migrate_retired_modes():
        print(f"📦 Migrated retired mode: {line}", flush=True)

    # Check and restore persisted window policy and profile on startup
    persisted_status = engine.get_persistence_status()
    persisted_policy = engine.get_persisted_window_policy()
    persisted_mode = engine.get_persisted_profile()

    if persisted_policy and (persisted_policy != "follow-profile"
                             or engine.get_window_policy() != "follow-profile"):
        print(f"📦 Restoring persisted window policy on startup: {persisted_policy}", flush=True)
        engine.set_window_policy(persisted_policy, source="daemon-startup (persisted choice)")
    elif persisted_status.get("enabled"):
        engine.set_persistence(True, source="daemon-startup")

    if persisted_mode and persisted_mode != "omarchy":
        restore_persisted_profile(engine)
    elif persisted_mode == "omarchy":
        engine._write_state("omarchy", 0, policy=engine.get_window_policy())
    elif persisted_status.get("enabled"):
        cur_mode = engine.get_state().get("mode") or "windows"
        engine.set_persistence(True, profile=cur_mode)

    # Enforce active window policy on startup
    if engine.get_effective_window_mode() in ("floating", "scrolling"):
        try:
            engine._apply_window_policy(force=True)
        except Exception as _e:
            # Broad: startup policy enforcement is best-effort; the daemon
            # must stay up even if the compositor misbehaves.
            _debug(f"startup window-policy apply failed: {_e}")

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
            except OSError:
                pass  # best-effort cleanup
            curr = engine.get_state().get("mode", "omarchy")
            cur_app = engine._get_applied_window_mode()
            if curr != "omarchy" or cur_app in ("floating", "scrolling") or engine._get_active_overlay():
                # Do not sync persistence on shutdown: exit must not rewrite the last chosen profile.
                engine.restore(sync_persistence=False)

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
