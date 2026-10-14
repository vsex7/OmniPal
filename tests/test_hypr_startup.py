#!/usr/bin/env python3
"""Tests for Hyprland signature derivation and daemon startup restore of the persisted profile."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_omni as base  # noqa: E402  (sets up isolated env + fake hyprctl)
import engine.engine as engine_module  # noqa: E402
from engine.engine import OmniPalEngine  # noqa: E402


class _EnvCase(base.BaseOmniTestCase):
    def setUp(self):
        super().setUp()
        self._saved = {k: os.environ.get(k) for k in ("XDG_RUNTIME_DIR", "HYPRLAND_INSTANCE_SIGNATURE")}
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_RUNTIME_DIR"] = self.tmp.name
        os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()
        super().tearDown()

    def make_instance(self, sig, sock=".socket.sock", mtime=None):
        d = Path(self.tmp.name) / "hypr" / sig
        d.mkdir(parents=True, exist_ok=True)
        p = d / sock
        p.touch()
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return d


class TestSignatureDerivation(_EnvCase):
    def test_no_hypr_dir(self):
        self.assertIsNone(engine_module.derive_hyprland_instance_signature())
        self.assertIsNone(engine_module._ensure_hyprland_instance())
        self.assertNotIn("HYPRLAND_INSTANCE_SIGNATURE", os.environ)

    def test_derives_newest_and_sets_environ(self):
        now = time.time()
        self.make_instance("old_sig", ".socket2.sock", mtime=now - 100)
        self.make_instance("new_sig", ".socket.sock", mtime=now)
        (Path(self.tmp.name) / "hypr" / "empty_dir").mkdir()
        self.assertEqual(engine_module.derive_hyprland_instance_signature(), "new_sig")
        self.assertEqual(engine_module._ensure_hyprland_instance(), "new_sig")
        self.assertEqual(os.environ["HYPRLAND_INSTANCE_SIGNATURE"], "new_sig")

    def test_keeps_valid_signature_and_replaces_stale(self):
        self.make_instance("live", ".socket2.sock")
        self.make_instance("other", ".socket.sock", mtime=time.time() + 50)
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "live"
        self.assertEqual(engine_module._ensure_hyprland_instance(), "live")
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "gone"
        self.assertEqual(engine_module._ensure_hyprland_instance(), "other")

    def test_subprocess_inherits(self):
        self.make_instance("abc123")
        engine_module._ensure_hyprland_instance()
        import subprocess
        out = subprocess.check_output([sys.executable, "-c", "import os;print(os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'))"], text=True)
        self.assertEqual(out.strip(), "abc123")

    def test_wait_for_hyprland_bounded(self):
        t0 = time.monotonic()
        self.assertFalse(engine_module.wait_for_hyprland(timeout=0.3, interval=0.05))
        self.assertLess(time.monotonic() - t0, 2.0)
        self.make_instance("sig")
        self.assertTrue(engine_module.wait_for_hyprland(timeout=0.3, interval=0.05))


class TestStartupRestore(_EnvCase):
    def setUp(self):
        super().setUp()
        self.engine = OmniPalEngine(PROJECT_ROOT)
        self.engine.set_persistence(True, profile="windows")
        if engine_module.STATE_FILE.exists():
            engine_module.STATE_FILE.unlink()
        self.make_instance("sig")

    def test_applies_persisted_profile(self):
        self.assertTrue(engine_module.restore_persisted_profile(self.engine, wait_timeout=1, sleep=lambda s: None))
        self.assertEqual(self.engine.get_state()["mode"], "windows")

    def test_retries_with_backoff(self):
        real = self.engine.switch_mode
        calls, sleeps = [], []
        def flaky(mode, *a, **k):
            calls.append(mode)
            return False if len(calls) < 3 else real(mode, *a, **k)
        with mock.patch.object(self.engine, "switch_mode", side_effect=flaky):
            ok = engine_module.restore_persisted_profile(self.engine, attempts=4, base_delay=1.0,
                                                         wait_timeout=1, sleep=sleeps.append)
        self.assertTrue(ok)
        self.assertEqual(calls, ["windows"] * 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_gives_up_without_socket(self):
        import shutil
        shutil.rmtree(Path(self.tmp.name) / "hypr")
        with mock.patch.object(self.engine, "switch_mode") as sw:
            self.assertFalse(engine_module.restore_persisted_profile(self.engine, wait_timeout=0.2))
            sw.assert_not_called()

    def test_reapply_mode_uses_persisted_when_no_state(self):
        self.assertEqual(engine_module.resolve_reapply_mode(self.engine), "windows")
        self.engine.switch_mode("kde")
        self.assertEqual(engine_module.resolve_reapply_mode(self.engine), "kde")


if __name__ == "__main__":
    unittest.main()
