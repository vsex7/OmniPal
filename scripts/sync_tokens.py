#!/usr/bin/env python3
"""Copies plugins/shared/{Tokens.js,OmniTheme.qml} (single sources) into every plugin dir.

Each plugin ships its own copy because plugins are installed as individual
symlinks, so a relative import like "../shared/Tokens.js" is not reliable.
Run with --check to only verify copies are in sync (exit 1 if not).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED_FILES = ("Tokens.js", "OmniTheme.qml", "Icons.js")


def plugin_dirs():
    return sorted(p for p in (ROOT / "plugins").glob("omni.*") if p.is_dir())


def out_of_sync(root: Path = ROOT):
    bad = []
    for name in SHARED_FILES:
        src = root / "plugins" / "shared" / name
        if not src.exists():
            continue
        data = src.read_bytes()
        for p in sorted((root / "plugins").glob("omni.*")):
            if p.is_dir():
                copy = p / name
                if not copy.exists() or copy.read_bytes() != data:
                    bad.append(copy)
    return bad


def main():
    if "--check" in sys.argv:
        bad = out_of_sync()
        for b in bad:
            print(f"❌ out of sync: {b.relative_to(ROOT)}")
        sys.exit(1 if bad else 0)
    for name in SHARED_FILES:
        data = (ROOT / "plugins" / "shared" / name).read_bytes()
        for p in plugin_dirs():
            (p / name).write_bytes(data)
            print(f"✅ synced {p.name}/{name}")


if __name__ == "__main__":
    main()
