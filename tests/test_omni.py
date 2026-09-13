#!/usr/bin/env python3
"""
OmniPal Automated Unit Tests
Tests schema consistency, state management, profile parsing, and plugin compliance.
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.engine import OmniPalEngine, format_combo
from scripts.check_consistency import check_consistency

class TestOmniPal(unittest.TestCase):
    def setUp(self):
        self.engine = OmniPalEngine(PROJECT_ROOT)

    def test_schema_and_profile_consistency(self):
        """Validates that all profiles and plugins strictly adhere to specs."""
        self.assertTrue(check_consistency(PROJECT_ROOT))

    def test_format_combo(self):
        """Verifies modifier string formatting into standard Hyprland combos."""
        self.assertEqual(format_combo("ALT", "F4"), "ALT + F4")
        self.assertEqual(format_combo("SUPER", "Left"), "SUPER + LEFT")
        self.assertEqual(format_combo("SUPER SHIFT", "s"), "SUPER + SHIFT + S")
        self.assertEqual(format_combo("SUPER CTRL", "q"), "SUPER + CTRL + Q")
        self.assertEqual(format_combo("SUPER ALT", "d"), "SUPER + ALT + D")

    def test_profiles_loaded(self):
        """Ensures all default profiles are registered."""
        self.assertIn("omarchy", self.engine.profiles)
        self.assertIn("windows", self.engine.profiles)
        self.assertIn("mac", self.engine.profiles)

    def test_cheatsheet_generation(self):
        """Checks cheatsheet data extraction from single source of truth."""
        win_sheet = self.engine.cheatsheet("windows")
        self.assertGreater(len(win_sheet), 0)
        self.assertTrue(any("F4" in item["key"] for item in win_sheet))
        self.assertTrue(any("I" in item["key"] for item in win_sheet))

        mac_sheet = self.engine.cheatsheet("mac")
        self.assertGreater(len(mac_sheet), 0)
        self.assertTrue(any("Q" in item["key"] for item in mac_sheet))
        self.assertTrue(any("D" in item["key"] for item in mac_sheet))

    def test_all_six_plugins_exist(self):
        """Validates that all 6 required Quickshell plugins exist with entry points."""
        expected_plugins = [
            "omni.mode-indicator",
            "omni.cheat-sheet",
            "omni.settings",
            "omni.snap-feedback",
            "omni.overview",
            "omni.mac-dock"
        ]
        plugins_dir = PROJECT_ROOT / "plugins"
        for p_name in expected_plugins:
            p_path = plugins_dir / p_name
            self.assertTrue(p_path.exists(), f"Missing plugin directory: {p_name}")
            manifest = p_path / "manifest.json"
            self.assertTrue(manifest.exists(), f"Missing manifest.json for: {p_name}")
            with open(manifest, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data.get("schemaVersion"), 1)
            self.assertEqual(data.get("id"), p_name)
            for ep_type, ep_file in data.get("entryPoints", {}).items():
                self.assertTrue((p_path / ep_file).exists(), f"Entry point {ep_file} not found in {p_name}")

    def test_hard_stop_compliance(self):
        """Ensures that engine runtime state files are strictly confined to tmpfs (/run/user/)."""
        from engine.engine import STATE_FILE, OVERLAY_FILE, RUN_DIR
        self.assertTrue(str(RUN_DIR).startswith("/run/user/"))
        self.assertTrue(str(STATE_FILE).startswith("/run/user/"))
        self.assertTrue(str(OVERLAY_FILE).startswith("/run/user/"))
        # Ensure no configuration directories are referenced as write targets
        self.assertNotIn(".config/hypr", str(STATE_FILE))
        self.assertNotIn("shell.json", str(STATE_FILE))

    def test_snap_execution(self):
        """Validates that snap method writes to snap.json in tmpfs and dispatches correctly."""
        from engine.engine import SNAP_FILE
        success = self.engine.snap("left")
        self.assertTrue(success)
        self.assertTrue(SNAP_FILE.exists())
        with open(SNAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("zone"), "left")
        if hasattr(self.engine, "_last_summon_proc") and self.engine._last_summon_proc:
            try:
                self.engine._last_summon_proc.wait(timeout=0.5)
            except Exception:
                pass

    def test_benchmark_metrics(self):
        """Verifies benchmark latency execution and reporting structure."""
        metrics = self.engine.benchmark()
        self.assertIn("parse_ms", metrics)
        self.assertIn("switch_windows_ms", metrics)
        self.assertIn("switch_mac_ms", metrics)
        self.assertIn("restore_ms", metrics)
        self.assertIn("state_write_ms", metrics)

    def test_doctor_diagnostics(self):
        """Validates doctor diagnostic engine reports structured health metrics."""
        diag = self.engine.doctor()
        self.assertIn("healthy", diag)
        self.assertIn("version", diag)
        self.assertIn("daemon", diag)
        self.assertIn("socket2", diag)
        self.assertIn("state", diag)
        self.assertIn("overlay", diag)
        self.assertIn("consistency", diag)
        self.assertTrue(diag["consistency"])

    def test_idempotent_switch_and_restore(self):
        """Ensures that repeated switch and restore calls remain idempotent and safe."""
        for _ in range(3):
            self.assertTrue(self.engine.switch_mode("windows"))
            state = self.engine.get_state()
            self.assertEqual(state["mode"], "windows")
            self.assertEqual(state["active_bindings_count"], 13)

        for _ in range(2):
            self.assertTrue(self.engine.restore())
            state = self.engine.get_state()
            self.assertEqual(state["mode"], "omarchy")
            self.assertEqual(state["active_bindings_count"], 0)

    def test_rollback_on_eval_failure(self):
        """Verifies that engine rolls back to clean state when Hyprland eval fails."""
        original_eval = self.engine._eval_lua
        try:
            # Force eval to return False to simulate Hyprland error
            self.engine._eval_lua = lambda code: False
            success = self.engine.switch_mode("windows")
            self.assertFalse(success)
            state = self.engine.get_state()
            # Must roll back to baseline omarchy mode
            self.assertEqual(state["mode"], "omarchy")
            self.assertEqual(state["active_bindings_count"], 0)
        finally:
            self.engine._eval_lua = original_eval

if __name__ == "__main__":
    unittest.main()
