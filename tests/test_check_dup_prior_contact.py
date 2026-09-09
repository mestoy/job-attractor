#!/usr/bin/env python3
"""Red-green tests for check_dup.prior_contact() — dedup at card build (kit, 09-08 Outmarket AI /
Gradient AI block; documents/state/dedup-card-build-bug-draft-02-2026-09-09.md).

Covers fc's step 1: `prior_contact(company, person="") -> dict` returning
{"strong": [...], "weak": [...], "verdict": "red"|"yellow"|"clean"}, extracted from the
`--send-gate` path of main() without changing main()'s own exit codes or printed output.

Run:  python3 -m unittest tests.test_check_dup_prior_contact
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

check_dup = importlib.import_module("check_dup")


class TestPriorContact(unittest.TestCase):
    """A temp send-log with a delivered, a bounced, and a staged row — red, yellow, clean."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents"), exist_ok=True)
        rows = [
            {"date": "2026-08-01", "company": "Acme Rockets", "to": "Jordan Vance",
             "rung": "cold-boss", "status": "sent"},
            {"date": "2026-08-05", "company": "Bravo Systems", "to": "Casey Stone",
             "rung": "cold-boss", "status": "bounced"},
            {"date": "2026-08-09", "company": "Cascade Metrics", "to": "Dana Ford",
             "rung": "cold-boss", "status": "staged"},
        ]
        with open(os.path.join(self.tmp.name, "documents", "send-log.jsonl"), "w",
                  encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        self._real_repo = check_dup.REPO
        check_dup.REPO = self.tmp.name
        self.addCleanup(lambda: setattr(check_dup, "REPO", self._real_repo))

    # ── the shape ──────────────────────────────────────────────────────────────────────────

    def test_red_on_a_delivered_send(self):
        pc = check_dup.prior_contact("Acme Rockets", "Jordan Vance")
        self.assertEqual(pc["verdict"], "red")
        self.assertTrue(pc["strong"])
        self.assertEqual(pc["weak"], [])
        self.assertTrue(any(h["store"] == check_dup.SENDLOG for h in pc["strong"]))

    def test_yellow_on_a_bounced_send(self):
        """A bounce did not deliver — SENDLOG_DELIVERED excludes it — so it is a weak (yellow)
        signal, never a red block. A retry is the correct next action for a bounce."""
        pc = check_dup.prior_contact("Bravo Systems")
        self.assertEqual(pc["verdict"], "yellow")
        self.assertEqual(pc["strong"], [])
        self.assertTrue(pc["weak"])

    def test_yellow_on_a_staged_send(self):
        """STAGED means a draft exists, not that it was sent — still yellow, not red."""
        pc = check_dup.prior_contact("Cascade Metrics")
        self.assertEqual(pc["verdict"], "yellow")
        self.assertEqual(pc["strong"], [])
        self.assertTrue(pc["weak"])

    def test_clean_when_no_prior_record(self):
        pc = check_dup.prior_contact("Drift Robotics", "Riley Park")
        self.assertEqual(pc["verdict"], "clean")
        self.assertEqual(pc["strong"], [])
        self.assertEqual(pc["weak"], [])

    def test_person_only_narrows_the_needle_set_not_the_verdict_shape(self):
        """Calling with no person still returns the full dict shape (person defaults to "")."""
        pc = check_dup.prior_contact("Acme Rockets")
        self.assertIn("strong", pc)
        self.assertIn("weak", pc)
        self.assertIn("verdict", pc)
        self.assertEqual(pc["verdict"], "red")


class TestMainSendGateUnchanged(unittest.TestCase):
    """main()'s own --send-gate exit codes and printed VERDICT lines must be byte-identical to
    before prior_contact() was factored out of that path."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents"), exist_ok=True)
        rows = [
            {"date": "2026-08-01", "company": "Acme Rockets", "to": "Jordan Vance",
             "rung": "cold-boss", "status": "sent"},
            {"date": "2026-08-05", "company": "Bravo Systems", "to": "Casey Stone",
             "rung": "cold-boss", "status": "bounced"},
        ]
        with open(os.path.join(self.tmp.name, "documents", "send-log.jsonl"), "w",
                  encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        self.env = dict(os.environ)
        self.env["CLAUDE_PROJECT_DIR"] = self.tmp.name

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "check_dup.py"), "--send-gate", *args],
            cwd=self.tmp.name, env=self.env, capture_output=True, text=True)

    def test_delivered_send_exits_1_with_red_verdict(self):
        p = self._run("Acme Rockets", "Jordan Vance")
        self.assertEqual(p.returncode, 1)
        self.assertIn("VERDICT: 🔴 ALREADY-SEEN", p.stdout)

    def test_bounced_send_exits_3_with_possible_verdict(self):
        p = self._run("Bravo Systems")
        self.assertEqual(p.returncode, 3)
        self.assertIn("VERDICT: 🟡 POSSIBLE", p.stdout)

    def test_clean_company_exits_0_with_new_verdict(self):
        p = self._run("Drift Robotics")
        self.assertEqual(p.returncode, 0)
        self.assertIn("VERDICT: 🟢 NEW", p.stdout)


if __name__ == "__main__":
    unittest.main()
