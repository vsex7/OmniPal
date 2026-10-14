#!/usr/bin/env python3
"""First-run guide flag, Omarchy menu extension block, and takeover parsing (Takeovers.js)."""

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

from engine import onboarding  # noqa: E402

OMARCHY_TEMPLATE = Path("/workspace/ref/omarchy/config/omarchy/extensions/omarchy-menu.jsonc")
PROFILES = [
    {"id": "windows", "name": "Windows 11 习惯模式", "description": "d"},
    {"id": "mac", "name": "macOS 习惯模式", "description": ""},
    {"id": "bad id", "name": "x"},
]
TEMPLATE_FALLBACK = '{\n  // comment\n  // "about": {"icon":"","label":"About"},\n}\n'


class OnboardingFlagTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.cfg = Path(self.td.name) / "omnipal"

    def tearDown(self):
        self.td.cleanup()

    def test_claim_only_once(self):
        self.assertFalse(onboarding.onboarding_status(self.cfg)["shown"])
        self.assertTrue(onboarding.onboarding_claim(self.cfg))
        self.assertFalse(onboarding.onboarding_claim(self.cfg))
        st = onboarding.onboarding_status(self.cfg)
        self.assertTrue(st["shown"])
        self.assertIn("shown_at", st)

    def test_reset_allows_one_more(self):
        onboarding.onboarding_claim(self.cfg)
        self.assertTrue(onboarding.onboarding_reset(self.cfg))
        self.assertFalse(onboarding.onboarding_reset(self.cfg))
        self.assertTrue(onboarding.onboarding_claim(self.cfg))

    def test_unwritable_dir_never_shows(self):
        blocker = Path(self.td.name) / "file"
        blocker.write_text("x")
        self.assertFalse(onboarding.onboarding_claim(blocker / "sub"))

    def test_cli_claim(self):
        env = dict(os.environ, OMNIPAL_CONFIG_DIR=str(self.cfg))
        env.setdefault("XDG_RUNTIME_DIR", self.td.name)
        cmd = [sys.executable, str(PROJECT_ROOT / "bin" / "omni-profile"), "onboarding", "claim", "--json"]
        first = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
        second = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(first.stdout.strip().splitlines()[-1]), {"show": True})
        self.assertEqual(json.loads(second.stdout.strip().splitlines()[-1]), {"show": False})


class MenuExtensionTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.cfg = Path(self.td.name) / "omnipal"
        self.menu = Path(self.td.name) / "omarchy" / "extensions" / "omarchy-menu.jsonc"
        self.menu.parent.mkdir(parents=True)

    def tearDown(self):
        self.td.cleanup()

    def template(self):
        return OMARCHY_TEMPLATE.read_text(encoding="utf-8") if OMARCHY_TEMPLATE.exists() else TEMPLATE_FALLBACK

    def install(self):
        return onboarding.menu_install(PROFILES, "/home/u/.local/bin/omni-profile", self.menu, self.cfg)

    def test_install_into_template_and_uninstall_restores(self):
        orig = self.template()
        self.menu.write_text(orig, encoding="utf-8")
        r = self.install()
        self.assertEqual(r["modes"], ["setup.omnipal.mode-windows", "setup.omnipal.mode-mac"])
        items = onboarding.parse_menu_items(self.menu.read_text(encoding="utf-8"))
        self.assertEqual(items["setup.omnipal"]["label"], "快捷键模式")
        self.assertIn("omnipal", items["setup.omnipal"]["aliases"])
        self.assertEqual(items["setup.omnipal.mode-mac"]["action"], "'/home/u/.local/bin/omni-profile' switch mac")
        self.assertIn("== mac ]]", items["setup.omnipal.mode-mac"]["checked"])
        self.assertIn("omni.settings", items["setup.omnipal.settings"]["action"])
        self.assertEqual(items["setup.omnipal.cheatsheet"]["label"], "速查表")
        self.assertIn('"guide":true', items["setup.omnipal.guide"]["action"])
        self.assertFalse(r["created_file"])
        u = onboarding.menu_uninstall(self.menu, self.cfg)
        self.assertTrue(u["removed_block"])
        self.assertFalse(u["removed_file"])
        self.assertEqual(self.menu.read_text(encoding="utf-8"), orig)
        self.assertFalse((self.cfg / onboarding.MENU_STATE_FILE).exists())

    def test_reinstall_is_idempotent(self):
        self.menu.write_text(self.template(), encoding="utf-8")
        self.install()
        once = self.menu.read_text(encoding="utf-8")
        self.install()
        self.assertEqual(self.menu.read_text(encoding="utf-8"), once)
        self.assertEqual(once.count(onboarding.BLOCK_BEGIN), 1)

    def test_keeps_user_entries_and_adds_comma(self):
        self.menu.write_text('{\n  "personal": {"label": "Personal"}\n}\n', encoding="utf-8")
        self.install()
        items = onboarding.parse_menu_items(self.menu.read_text(encoding="utf-8"))
        self.assertIn("personal", items)
        self.assertIn("setup.omnipal", items)
        onboarding.menu_uninstall(self.menu, self.cfg)
        items = onboarding.parse_menu_items(self.menu.read_text(encoding="utf-8"))
        self.assertEqual(list(items), ["personal"])

    def test_created_file_is_removed_on_uninstall(self):
        self.install()
        self.assertTrue(self.menu.exists())
        u = onboarding.menu_uninstall(self.menu, self.cfg)
        self.assertTrue(u["removed_file"])
        self.assertFalse(self.menu.exists())

    def test_refuses_broken_or_wrapped_file(self):
        self.menu.write_text('{ "a": ', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(self.menu.read_text(encoding="utf-8"), '{ "a": ')
        self.menu.write_text('{"items": {"a": {"label": "A"}}}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.install()

    def test_uninstall_without_block_is_noop(self):
        self.menu.write_text('{\n  "a": {"label": "A"},\n}\n', encoding="utf-8")
        u = onboarding.menu_uninstall(self.menu, self.cfg)
        self.assertFalse(u["removed_block"])
        self.assertTrue(self.menu.exists())

    def test_scripts_register_and_remove(self):
        install = (PROJECT_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        uninstall = (PROJECT_ROOT / "scripts" / "uninstall.sh").read_text(encoding="utf-8")
        self.assertIn("menu install", install)
        self.assertIn("fixed_bindings.json", install)
        self.assertIn("menu uninstall", uninstall)
        self.assertIn("onboarding.json", uninstall)
        self.assertNotIn("/usr/share/omarchy", install)


NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node not installed")
class TakeoverParsingTest(unittest.TestCase):
    def run_js(self, expr):
        src = (PROJECT_ROOT / "plugins" / "shared" / "Takeovers.js").read_text(encoding="utf-8")
        src = src.replace(".pragma library", "")
        out = subprocess.run([NODE, "-e", src + "\nconsole.log(JSON.stringify(" + expr + "));"],
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    DOCTOR = {"healthy": False, "takeovers": {
        "mac": {"mode": "mac", "source": "live", "count": 2, "takeovers": [
            {"combo": "SUPER + SPACE", "name": "启动器", "fixed": False,
             "native": [{"description": "Launch apps", "dispatcher": "exec", "arg": "walker"}]},
            {"combo": "SUPER + ALT + I", "name": "控制中心", "fixed": True,
             "native": [{"description": "", "dispatcher": "exec", "arg": "foo"}]}]},
        "kde": {"mode": "kde", "source": "none", "count": 0, "takeovers": []},
        "windows": {"mode": "windows", "error": "boom"},
        "omarchy": {"mode": "omarchy", "source": "baseline", "count": 0, "takeovers": []}}}

    def test_parse_ok(self):
        r = self.run_js("forMode(%s, 'mac')" % json.dumps(self.DOCTOR))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["items"][0]["combo"], "Super+Space")
        self.assertEqual(r["items"][0]["was"], "Launch apps")
        self.assertFalse(r["items"][0]["fixed"])
        self.assertTrue(r["items"][1]["fixed"])
        self.assertEqual(r["items"][1]["was"], "exec foo")

    def test_source_none_and_errors(self):
        d = json.dumps(self.DOCTOR)
        none = self.run_js("forMode(%s, 'kde')" % d)
        self.assertEqual(none["status"], "none")
        self.assertIn("读不到", none["hint"])
        self.assertEqual(self.run_js("forMode(%s, 'windows')" % d)["status"], "error")
        self.assertEqual(self.run_js("forMode(%s, 'omarchy')" % d)["status"], "empty")
        self.assertEqual(self.run_js("forMode(%s, 'nope')" % d)["status"], "unknown")
        self.assertEqual(self.run_js("forMode(null, 'mac')")["status"], "unknown")
        self.assertEqual(self.run_js("forMode('not json', 'mac')")["status"], "unknown")

    def test_parse_doctor_text_with_noise(self):
        text = "Warning: x\n" + json.dumps(self.DOCTOR) + "\n"
        r = self.run_js("forMode(parseDoctor(%s), 'mac')" % json.dumps(text))
        self.assertEqual(len(r["items"]), 2)

    def test_pretty_combo(self):
        self.assertEqual(self.run_js("prettyCombo('SUPER + CTRL + SLASH')"), "Super+Ctrl+/")
        self.assertEqual(self.run_js("prettyCombo('SUPER + SHIFT + F4')"), "Super+Shift+F4")
        self.assertEqual(self.run_js("prettyCombo('ALT + ESCAPE')"), "Alt+Esc")


class PluginWiringTest(unittest.TestCase):
    def test_cheat_sheet_and_settings_use_takeovers(self):
        cs = (PROJECT_ROOT / "plugins" / "omni.cheat-sheet" / "CheatSheet.qml").read_text(encoding="utf-8")
        st = (PROJECT_ROOT / "plugins" / "omni.settings" / "SettingsPanel.qml").read_text(encoding="utf-8")
        for src in (cs, st):
            self.assertIn('import "Takeovers.js" as Takeovers', src)
            self.assertIn("doctor --json", src)
            self.assertIn("原来的功能：", src)
        self.assertIn("onboarding claim --json", cs)
        self.assertIn("guideShown", cs)


if __name__ == "__main__":
    unittest.main()
