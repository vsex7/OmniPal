#!/usr/bin/env python3
"""
OmniPal Phone Mirror Runner (scrcpy-both integration)
Manages multi-phone scrcpy mirroring sessions with geometry positioning,
USB auto-detection, Wi-Fi ADB fallback, desktop notifications, and diagnostics.
"""

import copy
import json
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
from typing import Any, Dict, List, Optional, Tuple


def resolve_config_dir() -> Path:
    """Resolves the OmniPal user config directory, honoring OMNIPAL_CONFIG_DIR and XDG."""
    env_dir = os.environ.get("OMNIPAL_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "omnipal"
    return Path.home() / ".config" / "omnipal"


def get_devices_config_path() -> Path:
    """Returns the path to devices.json configuration file."""
    return resolve_config_dir() / "devices.json"


def _resolve_run_dir() -> Path:
    """Resolves the runtime directory for ephemeral PID and state files."""
    custom = os.environ.get("OMNIPAL_RUN_DIR")
    if custom:
        d = Path(custom)
    else:
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg:
            d = Path(xdg) / "omnipal"
        else:
            d = Path(f"/run/user/{os.getuid()}/omnipal")
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULT_DEVICES_CONFIG: Dict[str, Any] = {
    "auto_wifi": True,
    "default_bitrate": "4M",
    "turn_screen_off": False,
    "stay_awake": True,
    "no_audio": False,
    "notify": True,
    "devices": [],
}


def load_devices_config() -> Dict[str, Any]:
    """Loads devices configuration without mutating the filesystem on read-only commands."""
    cfg_file = get_devices_config_path()
    if not cfg_file.exists():
        return copy.deepcopy(DEFAULT_DEVICES_CONFIG)

    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"⚠️ [phone_runner] Failed to parse devices.json: {e}", file=sys.stderr)

    return copy.deepcopy(DEFAULT_DEVICES_CONFIG)


def save_devices_config(cfg: Dict[str, Any]) -> bool:
    """Atomically saves device configuration with private file permissions."""
    cfg_file = get_devices_config_path()
    tmp_path = cfg_file.with_name(f".{cfg_file.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, cfg_file)
        return True
    except Exception as e:
        print(f"⚠️ [phone_runner] Failed to save devices.json: {e}", file=sys.stderr)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _read_process_cmdline(pid: int) -> List[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return [part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part]
    except OSError:
        return []


def _is_pid_alive(pid: int, expected_title: Optional[str] = None) -> bool:
    """Checks that a live PID is still the exact OmniPal-managed scrcpy process."""
    if pid <= 0:
        return False
    argv = _read_process_cmdline(pid)
    if not argv or Path(argv[0]).name != "scrcpy":
        return False
    if expected_title and f"--window-title={expected_title}" not in argv:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def notify_desktop(summary: str, body: str = "", urgency: str = "normal") -> None:
    """Sends a desktop notification using notify-send if enabled and available."""
    try:
        notify_bin = shutil.which("notify-send")
        if not notify_bin:
            return
        cmd = [notify_bin, "-a", "OmniPal", "-u", urgency, "-i", "phone", summary]
        if body:
            cmd.append(body)
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def _read_pid_record() -> Dict[str, Any]:
    """Reads PID record containing device mappings from phone_mirror.pid."""
    pid_file = _resolve_run_dir() / "phone_mirror.pid"
    if not pid_file.exists():
        return {"pids": [], "device_pids": {}}
    try:
        content = pid_file.read_text(encoding="utf-8").strip()
        if not content:
            return {"pids": [], "device_pids": {}}
        if content.startswith("{"):
            data = json.loads(content)
            device_pids = data.get("device_pids", {})
            pids = data.get("pids", [])
            if not pids and device_pids:
                pids = list(device_pids.values())
            return {
                "pids": [int(p) for p in pids if str(p).isdigit()],
                "device_pids": {k: int(v) for k, v in device_pids.items() if str(v).isdigit()},
                "device_meta": data.get("device_meta", {}) if isinstance(data.get("device_meta", {}), dict) else {},
                "started_at": data.get("started_at"),
            }
        else:
            raw_pids = [int(p) for p in content.split() if p.isdigit()]
            return {"pids": raw_pids, "device_pids": {}}
    except Exception:
        return {"pids": [], "device_pids": {}}


def _write_pid_record(
    device_pids: Dict[str, int],
    expected_titles: Optional[Dict[str, str]] = None,
    previous_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """Writes updated PID record to phone_mirror.pid."""
    pid_file = _resolve_run_dir() / "phone_mirror.pid"
    titles = expected_titles or {}
    meta_source = previous_meta or {}
    live_device_pids = {
        device_id: pid
        for device_id, pid in device_pids.items()
        if _is_pid_alive(pid, titles.get(device_id) or meta_source.get(device_id, {}).get("title"))
    }
    live_pids = list(live_device_pids.values())
    if not live_pids:
        if pid_file.exists():
            try:
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass
        return {}

    device_meta = {}
    now = int(time.time())
    for device_id, pid in live_device_pids.items():
        old_meta = meta_source.get(device_id, {})
        device_meta[device_id] = {
            "title": titles.get(device_id) or old_meta.get("title"),
            "started_at": old_meta.get("started_at") or now,
        }
    record = {
        "pids": live_pids,
        "device_pids": live_device_pids,
        "device_meta": device_meta,
        "updated_at": int(time.time()),
    }
    try:
        tmp_path = pid_file.with_name(f".{pid_file.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, pid_file)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
    return live_device_pids


def get_phone_status() -> Dict[str, Any]:
    """
    Returns current status of phone mirroring sessions, including
    overall status and per-device state.
    """
    cfg = load_devices_config()
    raw_devices = cfg.get("devices", [])
    configured_devices = raw_devices if isinstance(raw_devices, list) else []
    expected_titles = {
        str(d.get("id") or d.get("serial") or "device"): f"OmniPal Phone - {d.get('name', d.get('id', 'device'))}"
        for d in configured_devices
        if isinstance(d, dict)
    }
    record = _read_pid_record()
    device_pids = record.get("device_pids", {})
    previous_meta = record.get("device_meta", {})
    active_device_pids = {
        device_id: pid
        for device_id, pid in device_pids.items()
        if _is_pid_alive(pid, expected_titles.get(device_id) or previous_meta.get(device_id, {}).get("title"))
    }
    if active_device_pids != device_pids:
        active_device_pids = _write_pid_record(active_device_pids, expected_titles, previous_meta)

    live_pids = list(active_device_pids.values())
    is_running = len(live_pids) > 0

    devices_status = []
    for d in configured_devices:
        if not isinstance(d, dict):
            continue
        dev_id = d.get("id", d.get("serial", "phone"))
        dev_pid = active_device_pids.get(dev_id)
        if not dev_pid:
            # Check by serial as fallback
            dev_pid = active_device_pids.get(d.get("serial", ""))

        d_copy = dict(d)
        expected_title = expected_titles.get(dev_id)
        d_copy["running"] = bool(dev_pid and _is_pid_alive(dev_pid, expected_title))
        d_copy["pid"] = dev_pid if d_copy["running"] else None
        devices_status.append(d_copy)

    return {
        "running": is_running,
        "active": is_running,
        "pids": live_pids,
        "pid": live_pids[0] if live_pids else None,
        "active_devices": [d["id"] for d in devices_status if d["running"]],
        "devices": devices_status,
        "turn_screen_off": bool(cfg.get("turn_screen_off", False)),
        "auto_wifi": bool(cfg.get("auto_wifi", True)),
    }


def _get_connected_adb_devices() -> Dict[str, str]:
    """Queries `adb devices` to return a mapping of serial/target -> state."""
    try:
        res = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        lines = res.stdout.strip().splitlines()
        devs = {}
        for line in lines[1:]:
            parts = line.strip().split()
            if len(parts) >= 2:
                devs[parts[0]] = parts[1]
        return devs
    except Exception:
        return {}


def _extract_device_wlan_ip(serial: str) -> Optional[str]:
    """Extracts active WLAN IP address of a device via adb shell ip route."""
    try:
        res = subprocess.run(
            ["adb", "-s", serial, "shell", "ip", "route"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        m = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", res.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _check_tcp_port(ip: str, port: int = 5555, timeout: float = 0.5) -> bool:
    """Checks if a TCP port is open and accepting connections."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _apply_hyprland_window_geometries(devices: List[Dict[str, Any]]) -> None:
    """Under Hyprland/Wayland, client apps cannot position their own windows via --window-x/y.
    Query hyprctl clients and reposition scrcpy windows to their configured geometry.
    """
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return
    try:
        res = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True, timeout=2.0)
        if res.returncode != 0 or not res.stdout.strip():
            return
        clients = json.loads(res.stdout)
    except Exception:
        return

    for dev in devices:
        geo = dev.get("geometry", {})
        if not geo:
            continue
        gx = geo.get("x")
        gy = geo.get("y")
        gw = geo.get("width")
        gh = geo.get("height")
        if gx is None and gy is None and gw is None and gh is None:
            continue

        d_id = str(dev.get("id") or dev.get("serial") or "")
        name = str(dev.get("name", d_id))
        target_title = f"OmniPal Phone - {name}"

        for c in clients:
            if c.get("class") == "scrcpy" and (c.get("title") == target_title or name in c.get("title", "")):
                addr = c.get("address", "")
                if not addr:
                    continue
                if not c.get("floating", False):
                    subprocess.run(
                        ["hyprctl", "dispatch", f'hl.dsp.window.float({{ action = "enable", window = "address:{addr}" }})'],
                        capture_output=True,
                        timeout=1.0,
                    )
                if gw is not None and gh is not None:
                    subprocess.run(
                        ["hyprctl", "dispatch", f'hl.dsp.window.resize({{ x = {int(gw)}, y = {int(gh)}, window = "address:{addr}" }})'],
                        capture_output=True,
                        timeout=1.0,
                    )
                if gx is not None and gy is not None:
                    subprocess.run(
                        ["hyprctl", "dispatch", f'hl.dsp.window.move({{ x = {int(gx)}, y = {int(gy)}, window = "address:{addr}" }})'],
                        capture_output=True,
                        timeout=1.0,
                    )


def start_phone_mirror(device_id: Optional[str] = None) -> bool:
    """
    Spawns scrcpy instances for configured devices.
    If device_id is provided, only mirrors that device.
    """
    scrcpy_bin = shutil.which("scrcpy")
    if not scrcpy_bin:
        print("❌ Error: scrcpy is not installed or not found in PATH", file=sys.stderr)
        notify_desktop("⚠️ 手机同屏启动失败", "系统未安装 scrcpy 或 PATH 环境变量未包含", urgency="critical")
        return False

    adb_bin = shutil.which("adb")
    if not adb_bin:
        print("❌ Error: adb is not installed or not found in PATH", file=sys.stderr)
        notify_desktop("⚠️ 手机同屏启动失败", "系统未安装 adb", urgency="critical")
        return False

    cfg = load_devices_config()
    raw_devices = cfg.get("devices", [])
    devices = [d for d in raw_devices if isinstance(d, dict)] if isinstance(raw_devices, list) else []
    if not devices:
        print("⚠️ [phone_runner] No devices configured in devices.json", file=sys.stderr)
        return False

    if device_id:
        target_devs = [d for d in devices if d.get("id") == device_id or d.get("serial") == device_id]
        if not target_devs:
            print(f"❌ Device '{device_id}' not found in devices.json", file=sys.stderr)
            return False
    else:
        target_devs = devices

    target_ids = {str(d.get("id") or d.get("serial") or "device") for d in target_devs}

    auto_wifi = cfg.get("auto_wifi", True)
    default_bitrate = cfg.get("default_bitrate", "4M")
    turn_screen_off = cfg.get("turn_screen_off", False)
    stay_awake = cfg.get("stay_awake", True)
    no_audio = cfg.get("no_audio", False)
    do_notify = cfg.get("notify", True)

    record = _read_pid_record()
    current_device_pids = record.get("device_pids", {})
    current_device_meta = record.get("device_meta", {})
    expected_titles = {
        str(d.get("id") or d.get("serial") or "device"): f"OmniPal Phone - {d.get('name', d.get('id', 'device'))}"
        for d in devices
        if isinstance(d, dict)
    }
    current_device_pids = _write_pid_record(current_device_pids, expected_titles, current_device_meta)
    current_device_meta = {
        device_id: current_device_meta.get(device_id, {})
        for device_id in current_device_pids
    }

    launched_names: List[str] = []
    launch_diagnostics: Dict[str, Tuple[Any, List[str], threading.Thread]] = {}
    pending_ids = set(target_ids)

    def launch_device(dev: Dict[str, Any]) -> None:
        d_id = str(dev.get("id") or dev.get("serial") or "device")
        expected_title = expected_titles.get(d_id, f"OmniPal Phone - {dev.get('name', d_id)}")
        # Skip if already running for this device
        existing_pid = current_device_pids.get(d_id)
        if existing_pid and _is_pid_alive(existing_pid, expected_title):
            pending_ids.discard(d_id)
            return

        serial = str(dev.get("serial", "")).strip()
        ip = str(dev.get("ip", "")).strip()
        port = dev.get("port", 5555)
        name = str(dev.get("name", d_id))
        geo = dev.get("geometry", {})
        bitrate = dev.get("bitrate", default_bitrate)
        dev_turn_off = dev.get("turn_screen_off", turn_screen_off)
        dev_no_audio = dev.get("no_audio", no_audio)

        # 1. Check USB connection first
        target_selector: Optional[List[str]] = None
        if serial and connected_adb.get(serial) == "device":
            target_selector = ["-s", serial]
        elif ip and auto_wifi:
            # 2. Wi-Fi fallback: check if port 5555 is open before connecting
            if _check_tcp_port(ip, port, timeout=0.6):
                tcp_target = f"{ip}:{port}"
                if connected_adb.get(tcp_target) != "device":
                    try:
                        subprocess.run(
                            [adb_bin, "connect", tcp_target],
                            capture_output=True,
                            text=True,
                            timeout=2.0,
                        )
                    except Exception:
                        pass
                target_selector = ["-s", tcp_target]
            elif serial and connected_adb.get(serial) == "device":
                target_selector = ["-s", serial]
            else:
                # Device is not reachable via USB or open Wi-Fi port
                return
        elif serial and connected_adb.get(serial) == "device":
            target_selector = ["-s", serial]
        else:
            return

        cmd = [scrcpy_bin]
        if target_selector:
            cmd.extend(target_selector)

        cmd.append(f"--window-title=OmniPal Phone - {name}")

        if isinstance(geo, dict):
            if "x" in geo:
                cmd.append(f"--window-x={geo['x']}")
            if "y" in geo:
                cmd.append(f"--window-y={geo['y']}")
            if "width" in geo:
                cmd.append(f"--window-width={geo['width']}")
            if "height" in geo:
                cmd.append(f"--window-height={geo['height']}")

        if bitrate:
            cmd.extend(["-b", str(bitrate)])

        if stay_awake:
            cmd.append("--stay-awake")

        if dev_turn_off:
            cmd.append("--turn-screen-off")

        if dev_no_audio:
            cmd.append("--no-audio")

        stderr_buffer: List[str] = []
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )

            def drain_stderr() -> None:
                try:
                    if proc.stderr is not None:
                        stderr_buffer.append(proc.stderr.read() or "")
                except Exception:
                    pass
                finally:
                    if proc.stderr is not None:
                        proc.stderr.close()

            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()
            launch_diagnostics[d_id] = (proc, stderr_buffer, stderr_thread)
            current_device_pids[d_id] = proc.pid
            current_device_meta[d_id] = {"title": expected_title, "started_at": int(time.time())}
            if name not in launched_names:
                launched_names.append(name)
        except Exception as e:
            print(f"⚠️ [phone_runner] Failed to spawn scrcpy for {name}: {e}", file=sys.stderr)

    # Retry transient scrcpy/ADB startup failures while allowing time to initialize.
    for attempt in range(3):
        # Refresh on every attempt so newly attached devices and a restarted
        # ADB server are observed before the next scrcpy launch.
        connected_adb = _get_connected_adb_devices()
        for dev in target_devs:
            d_id = str(dev.get("id") or dev.get("serial") or "device")
            if d_id in pending_ids:
                launch_device(dev)

        if not pending_ids:
            break

        time.sleep(0.5 * (attempt + 1))
        for d_id in list(pending_ids):
            pid = current_device_pids.get(d_id)
            title = expected_titles.get(d_id) or current_device_meta.get(d_id, {}).get("title")
            if pid and _is_pid_alive(pid, title):
                pending_ids.discard(d_id)

    # Verify which scrcpy processes actually remained alive
    alive_device_pids: Dict[str, int] = {}
    for d_id, p in current_device_pids.items():
        expected_title = expected_titles.get(d_id)
        if _is_pid_alive(p, expected_title or current_device_meta.get(d_id, {}).get("title")):
            alive_device_pids[d_id] = p

    _write_pid_record(alive_device_pids, expected_titles, current_device_meta)

    missing_target_ids = sorted(target_ids - set(alive_device_pids))
    if missing_target_ids:
        if not alive_device_pids:
            reason = "未检测到可用的在线手机或投屏进程未能维持运行"
        else:
            reason = f"目标设备未维持运行: {', '.join(missing_target_ids)}"
        print(f"❌ Error: {reason}", file=sys.stderr)
        for d_id in missing_target_ids:
            diagnostic = launch_diagnostics.get(d_id)
            if not diagnostic:
                continue
            proc, output, thread = diagnostic
            if proc.poll() is not None:
                thread.join(timeout=0.2)
            details = "".join(output).strip().splitlines()
            if details:
                tail = " | ".join(details[-3:])
                print(f"   [{d_id}] {tail}", file=sys.stderr)
        if do_notify:
            notify_desktop("⚠️ 手机同屏未完全启动", reason, urgency="normal")
        return False

    _apply_hyprland_window_geometries(target_devs)

    if launched_names and do_notify:
        names_str = ", ".join(launched_names)
        notify_desktop("📱 手机同屏已启动", f"正在同屏: {names_str}")

    return True


def stop_phone_mirror(device_id: Optional[str] = None) -> bool:
    """
    Terminates runner processes. If device_id is specified, only stops that device.
    Otherwise stops all phone mirroring sessions.
    """
    cfg = load_devices_config()
    do_notify = cfg.get("notify", True)
    raw_devices = cfg.get("devices", [])
    devices = [d for d in raw_devices if isinstance(d, dict)] if isinstance(raw_devices, list) else []
    expected_titles = {
        str(d.get("id") or d.get("serial") or "device"): f"OmniPal Phone - {d.get('name', d.get('id', 'device'))}"
        for d in devices
        if isinstance(d, dict)
    }
    record = _read_pid_record()
    current_device_pids = record.get("device_pids", {})
    current_device_meta = record.get("device_meta", {})

    pids_to_kill: List[int] = []
    killed_titles: Dict[int, str] = {}
    stopped_names: List[str] = []

    if device_id:
        resolved_id = device_id
        if resolved_id not in current_device_pids:
            resolved_id = next(
                (str(d.get("id")) for d in devices if isinstance(d, dict) and d.get("serial") == device_id),
                device_id,
            )
        pid = current_device_pids.get(resolved_id)
        expected_title = expected_titles.get(resolved_id) or current_device_meta.get(resolved_id, {}).get("title")
        if pid and _is_pid_alive(pid, expected_title):
            pids_to_kill.append(current_device_pids.pop(resolved_id))
            if expected_title:
                killed_titles[pid] = expected_title
            current_device_meta.pop(resolved_id, None)
            stopped_names.append(resolved_id)
        else:
            current_device_pids.pop(resolved_id, None)
            current_device_meta.pop(resolved_id, None)
            _write_pid_record(current_device_pids, expected_titles, current_device_meta)
            print(f"❌ Device '{device_id}' is not running or is not a managed scrcpy process", file=sys.stderr)
            return False
    else:
        for device_key, pid in list(current_device_pids.items()):
            expected_title = expected_titles.get(device_key) or current_device_meta.get(device_key, {}).get("title")
            if _is_pid_alive(pid, expected_title):
                pids_to_kill.append(pid)
                if expected_title:
                    killed_titles[pid] = expected_title
                stopped_names.append(device_key)
            else:
                current_device_pids.pop(device_key, None)
                current_device_meta.pop(device_key, None)
        current_device_pids.clear()
        current_device_meta.clear()

    for p in pids_to_kill:
        try:
            os.kill(p, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    if pids_to_kill:
        time.sleep(0.2)
        for p in pids_to_kill:
            if _is_pid_alive(p):
                try:
                    os.kill(p, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass

    _write_pid_record(current_device_pids, expected_titles, current_device_meta)

    if stopped_names and do_notify:
        notify_desktop("📱 手机同屏已停止", "已安全断开屏幕镜像会话")

    remaining = [
        pid for pid in pids_to_kill
        if _is_pid_alive(pid, killed_titles.get(pid))
    ]
    return not remaining


def toggle_phone_mirror(device_id: Optional[str] = None) -> bool:
    """Toggles phone mirroring: stops if running, starts otherwise."""
    st = get_phone_status()
    if device_id:
        dev = next((d for d in st["devices"] if d.get("id") == device_id or d.get("serial") == device_id), None)
        if not dev:
            print(f"❌ Device '{device_id}' not found in devices.json", file=sys.stderr)
            return False
        if dev and dev.get("running"):
            return stop_phone_mirror(dev.get("id", device_id))
        else:
            return start_phone_mirror(device_id)
    else:
        if st.get("running"):
            return stop_phone_mirror()
        else:
            return start_phone_mirror()


def diagnose_phone_environment() -> Dict[str, Any]:
    """Performs deep health and connectivity diagnosis for scrcpy and connected phones."""
    report: Dict[str, Any] = {
        "scrcpy": {"installed": False, "version": None, "path": None},
        "adb": {"installed": False, "server_ok": False, "path": None},
        "devices": [],
        "verdict": "ready",
        "suggestions": [],
    }

    # 1. scrcpy check
    scrcpy_path = shutil.which("scrcpy")
    if scrcpy_path:
        report["scrcpy"]["installed"] = True
        report["scrcpy"]["path"] = scrcpy_path
        try:
            out = subprocess.check_output(["scrcpy", "--version"], text=True, timeout=2.0)
            first_line = out.splitlines()[0] if out.splitlines() else ""
            report["scrcpy"]["version"] = first_line
        except Exception:
            report["scrcpy"]["version"] = "unknown"
    else:
        report["verdict"] = "error"
        report["suggestions"].append("系统未安装 scrcpy，请运行: sudo pacman -S scrcpy")

    # 2. adb check
    adb_path = shutil.which("adb")
    if adb_path:
        report["adb"]["installed"] = True
        report["adb"]["path"] = adb_path
        try:
            res = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=2.0)
            report["adb"]["server_ok"] = (res.returncode == 0)
        except Exception:
            report["adb"]["server_ok"] = False
    else:
        report["verdict"] = "error"
        report["suggestions"].append("系统未安装 adb (android-tools)，请运行: sudo pacman -S android-tools")

    # 3. Devices check
    cfg = load_devices_config()
    raw_devices = cfg.get("devices", [])
    devices = [d for d in raw_devices if isinstance(d, dict)] if isinstance(raw_devices, list) else []
    connected_adb = _get_connected_adb_devices()

    has_any_connected = False
    for dev in devices:
        d_id = dev.get("id", "device")
        name = dev.get("name", d_id)
        serial = dev.get("serial", "")
        ip = dev.get("ip", "")
        port = dev.get("port", 5555)

        usb_state = connected_adb.get(serial, "disconnected")
        wifi_port_open = _check_tcp_port(ip, port) if ip else False

        dev_diag = {
            "id": d_id,
            "name": name,
            "serial": serial,
            "ip": ip,
            "usb_state": usb_state,
            "wifi_port_5555": wifi_port_open,
            "status": "ready" if (usb_state == "device" or wifi_port_open) else "offline",
        }

        if usb_state == "device":
            has_any_connected = True
        elif usb_state == "unauthorized":
            report["suggestions"].append(f"设备 [{name}] USB 处于未授权状态，请在手机端勾选『始终允许此计算机进行 USB 调试』")
        elif wifi_port_open:
            has_any_connected = True

        report["devices"].append(dev_diag)

    if not has_any_connected and report["verdict"] == "ready":
        report["verdict"] = "degraded"
        report["suggestions"].append("当前未检测到在线设备，请通过 USB 数据线连接手机或确保手机在同一局域网并已开启无线调试")

    return report


if __name__ == "__main__":
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "status"
    target = sys.argv[2] if len(sys.argv) > 2 else None
    if action == "start":
        ok = start_phone_mirror(target)
        sys.exit(0 if ok else 1)
    elif action == "stop":
        ok = stop_phone_mirror(target)
        sys.exit(0 if ok else 1)
    elif action == "toggle":
        ok = toggle_phone_mirror(target)
        sys.exit(0 if ok else 1)
    elif action == "status":
        print(json.dumps(get_phone_status(), indent=2, ensure_ascii=False))
        sys.exit(0 if get_phone_status().get("running") else 1)
    elif action == "doctor":
        print(json.dumps(diagnose_phone_environment(), indent=2, ensure_ascii=False))
        sys.exit(0)
    elif action == "config":
        print(json.dumps(load_devices_config(), indent=2, ensure_ascii=False))
        sys.exit(0)
    else:
        print(f"Usage: {sys.argv[0]} [start|stop|toggle|status|doctor|config] [device_id]", file=sys.stderr)
        sys.exit(2)
