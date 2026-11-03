#!/usr/bin/env python3
"""BUG-737 (c): partner-starter closeness matches a picker hold on the STATE (^PAUSED-by-), as main does (BUG-731), not on one spelling.

A row held as `PAUSED-by-sam` (or any `PAUSED-by-<anyone>`) is a picker hold: pausing it again with the same note is a no-op, and lift()
removes it when its note carries the picker mark. The old exact compare to "PAUSED-by-owner" treated the other spellings as not held.
Names are invented.   cd partner-starter/tests && python3 -m unittest test_bug737_paused_rule -v
"""
import datetime
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import closeness  # noqa: E402

TODAY = datetime.date(2026, 10, 25)


class PausedIsMatchedOnTheState(unittest.TestCase):
    def _held(self, status):
        row = closeness.pause({}, "held for a fixture reason", today=TODAY)
        row["outreach_status"] = status
        return row

    def test_pause_writes_the_neutral_spelling(self):
        self.assertEqual(closeness.pause({}, "r", today=TODAY)["outreach_status"], "PAUSED-by-owner")

    def test_re_pausing_any_spelling_with_the_same_note_is_a_no_op(self):
        for status in ("PAUSED-by-owner", "PAUSED-by-sam", "paused-by-someone-else", "PAUSED-by-Pat"):
            with self.subTest(status=status):
                row = self._held(status)
                again = closeness.pause(row, "held for a fixture reason", today=TODAY)
                self.assertEqual(again["outreach_status"], status, "an identical hold must not rewrite the status")

    def test_lift_removes_a_picker_hold_of_any_spelling(self):
        for status in ("PAUSED-by-owner", "PAUSED-by-sam", "paused-by-someone-else"):
            with self.subTest(status=status):
                lifted = closeness.lift(self._held(status), "fixture lift", today=TODAY)
                self.assertNotIn("outreach_status", lifted)
                self.assertIn("lift_note", lifted)

    def test_lift_leaves_a_hand_written_hold_alone(self):
        row = {"outreach_status": "PAUSED-by-sam", "paused_note": "held by hand, no picker mark"}
        self.assertEqual(closeness.lift(row, "fixture lift", today=TODAY), row)

    def test_a_status_that_only_contains_the_word_is_not_a_hold(self):
        row = self._held("not PAUSED-by-owner")
        self.assertEqual(closeness.lift(row, "fixture lift", today=TODAY)["outreach_status"], "not PAUSED-by-owner")


if __name__ == "__main__":
    unittest.main()
