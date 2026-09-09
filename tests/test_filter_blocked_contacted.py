#!/usr/bin/env python3
"""Red-green tests for filter_blocked.py's CONTACTED line — dedup at card build, step 3 (kit,
09-08 Outmarket AI / Gradient AI block; documents/state/dedup-card-build-bug-draft-02-2026-09-09.md).

A card built for a company with a prior contact must never reach a picker without that fact
visible. Exit code stays scoped to the blocked-list check alone — CONTACTED never changes it.

Run:  python3 -m unittest tests.test_filter_blocked_contacted
"""
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

filter_blocked = importlib.import_module("filter_blocked")
check_dup = importlib.import_module("check_dup")


class TestContactedLine(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents"), exist_ok=True)
        with open(os.path.join(self.tmp.name, "documents", "send-log.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps({"date": "2026-08-17", "company": "Acme Rockets",
                                  "to": "Jordan Vance", "rung": "cold-boss",
                                  "status": "sent"}) + "\n")
        self._real_repo = check_dup.REPO
        check_dup.REPO = self.tmp.name
        self.addCleanup(lambda: setattr(check_dup, "REPO", self._real_repo))

    def _run(self, *names):
        old_argv = sys.argv
        sys.argv = ["filter_blocked.py", *names]
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = filter_blocked.main()
        finally:
            sys.argv = old_argv
        return rc, out.getvalue()

    def test_contacted_line_present_on_prior_delivered_touch(self):
        rc, out = self._run("Acme Rockets")
        self.assertIn("CONTACTED:", out)
        self.assertIn("2026-08-17", out)
        self.assertIn("Jordan Vance", out)
        self.assertEqual(rc, 0, "CONTACTED must not change the blocked-list exit code")

    def test_contacted_line_absent_when_clean(self):
        rc, out = self._run("Drift Robotics")
        self.assertNotIn("CONTACTED:", out)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
