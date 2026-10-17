"""Run/config/state path resolution and well-known file locations."""

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

LOCK_FILE = RUN_DIR / "engine.lock"
APPLIED_WINDOW_MODE_FILE = RUN_DIR / "applied_window_mode"
BASELINE_FILE = RUN_DIR / "baseline_bindings.json"

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
