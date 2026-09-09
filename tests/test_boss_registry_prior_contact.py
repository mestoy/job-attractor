#!/usr/bin/env python3
"""Red-green tests for boss_registry.py's `add` — dedup at card build, step 2 (kit, 09-08
Outmarket AI / Gradient AI block; documents/state/dedup-card-build-bug-draft-02-2026-09-09.md).

Same person already DELIVERED a prior send: `add` refuses unless --next-target-ok is given.
A DIFFERENT person at an already-contacted company: `add` warns and records, never blocks.

Run:  python3 -m unittest tests.test_boss_registry_prior_contact
"""
import argparse
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

boss_registry = importlib.import_module("boss_registry")
check_dup = importlib.import_module("check_dup")
state = importlib.import_module("state")


def _add_args(**kw):
    base = dict(person="Jordan Vance", company="Acme Rockets", verdict="candidate",
                boss_read="likely-boss", verified="linkedin-live", role_status="current",
                why="", linkedin="", title="", source_url=[], date="", dry_run=False,
                next_target_ok=False)
    base.update(kw)
    return argparse.Namespace(**base)


class TestAddPriorContactGate(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents"), exist_ok=True)
        with open(os.path.join(self.tmp.name, "documents", "send-log.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps({"date": "2026-08-17", "company": "Acme Rockets",
                                  "to": "Jordan Vance", "rung": "cold-boss",
                                  "status": "sent"}) + "\n")

        self._real_check_dup_repo = check_dup.REPO
        check_dup.REPO = self.tmp.name
        self.addCleanup(lambda: setattr(check_dup, "REPO", self._real_check_dup_repo))

        self._real_state_dir = state.STATE_DIR
        state.STATE_DIR = os.path.join(self.tmp.name, "documents", "state")
        self.addCleanup(lambda: setattr(state, "STATE_DIR", self._real_state_dir))

    def _rows(self):
        path = state.store_path("boss")
        if not os.path.exists(path):
            return []
        return [json.loads(ln) for ln in open(path, encoding="utf-8") if ln.strip()]

    def test_same_person_delivered_is_refused(self):
        """Jordan Vance at Acme Rockets was already delivered a cold send — the exact re-add is
        the Outmarket AI shape (a fresh card built with no note of the prior touch)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = boss_registry.cmd_add(_add_args())
        self.assertNotEqual(rc, 0)
        self.assertIn("BLOCKED", err.getvalue())
        self.assertIn("PRIOR CONTACT", out.getvalue())
        self.assertEqual(self._rows(), [], "a refused add must not write a row")

    def test_same_person_delivered_but_next_target_ok_proceeds(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = boss_registry.cmd_add(_add_args(next_target_ok=True))
        self.assertEqual(rc, 0)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["prior_contact"])
        self.assertEqual(rows[0]["prior_contact"]["verdict"], "red")

    def test_different_person_same_company_warns_and_records(self):
        """A fallback boss (Craig Adams after Kim Wiswell) is a legitimate next target — the
        Gradient AI shape. It must warn, and it must still write the row."""
        out = io.StringIO()
        with redirect_stdout(out):
            rc = boss_registry.cmd_add(_add_args(person="Alex Carter"))
        self.assertEqual(rc, 0, "a different person must never be blocked")
        self.assertIn("PRIOR CONTACT", out.getvalue())
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["person"], "Alex Carter")
        self.assertIsNotNone(rows[0]["prior_contact"])

    def test_clean_company_writes_no_prior_contact_noise(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = boss_registry.cmd_add(_add_args(person="Riley Park", company="Drift Robotics"))
        self.assertEqual(rc, 0)
        self.assertNotIn("PRIOR CONTACT", out.getvalue())
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["prior_contact"])


if __name__ == "__main__":
    unittest.main()
