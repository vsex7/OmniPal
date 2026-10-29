#!/usr/bin/env python3
"""Regression tests for the 2026-10-17 UX/design fixes.

Covers review issues #1 (cheatsheet naming/merging), #2 (protected
system keybindings), #6a (`diff` unknown state) and #6b (unified fixed
entry modifiers). No new features; only existing design corrections.
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if not shutil.which("hyprctl") or os.environ.get("OMNIPAL_FAKE_HYPRCTL") == "1":
    os.environ["PATH"] = str(Path(__file__).resolve().parent / "fakebin") + os.pathsep + os.environ.get("PATH", "")
if not os.environ.get("XDG_RUNTIME_DIR") or not os.path.isdir(os.environ["XDG_RUNTIME_DIR"]):
    os.environ["XDG_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="omnipal-test-ux-")
_cfg = tempfile.TemporaryDirectory()
os.environ["OMNIPAL_CONFIG_DIR"] = _cfg.name
_run = tempfile.TemporaryDirectory()
os.environ["OMNIPAL_RUN_DIR"] = _run.name
os.environ["OMNIPAL_DRY_RUN"] = "1"

from engine.engine import OmniPalEngine
import scripts.check_consistency as cc


def _engine():
    return OmniPalEngine(PROJECT_ROOT)


def _load_cli():
    # bin/omni-profile has no .py suffix, so name the loader explicitly.
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("omni_profile_cli", str(PROJECT_ROOT / "bin" / "omni-profile"))
    spec = importlib.util.spec_from_loader("omni_profile_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _actions():
    return {a["id"]: a for a in
            json.loads((PROJECT_ROOT / "schema" / "actions.json").read_text(encoding="utf-8"))["actions"]}


class TestForwardNaming(unittest.TestCase):
    """Issue #1: every forward_shortcut row must be distinguishable."""

    def test_mac_forwards_all_named_distinctly(self):
        sheet = _engine().cheatsheet("mac")
        fw = [r for r in sheet if r["action"] == "forward_shortcut"]
        self.assertEqual(len(fw), 17)
        names = [r["name"] for r in fw]
        self.assertEqual(len(set(names)), 17, f"duplicate forward names: {names}")
        for r in fw:
            self.assertIn("发送 Ctrl", r["name"])
            self.assertEqual(r["category"], "app")

    def test_forward_name_examples(self):
        sheet = _engine().cheatsheet("mac")
        by_key = {r["key"]: r["name"] for r in sheet if r["action"] == "forward_shortcut"}
        self.assertEqual(by_key["SUPER + W"], "关闭标签页（发送 Ctrl+W）")
        self.assertEqual(by_key["SUPER + 1"], "切换到第1个标签页（发送 Ctrl+1）")

    def test_forward_without_name_falls_back_to_target(self):
        e = _engine()
        e.profiles["_t"] = {"id": "_t", "bindings": [
            {"mod": "SUPER", "key": "X", "action": "forward_shortcut", "forward": "CTRL X"}]}
        sheet = e.cheatsheet("_t")
        self.assertEqual(sheet[0]["name"], "转发为 Ctrl+X")

    def test_binding_name_must_be_str(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"id": "x", "bindings": [
                {"action": "lock_screen", "mod": "SUPER", "key": "Q", "name": 123}]}),
                encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(cc._validate_profile_file(bad, _actions()))


class TestCheatsheetMerge(unittest.TestCase):
    """Issue #1: one action -> one row listing every combo."""

    def test_fixed_entries_merged_with_profile_aliases(self):
        sheet = _engine().cheatsheet("windows")
        for action in ("omni_settings",):
            rows = [r for r in sheet if r["action"] == action]
            self.assertEqual(len(rows), 1, f"{action} should be a single merged row")
            self.assertIn("/", rows[0]["key"])
            self.assertTrue(rows[0].get("fixed"))

    def test_merge_keeps_both_combos(self):
        sheet = _engine().cheatsheet("mac")
        cs = next(r for r in sheet if r["action"] == "task_view")
        self.assertIn("UP", cs["key"])
        self.assertIn("/", cs["key"])
        self.assertNotIn("keys", cs, "merge accumulator must not leak into the row")


class TestProtectedBindings(unittest.TestCase):
    """Issue #2: system-critical combos must be rejected at validation."""

    def test_rejects_omarchy_menu_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"id": "x", "bindings": [
                {"action": "file_manager", "mod": "SUPER", "key": "space"}]}),
                encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertFalse(cc._validate_protected_bindings(PROJECT_ROOT, [bad]))
            self.assertIn("Omarchy", err.getvalue())

    def test_allows_compliant_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = Path(tmp) / "ok.json"
            ok.write_text(json.dumps({"id": "x", "bindings": [
                {"action": "file_manager", "mod": "SUPER ALT", "key": "E"}]}),
                encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(cc._validate_protected_bindings(PROJECT_ROOT, [ok]))

    def test_mac_profile_passes_protected_check(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(cc._validate_protected_bindings(
                PROJECT_ROOT, [PROJECT_ROOT / "profiles" / "mac.json"]))

    def test_mac_file_manager_not_on_menu_key(self):
        mac = json.loads((PROJECT_ROOT / "profiles" / "mac.json").read_text(encoding="utf-8"))
        for b in mac["bindings"]:
            self.assertFalse(
                b.get("mod", "").upper().replace(" ", "") == "SUPER"
                and b.get("key", "").lower() == "space",
                "mac profile must not override the Omarchy menu key")


class TestProtectedEnforcement(unittest.TestCase):
    """P0 follow-up: `import` and `doctor` must enforce protected bindings,
    not just the dev-side consistency checker."""

    def test_import_rejects_protected_combo(self):
        cli = _load_cli()
        e = _engine()
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "evil.json"
            bad.write_text(json.dumps({"id": "evil", "name": "evil", "bindings": [
                {"action": "lock_screen", "mod": "SUPER", "key": "space"}]}),
                encoding="utf-8")
            args = types.SimpleNamespace(file=str(bad), id=None, force=False, yes=True)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as cm:
                    cli.cmd_import(e, args)
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("保护键位", err.getvalue())
            self.assertFalse((e.user_profiles_dir / "evil.json").exists())

    def test_import_accepts_compliant_profile(self):
        cli = _load_cli()
        e = _engine()
        dest = e.user_profiles_dir / "good.json"
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.json"
            good.write_text(json.dumps({"id": "good", "name": "good", "bindings": [
                {"action": "lock_screen", "mod": "SUPER", "key": "Q"}]}),
                encoding="utf-8")
            args = types.SimpleNamespace(file=str(good), id=None, force=False, yes=True)
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    cli.cmd_import(e, args)
            finally:
                if dest.exists():
                    dest.unlink()
        self.assertIn("已导入", out.getvalue())

    def test_doctor_names_protected_violation(self):
        e = _engine()
        e.profiles["_evil"] = {"id": "_evil", "bindings": [
            {"action": "lock_screen", "mod": "SUPER", "key": "space"}]}
        diag = e.doctor()
        hits = [i for i in diag["issues"] if "_evil" in i and "protected" in i]
        self.assertTrue(hits, f"doctor should name the violation, got: {diag['issues']}")
        self.assertTrue(diag["fixes"], "doctor should suggest a fix")

    def test_doctor_clean_tree_has_no_protected_issue(self):
        diag = _engine().doctor()
        self.assertFalse([i for i in diag["issues"] if "protected system key" in i])


class TestBindOpNaming(unittest.TestCase):
    """P2: the Hyprland bind description should prefer the binding-level name,
    so `hyprctl binds` agrees with the cheatsheet."""

    def test_bind_op_prefers_binding_name(self):
        e = _engine()
        ops, records = e._build_bind_ops([
            {"mod": "SUPER", "key": "W", "action": "forward_shortcut",
             "forward": "CTRL W", "name": "关闭标签页"}])
        binds = [o for o in ops if o.startswith("o.bind(")]
        self.assertTrue(binds, "expected at least one o.bind op")
        self.assertIn("关闭标签页", binds[0])
        self.assertEqual(records[0]["name"], "关闭标签页")

    def test_bind_op_falls_back_to_action_name(self):
        e = _engine()
        ops, _ = e._build_bind_ops([{"mod": "SUPER", "key": "Q", "action": "close_window"}])
        binds = [o for o in ops if o.startswith("o.bind(")]
        self.assertTrue(binds, "expected at least one o.bind op")
        self.assertIn("关闭当前窗口", binds[0])


class TestDiffUnknown(unittest.TestCase):
    """Issue #6a: `diff` with no Hyprland data must say 无法判断."""

    def test_diff_source_none_reports_unknown(self):
        cli = _load_cli()

        class _StubEngine:
            def mode_diff(self, mode):
                return {"mode": mode, "source": "none", "count": 0, "takeovers": []}

        args = types.SimpleNamespace(mode="mac", json=False)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.cmd_diff(_StubEngine(), args)
        self.assertIn("无法判断", out.getvalue())
        self.assertNotIn("0 个", out.getvalue())


class TestFixedEntries(unittest.TestCase):
    """Fixed entries must match schema/fixed_bindings.json exactly.

    NOTE: cheat_sheet is SUPER CTRL+slash, NOT SUPER ALT+slash — the latter
    collides with Omarchy's native "Monitor scaling down" (tiling.lua).
    Do not "unify" the modifiers without checking Omarchy defaults first."""

    def test_fixed_combos_match_schema(self):
        e = _engine()
        fixed = json.loads(
            (PROJECT_ROOT / "schema" / "fixed_bindings.json").read_text(encoding="utf-8"))["bindings"]
        expected = {f"{b['mod'].replace(' ', ' + ')} + {b['key'].upper()}": b["action"]
                    for b in fixed}
        self.assertEqual(e.fixed_combos(), expected)
        self.assertEqual(e.fixed_combos()["SUPER + CTRL + SLASH"], "cheat_sheet")


class TestCategoryLabels(unittest.TestCase):
    """Issue #1 follow-up: every action category needs a JS display label,
    so a missing label (like `app`) can never slip through again."""

    def test_every_category_has_cheatsheet_label(self):
        actions = json.loads(
            (PROJECT_ROOT / "schema" / "actions.json").read_text(encoding="utf-8"))["actions"]
        cats = {a["category"] for a in actions if a.get("category")}
        js = (PROJECT_ROOT / "plugins" / "omni.cheat-sheet" / "CheatSheetData.js").read_text(encoding="utf-8")
        m = re.search(r"var CATEGORY_LABELS = \{(.*?)\};", js, re.S)
        self.assertIsNotNone(m, "CATEGORY_LABELS not found in CheatSheetData.js")
        labels = set(re.findall(r"^\s*(\w+)\s*:", m.group(1), re.M))
        self.assertEqual(cats - labels, set(), f"categories without JS label")
        self.assertIn("app", labels)


if __name__ == "__main__":
    unittest.main()
