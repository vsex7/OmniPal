"""Hyprland IPC helpers: socket discovery, native-bind stash/unstash Lua."""

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

from engine.omnipal.util import (_FLAG_OPTS, _sig_combo, bind_key_name, find_duplicate_binds, lua_str)

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
            f'R.omnipal_stash[{c}] = {{ {", ".join(entries)} }} end')


def _native_unstash_lua(combo: str, present: Optional[int] = 0) -> str:
    """Lua that rebinds a combo's stashed native handlers; raises if the stash is gone.

    Idempotent: `present` binds still live on the combo (None = unknown, assume at most one) are
    unbound first, so the result is exactly the stashed natives and never a duplicate."""
    c = lua_str(combo)
    n = 1 if present is None else max(0, int(present))
    pre = "".join(f'hl.unbind({c}); ' for _ in range(n))
    return (f'do local R = debug.getregistry(); local S = R.omnipal_stash and R.omnipal_stash[{c}]; '
            f'if not S then error("omnipal: no stashed native for " .. {c}) end; '
            f'for _, e in ipairs(S) do if e.h == nil then error("omnipal: lost native handler") end end; '
            f'{pre}'
            f'for _, e in ipairs(S) do if e.h == nil then error("omnipal: lost native handler") end; '
            f'hl.bind({c}, e.h, e.o) end; R.omnipal_stash[{c}] = nil end')


def _dedupe_binds_lua(details: Dict[Tuple[int, str], List[Dict[str, Any]]]) -> List[str]:
    """Lua that collapses identical duplicate `__lua` binds to one per handler (self-heal)."""
    ops = []
    for sig, lst in details.items():
        if not find_duplicate_binds(lst):
            continue
        if any(b.get("dispatcher") != "__lua" or not str(b.get("arg", "")).isdigit() for b in lst):
            continue
        keep, seen = [], set()
        for b in lst:
            k = (b.get("description") or "", tuple(bool(b.get(f)) for f, _ in _FLAG_OPTS))
            if k not in seen:
                seen.add(k)
                keep.append(b)
        key = bind_key_name(lst[0])
        if not key or any(bind_key_name(b) != key for b in lst):
            continue
        c = lua_str(_sig_combo((sig[0], key)))
        locs = "; ".join(f'local h{i} = R[{int(b["arg"])}]' for i, b in enumerate(keep))
        check = " and ".join(f'type(h{i}) == "function"' for i in range(len(keep)))
        unb = " ".join(f'hl.unbind({c});' for _ in lst)
        binds = []
        for i, b in enumerate(keep):
            opts = [f'description = {lua_str(b.get("description") or "")}']
            opts += [f"{lua} = true" for js, lua in _FLAG_OPTS if b.get(js)]
            binds.append(f'hl.bind({c}, h{i}, {{ {", ".join(opts)} }})')
        ops.append(f'do local R = debug.getregistry(); {locs}; if {check} then {unb} {"; ".join(binds)} end end')
    return ops
