"""kit#162: --dry-run must short-circuit BEFORE any write, on every action
(--confirm-sent, --stage, --mark-replied), not only the new-row path. Also:
--confirm-sent's sent_ts is confirmation time, not the real send time; an
optional --sent-at should let a caller supply the real one.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "log_linkedin_send.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import log_linkedin_send as lls  # noqa: E402


class TestDryRunGuardsEveryWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "send-log.jsonl")
        row = {
            "ts": "2026-09-25T10:00:00-04:00", "date": "2026-09-25", "rung": "cold-boss",
            "to": "https://linkedin.com/in/plain-person", "to_name": "Fake Person",
            "company": "Fakemonth Corp", "targets": [], "subject": "(LinkedIn)",
            "segment": "test", "kind": "initial", "followup_due": None,
            "status": "staged", "replied": False, "sent_note": "fixture",
        }
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def _read(self):
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]

    def test_dry_run_confirm_sent_writes_nothing(self):
        before = self._read()
        row, state = lls.confirm_sent(
            "https://linkedin.com/in/plain-person", self.path, dry_run=True)
        self.assertIsNotNone(row)
        after = self._read()
        self.assertEqual(before, after)
        self.assertEqual(after[0]["status"], "staged")

    def test_dry_run_stage_writes_nothing(self):
        before = self._read()
        row, err = lls.set_stage(
            "https://linkedin.com/in/plain-person", "opened", self.path, dry_run=True)
        after = self._read()
        self.assertEqual(before, after)

    def test_dry_run_mark_replied_writes_nothing(self):
        before = self._read()
        row = lls.mark_replied(
            "https://linkedin.com/in/plain-person", self.path, dry_run=True)
        after = self._read()
        self.assertEqual(before, after)

    def test_confirm_sent_without_sent_at_uses_now(self):
        row, state = lls.confirm_sent("https://linkedin.com/in/plain-person", self.path)
        self.assertIsNotNone(row.get("sent_ts"))

    def test_confirm_sent_with_sent_at_uses_the_given_time(self):
        row, state = lls.confirm_sent(
            "https://linkedin.com/in/plain-person", self.path,
            sent_at="2026-09-25T10:15:38-04:00")
        self.assertEqual(row["sent_ts"], "2026-09-25T10:15:38-04:00")


if __name__ == "__main__":
    unittest.main()
