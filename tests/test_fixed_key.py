#!/usr/bin/env python3
"""Regression tests: fixed entry points must not absorb mode aliases.

cheatsheet() merges a fixed entry row with a mode-specific alias row of the
same action (e.g. mac SUPER+comma for omni_settings) into one row whose `key`
lists every combo. The merged row carries `fixed_key` (the fixed combo alone)
so the onboarding guide can show only the fixed combos, never the aliases.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if not shutil.which("hyprctl") or os.environ.get("OMNIPAL_FAKE_HYPRCTL") == "1":
    os.environ["PATH"] = str(Path(__file__).resolve().parent / "fakebin") + os.pathsep + os.environ.get("PATH", "")
if not os.environ.get("XDG_RUNTIME_DIR") or not os.path.isdir(os.environ["XDG_RUNTIME_DIR"]):
    os.environ["XDG_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="omnipal-test-fk-")
_cfg = tempfile.TemporaryDirectory()
os.environ["OMNIPAL_CONFIG_DIR"] = _cfg.name
_run = tempfile.TemporaryDirectory()
os.environ["OMNIPAL_RUN_DIR"] = _run.name
os.environ["OMNIPAL_DRY_RUN"] = "1"

# NOTE: the engine must NOT be imported at module level here. test_omni.py
# (collected after this module) freezes engine path constants (OVERLAY_FILE,
# STATE_FILE, ...) from OMNIPAL_RUN_DIR at first import and then switches the
# run dir; an earlier import here would freeze them to this module's temp dir
# and break 15 test_omni tests. pytest imports test_omni at collection time,
# so a lazy import below always resolves to the already-imported module.


def _engine():
    from engine.engine import OmniPalEngine
    return OmniPalEngine(PROJECT_ROOT)


def _format_combo(mod, key):
    from engine.omnipal.util import format_combo
    return format_combo(mod, key)


def _fixed_bindings():
    return json.loads(
        (PROJECT_ROOT / "schema" / "fixed_bindings.json").read_text(encoding="utf-8"))["bindings"]


class TestFixedKey(unittest.TestCase):
    MODES = ("windows", "mac", "omarchy")

    def test_fixed_rows_carry_single_fixed_key(self):
        e = _engine()
        expected = {b["action"]: _format_combo(b.get("mod", ""), b["key"])
                    for b in _fixed_bindings()}
        for mode in self.MODES:
            fixed_rows = [r for r in e.cheatsheet(mode) if r.get("fixed")]
            self.assertEqual(len(fixed_rows), len(expected),
                             f"{mode}: expected {len(expected)} fixed rows")
            for r in fixed_rows:
                self.assertIn("fixed_key", r, f"{mode} {r['action']}: missing fixed_key")
                self.assertNotIn("/", r["fixed_key"],
                                 f"{mode} {r['action']}: fixed_key must be a single combo")
                self.assertEqual(r["fixed_key"], expected[r["action"]],
                                 f"{mode} {r['action']}: fixed_key is not the fixed combo")

    def test_merged_row_keeps_merged_key_but_single_fixed_key(self):
        # windows omni_settings: profile alias SUPER+I merges with the fixed
        # entry SUPER+ALT+I; the main table keeps the merged key (intentional),
        # but fixed_key must hold only the fixed combo.
        rows = {r["action"]: r for r in _engine().cheatsheet("windows")}
        row = rows["omni_settings"]
        self.assertIn("/", row["key"], "alias row must stay merged")
        self.assertIn("SUPER + I", row["key"])
        self.assertEqual(row["fixed_key"], "SUPER + ALT + I")

    def test_guide_combos_are_fixed_only_in_every_mode(self):
        # Acceptance: the onboarding guide (fixed rows via fixed_key) shows
        # exactly the three fixed combos, never a mode-only alias like Super+,.
        e = _engine()
        fixed_combos = {_format_combo(b.get("mod", ""), b["key"])
                        for b in _fixed_bindings()}
        profile_combos = set()
        for mode in self.MODES:
            profile = json.loads(
                (PROJECT_ROOT / "profiles" / f"{mode}.json").read_text(encoding="utf-8"))
            for b in profile.get("bindings", []):
                profile_combos.add(_format_combo(b.get("mod", ""), b.get("key", "")))
        aliases = profile_combos - fixed_combos
        self.assertTrue(aliases, "profiles must contain alias combos for this test to mean anything")
        for mode in self.MODES:
            guide = [r["fixed_key"] for r in e.cheatsheet(mode) if r.get("fixed")]
            self.assertEqual(set(guide), fixed_combos,
                             f"{mode}: guide must show exactly the fixed combos")
            for alias in aliases:
                self.assertNotIn(alias, guide, f"{mode}: alias {alias!r} leaked into the guide")

    def test_nonfixed_rows_have_no_fixed_key(self):
        for mode in self.MODES:
            for r in _engine().cheatsheet(mode):
                if not r.get("fixed"):
                    self.assertNotIn("fixed_key", r,
                                     f"{mode} {r['action']}: fixed_key is for fixed rows only")


if __name__ == "__main__":
    unittest.main()
