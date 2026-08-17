#!/usr/bin/env python3
"""BUG-218 Layer 1: the review-hold pauses only the publish, and CANNOT wedge backups forever.

Pins: `on` sets a hold, `check` reports it active (exit 0), `off` clears it, a hold older than the TTL
is auto-voided (exit 1, file deleted), and a malformed hold file fails safe (voided, not honored)."""
import datetime
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)


class BackupHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents", "state"), exist_ok=True)
        os.environ["CLAUDE_PROJECT_DIR"] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop("CLAUDE_PROJECT_DIR", None))
        import backup_hold
        importlib.reload(backup_hold)
        self.bh = backup_hold

    def _cli(self, *args):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "backup_hold.py"), *args],
                           capture_output=True, text=True,
                           env={**os.environ, "CLAUDE_PROJECT_DIR": self.tmp.name})
        return r.returncode, (r.stdout + r.stderr)

    def test_on_then_check_is_active(self):
        self._cli("on", "--reason", "landing a batch")
        rc, _ = self._cli("check")
        self.assertEqual(rc, 0, "check must exit 0 (hold active) after on")
        ok, reason = self.bh.active()
        self.assertTrue(ok)
        self.assertIn("batch", reason)

    def test_off_clears_the_hold(self):
        self._cli("on", "--reason", "x")
        self._cli("off")
        rc, _ = self._cli("check")
        self.assertEqual(rc, 1, "check must exit 1 (no hold) after off")
        self.assertFalse(os.path.exists(self.bh.HOLD))

    def test_no_hold_checks_inactive(self):
        rc, _ = self._cli("check")
        self.assertEqual(rc, 1, "with no hold set, check must exit 1 so backup publishes")

    def test_a_hold_past_the_ttl_is_auto_voided(self):
        old = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(seconds=self.bh.HOLD_TTL_SECONDS + 60)).isoformat()
        with open(self.bh.HOLD, "w", encoding="utf-8") as fh:
            json.dump({"reason": "forgotten", "ts": old, "pid": 1}, fh)
        ok, _ = self.bh.active()
        self.assertFalse(ok, "a hold older than the TTL must not be honored")
        self.assertFalse(os.path.exists(self.bh.HOLD), "a stale hold must be deleted so it can't wedge")

    def test_a_fresh_hold_within_ttl_is_honored(self):
        recent = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(seconds=60)).isoformat()
        with open(self.bh.HOLD, "w", encoding="utf-8") as fh:
            json.dump({"reason": "recent", "ts": recent, "pid": 1}, fh)
        ok, reason = self.bh.active()
        self.assertTrue(ok)
        self.assertEqual(reason, "recent")

    def test_malformed_hold_file_fails_safe(self):
        with open(self.bh.HOLD, "w", encoding="utf-8") as fh:
            fh.write("not json")
        ok, _ = self.bh.active()
        self.assertFalse(ok, "an unreadable hold must be voided, not honored")
        self.assertFalse(os.path.exists(self.bh.HOLD))


if __name__ == "__main__":
    unittest.main()
