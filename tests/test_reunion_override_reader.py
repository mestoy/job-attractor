#!/usr/bin/env python3
"""BUG-769: check_preview._reunion_override_for reads the override from the DATA ROOT, from either layout, by the same exactly-one rule
as the tier lookup. A pure bugfix: no tier verdict changes.

The live override layout puts the override at the TOP LEVEL of documents/contact-closeness.json (key = name) while closeness.load() reads only raw["contacts"].
The reader also resolved the file from the SCRIPT's own tree, so a redirected install (JOBSEARCH_DATA_ROOT, the app's stage) silently ignored it.
It now reads the data root, accepts the override at the top level or in the person's own row (same narrow rules: ruled_on and reason, per
person, no wildcard), and an exact name wins while a prefix (a capture truncated before a middle initial) matches only when EXACTLY ONE person
carries it: an ambiguous prefix matches nothing instead of borrowing the first row's ruling. Names are obviously fake.
"""
import json
import os
import _roots
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import closeness  # noqa: E402

NAME = "Zzqana Testperson"
OVERRIDE = {"ruled_on": "2026-10-01", "reason": "fake reason", "scope": "fixture"}


def thread(last_inbound, they_sent=2, total=5):
    return {"messages": {"total": total, "they_sent": they_sent, "last_inbound": last_inbound}}


class Reader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="override_reader_", dir=os.path.expanduser("~/render"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, "documents"))
        _roots.patch_roots(self, self.tmp)
        import check_preview
        self.cp = check_preview


    def _write(self, raw):
        with open(os.path.join(self.tmp, "documents", "contact-closeness.json"), "w", encoding="utf-8") as fh:
            json.dump(raw, fh)

    def test_the_live_layout_override_at_the_top_level_is_found_under_a_redirected_data_root(self):
        self._write({"contacts": {NAME: dict(closeness="worked-together", **thread("2020-01-01"))},
                     NAME: dict(closeness="worked-together", reunion_override=OVERRIDE)})
        self.assertEqual(OVERRIDE, self.cp._reunion_override_for(NAME))
        self.assertIsNone(self.cp._closeness_verdict(NAME), "a cold strong tie with an override stands down")

    def test_an_override_inside_the_persons_own_row_also_counts(self):
        self._write({"contacts": {NAME: dict(closeness="worked-together", reunion_override=OVERRIDE, **thread("2020-01-01"))}})
        self.assertEqual(OVERRIDE, self.cp._reunion_override_for(NAME))
        self.assertIsNone(self.cp._closeness_verdict(NAME))

    def test_an_override_without_a_date_or_a_reason_does_nothing(self):
        for bad in ({"reason": "no date"}, {"ruled_on": "2026-10-01"}, {}):
            with self.subTest(bad=bad):
                self._write({"contacts": {NAME: dict(closeness="worked-together", **thread("2020-01-01"))},
                             NAME: dict(closeness="worked-together", reunion_override=bad)})
                self.assertIsNone(self.cp._reunion_override_for(NAME))
                self.assertIsNotNone(self.cp._closeness_verdict(NAME))

    def test_an_override_is_per_person_never_a_wildcard(self):
        self._write({"contacts": {NAME: dict(closeness="worked-together", **thread("2020-01-01"))},
                     "Someone Else": dict(closeness="know-well", reunion_override=OVERRIDE)})
        self.assertIsNone(self.cp._reunion_override_for(NAME))
        self.assertIsNotNone(self.cp._closeness_verdict(NAME))

    def test_an_override_never_rescues_a_never_spoke_or_held_row(self):
        for extra in ({"closeness": "never-spoke"}, {"closeness": "know-well", "do_not_contact": True}):
            with self.subTest(extra=extra):
                self._write({"contacts": {NAME: dict(extra)}, NAME: dict(extra, reunion_override=OVERRIDE)})
                self.assertIsNotNone(self.cp._closeness_verdict(NAME))

    def test_a_reunion_kind_tier_is_never_refused_as_a_tier(self):
        reunions = [t for t, spec in closeness.TIERS.items() if spec[0] == "reunion"]
        self.assertTrue(reunions, "the table has no reunion-kind tier to test")
        for t in reunions:
            with self.subTest(tier=t):
                self._write({"contacts": {NAME: {"closeness": t}}})
                self.assertIsNone(self.cp._closeness_verdict(NAME))
                self._write({"contacts": {NAME: dict(closeness=t, **thread("2026-10-01"))}})
                self.assertIsNone(self.cp._closeness_verdict(NAME))

    def test_an_exact_name_wins_over_a_longer_name_that_shares_its_start(self):
        self._write({"contacts": {NAME: {"closeness": "know-well"}, NAME + " Junior": {"closeness": "know-well"}},
                     NAME + " Junior": dict(reunion_override=OVERRIDE)})
        self.assertIsNone(self.cp._reunion_override_for(NAME), "the exact person has no override; the longer name's must not leak in")
        self.assertEqual(OVERRIDE, self.cp._reunion_override_for(NAME + " Junior"))

    def test_a_truncated_capture_resolves_only_when_exactly_one_person_carries_the_prefix(self):
        # `WARM-RUNG: Pat J. Example` captures "Pat J": one person carries that prefix, so it resolves
        self._write({"contacts": {"Zzpat J Example": {"closeness": "know-well"}}, "Zzpat J Example": dict(reunion_override=OVERRIDE)})
        self.assertEqual(OVERRIDE, self.cp._reunion_override_for("Zzpat J"))
        # two people carry the prefix, only one holds an override: the ambiguous prefix matches NOTHING (the old code took the first)
        self._write({"contacts": {"Zzpat J Example": {"closeness": "know-well"}, "Zzpat J Sample": {"closeness": "know-well"}},
                     "Zzpat J Example": dict(reunion_override=OVERRIDE)})
        self.assertIsNone(self.cp._reunion_override_for("Zzpat J"))
        self.assertEqual(OVERRIDE, self.cp._reunion_override_for("Zzpat J Example"))

    def test_the_reader_follows_the_data_root_not_the_script_tree(self):
        self._write({NAME: dict(reunion_override=OVERRIDE)})
        self.assertEqual(OVERRIDE, self.cp._reunion_override_for(NAME))
        other = tempfile.mkdtemp(prefix="override_reader_other_", dir=os.path.expanduser("~/render"))
        self.addCleanup(shutil.rmtree, other, True)
        os.makedirs(os.path.join(other, "documents"))
        os.environ["JOBSEARCH_DATA_ROOT"] = other
        self.assertIsNone(self.cp._reunion_override_for(NAME), "another data root has no override for this person")


if __name__ == "__main__":
    unittest.main()
