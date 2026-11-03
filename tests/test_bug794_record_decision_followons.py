#!/usr/bin/env python3
"""BUG-794: three follow-ons from the BUG-790 review, one test, all copies of record_decision.py.

N2  A "#N" pick on a skip label is resolved to the label BEFORE it is classified, in every copy, so the
    ledger says SKIP and not OTHER (the hold was already written through the label).
N3  A typed answer with options on the question and none picked writes a hold only when the answer names
    the contact in his own words: one line, short, one contact. A pasted log, or "hold it for now", records
    the ruling, writes nothing and prints one seat line. (LaCivita, 2026-09-21: a pasted cross-session
    message held the contact option 1 named.) A question with NO options keeps the BUG-233 typed rule.
N1  The hold note says HELD for a "Hold ..." option and SKIPPED for a skip, pass or drop option.

Every name is invented. Same harness as the BUG-790 test: the real hook in a child process per copy."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_bug790_option_pick_is_the_ruling import (  # noqa: E402
    ANDY, NEXT_STEP, Base, opts)

SEAT_LINE = "no hold was written"
PASTE = ('<cross-session-message from="uds:/tmp/cc-socks/1.sock" from-name="seat-x" from-mode="prompting">\n'
         "x to y: hold the publish, do not send until the walk passes.\n"
         "Nothing is published and no browser is running.\n"
         "</cross-session-message>")


class N2HashNOnASkipLabelIsSkip(Base):
    def test_hash_two_on_a_skip_label(self):
        def check(r):
            self.assertEqual(r.ruling(), "SKIP", r.proc.stderr)
            self.assertTrue(r.row().get("outreach_status", "").startswith("PAUSED-by"))
        self.run_all("#2", opts("Build it for Alpha Co", "Skip Zorblat Fakeperson"), check)

    def test_hash_one_on_a_non_skip_label_is_not_a_skip(self):
        def check(r):
            self.assertEqual(r.ruling(), "OTHER")
            self.assertEqual(r.before, r.after)
        self.run_all("#1", ANDY, check)


class N3ATypedAnswerNeedsHisOwnWordsToHold(Base):
    def test_a_pasted_log_records_the_ruling_and_writes_no_hold(self):
        def check(r):
            self.assertEqual(r.before, r.after, "a pasted log wrote a hold")
            self.assertIn(SEAT_LINE, r.proc.stderr)
            self.assertTrue(r.ruling())
        self.run_all(PASTE, ANDY, check)

    def test_a_pasted_log_that_names_the_contact_still_writes_no_hold(self):
        def check(r):
            self.assertEqual(r.before, r.after, "a pasted log naming the contact wrote a hold")
        self.run_all(PASTE + "\nRe: Zorblat Fakeperson", ANDY, check)

    def test_hold_it_for_now_names_nobody_so_no_hold(self):
        def check(r):
            self.assertEqual(r.before, r.after)
            self.assertIn(SEAT_LINE, r.proc.stderr)
        self.run_all("Hold it for now", ANDY, check)

    def test_a_short_typed_skip_that_names_the_contact_holds(self):
        def check(r):
            self.assertTrue(r.row().get("outreach_status", "").startswith("PAUSED-by"))
            self.assertNotIn(SEAT_LINE, r.proc.stderr)
        self.run_all("skip Zorblat Fakeperson for now", ANDY, check)

    def test_no_options_keeps_the_bug233_typed_rule(self):
        def check(r):
            self.assertTrue(r.row().get("outreach_status", "").startswith("PAUSED-by"))
        self.run_all("skip it", [], check, question="Skip Zorblat Fakeperson for now?")


class N1TheNoteVerbFollowsTheLabel(Base):
    def note(self, label):
        out = {}
        def check(r):
            out["note"] = r.row().get("paused_note", "")
        self.run_all(label, opts(label, "Other"), check)
        return out["note"]

    def test_hold_label_says_held(self):
        self.assertIn(" HELD ", self.note("Hold Zorblat Fakeperson, recompute"))

    def test_skip_pass_drop_labels_say_skipped(self):
        for lab in ("Skip Zorblat Fakeperson", "Pass on Zorblat Fakeperson", "Drop Zorblat Fakeperson"):
            self.assertIn(" SKIPPED ", self.note(lab), lab)


if __name__ == "__main__":
    unittest.main()
