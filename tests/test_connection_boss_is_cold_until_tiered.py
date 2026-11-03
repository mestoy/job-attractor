#!/usr/bin/env python3
"""test_connection_boss_is_cold_until_tiered.py -- slice A commit 2 (BUG-600), test (b4) on the app path.

feed_install.annotate used to mark ANY boss whose name is in the contact store as rung "warm", whatever the closeness tier, so the
app built warm-shaped notes for people the CLI would refuse (check_preview's WARM-RUNG consults the closeness store). Now a boss
who is merely a connection is cold (rung None, which the page and Build read as "cold-boss") until closeness.warm_sanctioned says
otherwise. The clock is pinned through `today`. Names are obviously fake.
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import feed_install  # noqa: E402

TODAY = datetime.date(2026, 10, 8)
BOSS = "Zzqana Testperson"


class ConnectionBossIsCold(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="coldboss_", dir=os.environ.get("TMPDIR"))
        self.addCleanup(shutil.rmtree, self.repo, True)
        os.makedirs(os.path.join(self.repo, "documents", "state"))
        row = {"kind": "contact", "key": "zzqana-testperson", "payload": {"name": BOSS, "company": "Zzqco Fake Works"}}
        with open(os.path.join(self.repo, "documents", "state", "contact.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def _tier(self, tier, **extra):
        entry = {"closeness": tier}
        entry.update(extra)
        with open(os.path.join(self.repo, "documents", "contact-closeness.json"), "w", encoding="utf-8") as fh:
            json.dump({"contacts": {BOSS: entry}}, fh)

    def _annotated(self, boss=BOSS):
        cards = [{"slug": "zzqco-fake-works", "company": "Zzqco Fake Works", "boss": {"name": boss}}]
        warm = feed_install.read_warm(self.repo)
        return feed_install.annotate(cards, [], warm, [], today=TODAY)[0]

    def test_a_connection_with_no_closeness_store_at_all_is_cold(self):
        c = self._annotated()
        self.assertIsNone(c["rung"])

    def test_a_connection_with_no_row_in_the_store_is_cold(self):
        with open(os.path.join(self.repo, "documents", "contact-closeness.json"), "w", encoding="utf-8") as fh:
            json.dump({"contacts": {"Zzqbo Someoneelse": {"closeness": "know-well"}}}, fh)
        self.assertIsNone(self._annotated()["rung"])

    def test_untiered_tiers_stay_cold(self):
        for tier in ("never-spoke", "linkedin-acquaintance", "known-level-tbd", "zzq-not-a-tier"):
            self._tier(tier)
            self.assertIsNone(self._annotated()["rung"], tier)

    def test_a_held_contact_stays_cold_whatever_the_tier(self):
        self._tier("worked-together", do_not_contact=True)
        self.assertIsNone(self._annotated()["rung"])

    def test_the_control_a_warm_tier_gives_warm(self):
        for tier in ("worked-together", "know-well", "know-not-close", "friend"):
            self._tier(tier)
            c = self._annotated()
            self.assertEqual(c["rung"], "warm", tier)
            self.assertEqual(c["closeness"], tier)

    def test_a_strong_tie_gone_quiet_is_cold_and_a_live_one_is_warm_on_the_pinned_date(self):
        self._tier("worked-together", messages={"total": 5, "they_sent": 2, "last_inbound": "2024-01-01"})
        self.assertIsNone(self._annotated()["rung"])
        self._tier("worked-together", messages={"total": 5, "they_sent": 2, "last_inbound": "2026-09-20"})
        self.assertEqual(self._annotated()["rung"], "warm")

    def test_a_boss_who_is_not_a_connection_is_still_cold_and_unmarked(self):
        c = self._annotated(boss="Zzqyo Nobody")
        self.assertIsNone(c["rung"])
        self.assertIsNone(c["closeness"])


class AHandBuiltWarmDict(unittest.TestCase):
    """R244 SHOULD: a warm dict in the OLD shape (names, tiers, normalize; no rows, no predicate) must not KeyError, and it must not fabricate warmth."""

    def test_the_old_shape_does_not_raise_and_stays_cold(self):
        import closeness
        warm = {"names": {"zzqana testperson": "Zzqana Testperson"}, "tiers": {"zzqana testperson": "know-well"},
                "normalize": closeness.normalize_name}
        cards = [{"slug": "zzqco", "company": "Zzqco Fake Works", "boss": {"name": "Zzqana Testperson"}}]
        out = feed_install.annotate(cards, [], warm, [], today=TODAY)[0]
        self.assertIsNone(out["rung"])                      # no closeness row travels in the old shape, so nothing is sanctioned


if __name__ == "__main__":
    unittest.main()
