#!/usr/bin/env python3
"""Protected keybindings at switch time (A2 task, 2026-10-17).

A mode file dropped straight into the user profiles directory bypasses
`omni-profile import`, so the engine itself must refuse to install protected
system combos (schema/protected_bindings.json, e.g. Super+Alt+Space): skip
them with a warning and let the switch continue.

Also locks in the refactor: the protected-combos rules live in
engine/omnipal/profiles.py and are shared by the consistency checker,
`omni-profile import`, engine.doctor() and the switch-time filter.
"""

import contextlib
import io
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
    os.environ["XDG_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="omnipal-test-sw-")
_cfg = tempfile.TemporaryDirectory()
os.environ["OMNIPAL_CONFIG_DIR"] = _cfg.name
_run = tempfile.TemporaryDirectory()
os.environ["OMNIPAL_RUN_DIR"] = _run.name
os.environ["OMNIPAL_DRY_RUN"] = "1"

from engine.engine import OmniPalEngine
from engine.omnipal import profiles as engine_profiles
from engine.omnipal.profiles import combo_key
import scripts.check_consistency as cc


def _record_combo_key(combo: str) -> str:
    """Re-normalize a format_combo() string ('SUPER + ALT + SPACE') with combo_key."""
    parts = [p.strip() for p in str(combo or "").split("+")]
    return combo_key(" ".join(parts[:-1]), parts[-1] if parts else "")


class TestSharedSingleSource(unittest.TestCase):
    """The protected-combos rules must have exactly one home: engine/omnipal/profiles."""

    def test_check_consistency_reuses_engine_copy(self):
        self.assertIs(cc.find_protected_violations, engine_profiles.find_protected_violations)
        self.assertIs(cc._validate_protected_bindings, engine_profiles.validate_protected_bindings)
        self.assertIs(cc._combo_key, engine_profiles.combo_key)

    def test_normalization_agrees(self):
        self.assertEqual(combo_key("SUPER ALT", "space"), combo_key("alt+super", "SPACE"))


class TestSwitchSkipsProtectedBindings(unittest.TestCase):
    """switch_mode() must skip protected combos with a warning, not install them,
    and not interrupt the switch for the remaining bindings."""

    def _evil_engine(self, updir: Path) -> OmniPalEngine:
        evil = {
            "id": "_a2evil",
            "name": "a2 evil",
            "bindings": [
                {"action": "lock_screen", "mod": "SUPER ALT", "key": "space"},
                {"action": "lock_screen", "mod": "SUPER", "key": "F9"},
            ],
        }
        (updir / "_a2evil.json").write_text(json.dumps(evil), encoding="utf-8")
        return OmniPalEngine(PROJECT_ROOT, user_profiles_dir=updir)

    def test_switch_skips_protected_combo_with_warning(self):
        with tempfile.TemporaryDirectory() as ud:
            updir = Path(ud)
            e = self._evil_engine(updir)
            self.assertIn("_a2evil", e.profiles, "dropped-in mode file must be picked up")

            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                ok = e.switch_mode("_a2evil")

            # 1. Switch is not interrupted by the offending binding.
            self.assertTrue(ok)
            self.assertEqual(e.get_state().get("mode"), "_a2evil")

            # 2. The protected combo was skipped with a warning.
            self.assertIn("protected", err.getvalue().lower())
            self.assertIn("skipping", err.getvalue().lower())

            # 3. The protected key was NOT installed; the benign one was.
            keys = {_record_combo_key(r.get("combo", "")) for r in e._get_active_overlay()}
            self.assertNotIn(combo_key("SUPER ALT", "space"), keys,
                             "protected combo must not be in the installed overlay")
            self.assertIn(combo_key("SUPER", "F9"), keys,
                          "benign bindings of the same mode must still be installed")

    def test_find_violations_spots_dropped_in_profile(self):
        with tempfile.TemporaryDirectory() as ud:
            updir = Path(ud)
            e = self._evil_engine(updir)
            hits = engine_profiles.find_protected_violations(PROJECT_ROOT, e.profiles)
            self.assertTrue([h for h in hits if h[0] == "_a2evil"],
                            f"dropped-in profile must be flagged, got: {hits}")


if __name__ == "__main__":
    unittest.main()
