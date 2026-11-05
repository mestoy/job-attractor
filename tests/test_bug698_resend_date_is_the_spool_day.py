#!/usr/bin/env python3
"""BUG-698: a spooled resend folded the next day carried the fold's date as resent_date. The date belongs to the day
the resend was spooled (the entry's `at`), read in the configured zone like every other send day (BUG-795). The live
writer still stamps today. All names are invented."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import sendlog_lock as sl  # noqa: E402


def bounced():
    return {"status": "bounced", "company": "Zzyx Widgets", "to_name": "Casey Fixture", "subject": "Hello", "to": "old@zzyx.example",
            "date": "2026-10-02", "bounced_at": "2026-10-02", "first_bounced_at": "2026-10-02"}


def entry(at, **extra):
    e = {"spool_id": "a" * 32, "at": at, "op": "append", "writer": "mail-draft",
         "key": {"resend": True, "company": "Zzyx Widgets", "to_name": "Casey Fixture", "subject": "Hello"},
         "fields": {"status": "staged", "company": "Zzyx Widgets", "to_name": "Casey Fixture", "subject": "Hello", "to": "new@zzyx.example", "date": "2026-10-05"}}
    e.update(extra)
    return e


class ResentDateIsTheSpoolDay(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.get("LOCAL_DAY_NOW")
        os.environ["LOCAL_DAY_NOW"] = "2026-10-06T10:00:00-04:00"        # the fold runs the next day

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("LOCAL_DAY_NOW", None)
        else:
            os.environ["LOCAL_DAY_NOW"] = self.saved

    def test_a_folded_resend_carries_the_day_it_was_spooled(self):
        items = [bounced()]
        state, _ = sl.apply_entry(items, entry("2026-10-05T14:00:00.000000-04:00"))
        self.assertEqual("applied", state)
        self.assertEqual("2026-10-05", items[0]["resent_date"])

    def test_the_live_writer_still_stamps_today(self):
        items = [bounced()]
        row = dict(entry("x")["fields"])
        self.assertTrue(sl.resend_into(items, row, "Zzyx Widgets", "Casey Fixture", "Hello", set()))
        self.assertEqual("2026-10-06", items[0]["resent_date"])

    def test_an_entry_with_no_readable_at_falls_back_to_today(self):
        for at in ("", "not a time"):
            items = [bounced()]
            sl.apply_entry(items, entry(at))
            self.assertEqual("2026-10-06", items[0]["resent_date"], at)

    def test_a_late_evening_spool_keeps_its_own_calendar_day(self):
        items = [bounced()]
        sl.apply_entry(items, entry("2026-10-06T03:30:00+00:00"))        # 23:30 on the 5th in New York
        self.assertEqual(sl._local_day.day_of("2026-10-06T03:30:00+00:00"), items[0]["resent_date"])


if __name__ == "__main__":
    unittest.main()
