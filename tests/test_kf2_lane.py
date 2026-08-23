#!/usr/bin/env python3
"""Cluster C: lane configurability (kit#52 + kit#64 — the same PM-lane-hardcoding shape,
one at the discovery layer, one at the linter layer).

kit#52: `check_ats.is_pm()` (the LIVE-role-vs-RADAR verdict) matched product-management titles
only, so an install whose lane is business analysis, process improvement or program management
was blind to its own primary lane — both false negatives (a live in-lane req reported as absent)
and false positives (an engineering seat reported as the "live PM role").

kit#64: `check_outreach.py` ingredient 5 ("what you can offer them") recognized only
product-management outcome verbs (taken/drove/driven/led/shipped/built), so 9 of 12 realistic
first-person business-analyst / process-improvement result sentences failed the gate even though
each one is the same CLASS of claim, just phrased differently.

⚠️ NEW FILE, NOT test_gates.py: consistent with Cluster A's collision-avoidance note — keeping
each cluster's coverage in its own file means merges never fight over the same test-file diff.
"""
import importlib
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)


# ─────────────────────────────────────────────────────────────────────────────
# kit#52 — check_ats.is_in_lane() (formerly is_pm)
# ─────────────────────────────────────────────────────────────────────────────
class InLaneConfigurabilityTests(unittest.TestCase):
    def setUp(self):
        check_ats = importlib.import_module("check_ats")
        kit_config = importlib.import_module("kit_config")
        importlib.reload(check_ats)  # fresh, in case an earlier test mutated kit_config
        self.check_ats = check_ats
        self.kit_config = kit_config
        self._real_seat_title = kit_config.SEAT_TITLE

    def tearDown(self):
        self.kit_config.SEAT_TITLE = self._real_seat_title

    # ── kit#52's own reproduction, both configurations ──────────────────────────────────
    PM_TITLES = ["Senior Product Manager", "Product Owner"]
    BA_TITLES = [
        "Lead Program Manager, Community Wishlist", "Senior Business Analyst",
        "Business Systems Analyst V", "Senior Outbound Program Manager",
        "Process Improvement Manager", "PMO Analyst", "Technical Program Manager",
    ]

    def test_default_lane_unset_matches_only_pm_titles_unchanged(self):
        """No SEAT_TITLE configured: behavior must be BYTE-IDENTICAL to before this fix — the
        exact false-negative repro from kit#52 still misses under the shipped default, because
        an install that has not declared a lane gets no behavior change."""
        self.kit_config.SEAT_TITLE = ""
        for t in self.PM_TITLES:
            self.assertTrue(self.check_ats.is_in_lane(t), f"default lane missed a PM title: {t}")
        for t in self.BA_TITLES:
            self.assertFalse(self.check_ats.is_in_lane(t),
                             f"default (unconfigured) lane must not match a BA/PMO title: {t}")

    def test_a_configured_ba_lane_recognizes_every_missed_title(self):
        """THE FIX. Every title kit#52 measured as MISS under a BA/PMO lane must now match."""
        self.kit_config.SEAT_TITLE = (
            r"\b(program manager|business analyst|business systems analyst|"
            r"process improvement manager|pmo analyst|technical program manager)\b")
        for t in self.BA_TITLES:
            self.assertTrue(self.check_ats.is_in_lane(t),
                            f"configured BA lane still missed an in-lane title: {t}")

    def test_a_configured_lane_does_not_accept_everything(self):
        """⛔ DOES-NOT-OVER-ACCEPT. Configuring a BA lane must not turn is_in_lane into a
        rubber stamp — an off-lane engineering seat, and an off-lane PM seat, both still miss."""
        self.kit_config.SEAT_TITLE = (
            r"\b(program manager|business analyst|business systems analyst|"
            r"process improvement manager|pmo analyst|technical program manager)\b")
        self.assertFalse(self.check_ats.is_in_lane("Staff Software Engineer, Product"),
                         "an engineering seat matched a BA lane — this is kit#52's own named "
                         "false-positive example, now reproduced under a configured lane")
        for t in self.PM_TITLES:
            self.assertFalse(self.check_ats.is_in_lane(t),
                             f"a PM title matched a lane that never named product management: {t}")

    def test_is_pm_alias_still_works(self):
        """Backward compatibility: anything importing `is_pm` directly keeps working."""
        self.assertIs(self.check_ats.is_pm, self.check_ats.is_in_lane)

    def test_the_verdict_wording_is_lane_neutral(self):
        src = open(os.path.join(SCRIPTS, "check_ats.py"), encoding="utf-8").read()
        self.assertIn("LIVE IN-LANE ROLE", src)
        self.assertNotIn("LIVE PM ROLE", src,
                         "the verdict string still says 'PM role', misleading on a non-PM install")


# ─────────────────────────────────────────────────────────────────────────────
# kit#64 — check_outreach.py ingredient 5/1 outcome-verb recognition
# ─────────────────────────────────────────────────────────────────────────────
class OutcomeVerbConfigurabilityTests(unittest.TestCase):
    def setUp(self):
        self.co = importlib.import_module("check_outreach")

    def _ingredient(self, n):
        row = next(r for r in self.co.INGREDIENTS if r[0] == n)
        return re.compile(row[2], re.I)

    # kit#64's own twelve-sentence reproduction, verbatim.
    RESULT_SENTENCES = [
        "At Florida Blue I migrated 7 lines of business across enterprise data sources",
        "I led the migration of 7 lines of business",
        "I consolidated three systems into one",
        "I automated the intake process",
        "I rebuilt the process end to end",
        "I owned the requirements and the backlog",
        "I delivered the platform on time",
        "I launched the new intake flow",
        "I implemented the scheduling module",
        "I standardised reporting across the business",
        "I shipped the release",
        "I built the dashboard",
    ]

    def test_all_twelve_reproduction_sentences_now_match_ingredient_5(self):
        pat = self._ingredient(5)
        misses = [s for s in self.RESULT_SENTENCES if not pat.search(s)]
        self.assertEqual(misses, [], f"still missing: {misses}")

    def test_ingredient_1_recognizes_the_same_broadened_verb_set(self):
        """Ingredient 1 ('who you are') shares the SAME verb branch as ingredient 5, on
        purpose (kit issue #64's fix note: 'shared... so the two branches cannot drift').
        Pin that they actually stay in sync rather than re-diverging silently."""
        pat1 = self._ingredient(1)
        self.assertTrue(pat1.search("I consolidated three systems into one"))
        self.assertTrue(pat1.search("I automated the intake process"))

    def test_does_not_over_accept_a_non_first_person_or_non_claim_sentence(self):
        """⛔ DOES-NOT-OVER-ACCEPT. The broadened list must still require first person and an
        actual outcome verb — it must not become 'any sentence mentioning a company action'."""
        pat = self._ingredient(5)
        negatives = [
            "They built a great platform",
            "You led an amazing team",
            "The company migrated to a new system",
            "I think this is a great opportunity",
            "I am excited about your work",
        ]
        for s in negatives:
            self.assertIsNone(pat.search(s), f"over-accepted a non-claim sentence: {s!r}")

    def test_the_verb_list_is_read_from_kit_config(self):
        kit_config = importlib.import_module("kit_config")
        self.assertTrue(hasattr(kit_config, "OUTCOME_VERBS"),
                        "kit_config has no OUTCOME_VERBS — the verb list is not configurable")
        self.assertIn("migrated", kit_config.OUTCOME_VERBS)
        self.assertIn("consolidated", kit_config.OUTCOME_VERBS)
        # The shipped PM verbs must still be present — this is an EXTENSION, not a replacement.
        for v in ("taken", "led", "built", "shipped", "drove", "driven"):
            self.assertIn(v, kit_config.OUTCOME_VERBS)

    def test_the_two_ingredient_branches_share_one_verb_definition(self):
        """⛔ NO SECOND WRITER. Both branches must build FROM the same `_OUTCOME_VERB_RE`
        rather than each hand-typing its own copy of the verb list — the exact defect shape
        that let ingredient 5 drift out of sync with a future ingredient-1 edit."""
        src = open(os.path.join(SCRIPTS, "check_outreach.py"), encoding="utf-8").read()
        self.assertEqual(src.count("_OUTCOME_VERB_RE"), 3,
                         "expected exactly one definition + two uses of _OUTCOME_VERB_RE")


if __name__ == "__main__":
    unittest.main()
