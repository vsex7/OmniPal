#!/usr/bin/env python3
"""
OmniPal Automated Unit Tests
Tests schema consistency, state management, profile parsing, and plugin compliance.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import shutil as _shutil
if not _shutil.which("hyprctl") or os.environ.get("OMNIPAL_FAKE_HYPRCTL") == "1":
    os.environ["PATH"] = str(Path(__file__).resolve().parent / "fakebin") + os.pathsep + os.environ.get("PATH", "")
if not os.environ.get("XDG_RUNTIME_DIR") or not os.path.isdir(os.environ["XDG_RUNTIME_DIR"]):
    os.environ["XDG_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="omnipal-test-")

# Isolate both config and run directories before loading engine to prevent mutating host desktop state
_GLOBAL_TEST_CONFIG_DIR = tempfile.TemporaryDirectory()
os.environ["OMNIPAL_CONFIG_DIR"] = _GLOBAL_TEST_CONFIG_DIR.name
_GLOBAL_TEST_RUN_DIR = tempfile.TemporaryDirectory()
os.environ["OMNIPAL_RUN_DIR"] = _GLOBAL_TEST_RUN_DIR.name
os.environ["OMNIPAL_DRY_RUN"] = "1"

import engine.engine as engine_module
from engine.engine import OmniPalEngine, format_combo
# NOTE(structure): engine internals moved to the engine.omnipal package;
# monkeypatch seams now target the namespace where names are looked up.
from engine.omnipal import core as _engine_core
from scripts.check_consistency import check_consistency

def _ensure_global_test_env():
    global _GLOBAL_TEST_CONFIG_DIR, _GLOBAL_TEST_RUN_DIR
    if _GLOBAL_TEST_CONFIG_DIR is None:
        _GLOBAL_TEST_CONFIG_DIR = tempfile.TemporaryDirectory()
    if _GLOBAL_TEST_RUN_DIR is None:
        _GLOBAL_TEST_RUN_DIR = tempfile.TemporaryDirectory()
    os.environ["OMNIPAL_CONFIG_DIR"] = _GLOBAL_TEST_CONFIG_DIR.name
    os.environ["OMNIPAL_RUN_DIR"] = _GLOBAL_TEST_RUN_DIR.name
    os.environ["OMNIPAL_DRY_RUN"] = "1"
    engine_module._resolve_run_dir()

def setUpModule():
    _ensure_global_test_env()

def tearDownModule():
    global _GLOBAL_TEST_CONFIG_DIR, _GLOBAL_TEST_RUN_DIR
    os.environ.pop("OMNIPAL_CONFIG_DIR", None)
    os.environ.pop("OMNIPAL_RUN_DIR", None)
    os.environ.pop("OMNIPAL_DRY_RUN", None)
    if _GLOBAL_TEST_CONFIG_DIR:
        _GLOBAL_TEST_CONFIG_DIR.cleanup()
        _GLOBAL_TEST_CONFIG_DIR = None
    if _GLOBAL_TEST_RUN_DIR:
        _GLOBAL_TEST_RUN_DIR.cleanup()
        _GLOBAL_TEST_RUN_DIR = None

class BaseOmniTestCase(unittest.TestCase):
    """Base test case ensuring test isolation and preventing desktop environment leakage."""
    def setUp(self):
        super().setUp()
        _ensure_global_test_env()

    def tearDown(self):
        super().tearDown()
        _ensure_global_test_env()

class TestOmniPal(BaseOmniTestCase):
    def setUp(self):
        super().setUp()
        self.engine = OmniPalEngine(PROJECT_ROOT)

    def tearDown(self):
        super().tearDown()
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
        self.assertEqual(format_combo("SUPER", "comma"), "SUPER + COMMA")
        self.assertEqual(format_combo("SUPER", "slash"), "SUPER + SLASH")

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

    def test_all_plugins_exist(self):
        """Validates that all required Quickshell plugins exist with entry points."""
        expected_plugins = [
            "omni.mode-indicator",
            "omni.cheat-sheet",
            "omni.settings",
            "omni.snap-feedback",
            "omni.mac-dock",
            "omni.overview"
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
        from engine.engine import _resolve_run_dir, STATE_FILE, OVERLAY_FILE, RUN_DIR
        orig_run_dir = os.environ.pop("OMNIPAL_RUN_DIR", None)
        try:
            default_dir = _resolve_run_dir()
            expected_base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
            self.assertEqual(str(default_dir), str(Path(expected_base) / "omnipal"))
        finally:
            _ensure_global_test_env()
        self.assertTrue(str(RUN_DIR).startswith("/run/user/") or str(RUN_DIR).startswith(tempfile.gettempdir()) or "/tmp" in str(RUN_DIR))
        self.assertTrue(str(STATE_FILE).startswith("/run/user/") or str(STATE_FILE).startswith(tempfile.gettempdir()) or "/tmp" in str(STATE_FILE))
        self.assertTrue(str(OVERLAY_FILE).startswith("/run/user/") or str(OVERLAY_FILE).startswith(tempfile.gettempdir()) or "/tmp" in str(OVERLAY_FILE))
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
            # 1. Create a brand new custom profile 'gnome'
            gnome_file = user_dir / "gnome.json"
            gnome_data = {
                "id": "gnome",
                "name": "GNOME 模式",
                "description": "User custom GNOME bindings",
                "bindings": [
                    {"action": "file_manager", "mod": "CTRL ALT", "key": "e"}
                ]
            }
            with open(gnome_file, "w", encoding="utf-8") as f:
                json.dump(gnome_data, f)

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

            self.assertIn("gnome", user_engine.profiles)
            self.assertEqual(profiles_meta["gnome"]["source"], "user")
            self.assertFalse(profiles_meta["gnome"]["override"])

            self.assertIn("windows", user_engine.profiles)
            self.assertEqual(profiles_meta["windows"]["source"], "user")
            self.assertTrue(profiles_meta["windows"]["override"])
            self.assertEqual(user_engine.profiles["windows"]["name"], "Windows (Custom Overridden)")

            # Test dynamic cycling order: omarchy -> windows -> mac -> gnome -> omarchy
            user_engine.switch_mode("omarchy")
            self.assertEqual(user_engine.cycle_mode(), "windows")
            self.assertEqual(user_engine.cycle_mode(), "mac")
            self.assertEqual(user_engine.cycle_mode(), "gnome")
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
        self.assertEqual(set(profiles), {"windows", "mac", "omarchy"})

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

    def test_restore_failure_retains_overlay_and_state(self):
        """A failed compositor restore must remain retryable without losing tracking."""
        from engine.engine import OVERLAY_FILE
        overlay = [{"action": "window_close", "combo": "ALT + F4", "name": "Close Window"}]
        self.engine._write_active_overlay(overlay)
        self.engine._write_state("windows", len(overlay))
        original_eval = self.engine._eval_lua
        try:
            self.engine._eval_lua = lambda code: False
            self.assertFalse(self.engine.restore())
            self.assertTrue(OVERLAY_FILE.exists())
            self.assertEqual(self.engine.get_state().get("mode"), "windows")

            self.engine._eval_lua = lambda code: True
            self.assertTrue(self.engine.restore())
            self.assertFalse(OVERLAY_FILE.exists())
            self.assertEqual(self.engine.get_state().get("mode"), "omarchy")
        finally:
            self.engine._eval_lua = original_eval

    def test_restore_reload_failure_retains_overlay_and_floating_state(self):
        """A successful Lua restore must not report success until policy reload succeeds."""
        from engine.engine import APPLIED_WINDOW_MODE_FILE, OVERLAY_FILE

        overlay = [{"action": "window_close", "combo": "ALT + F4", "name": "Close Window"}]
        self.engine._write_active_overlay(overlay)
        self.engine._write_state("windows", len(overlay))
        self.engine._set_applied_window_mode("floating")

        original_eval = self.engine._eval_lua
        original_reload = self.engine._reload_config_only
        try:
            self.engine._eval_lua = lambda code: True
            self.engine._eval_lua_strict = lambda code: False
            self.engine._reload_config_only = lambda: False
            self.assertFalse(self.engine.restore())
            self.assertTrue(OVERLAY_FILE.exists())
            self.assertEqual(APPLIED_WINDOW_MODE_FILE.read_text(encoding="utf-8"), "floating")
            self.assertEqual(self.engine.get_state().get("mode"), "windows")

            self.engine._reload_config_only = lambda: True
            self.assertTrue(self.engine.restore())
            self.assertFalse(OVERLAY_FILE.exists())
            self.assertEqual(APPLIED_WINDOW_MODE_FILE.read_text(encoding="utf-8"), "tiled")
            self.assertEqual(self.engine.get_state().get("mode"), "omarchy")
        finally:
            self.engine._eval_lua = original_eval
            self.engine._reload_config_only = original_reload

    def test_compositor_mutation_dry_run(self):
        """Tests can execute Engine code without sending Lua to the live compositor."""
        from unittest.mock import patch
        with patch("engine.engine.subprocess.run", side_effect=AssertionError("live eval attempted")):
            self.assertTrue(self.engine._eval_lua("hl.unbind('SUPER + X')"))

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

    def test_resolve_run_dir_precedence(self):
        """Validates that _resolve_run_dir honors OMNIPAL_RUN_DIR > XDG_RUNTIME_DIR > /run/user/<uid>."""
        from engine.engine import _resolve_run_dir
        orig_run_dir = os.environ.get("OMNIPAL_RUN_DIR")
        orig_xdg = os.environ.get("XDG_RUNTIME_DIR")
        try:
            # 1. Custom OMNIPAL_RUN_DIR
            os.environ["OMNIPAL_RUN_DIR"] = "/tmp/custom_omnipal_test"
            self.assertEqual(str(_resolve_run_dir()), "/tmp/custom_omnipal_test")

            # 2. Fallback to XDG_RUNTIME_DIR
            os.environ.pop("OMNIPAL_RUN_DIR", None)
            os.environ["XDG_RUNTIME_DIR"] = "/tmp/mock_xdg"
            self.assertEqual(str(_resolve_run_dir()), "/tmp/mock_xdg/omnipal")

            # 3. Fallback to /run/user/<uid>/omnipal
            os.environ.pop("XDG_RUNTIME_DIR", None)
            self.assertEqual(str(_resolve_run_dir()), f"/run/user/{os.getuid()}/omnipal")
        finally:
            if orig_xdg is not None:
                os.environ["XDG_RUNTIME_DIR"] = orig_xdg
            else:
                os.environ.pop("XDG_RUNTIME_DIR", None)
            _ensure_global_test_env()

    def test_verify_overlay_bindings(self):
        """Verifies that verify_overlay_bindings correctly detects missing vs present bindings."""
        import subprocess
        # In omarchy mode, always returns True
        self.engine._write_state("omarchy", 0)
        self.assertTrue(self.engine.verify_overlay_bindings())

        # In windows mode with no overlay file, returns False
        self.engine._write_state("windows", 10)
        from engine.engine import OVERLAY_FILE
        if OVERLAY_FILE.exists():
            OVERLAY_FILE.unlink()
        self.assertFalse(self.engine.verify_overlay_bindings())

        # Write mock overlay
        self.engine._write_active_overlay([
            {"action": "window_close", "combo": "ALT + F4", "name": "Close Window"}
        ])

        # Mock hyprctl binds -j returning matching or missing description
        orig_run = subprocess.run
        try:
            class MockCompletedProcess:
                def __init__(self, stdout):
                    self.stdout = stdout
                    self.returncode = 0

            # Missing description
            subprocess.run = lambda *args, **kwargs: MockCompletedProcess('[{"description": "Other Action"}]')
            self.assertFalse(self.engine.verify_overlay_bindings())

            # Present description
            subprocess.run = lambda *args, **kwargs: MockCompletedProcess('[{"description": "Close Window"}]')
            self.assertTrue(self.engine.verify_overlay_bindings())
        finally:
            subprocess.run = orig_run
            self.engine.restore()

class TestPersistenceManager(BaseOmniTestCase):
    """Validates the opt-in profile persistence isolated via OMNIPAL_CONFIG_DIR."""

    def setUp(self):
        super().setUp()
        self._tmp_dir = tempfile.TemporaryDirectory()
        os.environ["OMNIPAL_CONFIG_DIR"] = self._tmp_dir.name
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.persist_path = Path(self._tmp_dir.name) / "persistence.json"
        # Neutralize live Hyprland eval side effects for persistence flows.
        self._orig_eval = self.engine._eval_lua
        self.engine._eval_lua = lambda code: True

    def tearDown(self):
        self.engine._eval_lua = self._orig_eval
        self._tmp_dir.cleanup()
        super().tearDown()

    def test_default_state_is_enabled(self):
        """Fresh environment defaults to enabled persistence to remember last configuration across reboots."""
        status = self.engine.get_persistence_status()
        self.assertTrue(status["enabled"])
        self.assertIsNone(status["profile"])
        self.assertIsNone(status["window_policy"])
        self.assertIsNone(status["updated_at"])
        self.assertEqual(status["path"], str(self.persist_path))
        self.assertFalse(self.persist_path.exists(), "惰性写入：首次配置变更前不强行创建文件")
        self.assertIsNone(self.engine.get_persisted_profile())
        self.assertIsNone(self.engine.get_persisted_window_policy())

    def test_enable_disable_and_invalid_profile(self):
        """Enable/disable round-trip, window policy stored, rejection of unknown profiles."""
        self.assertTrue(self.engine.set_persistence(True, "mac", "floating"))
        status = self.engine.get_persistence_status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["profile"], "mac")
        self.assertIsNotNone(status["updated_at"])
        self.assertTrue(self.persist_path.exists())
        self.assertEqual(status["window_policy"], "floating")
        self.assertEqual(json.loads(self.persist_path.read_text(encoding="utf-8"))["window_policy"], "floating")
        self.assertEqual(self.engine.get_persisted_profile(), "mac")
        self.assertEqual(self.engine.get_persisted_window_policy(), "floating")

        # Illegal profile must be refused without touching the stored state
        self.assertFalse(self.engine.set_persistence(True, "nonexistent_bogus"))
        status = self.engine.get_persistence_status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["profile"], "mac")

        self.assertTrue(self.engine.set_persistence(False))
        status = self.engine.get_persistence_status()
        self.assertFalse(status["enabled"])
        self.assertIsNone(status["profile"])
        self.assertIsNone(status["window_policy"])
        self.assertIsNone(self.engine.get_persisted_profile())
        self.assertIsNone(self.engine.get_persisted_window_policy())

    def test_switch_mode_autosync(self):
        """switch_mode must mirror into persistence.json when persistence is enabled."""
        self.assertTrue(self.engine.switch_mode("windows"))
        status = self.engine.get_persistence_status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["profile"], "windows")
        self.assertEqual(self.engine.get_persisted_profile(), "windows")

        self.assertTrue(self.engine.switch_mode("mac"))
        self.assertEqual(self.engine.get_persistence_status()["profile"], "mac")

        self.assertTrue(self.engine.switch_mode("omarchy"))
        self.assertEqual(self.engine.get_persistence_status()["profile"], "omarchy")

        # Disabled persistence stays fully inert during switches
        self.assertTrue(self.engine.set_persistence(False))
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertIsNone(self.engine.get_persisted_profile())

    def test_enable_without_profile_uses_active_mode(self):
        """Enabling with no explicit profile persists the currently active mode."""
        self.assertTrue(self.engine.switch_mode("mac"))
        self.assertTrue(self.engine.set_persistence(True))
        self.assertEqual(self.engine.get_persistence_status()["profile"], "mac")

    def test_restore_autosyncs_persistence(self):
        """Direct restore (CLI/bar/settings path) must mirror omarchy into persistence.json."""
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertEqual(self.engine.get_persisted_profile(), "windows")

        self.assertTrue(self.engine.restore())
        self.assertEqual(self.engine.get_state().get("mode"), "omarchy")
        self.assertEqual(self.engine.get_persistence_status()["profile"], "omarchy")
        self.assertEqual(self.engine.get_persisted_profile(), "omarchy")
        self.assertEqual(
            json.loads(self.persist_path.read_text(encoding="utf-8"))["profile"],
            "omarchy",
        )

        # Disabled persistence stays inert during restore
        self.assertTrue(self.engine.set_persistence(False))
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertTrue(self.engine.restore())
        self.assertIsNone(self.engine.get_persisted_profile())
        self.assertFalse(self.engine.get_persistence_status()["enabled"])

    def test_restore_can_skip_persistence_sync(self):
        """Daemon shutdown restore must not overwrite the last chosen persisted profile."""
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertEqual(self.engine.get_persisted_profile(), "windows")

        self.assertTrue(self.engine.restore(sync_persistence=False))
        self.assertEqual(self.engine.get_state().get("mode"), "omarchy")
        self.assertEqual(self.engine.get_persisted_profile(), "windows")
        self.assertEqual(
            json.loads(self.persist_path.read_text(encoding="utf-8"))["profile"],
            "windows",
        )

    def test_enable_snapshots_current_over_stale_persisted(self):
        """persist enable without --profile prefers live mode over a stale persisted profile."""
        self.assertTrue(self.engine.set_persistence(True, "windows", "tiled"))
        # Simulate a restore that failed to sync (or sync_persistence=False), leaving stale profile.
        self.assertTrue(self.engine.restore(sync_persistence=False))
        self.assertEqual(self.engine.get_state().get("mode"), "omarchy")
        self.assertEqual(self.engine.get_persisted_profile(), "windows")

        self.assertTrue(self.engine.set_persistence(True))
        self.assertEqual(self.engine.get_persistence_status()["profile"], "omarchy")
        self.assertEqual(self.engine.get_persisted_profile(), "omarchy")

    def test_env_config_dir_isolation(self):
        """OMNIPAL_CONFIG_DIR must fully isolate every persistence read/write."""
        self.assertTrue(self.engine.set_persistence(True, "windows"))
        self.assertTrue(self.persist_path.exists())

        with tempfile.TemporaryDirectory() as other_dir:
            os.environ["OMNIPAL_CONFIG_DIR"] = other_dir
            status = self.engine.get_persistence_status()
            self.assertEqual(status["path"], str(Path(other_dir) / "persistence.json"))
            self.assertFalse((Path(other_dir) / "persistence.json").exists())
            self.assertIsNone(self.engine.get_persisted_profile())
        os.environ["OMNIPAL_CONFIG_DIR"] = self._tmp_dir.name
        self.assertEqual(self.engine.get_persisted_profile(), "windows")

    def test_reboot_restoration_across_clean_tmpfs(self):
        """Simulate reboot: tmpfs state wiped, engine reconstructs the persisted mode."""
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertEqual(self.engine.get_persisted_profile(), "windows")
        self.engine.restore()
        self.engine.set_persistence(True, "windows")

        with tempfile.TemporaryDirectory() as fresh_run_dir:
            orig_run_dir_env = os.environ.get("OMNIPAL_RUN_DIR")
            os.environ["OMNIPAL_RUN_DIR"] = fresh_run_dir
            engine_module._resolve_run_dir()
            try:
                self.assertFalse(engine_module.STATE_FILE.exists())
                fresh_engine = OmniPalEngine(PROJECT_ROOT)
                self.assertEqual(fresh_engine.get_persisted_profile(), "windows")
            finally:
                if orig_run_dir_env is not None:
                    os.environ["OMNIPAL_RUN_DIR"] = orig_run_dir_env
                else:
                    os.environ.pop("OMNIPAL_RUN_DIR", None)
                engine_module._resolve_run_dir()

    def test_stored_window_policy_is_kept_and_restored(self):
        """No startup migration: a stored global policy survives and is honoured (follow-profile restored)."""
        from engine.engine import STATE_FILE
        self.assertFalse(hasattr(self.engine, "migrate_legacy_window_policy"))
        self.persist_path.write_text(json.dumps({"enabled": True, "profile": "windows", "window_policy": "floating"}), encoding="utf-8")
        STATE_FILE.write_text(json.dumps({"mode": "windows", "window_policy": "floating"}), encoding="utf-8")
        state = self.engine.get_state()
        self.assertEqual(state["window_policy"], "floating")
        self.assertEqual(state["effective_window_mode"], "floating")
        self.assertEqual(self.engine.get_persisted_window_policy(), "floating")
        self.assertEqual(json.loads(self.persist_path.read_text(encoding="utf-8"))["window_policy"], "floating")
        STATE_FILE.write_text(json.dumps({"mode": "omarchy", "window_policy": "follow-profile"}), encoding="utf-8")
        self.engine.window_policy = "follow-profile"

class TestWindowPolicyAndModeIndicator(BaseOmniTestCase):
    """Validates window policy management, state synchronization, and Mode Indicator UI architecture."""

    def setUp(self):
        super().setUp()
        # Pretend a compositor socket exists so window-policy paths run without a live Hyprland (CI)
        from unittest.mock import patch
        fd, sock_path = tempfile.mkstemp(prefix="omnipal-fake-socket2-")
        os.close(fd)
        self._fake_sock = Path(sock_path)
        self._sock_patch = patch.object(_engine_core, "find_socket2_path", return_value=self._fake_sock)
        self._sock_patch.start()
        self.engine = OmniPalEngine(PROJECT_ROOT)
        # Neutralize live Hyprland eval side effects
        self._orig_eval = self.engine._eval_lua
        self.engine._eval_lua = lambda code: True

    def tearDown(self):
        self.engine._eval_lua = self._orig_eval
        self._sock_patch.stop()
        self._fake_sock.unlink(missing_ok=True)
        super().tearDown()

    def test_window_policy_api_and_stats_removed(self):
        """Global policy API is back; usage-stats API stays removed."""
        for present in ("set_window_policy", "get_window_policy", "get_persisted_window_policy"):
            self.assertTrue(hasattr(self.engine, present), present)
        for gone in ("get_stats", "reset_stats", "record_switch", "record_snap", "record_action", "_record_stat",
                     "migrate_legacy_window_policy"):
            self.assertFalse(hasattr(self.engine, gone), gone)
        state = self.engine.get_state()
        self.assertIn("window_policy", state)
        self.assertIn("effective_window_mode", state)

    def test_set_window_policy_overrides_and_follows(self):
        """tiled/floating override every mode's window_mode; follow-profile hands it back."""
        try:
            self.assertTrue(self.engine.switch_mode("windows"))
            self.assertTrue(self.engine.set_window_policy("floating"))
            st = self.engine.get_state()
            self.assertEqual(st["window_policy"], "floating")
            self.assertEqual(st["effective_window_mode"], "floating")
            self.assertEqual(self.engine.get_persistence_status()["window_policy"], "floating")
            # survives a mode switch
            self.assertTrue(self.engine.switch_mode("mac"))
            self.assertEqual(self.engine.get_state()["window_policy"], "floating")
            self.assertTrue(self.engine.set_window_policy("tiled"))
            self.assertEqual(self.engine.get_state()["effective_window_mode"], "tiled")
            self.assertTrue(self.engine.set_window_policy("follow-profile"))
            self.assertEqual(self.engine.get_state()["effective_window_mode"], "floating")  # mac's own
            self.assertFalse(self.engine.set_window_policy("bogus"))
            self.assertEqual(self.engine.get_window_policy(), "follow-profile")
        finally:
            self.engine.set_window_policy("follow-profile")
            self.engine.restore()

    def test_rejected_policy_rolls_back(self):
        self.engine.set_window_policy("follow-profile")
        orig = self.engine._apply_window_policy
        self.engine._apply_window_policy = lambda *a, **k: False
        try:
            self.assertFalse(self.engine.set_window_policy("floating"))
            self.assertEqual(self.engine.get_window_policy(), "follow-profile")
        finally:
            self.engine._apply_window_policy = orig

    def test_tiled_disables_float_rules_without_reload(self):
        from engine.engine import APPLIED_WINDOW_MODE_FILE
        import engine.engine as E
        self.engine._write_state("windows", 1)
        APPLIED_WINDOW_MODE_FILE.write_text("floating", encoding="utf-8")
        calls, orig = [], (self.engine._reload_config_only, _engine_core.find_socket2_path)
        try:
            self.engine._reload_config_only = lambda timeout=3.0: calls.append("reload") or True
            self.engine._eval_lua_strict = lambda code: calls.append(code) or True
            self.engine._unfloat_existing_windows = lambda: None
            _engine_core.find_socket2_path = lambda: Path("/")
            self.assertTrue(self.engine._apply_window_policy(force=True))
            self.assertNotIn("reload", calls)
            self.assertTrue(any("set_enabled(false)" in c for c in calls))
        finally:
            self.engine._reload_config_only, _engine_core.find_socket2_path = orig
            self.engine._write_state("omarchy", 0)
            APPLIED_WINDOW_MODE_FILE.write_text("tiled", encoding="utf-8")

    def test_follow_profile_reads_profile_window_mode(self):
        self.assertEqual(self.engine.get_effective_window_mode("mac"), "floating")
        self.assertEqual(self.engine.get_effective_window_mode("windows"), "tiled")
        self.engine.profiles["windows"]["window_mode"] = "floating"
        self.assertEqual(self.engine.get_effective_window_mode("windows"), "floating")
        self.assertEqual(self.engine.window_modes_by_profile()["windows"], "floating")
        self.assertEqual(self.engine.get_effective_window_mode("windows", "tiled"), "tiled")
        self.assertEqual(self.engine.get_effective_window_mode("mac", "follow-profile"), "floating")

    def test_follow_profile_effective_mode(self):
        """Each mode's own window_mode decides: floating on mac, tiled elsewhere."""

        self.assertTrue(self.engine.switch_mode("windows"))
        state = self.engine.get_state()
        self.assertEqual(state.get("effective_window_mode"), "tiled")

        self.assertTrue(self.engine.switch_mode("mac"))
        state = self.engine.get_state()
        self.assertEqual(state.get("effective_window_mode"), "floating")

        self.assertTrue(self.engine.switch_mode("omarchy"))
        state = self.engine.get_state()
        self.assertEqual(state.get("effective_window_mode"), "tiled")

    def test_policy_preserved_on_switch_and_restore(self):
        """A stored global policy is kept across switch and restore."""
        from engine.engine import STATE_FILE
        STATE_FILE.write_text(json.dumps({"mode": "omarchy", "window_policy": "floating"}), encoding="utf-8")
        try:
            self.assertTrue(self.engine.switch_mode("windows"))
            self.assertEqual(self.engine.get_state()["effective_window_mode"], "floating")
            self.assertEqual(json.loads(STATE_FILE.read_text(encoding="utf-8"))["window_policy"], "floating")
            self.assertTrue(self.engine.restore())
            self.assertEqual(self.engine.get_state()["window_policy"], "floating")
        finally:
            self.engine.set_window_policy("follow-profile")

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
        """window-policy show + set <follow-profile|tiled|floating>; aliases, window-mode and stats stay removed."""
        bin_path = str(PROJECT_ROOT / "bin" / "omni-profile")
        env = dict(os.environ, OMNIPAL_DRY_RUN="1")
        p1 = subprocess.run([bin_path, "window-policy"], capture_output=True, text=True, env=env)
        self.assertEqual(p1.returncode, 0, p1.stderr)
        self.assertIn("OmniPal 窗口策略", p1.stdout)
        self.assertIn("(mac): 浮动", p1.stdout)

        p2 = subprocess.run([bin_path, "window-policy", "--json"], capture_output=True, text=True, env=env)
        self.assertEqual(p2.returncode, 0, p2.stderr)
        data = json.loads(p2.stdout)
        self.assertIn(data["window_policy"], ("follow-profile", "tiled", "floating"))
        self.assertIn("overridden", data)
        self.assertIn("effective_window_mode", data)
        self.assertEqual(data["window_modes"]["mac"], "floating")
        self.assertEqual(data["window_modes"]["windows"], "tiled")

        src = (PROJECT_ROOT / "bin" / "omni-profile").read_text(encoding="utf-8")
        self.assertIn('WINDOW_POLICY_CHOICES = ["follow-profile", "tiled", "floating"]', src)
        self.assertIn('p_p_enable.add_argument("--policy", choices=WINDOW_POLICY_CHOICES', src)
        self.assertIn("窗口策略: ⚠️ 已覆盖：全局", src)  # doctor warning
        self.assertIn("window-policy set follow-profile", src)
        self.assertNotIn("_warn_deprecated_alias", src)
        self.assertNotIn("DEPRECATED_POLICY_SUBCOMMANDS", src)

        for removed in (["window-mode"], ["window-policy", "tiled"], ["window-policy", "float"],
                        ["window-policy", "follow-profile"], ["window-policy", "follow"],
                        ["window-policy", "set", "float"], ["window-policy", "set", "follow"],
                        ["window-policy", "set", "tile"], ["stats"], ["stats", "--reset"],
                        ["persist", "enable", "--policy", "float"]):
            p = subprocess.run([bin_path, *removed], capture_output=True, text=True, env=env)
            self.assertNotEqual(p.returncode, 0, removed)

    def test_mode_indicator_model_helpers(self):
        """Model.js resolves policy names/effective mode; follow-profile reads each mode's window_mode."""
        content = (PROJECT_ROOT / "plugins" / "omni.mode-indicator" / "Model.js").read_text(encoding="utf-8")
        for present in ("effectiveWindowMode", "DEFAULT_POLICIES", "normalizePolicy", "computeEffectiveMode", "resolvePolicyName"):
            self.assertIn(present, content)
        self.assertNotIn('"name": "跟随",', content)

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
        if (!win || typeof win.bindings_count !== 'number' || win.bindings_count <= 0) throw new Error('windows binding count invalid: ' + (win ? win.bindings_count : null));
        if (!mac || typeof mac.bindings_count !== 'number' || mac.bindings_count <= 0) throw new Error('mac binding count invalid: ' + (mac ? mac.bindings_count : null));

        // Effective window mode follows each mode's window_mode
        if (ctx.effectiveWindowMode('mac', []) !== 'floating') throw new Error('mac != floating');
        if (ctx.effectiveWindowMode('windows', []) !== 'tiled') throw new Error('windows != tiled');
        if (ctx.effectiveWindowMode('windows', [{{id: 'windows', window_mode: 'floating'}}]) !== 'floating') throw new Error('window_mode ignored');
        if (ctx.effectiveWindowMode(null, null) !== 'tiled') throw new Error('null != tiled');
        // Global policy overrides; follow-profile defers to the mode
        if (ctx.computeEffectiveMode('floating', 'windows', []) !== 'floating') throw new Error('floating override');
        if (ctx.computeEffectiveMode('tiled', 'mac', []) !== 'tiled') throw new Error('tiled override');
        if (ctx.computeEffectiveMode('follow-profile', 'mac', []) !== 'floating') throw new Error('follow mac');
        if (ctx.normalizePolicy('') !== 'follow-profile') throw new Error('empty -> follow-profile');
        if (ctx.resolvePolicyName('follow-profile') !== '跟随模式') throw new Error('glossary name');
        """
        res = subprocess.run(["node", "-e", js_code], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Node execution error: {res.stderr}")

    def test_mode_indicator_qml_and_ipc_structure(self):
        """Validates that BarWidget.qml is a native qs.Ui Panel with window policy controls and IPC."""
        qml_file = PROJECT_ROOT / "plugins" / "omni.mode-indicator" / "BarWidget.qml"
        self.assertTrue(qml_file.exists())
        content = qml_file.read_text(encoding="utf-8")
        self.assertIn("import qs.Ui", content)
        self.assertIn("KeyboardPanel", content)
        self.assertIn("BarIconButton", content)
        self.assertIn("IpcHandler", content)
        self.assertNotIn("ShellIpc", content)  # absent on Omarchy 4.0.4
        self.assertNotIn("PopupCard", content)
        self.assertIn("effectiveWindowMode", content)
        self.assertIn("compositorConnected", content)
        self.assertIn("effPolicyBadge", content)
        self.assertIn("getEffectiveWindowMode", content)
        for present in ("windowPolicy", "policyOptions", "setPolicy", "getWindowPolicy(): string",
                        "setWindowPolicy(policy: string): void", "policyOverridden", "已覆盖 · ",
                        "omni-profile window-policy set ", "policyBase", '"当前"'):
            self.assertIn(present, content, present)
        for gone in ("切换下一模式", 'run: "cycle"'):
            self.assertNotIn(gone, content, gone)
        self.assertIn("closePanel", content)
        self.assertIn("panelOpen", content)

    def test_mode_indicator_manifest(self):
        """Validates manifest compliance and metadata."""
        manifest_file = PROJECT_ROOT / "plugins" / "omni.mode-indicator" / "manifest.json"
        self.assertTrue(manifest_file.exists())
        with open(manifest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["id"], "omni.mode-indicator")
        self.assertEqual(data["entryPoints"]["barWidget"], "BarWidget.qml")

    def test_floating_window_policy_enforcement(self):
        """Validates that _apply_window_policy follows the mode's window_mode and floats/unfloats cleanly."""
        e = OmniPalEngine(PROJECT_ROOT)
        e._eval_lua = lambda code: True
        e._write_state("mac", 0)
        self.assertTrue(e._apply_window_policy(force=True))
        self.assertEqual(e._get_applied_window_mode(), "floating")
        e._float_existing_windows()
        e._write_state("windows", 0)
        e._eval_lua_strict = lambda code: True
        self.assertTrue(e._apply_window_policy(force=True))
        self.assertEqual(e._get_applied_window_mode(), "tiled")
        e._write_state("omarchy", 0)

    def test_special_window_classification(self):
        """Verifies exclusion and classification of PiP, scratchpad, micro-windows, and dialogs."""
        # 1. Picture-in-Picture
        self.assertTrue(engine_module.is_pip_window("google-chrome", "Picture-in-Picture"))
        self.assertTrue(engine_module.is_pip_window("firefox", "Video - Picture in picture"))
        self.assertTrue(engine_module.is_pip_window("pip", "Some Player"))
        self.assertTrue(engine_module.is_pip_window("firefox-pip", "Player"))
        self.assertFalse(engine_module.is_pip_window("pipewire-pulse", "Audio Settings"))
        self.assertFalse(engine_module.is_pip_window("google-chrome", "Google Search"))

        # 2. Scratchpad / special workspace
        self.assertTrue(engine_module.is_scratchpad_workspace("special:scratchpad", None))
        self.assertTrue(engine_module.is_scratchpad_workspace("special", None))
        self.assertTrue(engine_module.is_scratchpad_workspace("1", -98))
        self.assertTrue(engine_module.is_scratchpad_workspace("-99", None))
        self.assertFalse(engine_module.is_scratchpad_workspace("1", 1))
        self.assertFalse(engine_module.is_scratchpad_workspace("", None))

        # 3. Dialogs / prompts / popups
        for kw in ("polkit", "pinentry", "portal", "calc", "about", "dialog", "prompt", "steam_app_", "wlogout", "rofi"):
            self.assertTrue(engine_module.is_dialog_window(f"my-{kw}-app", "Window"), f"Failed for {kw} in class")
            self.assertTrue(engine_module.is_dialog_window("normal-app", f"Title with {kw}"), f"Failed for {kw} in title")
        self.assertFalse(engine_module.is_dialog_window("antigravity", "Coding session"))

        # 4. Micro-window
        self.assertTrue(engine_module.is_micro_window([150, 100]))
        self.assertTrue(engine_module.is_micro_window([250, 400]))
        self.assertTrue(engine_module.is_micro_window([800, 150]))
        self.assertFalse(engine_module.is_micro_window([800, 600]))
        self.assertFalse(engine_module.is_micro_window(None))

        # 5. Combined is_special_window
        # PiP -> skip=True, is_dialog=False
        skip, is_dlg = engine_module.is_special_window(cls_name="pip", title="Player")
        self.assertTrue(skip)
        self.assertFalse(is_dlg)

        # Scratchpad -> skip=True, is_dialog=False
        skip, is_dlg = engine_module.is_special_window(cls_name="alacritty", ws_name="special:term")
        self.assertTrue(skip)
        self.assertFalse(is_dlg)

        # Micro-window -> skip=True, is_dialog=False
        skip, is_dlg = engine_module.is_special_window(cls_name="alacritty", size=[100, 100])
        self.assertTrue(skip)
        self.assertFalse(is_dlg)

        # Dialog -> skip=False, is_dialog=True
        skip, is_dlg = engine_module.is_special_window(cls_name="polkit-agent", title="Auth Required")
        self.assertFalse(skip)
        self.assertTrue(is_dlg)

        # Normal window -> skip=False, is_dialog=False
        skip, is_dlg = engine_module.is_special_window(cls_name="firefox", title="Documentation", ws_name="2", ws_id=2, size=[1200, 800])
        self.assertFalse(skip)
        self.assertFalse(is_dlg)

    def test_golden_cascade_monitor_aware_lua(self):
        """Verifies that _apply_golden_cascade_geometry generates monitor-aware Lua code."""
        e = OmniPalEngine(PROJECT_ROOT)
        captured_lua = []
        e._eval_lua = lambda code: captured_lua.append(code) or True

        # Test with monitor dict
        mon_dict = {"x": 2560, "y": 0, "width": 1920, "height": 1080, "reserved": [0, 26, 0, 0]}
        e._apply_golden_cascade_geometry("0x1234", step=2, is_dialog=False, monitor=mon_dict)
        self.assertEqual(len(captured_lua), 1)
        code = captured_lua[0]
        self.assertIn("target_mon = { x = 2560, y = 0, width = 1920, height = 1080", code)
        self.assertIn("hl.get_monitors", code)
        self.assertIn("hl.get_windows", code)
        self.assertIn("win.monitor", code)
        self.assertIn("hl.dsp.window.resize", code)
        self.assertIn("hl.dsp.window.move", code)

        # Test with dialog (should set is_dialog=1 and include center dispatch)
        captured_lua.clear()
        e._apply_golden_cascade_geometry("0x5678", step=0, is_dialog=True, monitor="DP-2")
        self.assertEqual(len(captured_lua), 1)
        dlg_code = captured_lua[0]
        self.assertIn('target_mon = "DP-2"', dlg_code)
        self.assertIn("is_dialog = 1", dlg_code)
        self.assertIn("hl.dsp.window.center", dlg_code)

    def test_float_existing_windows_skips_special_and_centers_dialogs(self):
        """Validates that _float_existing_windows skips PiP, scratchpad, micro-windows, and centers dialogs."""
        e = OmniPalEngine(PROJECT_ROOT)
        fake_clients = [
            # 1. Normal window -> cascaded
            {"address": "0x111", "mapped": True, "hidden": False, "class": "firefox", "title": "Web", "workspace": {"id": 1, "name": "1"}, "size": [1000, 700], "floating": False, "pinned": False, "fullscreen": 0, "monitor": 0},
            # 2. PiP window -> skipped
            {"address": "0x222", "mapped": True, "hidden": False, "class": "google-chrome", "title": "Picture-in-Picture", "workspace": {"id": 1, "name": "1"}, "size": [400, 300], "floating": True, "pinned": False, "fullscreen": 0, "monitor": 0},
            # 3. Scratchpad window -> skipped
            {"address": "0x333", "mapped": True, "hidden": False, "class": "kitty", "title": "scratch", "workspace": {"id": -98, "name": "special:scratchpad"}, "size": [800, 600], "floating": True, "pinned": False, "fullscreen": 0, "monitor": 0},
            # 4. Micro window -> skipped
            {"address": "0x444", "mapped": True, "hidden": False, "class": "app", "title": "tip", "workspace": {"id": 1, "name": "1"}, "size": [120, 80], "floating": True, "pinned": False, "fullscreen": 0, "monitor": 0},
            # 5. Dialog window -> centered
            {"address": "0x555", "mapped": True, "hidden": False, "class": "polkit-gnome", "title": "Authentication", "workspace": {"id": 1, "name": "1"}, "size": [450, 300], "floating": True, "pinned": False, "fullscreen": 0, "monitor": 0},
        ]

        calls = []
        e.get_windows = lambda: fake_clients
        e._apply_golden_cascade_geometry = lambda addr, step=0, is_dialog=False, monitor=None: calls.append({
            "addr": addr, "step": step, "is_dialog": is_dialog, "monitor": monitor
        })

        e._float_existing_windows()

        # Only 0x111 and 0x555 should be processed!
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["addr"], "0x111")
        self.assertFalse(calls[0]["is_dialog"])
        self.assertEqual(calls[0]["step"], 0)

        self.assertEqual(calls[1]["addr"], "0x555")
        self.assertTrue(calls[1]["is_dialog"])

    def test_unfloat_existing_windows(self):
        """Validates that _unfloat_existing_windows unfloats normal windows in active workspace while preserving special windows."""
        e = OmniPalEngine(PROJECT_ROOT)
        fake_clients = [
            # Normal floating window in active workspace 1 -> should unfloat
            {"address": "0xaaa", "mapped": True, "hidden": False, "class": "kitty", "title": "Terminal", "workspace": {"id": 1, "name": "1"}, "floating": True, "pinned": False, "fullscreen": 0, "size": [800, 600]},
            # Dialog window in active workspace 1 -> keep floating
            {"address": "0xbbb", "mapped": True, "hidden": False, "class": "polkit", "title": "Prompt", "workspace": {"id": 1, "name": "1"}, "floating": True, "pinned": False, "fullscreen": 0, "size": [400, 300]},
            # PiP window in active workspace 1 -> keep floating
            {"address": "0xccc", "mapped": True, "hidden": False, "class": "pip", "title": "Video", "workspace": {"id": 1, "name": "1"}, "floating": True, "pinned": False, "fullscreen": 0, "size": [400, 300]},
            # Pinned window -> keep floating
            {"address": "0xddd", "mapped": True, "hidden": False, "class": "notes", "title": "Notes", "workspace": {"id": 1, "name": "1"}, "floating": True, "pinned": True, "fullscreen": 0, "size": [500, 400]},
            # Fullscreen window -> keep
            {"address": "0xeee", "mapped": True, "hidden": False, "class": "vlc", "title": "Movie", "workspace": {"id": 1, "name": "1"}, "floating": True, "pinned": False, "fullscreen": 1, "size": [1920, 1080]},
            # Already tiled window -> skip
            {"address": "0xfff", "mapped": True, "hidden": False, "class": "editor", "title": "Code", "workspace": {"id": 1, "name": "1"}, "floating": False, "pinned": False, "fullscreen": 0, "size": [800, 600]},
        ]

        e.get_windows = lambda: fake_clients
        captured_lua = []
        e._eval_lua_strict = lambda code: captured_lua.append(code) or True

        e._unfloat_existing_windows()

        self.assertEqual(len(captured_lua), 1)
        code = captured_lua[0]
        # Only 0xaaa should be unfloated!
        self.assertIn("0xaaa", code)
        self.assertIn('action = "off"', code)
        self.assertNotIn("0xbbb", code)
        self.assertNotIn("0xccc", code)
        self.assertNotIn("0xddd", code)
        self.assertNotIn("0xeee", code)
        self.assertNotIn("0xfff", code)

    def test_qml_syntax_via_qmllint(self):
        """Lints every plugin QML against the Omarchy shell (qs.*) + Quickshell stubs."""
        if not os.path.exists("/usr/lib/qt6/bin/qmllint"):
            self.skipTest("qmllint not installed on system")
        shells = [os.environ.get("OMARCHY_SHELL", ""), "/workspace/ref/omarchy/shell",
                  "/usr/share/omarchy/shell"]
        if not any(s and os.path.isdir(os.path.join(s, "Commons")) for s in shells):
            self.skipTest("Omarchy shell source (qs.Commons/qs.Ui) not available")
        p = subprocess.run(["bash", str(PROJECT_ROOT / "scripts" / "qmllint.sh")],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f"qmllint failed: {p.stdout}{p.stderr}")

    def test_corrupted_state_policy_recovery(self):
        """Engine recovers safely when state.json is corrupted or holds a legacy policy value."""
        from engine.engine import STATE_FILE
        orig_state_text = STATE_FILE.read_text(encoding="utf-8") if STATE_FILE.exists() else None
        try:
            for raw in ("[1, 2, 3]", "NOT_VALID_JSON{{{",
                        json.dumps({"mode": "omarchy", "window_policy": "bogus"})):
                STATE_FILE.write_text(raw, encoding="utf-8")
                self.engine.window_policy = "follow-profile"
                self.assertEqual(self.engine.get_effective_window_mode(), "tiled")
                st = self.engine.get_state()
                self.assertEqual(st.get("effective_window_mode"), "tiled")
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




class TestLuaEscaping(unittest.TestCase):
    def test_lua_str_escapes_quotes_backslashes_and_newlines(self):
        from engine.engine import lua_str
        self.assertEqual(lua_str('notify-send "hi"'), '"notify-send \\"hi\\""')
        self.assertEqual(lua_str("a\\b"), '"a\\\\b"')
        self.assertEqual(lua_str("x\ny"), '"x\\ny"')
        self.assertEqual(lua_str("\x01"), '"\\001"')
        self.assertEqual(lua_str("中文"), '"中文"')

    def test_switch_mode_escapes_user_command(self):
        from engine.engine import OmniPalEngine
        engine = OmniPalEngine()
        captured = []
        engine._eval_lua = lambda code: captured.append(code) or True
        payload = 'notify-send "hi"\nend os.execute("rm -rf ~") --'
        engine.profiles["evil"] = {"bindings": [{"action": "custom_cmd_x", "mod": "SUPER", "key": "Q", "arg": payload}]}
        self.assertTrue(engine.switch_mode("evil"))
        code = captured[-1]
        self.assertIn('notify-send \\"hi\\"\\nend os.execute(\\"rm -rf ~\\") --', code)
        self.assertNotIn('"hi"\n', code)
        engine.restore()


class TestSwitchRollback(unittest.TestCase):
    """A failed switch must land the user back in the mode they had before, not the native baseline."""

    def setUp(self):
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.engine.record_switch = lambda mode_id: None

    def test_failed_switch_restores_previous_mode(self):
        self.engine._eval_lua = lambda code: True
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertEqual(self.engine.get_state().get("mode"), "windows")

        calls = []

        def flaky_eval(code):
            calls.append(code)
            # Fail only the first batch (the switch to mac); restore and re-apply succeed.
            return len(calls) > 1

        self.engine._eval_lua = flaky_eval
        self.assertFalse(self.engine.switch_mode("mac"))
        self.assertEqual(self.engine.get_state().get("mode"), "windows")
        combos = {r["combo"] for r in self.engine._get_active_overlay()}
        expected = {format_combo(b.get("mod", "").strip(), b["key"].strip())
                    for b in self.engine.profiles["windows"]["bindings"] if b.get("key", "").strip()}
        self.assertEqual(combos, expected)

    def test_failed_rollback_does_not_recurse(self):
        self.engine._eval_lua = lambda code: True
        self.engine.switch_mode("windows")
        calls = []
        self.engine._eval_lua = lambda code: calls.append(code) or False
        self.assertFalse(self.engine.switch_mode("mac"))
        # failed switch + cleanup unbind + restore, then one rollback attempt (same 3) and no further recursion
        self.assertLessEqual(len(calls), 6)


class TestProfileExportImport(unittest.TestCase):
    """omni-profile export/import round-trip, validation and safety guards."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, OMNIPAL_USER_PROFILES_DIR=str(Path(self._tmp.name) / "profiles"))
        self.cli = [sys.executable, str(PROJECT_ROOT / "bin" / "omni-profile")]

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *args, stdin=None):
        return subprocess.run(self.cli + list(args), input=stdin, capture_output=True, text=True, env=self.env)

    def test_round_trip_with_new_id(self):
        out = Path(self._tmp.name) / "win.json"
        self.assertEqual(self.run_cli("export", "windows", "-o", str(out)).returncode, 0)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertFalse(any(k.startswith("_") for k in data))
        r = self.run_cli("import", str(out), "--id", "my-win")
        self.assertEqual(r.returncode, 0, r.stderr)
        saved = json.loads((Path(self.env["OMNIPAL_USER_PROFILES_DIR"]) / "my-win.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["id"], "my-win")
        self.assertEqual(saved["bindings"], data["bindings"])

    def test_refuses_builtin_name_bad_id_and_invalid_action(self):
        out = Path(self._tmp.name) / "win.json"
        self.run_cli("export", "windows", "-o", str(out))
        self.assertNotEqual(self.run_cli("import", str(out)).returncode, 0)
        self.assertNotEqual(self.run_cli("import", "-", stdin='{"id":"Bad ID","bindings":[]}').returncode, 0)
        bad = '{"id":"b","bindings":[{"action":"no_such_action","key":"A"}]}'
        self.assertNotEqual(self.run_cli("import", "-", stdin=bad).returncode, 0)
        self.assertFalse(Path(self.env["OMNIPAL_USER_PROFILES_DIR"]).joinpath("b.json").exists())

    def test_custom_command_requires_confirmation(self):
        prof = '{"id":"cmdp","bindings":[{"action":"snap_left","mod":"SUPER","key":"F9","arg":"echo hi"}]}'
        r = self.run_cli("import", "-", stdin=prof)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("echo hi", r.stdout)
        self.assertEqual(self.run_cli("import", "-", "--yes", stdin=prof).returncode, 0)


class TestDoctorInstallCheck(unittest.TestCase):
    """doctor's installation self-check: CLI/plugin links, systemd unit, token copies, with fixes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.root = PROJECT_ROOT.resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def _install_links(self):
        (self.home / ".local" / "bin").mkdir(parents=True)
        (self.home / ".local" / "bin" / "omni-profile").symlink_to(self.root / "bin" / "omni-profile")
        pdir = self.home / ".config" / "omarchy" / "plugins"
        pdir.mkdir(parents=True)
        for src in sorted((self.root / "plugins").glob("omni.*")):
            (pdir / src.name).symlink_to(src)
        # install.sh also links plugins/shared (plugin ../shared/* links need it)
        (pdir / "shared").symlink_to(self.root / "plugins" / "shared")
        return pdir

    def test_fresh_home_reports_missing_with_reinstall_fix(self):
        info = self.engine.check_installation(home=self.home)
        self.assertEqual(info["cli"], "missing")
        self.assertTrue(all(v == "missing" for v in info["plugins"].values()))
        self.assertTrue(info["problems"])
        self.assertTrue(all("install.sh" in p["fix"] for p in info["problems"]))

    def test_clean_install_has_no_problems(self):
        self._install_links()
        info = self.engine.check_installation(home=self.home)
        self.assertEqual(info["cli"], "ok")
        self.assertEqual(info["problems"], [])

    def test_broken_plugin_link_detected(self):
        pdir = self._install_links()
        victim = sorted(pdir.iterdir())[0]
        victim.unlink()
        victim.symlink_to(self.home / "gone")
        info = self.engine.check_installation(home=self.home)
        self.assertEqual(info["plugins"][victim.name], "broken")
        self.assertEqual(len(info["problems"]), 1)


class TestSettingsCounts(unittest.TestCase):
    def test_settings_panel_has_no_hardcoded_mode_metadata(self):
        """Mode name/description/count come only from profiles via `omni-profile list --json`."""
        import re
        qml = (PROJECT_ROOT / "plugins" / "omni.settings" / "SettingsPanel.qml").read_text(encoding="utf-8")
        self.assertRegex(qml, r"property var modeItems:\s*\[\s*\]")
        self.assertIn('"omni-profile", "list", "--json"', qml)
        for mid in ("windows", "mac"):
            prof = json.loads((PROJECT_ROOT / "profiles" / f"{mid}.json").read_text(encoding="utf-8"))
            self.assertNotIn(prof["name"], qml, mid)

    def test_profile_descriptions_follow_glossary(self):
        """docs/GLOSSARY.md: Super/Space spelled in English, 贴靠 not 吸附."""
        for f in (PROJECT_ROOT / "profiles").glob("*.json"):
            desc = json.loads(f.read_text(encoding="utf-8")).get("description", "")
            for bad in ("空格", "Meta+", "Win+", "吸附", "Snap"):
                self.assertNotIn(bad, desc, f.name)


class TestAppRules(unittest.TestCase):
    """Per-app auto switching: matching, persistence and return-to-base behavior."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("OMNIPAL_CONFIG_DIR")
        os.environ["OMNIPAL_CONFIG_DIR"] = self._tmp.name
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.engine.restore()

    def tearDown(self):
        self.engine.restore()
        if self._old is None:
            os.environ.pop("OMNIPAL_CONFIG_DIR", None)
        else:
            os.environ["OMNIPAL_CONFIG_DIR"] = self._old
        self._tmp.cleanup()

    def test_match_kinds_and_case(self):
        rules = {"enabled": True, "rules": [
            {"class": "Code", "mode": "mac"},
            {"class": "org.gnome.", "match": "prefix", "mode": "omarchy"},
            {"class": "^jetbrains-", "match": "regex", "mode": "windows"},
            {"class": "firefox", "mode": "mac", "enabled": False},
        ]}
        m = self.engine.match_app_rule
        self.assertEqual(m("code", rules)["mode"], "mac")
        self.assertEqual(m("org.gnome.Nautilus", rules)["mode"], "omarchy")
        self.assertEqual(m("jetbrains-idea", rules)["mode"], "windows")
        self.assertIsNone(m("firefox", rules))
        self.assertIsNone(m("code", {"enabled": False, "rules": rules["rules"]}))

    def test_save_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            self.engine.save_app_rules({"enabled": True, "rules": [{"class": "x", "mode": "nope"}]})

    def test_save_rejects_nested_quantifier_regex(self):
        # catastrophic-backtracking shapes must never reach the daemon
        for pat in ("(a+)+$", "(a+)+", "(x*)*", "(.*)+", "(?:ab+)+",
                    "(?P<n>a+)+", "a*a*", ".*.*"):
            with self.assertRaises(ValueError, msg=pat):
                self.engine.save_app_rules(
                    {"enabled": True,
                     "rules": [{"class": pat, "match": "regex", "mode": "windows"}]})

    def test_save_rejects_overlong_regex(self):
        with self.assertRaises(ValueError):
            self.engine.save_app_rules(
                {"enabled": True,
                 "rules": [{"class": "a" * 201, "match": "regex", "mode": "windows"}]})
        # exactly at the cap is fine
        self.engine.save_app_rules(
            {"enabled": True,
             "rules": [{"class": "a" * 200, "match": "regex", "mode": "windows"}]})

    def test_save_rejects_invalid_regex(self):
        with self.assertRaises(ValueError):
            self.engine.save_app_rules(
                {"enabled": True,
                 "rules": [{"class": "(unclosed", "match": "regex", "mode": "windows"}]})

    def test_legit_regex_rules_unaffected(self):
        # escaped metachars / char classes are not quantifiers; ordinary
        # patterns must keep working end to end
        rules = {"enabled": True, "rules": [
            {"class": "^jetbrains-", "match": "regex", "mode": "windows"},
            {"class": r"firefox(\.exe)?", "match": "regex", "mode": "mac"},
            {"class": "[Cc]ode|kitty", "match": "regex", "mode": "omarchy"},
            {"class": "a*b*", "match": "regex", "mode": "mac"},  # 不同原子相邻量词是线性的
        ]}
        self.engine.save_app_rules(rules)
        m = self.engine.match_app_rule
        self.assertEqual(m("jetbrains-idea")["mode"], "windows")
        self.assertEqual(m("Firefox.exe")["mode"], "mac")
        self.assertEqual(m("kitty")["mode"], "omarchy")
        self.assertEqual(m("aaabbb")["mode"], "mac")

    def test_match_bounds_long_window_class(self):
        # a pathological window class is truncated before user regexes see it:
        # matching stays prompt and still works for ordinary patterns
        rules = {"enabled": True, "rules": [
            {"class": "^a+$", "match": "regex", "mode": "windows"},
        ]}
        self.assertEqual(self.engine.match_app_rule("a" * 5000, rules)["mode"], "windows")
        self.assertIsNone(self.engine.match_app_rule("b" * 5000, rules))

    def test_switch_and_return_to_manual_mode(self):
        self.engine.save_app_rules({"enabled": True, "default_mode": None,
                                    "rules": [{"class": "code", "mode": "mac"}]})
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertEqual(self.engine.apply_app_rule("code"), "mac")
        self.assertEqual(self.engine.get_state().get("mode"), "mac")
        self.assertEqual(self.engine.apply_app_rule("kitty"), "windows")
        self.assertEqual(self.engine.get_state().get("mode"), "windows")
        self.assertIsNone(self.engine.apply_app_rule("kitty"))

    def test_manual_switch_during_rule_becomes_new_base(self):
        self.engine.save_app_rules({"enabled": True, "rules": [{"class": "code", "mode": "mac"}]})
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertEqual(self.engine.apply_app_rule("code"), "mac")
        self.assertTrue(self.engine.switch_mode("omarchy"))  # user overrides by hand inside VS Code
        self.assertIsNone(self.engine.apply_app_rule("kitty"))  # stays on omarchy, not back to windows
        self.assertEqual(self.engine.get_state().get("mode"), "omarchy")

    def test_switch_retired_mode_lists_valid_modes(self):
        with self.assertRaises(ValueError) as cm:
            self.engine.switch_mode("kde")
        msg = str(cm.exception)
        self.assertIn("removed", msg)
        for mid in ("windows", "mac", "omarchy"):
            self.assertIn(mid, msg)

    def test_migrate_retired_mode_falls_back_to_windows(self):
        import engine.engine as em
        em.write_state_json(em.STATE_FILE, {"mode": "kde", "name": "KDE", "display": {},
                                            "auto": {"mode": "kde", "return_to": "mac"}})
        em.atomic_write_json(em.persistence_file_path(), {"enabled": True, "profile": "kde"})
        em.atomic_write_json(em.app_rules_file_path(), {"enabled": True, "default_mode": "kde", "rules": [
            {"class": "dolphin", "mode": "kde"}, {"class": "code", "mode": "mac"}]})
        logs = self.engine.migrate_retired_modes()
        self.assertEqual(len(logs), 3)
        state = json.loads(em.STATE_FILE.read_text())
        self.assertEqual(state["mode"], "windows")
        self.assertNotIn("auto", state)
        self.assertEqual(self.engine.get_persistence_status()["profile"], "windows")
        rules = self.engine.load_app_rules()
        self.assertEqual(rules["default_mode"], "windows")
        self.assertEqual([r["class"] for r in rules["rules"]], ["code"])
        self.assertEqual(self.engine.migrate_retired_modes(), [])  # idempotent


class TestRulesAddCurrent(unittest.TestCase):
    """rules add/test --current read the focused window's class (via the hyprctl stub)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        fakebin = str(PROJECT_ROOT / "tests" / "fakebin")
        self.env = dict(os.environ, OMNIPAL_CONFIG_DIR=self._tmp.name,
                        PATH=fakebin + os.pathsep + os.environ.get("PATH", ""))
        self.cli = [sys.executable, str(PROJECT_ROOT / "bin" / "omni-profile"), "rules"]

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(self.cli + list(args), capture_output=True, text=True, env=self.env)

    def test_add_current_uses_focused_class(self):
        r = self.run_cli("add", "--current", "mac", "--delay", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        rules = json.loads(self.run_cli("list", "--json").stdout)["rules"]
        self.assertEqual([(x["class"], x["mode"]) for x in rules], [("fake", "mac")])
        self.assertIn("fake -> mac", self.run_cli("test", "--current", "--delay", "0").stdout)

    def test_add_without_mode_is_rejected(self):
        self.assertNotEqual(self.run_cli("add", "code").returncode, 0)
        self.assertNotEqual(self.run_cli("add", "--current", "--delay", "0").returncode, 0)


class TestCheatSheetHighlight(unittest.TestCase):
    def test_highlight_escapes_and_marks_matches(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = PROJECT_ROOT / "plugins" / "omni.cheat-sheet" / "CheatSheetData.js"
        script = (
            "const fs=require('fs');eval(fs.readFileSync(process.argv[1],'utf8').replace('.pragma library',''));"
            "console.log(JSON.stringify([highlightMatches('关闭 <窗口> Close','clo','#e2a03f'),highlightMatches('abc','',null)]))"
        )
        out = subprocess.run(["node", "-e", script, str(js)], capture_output=True, text=True, check=True).stdout
        a, b = json.loads(out)
        self.assertEqual(a, '关闭 &lt;窗口&gt; <b><font color="#e2a03f">Clo</font></b>se')
        self.assertEqual(b, "abc")


class TestAppRulesExportImport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, OMNIPAL_CONFIG_DIR=self._tmp.name)
        self.cli = [sys.executable, str(PROJECT_ROOT / "bin" / "omni-profile")]

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *a, stdin=None):
        return subprocess.run(self.cli + list(a), env=self.env, capture_output=True, text=True, input=stdin)

    def test_roundtrip_merge_and_skip_unknown_mode(self):
        self.assertEqual(self.run_cli("rules", "add", "code", "mac").returncode, 0)
        exported = self.run_cli("rules", "export").stdout
        self.assertIn('"code"', exported)
        bundle = json.dumps({"rules": [{"class": "code", "mode": "windows"},
                                       {"class": "kitty", "mode": "omarchy"},
                                       {"class": "x", "mode": "does-not-exist"}]})
        res = self.run_cli("rules", "import", "-", stdin=bundle)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("跳过", res.stdout)
        data = json.loads((Path(self._tmp.name) / "app_rules.json").read_text())
        modes = {r["class"]: r["mode"] for r in data["rules"]}
        self.assertEqual(modes, {"code": "windows", "kitty": "omarchy"})

    def test_replace(self):
        self.run_cli("rules", "add", "code", "mac")
        res = self.run_cli("rules", "import", "-", "--replace", stdin=json.dumps({"rules": [{"class": "kitty", "mode": "mac"}]}))
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads((Path(self._tmp.name) / "app_rules.json").read_text())
        self.assertEqual([r["class"] for r in data["rules"]], ["kitty"])

class TestForwardShortcut(unittest.TestCase):
    """mac mode forwards Super+W etc. to the app via sendshortcut."""

    def setUp(self):
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.evals, self.calls = [], []
        self.engine._eval_lua = lambda code: self.evals.append(code) or True
        self.engine._reload_hyprland = lambda: self.calls.append("reload") or True
        self.engine._write_active_overlay = lambda recs: setattr(self, "overlay", recs)
        self.engine._get_active_overlay = lambda: getattr(self, "overlay", [])
        self.engine._write_state = lambda *a, **k: None
        self.engine.record_switch = lambda *a, **k: None
        self.engine.get_persistence_status = lambda: {"enabled": False}

    def test_parse_and_terminal(self):
        from engine.engine import parse_forward, forward_for_class
        self.assertEqual(parse_forward("ctrl shift t"), (["CTRL", "SHIFT"], "T"))
        self.assertEqual(forward_for_class("CTRL W", "firefox"), (["CTRL"], "W"))
        self.assertEqual(forward_for_class("CTRL W", "Alacritty"), (["CTRL", "SHIFT"], "W"))
        self.assertEqual(forward_for_class("CTRL SHIFT T", "kitty"), (["CTRL", "SHIFT"], "T"))
        for bad in ["", "CTRL W;rm", 'CTRL "x', "C-1 W"]:
            with self.assertRaises(ValueError):
                parse_forward(bad)

    def test_mac_unbinds_native_and_quotes_lua(self):
        from engine.engine import lua_str
        self.assertTrue(self.engine.switch_mode("mac"))
        lua = self.evals[-1]
        fw = [b for b in self.overlay if b.get("native_unbound")]
        self.assertGreaterEqual(len(fw), 10)
        for b in fw:
            self.assertIn(f"hl.unbind({lua_str(b['combo'])})", lua)
        self.assertNotIn("omni-profile send", lua)  # no external process per key
        self.assertIn('hl.dsp.send_shortcut({ mods = t and "CTRL SHIFT" or "CTRL", key = "W" })', lua)
        self.assertIn('["alacritty"] = true', lua)

    def test_bad_forward_is_skipped(self):
        prof = self.engine.profiles["mac"]
        saved = list(prof["bindings"])
        prof["bindings"] = saved + [{"mod": "SUPER", "key": "F12", "action": "forward_shortcut", "forward": 'CTRL ")os.exit('}]
        try:
            self.engine.switch_mode("mac")
        finally:
            prof["bindings"] = saved
        self.assertNotIn("os.exit", self.evals[-1])

    def test_restore_and_switch_reload_natives(self):
        self.engine.switch_mode("mac")
        self.engine.switch_mode("windows")
        self.assertEqual(self.calls, ["reload"])
        self.assertFalse(any(b.get("native_unbound") for b in self.overlay))
        self.engine.restore()
        self.assertEqual(self.calls, ["reload"])  # windows unbound nothing native

    def test_user_terminals(self):
        from engine.engine import load_terminal_patterns, is_terminal_class, forward_lua
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("OMNIPAL_CONFIG_DIR")
            os.environ["OMNIPAL_CONFIG_DIR"] = d
            try:
                Path(d, "terminals.json").write_text('["MyTerm", "rio*", "x\\"] = true }) os.exit() --"]')
                pats = load_terminal_patterns()
                self.assertTrue(is_terminal_class("myterm", pats))
                self.assertTrue(is_terminal_class("rio-nightly", pats))
                self.assertFalse(is_terminal_class("firefox", pats))
                lua = forward_lua(["CTRL"], "W", pats)
                self.assertIn('"rio"', lua)
                from engine.engine import lua_str
                evil = [p for p in pats if "os.exit" in p][0]
                self.assertIn(f"[{lua_str(evil)}] = true", lua)  # stays one escaped literal
            finally:
                if old is None: os.environ.pop("OMNIPAL_CONFIG_DIR", None)
                else: os.environ["OMNIPAL_CONFIG_DIR"] = old

    def test_send_cli_stub(self):
        self.assertTrue(self.engine.send_shortcut("CTRL W", window_class="kitty"))
        self.assertFalse(self.engine.send_shortcut("CTRL W;x", window_class="kitty"))
    def test_snap_invalid_zone(self):
        """Ensures snap returns False when supplied an invalid or nonexistent zone."""
        self.assertFalse(self.engine.snap("completely_nonexistent_zone_12345"))

    def test_engine_lock_reentrancy(self):
        """Ensures engine_lock handles recursive nested acquisition smoothly without deadlock."""
        from engine.engine import engine_lock
        with engine_lock(timeout=0.5):
            with engine_lock(timeout=0.5):
                with engine_lock(timeout=0.5):
                    self.assertTrue(True)

    def test_engine_lock_exception_propagation(self):
        """Ensures exceptions raised inside engine_lock propagate directly without RuntimeError."""
        from engine.engine import engine_lock
        class CustomTestError(Exception):
            pass

        with self.assertRaises(CustomTestError):
            with engine_lock(timeout=0.5):
                raise CustomTestError("Test error propagation inside engine_lock")

    def test_atomic_write_json_safety(self):
        """Validates that atomic_write_json safely writes data and does not leave temporary files."""
        from engine.engine import atomic_write_json
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "test_state.json"
            data = {"status": "ok", "count": 42}
            ok = atomic_write_json(target, data)
            self.assertTrue(ok)
            self.assertTrue(target.exists())
            loaded = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(loaded, data)
            # Ensure no orphan .tmp files in directory
            tmps = list(Path(td).glob("*.tmp"))
            self.assertEqual(len(tmps), 0)

    def test_get_windows(self):
        """Verifies get_windows returns a list and handles failures safely."""
        windows = self.engine.get_windows()
        self.assertIsInstance(windows, list)

    def test_snap_layouts_with_address_does_not_crash(self):
        """Verifies snap('layouts', '0x1234') executes cleanly without crashing."""
        from engine.engine import SNAP_FILE
        res = self.engine.snap("layouts", target_address="0x1234", no_hud=True)
        self.assertTrue(res)
        self.assertTrue(SNAP_FILE.exists())
        data = json.loads(SNAP_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data.get("zone"), "layouts")
        self.assertEqual(data.get("target_window"), "0x1234")

    def test_snap_target_address_injection_safety(self):
        """Ensures snap validates target_address with strict regex, dropping malicious Lua injections."""
        from engine.engine import SNAP_FILE
        malicious_input = "'; os.execute('echo pwned'); --"
        res = self.engine.snap("left", target_address=malicious_input, no_hud=True)
        self.assertTrue(SNAP_FILE.exists())
        data = json.loads(SNAP_FILE.read_text(encoding="utf-8"))
        self.assertIsNone(data.get("target_window"))
        self.assertNotIn("pwned", str(data))

    def test_omni_profile_cheatsheet_nonexistent_exit_code(self):
        """Verifies omni-profile cheatsheet with unknown mode exits with code 2 and stderr message."""
        cli = PROJECT_ROOT / "bin" / "omni-profile"
        res = subprocess.run([sys.executable, str(cli), "cheatsheet", "nonexistent_profile_xyz"],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("nonexistent_profile_xyz", res.stderr)

    def test_snapshot_baseline_bindings(self):
        """Verifies that _snapshot_baseline_bindings captures overlapping profile/action bindings and caches them."""
        mock_binds = [
            {
                "modmask": 64,
                "key": "SPACE",
                "dispatcher": "__lua",
                "arg": "1234",
                "description": "User Custom Launcher"
            },
            {
                "modmask": 64,
                "key": "W",
                "dispatcher": "__lua",
                "arg": "5678",
                "description": "Close window"
            },
            {
                "modmask": 8,
                "key": "F4",
                "dispatcher": "exec",
                "arg": "my-close-script.sh",
                "description": "Custom Close"
            },
            {
                "modmask": 65,
                "key": "F12",
                "dispatcher": "exec",
                "arg": "irrelevant-action.sh",
                "description": "Irrelevant Custom"
            }
        ]
        from unittest.mock import patch
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["hyprctl", "binds", "-j"],
                returncode=0,
                stdout=json.dumps(mock_binds)
            )
            self.engine.baseline_bindings = {}
            captured = self.engine._snapshot_baseline_bindings(force=True)

            self.assertIn("SUPER + SPACE", captured)
            self.assertEqual(captured["SUPER + SPACE"]["description"], "User Custom Launcher")
            self.assertEqual(captured["SUPER + SPACE"]["arg"], "1234")

            self.assertIn("SUPER + W", captured)
            self.assertIn("ALT + F4", captured)
            self.assertEqual(captured["ALT + F4"]["dispatcher"], "exec")

            # Irrelevant F12 does not overlap with any profile or action catalog item
            self.assertNotIn("SUPER + SHIFT + F12", captured)

            # Check that BASELINE_FILE was written
            from engine.engine import BASELINE_FILE
            self.assertTrue(BASELINE_FILE.exists())
            cached_data = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
            self.assertIn("SUPER + SPACE", cached_data)

    def test_dynamic_restore_generation_and_fallback(self):
        """Validates that restore() uses dynamic Lua when snapshot is present, falling back to baseline when absent."""
        from engine.engine import LUA_RESTORE_BASELINE
        from unittest.mock import patch
        eval_history = []

        def fake_eval(lua_code):
            eval_history.append(lua_code)
            return True

        # 1. Test dynamic restore when snapshot exists
        self.engine.baseline_bindings = {
            "SUPER + SPACE": {
                "combo": "SUPER + SPACE",
                "dispatcher": "__lua",
                "arg": "9999",
                "description": "Custom Launcher"
            },
            "ALT + F4": {
                "combo": "ALT + F4",
                "dispatcher": "exec",
                "arg": "custom-kill",
                "description": "Custom Kill"
            }
        }

        # Only natives the overlay displaced are replayed (untouched natives are still bound).
        displaced = [{"combo": c, "native_unbound": True, "native_restorable": False, "native_count": 0, "name": "x"} for c in ("SUPER + SPACE", "ALT + F4")]
        with patch.object(self.engine, "_eval_lua", side_effect=fake_eval), \
             patch.object(self.engine, "_get_active_overlay", return_value=displaced), \
             patch.object(self.engine, "_reload_hyprland", return_value=True):
            ok = self.engine.restore()
            self.assertTrue(ok)
            self.assertTrue(len(eval_history) > 0)
            executed_lua = next(l for l in eval_history if "local reg" in l)
            self.assertIn("local reg = debug.getregistry()", executed_lua)
            self.assertIn('hl.bind("SUPER + SPACE", fn_9999', executed_lua)
            self.assertIn('o.bind("ALT + F4", "Custom Kill", "custom-kill")', executed_lua)
            self.assertNotIn(LUA_RESTORE_BASELINE, executed_lua)

        # 2. Test fallback when baseline snapshot is absent
        eval_history.clear()
        self.engine.baseline_bindings = {}
        from engine.engine import BASELINE_FILE
        if BASELINE_FILE.exists():
            BASELINE_FILE.unlink()

        with patch.object(self.engine, "_eval_lua", side_effect=fake_eval), \
             patch.object(self.engine, "_get_active_overlay", return_value=displaced), \
             patch.object(self.engine, "_reload_hyprland", return_value=True), \
             patch.object(self.engine, "_snapshot_baseline_bindings", return_value={}):
            ok = self.engine.restore()
            self.assertTrue(ok)
            self.assertTrue(len(eval_history) > 0)
            executed_lua = next(l for l in eval_history if LUA_RESTORE_BASELINE in l)
            self.assertIn(LUA_RESTORE_BASELINE, executed_lua)

    def test_switch_mode_omarchy_uses_snapshot(self):
        """Verifies switch_mode('omarchy') executes dynamic restore with captured snapshot."""
        from unittest.mock import patch
        self.engine.baseline_bindings = {
            "SUPER + SPACE": {
                "combo": "SUPER + SPACE",
                "dispatcher": "__lua",
                "arg": "7777",
                "description": "My Menu"
            }
        }
        eval_history = []
        displaced = [{"combo": "SUPER + SPACE", "native_unbound": True, "native_restorable": False, "native_count": 0}]
        with patch.object(self.engine, "_eval_lua", side_effect=lambda lua: eval_history.append(lua) or True), \
             patch.object(self.engine, "_get_active_overlay", return_value=displaced), \
             patch.object(self.engine, "_reload_hyprland", return_value=True):
            ok = self.engine.switch_mode("omarchy")
            self.assertTrue(ok)
            self.assertTrue(any("fn_7777" in lua for lua in eval_history))


if __name__ == "__main__":
    unittest.main()


class TestSettingsPanelKeys(unittest.TestCase):
    """Settings panel destructive keys need confirm; mode switch is undoable; Shift+Tab goes back."""
    def setUp(self):
        self.qml = (PROJECT_ROOT / "plugins" / "omni.settings" / "SettingsPanel.qml").read_text(encoding="utf-8")

    def test_restore_requires_shift_and_confirm(self):
        self.assertRegex(self.qml, r"Qt\.Key_R && \(event\.modifiers & Qt\.ShiftModifier\)\)\s*\{\s*root\.askRestore\(\)")
        self.assertIn("ConfirmDialog {", self.qml)
        self.assertNotRegex(self.qml, r"onClicked:\s*root\.(restoreNative|resetStats)\(\)")

    def test_mode_switch_undo_and_backtab(self):
        self.assertIn("root.switchModeWithUndo(root.modeItems[num].id)", self.qml)
        self.assertIn("Qt.Key_U", self.qml)
        self.assertIn("Qt.Key_Backtab", self.qml)

    def test_manifests_declare_min_omarchy(self):
        for mf in (PROJECT_ROOT / "plugins").glob("omni.*/manifest.json"):
            self.assertEqual(json.loads(mf.read_text(encoding="utf-8")).get("minOmarchy"), "4.0.4", mf)


class TestOmarchyVersionGate(unittest.TestCase):
    """Shared Omarchy version detection used by install.sh and doctor."""
    def _check(self, version):
        from engine import omarchy_version as ov
        old = {k: os.environ.get(k) for k in ("OMNIPAL_OMARCHY_VERSION", "OMARCHY_PATH", "PATH")}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["OMARCHY_PATH"] = tmp  # no version file
                os.environ["PATH"] = tmp          # no pacman
                if version is None:
                    os.environ.pop("OMNIPAL_OMARCHY_VERSION", None)
                else:
                    os.environ["OMNIPAL_OMARCHY_VERSION"] = version
                return ov.check_omarchy_version(PROJECT_ROOT)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_statuses(self):
        self.assertEqual(self._check("4.0.4")["status"], "ok")
        self.assertEqual(self._check("4.1.0-2")["status"], "ok")
        self.assertEqual(self._check("4.0.3")["status"], "too_old")
        r = self._check(None)
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["minimum"], "4.0.4")

    def test_install_warns_on_unknown_and_points_to_doctor(self):
        sh = (PROJECT_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("engine/omarchy_version.py", sh)
        unknown = sh.split("*)", 1)[1].split("esac", 1)[0]
        self.assertIn("omni-profile doctor", unknown)
        self.assertNotIn("exit 1", unknown)
        too_old = sh.split("too_old)", 1)[1].split(";;", 1)[0]
        self.assertIn("exit 1", too_old)


class TestUxSafetyRound2(unittest.TestCase):
    """Overview typing goes to search, closes need a second press, mode switches are undoable."""
    P = PROJECT_ROOT / "plugins"

    def read(self, rel):
        return (self.P / rel).read_text(encoding="utf-8")

    def test_overview_plain_letters_are_not_shortcuts(self):
        qml = self.read("omni.overview/Overview.qml")
        self.assertNotIn('root.searchQuery === "" && (event.key', qml)
        self.assertNotIn('root.searchQuery === "" && event.key', qml)
        self.assertIn("(alt && event.key === Qt.Key_X)", qml)
        self.assertIn("alt && event.key === Qt.Key_M", qml)
        self.assertIn("alt && (event.key === Qt.Key_L || event.key === Qt.Key_J)", qml)
        self.assertNotIn("Qt.Key_Space", qml)

    def test_overview_close_requires_second_press(self):
        qml = self.read("omni.overview/Overview.qml")
        self.assertIn("root.requestClose(root.currentSelectedWin.address)", qml)
        self.assertEqual(qml.count("root.closeWindow("), 1)  # only from requestClose
        self.assertIn("interval: Safety.CONFIRM_MS", qml)
        self.assertIn("Safety.CLOSE_AGAIN_TEXT", qml)

    def test_overview_number_range_matches_settings(self):
        qml = self.read("omni.overview/Overview.qml")
        self.assertIn("event.key <= Qt.Key_9", qml)
        self.assertNotIn("Qt.Key_8", qml)
        self.assertNotIn("(i < 8)", self.read("omni.overview/Model.js"))
        self.assertIn("num < 9", self.read("omni.settings/SettingsPanel.qml"))

    def test_dock_multi_window_close_arms_first(self):
        qml = self.read("omni.mac-dock/MacDock.qml")
        self.assertIn("it.windowCount > 1 && !Safety.isArmed(root.closeArmedKey", qml)
        self.assertIn("interval: Safety.CONFIRM_MS", qml)

    def test_mode_indicator_switch_is_undoable(self):
        qml = self.read("omni.mode-indicator/BarWidget.qml")
        self.assertIn("onClicked: root.switchModeWithUndo(profileRow.modelData.id)", qml)
        self.assertIn("root.switchModeWithUndo(root.profiles[i].id)", qml)
        self.assertIn("interval: Safety.UNDO_MS", qml)
        self.assertIn("root.undoSwitch()", qml)

    def test_safety_js_is_shared(self):
        js = self.read("shared/Safety.js")
        self.assertIn("var UNDO_MS = 5000", js)
        self.assertIn("var CONFIRM_MS = 2000", js)
        self.assertIn("再按一次关闭", js)
        for d in ("omni.overview", "omni.mac-dock", "omni.mode-indicator", "omni.settings"):
            self.assertEqual((self.P / d / "Safety.js").read_text(encoding="utf-8"), js, d)


class TestNativeConflicts(unittest.TestCase):
    """Overlay combos that collide with live Omarchy binds unbind the native(s) and restore reloads them."""

    def setUp(self):
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.evals, self.calls = [], []
        self.overlay = []
        self.live = {}
        e = self.engine
        e._eval_lua = lambda code: self.evals.append(code) or True
        e._reload_hyprland = lambda: self.calls.append("reload") or True
        e._write_active_overlay = lambda recs: setattr(self, "overlay", recs)
        e._get_active_overlay = lambda: self.overlay
        e._write_state = lambda *a, **k: None
        e.record_switch = lambda *a, **k: None
        e.get_persistence_status = lambda: {"enabled": False}
        e._live_bind_counts = lambda: dict(self.live)
        self.details = {}
        e._live_bind_details = lambda: {k: [dict(x) for x in v] for k, v in self.details.items()}
        self.strict_ok = True
        e._eval_lua_strict = lambda code: self.evals.append(code) or self.strict_ok
        e._apply_window_policy = lambda *a, **k: True

    def test_combo_signature_matches_hyprctl_modmask(self):
        from engine.engine import combo_signature
        self.assertEqual(combo_signature("SUPER + TAB"), (64, "TAB"))
        self.assertEqual(combo_signature("SUPER + SHIFT + TAB"), (65, "TAB"))
        self.assertEqual(combo_signature("SUPER + CTRL + LEFT"), (68, "LEFT"))

    def test_windows_super_tab_unbinds_native_and_restore_reloads(self):
        self.live = {(64, "TAB"): 1}  # Omarchy "Next workspace"
        self.assertTrue(self.engine.switch_mode("windows"))
        rec = {b["combo"]: b for b in self.overlay}
        self.assertTrue(rec["SUPER + TAB"].get("native_unbound"))
        self.assertIn('hl.unbind("SUPER + TAB")', self.evals[-1])
        self.assertTrue(self.engine.restore())
        self.assertIn("reload", self.calls)

    def test_lua_native_is_stashed_and_restored_without_reload(self):
        self.live = {(64, "TAB"): 1}
        self.details = {(64, "TAB"): [{"modmask": 64, "key": "Tab", "dispatcher": "__lua", "arg": "42",
                                       "description": "Next workspace", "repeat": True}]}
        self.assertTrue(self.engine.switch_mode("windows"))
        code = self.evals[-1]
        stash = code.index("omnipal_stash")
        self.assertLess(stash, code.index('hl.unbind("SUPER + TAB")'))
        self.assertIn("h = R[42]", code)
        self.assertIn("repeating = true", code)
        rec = {b["combo"]: b for b in self.overlay}
        self.assertTrue(rec["SUPER + TAB"]["native_restorable"])
        self.calls.clear()
        self.assertTrue(self.engine.restore())
        self.assertNotIn("reload", self.calls)
        self.assertIn('hl.bind("SUPER + TAB", e.h, e.o)', self.evals[-1])

    def test_unstash_failure_falls_back_to_reload(self):
        self.live = {(64, "TAB"): 1}
        self.details = {(64, "TAB"): [{"dispatcher": "__lua", "arg": "7", "description": "n"}]}
        self.assertTrue(self.engine.switch_mode("windows"))
        self.strict_ok = False
        self.calls.clear()
        self.assertTrue(self.engine.restore())
        self.assertIn("reload", self.calls)

    def test_non_lua_native_falls_back_to_reload(self):
        self.live = {(64, "TAB"): 1}
        self.details = {(64, "TAB"): [{"dispatcher": "workspace", "arg": "e+1", "description": "n"}]}
        self.assertTrue(self.engine.switch_mode("windows"))
        rec = {b["combo"]: b for b in self.overlay}
        self.assertFalse(rec["SUPER + TAB"]["native_restorable"])
        self.calls.clear()
        self.assertTrue(self.engine.restore())
        self.assertIn("reload", self.calls)

    def test_multiple_natives_on_one_combo_all_unbound(self):
        self.live = {(64, "TAB"): 2}
        self.assertTrue(self.engine.switch_mode("windows"))
        code = self.evals[-1]
        self.assertGreaterEqual(code.count('hl.unbind("SUPER + TAB")'), 2)

    def test_own_overlay_not_counted_as_native(self):
        # windows overlay already active, live shows only our own SUPER + TAB → not a native conflict
        self.overlay = [{"action": "task_view", "combo": "SUPER + TAB", "name": "x"}]
        self.live = {(64, "TAB"): 1}
        self.assertTrue(self.engine.switch_mode("windows"))
        rec = {b["combo"]: b for b in self.overlay}
        self.assertFalse(rec["SUPER + TAB"].get("native_unbound", False))

    def test_no_live_conflict_no_reload(self):
        self.live = {}
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertFalse(any(b.get("native_unbound") for b in self.overlay))
        self.calls.clear()
        self.assertTrue(self.engine.restore())
        self.assertNotIn("reload", self.calls)

    def test_profiles_cover_omarchy_default_collisions(self):
        """Every OmniPal combo that collides with an Omarchy default bind gets unbound when live."""
        import re, glob
        from engine.engine import format_combo, combo_signature
        ref = Path("/workspace/ref/omarchy/default/hypr/bindings")
        if not ref.is_dir():
            self.skipTest("Omarchy reference bindings not available")
        native = set()
        for f in glob.glob(str(ref / "*.lua")):
            for m in re.finditer(r'o\.bind\w*\(\s*"([^"]+)"', Path(f).read_text(encoding="utf-8")):
                native.add(combo_signature(m.group(1)))
        prof = json.loads((PROJECT_ROOT / "profiles" / "windows.json").read_text(encoding="utf-8"))
        colliding = {combo_signature(format_combo(b.get("mod", ""), b["key"])) for b in prof["bindings"]} & native
        self.assertIn((64, "TAB"), colliding)
        self.live = {sig: 1 for sig in colliding}
        self.assertTrue(self.engine.switch_mode("windows"))
        unbound = {combo_signature(b["combo"]) for b in self.overlay if b.get("native_unbound")}
        self.assertEqual(unbound, colliding)


class TestFixedEntryPoints(unittest.TestCase):
    """Cheat sheet / settings / overview have the same keys in every mode."""

    def setUp(self):
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.evals = []
        self.overlay = []
        e = self.engine
        e._eval_lua = lambda code: self.evals.append(code) or True
        e._eval_lua_strict = lambda code: self.evals.append(code) or True
        e._reload_hyprland = lambda: True
        e._write_active_overlay = lambda recs: setattr(self, "overlay", recs)
        e._get_active_overlay = lambda: self.overlay
        e._write_state = lambda *a, **k: None
        e.record_switch = lambda *a, **k: None
        e.get_persistence_status = lambda: {"enabled": False}
        e._live_bind_counts = lambda: {}
        e._apply_window_policy = lambda *a, **k: True

    def test_fixed_combos(self):
        self.assertEqual(self.engine.fixed_combos(), {
            "SUPER + ALT + SLASH": "cheat_sheet",
            "SUPER + ALT + I": "omni_settings",
            "SUPER + ALT + O": "task_view",
        })

    def test_fixed_combos_free_in_omarchy_defaults(self):
        import re, glob
        from engine.engine import combo_signature
        ref = Path("/workspace/ref/omarchy/default/hypr")
        if not ref.is_dir():
            self.skipTest("Omarchy reference not available")
        native = set()
        for f in glob.glob(str(ref / "**" / "*.lua"), recursive=True):
            for m in re.finditer(r'o\.bind\w*\(\s*"([^"]+)"', Path(f).read_text(encoding="utf-8")):
                native.add(combo_signature(m.group(1)))
        for combo in self.engine.fixed_combos():
            self.assertNotIn(combo_signature(combo), native, combo)

    def test_injected_in_every_mode(self):
        for mode in ("windows", "mac", "omarchy"):
            self.evals.clear()
            self.assertTrue(self.engine.switch_mode(mode), mode)
            code = "; ".join(self.evals)
            for combo in self.engine.fixed_combos():
                self.assertIn(f'o.bind("{combo}"', code, (mode, combo))

    def test_profile_cannot_override(self):
        self.engine.profiles["windows"]["bindings"] = self.engine.profiles["windows"]["bindings"] + [
            {"action": "lock_screen", "mod": "SUPER ALT", "key": "I"}]
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertNotIn("SUPER + ALT + I", {b["combo"] for b in self.overlay})
        code = self.evals[-1]
        self.assertIn('o.bind("SUPER + ALT + I", "OmniPal 控制中心"', code)

    def test_cheatsheet_lists_fixed_in_omarchy(self):
        sheet = self.engine.cheatsheet("omarchy")
        self.assertEqual({e["key"] for e in sheet if e.get("fixed")}, set(self.engine.fixed_combos()))

    def test_check_consistency_rejects_override(self):
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import check_consistency as cc
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"bindings": [{"action": "lock_screen", "mod": "SUPER ALT", "key": "slash"}]}))
            ok_alias = Path(tmp) / "ok.json"
            ok_alias.write_text(json.dumps({"bindings": [{"action": "cheat_sheet", "mod": "SUPER ALT", "key": "slash"}]}))
            actions = {a["id"]: a for a in json.loads((PROJECT_ROOT / "schema" / "actions.json").read_text())["actions"]}
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(cc._validate_fixed_bindings(PROJECT_ROOT, actions, [bad]))
                self.assertTrue(cc._validate_fixed_bindings(PROJECT_ROOT, actions, [ok_alias]))


class TestAutoSwitchState(unittest.TestCase):
    """Auto switches mark state['auto'], notify, and manual switches cancel the auto-return."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("OMNIPAL_CONFIG_DIR")
        os.environ["OMNIPAL_CONFIG_DIR"] = self._tmp.name
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.engine.restore()
        self.notes = []
        self._orig_notify = _engine_core.notify_user
        _engine_core.notify_user = lambda t, b="": self.notes.append((t, b))
        self.engine.save_app_rules({"enabled": True, "rules": [{"class": "code", "mode": "mac"}]})

    def tearDown(self):
        _engine_core.notify_user = self._orig_notify
        self.engine.restore(auto=None)
        if self._old is None:
            os.environ.pop("OMNIPAL_CONFIG_DIR", None)
        else:
            os.environ["OMNIPAL_CONFIG_DIR"] = self._old
        self._tmp.cleanup()

    def test_auto_marks_state_and_notifies(self):
        self.assertTrue(self.engine.switch_mode("windows"))
        self.assertEqual(self.engine.apply_app_rule("code"), "mac")
        auto = self.engine.get_state().get("auto")
        self.assertEqual((auto["app"], auto["mode"], auto["return_to"]), ("code", "mac", "windows"))
        self.assertIn("因为聚焦了 code", self.notes[-1][0])
        self.assertIn("离开后回到", self.notes[-1][1])
        self.assertEqual(self.engine.apply_app_rule("kitty"), "windows")
        self.assertIsNone(self.engine.get_state().get("auto"))
        self.assertIn("回到", self.notes[-1][0])

    def test_manual_switch_cancels_auto_return(self):
        self.assertTrue(self.engine.switch_mode("windows"))
        self.engine.apply_app_rule("code")
        prev = self.engine.cancel_auto()           # what the CLI does before a manual switch
        self.assertEqual(prev["return_to"], "windows")
        self.assertTrue(self.engine.switch_mode("omarchy"))
        self.engine.notify_manual_override(prev, "omarchy")
        self.assertIn("已取消自动返回", self.notes[-1][1])
        self.assertIsNone(self.engine.get_state().get("auto"))
        self.assertIsNone(self.engine.apply_app_rule("kitty"))   # stays on omarchy (new base)
        self.assertEqual(self.engine.get_state().get("mode"), "omarchy")
        self.assertEqual(self.engine.apply_app_rule("code"), "mac")
        self.assertEqual(self.engine.get_state()["auto"]["return_to"], "omarchy")

    def test_manual_switch_to_same_mode_still_cancels(self):
        self.assertTrue(self.engine.switch_mode("windows"))
        self.engine.apply_app_rule("code")
        self.engine.cancel_auto()
        self.assertTrue(self.engine.switch_mode("mac"))
        self.assertIsNone(self.engine.get_state().get("auto"))
        self.assertIsNone(self.engine.apply_app_rule("kitty"))
        self.assertEqual(self.engine.get_state().get("mode"), "mac")


class TestUiAutoOverrideText(unittest.TestCase):
    def test_bar_and_settings_show_auto_and_window_mode(self):
        bar = (PROJECT_ROOT / "plugins/omni.mode-indicator/BarWidget.qml").read_text(encoding="utf-8")
        self.assertIn("active: root.engineRunning && root.autoActive", bar)
        self.assertIn("离开后回到", bar)
        st = (PROJECT_ROOT / "plugins/omni.settings/SettingsPanel.qml").read_text(encoding="utf-8")
        self.assertIn("root.windowModeLabel(modeCard.modelData.windowMode)", st)
        self.assertIn("Super+Alt+/", st)
        self.assertIn("已覆盖 · ", bar)
        self.assertIn("（已覆盖：全局", st)
        self.assertIn("已覆盖 · ", st)
        for qml in (bar, st):
            self.assertNotIn("Style.font.caption", qml)
            self.assertNotIn("Style.font.bodySmall", qml)

class TestSettingsSingleEntry(unittest.TestCase):
    """Design review item 4: settings is the one complete entry point."""
    def setUp(self):
        self.bar = (PROJECT_ROOT / "plugins/omni.mode-indicator/BarWidget.qml").read_text(encoding="utf-8")
        self.st = (PROJECT_ROOT / "plugins/omni.settings/SettingsPanel.qml").read_text(encoding="utf-8")

    def test_settings_window_policy_selector(self):
        for present in ('["omni-profile", "window-policy", "set", policy]', "policyOptions", "policyGroup",
                        "policyOverridden", "已覆盖", '"follow-profile"', '"tiled"', '"floating"'):
            self.assertIn(present, self.st, present)
        for gone in ('"stats"', "statsProc", "resetStats", "askResetStats", "重置统计数据", "analyticsTab", "RankRow"):
            self.assertNotIn(gone, self.st, gone)
        self.assertIn('["模式", "选项", "规则"]', self.st)

    def test_bar_menu_has_full_quick_controls(self):
        """User request: functions are back in the bar right-click menu (both places work)."""
        self.assertIn('label: "打开设置"', self.bar)
        for present in ("actionRows", "systemRows", "effPolicyBadge",
                        "omni-profile restore",
                        "omni-profile doctor", "omni-profile snap layouts",
                        "omni.overview", "omni.cheat-sheet", '\\"guide\\":true',
                        '"速查表"', '"概览"', '"贴靠布局"',
                        "还原 Omarchy 原生模式", "PanelSectionHeader", "PanelSeparator",
                        "restoreArmed", "Safety.CONFIRM_MS", "root.undoMode = root.currentMode"):
            self.assertIn(present, self.bar, present)
        # 分组顺序：模式 → 窗口策略 → 快捷入口 → 系统 → 打开设置
        order = [self.bar.index(f'text: "{h}"') for h in ("模式", "窗口策略", "快捷入口", "系统")]
        self.assertEqual(order, sorted(order))
        self.assertLess(order[-1], self.bar.index("row: root.settingsRow"))
        self.assertIn("omni-profile window-policy set ", self.bar)
        for bad in ("快捷键速查表\"", "多任务概览", "布局吸附", "控制中心", "切换下一模式"):
            self.assertNotIn(bad, self.bar, bad)

    def test_restore_merged_into_omarchy_card(self):
        self.assertIn('if (targetMode === "omarchy") root.askRestore()', self.st)
        self.assertIn("onClicked: root.selectMode(modeCard.modelData.id)", self.st)
        self.assertNotIn("restoreCardBody", self.st)
        for bad in ("恢复原生快捷键", "还原原生快捷键", "系统原生还原"):
            self.assertNotIn(bad, self.st)
            self.assertNotIn(bad, self.bar)

    def test_settings_keeps_quick_actions(self):
        for present in ("omni.cheat-sheet", "omni.snap-feedback", "askRestore"):
            self.assertIn(present, self.st)


class TestModeDiff(unittest.TestCase):
    def setUp(self):
        self.e = OmniPalEngine(PROJECT_ROOT)
        self.e._get_active_overlay = lambda: []
        self.e.baseline_bindings = {}
        self.e._load_baseline_cache = lambda: {}

    def test_live_natives_listed_with_previous_function(self):
        from engine.engine import combo_signature
        sig = combo_signature("SUPER + TAB")
        self.e._live_bind_details = lambda: {sig: [{"description": "Next workspace", "dispatcher": "__lua", "arg": "12"}]}
        d = self.e.mode_diff("windows")
        self.assertEqual(d["source"], "live")
        tab = [t for t in d["takeovers"] if t["combo"] == "SUPER + TAB"]
        self.assertEqual(len(tab), 1)
        self.assertEqual(tab[0]["native"][0], {"description": "Next workspace", "dispatcher": "__lua", "arg": ""})
        self.assertEqual(d["count"], len(d["takeovers"]))

    def test_baseline_fallback_and_unknown_mode(self):
        self.e._live_bind_details = lambda: {}
        self.e.baseline_bindings = {"SUPER + TAB": {"combo": "SUPER + TAB", "description": "Next workspace", "dispatcher": "workspace", "arg": "e+1"}}
        d = self.e.mode_diff("windows")
        self.assertEqual(d["source"], "baseline")
        self.assertTrue(any(t["combo"] == "SUPER + TAB" for t in d["takeovers"]))
        with self.assertRaises(ValueError):
            self.e.mode_diff("nope")

    def test_no_data(self):
        self.e._live_bind_details = lambda: {}
        d = self.e.mode_diff("mac")
        self.assertEqual((d["source"], d["count"]), ("none", 0))


class TestModeDiffFilters(unittest.TestCase):
    def setUp(self):
        self.e = OmniPalEngine(PROJECT_ROOT)
        self.e._get_active_overlay = lambda: []
        self.e.baseline_bindings = {}
        self.e._load_baseline_cache = lambda: {}

    def test_dedupes_and_drops_own_binds(self):
        from engine.engine import combo_signature, format_combo
        fb = self.e.fixed_bindings[0]
        fcombo = format_combo(fb.get("mod", ""), fb["key"])
        own_name = self.e.actions_catalog[fb["action"]]["name"]
        tab = combo_signature("SUPER + TAB")
        self.e._live_bind_details = lambda: {
            tab: [{"description": "Next workspace", "dispatcher": "__lua", "arg": str(i)} for i in range(14)],
            combo_signature(fcombo): [{"description": own_name, "dispatcher": "__lua", "arg": "9"}],
        }
        d = self.e.mode_diff("windows")
        t = [x for x in d["takeovers"] if x["combo"] == "SUPER + TAB"][0]
        self.assertEqual(len(t["native"]), 1)
        self.assertFalse(any(x["combo"] == fcombo for x in d["takeovers"]))


class _FakeCompositor:
    """Interprets the engine's Lua ops against an in-memory bind table (hl.unbind removes one bind)."""
    import re as _re
    TOKEN = _re.compile(
        r'hl\.unbind\("([^"]+)"\)'
        r'|R\.omnipal_stash\["([^"]+)"\] = \{ (.*?) \} end'
        r'|R\.omnipal_stash = nil|debug\.getregistry\(\)\.omnipal_stash = nil'
        r'|hl\.bind\("([^"]+)", e\.h, e\.o\)'
        r'|hl\.bind\("([^"]+)", (?:fn_\d+|h\d+), \{ description = "([^"]*)"'
        r'|o\.bind\("([^"]+)", "([^"]*)"')

    def __init__(self, natives):
        self.binds, self.stash, self.ref = [], {}, 100
        for combo, desc in natives:
            self.add(combo, desc)

    def add(self, combo, desc):
        from engine.engine import combo_signature
        m, k = combo_signature(combo)
        self.ref += 1
        self.binds.append({"modmask": m, "key": k, "dispatcher": "__lua", "arg": str(self.ref), "description": desc})

    def unbind(self, combo):
        from engine.engine import combo_signature
        sig = combo_signature(combo)
        for i, b in enumerate(self.binds):
            if (b["modmask"], b["key"]) == sig:
                del self.binds[i]
                return

    def eval(self, code):
        import re
        for m in self.TOKEN.finditer(code):
            g = m.groups()
            if g[0]:
                self.unbind(g[0])
            elif g[1]:
                self.stash[g[1]] = re.findall(r'description = "([^"]*)"', g[2])
            elif m.group(0).endswith("omnipal_stash = nil"):
                self.stash = {}
            elif g[3]:
                for d in self.stash.pop(g[3], []):
                    self.add(g[3], d)
            elif g[4]:
                self.add(g[4], g[5])
            elif g[6]:
                self.add(g[6], g[7])
        return True

    def hyprctl(self):
        """What `hyprctl binds -j` shows: Omarchy's code:NN binds come back as key "" / keycode 0."""
        out = []
        for b in self.binds:
            d = dict(b)
            if d["key"].startswith("CODE:"):
                d["key"], d["keycode"] = "", 0
            out.append(d)
        return out

    def details(self):
        from engine.engine import bind_signature
        out = {}
        for b in self.hyprctl():
            sig = bind_signature(b)
            if sig is not None:
                out.setdefault(sig, []).append(b)
        return out

    def counts(self):
        return {k: len(v) for k, v in self.details().items()}

    def by_desc(self, desc):
        return sum(1 for b in self.binds if b["description"] == desc)


class TestNoDuplicateNativeBinds(unittest.TestCase):
    """Repeated switch / restore / daemon start cycles must leave exactly one bind per native."""
    NATIVES = [("SUPER + RETURN", "Terminal"), ("SUPER + TAB", "Next workspace"),
               ("SUPER + W", "Close window"), ("SUPER + SPACE", "Launch apps"),
               ("SUPER + E", "File manager"), ("SUPER + D", "Show desktop"),
               ("ALT + TAB", "Cycle windows"), ("ALT + TAB", "Bring to top")]

    def setUp(self):
        from engine.engine import combo_signature
        self.sig = combo_signature
        self.fc = _FakeCompositor(self.NATIVES)
        self.engine = e = OmniPalEngine(PROJECT_ROOT)
        self.overlay, self.calls = [], []
        e._eval_lua = self.fc.eval
        e._eval_lua_strict = self.fc.eval
        e._reload_hyprland = self._reload
        e._write_active_overlay = lambda recs: setattr(self, "overlay", recs)
        e._get_active_overlay = lambda: self.overlay
        e._write_state = lambda *a, **k: None
        e.get_persistence_status = lambda: {"enabled": False}
        e._live_bind_counts = self.fc.counts
        e._live_bind_details = self.fc.details
        e._apply_window_policy = lambda *a, **k: True
        e._get_applied_window_mode = lambda: "tiled"
        real_restore = e.restore

        def restore(*a, **k):  # the real restore deletes the overlay file
            ok = real_restore(*a, **k)
            if ok:
                self.overlay = []
            return ok
        e.restore = restore
        e.baseline_bindings = {c: dict(b, combo=c) for b in self.fc.binds
                               for c in [next(cc for cc, d in self.NATIVES if d == b["description"])]}

    def _reload(self):
        self.calls.append("reload")
        self.fc.__init__(self.NATIVES)
        return True

    def assert_no_dups(self, where):
        from engine.engine import find_duplicate_binds
        self.assertEqual(find_duplicate_binds(self.fc.binds), {}, where)

    def assert_natives_exact(self, where):
        counts = self.fc.counts()
        for combo, n in [("SUPER + RETURN", 1), ("SUPER + TAB", 1), ("ALT + TAB", 2), ("SUPER + E", 1)]:
            self.assertEqual(counts.get(self.sig(combo), 0), n, f"{where}: {combo}")

    def test_repeated_cycles_never_duplicate(self):
        e = self.engine
        e.dedupe_binds = lambda: 0  # prove the paths themselves are idempotent, not just self-healed
        for i in range(12):
            self.assertTrue(e.switch_mode("windows"))
            self.assert_no_dups(f"switch windows #{i}")
            self.assertTrue(e.switch_mode("mac"))
            self.assert_no_dups(f"switch mac #{i}")
            self.assertTrue(e.switch_mode("windows"))
            self.assertTrue(e.restore())
            self.assert_no_dups(f"restore #{i}")
            self.assert_natives_exact(f"restore #{i}")
            self.assertTrue(e.restore())  # restore twice in a row must be a no-op
            self.assert_natives_exact(f"double restore #{i}")
            # daemon start in omarchy mode, then a start that re-applies a persisted mode
            self.assertTrue(e.apply_fixed_bindings())
            self.assertTrue(e.switch_mode("windows"))
            self.assertTrue(e.switch_mode("windows"))  # configreloaded / socket reconnect re-apply
            self.assert_no_dups(f"restart #{i}")
            self.assertTrue(e.restore(sync_persistence=False))  # daemon stop
            self.assert_natives_exact(f"daemon stop #{i}")
        self.assertEqual(self.fc.counts()[self.sig("SUPER + RETURN")], 1)
        self.assertEqual(self.calls, [])

    def test_unstash_unbinds_a_still_live_native_first(self):
        e = self.engine
        self.assertTrue(e.switch_mode("windows"))
        stashed = [b["combo"] for b in self.overlay if b.get("native_count")]
        self.assertTrue(stashed)
        for c in stashed:  # something re-added the native behind our back
            self.fc.add(c, "re-added")
        self.assertTrue(e.restore())
        for c in stashed:
            descs = [b["description"] for b in self.fc.details().get(self.sig(c), [])]
            self.assertNotIn("re-added", descs, c)
        self.assert_natives_exact("restore")

    def test_dedupe_collapses_existing_duplicates(self):
        for _ in range(38):
            self.fc.add("SUPER + RETURN", "Terminal")
        self.fc.add("SUPER + TAB", "Next workspace")
        self.assertEqual(self.engine.dedupe_binds(), 39)
        self.assert_no_dups("dedupe")
        self.assert_natives_exact("dedupe")

    def test_doctor_reports_duplicates_unhealthy(self):
        from engine.engine import find_duplicate_binds
        for _ in range(38):
            self.fc.add("SUPER + RETURN", "Terminal")
        self.assertEqual(find_duplicate_binds(self.fc.binds), {self.sig("SUPER + RETURN"): 38})
        self.engine.check_installation = lambda: {"problems": []}
        rep = self.engine.doctor()
        self.assertFalse(rep["healthy"])
        self.assertEqual(rep["duplicate_binds"]["count"], 38)
        self.assertTrue(any(i.startswith("❌ Duplicate binds: 38") for i in rep["issues"]))

    def test_distinct_binds_on_same_key_are_not_duplicates(self):
        from engine.engine import find_duplicate_binds
        self.assertEqual(find_duplicate_binds(self.fc.binds), {})


class TestKeycodeBindsSurviveRestarts(TestNoDuplicateNativeBinds):
    """code:NN binds (hyprctl: key "" keycode 0) must never be deduped/replayed into copies."""
    NATIVES = TestNoDuplicateNativeBinds.NATIVES + [
        (f"SUPER + code:{9 + n}", f"Switch to workspace {n}") for n in range(1, 11)] + [
        (f"SUPER + SHIFT + code:{9 + n}", f"Move window to workspace {n}") for n in range(1, 11)] + [
        ("SUPER + code:20", "Expand window left"), ("SUPER + code:21", "Shrink window left")]

    def _stop(self):
        # legacy unit: ExecStop `omni-profile restore` + the daemon's SIGTERM restore
        self.assertTrue(self.engine.restore())
        self.assertTrue(self.engine.restore(sync_persistence=False))

    def _assert_keycode_binds_exact(self, where):
        for combo, desc in self.NATIVES:
            if "code:" in combo:
                self.assertEqual(self.fc.by_desc(desc), 1, f"{where}: {desc}")
        self.assertEqual(sum(1 for b in self.fc.binds if b["key"] == ""), 0, where)

    def test_restart_cycles_keep_keycode_binds_single(self):
        e = self.engine
        for i in range(3):
            self._stop()
            self.assertTrue(e.apply_fixed_bindings())  # start in omarchy mode
            self._assert_keycode_binds_exact(f"restart omarchy #{i}")
            self.assert_natives_exact(f"restart omarchy #{i}")
            self.assertTrue(e.switch_mode("windows"))
            self._stop()
            self.assertTrue(e.switch_mode("windows"))  # start re-applying a persisted mode
            self._assert_keycode_binds_exact(f"restart windows #{i}")
        self.assert_no_dups("end")

    def test_dedupe_never_touches_unidentifiable_binds(self):
        from engine.engine import find_duplicate_binds
        evals = []
        self.engine._eval_lua = lambda code: evals.append(code) or True
        self.assertEqual(find_duplicate_binds(self.fc.hyprctl()), {})
        self.assertEqual(self.engine.dedupe_binds(), 0)
        self.assertEqual(evals, [])

    def test_identical_keycode_binds_with_real_keycode_are_duplicates(self):
        from engine.engine import find_duplicate_binds
        b = {"modmask": 64, "key": "", "keycode": 10, "dispatcher": "__lua", "arg": "5", "description": "ws1"}
        c = dict(b, keycode=11)
        self.assertEqual(find_duplicate_binds([b, dict(b, arg="6"), c]), {(64, "CODE:10"): 1})


class TestStopRunsOneRestore(unittest.TestCase):
    def test_unit_has_no_execstop_restore(self):
        text = (PROJECT_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("ExecStop=", text)

    def test_cli_restore_skips_under_systemd_stop(self):
        env = dict(os.environ, SERVICE_RESULT="success", INVOCATION_ID="x", PATH=str(PROJECT_ROOT / "tests" / "fakebin") + ":" + os.environ.get("PATH", ""))
        res = subprocess.run([sys.executable, str(PROJECT_ROOT / "bin" / "omni-profile"), "restore"],
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("skipping duplicate restore", res.stdout)


class TestWindowPolicyPersistsFollowProfile(unittest.TestCase):
    def test_follow_profile_is_persisted_and_returned(self):
        e = OmniPalEngine(PROJECT_ROOT)
        written = {}
        e.get_persistence_status = lambda: {"enabled": True, "profile": "windows",
                                            "window_policy": written.get("window_policy", "floating")}
        e.set_persistence = lambda enabled, profile=None, window_policy=None: written.update(window_policy=window_policy) or True
        e._apply_window_policy = lambda *a, **k: True
        e._write_state = lambda *a, **k: None
        self.assertEqual(e.get_persisted_window_policy(), "floating")
        self.assertTrue(e.set_window_policy("follow-profile"))
        self.assertEqual(written["window_policy"], "follow-profile")
        # startup must see follow-profile (previously ignored, so a stale state 'floating' won)
        self.assertEqual(e.get_persisted_window_policy(), "follow-profile")
