#!/usr/bin/env python3
"""
OmniPal Automated Unit Tests
Tests schema consistency, state management, and profile parsing.
"""

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
        """Validates that all profiles strictly adhere to schema/actions.json"""
        self.assertTrue(check_consistency(PROJECT_ROOT))

    def test_format_combo(self):
        """Verifies modifier string formatting into standard Hyprland combos"""
        self.assertEqual(format_combo("ALT", "F4"), "ALT + F4")
        self.assertEqual(format_combo("SUPER", "Left"), "SUPER + LEFT")
        self.assertEqual(format_combo("SUPER SHIFT", "s"), "SUPER + SHIFT + S")
        self.assertEqual(format_combo("SUPER CTRL", "q"), "SUPER + CTRL + Q")

    def test_profiles_loaded(self):
        """Ensures all default profiles are registered"""
        self.assertIn("omarchy", self.engine.profiles)
        self.assertIn("windows", self.engine.profiles)
        self.assertIn("mac", self.engine.profiles)

    def test_cheatsheet_generation(self):
        """Checks cheatsheet data extraction from single source of truth"""
        win_sheet = self.engine.cheatsheet("windows")
        self.assertGreater(len(win_sheet), 0)
        self.assertTrue(any("F4" in item["key"] for item in win_sheet))

        mac_sheet = self.engine.cheatsheet("mac")
        self.assertGreater(len(mac_sheet), 0)
        self.assertTrue(any("Q" in item["key"] for item in mac_sheet))

if __name__ == "__main__":
    unittest.main()
