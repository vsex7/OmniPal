#!/usr/bin/env python3
"""Shared Omarchy version detection (used by scripts/install.sh and `omni-profile doctor`).

Detection order: $OMNIPAL_OMARCHY_VERSION override, `pacman -Q omarchy`,
then $OMARCHY_PATH/version (default ~/.local/share/omarchy/version).
Required minimum = highest `minOmarchy` across plugins/omni.*/manifest.json.
CLI: `python3 engine/omarchy_version.py [ROOT]` prints "<status> <detected> <minimum>"
where status is ok | too_old | unknown.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple


def _vtuple(v: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)


def _normalize(v: str) -> str:
    v = v.strip().lstrip("vV")
    return v.split("-", 1)[0]


def detect_omarchy_version() -> Optional[str]:
    override = os.environ.get("OMNIPAL_OMARCHY_VERSION", "").strip()
    if override:
        return _normalize(override)
    if shutil.which("pacman"):
        try:
            res = subprocess.run(["pacman", "-Q", "omarchy"], capture_output=True, text=True, timeout=10)
            parts = res.stdout.split()
            if res.returncode == 0 and len(parts) >= 2:
                return _normalize(parts[1])
        except Exception:
            pass
    base = os.environ.get("OMARCHY_PATH") or str(Path.home() / ".local/share/omarchy")
    vf = Path(base) / "version"
    try:
        line = vf.read_text(encoding="utf-8").strip().splitlines()[0]
        if line.strip():
            return _normalize(line)
    except (OSError, IndexError):
        pass
    return None


def required_min_omarchy(root: Path) -> str:
    vals = []
    for mf in sorted(Path(root).glob("plugins/omni.*/manifest.json")):
        try:
            v = json.loads(mf.read_text(encoding="utf-8")).get("minOmarchy")
        except (OSError, ValueError):
            continue
        if v:
            vals.append(str(v))
    return max(vals, key=_vtuple) if vals else "0"


def check_omarchy_version(root: Path) -> Dict[str, Optional[str]]:
    minimum = required_min_omarchy(root)
    detected = detect_omarchy_version()
    if detected is None:
        status = "unknown"
    elif _vtuple(detected) < _vtuple(minimum):
        status = "too_old"
    else:
        status = "ok"
    return {"status": status, "detected": detected, "minimum": minimum}


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    r = check_omarchy_version(root)
    print(r["status"], r["detected"] or "-", r["minimum"])
