"""OmniPalEngine: the in-memory keybinding overlay engine."""

import datetime
import json
import contextlib
import io
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from engine.omnipal.version import (__version__)
from engine.omnipal.paths import (APPLIED_WINDOW_MODE_FILE, APP_RULE_STATE_FILE, BASELINE_FILE, FLOATED_BY_OMNIPAL_FILE, OVERLAY_FILE, PID_FILE, SNAP_FILE, SNAP_LAYOUTS_FILE, STATE_FILE, _resolve_run_dir, app_rules_file_path, persistence_file_path, resolve_user_profiles_dir)
from engine.omnipal.util import (LUA_RESTORE_BASELINE, _KEEP, _debug, _escape_lua_string, _sig_combo, atomic_write_json, bind_key_name, bind_signature, combo_signature, compositor_mutation_disabled, engine_lock, find_duplicate_binds, format_combo, log_policy_write, lua_str, notify_user, write_state_json)
from engine.omnipal.hypr_ipc import (_dedupe_binds_lua, _ensure_hyprland_instance, _native_stash_lua, _native_unstash_lua, find_socket2_path)
from engine.omnipal.profiles import (FORWARD_ACTION, MIGRATION_FALLBACK_MODE, OWN_SIZE_CLASSES, RETIRED_MODES, combo_key, find_protected_violations, forward_for_class, forward_lua, is_special_window, load_fixed_bindings, load_protected_combos, load_terminal_patterns, normalize_window_policy, parse_forward)

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
# --- App-rule regex safety -------------------------------------------------
# A regex-typed app rule runs inside the daemon on every focus change
# (OmniPalEngine.match_app_rule), so a catastrophic-backtracking pattern can
# wedge the whole daemon. All rule entry points (`rules add`, `rules import`,
# and the settings panel, which shells out to the `omni-profile rules` CLI)
# funnel through validate_app_rule_pattern(); keep it the single gate.
APP_RULE_REGEX_MAX_LEN = 200
APP_RULE_WINDOW_CLASS_MAX_LEN = 512

# A group-closing `)` directly followed by `*`, `+`, or `{`: the whole group is
# under quantification — the catastrophic-backtracking shape, e.g. (a+)+,
# (a|a)*b, (.*a){12}, (a{1,30}){1,30}. `)?` stays allowed, so the existing
# `(https?://)?` is unaffected. Operates on the literal-stripped skeleton, so
# only real group closes are seen.
# Same single atom quantified twice in a row, e.g. a*a* or .*.* : ambiguous and
# just as exponential on failure; nobody writes this on purpose. (a*b* with
# different atoms is linear and stays allowed.)
_REPEATED_QUANTIFIED_ATOM_RE = re.compile(r"(.)[*+]\1[*+]")


def _has_quantified_group(skeleton: str) -> bool:
    """True if a group-closing `)` is directly followed by `*`, `+`, or `{`.
    Runs on the literal-stripped skeleton so only real group closes are seen;
    `)?` is deliberately not flagged here (checked by callers)."""
    i = skeleton.find(")")
    while i != -1:
        j = i + 1
        if j < len(skeleton) and skeleton[j] in "*+{":
            return True
        i = skeleton.find(")", j)
    return False


def _is_valid_workspace_id(ws_id: Any) -> bool:
    """Validates numeric workspace ID. Named workspaces have negative IDs and must be skipped."""
    try:
        val = int(str(ws_id).strip())
        return val >= 1
    except (ValueError, TypeError):
        return False


# Omarchy executes the per-workspace layout state files as Lua, so a layout
# name must never be interpolated into them (or into eval'd Lua) unchecked.
_VALID_WORKSPACE_LAYOUTS = frozenset({"dwindle", "scrolling", "floating"})


def _validated_workspace_layout(value: Any) -> str:
    """Returns the layout name if it is on the allowlist, else ""."""
    layout = str(value or "").strip().lower()
    return layout if layout in _VALID_WORKSPACE_LAYOUTS else ""


def _sanitize_saved_workspace_layouts(raw: Any) -> Dict[str, str]:
    """Keeps only restorable saved layouts: valid workspace, allowlisted layout.

    A workspace whose original layout was "floating" has nothing to restore
    (switching back to tiled must not force it to a tiled layout), so such
    entries are dropped instead of being recorded as e.g. "dwindle"."""
    out: Dict[str, str] = {}
    if isinstance(raw, dict):
        for ws_id, layout in raw.items():
            valid_layout = _validated_workspace_layout(layout)
            if _is_valid_workspace_id(ws_id) and valid_layout and valid_layout != "floating":
                out[str(ws_id)] = valid_layout
    return out


def _strip_regex_literals(pattern: str) -> str:
    """Blank out escaped chars and [...] classes so the nested-quantifier
    heuristic only sees real regex syntax (e.g. ``\\+`` or ``[+]`` are not
    quantifiers)."""
    out = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":
            out.append(" ")
            i += 2
            continue
        if c == "[":
            j = i + 1
            if j < n and pattern[j] == "^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1  # a leading "]" is a literal
            while j < n and pattern[j] != "]":
                if pattern[j] == "\\":
                    j += 1
                j += 1
            i = j + 1 if j < n else n
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def validate_app_rule_pattern(pattern: str) -> None:
    """Reject regex-typed app-rule patterns that are invalid, too long, or
    shaped for catastrophic backtracking. Raises ValueError with a
    human-readable (Chinese) reason; returns None when the pattern is fine."""
    if not isinstance(pattern, str):
        raise ValueError("规则类名必须是字符串")
    if len(pattern) > APP_RULE_REGEX_MAX_LEN:
        raise ValueError(
            f"正则过长（{len(pattern)} 字符，上限 {APP_RULE_REGEX_MAX_LEN}），请缩短")
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"正则非法: {e}")
    skeleton = _strip_regex_literals(pattern)
    if _has_quantified_group(skeleton):
        raise ValueError("正则中分组后面不能直接跟量词（*、+、{…}），可能导致匹配卡死，已拒绝；"
                         "可选分组请用 (…) ? 形式")
    if _REPEATED_QUANTIFIED_ATOM_RE.search(skeleton):
        raise ValueError("正则包含重复量词（如 a*a*），匹配可能卡死，已拒绝")


class OmniPalEngine:
    def __init__(self, root_dir: Optional[Path] = None, user_profiles_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parents[2]  # NOTE(structure): core.py lives one level deeper than the old engine.py; parents[2] == repo root
        self.user_profiles_dir = Path(user_profiles_dir) if user_profiles_dir else resolve_user_profiles_dir()
        self.schema_file = self.root_dir / "schema" / "actions.json"
        self.snap_schema_file = self.root_dir / "schema" / "snap_layouts.json"
        self.profiles_dir = self.root_dir / "profiles"
        self.fixed_bindings: List[Dict[str, Any]] = load_fixed_bindings(self.root_dir)
        self.actions_catalog: Dict[str, Dict[str, Any]] = {}
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self.snap_zones: Dict[str, Dict[str, Any]] = {}
        self.snap_layouts: List[Dict[str, Any]] = []
        self._last_summon_proc = None
        self.window_policy: str = "follow-profile"
        self._saved_workspace_layouts: Dict[str, str] = {}
        self._ensure_run_dir()
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    _st = json.load(f)
                    pol = normalize_window_policy(_st.get("window_policy"))
                    if pol:
                        self.window_policy = pol
                    if isinstance(_st.get("saved_workspace_layouts"), dict):
                        self._saved_workspace_layouts = _sanitize_saved_workspace_layouts(_st["saved_workspace_layouts"])
            except (OSError, ValueError) as _e:
                # Corrupt/unreadable state file: fall back to default policy.
                _debug(f"ignoring unreadable state file: {_e}")
        else:
            try:
                persisted_pol = self.get_persisted_window_policy()
                if persisted_pol:
                    self.window_policy = persisted_pol
            except (OSError, ValueError) as _e:
                _debug(f"ignoring unreadable persisted window policy: {_e}")
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
        except OSError as _e:
            _debug(f"cannot ensure run dir: {_e}")

    def _load_snap_schema(self):
        if self.snap_schema_file.exists():
            try:
                with open(self.snap_schema_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.snap_zones = data.get("zones", {})
                    self.snap_layouts = data.get("templates", [])
            except (OSError, ValueError) as e:
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
        except (OSError, ValueError, subprocess.SubprocessError) as _e:
            _debug(f"hyprctl getoption failed, using default gap: {_e}")
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
                except (OSError, ValueError) as e:
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
                except (OSError, ValueError) as e:
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
                "window_mode": p_data.get("window_mode", "tiled"),
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
        except (OSError, ValueError) as _e:
            _debug(f"ignoring unreadable persistence file {path}: {_e}")
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
        if status["enabled"] and policy in ("follow-profile", "tiled", "floating"):
            return policy
        return None

    def set_persistence(
        self,
        enabled: bool,
        profile: Optional[str] = None,
        window_policy: Optional[str] = None,
        source: str = "unspecified",
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
            except (OSError, ValueError, TypeError) as e:
                print(f"Warning: Failed to write disabled persistence config {path}: {e}", file=sys.stderr)
                return False

        cur_persisted = self.get_persistence_status()

        # Resolve target profile (persist enable snapshots current mode by default):
        # passed profile -> active mode in state -> existing persisted profile -> "windows"
        target_profile = (
            profile
            or self.get_state().get("mode")
            or cur_persisted.get("profile")
            or "windows"
        ).lower().strip()

        if target_profile not in self.profiles:
            valid = ", ".join(sorted(self.profiles.keys()))
            print(f"Error: Unknown profile '{target_profile}' for persistence. Available profiles: {valid}", file=sys.stderr)
            return False

        # Window policy: only an explicit choice changes it. Profile syncs (switch / cycle /
        # restore / startup) pass none and must keep the persisted policy; the runtime policy is
        # used only when persistence holds none yet (first enable).
        raw_policy = (
            window_policy
            or cur_persisted.get("window_policy")
            or self.get_window_policy()
            or "follow-profile"
        )
        target_policy = normalize_window_policy(raw_policy) or "follow-profile"
        old_policy = cur_persisted.get("window_policy")
        if window_policy or old_policy != target_policy:
            log_policy_write("persistence.json", old_policy, target_policy,
                             source if window_policy else f"{source} (implicit)")

        data = {
            "enabled": True,
            "profile": target_profile,
            "window_policy": target_policy,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"Warning: Failed to create config dir {path.parent}: {e}", file=sys.stderr)
            return False

        return atomic_write_json(path, data)

    def migrate_retired_modes(self) -> List[str]:
        """Retired built-in modes (kde) fall back to windows: rewrites state.json (mode / auto),
        persistence.json (profile) and app_rules.json (default_mode; rules targeting a retired
        mode are dropped). Returns human-readable log lines, one per rewritten file."""
        fb = MIGRATION_FALLBACK_MODE
        logs: List[str] = []

        def _load(path: Path) -> Any:
            if not path.exists():
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        try:
            data = _load(STATE_FILE)
            if isinstance(data, dict):
                changed = False
                auto = data.get("auto")
                if isinstance(auto, dict):
                    if auto.get("mode") in RETIRED_MODES:
                        data.pop("auto", None); changed = True
                    elif auto.get("return_to") in RETIRED_MODES:
                        auto["return_to"] = fb; changed = True
                old = data.get("mode")
                old_ret = auto.get("return_to") if isinstance(auto, dict) else None
                if old in RETIRED_MODES:
                    prof = self.profiles.get(fb, {})
                    data["mode"] = fb
                    data["name"] = prof.get("name", fb)
                    data["display"] = prof.get("display", {})
                    data.pop("auto", None)
                    changed = True
                if changed and write_state_json(STATE_FILE, data):
                    retired = old if old in RETIRED_MODES else (auto.get("mode") if isinstance(auto, dict) and auto.get("mode") in RETIRED_MODES else old_ret)
                    logs.append(f"{STATE_FILE}: retired mode '{retired}' -> '{fb}'")
        except (OSError, ValueError, TypeError) as _e:
            _debug(_e)
        try:
            path = persistence_file_path()
            data = _load(path)
            if isinstance(data, dict) and data.get("profile") in RETIRED_MODES:
                old = data["profile"]
                data["profile"] = fb
                if atomic_write_json(path, data):
                    logs.append(f"{path}: persisted profile '{old}' -> '{fb}'")
        except (OSError, ValueError, TypeError) as _e:
            _debug(_e)
        try:
            path = app_rules_file_path()
            data = _load(path)
            if isinstance(data, dict):
                rules = data.get("rules") if isinstance(data.get("rules"), list) else []
                kept = [r for r in rules if not (isinstance(r, dict) and r.get("mode") in RETIRED_MODES)]
                dropped = len(rules) - len(kept)
                dm_old = data.get("default_mode")
                if dropped or dm_old in RETIRED_MODES:
                    data["rules"] = kept
                    if dm_old in RETIRED_MODES:
                        data["default_mode"] = fb
                    if atomic_write_json(path, data):
                        msg = f"{path}: dropped {dropped} rule(s) targeting retired modes"
                        if dm_old in RETIRED_MODES:
                            msg += f", default_mode '{dm_old}' -> '{fb}'"
                        logs.append(msg)
        except (OSError, ValueError, TypeError) as _e:
            _debug(_e)
        return logs

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
        except (OSError, subprocess.SubprocessError) as e:
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
        except (OSError, subprocess.SubprocessError) as e:
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
        except (OSError, subprocess.SubprocessError) as e:
            print(f"Hyprland config reload failed: {e}", file=sys.stderr)
            return False

    def _get_applied_window_mode(self) -> str:
        if APPLIED_WINDOW_MODE_FILE.exists():
            try:
                val = APPLIED_WINDOW_MODE_FILE.read_text(encoding="utf-8").strip()
                if val in ("floating", "tiled"):
                    return val
            except (OSError, ValueError) as _e:
                # Best-effort read; fall back to the default below.
                _debug(f"ignoring unreadable applied-window-mode file: {_e}")
        return "tiled"

    def _set_applied_window_mode(self, mode: str):
        self._ensure_run_dir()
        try:
            APPLIED_WINDOW_MODE_FILE.write_text(mode, encoding="utf-8")
        except OSError as _e:
            _debug(f"failed to record applied window mode: {_e}")

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
                sig = bind_signature(b)
                if sig is None:
                    continue
                counts[sig] = counts.get(sig, 0) + 1
        except (OSError, ValueError, subprocess.SubprocessError) as e:
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
                sig = bind_signature(b)
                if sig is None:
                    continue
                out.setdefault(sig, []).append(b)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
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
            # Binding-level display name wins (e.g. mac forwards) so `hyprctl binds`
            # shows the same name as the cheatsheet; falls back to the action name.
            name = b.get("name") or action_meta.get("name", action_id)
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

    # ---------- fixed entry points (same keys in every mode) ----------
    def mode_diff(self, mode: str, live: Optional[Dict[Tuple[int, str], List[Dict[str, Any]]]] = None) -> Dict[str, Any]:
        """Which Omarchy native binds `mode` takes over, and what they did before.

        Natives come from live `hyprctl binds` (minus OmniPal's own overlay); combos the active
        overlay already replaced fall back to the baseline snapshot. `source` says which was used."""
        if mode not in self.profiles:
            raise ValueError(f"unknown mode: {mode}")
        if live is None:
            live = self._own_filtered_natives()
        if not self.baseline_bindings:
            self._load_baseline_cache()
        baseline: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
        for b in (self.baseline_bindings or {}).values():
            baseline.setdefault(combo_signature(b.get("combo", "")), []).append(b)
        source = "live" if live else ("baseline" if baseline else "none")
        bindings = ([] if mode == "omarchy" else self._without_fixed(self.profiles[mode].get("bindings", [])))
        entries = [(b, False) for b in bindings] + [(b, True) for b in self.fixed_bindings]
        out, seen = [], set()
        for b, is_fixed in entries:
            combo = format_combo(b.get("mod", ""), b.get("key", ""))
            if not combo or combo in seen:
                continue
            seen.add(combo)
            sig = combo_signature(combo)
            natives, keys = [], set()
            for n in (live.get(sig) or baseline.get(sig) or []):
                k = (n.get("description") or "", n.get("dispatcher") or "",
                     "" if n.get("dispatcher") == "__lua" else str(n.get("arg", "")))
                if k not in keys:
                    keys.add(k)
                    natives.append(n)
            if not natives:
                continue
            meta = self.actions_catalog.get(b.get("action"), {})
            out.append({
                "combo": combo,
                "action": b.get("action"),
                "name": meta.get("name", b.get("action")),
                "fixed": is_fixed,
                "native": [{"description": n.get("description") or "",
                            "dispatcher": n.get("dispatcher") or "",
                            "arg": "" if n.get("dispatcher") == "__lua" else str(n.get("arg", ""))}
                           for n in natives],
            })
        out.sort(key=lambda e: e["combo"])
        return {"mode": mode, "source": source, "count": len(out), "takeovers": out}

    def _own_filtered_natives(self) -> Dict[Tuple[int, str], List[Dict[str, Any]]]:
        """Live binds minus everything OmniPal injected: the active overlay and the fixed entries,
        plus any bind whose description is one of OmniPal's action names."""
        live = self._native_details(self._get_active_overlay())
        own = {m.get("name") for m in self.actions_catalog.values() if m.get("name")}
        out = {}
        for sig, lst in live.items():
            keep = [n for n in lst if (n.get("description") or "") not in own]
            if keep:
                out[sig] = keep
        return out

    def fixed_combos(self) -> Dict[str, str]:
        return {format_combo(b.get("mod", ""), b["key"]): b["action"] for b in self.fixed_bindings}

    def _without_fixed(self, bindings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Profile bindings minus those on fixed combos (fixed entries always win)."""
        fixed = self.fixed_combos()
        return [b for b in bindings if format_combo(b.get("mod", ""), b.get("key", "")) not in fixed]

    def _without_protected(self, profile_id: str, bindings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Profile bindings minus those on protected system combos.

        `omni-profile import` rejects such profiles outright, but a mode file
        dropped straight into the profiles directory bypasses `import`, so the
        engine itself refuses to install these bindings at switch time: skip
        them with a warning and let the switch continue."""
        try:
            combos = load_protected_combos(self.root_dir)
        except Exception as e:
            # Loud on purpose: silently disabling the filter would leave the
            # Omarchy menu key unprotected with no visible trace.
            print(f"Warning: protected_bindings.json 读取失败（{e}），受保护键位过滤已停用",
                  file=sys.stderr)
            return bindings
        if not combos:
            return bindings
        kept = []
        for b in bindings:
            ck = combo_key(b.get("mod", ""), b.get("key", ""))
            if ck in combos:
                entry = combos[ck]
                allowed = getattr(entry, "allowed_actions", set())
                if b.get("action") in allowed:
                    kept.append(b)
                    continue
                print(f"Warning: skipping protected system key {b.get('mod', '')} {b.get('key', '')} "
                      f"({entry}) from profile '{profile_id}'; it will not be installed",
                      file=sys.stderr)
            else:
                kept.append(b)
        return kept

    def _fixed_bind_ops(self) -> List[str]:
        ops, _records = self._build_bind_ops(self.fixed_bindings)
        return ops

    def apply_fixed_bindings(self) -> bool:
        """(Re-)injects the fixed entry points, e.g. in omarchy mode or after a config reload."""
        ops = self._fixed_bind_ops()
        ok = self._eval_lua("; ".join(ops)) if ops else True
        if ok:
            self.dedupe_binds()
        return ok

    def dedupe_binds(self) -> int:
        """Self-heal: collapse identical duplicate native binds (one Super+Enter must open one
        terminal). Returns how many duplicate copies were found."""
        details = self._live_bind_details()
        dups = sum(find_duplicate_binds([b for lst in details.values() for b in lst]).values())
        if dups:
            ops = _dedupe_binds_lua(details)
            if ops:
                print(f"⚠️ Collapsing {dups} duplicate key binds", file=sys.stderr, flush=True)
                self._eval_lua("; ".join(ops))
        return dups

    def _reinject_active_bindings(self, target_mode: str) -> bool:
        """Re-applies the active overlay bindings into Hyprland (e.g. after a config reload)."""
        if target_mode not in self.profiles or target_mode == "omarchy":
            return self.apply_fixed_bindings()
        target_profile = self.profiles[target_mode]
        target_bindings = self._without_fixed(target_profile.get("bindings", []))
        # Same guard as switch_mode(): never re-install a protected combo.
        target_bindings = self._without_protected(target_mode, target_bindings)
        # Called after a config reload: the overlay is gone and natives are back, so live == native.
        live = self._live_bind_counts()
        lua_ops, new_overlay_records = self._build_bind_ops(target_bindings, live, self._live_bind_details())
        if lua_ops:
            lua_ops.insert(0, 'debug.getregistry().omnipal_stash = nil')
        lua_ops.extend(self._fixed_bind_ops())

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
        monitor: Optional[Union[int, str, Dict[str, Any]]] = None,
        keep_size: bool = False,
        orig_size: Optional[List[int]] = None,
    ):
        """Applies mature golden dimensions (0.618 x 0.70) and terraced cascading placement to a floating window.

        keep_size=True only floats the window (no resize/move/center): used for OWN_SIZE_CLASSES
        (scrcpy etc.). New ordinary windows get the full golden cascade (no orig_size). Existing
        tiled windows being floated pass orig_size so they never grow beyond their previous size."""
        if keep_size:
            # Float only: never resize or move (the app or the user's script sized/placed it).
            self._eval_lua(f'hl.dispatch(hl.dsp.window.float({{ action = "enable", window = "address:{_escape_lua_string(addr)}" }}))')
            return
        try:
            ow, oh = int(orig_size[0]), int(orig_size[1])  # type: ignore[index]
        except Exception:
            ow, oh = 0, 0
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
local orig_w, orig_h = {ow}, {oh}

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
    -- Cap only for existing tiled windows being floated (orig_* set); new windows get golden size
    if orig_w > 0 and orig_w < gw then gw = orig_w end
    if orig_h > 0 and orig_h < gh then gh = orig_h end

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

    def _load_floated_addrs(self) -> set:
        try:
            if FLOATED_BY_OMNIPAL_FILE.exists():
                data = json.loads(FLOATED_BY_OMNIPAL_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return {str(a) for a in data if a}
        except Exception as e:
            _debug(e)
        return set()

    def _save_floated_addrs(self, addrs) -> None:
        self._ensure_run_dir()
        try:
            atomic_write_json(FLOATED_BY_OMNIPAL_FILE, sorted(str(a) for a in addrs if a))
        except Exception as e:
            _debug(e)

    def _remember_floated(self, addr: str) -> None:
        if not addr:
            return
        addrs = self._load_floated_addrs()
        if addr not in addrs:
            addrs.add(addr)
            self._save_floated_addrs(addrs)

    def _clear_floated(self) -> None:
        self._save_floated_addrs([])

    @staticmethod
    def keeps_own_size(cls_name: str, floating: bool = False) -> bool:
        """Windows the floating policy must not resize: already floating, or apps that pick their
        own size/aspect ratio (scrcpy phone mirrors, video/image viewers)."""
        if floating:
            return True
        c = str(cls_name or "").lower()
        return any(c == k or c.startswith(k) for k in OWN_SIZE_CLASSES)

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

                if self.keeps_own_size(cls_name, bool(c.get("floating"))):
                    # Already floating: leave alone (was floating before OmniPal). OWN_SIZE tiled:
                    # float without resize; don't track so returning to tiled leaves them alone.
                    if not c.get("floating"):
                        self._apply_golden_cascade_geometry(addr, is_dialog=is_dlg, monitor=mon, keep_size=True)
                    continue
                self._apply_golden_cascade_geometry(addr, step=step, is_dialog=is_dlg, monitor=mon, orig_size=size)
                if not is_dlg:
                    self._remember_floated(addr)
                    step = (step + 1) % 6
        except Exception as _e:
            # Broad: per-window cascade geometry is best-effort; one bad
            # window must not abort the whole pass.
            _debug(f"cascade geometry failed for a window: {_e}")

    def _unfloat_existing_windows(self):
        """Unfloats floating client windows on every regular workspace when returning to tiled mode."""
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
            except (OSError, ValueError, subprocess.SubprocessError) as _e:
                _debug(f"monitors query failed: {_e}")

            if not active_ws_ids:
                try:
                    _ensure_hyprland_instance()
                    act_out = subprocess.check_output(["hyprctl", "activeworkspace", "-j"], text=True, timeout=0.5)
                    act = json.loads(act_out)
                    if "id" in act:
                        active_ws_ids.add(act["id"])
                except (OSError, ValueError, subprocess.SubprocessError) as _e:
                    _debug(f"activeworkspace query failed: {_e}")

            # Only windows OmniPal floated (tracked when we cascaded them). Windows that were
            # already floating before the policy, OWN_SIZE apps, dialogs and specials stay floating.
            owned = self._load_floated_addrs()
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

                if ws_name.startswith("special") or (isinstance(ws_id, int) and ws_id < 0):
                    continue

                addr = c.get("address")
                if not addr or addr not in owned:
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
                if self.keeps_own_size(cls_name):
                    print(f"unfloat skip {addr} {cls_name!r} own-size app", file=sys.stderr)
                    continue
                if skip or is_dlg:
                    print(f"unfloat skip {addr} {cls_name!r} special={skip} dialog={is_dlg}", file=sys.stderr)
                    continue

                to_unfloat.append(addr)

            if not to_unfloat:
                self._clear_floated()
                return

            lua_ops = []
            for addr in to_unfloat:
                esc_addr = _escape_lua_string(addr)
                lua_ops.append(
                    f'if type(hl) == "table" and type(hl.dispatch) == "function" and type(hl.dsp) == "table" and type(hl.dsp.window) == "table" then '
                    f'hl.dispatch(hl.dsp.window.float({{ action = "off", window = "address:{esc_addr}" }})) end'
                )
            print(f"unfloat {to_unfloat}", file=sys.stderr)
            ok = self._eval_lua_strict("; ".join(lua_ops))
            if not ok:
                for addr in to_unfloat:
                    try:
                        _ensure_hyprland_instance()
                        subprocess.run(
                            ["hyprctl", "dispatch", "settiled", f"address:{addr}"],
                            capture_output=True,
                            timeout=0.5
                        )
                    except (OSError, subprocess.SubprocessError) as _e:
                        _debug(f"settiled failed for {addr}: {_e}")
            # Drop the ones we tiled; leave any remaining owned addresses (gone windows)
            # cleared so a later floating session starts clean.
            self._clear_floated()
        except (OSError, subprocess.SubprocessError) as e:
            print(f"unfloat failed: {e}", file=sys.stderr)

    def get_active_workspace_info(self) -> Dict[str, Any]:
        """Queries the active workspace from Hyprland safely."""
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(["hyprctl", "activeworkspace", "-j"], capture_output=True, text=True, check=False, timeout=0.5)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                return data if isinstance(data, dict) else {}
        except (OSError, ValueError, subprocess.SubprocessError) as _e:
            _debug(f"activeworkspace query failed: {_e}")
        return {}

    def get_workspace_layout(self, ws_id: Optional[str] = None) -> str:
        """Returns the current workspace layout mode via Omarchy 4.5 CLI or general.layout fallback."""
        if shutil.which("omarchy-hyprland-workspace-layout-current"):
            try:
                cmd = ["omarchy-hyprland-workspace-layout-current"]
                if ws_id:
                    cmd.append(str(ws_id))
                res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=0.5)
                layout = _validated_workspace_layout(res.stdout.strip())
                if layout:
                    return layout
            except (OSError, subprocess.SubprocessError) as _e:
                _debug(f"workspace layout query failed: {_e}")
        return "dwindle"

    def _workspace_layouts_dir(self) -> Path:
        """Omarchy's per-workspace layout state directory (single source for the path).

        An empty XDG_STATE_HOME counts as unset; honoring it literally would
        produce a relative path and scatter state files into the CWD."""
        xdg_state = os.environ.get("XDG_STATE_HOME")
        base = Path(xdg_state) if xdg_state else Path.home() / ".local" / "state"
        return base / "omarchy" / "workspace-layouts"

    def _write_workspace_layout_file(self, ws_id: str, mode: str) -> None:
        """Atomically records one workspace's layout in Omarchy's state file.

        Both values are allowlist-validated first: the file is later executed
        as Lua by Omarchy, so unvalidated content would be code injection."""
        layout = _validated_workspace_layout(mode)
        if not _is_valid_workspace_id(ws_id) or not layout:
            return
        try:
            modes_dir = self._workspace_layouts_dir()
            modes_dir.mkdir(parents=True, exist_ok=True)
            mode_file = modes_dir / f"{ws_id}.lua"
            tmp_file = mode_file.with_name(f"{mode_file.name}.{os.getpid()}.tmp")
            tmp_file.write_text(f'o.workspace_mode({{ workspace = "{ws_id}", mode = "{layout}" }})\n', encoding="utf-8")
            tmp_file.replace(mode_file)
        except OSError as _e:
            _debug(f"Failed to write workspace layout file for {ws_id}: {_e}")

    def _sync_workspace_layout_file(self, ws_id: str, layout: str, default_layout: str) -> None:
        """Mirrors a restored layout to its state file: the default layout is
        represented by the absence of a file, anything else is written."""
        if not _is_valid_workspace_id(ws_id):
            return
        if layout == default_layout:
            try:
                mode_file = self._workspace_layouts_dir() / f"{ws_id}.lua"
                if mode_file.exists():
                    mode_file.unlink()
            except OSError as _e:
                _debug(f"Failed to remove workspace layout file for {ws_id}: {_e}")
        else:
            self._write_workspace_layout_file(ws_id, layout)

    def _current_workspace_layout(self, ws_id: str) -> str:
        """The workspace's layout before OmniPal touches it, from Omarchy's
        state file first, then its CLI; "" when neither reports a valid one."""
        mode_file = self._workspace_layouts_dir() / f"{ws_id}.lua"
        if mode_file.exists():
            try:
                m = re.search(r'mode\s*=\s*"([a-z]+)"', mode_file.read_text(encoding="utf-8"))
                if m:
                    layout = _validated_workspace_layout(m.group(1))
                    if layout:
                        return layout
            except OSError:
                pass
        if shutil.which("omarchy-hyprland-workspace-layout-current"):
            try:
                res = subprocess.run(["omarchy-hyprland-workspace-layout-current", ws_id], capture_output=True, text=True, timeout=0.5, check=False)
                if res.returncode == 0:
                    layout = _validated_workspace_layout(res.stdout.strip())
                    if layout:
                        return layout
            except (OSError, subprocess.SubprocessError):
                pass
        return _validated_workspace_layout(self.get_workspace_layout(ws_id))

    def _default_workspace_layout(self) -> str:
        """Omarchy's default workspace layout, allowlist-validated."""
        if shutil.which("omarchy-hyprland-workspace-layout-default"):
            try:
                res = subprocess.run(["omarchy-hyprland-workspace-layout-default"], capture_output=True, text=True, timeout=0.5, check=False)
                if res.returncode == 0:
                    layout = _validated_workspace_layout(res.stdout.strip())
                    if layout and layout != "floating":
                        return layout
            except (OSError, subprocess.SubprocessError):
                pass
        return "dwindle"

    def _save_workspace_layouts_state(self) -> None:
        """Persists the saved workspace layouts to STATE_FILE atomically.

        Creates the state file when it does not exist yet (previously the
        records were silently dropped in that case), preserving any other
        state keys already stored in it."""
        data: Dict[str, Any] = {}
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, ValueError) as _e:
                _debug(f"Failed to read state before persisting saved_workspace_layouts: {_e}")
                return
        data["saved_workspace_layouts"] = _sanitize_saved_workspace_layouts(self._saved_workspace_layouts)
        if not atomic_write_json(STATE_FILE, data):
            _debug("Failed to persist saved_workspace_layouts")

    def _ensure_hyprbars_if_floating(self) -> None:
        """Ensures the hyprbars plugin is loaded when floating layout is applied.

        Uses a config-only reload: a full `hyprctl reload` wipes OmniPal's
        injected binds and relies on the daemon noticing the reload to put
        them back (with no daemon running, the binds are simply lost)."""
        if not shutil.which("hyprctl"):
            return
        try:
            res = subprocess.run(["hyprctl", "plugin", "list", "-j"], capture_output=True, text=True, timeout=0.5, check=False)
            if res.returncode == 0 and res.stdout.strip():
                plugins = json.loads(res.stdout)
                has_hyprbars = any(p.get("name") == "hyprbars" for p in plugins if isinstance(p, dict))
                if not has_hyprbars:
                    self._reload_config_only()
        except (OSError, ValueError, subprocess.SubprocessError) as _e:
            _debug(f"check hyprbars failed: {_e}")

    def _apply_window_policy(self, force: bool = False) -> bool:
        """Applies the current effective window policy (tiled vs floating) to Hyprland."""
        _ensure_hyprland_instance()
        sock = find_socket2_path()
        if not sock or not sock.exists():
            return True

        target_mode = self.get_effective_window_mode()
        cur_applied = self._get_applied_window_mode()

        ws_info = self.get_active_workspace_info()
        ws_id = str(ws_info.get("id", "")) if ws_info else ""
        valid_ws = _is_valid_workspace_id(ws_id)

        if target_mode == "floating":
            if not force and cur_applied == "floating":
                return True
            if valid_ws and ws_id not in self._saved_workspace_layouts:
                # Record the layout to restore when switching back to tiled.
                # A workspace that was already floating (e.g. the user set it
                # with Super+L) is NOT recorded: it was floating before
                # OmniPal and must stay floating afterwards.
                cur_layout = self._current_workspace_layout(ws_id)
                if cur_layout and cur_layout != "floating":
                    self._saved_workspace_layouts[ws_id] = cur_layout
                    self._save_workspace_layouts_state()

            # Rules are kept in the Lua registry so tiled mode can disable them without a reload.
            lua_code = (
                'local R = debug.getregistry(); '
                'local used_omarchy_mode = false; '
                'if type(o) == "table" and type(o.workspace_mode) == "function" then '
                '  local ws = (type(hl) == "table" and type(hl.get_active_workspace) == "function") and hl.get_active_workspace() or nil; '
                '  if ws and ws.id and tonumber(ws.id) and tonumber(ws.id) >= 1 then '
                '    o.workspace_mode({ workspace = tostring(ws.id), mode = "floating" }); '
                '    used_omarchy_mode = true '
                '  end '
                'end; '
                'R.omnipal_used_omarchy_mode = used_omarchy_mode; '
                'if not used_omarchy_mode then '
                '  if R.omnipal_float_rules then '
                '    for _, r in ipairs(R.omnipal_float_rules) do r:set_enabled(true) end '
                '  elseif type(hl) == "table" and type(hl.window_rule) == "function" then '
                '    R.omnipal_float_rules = { '
                '      hl.window_rule({ match = {}, float = true }), '
                '      hl.window_rule({ match = { class = ".*" }, float = true }), '
                '      hl.window_rule({ match = { tag = "chromium-based-browser" }, float = true }), '
                '      hl.window_rule({ match = { tag = "terminal" }, float = true }) } '
                '  elseif type(o) == "table" and type(o.window) == "function" then '
                '    o.window(".*", { float = true }); '
                '    o.window({ tag = "chromium-based-browser" }, { float = true }); '
                '    o.window({ tag = "terminal" }, { float = true }) '
                '  end '
                'end'
            )
            ok = self._eval_lua(lua_code)
            if ok:
                if cur_applied != "floating":
                    self._clear_floated()
                self._set_applied_window_mode("floating")
                self._float_existing_windows()
                if valid_ws:
                    self._write_workspace_layout_file(ws_id, "floating")
                    self._ensure_hyprbars_if_floating()
                self._notify_omarchy_layout()
            return ok
        else:
            # target_mode == "tiled"
            if not force and cur_applied != "floating":
                return True
            reloaded = self._disable_float_rules()
            if reloaded is None:
                return False
            self._unfloat_existing_windows()
            self._set_applied_window_mode("tiled")
            self._notify_omarchy_layout()
            if not reloaded:
                return True

            st = self.get_state()
            active_m = st.get("mode", "omarchy")
            if active_m != "omarchy":
                self._reinject_active_bindings(active_m)
            return True

    def _disable_float_rules(self) -> Optional[bool]:
        """Turns the floating rules off and restores every workspace layout
        OmniPal previously floated. Returns False if done in place (no
        reload), True if it had to fall back to a config-only reload (Lua
        state rebuilt), None if both failed.

        Restoration is driven by _saved_workspace_layouts, NOT by whichever
        workspace happens to be active now: floating may have been applied
        on workspace 1 while the user has since moved to workspace 2, and a
        workspace with no record (e.g. one the user set to scrolling with
        Super+L in the meantime) must be left completely alone."""
        default_mode = self._default_workspace_layout()
        restores = _sanitize_saved_workspace_layouts(self._saved_workspace_layouts)

        restore_calls = " ".join(
            f'o.workspace_mode({{ workspace = "{ws_id}", mode = "{layout}" }});'
            for ws_id, layout in sorted(restores.items(), key=lambda kv: int(kv[0]))
        )
        lua = (
            'local R = debug.getregistry(); '
            + (f'if type(o) == "table" and type(o.workspace_mode) == "function" then {restore_calls} end; ' if restore_calls else '')
            + 'local t = R.omnipal_float_rules; '
            'if t then '
            '  for _, r in ipairs(t) do r:set_enabled(false) end '
            'end'
        )
        ok = self._eval_lua_strict(lua)
        if ok:
            # Only persist the restore once it actually took effect: a
            # layout that was never applied must not be saved (Omarchy's own
            # tools follow the same rule).
            for ws_id, layout in restores.items():
                self._sync_workspace_layout_file(ws_id, layout, default_mode)
            self._saved_workspace_layouts.clear()
            self._save_workspace_layouts_state()
            self._notify_omarchy_layout()
            return False
        print("Disabling float rules in place failed; falling back to config reload", file=sys.stderr)
        # The reload re-reads the per-workspace state files, so they have to
        # be synced first — but if the reload fails too, roll the files back
        # so a restore that never took effect is not left saved on disk.
        layouts_dir = self._workspace_layouts_dir()
        previous_files: Dict[str, Optional[str]] = {}
        for ws_id in restores:
            mode_file = layouts_dir / f"{ws_id}.lua"
            try:
                previous_files[ws_id] = mode_file.read_text(encoding="utf-8") if mode_file.exists() else None
            except OSError:
                previous_files[ws_id] = None
        for ws_id, layout in restores.items():
            self._sync_workspace_layout_file(ws_id, layout, default_mode)
        if self._reload_config_only():
            self._saved_workspace_layouts.clear()
            self._save_workspace_layouts_state()
            self._notify_omarchy_layout()
            return True
        for ws_id, previous in previous_files.items():
            mode_file = layouts_dir / f"{ws_id}.lua"
            try:
                if previous is None:
                    mode_file.unlink(missing_ok=True)
                else:
                    mode_file.write_text(previous, encoding="utf-8")
            except OSError as _e:
                _debug(f"Failed to roll back workspace layout file for {ws_id}: {_e}")
        return None

    def _notify_omarchy_layout(self) -> None:
        """Notifies Omarchy shell to refresh dock and workspaces widgets if available."""
        if shutil.which("omarchy-shell"):
            try:
                subprocess.run(["omarchy-shell", "-q", "omarchy.workspaces", "refresh"], capture_output=True, timeout=0.3, check=False)
                subprocess.run(["omarchy-shell", "-q", "omarchy.dock", "refresh"], capture_output=True, timeout=0.3, check=False)
            except (OSError, subprocess.SubprocessError) as _e:
                _debug(f"omarchy-shell layout refresh failed: {_e}")

    def get_effective_window_mode(self, mode: Optional[str] = None, policy: Optional[str] = None) -> str:
        pol = normalize_window_policy(policy) or self.get_window_policy()
        if pol == "follow-profile":
            if mode is None:
                cur_m = (self.get_state().get("mode") if hasattr(self, "get_state") else "omarchy")
            else:
                cur_m = mode
            m = str(cur_m).lower().strip()
            prof = getattr(self, "profiles", {}).get(m) or {}
            wm = prof.get("window_mode")
            if wm in ("floating", "tiled"):
                return wm
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
            except (OSError, ValueError) as _e:
                _debug(_e)
        return normalize_window_policy(getattr(self, "window_policy", None)) or "follow-profile"

    def profile_window_mode(self, mode_id: Any) -> str:
        """The mode's own window_mode (tiled/floating), ignoring the global policy."""
        m = str(mode_id).lower().strip()
        prof = getattr(self, "profiles", {}).get(m) or {}
        wm = prof.get("window_mode")
        if wm in ("floating", "tiled"):
            return wm
        return "floating" if m == "mac" else "tiled"

    def window_modes_by_profile(self) -> Dict[str, str]:
        """Each mode's own window_mode (tiled/floating), before any global override."""
        return {pid: self.profile_window_mode(pid) for pid in self.profiles}

    def set_window_policy(self, policy: str, source: str = "unspecified") -> bool:
        """Sets the global window policy. Only explicit user choices may call this (CLI
        `window-policy set`, bar menu, settings panel) or the startup restore of that choice."""
        with engine_lock():
            norm = normalize_window_policy(policy)
            if not norm:
                return False
            previous_policy = self.get_window_policy()
            log_policy_write("state", previous_policy, norm, source)
            self.window_policy = norm
            cur_state = self.get_state()
            cur_mode = cur_state.get("mode", "omarchy")
            count = cur_state.get("active_bindings_count", 0)
            self._write_state(cur_mode, count, policy=norm)
            try:
                applied = self._apply_window_policy(force=True)
            except Exception as e:
                # Broad: any unexpected failure here must roll back to the
                # previous policy instead of leaving a half-applied one.
                print(f"Warning: Failed to apply window policy '{norm}': {e}", file=sys.stderr)
                applied = False
            if not applied:
                self.window_policy = previous_policy
                self._write_state(cur_mode, count, policy=previous_policy)
                print(f"Warning: Compositor rejected window policy '{norm}'; previous policy restored", file=sys.stderr)
                return False
            if self.get_persistence_status()["enabled"]:
                self.set_persistence(True, window_policy=norm, source=source)
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
        except Exception as _e:
            # Broad: get_state() feeds `omni-profile status` and must never
            # crash; fall back to the default state below.
            _debug(f"get_state failed, returning default: {_e}")
            return default_state

    def _resolve_auto(self, mode: str, auto: Any) -> Optional[Dict[str, Any]]:
        if auto is _KEEP:
            prev = self.get_state().get("auto")
            return prev if isinstance(prev, dict) and prev.get("mode") == mode else None
        return auto or None

    def _write_state(self, mode: str, count: int, policy: Optional[str] = None, auto: Any = _KEEP):
        auto = self._resolve_auto(mode, auto)
        self._ensure_run_dir()
        profile_data = self.profiles.get(mode, {})
        profile_name = profile_data.get("name", mode)
        display_meta = profile_data.get("display", {})
        daemon_pid = None
        if PID_FILE.exists():
            try:
                daemon_pid = int(PID_FILE.read_text().strip())
            except (OSError, ValueError) as _e:
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
                except (OSError, ValueError) as _e:
                    _debug(_e)
            if not cur_policy:
                cur_policy = normalize_window_policy(getattr(self, "window_policy", None)) or "follow-profile"

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
            "saved_workspace_layouts": self._saved_workspace_layouts,
        }
        if auto:
            # Set only while an app rule switched the mode: {app, mode, return_to, since}
            state_data["auto"] = auto
        write_state_json(STATE_FILE, state_data)
        if not compositor_mutation_disabled():
            try:
                subprocess.Popen(
                    ["omarchy-shell", "-q", "omni.mode-indicator", "refresh"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError) as _e:
                # Best-effort UI refresh; the state write above already succeeded.
                _debug(f"mode-indicator refresh failed: {_e}")


    def _get_active_overlay(self) -> List[Dict[str, str]]:
        if not OVERLAY_FILE.exists():
            return []
        try:
            with open(OVERLAY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError) as _e:
            _debug(f"ignoring unreadable overlay file: {_e}")
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
            except (OSError, ValueError) as _e:
                _debug(f"ignoring unreadable baseline file: {_e}")
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
        except (OSError, ValueError, subprocess.SubprocessError) as _e:
            _debug(f"baseline binds query failed: {_e}")
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
            key = bind_key_name(b)
            if not key or b.get("submap") or b.get("mouse") or b.get("release"):
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

    def _build_dynamic_restore_lua(self, filter_combos: Optional[Set[str]] = None,
                                   native_counts: Optional[Dict[Tuple[int, str], int]] = None) -> Optional[str]:
        """Builds Lua statements to restore the exact captured baseline bindings.
        If filter_combos is specified, only restores bindings for those combos.

        Idempotent: a combo whose native is still live (per native_counts, i.e. live binds minus
        OmniPal's overlay) is skipped; with no live bind table every rebind is unbind-then-bind,
        so re-running restore never stacks a second copy of a native bind."""
        counts_known = bool(native_counts)
        native_counts = native_counts or {}
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
            if counts_known:
                if native_counts.get(combo_signature(combo), 0) > 0:
                    continue
            else:
                lua_ops.append(f'hl.unbind("{esc_combo}")')

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

    def restore(self, auto: Any = _KEEP, *, sync_persistence: bool = True) -> bool:
        """Restores Hyprland keybindings by unbinding all currently injected overlays and re-registering baseline.

        When persistence is enabled, a successful user-facing restore mirrors profile "omarchy"
        into persistence.json (same as switch/cycle). Pass sync_persistence=False for daemon
        shutdown cleanup so exiting does not overwrite the last chosen profile.
        """
        with engine_lock():
            auto = self._resolve_auto("omarchy", auto)
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
            # Only natives our overlay displaced were ever unbound: replay exactly those. Natives
            # we never touched are still bound (code:NN binds even show key ""/keycode 0 in
            # hyprctl, so a live check can't vouch for them) and replaying them stacks copies.
            displaced = {b.get("combo") for b in active_overlay if b.get("native_unbound") and b.get("combo")}
            replay = displaced - stashed
            native_counts = self._native_counts(active_overlay)
            if replay:
                dynamic_lua = self._build_dynamic_restore_lua(filter_combos=replay, native_counts=native_counts)
                if dynamic_lua:
                    lua_lines.append(dynamic_lua)
                elif not self.baseline_bindings:
                    lua_lines.append(LUA_RESTORE_BASELINE)

            lua_lines.extend(self._fixed_bind_ops())
            success = self._eval_lua("; ".join(lua_lines))

            # Never discard the active overlay while the compositor still reports a failure.
            # Keeping it allows a later daemon reconnect or explicit retry to finish Restore.
            if not success:
                print("Warning: Restore evaluation failed; retaining active overlay for retry", file=sys.stderr)
                return False

            policy_restored = True
            config_reloaded = False
            if self._get_applied_window_mode() == "floating" and self.get_effective_window_mode("omarchy") != "floating":
                res = self._disable_float_rules()
                policy_restored = res is not None
                config_reloaded = bool(res)
                if policy_restored:
                    self._unfloat_existing_windows()
                    self._set_applied_window_mode("tiled")
                    self._notify_omarchy_layout()
                    self._saved_workspace_layouts.clear()
            if not policy_restored:
                print("Warning: Restore window policy reload failed; retaining active overlay for retry", file=sys.stderr)
                return False

            try:
                if OVERLAY_FILE.exists():
                    OVERLAY_FILE.unlink()
            except OSError:
                pass  # best-effort cleanup

            self._write_state("omarchy", 0, auto=auto)
            # State is already "omarchy", so the reload watcher won't re-apply an overlay.
            # Natives we unbound are rebound from the Lua stash; reload only if that isn't possible.
            unbound = [b for b in active_overlay if b.get("native_unbound")]
            ok = True
            if not unbound:
                ok = True
            elif config_reloaded:
                # A config reload above rebuilt the Lua state: natives are back and the stash is gone.
                ok = self.apply_fixed_bindings()
            elif all(b.get("native_restorable", False) for b in unbound):
                restore_ops = [_native_unstash_lua(
                                   b["combo"],
                                   native_counts.get(combo_signature(b["combo"]), 0) if native_counts else None)
                               for b in unbound
                               if b.get("native_count", 0) > 0]
                if not restore_ops or self._eval_lua_strict("; ".join(restore_ops)):
                    ok = True
                else:
                    print("Native rebind from stash failed; falling back to hyprctl reload", file=sys.stderr)
                    ok = self._reload_hyprland() and self.apply_fixed_bindings()
            else:
                if not self._reload_hyprland():
                    ok = False
                else:
                    ok = self.apply_fixed_bindings()

            # CLI / bar / settings / IPC restore paths share this method; keep persistence.json
            # aligned with the live mode the same way switch_mode and cycle_mode do.
            if ok:
                self.dedupe_binds()
            if ok and sync_persistence and self.get_persistence_status()["enabled"]:
                self.set_persistence(True, profile="omarchy")
            return ok

    def _reload_hyprland(self) -> bool:
        if compositor_mutation_disabled():
            return True
        try:
            _ensure_hyprland_instance()
            res = subprocess.run(["hyprctl", "reload"], capture_output=True, text=True, check=False)
            return res.returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            print(f"hyprctl reload failed: {e}", file=sys.stderr)
            return False

    def send_shortcut(self, spec: str, window_class: Optional[str] = None) -> bool:
        """Forwards a shortcut to the focused window, adjusted for terminals."""
        tags = []
        if window_class is None:
            window_class = ""
            try:
                _ensure_hyprland_instance()
                res = subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True, text=True, check=False)
                win_data = json.loads(res.stdout or "{}") or {}
                window_class = win_data.get("class", "") or ""
                tags = win_data.get("tags", []) or []
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                _debug(e)
        try:
            mods, key = forward_for_class(spec, window_class, tags=tags)
        except ValueError as e:
            print(f"Invalid shortcut: {e}", file=sys.stderr)
            return False
        arg = f"{' '.join(mods)}, {key}, activewindow"
        _ensure_hyprland_instance()
        res = subprocess.run(["hyprctl", "dispatch", "sendshortcut", arg], capture_output=True, text=True, check=False)
        return res.returncode == 0 and "error" not in (res.stdout or "").lower()

    def switch_mode(self, target_mode: str, _rollback: bool = False, auto: Any = _KEEP) -> bool:
        """Atomically switches the in-memory keybindings to target_mode with rollback on error."""
        with engine_lock():
            target_mode = target_mode.lower().strip()
            if target_mode in RETIRED_MODES and target_mode not in self.profiles:
                valid_modes = ", ".join(self.profiles.keys())
                raise ValueError(f"Mode '{target_mode}' has been removed. Valid modes: {valid_modes}")
            if target_mode not in self.profiles:
                valid_modes = ", ".join(self.profiles.keys())
                raise ValueError(f"Unknown mode '{target_mode}'. Available modes: {valid_modes}")

            # Switching to omarchy mode means clearing all overlays and restoring system baseline
            if target_mode == "omarchy":
                ok = self.restore(auto=auto)
                if ok and self.get_persistence_status()["enabled"]:
                    self.set_persistence(True, profile="omarchy")
                return ok

            previous_mode = self.get_state().get("mode", "omarchy")
            auto = self._resolve_auto(target_mode, auto)
            target_profile = self.profiles[target_mode]
            # Fixed entry points (schema/fixed_bindings.json) always win over profile bindings.
            target_bindings = self._without_fixed(target_profile.get("bindings", []))
            # Protected system combos (schema/protected_bindings.json) are never
            # installed, even from a mode file dropped in without `import`.
            target_bindings = self._without_protected(target_mode, target_bindings)

            # A previous overlay that unbound natives needs a restore first (exact rebind, reload only as fallback)
            if any(b.get("native_unbound") for b in self._get_active_overlay()):
                if not self.restore():
                    return False

            # Ensure baseline snapshot is captured before any new overlay is applied
            if not self.baseline_bindings:
                self._snapshot_baseline_bindings()

            # Stage 1: Unbind previous overlay
            current_overlay = self._get_active_overlay()
            # Native binds = live binds minus those our current overlay injected.
            native_counts = self._native_counts(current_overlay)
            native_details = self._native_details(current_overlay)
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
                    dynamic_lua = self._build_dynamic_restore_lua(filter_combos=released_combos,
                                                                  native_counts=native_counts)
                    if dynamic_lua:
                        lua_ops.append(dynamic_lua)


            # Stage 3: Unbind-before-bind for every target combo (incl. forwarded shortcuts)
            bind_ops, new_overlay_records = self._build_bind_ops(target_bindings, native_counts, native_details)
            lua_ops.extend(bind_ops)
            lua_ops.extend(self._fixed_bind_ops())

            # Execute batch in single eval call (< 5ms)
            success = self._eval_lua("; ".join(lua_ops))

            if success:
                self.dedupe_binds()
                self._write_active_overlay(new_overlay_records)
                self._write_state(target_mode, len(new_overlay_records), auto=auto)
                # Configuration persistence: mirror the successful switch when persistence is enabled.
                if self.get_persistence_status()["enabled"]:
                    self.set_persistence(True, profile=target_mode)
                try:
                    self._apply_window_policy()
                except Exception as _e:
                    # Broad: the mode switch already succeeded; a policy
                    # failure must not fail the switch, just stay visible.
                    _debug(f"post-switch window-policy apply failed: {_e}")
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
                    if not self.switch_mode(previous_mode, _rollback=True):
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
        except (OSError, ValueError, subprocess.SubprocessError) as _e:
            _debug(f"overlay verification query failed: {_e}")
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
                    rules = []
                    for r in raw.get("rules", []):
                        if not (isinstance(r, dict) and r.get("class") and r.get("mode")):
                            continue
                        if r.get("match") == "regex":
                            try:
                                validate_app_rule_pattern(r["class"])
                            except ValueError as e:
                                # Hand-edited or legacy rule files bypass the
                                # save-time gate; skip the rule here so a bad
                                # regex can never reach the matcher and hang the
                                # daemon. doctor() reports these via
                                # invalid_app_rules().
                                _debug(f"skipping app rule with unsafe regex {r.get('class')!r}: {e}")
                                continue
                        rules.append(r)
                    data["rules"] = rules
            except (OSError, ValueError) as e:
                print(f"Warning: Failed to read app rules {path}: {e}", file=sys.stderr)
        return data

    def invalid_app_rules(self) -> List[Dict[str, str]]:
        """Rules in the on-disk file that load_app_rules() skips for unsafe regex.
        Returns [{class, reason}]; used by doctor() to report them."""
        path = app_rules_file_path()
        out: List[Dict[str, str]] = []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return out
        if not isinstance(raw, dict):
            return out
        for r in raw.get("rules", []):
            if isinstance(r, dict) and r.get("match") == "regex":
                try:
                    validate_app_rule_pattern(r.get("class"))
                except ValueError as e:
                    out.append({"class": str(r.get("class")), "reason": str(e)})
        return out

    def save_app_rules(self, data: Dict[str, Any]) -> None:
        for r in data.get("rules", []):
            if r.get("mode") not in self.profiles:
                raise ValueError(f"Unknown mode '{r.get('mode')}' in rule for '{r.get('class')}'")
            if r.get("match", "exact") not in ("exact", "prefix", "regex"):
                raise ValueError(f"Invalid match type '{r.get('match')}'")
            if r.get("match") == "regex":
                validate_app_rule_pattern(r["class"])
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
        # Bound the subject handed to user regexes: a hostile rule (or a
        # hostile window class) must not be able to wedge the daemon with
        # backtracking over an unbounded string.
        regex_subject = window_class[:APP_RULE_WINDOW_CLASS_MAX_LEN]
        for r in rules.get("rules", []):
            if not r.get("enabled", True):
                continue
            pat = str(r["class"]).strip()
            kind = r.get("match", "exact")
            try:
                if (kind == "exact" and wc == pat.lower()) or \
                   (kind == "prefix" and wc.startswith(pat.lower())) or \
                   (kind == "regex" and re.search(pat, regex_subject, re.IGNORECASE)):
                    return r
            except re.error as e:
                _debug(e)
        return None

    def mode_display_name(self, mode: Optional[str]) -> str:
        return self.profiles.get(mode or "", {}).get("name", mode or "")

    def cancel_auto(self) -> Optional[Dict[str, Any]]:
        """Manual switch while an app rule is active: drop the auto-return and return the old marker.
        The mode the user picks by hand becomes the new base (what later auto switches return to)."""
        st = self.get_state()
        auto = st.get("auto")
        if not isinstance(auto, dict):
            return None
        mode = st.get("mode", "omarchy")
        self._write_state(mode, int(st.get("active_bindings_count", 0) or 0), auto=None)
        return auto

    def notify_manual_override(self, prev_auto: Optional[Dict[str, Any]], new_mode: str) -> None:
        if not prev_auto:
            return
        notify_user(f"已手动切换到 {self.mode_display_name(new_mode)}",
                    f"已取消自动返回 {self.mode_display_name(prev_auto.get('return_to'))}；"
                    f"{self.mode_display_name(new_mode)} 成为新的基础模式")

    def apply_app_rule(self, window_class: str) -> Optional[str]:
        """Called on focus change. Switches to the rule's mode (marking state["auto"]), or back to
        the remembered return mode when the focused app no longer matches. A manual switch clears
        state["auto"] (see cancel_auto), so the hand-picked mode is the new base.
        Returns the mode switched to, or None if nothing changed."""
        rules = self.load_app_rules()
        rule = self.match_app_rule(window_class, rules)
        st = self.get_state()
        current = st.get("mode", "omarchy")
        auto = st.get("auto") if isinstance(st.get("auto"), dict) else None
        self._write_app_rule_state(window_class, rule)

        if rule is not None:
            target = rule["mode"]
            if target not in self.profiles:
                return None
            if auto and auto.get("mode") == target and current == target:
                return None  # still inside the same rule (e.g. another window of a matching app)
            if not auto and target == current:
                return None  # user is already in that mode by hand: nothing to return to
            base = auto.get("return_to") if auto else current
            return_to = rules.get("default_mode") or base
            if return_to not in self.profiles:
                return_to = base
            new_auto = {
                "app": window_class, "mode": target, "return_to": return_to,
                "since": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            ok = self.switch_mode(target, auto=new_auto)
            if ok:
                notify_user(f"因为聚焦了 {window_class}，切到 {self.mode_display_name(target)}",
                            f"离开后回到 {self.mode_display_name(return_to)}")
            return target if ok else None

        if not auto:
            return None
        target = auto.get("return_to") or current
        if target not in self.profiles or target == current:
            self.cancel_auto()
            return None
        ok = self.switch_mode(target, auto=None)
        if ok:
            notify_user(f"离开了 {auto.get('app', '')}，回到 {self.mode_display_name(target)}")
        return target if ok else None

    def _write_app_rule_state(self, window_class: str, rule: Optional[Dict[str, Any]]) -> None:
        """Broadcasts the currently matched rule for the settings UI and cheat sheet."""
        try:
            self._ensure_run_dir()
            tmp = APP_RULE_STATE_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"window_class": window_class, "rule": rule}, f, ensure_ascii=False)
            tmp.replace(APP_RULE_STATE_FILE)
        except (OSError, ValueError, TypeError) as e:
            _debug(e)

    def _pretty_forward_target(self, spec: str) -> str:
        """'CTRL W' -> 'Ctrl+W' for cheatsheet display; falls back to raw."""
        try:
            mods, key = parse_forward(spec)
        except ValueError:
            return str(spec)
        return "+".join([m.capitalize() for m in mods] + [key])

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
            # Binding-level display name override (optional "name" in the
            # profile). forward_shortcut falls back to its target combo so
            # that 19 identical 「转发快捷键到应用」 rows stay distinguishable.
            name = b.get("name")
            if action_id == FORWARD_ACTION and b.get("forward"):
                target = self._pretty_forward_target(b["forward"])
                name = f"{name}（发送 {target}）" if name else f"转发为 {target}"
            if not name:
                name = action_meta.get("name", action_id)
            sheet.append({
                "action": action_id,
                "key": combo,
                "name": name,
                "category": action_meta.get("category", "other"),
                "description": action_meta.get("description", "")
            })
        # Fixed entry points are live in every mode (incl. Omarchy 原生模式).
        # A fixed combo always wins: a profile row on the very same keys is
        # dropped so the fixed entry is never shadowed.
        fixed = self.fixed_combos()
        sheet = [e for e in sheet if e["key"] not in fixed]
        for b in self.fixed_bindings:
            meta = self.actions_catalog.get(b["action"], {})
            combo = format_combo(b.get("mod", ""), b["key"])
            sheet.append({
                "action": b["action"],
                "key": combo,
                # Canonical fixed combo, kept verbatim even when this row is
                # merged with a mode-specific alias row: the onboarding guide
                # must show only the fixed combo, never the merged list.
                "fixed_key": combo,
                "name": meta.get("name", b["action"]),
                "category": "omnipal",
                "description": "固定入口：所有模式通用",
                "fixed": True,
            })
        # One action on several combos (profile alias + fixed entry) merges
        # into a single row listing every combo, e.g. "SUPER+slash / SUPER+ALT+slash".
        # Grouped by (action, name): forward_shortcut rows each carry their own
        # meaning ("关闭标签页", "新建标签页", …) and must NOT collapse into one.
        merged: List[Dict[str, Any]] = []
        by_action: Dict[tuple, Dict[str, Any]] = {}
        for e in sheet:
            g = by_action.get((e["action"], e["name"]))
            if g is None:
                e = dict(e)
                e["keys"] = [e["key"]]
                by_action[(e["action"], e["name"])] = e
                merged.append(e)
                continue
            if e["key"] not in g["keys"]:
                g["keys"].append(e["key"])
            # A fixed entry is canonical: keep its metadata on the merged row.
            # fixed_key (the fixed combo alone) survives the merge so the
            # onboarding guide can show it without the mode-specific aliases.
            if e.get("fixed") and not g.get("fixed"):
                for k in ("name", "category", "description", "fixed", "fixed_key"):
                    g[k] = e[k]
        for e in merged:
            e["key"] = " / ".join(e["keys"])
            del e["keys"]  # merge-time accumulator only; not part of the row contract
        return merged

    def get_windows(self) -> List[Dict[str, Any]]:
        """Queries all clients/windows from Hyprland via `hyprctl clients -j` safely."""
        try:
            _ensure_hyprland_instance()
            cli_out = subprocess.check_output(["hyprctl", "clients", "-j"], text=True, timeout=0.5).strip()
            if not cli_out:
                return []
            clients = json.loads(cli_out)
            return clients if isinstance(clients, list) else []
        except (OSError, ValueError, subprocess.SubprocessError) as _e:
            _debug(f"hyprctl clients query failed: {_e}")
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
        except (OSError, ValueError, subprocess.SubprocessError, TypeError) as _e:
            _debug(f"active-window-at-point query failed: {_e}")
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
        except (OSError, ValueError, subprocess.SubprocessError) as _e:
            _debug(f"hyprctl activewindow query failed: {_e}")
            return None

    def _hypr_dispatch(self, lua_cmd: str, legacy_args: List[str]) -> bool:
        """Dispatches a command via Lua API (hl.dsp.*) first, falling back to legacy hyprctl dispatch.

        Success is judged by hyprctl's output, not its exit code: hyprctl can
        print an error and still exit 0, and trusting the exit code made
        callers (e.g. unpin) report success for dispatches that never ran.
        Only an exact `ok` reply counts, same as _eval_lua_strict."""
        if compositor_mutation_disabled():
            # Dry run means "do not mutate the compositor" — never dispatch
            # for real here (the previous code did exactly that).
            return True
        if not shutil.which("hyprctl"):
            return False

        def _dispatch(args: List[str]) -> bool:
            try:
                res = subprocess.run(["hyprctl", "dispatch"] + args, capture_output=True, text=True, timeout=0.5, check=False)
                return res.returncode == 0 and res.stdout.strip() == "ok"
            except (OSError, subprocess.SubprocessError) as _e:
                _debug(f"hyprctl dispatch {args} failed: {_e}")
                return False

        if lua_cmd and _dispatch([lua_cmd]):
            return True
        if legacy_args:
            return _dispatch(legacy_args)
        return False

    def unpin(self, address: Optional[str] = None, all_windows: bool = False) -> Dict[str, Any]:
        """Unpins pinned window(s) so they no longer float on top of all workspaces, matching omarchy-hyprland-window-pop."""
        _ensure_hyprland_instance()
        windows = self.get_windows()
        pinned_windows = [w for w in windows if w.get("pinned", False)]

        target_windows = []
        if all_windows:
            target_windows = pinned_windows
            if not target_windows:
                return {"unpinned": [], "message": "当前没有处于置顶状态的窗口"}
        elif address:
            addr_norm = address.lower().strip()
            if not addr_norm.startswith("0x"):
                addr_norm = "0x" + addr_norm
            matched = [w for w in windows if str(w.get("address", "")).lower() == addr_norm]
            if not matched:
                return {"unpinned": [], "message": f"未找到地址为 {address} 的窗口"}
            win = matched[0]
            if not win.get("pinned", False):
                cls_str = f" [{win.get('class')}]" if win.get('class') else ""
                return {"unpinned": [], "message": f"窗口{cls_str} ({address}) 当前并未处于置顶状态，无需取消置顶"}
            target_windows = [win]
        else:
            # Active window or single pinned window fallback
            active = self.get_active_window()
            if active and active.get("pinned", False):
                target_windows = [active]
            elif len(pinned_windows) == 1:
                target_windows = pinned_windows
            elif active and not pinned_windows:
                return {"unpinned": [], "message": f"当前活动窗口 [{active.get('class')}] 并未处于置顶状态"}
            elif not pinned_windows:
                return {"unpinned": [], "message": "当前没有处于置顶状态的窗口"}
            else:
                classes = ", ".join(f"[{w.get('class', '')}] {w.get('address')}" for w in pinned_windows[:3])
                return {
                    "unpinned": [],
                    "message": f"存在多个置顶窗口 ({len(pinned_windows)} 个: {classes})，请聚焦窗口后运行、指定窗口地址或加 --all"
                }

        unpinned = []
        for w in target_windows:
            addr = w.get("address")
            if not addr:
                continue
            win_arg = f"address:{addr}"
            esc_win = f"address:{_escape_lua_string(addr)}"
            try:
                # 1. Unpin window
                if not self._hypr_dispatch(f'hl.dsp.window.pin({{ window = "{esc_win}" }})', ["pin", win_arg]):
                    _debug(f"Failed to unpin {addr}")
                    continue
                # 2. Toggle floating / restore tiled layout
                if w.get("floating", False):
                    self._hypr_dispatch(f'hl.dsp.window.float({{ window = "{esc_win}", action = "toggle" }})', ["togglefloating", win_arg])
                # 3. Remove -pop tag
                self._hypr_dispatch(f'hl.dsp.window.tag({{ window = "{esc_win}", tag = "-pop" }})', ["tagwindow", "-pop", win_arg])
                unpinned.append({
                    "address": addr,
                    "class": w.get("class", ""),
                    "title": (w.get("title", "") or "")[:30]
                })
            except (OSError, subprocess.SubprocessError) as _e:
                _debug(f"Failed to unpin {addr}: {_e}")

        return {"unpinned": unpinned, "message": "成功" if unpinned else "未执行取消置顶"}

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
                except (OSError, subprocess.SubprocessError) as _e:
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
            except (OSError, subprocess.SubprocessError) as _e:
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

        Non-destructive: the session's active mode is restored at the end (unmeasured)."""
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
            self.switch_mode("windows")
            results["switch_windows_ms"] = round((time.perf_counter() - t0) * 1000, 3)

            # 3. macOS profile switch latency
            t0 = time.perf_counter()
            self.switch_mode("mac")
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
                results["mode_restored"] = self.switch_mode(prev_mode)
            elif prev_mode == "omarchy":
                self._write_state("omarchy", 0, policy=prev_policy)

            current_policy = self.get_window_policy()
            results["policy_restored"] = True
            if prev_mode == "omarchy" and prev_policy == "floating":
                results["policy_restored"] = self.set_window_policy(prev_policy, source="benchmark-restore")
            elif prev_policy != current_policy:
                results["policy_restored"] = self.set_window_policy(prev_policy, source="benchmark-restore")

        return results

    def check_installation(self, home: Optional[Path] = None, fix: bool = False) -> Dict[str, Any]:
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

        # Check for known deprecated plugin links in plugins_dir (omni.mac-dock)
        deprecated_plugins = {"omni.mac-dock"}
        if plugins_dir.is_dir():
            for dep_name in deprecated_plugins:
                p_link = plugins_dir / dep_name
                if p_link.is_symlink() or p_link.exists():
                    if fix:
                        try:
                            if p_link.is_symlink() or p_link.is_file():
                                p_link.unlink()
                            elif p_link.is_dir():
                                shutil.rmtree(p_link)
                            _debug(f"Removed deprecated plugin link: {p_link}")
                        except OSError as _e:
                            problems.append({
                                "problem": f"Deprecated plugin link {dep_name} remains in {plugins_dir}",
                                "fix": f"rm -rf {p_link}"
                            })
                    else:
                        problems.append({
                            "problem": f"Deprecated plugin link {dep_name} exists in {plugins_dir}",
                            "fix": f"rm -rf {p_link} 或执行 omni-profile doctor --fix"
                        })

        # Shared design dir: plugins resolve ../shared/<file> through it, so it
        # must be linked next to the per-plugin links.
        shared_src = root / "plugins" / "shared"
        shared_link = plugins_dir / "shared"
        if not (shared_link.is_symlink() or shared_link.exists()):
            shared_state = "missing"
        elif not shared_link.exists():
            shared_state = "broken"
        elif shared_link.resolve() != shared_src:
            shared_state = "other"
        else:
            shared_state = "ok"
        info["plugins"]["shared"] = shared_state
        if shared_state != "ok":
            problems.append({"problem": f"Shared dir link is {shared_state} in {plugins_dir} "
                                        "(plugin ../shared/* symlinks will dangle)",
                             "fix": reinstall})

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
                except (OSError, subprocess.SubprocessError) as e:
                    _debug(f"systemctl query failed: {e}")
        # A missing unit is fine: the daemon is optional.

        # Shared design files must be symlinks into plugins/shared/
        try:
            bad = []
            for name in ("Tokens.js", "OmniTheme.qml", "Icons.js", "OverlayWindow.qml", "Safety.js", "Takeovers.js"):
                for p in sorted((root / "plugins").glob("omni.*")):
                    if p.is_dir():
                        link = p / name
                        if not link.is_symlink() or os.readlink(link) != f"../shared/{name}" or not link.exists():
                            bad.append(f"{p.name}/{name}")
        except OSError as e:
            _debug(f"shared-link check failed: {e}")
            bad = []
        if bad:
            info["tokens_in_sync"] = False
            problems.append({"problem": f"Shared design files not symlinked: {', '.join(bad)}",
                             "fix": reinstall})

        info["problems"] = problems
        return info

    def doctor(self, fix: bool = False) -> Dict[str, Any]:
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
            "window_policy": {"policy": self.get_window_policy(),
                              "overridden": self.get_window_policy() != "follow-profile"},
            "fixed_bindings": sorted(self.fixed_combos()),
            "takeovers": {},
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
            except OSError as e:
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
            except (OSError, ValueError, subprocess.SubprocessError) as e:
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

        # 3.6 Duplicate binds: the same (key, modmask) bound twice with the same handler fires N times
        report["duplicate_binds"] = {"count": 0, "combos": []}
        try:
            dups = find_duplicate_binds([b for lst in self._live_bind_details().values() for b in lst])
        except (OSError, ValueError, subprocess.SubprocessError) as _e:
            _debug(f"duplicate-binds query failed: {_e}")
            dups = {}
        if dups:
            total = sum(dups.values())
            report["duplicate_binds"] = {"count": total,
                                         "combos": sorted(f"{_sig_combo(s)} x{n + 1}" for s, n in dups.items())}
            report["issues"].append(f"❌ Duplicate binds: {total} extra copies on {len(dups)} key combos ("
                                    + ", ".join(report["duplicate_binds"]["combos"][:8]) + ")")
            report["fixes"].append("omni-profile restore（会自动合并重复绑定）或 hyprctl reload")

        # 3.7 Pinned windows check (windows forced on top)
        report["pinned_windows"] = []
        try:
            for c in self.get_windows():
                if c.get("pinned", False):
                    cls_name = str(c.get("class", "") or "unknown")
                    title = str(c.get("title", "") or "")
                    addr = str(c.get("address", "") or "")
                    short_t = title[:24] + ("..." if len(title) > 24 else "")
                    report["pinned_windows"].append({
                        "class": cls_name,
                        "title": short_t,
                        "address": addr
                    })
        except (OSError, ValueError, subprocess.SubprocessError) as _e:
            _debug(f"pinned-windows query failed: {_e}")

        # 4. Installation self-check (CLI link, plugin links, systemd unit, token copies)
        # Pass fix= directly: a try/except TypeError fallback here would also
        # swallow a genuine TypeError raised inside check_installation.
        install = self.check_installation(fix=fix)
        report["install"] = install
        for item in install["problems"]:
            report["issues"].append(item["problem"])
        report["fixes"] += [item["fix"] for item in install["problems"]]

        # 4.5 Omarchy version gate (shared with scripts/install.sh)
        try:
            from engine.omarchy_version import check_omarchy_version
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # NOTE(structure): engine/ dir (sibling of omnipal/) holds omarchy_version.py
            from omarchy_version import check_omarchy_version  # type: ignore
        ov = check_omarchy_version(self.root_dir)
        report["omarchy"] = ov
        if ov["status"] == "too_old":
            report["issues"].append(f"Omarchy {ov['detected']} is older than required {ov['minimum']}; plugins will fail to load")
            report["fixes"].append("Run omarchy-update to upgrade Omarchy")

        # 4. Consistency check
        # Run quietly so `omni-profile doctor --json` stays pure JSON on stdout.
        # NOTE: only the full checker comes from scripts/ here; the protected
        # bindings rules come from the engine itself (engine.omnipal.profiles),
        # so the engine no longer reverse-imports scripts/ for them.
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
            except (OSError, subprocess.SubprocessError) as run_err:
                report["issues"].append(f"Failed to run consistency check: {run_err}")
                report["consistency"] = False
        if not report["consistency"]:
            report["issues"].append("Schema or profile consistency validation failed")

        # 4.6 Protected system keybindings: name exactly which profile overrides what,
        # so `doctor` (not just the dev-side checker) points at the problem.
        # The rules come from engine.omnipal.profiles (imported at module top):
        # no reverse dependency on scripts/ here.
        try:
            for p_id, mod, key, reason in find_protected_violations(self.root_dir, self.profiles):
                report["issues"].append(
                    f"Profile '{p_id}' overrides protected system key {mod} {key} ({reason})")
                report["fixes"].append(
                    f"从 '{p_id}' 移除 {mod} {key} 绑定，或改用其他组合键")
        except (OSError, ValueError, KeyError) as e:
            _debug(f"protected-bindings scan failed: {e}")

        # App rules skipped at load for unsafe regex (hand-edited / legacy files
        # bypass the save-time gate).
        try:
            for bad in self.invalid_app_rules():
                report["issues"].append(
                    f"App rule '{bad['class']}' skipped: unsafe regex ({bad['reason']})")
                report["fixes"].append(
                    "修改该规则的正则（去掉分组后的量词）或改用 exact/prefix 匹配")
        except (OSError, ValueError, re.error) as e:
            _debug(f"invalid app-rules scan failed: {e}")

        if report["issues"]:
            report["healthy"] = False

        try:
            live_natives = self._own_filtered_natives()
        except (OSError, ValueError, subprocess.SubprocessError) as _e:
            _debug(f"native-binds query failed: {_e}")
            live_natives = {}
        for m in self.profiles:
            if m == "omarchy":
                continue
            try:
                report["takeovers"][m] = self.mode_diff(m, live_natives)
            except (OSError, ValueError, subprocess.SubprocessError, KeyError) as e:
                # Per-mode diff failure is recorded, not fatal; the
                # report must cover every mode even if one diff crashes.
                report["takeovers"][m] = {"mode": m, "error": str(e)}

        return report
