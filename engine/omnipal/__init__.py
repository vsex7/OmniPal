"""OmniPal core runtime engine package (split from single-file engine.py)."""

from engine.omnipal.version import __version__, VERSION

from engine.omnipal import paths as _paths
from engine.omnipal import util as _util
from engine.omnipal import hypr_ipc as _hypr_ipc
from engine.omnipal import profiles as _profiles
from engine.omnipal import core as _core
from engine.omnipal import daemon as _daemon

_SUBMODS = {'paths': _paths, 'util': _util, 'hypr_ipc': _hypr_ipc,
            'profiles': _profiles, 'core': _core, 'daemon': _daemon}

_NAME2MOD = {
    'VERSION': 'version',
    '__version__': 'version',
    'APPLIED_WINDOW_MODE_FILE': 'paths',
    'APP_RULE_STATE_FILE': 'paths',
    'BASELINE_FILE': 'paths',
    'LOCK_FILE': 'paths',
    'OVERLAY_FILE': 'paths',
    'PID_FILE': 'paths',
    'RUN_DIR': 'paths',
    'SNAP_FILE': 'paths',
    'SNAP_LAYOUTS_FILE': 'paths',
    'STATE_FILE': 'paths',
    '_resolve_run_dir': 'paths',
    'app_rules_file_path': 'paths',
    'persistence_file_path': 'paths',
    'resolve_config_dir': 'paths',
    'resolve_user_profiles_dir': 'paths',
    'LUA_RESTORE_BASELINE': 'util',
    '_FLAG_OPTS': 'util',
    '_KEEP': 'util',
    '_MODMASK': 'util',
    '_MODMASK_NAMES': 'util',
    '_debug': 'util',
    '_escape_lua_string': 'util',
    '_lock_local': 'util',
    '_sig_combo': 'util',
    'atomic_write_json': 'util',
    'bind_key_name': 'util',
    'bind_signature': 'util',
    'combo_signature': 'util',
    'compositor_mutation_disabled': 'util',
    'engine_lock': 'util',
    'find_duplicate_binds': 'util',
    'format_combo': 'util',
    'lua_str': 'util',
    'notify_user': 'util',
    'write_state_json': 'util',
    '_dedupe_binds_lua': 'hypr_ipc',
    '_ensure_hyprland_instance': 'hypr_ipc',
    '_native_stash_lua': 'hypr_ipc',
    '_native_unstash_lua': 'hypr_ipc',
    'derive_hyprland_instance_signature': 'hypr_ipc',
    'find_socket2_path': 'hypr_ipc',
    'hyprland_socket_ready': 'hypr_ipc',
    'DIALOG_KEYWORDS': 'profiles',
    'FORWARD_ACTION': 'profiles',
    'MIGRATION_FALLBACK_MODE': 'profiles',
    'RETIRED_MODES': 'profiles',
    'TERMINAL_CLASSES': 'profiles',
    'VALID_WINDOW_POLICIES': 'profiles',
    'WINDOW_POLICY_ALIASES': 'profiles',
    '_FORWARD_KEY_RE': 'profiles',
    '_FORWARD_MOD_RE': 'profiles',
    'forward_for_class': 'profiles',
    'forward_lua': 'profiles',
    'is_dialog_window': 'profiles',
    'is_micro_window': 'profiles',
    'is_pip_window': 'profiles',
    'is_scratchpad_workspace': 'profiles',
    'is_special_window': 'profiles',
    'is_terminal_class': 'profiles',
    'load_fixed_bindings': 'profiles',
    'load_terminal_patterns': 'profiles',
    'normalize_window_policy': 'profiles',
    'parse_forward': 'profiles',
    'LUA_DISPATCHERS': 'core',
    'OmniPalEngine': 'core',
    'validate_app_rule_pattern': 'core',
    '_watch_hyprland_socket2': 'daemon',
    'resolve_reapply_mode': 'daemon',
    'restore_persisted_profile': 'daemon',
    'run_daemon': 'daemon',
    'wait_for_hyprland': 'daemon',
}

def __getattr__(name):
    try:
        return getattr(_SUBMODS[_NAME2MOD[name]], name)
    except KeyError:
        raise AttributeError(f"module 'engine.omnipal' has no attribute {name!r}")

def __dir__():
    return sorted(set(globals()) | set(_NAME2MOD) | {'__version__', 'VERSION'})

__all__ = sorted(set(_NAME2MOD) | {'__version__', 'VERSION'})
