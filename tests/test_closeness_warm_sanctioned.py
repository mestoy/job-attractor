#!/usr/bin/env python3
"""test_closeness_warm_sanctioned.py -- slice A commit 1 (BUG-600).

ONE predicate says whether a closeness row sanctions a warm-shaped ask: closeness.warm_sanctioned(row, today=None).
check_preview._closeness_verdict (the CLI's WARM-RUNG consult) and feed_install.annotate (the app's rung) both call it,
so the two paths cannot disagree. thread_state reads today's date, so every test here pins `today`.
Names are obviously fake.
"""
import datetime
import json
import os
import _roots
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import closeness  # noqa: E402

TODAY = datetime.date(2026, 10, 8)


def row(tier, **extra):
    r = {"closeness": tier}
    r.update(extra)
    return r


def thread(last_inbound, they_sent=2, total=5):
    return {"messages": {"total": total, "they_sent": they_sent, "last_inbound": last_inbound}}


class WarmSanctioned(unittest.TestCase):
    def ok(self, r):
        return closeness.warm_sanctioned(r, today=TODAY)

    def test_no_row_is_not_sanctioned(self):
        self.assertFalse(self.ok(None))
        self.assertFalse(self.ok({}))

    def test_every_warm_tier_with_no_thread_data_is_sanctioned(self):
        for tier, spec in closeness.TIERS.items():
            if spec[0] in ("warm", "reunion") and tier != "known-level-tbd":
                self.assertTrue(self.ok(row(tier)), tier)

    def test_the_unlevelled_and_never_spoke_tiers_are_not_sanctioned(self):
        for tier in ("known-level-tbd", "never-spoke", "linkedin-acquaintance"):
            self.assertFalse(self.ok(row(tier)), tier)

    def test_aliases_resolve_before_the_check(self):
        self.assertTrue(self.ok(row("friend")))
        self.assertTrue(self.ok(row("acquaintance")))

    def test_an_unmapped_tier_fails_closed(self):
        self.assertFalse(self.ok(row("zzq-not-a-tier")))
        self.assertFalse(self.ok(row("")))
        self.assertFalse(self.ok({"display_name": "Zzqana Testperson"}))

    def test_a_held_contact_is_not_sanctioned_whatever_the_tier(self):
        self.assertFalse(self.ok(row("worked-together", do_not_contact=True)))
        self.assertFalse(self.ok(row("know-well", outreach_status="paused: not now")))

    def test_a_strong_tie_with_a_dead_thread_is_not_sanctioned_but_a_live_one_is(self):
        self.assertFalse(self.ok(row("worked-together", **thread("2024-01-01"))))
        self.assertFalse(self.ok(row("know-well", **thread(None, they_sent=0))))
        self.assertTrue(self.ok(row("worked-together", **thread("2026-09-20"))))

    def test_a_thin_tie_is_sanctioned_whatever_its_thread(self):
        self.assertTrue(self.ok(row("know-not-close", **thread("2020-01-01"))))

    def test_the_date_is_an_input_not_the_clock(self):
        r = row("worked-together", **thread("2026-06-01"))
        self.assertTrue(closeness.warm_sanctioned(r, today=datetime.date(2026, 8, 1)))
        self.assertFalse(closeness.warm_sanctioned(r, today=datetime.date(2028, 1, 1)))

    def test_the_refusal_carries_a_code_the_cli_can_word(self):
        self.assertEqual(closeness.warm_refusal(row("never-spoke"), today=TODAY)[0], "never-spoke")
        self.assertEqual(closeness.warm_refusal(row("linkedin-acquaintance"), today=TODAY)[0], "acquaintance")
        self.assertEqual(closeness.warm_refusal(row("known-level-tbd"), today=TODAY)[0], "unlevelled")
        self.assertEqual(closeness.warm_refusal(row("know-well", do_not_contact=True), today=TODAY)[0], "held")
        self.assertEqual(closeness.warm_refusal(row("know-well", **thread("2020-01-01")), today=TODAY)[0], "cold-strong")
        self.assertEqual(closeness.warm_refusal(row("zzq"), today=TODAY)[0], "unmapped")
        self.assertEqual(closeness.warm_refusal(row("know-well"), today=TODAY), (None, None))


class TheCliConsultAgrees(unittest.TestCase):
    """check_preview._closeness_verdict (None = no objection) must say exactly what warm_sanctioned says, for every tier and alias,
    with the clock pinned. The reunion override is the one documented extra: it stands a cold strong tie down."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="warm_sanc_", dir=os.environ.get("TMPDIR"))
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, "documents"))
        _roots.patch_roots(self, self.tmp)
        import check_preview
        self.cp = check_preview


    def _store(self, tier, extra=None):
        r = {"closeness": tier}
        r.update(extra or {})
        with open(os.path.join(self.tmp, "documents", "contact-closeness.json"), "w", encoding="utf-8") as fh:
            json.dump({"contacts": {"Zzqana Testperson": r}}, fh)

    def test_the_two_paths_agree_on_every_tier_and_alias(self):
        tiers = list(closeness.TIERS) + list(closeness.TIER_ALIASES) + ["zzq-not-a-tier"]
        for tier in tiers:
            self._store(tier)
            refused = self.cp._closeness_verdict("Zzqana Testperson") is not None
            sanctioned = closeness.warm_sanctioned({"closeness": tier})
            self.assertEqual(refused, not sanctioned, "%s: CLI refused=%s, predicate sanctioned=%s" % (tier, refused, sanctioned))

    def test_the_cli_consult_refuses_a_linkedin_acquaintance_in_its_own_words(self):
        """R243 SHOULD: the old logic let this tier through (its tuple is never-spoke's, but the consult never named it), and the
        refusal must not claim 'NEVER SPOKEN' for people who exchanged pleasantries."""
        self._store("linkedin-acquaintance")
        why = self.cp._closeness_verdict("Zzqana Testperson")
        self.assertIsNotNone(why)
        self.assertIn("beyond a LinkedIn connection", why)
        self.assertNotIn("NEVER SPOKEN", why)

    def test_a_cold_strong_tie_agrees_and_the_override_stands_it_down(self):
        extra = thread("2020-01-01")
        self._store("worked-together", extra)
        self.assertIsNotNone(self.cp._closeness_verdict("Zzqana Testperson"))
        self.assertFalse(closeness.warm_sanctioned(dict(closeness="worked-together", **extra)))
        entry = dict(closeness="worked-together", reunion_override={"ruled_on": "2026-10-01", "reason": "fake reason"}, **extra)
        # _reunion_override_for reads the RAW file's TOP-LEVEL keys while closeness.load reads raw["contacts"]; a
        # store that satisfies both carries the entry in both places (a latent mismatch, reported with this commit).
        raw = {"contacts": {"Zzqana Testperson": entry}, "Zzqana Testperson": entry}
        with open(os.path.join(self.tmp, "documents", "contact-closeness.json"), "w", encoding="utf-8") as fh:
            json.dump(raw, fh)
        self.assertIsNone(self.cp._closeness_verdict("Zzqana Testperson"))


class OneRuleOneFile(unittest.TestCase):
    def test_no_sanction_rule_is_written_outside_closeness_py(self):
        """The refusal reads (never-spoke / unlevelled / DEPTH_EVIDENCED_COLD) live in closeness.py; the callers consult it."""
        for name in ("check_preview.py", "feed_install.py"):
            with open(os.path.join(SCRIPTS, name), encoding="utf-8") as fh:
                src = fh.read()
            for needle in ("DEPTH_EVIDENCED_COLD", "TIERS.get(", "is_held("):
                self.assertFalse(needle in src, "%s still writes the sanction rule itself (%s)" % (name, needle))


if __name__ == "__main__":
    unittest.main()
