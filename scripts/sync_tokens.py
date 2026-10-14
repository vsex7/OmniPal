#!/usr/bin/env python3
"""Copies plugins/shared/Tokens.js (the single source) into every plugin dir.

Each plugin ships its own copy because plugins are installed as individual
symlinks, so a relative import like "../shared/Tokens.js" is not reliable.
Run with --check to only verify copies are in sync (exit 1 if not).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "plugins" / "shared" / "Tokens.js"


def plugin_dirs():
    return sorted(p for p in (ROOT / "plugins").glob("omni.*") if p.is_dir())


def out_of_sync(root: Path = ROOT):
    src = (root / "plugins" / "shared" / "Tokens.js")
    if not src.exists():
        return []
    data = src.read_bytes()
    bad = []
    for p in sorted((root / "plugins").glob("omni.*")):
        if p.is_dir():
            copy = p / "Tokens.js"
            if not copy.exists() or copy.read_bytes() != data:
                bad.append(copy)
    return bad


def main():
    if "--check" in sys.argv:
        bad = out_of_sync()
        for b in bad:
            print(f"❌ Tokens.js out of sync: {b.relative_to(ROOT)}")
        sys.exit(1 if bad else 0)
    data = SOURCE.read_bytes()
    for p in plugin_dirs():
        (p / "Tokens.js").write_bytes(data)
        print(f"✅ synced {p.name}/Tokens.js")


if __name__ == "__main__":
    main()
