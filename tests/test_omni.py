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

    def test_snap_extended_zones(self):
        """Validates all new snap layout zones: center, thirds, and two-thirds."""
        from engine.engine import SNAP_FILE
        extended_zones = [
            "center",
            "third-left",
            "third-right",
            "two-thirds-left",
            "two-thirds-right"
        ]
        eval_codes = []
        original_eval = self.engine._eval_lua
        try:
            self.engine._eval_lua = lambda code: (eval_codes.append(code) or True)
            for zone in extended_zones:
                success = self.engine.snap(zone)
                if hasattr(self.engine, "_last_summon_proc") and self.engine._last_summon_proc:
                    try:
                        self.engine._last_summon_proc.wait(timeout=0.5)
                    except Exception:
                        pass
                self.assertTrue(success, f"Snap zone {zone} failed")
                self.assertTrue(SNAP_FILE.exists())
                with open(SNAP_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(data.get("zone"), zone)
            
            # Verify that Lua code contains geometry calculations
            self.assertEqual(len(eval_codes), len(extended_zones))
            self.assertTrue(any("math.floor(rw * 0.6)" in code for code in eval_codes))
            self.assertTrue(any("0.333" in code for code in eval_codes))
            self.assertTrue(any("0.667" in code for code in eval_codes))
        finally:
            self.engine._eval_lua = original_eval

    def test_user_custom_profiles(self):
        """Validates user custom profile loading, overriding, cycling order, and validation."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            user_dir = Path(tmp_dir)
            # 1. Create a brand new custom profile 'kde'
            kde_file = user_dir / "kde.json"
            kde_data = {
                "id": "kde",
                "name": "KDE Plasma 模式",
                "description": "User custom KDE bindings",
                "bindings": [
                    {"action": "file_manager", "mod": "CTRL ALT", "key": "e"}
                ]
            }
            with open(kde_file, "w", encoding="utf-8") as f:
                json.dump(kde_data, f)

            # 2. Create an override profile for 'windows'
            win_override_file = user_dir / "windows.json"
            win_override_data = {
                "id": "windows",
                "name": "Windows (Custom Overridden)",
                "description": "Overridden windows profile",
                "bindings": [
                    {"action": "lock_screen", "mod": "SUPER", "key": "l"}
                ]
            }
            with open(win_override_file, "w", encoding="utf-8") as f:
                json.dump(win_override_data, f)

            user_engine = OmniPalEngine(PROJECT_ROOT, user_profiles_dir=user_dir)
            profiles_meta = {p["id"]: p for p in user_engine.list_profiles()}

            self.assertIn("kde", user_engine.profiles)
            self.assertEqual(profiles_meta["kde"]["source"], "user")
            self.assertFalse(profiles_meta["kde"]["override"])

            self.assertIn("windows", user_engine.profiles)
            self.assertEqual(profiles_meta["windows"]["source"], "user")
            self.assertTrue(profiles_meta["windows"]["override"])
            self.assertEqual(user_engine.profiles["windows"]["name"], "Windows (Custom Overridden)")

            # Test dynamic cycling order: omarchy -> windows -> mac -> kde -> omarchy
            user_engine.switch_mode("omarchy")
            self.assertEqual(user_engine.cycle_mode(), "windows")
            self.assertEqual(user_engine.cycle_mode(), "mac")
            self.assertEqual(user_engine.cycle_mode(), "kde")
            self.assertEqual(user_engine.cycle_mode(), "omarchy")

            # Test consistency checker passes on valid user profiles
            self.assertTrue(check_consistency(PROJECT_ROOT, user_profiles_dir=user_dir))

            # 3. Add an invalid profile and ensure consistency check catches it
            invalid_file = user_dir / "bad.json"
            with open(invalid_file, "w", encoding="utf-8") as f:
                json.dump({
                    "id": "bad",
                    "name": "Bad Profile",
                    "bindings": [{"action": "non_existent_action_xyz", "mod": "SUPER", "key": "x"}]
                }, f)
            self.assertFalse(check_consistency(PROJECT_ROOT, user_profiles_dir=user_dir))

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
