#!/usr/bin/env python3
"""BUG-687, step one: the matching the writers do inline is five pure functions in log_linkedin_send.py, so the spool's fold can run the SAME match the live writer runs.

Each function is named and tested here so none is dead. Rows in, a row (or a sentence) out, no I/O. Every name and address is obviously fake (reserved hosts).
Run: python3 -m unittest tests.test_sendlog_match_functions
"""
import importlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
lls = importlib.import_module("log_linkedin_send")


def row(to, date, ts, **kw):
    return dict({"to": to, "date": date, "ts": ts}, **kw)


ROWS = [row("pat@zz.example", "2026-10-01", "09:00", status="sent", company="Zz One", subject="One"),
        row("pat@zz.example", "2026-10-05", "10:00", status="staged", company="Zz Two", subject="Two"),
        row("pat@zz.example", "2026-10-06", "10:00", status="staged", company="Zz Three", subject="Three"),
        row("lee@zz.example", "2026-10-02", "09:00", status="bounced"),
        row("linkedin:zzyx-widgets-fake-0001", "2026-10-03", "09:00", status="sent", replied=True)]


class ThePureFunctions(unittest.TestCase):
    def test_match_newest_picks_the_newest_row_for_the_recipient_by_date_then_ts(self):
        self.assertIs(lls.match_newest(ROWS, "pat@zz.example"), ROWS[2])
        self.assertIsNone(lls.match_newest(ROWS, "nobody@zz.example"))

    def test_match_newest_knows_both_linkedin_spellings(self):
        self.assertIs(lls.match_newest(ROWS, "https://www.linkedin.example/in/zzyx-widgets-fake-0001/"), ROWS[4])

    def test_match_unsent_takes_the_newest_unsent_and_narrows_by_company_and_subject(self):
        self.assertIs(lls.match_unsent(ROWS, "pat@zz.example"), ROWS[2])
        self.assertIs(lls.match_unsent(ROWS, "pat@zz.example", company="Zz Two"), ROWS[1])
        self.assertIs(lls.match_unsent(ROWS, "pat@zz.example", subject="Two"), ROWS[1])
        self.assertIsNone(lls.match_unsent(ROWS, "pat@zz.example", company="Zz One"))      # sent, so not unsent
        self.assertIsNone(lls.match_unsent(ROWS, "pat@zz.example", company="Typo Co"))      # a typo is not a license to flip the newest
        self.assertIsNone(lls.match_unsent(ROWS, "lee@zz.example"))

    def test_match_status_filters_by_the_given_statuses(self):
        self.assertIs(lls.match_status(ROWS, "pat@zz.example", {"sent"}), ROWS[0])
        self.assertIs(lls.match_status(ROWS, "lee@zz.example", ("bounced",)), ROWS[3])
        self.assertIsNone(lls.match_status(ROWS, "lee@zz.example", ("sent",)))

    def test_current_stage_is_stage_else_replied_else_sent(self):
        self.assertEqual(lls.current_stage({"stage": "interview"}), "interview")
        self.assertEqual(lls.current_stage({"replied": True}), "replied")
        self.assertEqual(lls.current_stage({}), "sent")

    def test_stage_refusal_is_the_sentence_for_a_backwards_move_and_none_otherwise(self):
        self.assertIsNone(lls.stage_refusal("sent", "replied", "pat@zz.example"))
        self.assertIsNone(lls.stage_refusal("replied", "closed", "pat@zz.example"))
        top = lls.STAGES[-1]
        got = lls.stage_refusal(top, "sent", "pat@zz.example")
        self.assertEqual(got, "refusing to move %s BACKWARDS from %r to %r. Record a reversal as `closed` with a note; the high-water mark stays." % ("pat@zz.example", top, "sent"))


if __name__ == "__main__":
    unittest.main()
