#!/usr/bin/env python3
"""
OmniPal security regression tests: untrusted import path -> Lua code generation.

Covers the audit of `omni-profile import` (and `rules import`):
  * every profile field that can reach `hyprctl eval` must stay inside a Lua
    string literal (lua_str() escaping), even for hostile payloads;
  * the profile validator must reject malformed types cleanly (no tracebacks);
  * oversized import files are refused;
  * imported app rules are type/length/regex validated.

Runs without Hyprland: OMNIPAL_DRY_RUN=1 + tests/fakebin hyprctl stub,
isolated config/run dirs (same harness as test_omni.py).
"""

import io
import json
import os
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

_GLOBAL_TEST_CONFIG_DIR = tempfile.TemporaryDirectory()
os.environ["OMNIPAL_CONFIG_DIR"] = _GLOBAL_TEST_CONFIG_DIR.name
_GLOBAL_TEST_RUN_DIR = tempfile.TemporaryDirectory()
os.environ["OMNIPAL_RUN_DIR"] = _GLOBAL_TEST_RUN_DIR.name
os.environ["OMNIPAL_DRY_RUN"] = "1"

from engine.engine import OmniPalEngine, lua_str
from scripts.check_consistency import _validate_profile_file

CLI = str(PROJECT_ROOT / "bin" / "omni-profile")
PWN = '"); os.execute("touch /tmp/omnipal_pwned"); --'


def _parse_lua_string(s, i):
    """Parses one Lua double-quoted literal starting at s[i]=='"',
    understanding exactly the escapes lua_str() emits."""
    assert s[i] == '"'
    i += 1
    out = []
    while True:
        c = s[i]
        if c == '"':
            return "".join(out), i + 1
        if c == "\\":
            n = s[i + 1]
            if n == "n":
                out.append("\n"); i += 2
            elif n == "r":
                out.append("\r"); i += 2
            elif n == "t":
                out.append("\t"); i += 2
            elif n == '"':
                out.append('"'); i += 2
            elif n == "\\":
                out.append("\\"); i += 2
            elif n.isdigit():
                out.append(chr(int(s[i + 1:i + 4]))); i += 4
            else:
                raise AssertionError(f"unexpected escape \\{n}")
        else:
            out.append(c); i += 1


def _split_lua(lua):
    """Returns (literals, code_only): string-literal contents vs everything else."""
    literals, code = [], []
    i = 0
    while i < len(lua):
        if lua[i] == '"':
            v, i = _parse_lua_string(lua, i)
            literals.append(v)
        else:
            code.append(lua[i]); i += 1
    return literals, "".join(code)


EVIL_BINDINGS = [
    {"action": "snap_left", "mod": "SUPER" + PWN, "key": "x"},
    {"action": "close_window", "mod": "SUPER", "key": "y" + PWN},
    {"action": "snap_right", "mod": "SUPER", "key": "z", "arg": PWN},
    {"action": "snap_top", "mod": "SUPER", "key": "a",
     "arg": 'line1\nline2\rline3\tend\\"quoted\\'},
    {"action": "forward_shortcut", "mod": "SUPER", "key": "w",
     "forward": "CTRL" + PWN},  # must be rejected by parse_forward
    {"action": "snap_bottom", "mod": "SUPER", "key": "b", "arg": "echo 你好 🎉"},
    {"action": "snap_center", "mod": "SUPER", "key": "c",
     "arg": "\x00\x01\x1f\x7f control chars"},
]


class TestLuaInjectionNeutralized(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = OmniPalEngine(root_dir=PROJECT_ROOT,
                                   user_profiles_dir=Path(tempfile.mkdtemp()))
        cls.ops, cls.records = cls.engine._build_bind_ops(EVIL_BINDINGS)
        cls.lua = "; ".join(cls.ops)
        cls.literals, cls.code_only = _split_lua(cls.lua)

    def test_no_breakout_tokens_outside_literals(self):
        for tok in ("os.execute", "os.", "print(", "require", "debug.", "--"):
            self.assertNotIn(tok, self.code_only,
                             f"token {tok!r} escaped its string literal -> Lua injection")

    def test_raw_payload_never_in_code(self):
        self.assertNotIn(PWN, self.code_only)

    def test_payloads_round_trip_inside_literals(self):
        # Every injected value must survive as an intact Lua string literal.
        for raw in (PWN, 'line1\nline2\rline3\tend\\"quoted\\',
                    "echo 你好 🎉", "\x00\x01\x1f\x7f control chars"):
            self.assertIn(lua_str(raw), self.lua,
                          f"escaped form of {raw!r} missing from generated Lua")
            # decode check: literal parses back to the original value
            v, _ = _parse_lua_string(lua_str(raw), 0)
            self.assertEqual(v, raw)

    def test_forward_injection_binding_skipped(self):
        # parse_forward's regex rejects the payload; the binding must not emit ops.
        forward_ops = [o for o in self.ops if "send_shortcut" in o]
        self.assertEqual(forward_ops, [])

    def test_lua_str_escape_table(self):
        cases = {
            '"': '\\"',
            "\\": "\\\\",
            "\n": "\\n",
            "\r": "\\r",
            "\t": "\\t",
            "\x00": "\\000",
            "\x1b": "\\027",
            "\x7f": "\\127",
        }
        for raw, esc in cases.items():
            lit = lua_str(raw)
            self.assertEqual(lit, f'"{esc}"')
            v, end = _parse_lua_string(lit, 0)
            self.assertEqual(v, raw)
            self.assertEqual(end, len(lit))


class TestValidatorHardening(unittest.TestCase):
    def _validate(self, data):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            p = Path(f.name)
        try:
            return _validate_profile_file(p, {"snap_left": {}, "close_window": {}})
        finally:
            p.unlink(missing_ok=True)

    def test_rejects_malformed_types_without_crashing(self):
        bad = [
            {"id": "x", "bindings": ["notadict"]},
            {"id": "x", "bindings": [{"action": "snap_left", "mod": 123, "key": "x"}]},
            {"id": "x", "bindings": [{"action": "snap_left", "mod": "SUPER", "key": None}]},
            {"id": "x", "bindings": [{"action": {}, "mod": "SUPER", "key": "x"}]},
            {"id": "x", "bindings": {"a": 1}},
            {"id": "x", "name": {"evil": 1}, "bindings": []},
            {"id": "x", "description": ["not", "a", "string"], "bindings": []},
        ]
        for data in bad:
            with self.subTest(data=str(data)[:60]):
                self.assertFalse(self._validate(data))  # must not raise

    def test_accepts_repo_builtin_profiles(self):
        catalog = {"snap_left": {}}
        for p in sorted((PROJECT_ROOT / "profiles").glob("*.json")):
            with self.subTest(profile=p.name):
                # full catalog so action check passes; only type-safety is asserted here
                import engine.engine as em
                e = OmniPalEngine(root_dir=PROJECT_ROOT,
                                  user_profiles_dir=Path(tempfile.mkdtemp()))
                self.assertTrue(_validate_profile_file(p, e.actions_catalog))


class TestRegexBacktrackingGuard(unittest.TestCase):
    """A4 返工：分组后跟量词一律拒绝；加载时过滤手改/遗留规则文件；doctor 上报。"""

    # 用户验收的 5 个绕过用例：旧启发式放行、实际会卡死（29 字符类名 >3 秒）
    BYPASSES = [
        "(a|a)*b",
        "((a+))+$",
        "(a+){2,}$",
        "(a{1,30}){1,30}$",
        "(.*a){12}$",
    ]

    def test_rejects_quantified_groups(self):
        from engine.engine import validate_app_rule_pattern
        for pat in self.BYPASSES + ["(a+)+$", "(ab)+", "(a|b){2}"]:
            with self.subTest(pattern=pat):
                with self.assertRaises(ValueError):
                    validate_app_rule_pattern(pat)

    def test_allows_optional_group_and_legit_patterns(self):
        from engine.engine import validate_app_rule_pattern
        for pat in ["(https?://)?", r"firefox(\.exe)?", "^jetbrains-",
                    "a*b*", "[Cc]ode|kitty", "^a+$", "(a)?b"]:
            with self.subTest(pattern=pat):
                validate_app_rule_pattern(pat)  # must not raise

    def test_load_skips_hand_edited_bad_regex(self):
        from engine.omnipal.paths import app_rules_file_path
        e = OmniPalEngine(root_dir=PROJECT_ROOT, user_profiles_dir=Path(tempfile.mkdtemp()))
        path = app_rules_file_path()
        path.write_text(json.dumps({"rules": [
            {"class": "(a|a)*b", "match": "regex", "mode": "windows"},
            {"class": "firefox", "match": "exact", "mode": "windows"},
        ]}), encoding="utf-8")
        try:
            rules = e.load_app_rules()["rules"]
            self.assertEqual([r["class"] for r in rules], ["firefox"])
            bad = e.invalid_app_rules()
            self.assertEqual(len(bad), 1)
            self.assertEqual(bad[0]["class"], "(a|a)*b")
        finally:
            path.unlink(missing_ok=True)

    def test_doctor_reports_skipped_rule(self):
        from engine.omnipal.paths import app_rules_file_path
        e = OmniPalEngine(root_dir=PROJECT_ROOT, user_profiles_dir=Path(tempfile.mkdtemp()))
        path = app_rules_file_path()
        path.write_text(json.dumps({"rules": [
            {"class": "(.*a){12}$", "match": "regex", "mode": "mac"},
        ]}), encoding="utf-8")
        try:
            diag = e.doctor()
            hits = [i for i in diag["issues"] if "(.*a){12}$" in i]
            self.assertTrue(hits, f"doctor should report the skipped rule: {diag['issues']}")
        finally:
            path.unlink(missing_ok=True)


class TestImportCliHardening(unittest.TestCase):
    def setUp(self):
        # Other test modules' tearDownModule may pop these; re-ensure isolation.
        self._tmpdirs = []
        self._saved_env = {}
        for var, prefix in (("OMNIPAL_CONFIG_DIR", "sec-cfg-"),
                            ("OMNIPAL_RUN_DIR", "sec-run-")):
            if not os.environ.get(var) or not os.path.isdir(os.environ[var]):
                self._saved_env[var] = os.environ.get(var)
                td = tempfile.TemporaryDirectory(prefix=prefix)
                self._tmpdirs.append(td)
                os.environ[var] = td.name
        os.environ["OMNIPAL_DRY_RUN"] = "1"

    def tearDown(self):
        for td in self._tmpdirs:
            td.cleanup()
        # Don't leave the env pointing at the just-deleted temp dirs (later
        # classes, e.g. TestRegexBacktrackingGuard, write app_rules.json there).
        for var, val in self._saved_env.items():
            if val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = val

    def _run(self, *argv, stdin_data=None):
        return subprocess.run([sys.executable, CLI, *argv], capture_output=True,
                              text=True, input=stdin_data, timeout=30)

    def _tmp(self, content, suffix=".json"):
        f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
        f.write(content); f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return f.name

    def _run_bytes(self, *argv, stdin_bytes=None):
        return subprocess.run([sys.executable, CLI, *argv], capture_output=True,
                              input=stdin_bytes, timeout=30)

    def test_import_rejects_oversize_file(self):
        big = self._tmp("x" * (1024 * 1024 + 100))
        r = self._run("import", big)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("上限", r.stderr)

    def test_import_rejects_multibyte_stdin_over_byte_limit(self):
        # 400k CJK chars are ~1.2MB on the wire; the cap must count bytes.
        r = self._run("import", "-", stdin_data="汉" * 400_000)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("上限", r.stderr)

    def test_import_rejects_just_under_byte_limit_stdin(self):
        # 349_525 CJK chars = 1_048_575 bytes (1MiB - 1): must be accepted by
        # the size gate (it will then fail JSON parsing, not the size check).
        r = self._run("import", "-", stdin_data="汉" * 349_525)
        self.assertNotIn("上限", r.stderr)

    def test_import_rejects_invalid_utf8_stdin(self):
        r = self._run_bytes("import", "-", stdin_bytes=b'{"id": "x", \xff\xfe')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("UTF-8", r.stderr.decode("utf-8", "replace"))

    def test_import_rejects_malformed_types_cleanly(self):
        # mod as int used to crash the validator with a traceback
        p = self._tmp(json.dumps({"id": "badtypes", "bindings":
                                  [{"action": "snap_left", "mod": 123, "key": "x"}]}))
        r = self._run("import", p)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("校验未通过", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_rules_import_validates_entries(self):
        rules = {
            "rules": [
                {"class": "firefox", "match": "exact", "mode": "windows"},
                {"class": "evil", "match": "bogus-kind", "mode": "windows"},
                {"class": "(a+)+$", "match": "regex", "mode": "windows"},
                {"class": "(unclosed", "match": "regex", "mode": "windows"},
                {"class": "a" * 250, "match": "regex", "mode": "windows"},
                {"class": "x" * 300, "match": "exact", "mode": "windows"},
                {"class": {"not": "a string"}, "match": "exact", "mode": "windows"},
                {"class": "code", "match": "exact", "mode": {"not": "a string"}},
                "notadict",
            ]
        }
        p = self._tmp(json.dumps(rules))
        r = self._run("rules", "import", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("已导入 1 条", r.stdout)  # 只有 firefox 合法，其余逐条跳过
        saved = json.loads(Path(os.environ["OMNIPAL_CONFIG_DIR"], "app_rules.json")
                           .read_text(encoding="utf-8"))
        classes = [x["class"] for x in saved["rules"]]
        self.assertIn("firefox", classes)
        self.assertNotIn("(a+)+$", classes)  # 嵌套量词：可能卡死守护进程，拒绝
        self.assertNotIn("a" * 250, classes)  # 超过 200 字符上限的正则，拒绝
        self.assertNotIn("(unclosed", classes)
        self.assertNotIn("bogus-kind", [x["match"] for x in saved["rules"]])
        self.assertTrue(all(len(c) <= 256 for c in classes))
        self.assertTrue(all(isinstance(x["class"], str) for x in saved["rules"]))


if __name__ == "__main__":
    unittest.main()
