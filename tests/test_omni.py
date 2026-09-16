#!/usr/bin/env python3
"""
OmniPal Automated Unit Tests
Tests schema consistency, state management, profile parsing, and plugin compliance.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.engine import OmniPalEngine, format_combo
from scripts.check_consistency import check_consistency

class TestOmniPal(unittest.TestCase):
    def setUp(self):
        self.engine = OmniPalEngine(PROJECT_ROOT)

    def tearDown(self):
        if hasattr(self.engine, "_last_summon_proc") and self.engine._last_summon_proc:
            try:
                self.engine._last_summon_proc.wait(timeout=0.2)
            except Exception:
                pass

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
        self.assertTrue(any("snap" == item["category"] for item in mac_sheet))
        self.assertTrue(any("ALT + LEFT" in item["key"] for item in mac_sheet))
        self.assertTrue(any("ALT + Z" in item["key"] for item in mac_sheet))

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
            self.assertEqual(state["active_bindings_count"], len(self.engine.profiles["windows"]["bindings"]))

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

    def test_snap_layouts_flyout(self):
        """Validates that snap('layouts') triggers the interactive flyout and records state."""
        from engine.engine import SNAP_FILE
        success = self.engine.snap("layouts")
        if hasattr(self.engine, "_last_summon_proc") and self.engine._last_summon_proc:
            try:
                self.engine._last_summon_proc.wait(timeout=0.5)
            except Exception:
                pass
        self.assertTrue(success)
        self.assertTrue(SNAP_FILE.exists())
        with open(SNAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("zone"), "layouts")
        self.assertTrue(data.get("interactive"))

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

    def test_display_metadata_and_reverse_cycle(self):
        """Validates display metadata presence and reverse mode cycling."""
        profiles = {p["id"]: p for p in self.engine.list_profiles()}
        self.assertIn("windows", profiles)
        self.assertIn("display", profiles["windows"])
        self.assertEqual(profiles["windows"]["display"].get("icon"), "⊞")
        self.assertEqual(profiles["windows"]["display"].get("brief"), "WIN")
        self.assertEqual(profiles["windows"]["display"].get("color"), "#3892d6")

        self.assertIn("mac", profiles)
        self.assertEqual(profiles["mac"]["display"].get("icon"), "◆")

        self.assertIn("omarchy", profiles)
        self.assertEqual(profiles["omarchy"]["display"].get("icon"), "⊡")

        # Test state includes display
        self.engine.switch_mode("windows")
        state = self.engine.get_state()
        self.assertEqual(state.get("display", {}).get("icon"), "⊞")

        # Test reverse cycle: windows -> omarchy -> mac -> windows
        self.assertEqual(self.engine.cycle_mode(reverse=True), "omarchy")
        self.assertEqual(self.engine.cycle_mode(reverse=True), "mac")
        self.assertEqual(self.engine.cycle_mode(reverse=True), "windows")

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

    def test_snap_model_and_dimensions(self):
        """Validates that SnapFeedback Model and QML define two-stage navigation and dimension calculations."""
        model_file = PROJECT_ROOT / "plugins" / "omni.snap-feedback" / "Model.js"
        self.assertTrue(model_file.exists())
        content = model_file.read_text(encoding="utf-8")
        self.assertIn("calculateBox", content)
        self.assertIn("dim:", content)
        self.assertIn("loadSchemaJson", content)

        qml_file = PROJECT_ROOT / "plugins" / "omni.snap-feedback" / "SnapFeedback.qml"
        self.assertTrue(qml_file.exists())
        qml_content = qml_file.read_text(encoding="utf-8")
        self.assertIn("focusedTemplateIndex", qml_content)
        self.assertIn("focusedSlotIndex", qml_content)
        self.assertIn("infoPill", qml_content)
        self.assertIn("Key_1", qml_content)
        self.assertIn("Key_Left", qml_content)
        self.assertIn("effectiveTemplates", qml_content)
        self.assertIn("currentReserved", qml_content)

    def test_snap_layouts_single_source_of_truth(self):
        """Validates that schema/snap_layouts.json is the single source of truth for zones and templates."""
        from engine.engine import SNAP_LAYOUTS_FILE
        schema_file = PROJECT_ROOT / "schema" / "snap_layouts.json"
        self.assertTrue(schema_file.exists())
        with open(schema_file, "r", encoding="utf-8") as f:
            schema_data = json.load(f)
        
        self.assertIn("zones", schema_data)
        self.assertIn("templates", schema_data)
        self.assertGreaterEqual(len(schema_data["zones"]), 15)
        self.assertEqual(len(schema_data["templates"]), 6)

        # Verify engine loaded from schema and wrote to tmpfs
        zones = self.engine.get_snap_zones()
        layouts = self.engine.get_snap_layouts()
        self.assertEqual(len(zones), len(schema_data["zones"]))
        self.assertEqual(len(layouts), len(schema_data["templates"]))
        self.assertTrue(SNAP_LAYOUTS_FILE.exists())

    def test_snap_unfloat_restore(self):
        """Validates that snap('restore') safely un-floats window back into tiling tree instead of forcing coordinates."""
        eval_codes = []
        original_eval = self.engine._eval_lua
        try:
            self.engine._eval_lua = lambda code: (eval_codes.append(code) or True)
            self.engine.snap("restore")
            self.assertEqual(len(eval_codes), 1)
            code = eval_codes[0]
            # Must check if window is floating and toggle float back to tiling
            self.assertIn("w.floating", code)
            self.assertIn("hl.dsp.window.float", code)
            self.assertIn("toggle", code)
        finally:
            self.engine._eval_lua = original_eval

    def test_snap_no_hud_flag(self):
        """Validates that snap with no_hud=True does not spawn shell summon process."""
        self.engine._last_summon_proc = None
        success = self.engine.snap("right", no_hud=True)
        self.assertTrue(success)
        self.assertIsNone(self.engine._last_summon_proc)

    def test_overview_zero_fork_architecture(self):
        """Validates that Overview.qml uses direct hyprctl --batch without process forking or python helper scripts."""
        overview_qml = PROJECT_ROOT / "plugins" / "omni.overview" / "Overview.qml"
        self.assertTrue(overview_qml.exists())
        content = overview_qml.read_text(encoding="utf-8")
        self.assertNotIn("python3", content)
        self.assertNotIn("sh -c", content)
        self.assertIn("--batch", content)
        self.assertIn("workspaces ; clients ; monitors ; activewindow", content)

class TestPersistenceManager(unittest.TestCase):
    """Validates the opt-in profile persistence isolated via OMNIPAL_CONFIG_DIR."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._saved_env = os.environ.get("OMNIPAL_CONFIG_DIR")
        os.environ["OMNIPAL_CONFIG_DIR"] = self._tmp_dir.name
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.persist_path = Path(self._tmp_dir.name) / "persistence.json"
        # Neutralize live Hyprland eval side effects for persistence flows.
        self._orig_eval = self.engine._eval_lua
        self.engine._eval_lua = lambda code: True

    def tearDown(self):
        self.engine._eval_lua = self._orig_eval
        if self._saved_env is None:
            os.environ.pop("OMNIPAL_CONFIG_DIR", None)
        else:
            os.environ["OMNIPAL_CONFIG_DIR"] = self._saved_env
        self._tmp_dir.cleanup()

    def test_default_state_is_disabled(self):
        """Fresh environment must report disabled with zero persistence files written."""
        status = self.engine.get_persistence_status()
        self.assertFalse(status["enabled"])
        self.assertIsNone(status["profile"])
        self.assertIsNone(status["updated_at"])
        self.assertEqual(status["path"], str(self.persist_path))
        self.assertFalse(self.persist_path.exists(), "默认零文件写入：不得创建 persistence.json")
        self.assertIsNone(self.engine.get_persisted_profile())

    def test_enable_disable_and_invalid_profile(self):
        """Enable/disable round-trip plus rejection of unknown profiles."""
        self.assertTrue(self.engine.set_persistence(True, "mac"))
        status = self.engine.get_persistence_status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["profile"], "mac")
        self.assertIsNotNone(status["updated_at"])
        self.assertTrue(self.persist_path.exists())
        self.assertEqual(self.engine.get_persisted_profile(), "mac")

        # Illegal profile must be refused without touching the stored state
        self.assertFalse(self.engine.set_persistence(True, "nonexistent_bogus"))
        status = self.engine.get_persistence_status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["profile"], "mac")

        self.assertTrue(self.engine.set_persistence(False))
        status = self.engine.get_persistence_status()
        self.assertFalse(status["enabled"])
        self.assertIsNone(status["profile"])
        self.assertFalse(self.persist_path.exists(), "关闭持久化必须彻底清理 persistence.json")
        self.assertIsNone(self.engine.get_persisted_profile())

    def test_switch_mode_autosyncs_persisted_profile(self):
        """switch_mode must mirror into persistence.json only while persistence is enabled."""
        self.assertTrue(self.engine.set_persistence(True, "windows"))
        self.assertTrue(self.engine.switch_mode("mac"))
        status = self.engine.get_persistence_status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["profile"], "mac")
        self.assertEqual(self.engine.get_persisted_profile(), "mac")

        # Disabled persistence stays fully inert during switches (zero writes)
        self.assertTrue(self.engine.set_persistence(False))
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertFalse(self.persist_path.exists())

    def test_enable_without_profile_uses_active_mode(self):
        """Enabling with no explicit profile persists the currently active mode."""
        self.assertTrue(self.engine.switch_mode("mac"))
        self.assertTrue(self.engine.set_persistence(True))
        self.assertEqual(self.engine.get_persistence_status()["profile"], "mac")

    def test_env_config_dir_isolation(self):
        """OMNIPAL_CONFIG_DIR must fully isolate every persistence read/write."""
        self.assertTrue(self.engine.set_persistence(True, "windows"))
        self.assertTrue(self.persist_path.exists())

        with tempfile.TemporaryDirectory() as other_dir:
            os.environ["OMNIPAL_CONFIG_DIR"] = other_dir
            status = self.engine.get_persistence_status()
            self.assertFalse(status["enabled"], "切换 OMNIPAL_CONFIG_DIR 后必须读写隔离")
            self.assertEqual(status["path"], str(Path(other_dir) / "persistence.json"))
            self.assertFalse((Path(other_dir) / "persistence.json").exists())
        os.environ["OMNIPAL_CONFIG_DIR"] = self._tmp_dir.name
        # Original directory state is untouched and visible again
        self.assertEqual(self.engine.get_persisted_profile(), "windows")

class TestUsageStatistics(unittest.TestCase):
    """Validates fully local usage statistics: isolation, increments, reset, and zero-impact fault tolerance."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._saved_env = os.environ.get("OMNIPAL_CONFIG_DIR")
        os.environ["OMNIPAL_CONFIG_DIR"] = self._tmp_dir.name
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.stats_path = Path(self._tmp_dir.name) / "stats.json"
        # Neutralize live Hyprland eval side effects for statistics flows.
        self._orig_eval = self.engine._eval_lua
        self.engine._eval_lua = lambda code: True

    def tearDown(self):
        self.engine._eval_lua = self._orig_eval
        if self._saved_env is None:
            os.environ.pop("OMNIPAL_CONFIG_DIR", None)
        else:
            os.environ["OMNIPAL_CONFIG_DIR"] = self._saved_env
        self._tmp_dir.cleanup()

    def test_initial_state_is_empty(self):
        """Fresh environment reports the canonical empty structure without creating any file."""
        stats = self.engine.get_stats()
        self.assertEqual(stats["switches"], {})
        self.assertEqual(stats["snaps"], {})
        self.assertEqual(stats["actions"], {})
        self.assertIsNone(stats["last_updated"])
        self.assertIsNone(stats["last_reset"])
        self.assertFalse(self.stats_path.exists())

    def test_switch_and_snap_increment_counters(self):
        """switch_mode and snap calls must aggregate per-mode / per-zone counts."""
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertTrue(self.engine.switch_mode("mac"))
        self.assertTrue(self.engine.switch_mode("windows"))
        stats = self.engine.get_stats()
        self.assertEqual(stats["switches"], {"windows": 2, "mac": 1})
        self.assertIsNotNone(stats["last_updated"])

        self.assertTrue(self.engine.snap("left", no_hud=True))
        self.assertTrue(self.engine.snap("left", no_hud=True))
        self.assertTrue(self.engine.snap("layouts", no_hud=True))
        stats = self.engine.get_stats()
        self.assertEqual(stats["snaps"]["left"], 2)
        self.assertEqual(stats["snaps"]["layouts"], 1)
        self.assertTrue(self.stats_path.exists())

    def test_record_action(self):
        """record_action increments per-action trigger counters."""
        self.engine.record_action("close_window")
        self.engine.record_action("close_window")
        self.engine.record_action("toggle_floating")
        self.assertEqual(
            self.engine.get_stats()["actions"],
            {"close_window": 2, "toggle_floating": 1}
        )

    def test_reset_stats(self):
        """reset_stats clears every bucket and stamps last_reset."""
        self.engine.record_switch("mac")
        self.engine.record_snap("right")
        self.assertTrue(self.engine.reset_stats())
        stats = self.engine.get_stats()
        self.assertEqual(stats["switches"], {})
        self.assertEqual(stats["snaps"], {})
        self.assertEqual(stats["actions"], {})
        self.assertIsNone(stats["last_updated"])
        self.assertIsNotNone(stats["last_reset"])

    def test_stats_failure_never_breaks_switch_or_snap(self):
        """Zero-impact guarantee: unwritable stats target must not affect live switching or snapping."""
        import engine.engine as engine_module
        self.assertTrue(self.engine.switch_mode("windows"))
        original = engine_module.stats_file_path
        try:
            engine_module.stats_file_path = lambda: Path("/proc/omnipal-invalid/stats.json")
            self.assertTrue(self.engine.switch_mode("mac"))
            self.assertTrue(self.engine.snap("right", no_hud=True))
            self.assertEqual(self.engine.get_state()["mode"], "mac")
        finally:
            engine_module.stats_file_path = original

    def test_env_config_dir_isolation(self):
        """OMNIPAL_CONFIG_DIR must fully isolate every statistics read/write."""
        self.engine.record_switch("windows")
        with tempfile.TemporaryDirectory() as other_dir:
            os.environ["OMNIPAL_CONFIG_DIR"] = other_dir
            self.assertEqual(self.engine.get_stats()["switches"], {}, "环境变量重定向后必须读写隔离")
            self.engine.record_snap("center")
            self.assertEqual(self.engine.get_stats()["snaps"], {"center": 1})
            self.assertFalse(self.stats_path.read_text(encoding="utf-8").count("center"),
                             "隔离目录中的记录不得回流原目录")
        os.environ["OMNIPAL_CONFIG_DIR"] = self._tmp_dir.name
        stats = self.engine.get_stats()
        self.assertEqual(stats["switches"], {"windows": 1})
        self.assertEqual(stats["snaps"], {})

class TestWindowPolicyAndModeIndicator(unittest.TestCase):
    """Validates window policy management, state synchronization, and Mode Indicator UI architecture."""

    def setUp(self):
        self.engine = OmniPalEngine(PROJECT_ROOT)
        # Neutralize live Hyprland eval side effects
        self._orig_eval = self.engine._eval_lua
        self.engine._eval_lua = lambda code: True

    def tearDown(self):
        self.engine._eval_lua = self._orig_eval
        # Reset policy to tiled for clean baseline
        self.engine.set_window_policy("tiled")

    def test_window_policy_default_and_set(self):
        """Verifies default policy is tiled and set_window_policy updates state accurately."""
        self.engine.set_window_policy("tiled")
        state = self.engine.get_state()
        self.assertEqual(state.get("window_policy"), "tiled")
        self.assertEqual(state.get("effective_window_mode"), "tiled")
        self.assertEqual(self.engine.get_window_policy(), "tiled")

        # Set to floating
        self.assertTrue(self.engine.set_window_policy("floating"))
        state = self.engine.get_state()
        self.assertEqual(state.get("window_policy"), "floating")
        self.assertEqual(state.get("effective_window_mode"), "floating")

        # Set to follow-profile
        self.assertTrue(self.engine.set_window_policy("follow-profile"))
        state = self.engine.get_state()
        self.assertEqual(state.get("window_policy"), "follow-profile")

        # Rejection of invalid policy
        self.assertFalse(self.engine.set_window_policy("invalid_bogus_policy"))
        self.assertEqual(self.engine.get_window_policy(), "follow-profile")

        # Rejection of profile name 'omarchy' as policy
        self.assertFalse(self.engine.set_window_policy("omarchy"))
        self.assertEqual(self.engine.get_window_policy(), "follow-profile")

        # Rejection of empty / null
        self.assertFalse(self.engine.set_window_policy(""))

    def test_window_policy_alias_normalization(self):
        """Verifies that common aliases (tile, float, follow) normalize to standard policy IDs."""
        self.assertTrue(self.engine.set_window_policy("tile"))
        self.assertEqual(self.engine.get_window_policy(), "tiled")

        self.assertTrue(self.engine.set_window_policy("float"))
        self.assertEqual(self.engine.get_window_policy(), "floating")

        self.assertTrue(self.engine.set_window_policy("follow"))
        self.assertEqual(self.engine.get_window_policy(), "follow-profile")

        self.assertTrue(self.engine.set_window_policy("follow_profile"))
        self.assertEqual(self.engine.get_window_policy(), "follow-profile")

    def test_follow_profile_effective_mode(self):
        """Verifies that follow-profile dynamically resolves to floating on mac, tiled elsewhere."""
        self.assertTrue(self.engine.set_window_policy("follow-profile"))

        self.assertTrue(self.engine.switch_mode("windows"))
        state = self.engine.get_state()
        self.assertEqual(state.get("effective_window_mode"), "tiled")

        self.assertTrue(self.engine.switch_mode("mac"))
        state = self.engine.get_state()
        self.assertEqual(state.get("effective_window_mode"), "floating")

        self.assertTrue(self.engine.switch_mode("omarchy"))
        state = self.engine.get_state()
        self.assertEqual(state.get("effective_window_mode"), "tiled")

    def test_window_policy_preserved_on_switch_and_restore(self):
        """Ensures that switching modes or restoring baseline does not reset window policy."""
        self.assertTrue(self.engine.set_window_policy("floating"))

        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertEqual(self.engine.get_window_policy(), "floating")

        self.assertTrue(self.engine.restore())
        self.assertEqual(self.engine.get_window_policy(), "floating")
        state = self.engine.get_state()
        self.assertEqual(state["window_policy"], "floating")

    def test_display_metadata_persistence_in_state(self):
        """Verifies that state.json includes display metadata (icon, brief, color) for Mode Indicator."""
        self.assertTrue(self.engine.switch_mode("windows"))
        state = self.engine.get_state()
        self.assertIn("display", state)
        self.assertEqual(state["display"].get("icon"), "⊞")
        self.assertEqual(state["display"].get("brief"), "WIN")
        self.assertEqual(state["display"].get("color"), "#3892d6")

        self.assertTrue(self.engine.switch_mode("mac"))
        state = self.engine.get_state()
        self.assertEqual(state["display"].get("icon"), "◆")
        self.assertEqual(state["display"].get("brief"), "MAC")

        self.assertTrue(self.engine.restore())
        state = self.engine.get_state()
        self.assertEqual(state["display"].get("icon"), "⊡")
        self.assertEqual(state["display"].get("brief"), "OMA")

    def test_cli_window_policy_commands(self):
        """Verifies bin/omni-profile window-policy CLI commands and aliases."""
        bin_path = str(PROJECT_ROOT / "bin" / "omni-profile")

        # 1. Status string output
        p1 = subprocess.run([bin_path, "window-policy"], capture_output=True, text=True)
        self.assertEqual(p1.returncode, 0)
        self.assertIn("OmniPal 窗口布局策略", p1.stdout)

        # 2. JSON status
        p2 = subprocess.run([bin_path, "window-policy", "--json"], capture_output=True, text=True)
        self.assertEqual(p2.returncode, 0)
        data = json.loads(p2.stdout)
        self.assertIn("window_policy", data)
        self.assertIn("effective_window_mode", data)

        # 3. Set via explicit subcommand
        p3 = subprocess.run([bin_path, "window-policy", "set", "floating"], capture_output=True, text=True)
        self.assertEqual(p3.returncode, 0)
        self.assertIn("已更新为: floating", p3.stdout)

        # 4. Set via alias command window-mode
        p4 = subprocess.run([bin_path, "window-mode", "set", "follow-profile"], capture_output=True, text=True)
        self.assertEqual(p4.returncode, 0)
        self.assertIn("已更新为: follow-profile", p4.stdout)

        # 5. Direct policy shorthand: omni-profile window-policy tiled
        p5 = subprocess.run([bin_path, "window-policy", "tiled"], capture_output=True, text=True)
        self.assertEqual(p5.returncode, 0)
        self.assertIn("已更新为: tiled", p5.stdout)

        # 6. Direct alias shorthand: omni-profile window-policy float
        p6 = subprocess.run([bin_path, "window-policy", "float"], capture_output=True, text=True)
        self.assertEqual(p6.returncode, 0)
        self.assertIn("已更新为: floating", p6.stdout)

        # 7. Rejection of invalid policy
        p7 = subprocess.run([bin_path, "window-policy", "set", "omarchy"], capture_output=True, text=True)
        self.assertNotEqual(p7.returncode, 0)
        self.assertIn("无效的窗口策略", p7.stderr)

    def test_mode_indicator_model_helpers(self):
        """Validates that Model.js contains window policy options and helper functions."""
        model_file = PROJECT_ROOT / "plugins" / "omni.mode-indicator" / "Model.js"
        self.assertTrue(model_file.exists())
        content = model_file.read_text(encoding="utf-8")
        self.assertIn("DEFAULT_POLICIES", content)
        self.assertIn("windowPolicies", content)
        self.assertIn("resolvePolicyName", content)
        self.assertIn("resolvePolicyIcon", content)
        self.assertIn("resolvePolicyDesc", content)
        self.assertIn("computeEffectiveMode", content)
        self.assertIn("normalizePolicy", content)
        self.assertIn("tiled", content)
        self.assertIn("floating", content)
        self.assertIn("follow-profile", content)

    def test_mode_indicator_model_execution_in_node(self):
        """Executes Model.js in Node.js to strictly test pure logic functions and fallback counts."""
        model_file = PROJECT_ROOT / "plugins" / "omni.mode-indicator" / "Model.js"
        js_code = f"""
        const fs = require('fs');
        const vm = require('vm');
        const content = fs.readFileSync('{model_file}', 'utf-8').replace('.pragma library', '');
        const ctx = {{}};
        vm.createContext(ctx);
        vm.runInContext(content, ctx);

        // Verify fallback profiles count
        const profs = ctx.fallbackProfiles();
        const win = profs.find(p => p.id === 'windows');
        const mac = profs.find(p => p.id === 'mac');
        if (!win || win.bindings_count !== 14) throw new Error('windows binding count mismatch: ' + (win ? win.bindings_count : null));
        if (!mac || mac.bindings_count !== 19) throw new Error('mac binding count mismatch: ' + (mac ? mac.bindings_count : null));

        // Verify aliases
        if (ctx.resolvePolicyName('follow') !== '跟随') throw new Error('alias follow failed');
        if (ctx.resolvePolicyName('float') !== '浮动') throw new Error('alias float failed');
        if (ctx.resolvePolicyName('tile') !== '平铺') throw new Error('alias tile failed');

        // Verify computeEffectiveMode
        if (ctx.computeEffectiveMode('follow', 'mac') !== 'floating') throw new Error('follow mac != floating');
        if (ctx.computeEffectiveMode('follow', 'windows') !== 'tiled') throw new Error('follow windows != tiled');
        if (ctx.computeEffectiveMode('float', 'windows') !== 'floating') throw new Error('float windows != floating');
        """
        res = subprocess.run(["node", "-e", js_code], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Node execution error: {res.stderr}")

    def test_mode_indicator_qml_and_ipc_structure(self):
        """Validates that BarWidget.qml embeds PopupCard with window policy controls and IPC."""
        qml_file = PROJECT_ROOT / "plugins" / "omni.mode-indicator" / "BarWidget.qml"
        self.assertTrue(qml_file.exists())
        content = qml_file.read_text(encoding="utf-8")
        self.assertIn("PopupCard", content)
        self.assertIn("windowPolicy", content)
        self.assertIn("effectiveWindowMode", content)
        self.assertIn("compositorConnected", content)
        self.assertIn("policyOptions", content)
        self.assertIn("effPolicyBadge", content)
        self.assertIn("setPolicy", content)
        self.assertIn("getWindowPolicy", content)
        self.assertIn("getEffectiveWindowMode", content)
        self.assertIn("setWindowPolicy", content)
        self.assertIn("closePanel", content)
        self.assertIn("releasePopout", content)

    def test_mode_indicator_manifest(self):
        """Validates manifest compliance and metadata."""
        manifest_file = PROJECT_ROOT / "plugins" / "omni.mode-indicator" / "manifest.json"
        self.assertTrue(manifest_file.exists())
        with open(manifest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["id"], "omni.mode-indicator")
        self.assertEqual(data["entryPoints"]["barWidget"], "BarWidget.qml")

    def test_multi_instance_window_policy_sync_and_anti_clobber(self):
        """Validates that concurrent/daemon engine instances do not clobber externally updated window policy."""
        e1 = OmniPalEngine(PROJECT_ROOT)
        e2 = OmniPalEngine(PROJECT_ROOT)

        # 1. e2 sets policy to floating
        self.assertTrue(e2.set_window_policy("floating"))
        self.assertEqual(e2.get_window_policy(), "floating")

        # 2. e1 should dynamically observe the updated policy without restart
        self.assertEqual(e1.get_window_policy(), "floating")
        self.assertEqual(e1.get_effective_window_mode("windows"), "floating")

        # 3. e1 switches mode or restores baseline; must NOT clobber window policy back to tiled
        self.assertTrue(e1.switch_mode("windows"))
        self.assertEqual(e1.get_window_policy(), "floating")
        self.assertEqual(e2.get_window_policy(), "floating")

        self.assertTrue(e1.restore())
        self.assertEqual(e1.get_window_policy(), "floating")
        state = e1.get_state()
        self.assertEqual(state.get("window_policy"), "floating")

        # Reset for subsequent tests
        e1.set_window_policy("tiled")

    def test_cli_window_policy_json_flags(self):
        """Verifies that --json works on set and direct shortcut subcommands."""
        bin_path = str(PROJECT_ROOT / "bin" / "omni-profile")

        p1 = subprocess.run([bin_path, "window-policy", "set", "floating", "--json"], capture_output=True, text=True)
        self.assertEqual(p1.returncode, 0)
        data1 = json.loads(p1.stdout)
        self.assertTrue(data1.get("success"))
        self.assertEqual(data1.get("window_policy"), "floating")

        p2 = subprocess.run([bin_path, "window-policy", "tile", "--json"], capture_output=True, text=True)
        self.assertEqual(p2.returncode, 0)
        data2 = json.loads(p2.stdout)
        self.assertTrue(data2.get("success"))
        self.assertEqual(data2.get("window_policy"), "tiled")

    def test_qml_syntax_via_qmllint(self):
        """Verifies that BarWidget.qml passes Qt6 qmllint syntax checking."""
        qmllint_bin = "/usr/lib/qt6/bin/qmllint"
        if not os.path.exists(qmllint_bin):
            self.skipTest("qmllint not installed on system")

        qml_path = str(PROJECT_ROOT / "plugins" / "omni.mode-indicator" / "BarWidget.qml")
        p = subprocess.run([
            qmllint_bin,
            "-I", "/usr/share/omarchy/shell",
            "-I", str(PROJECT_ROOT / "plugins" / "omni.mode-indicator"),
            qml_path
        ], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"qmllint failed: {p.stderr}")

    def test_normalize_policy_safeguards_in_node(self):
        """Verifies that Model.js normalizePolicy safely defaults to tiled for corrupted/unknown inputs."""
        model_file = PROJECT_ROOT / "plugins" / "omni.mode-indicator" / "Model.js"
        js_code = f"""
        const fs = require('fs');
        const vm = require('vm');
        const content = fs.readFileSync('{model_file}', 'utf-8').replace('.pragma library', '');
        const ctx = {{}};
        vm.createContext(ctx);
        vm.runInContext(content, ctx);

        // All invalid/unknown/empty inputs must normalize safely to 'tiled'
        if (ctx.normalizePolicy(null) !== 'tiled') throw new Error('null failed');
        if (ctx.normalizePolicy(undefined) !== 'tiled') throw new Error('undefined failed');
        if (ctx.normalizePolicy('') !== 'tiled') throw new Error('empty string failed');
        if (ctx.normalizePolicy('invalid_garbage') !== 'tiled') throw new Error('garbage failed');
        if (ctx.normalizePolicy('unknown') !== 'tiled') throw new Error('unknown failed');

        // Valid aliases must continue to resolve accurately
        if (ctx.normalizePolicy('tile') !== 'tiled') throw new Error('tile failed');
        if (ctx.normalizePolicy('tiled') !== 'tiled') throw new Error('tiled failed');
        if (ctx.normalizePolicy('float') !== 'floating') throw new Error('float failed');
        if (ctx.normalizePolicy('floating') !== 'floating') throw new Error('floating failed');
        if (ctx.normalizePolicy('follow') !== 'follow-profile') throw new Error('follow failed');
        if (ctx.normalizePolicy('follow-profile') !== 'follow-profile') throw new Error('follow-profile failed');
        if (ctx.normalizePolicy('follow_profile') !== 'follow-profile') throw new Error('follow_profile failed');
        """
        res = subprocess.run(["node", "-e", js_code], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Node execution error: {res.stderr}")

    def test_corrupted_state_policy_recovery(self):
        """Verifies that engine and CLI recover safely when state.json is corrupted or contains invalid policy types."""
        from engine.engine import STATE_FILE
        # Backup existing state
        orig_state_text = STATE_FILE.read_text(encoding="utf-8") if STATE_FILE.exists() else None
        try:
            # 1. Non-dict JSON in state.json
            STATE_FILE.write_text("[1, 2, 3]", encoding="utf-8")
            self.assertEqual(self.engine.get_window_policy(), "tiled")
            self.assertEqual(self.engine.get_effective_window_mode(), "tiled")
            st = self.engine.get_state()
            self.assertEqual(st.get("window_policy"), "tiled")

            # 2. Corrupted raw syntax in state.json
            STATE_FILE.write_text("NOT_VALID_JSON{{{", encoding="utf-8")
            self.assertEqual(self.engine.get_window_policy(), "tiled")
            self.assertEqual(self.engine.get_effective_window_mode(), "tiled")
            st = self.engine.get_state()
            self.assertEqual(st.get("window_policy"), "tiled")

            # 3. Invalid policy value inside valid dict
            STATE_FILE.write_text(json.dumps({"mode": "omarchy", "window_policy": "bogus_gibberish"}), encoding="utf-8")
            self.assertEqual(self.engine.get_window_policy(), "tiled")
            self.assertEqual(self.engine.get_effective_window_mode(), "tiled")
        finally:
            if orig_state_text is not None:
                STATE_FILE.write_text(orig_state_text, encoding="utf-8")
            elif STATE_FILE.exists():
                STATE_FILE.unlink()

    def test_snap_with_target_address(self):
        """Verifies that snap accepts target_address and records it in snap.json."""
        from engine.engine import SNAP_FILE
        test_addr = "0x12345678abcd"
        self.engine.snap("left", target_address=test_addr, no_hud=True)
        self.assertTrue(SNAP_FILE.exists())
        data = json.loads(SNAP_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data.get("zone"), "left")
        self.assertEqual(data.get("target_window"), test_addr)

    def test_snap_layouts_target_window_record(self):
        """Verifies that snap layouts records target_window (either cursor-detected or None)."""
        from engine.engine import SNAP_FILE
        self.engine.snap("layouts", no_hud=True)
        self.assertTrue(SNAP_FILE.exists())
        data = json.loads(SNAP_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data.get("zone"), "layouts")
        self.assertTrue(data.get("interactive"))
        self.assertIn("target_window", data)

    def test_get_window_under_cursor_robustness(self):
        """Ensures get_window_under_cursor executes without crashing under arbitrary environment."""
        res = self.engine.get_window_under_cursor()
        if res is not None:
            self.assertIsInstance(res, dict)
            self.assertIn("address", res)

if __name__ == "__main__":
    unittest.main()


