#!/usr/bin/env python3
"""Regressions from the bug hunt: corrupt state files and CLI error paths must not traceback."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import onboarding  # noqa: E402

CLI = PROJECT_ROOT / "bin" / "omni-profile"
PROFILES = [{"id": "windows", "name": "Windows", "description": ""}]


class CorruptStateTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.cfg = self.root / "omnipal"
        self.cfg.mkdir()
        self.menu = self.root / "omarchy-menu.jsonc"

    def tearDown(self):
        self.td.cleanup()

    def test_onboarding_status_ignores_non_object_flag(self):
        (self.cfg / onboarding.ONBOARDING_FILE).write_text("[1]\n")
        st = onboarding.onboarding_status(self.cfg)
        self.assertTrue(st["shown"])

    def test_onboarding_reset_missing_is_false(self):
        self.assertFalse(onboarding.onboarding_reset(self.cfg))
        onboarding.onboarding_claim(self.cfg)
        self.assertTrue(onboarding.onboarding_reset(self.cfg))

    def test_menu_install_uninstall_with_non_object_state(self):
        for bad in ("[1]", '"x"', "{bad"):
            self.menu.unlink(missing_ok=True)
            (self.cfg / onboarding.MENU_STATE_FILE).write_text(bad)
            r = onboarding.menu_install(PROFILES, "/x/omni-profile", path=self.menu, config_dir=self.cfg)
            self.assertTrue(r["created_file"])
            (self.cfg / onboarding.MENU_STATE_FILE).write_text(bad)
            r = onboarding.menu_uninstall(path=self.menu, config_dir=self.cfg)
            self.assertTrue(r["removed_block"])


class CliErrorPathTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        t = Path(self.td.name)
        (t / "run").mkdir()
        self.env = dict(os.environ, HOME=str(t), XDG_CONFIG_HOME=str(t / "cfg"), XDG_RUNTIME_DIR=str(t / "run"),
                        OMNIPAL_CONFIG_DIR=str(t / "cfg" / "omnipal"), OMNIPAL_RUN_DIR=str(t / "run" / "omnipal"),
                        OMNIPAL_USER_PROFILES_DIR=str(t / "up"), OMNIPAL_DRY_RUN="1",
                        PATH=f"{PROJECT_ROOT / 'tests' / 'fakebin'}:{os.environ.get('PATH', '')}")

    def tearDown(self):
        self.td.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *args], env=self.env, capture_output=True,
                              text=True, timeout=30, stdin=subprocess.DEVNULL)

    def test_export_to_unwritable_path_is_clean_error(self):
        for args in (["export", "windows", "-o", "/nonexistent-dir/x.json"],
                     ["rules", "export", "-o", "/nonexistent-dir/x.json"]):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertNotIn("Traceback", r.stderr, args)

    def test_window_policy_parent_json_flag_survives_set(self):
        for args in (["window-policy", "--json", "set", "tiled"], ["window-policy", "set", "tiled", "--json"]):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["window_policy"], "tiled", args)


if __name__ == "__main__":
    unittest.main()


class TestUnfloatKeepsOwnSizeApps(unittest.TestCase):
    def test_scrcpy_not_unfloated(self):
        import importlib, sys as _s, os as _o
        _s.path.insert(0, _o.path.join(_o.path.dirname(__file__), "..", "engine"))
        eng = importlib.import_module("engine")
        cls = [v for v in vars(eng).values() if isinstance(v, type) and hasattr(v, "keeps_own_size")][0]
        self.assertTrue(cls.keeps_own_size("scrcpy"))
        src = open(_o.path.join(_o.path.dirname(__file__), "..", "engine", "engine.py")).read()
        body = src[src.index("def _unfloat_existing_windows"):]
        body = body[:body.index("to_unfloat.append")]
        self.assertIn("keeps_own_size", body)
