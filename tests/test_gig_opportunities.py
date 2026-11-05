#!/usr/bin/env python3
"""Tests for gig.py's opportunity model (2026-09-27): platform > opportunities, one card
per OPPORTUNITY (role, rate, stage). His ruling (relayed by 1e): every status ask and
every hours log names the opportunity, never just the platform. `--opportunity` is
optional everywhere and defaults to the platform's own name, so the 24 platforms banked
before this change need no migration or backfill -- test_gig.py (unchanged) is the
backward-compatibility proof this file does not repeat.

Runs the production script as a subprocess inside a sandbox (harness.Sandbox), same
shape as test_gig.py.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import SandboxTest  # noqa: E402

STAGES_REL = os.path.join("documents", "state", "gig-stages.jsonl")
INCOME_REL = os.path.join("documents", "state", "gig-income.jsonl")


class OpportunityDefaultsToPlatformName(SandboxTest):
    SANDBOX_NAME = "gig_opp_default"

    def _rows(self, rel):
        return [json.loads(l) for l in self.sb.lines(rel)]

    def test_bank_without_opportunity_defaults_to_platform_name(self):
        res = self.sb.script("gig.py", "bank", "SoloPlatform",
                              "--work-type", "eval_rubric", "--rate-hr", "60")
        self.assertExit(res, 0, res.stdout + res.stderr)
        rows = [r for r in self._rows(STAGES_REL) if r["platform"] == "SoloPlatform"]
        self.assertEqual(rows[0]["opportunity"], "SoloPlatform")

    def test_income_without_opportunity_defaults_to_platform_name(self):
        res = self.sb.script("gig.py", "income", "SoloPlatform",
                              "--week-of", "2026-09-08", "--hours", "10", "--rate-hr", "60")
        self.assertExit(res, 0, res.stdout + res.stderr)
        rows = [r for r in self._rows(INCOME_REL) if r.get("company_key") == "soloplatform"]
        self.assertEqual(rows[0]["opportunity"], "SoloPlatform")


class MultipleOpportunitiesPerPlatform(SandboxTest):
    SANDBOX_NAME = "gig_opp_multi"

    def _rows(self, rel):
        return [json.loads(l) for l in self.sb.lines(rel)]

    def test_two_opportunities_track_independent_stages(self):
        """The artboard's own example: one platform, several pieces of work, each its own
        card with its own stage. A stage move on one opportunity must never move, or be
        blocked by, another opportunity's stage on the same platform."""
        self.sb.script("gig.py", "bank", "MultiPlatform", "--opportunity", "Reviewer",
                        "--work-type", "eval_rubric", "--rate-hr", "55")
        self.sb.script("gig.py", "bank", "MultiPlatform", "--opportunity", "Writer",
                        "--work-type", "eval_rubric", "--rate-hr", "45")
        self.sb.script("gig.py", "screen", "MultiPlatform", "--opportunity", "Reviewer",
                        "--defense", "pass", "--a16z-led", "no",
                        "--pe-owned", "no", "--nonpayment-reported", "no")
        self.sb.script("gig.py", "stage", "MultiPlatform", "--opportunity", "Reviewer",
                        "--stage", "applied")

        rows = [r for r in self._rows(STAGES_REL) if r["platform"] == "MultiPlatform"]
        reviewer_latest = [r for r in rows if r["opportunity"] == "Reviewer"][-1]
        writer_latest = [r for r in rows if r["opportunity"] == "Writer"][-1]
        self.assertEqual(reviewer_latest["stage"], "applied")
        self.assertEqual(writer_latest["stage"], "banked", "Writer must be untouched by Reviewer's move")

    def test_monotonic_check_is_per_opportunity_not_per_platform(self):
        """A platform where one opportunity is already 'active' must not block a SECOND,
        newly banked opportunity on the same platform from starting at 'banked' -- the
        monotonic check compares each opportunity against its OWN prior stage."""
        self.sb.script("gig.py", "bank", "MonoMulti", "--opportunity", "First",
                        "--work-type", "eval_rubric", "--rate-hr", "55")
        self.sb.script("gig.py", "screen", "MonoMulti", "--opportunity", "First",
                        "--defense", "pass", "--a16z-led", "no",
                        "--pe-owned", "no", "--nonpayment-reported", "no")
        self.sb.script("gig.py", "stage", "MonoMulti", "--opportunity", "First",
                        "--stage", "applied")
        self.sb.script("gig.py", "stage", "MonoMulti", "--opportunity", "First",
                        "--stage", "active")
        # A brand new second opportunity on the same platform: banked is not a demotion for IT.
        res = self.sb.script("gig.py", "bank", "MonoMulti", "--opportunity", "Second",
                              "--work-type", "eval_rubric", "--rate-hr", "45")
        self.assertExit(res, 0, res.stdout + res.stderr)
        rows = [r for r in self._rows(STAGES_REL) if r["platform"] == "MonoMulti"]
        second_latest = [r for r in rows if r["opportunity"] == "Second"][-1]
        self.assertEqual(second_latest["stage"], "banked")

    def test_screen_requires_a_bank_for_that_same_opportunity(self):
        """Banking one opportunity on a platform must not let `screen` succeed for a
        DIFFERENT, never-banked opportunity on the same platform."""
        self.sb.script("gig.py", "bank", "NeedsOwnBank", "--opportunity", "Banked One",
                        "--work-type", "eval_rubric", "--rate-hr", "55")
        res = self.sb.script("gig.py", "screen", "NeedsOwnBank", "--opportunity", "Never Banked",
                              "--defense", "pass", "--a16z-led", "no",
                              "--pe-owned", "no", "--nonpayment-reported", "no")
        self.assertNotEqual(res.returncode, 0,
                             "screening an opportunity with no bank row of its own must be refused")


class RateCanBeUnknownNeverGuessed(SandboxTest):
    """His real zzmicro data (documents/design/zzmicro-opportunities-answers-2026-09-27.md):
    one opportunity, stage ACTIVE, "rate not given". The floor check must never guess a
    rate to satisfy its own required flag -- an unknown rate is its own honest state, not
    zero and not a red flag."""
    SANDBOX_NAME = "gig_opp_no_rate"

    def _rows(self, rel):
        return [json.loads(l) for l in self.sb.lines(rel)]

    def test_bank_without_rate_records_rate_as_none_not_a_guess(self):
        res = self.sb.script("gig.py", "bank", "NoRateCo", "--opportunity", "Generalist",
                              "--work-type", "eval_rubric")
        self.assertExit(res, 0, res.stdout + res.stderr)
        rows = [r for r in self._rows(STAGES_REL) if r["platform"] == "NoRateCo"]
        self.assertIsNone(rows[0]["rate_hr"])
        self.assertNotIn("below floor", rows[0]["red_flags"], "an unknown rate is not a floor violation")

    def test_report_shows_rate_not_given_never_a_guessed_number(self):
        self.sb.script("gig.py", "bank", "NoRateReport", "--opportunity", "Generalist",
                        "--work-type", "eval_rubric")
        res = self.sb.script("gig.py", "report", "--json", GIG_LANE_ENABLED="1")
        self.assertExit(res, 0, res.stdout + res.stderr)
        data = json.loads(res.stdout)
        row = [r for r in data["queue"]["banked"] if r["platform"] == "NoRateReport"][0]
        self.assertIsNone(row.get("rate_hr"))


class CurrentQueueGroupsByOpportunity(SandboxTest):
    SANDBOX_NAME = "gig_opp_queue"

    def test_report_json_names_the_opportunity(self):
        """His ruling: every status ask names the opportunity, never just the platform.
        `report --json` must carry an `opportunity` field the deck (and the CLI's own
        printed report) can read, distinguishing two cards on one platform."""
        self.sb.script("gig.py", "bank", "ReportMulti", "--opportunity", "Alpha Role",
                        "--work-type", "eval_rubric", "--rate-hr", "55")
        self.sb.script("gig.py", "bank", "ReportMulti", "--opportunity", "Beta Role",
                        "--work-type", "eval_rubric", "--rate-hr", "65")
        res = self.sb.script("gig.py", "report", "--json",
                              GIG_LANE_ENABLED="1")
        self.assertExit(res, 0, res.stdout + res.stderr)
        data = json.loads(res.stdout)
        banked = data["queue"]["banked"]
        opps = {(r["platform"], r["opportunity"]) for r in banked}
        self.assertIn(("ReportMulti", "Alpha Role"), opps)
        self.assertIn(("ReportMulti", "Beta Role"), opps)

    def test_report_text_names_the_opportunity_when_it_differs_from_platform(self):
        self.sb.script("gig.py", "bank", "TextMulti", "--opportunity", "Prompt Tester",
                        "--work-type", "eval_rubric", "--rate-hr", "55")
        res = self.sb.script("gig.py", "report", GIG_LANE_ENABLED="1")
        self.assertExit(res, 0, res.stdout + res.stderr)
        self.assertIn("Prompt Tester", res.stdout)

    def test_report_text_does_not_repeat_platform_as_opportunity_when_solo(self):
        """A single-opportunity platform (the common case, 24 of them today) should not
        clutter the report with 'Platform: Platform' -- opportunity defaults silently to
        the platform name and the report reads exactly as it did before this change."""
        self.sb.script("gig.py", "bank", "SoloReport",
                        "--work-type", "eval_rubric", "--rate-hr", "55")
        res = self.sb.script("gig.py", "report", GIG_LANE_ENABLED="1")
        self.assertExit(res, 0, res.stdout + res.stderr)
        self.assertNotIn("SoloReport: SoloReport", res.stdout)


if __name__ == "__main__":
    unittest.main()
