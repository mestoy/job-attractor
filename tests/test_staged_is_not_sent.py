#!/usr/bin/env python3
"""A STAGED-only entry in outreach_log.md must never be reported as SENT (kit issue #147).

check_dup already rates a staged draft as a WEAK hit, verdict yellow: its own word for "not a
recorded send". The defect was one step later. A weak hit was stored with the file's one fixed
status label, "SENT (or drop logged)", so the PRIOR CONTACT line and the command line dump told a
person they had already written to someone they never wrote to.

Each test asserts BEHAVIOR on three entries in one log: one that went out (must still say SENT),
one staged only (must never say SENT), and one company in no file (must be clean). The first and
the third are the controls, so a pass means something.

Run:  python3 -m unittest tests.test_staged_is_not_sent
"""
import importlib
import io
import os
import _roots
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

check_dup = importlib.import_module("check_dup")
boss_registry = importlib.import_module("boss_registry")

LOG = """# Outreach log

## 2026-09-01 — Priya Raman, VP Product @ Sentco Systems — SENT
**Status:** SENT 2026-09-01 09:14, from their own mail.
Subject: Your payouts rollout

## 2026-09-02 — Jordan Vale, Head of Product @ Stagedco Labs — STAGED (draft)
**Status:** STAGED (draft created, awaiting your send). Nothing has gone out.
Subject: Your claims intake rebuild

## 2026-09-03 — Devon Cole, Head of Ops @ ACME Robotics — STAGED (draft)
**Status:** STAGED (draft created, awaiting your send). Nothing has gone out.
Subject: Your fulfillment pipeline
"""

SENT_CO, STAGED_CO, CLEAN_CO = "Sentco Systems", "Stagedco Labs", "Nowhere Industries"
# A fictional company whose own name is a caps-heavy acronym, sitting to the LEFT of the real
# status word in the header ("... @ ACME Robotics — STAGED (draft)") -- the exact shape kit #147
# follow-up (29, 2026-09-22) found a leftmost-caps-scan misreading as status "ACME".
ACRONYM_CO = "ACME Robotics"


class TestStagedIsNotSent(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with open(os.path.join(self.tmp.name, "outreach_log.md"), "w", encoding="utf-8") as fh:
            fh.write(LOG)
        self._repo = check_dup.REPO
        check_dup.REPO = self.tmp.name
        _roots.patch_roots(self, self.tmp.name)
        self.addCleanup(lambda: setattr(check_dup, "REPO", self._repo))

    def _lines(self, company):
        return boss_registry._prior_contact_lines(check_dup.prior_contact(company))

    def test_control_a_sent_entry_still_says_sent(self):
        pc = check_dup.prior_contact(SENT_CO)
        self.assertEqual(pc["verdict"], "red")
        lines = self._lines(SENT_CO)
        self.assertTrue(lines, "the sent company must warn")
        self.assertTrue(all("SENT" in ln for ln in lines), lines)

    def test_control_a_company_in_no_file_is_clean(self):
        pc = check_dup.prior_contact(CLEAN_CO)
        self.assertEqual(pc["verdict"], "clean")
        self.assertEqual(self._lines(CLEAN_CO), [])

    def test_a_staged_only_entry_is_found_and_is_yellow(self):
        # The check must have something to look at: the staged entry IS found, as a weak hit.
        pc = check_dup.prior_contact(STAGED_CO)
        self.assertEqual(pc["verdict"], "yellow")
        self.assertEqual(len(pc["strong"]), 0)
        self.assertGreaterEqual(len(pc["weak"]), 1)

    def test_a_staged_only_entry_never_says_sent_in_the_prior_contact_line(self):
        lines = self._lines(STAGED_CO)
        self.assertTrue(lines, "the staged company must still be reported, as a caution")
        for ln in lines:
            self.assertNotIn("SENT", ln, "a staged draft was reported as SENT: %r" % ln)
            self.assertIn("NOT a recorded send", ln)

    def test_a_staged_only_entry_names_its_own_status_word(self):
        # The generic "NOT a recorded send" caution is not the full ask: the issue wants the
        # entry's OWN status word surfaced (STAGED here), not just a promise to "open the line
        # to see which". The matched line itself already carries the word ("... STAGED (draft)").
        lines = self._lines(STAGED_CO)
        self.assertTrue(lines)
        self.assertTrue(any("STAGED" in ln for ln in lines),
                         "the staged entry's own status word never reached the warning: %r" % lines)

    def test_a_caps_acronym_company_name_does_not_shadow_the_real_status_word(self):
        # kit #147 follow-up (29): the company's own name sits to the LEFT of the status word in
        # the header, so a leftmost ALL-CAPS scan reads the company's acronym as the status.
        lines = self._lines(ACRONYM_CO)
        self.assertTrue(lines, "the staged entry must still be reported")
        self.assertTrue(any("STAGED" in ln for ln in lines),
                         "the real status word never reached the warning: %r" % lines)
        self.assertFalse(any("ACME" in ln for ln in lines),
                         "the company's own acronym was reported as if it were the status: %r" % lines)

    def test_no_weak_hit_from_any_store_carries_that_stores_sent_label(self):
        pc = check_dup.prior_contact(STAGED_CO)
        for hit in pc["weak"]:
            if hit["store"] == check_dup.SENDLOG:
                continue
            self.assertNotEqual(hit["status"], check_dup.STORES.get(hit["store"]), hit)

    def test_the_command_line_dump_never_labels_a_staged_entry_sent(self):
        out = io.StringIO()
        argv = sys.argv
        sys.argv = ["check_dup.py", STAGED_CO]
        try:
            with redirect_stdout(out):
                try:
                    check_dup.main()
                except SystemExit:
                    pass
        finally:
            sys.argv = argv
        text = out.getvalue()
        self.assertIn("outreach_log.md", text, "the staged entry must show in the dump")
        for ln in text.splitlines():
            if "outreach_log.md" in ln and "[" in ln:
                self.assertNotIn("SENT", ln, "the dump labeled a staged entry SENT: %r" % ln)


if __name__ == "__main__":
    unittest.main()
