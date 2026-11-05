#!/usr/bin/env python3
"""Tests for scripts/gig.py -- G0 (stage log) and G1 (income log), red first.

Runs the PRODUCTION script as a subprocess inside a sandbox (harness.Sandbox), the same shape as
test_activity_fold.py. Proves: stages only rank forward (StageRank), a sub-floor rate flags but
never drops a row (RateFloorFlagsNeverDrops), a16z-led never auto-resolves a stage
(A16zNeverAuto), earned is computed from hours*rate never typed (IncomeComputed), the only
automatic hard drop is a defense/military/LE gate (HardDropDefense), and `report` sums trailing
7-day income correctly with a denominator (ReportSevenDayMath).
"""
import json
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import SandboxTest  # noqa: E402

STAGES_REL = os.path.join("documents", "state", "gig-stages.jsonl")
INCOME_REL = os.path.join("documents", "state", "gig-income.jsonl")


class GigStageTests(SandboxTest):
    SANDBOX_NAME = "gig_stage"

    def _rows(self, rel):
        return [json.loads(l) for l in self.sb.lines(rel)]

    def test_01_stage_rank_orders_forward(self):
        """StageRank: a later stage in banked->screened->applied->active->paid always ranks
        above an earlier one -- same shape as stage_funnel.py's own RANK dict. Run out-of-process
        (harness.probe) so importing gig.py never pollutes this test process's sys.path."""
        out = self.probe("gig", (
            "order = ['banked', 'screened', 'applied', 'active', 'paid']\n"
            "for i in range(len(order) - 1):\n"
            "    assert gig.RANK[order[i]] < gig.RANK[order[i + 1]], order[i]\n"
            "assert gig.RANK['dropped'] > gig.RANK['paid']\n"
            "print('ok')\n"
        ))
        self.assertIn("ok", out)

    def test_02_rate_floor_flags_never_drops(self):
        """RateFloorFlagsNeverDrops: a rate under $50/hr sets a red flag; the row is still
        written, never dropped or skipped."""
        res = self.sb.script("gig.py", "bank", "LowPay Co",
                              "--work-type", "persona_build", "--rate-hr", "35")
        self.assertExit(res, 0, res.stdout + res.stderr)
        rows = [r for r in self._rows(STAGES_REL) if r["platform"] == "LowPay Co"]
        self.assertEqual(len(rows), 1, "the row must still be written, never dropped")
        self.assertIn("below floor", rows[0]["red_flags"])
        self.assertEqual(rows[0]["stage"], "banked")

    def test_03_effective_rate_under_floor_also_flags(self):
        res = self.sb.script("gig.py", "bank", "EffFloor Co",
                              "--work-type", "eval_rubric", "--rate-hr", "80",
                              "--effective-rate-hr", "42")
        self.assertExit(res, 0, res.stdout + res.stderr)
        rows = [r for r in self._rows(STAGES_REL) if r["platform"] == "EffFloor Co"]
        self.assertIn("below floor", rows[0]["red_flags"])

    def test_04_a16z_never_auto_resolves(self):
        """A16zNeverAuto: a16z_led=yes never resolves to APPLIED or DROPPED by itself; the row
        stays SCREENED with needs_his_call set, until his own `stage` call moves it."""
        self.sb.script("gig.py", "bank", "Zzalign",
                        "--work-type", "eval_rubric", "--rate-hr", "60")
        res = self.sb.script("gig.py", "screen", "Zzalign",
                              "--defense", "pass", "--a16z-led", "yes",
                              "--pe-owned", "no", "--nonpayment-reported", "no")
        self.assertExit(res, 0, res.stdout + res.stderr)
        rows = [r for r in self._rows(STAGES_REL) if r["platform"] == "Zzalign"]
        latest = rows[-1]
        self.assertEqual(latest["stage"], "screened")
        self.assertTrue(latest["needs_his_call"])
        self.assertNotIn(latest["stage"], ("applied", "dropped"))

    def test_05_hard_drop_only_on_defense_or_nonpayment(self):
        """HardDropDefense: a defense gate, or a confirmed non-payment report, is the only
        automatic hard drop; pe_owned alone (with a16z=no) requires his own stage call and stays
        screened."""
        self.sb.script("gig.py", "bank", "DefenseCo",
                        "--work-type", "expert_calls", "--rate-hr", "70")
        res = self.sb.script("gig.py", "screen", "DefenseCo",
                              "--defense", "drop", "--a16z-led", "no",
                              "--pe-owned", "no", "--nonpayment-reported", "no")
        self.assertExit(res, 0, res.stdout + res.stderr)
        rows = [r for r in self._rows(STAGES_REL) if r["platform"] == "DefenseCo"]
        self.assertEqual(rows[-1]["stage"], "dropped")

        self.sb.script("gig.py", "bank", "NonPayCo",
                        "--work-type", "expert_calls", "--rate-hr", "70")
        res2 = self.sb.script("gig.py", "screen", "NonPayCo",
                               "--defense", "pass", "--a16z-led", "no",
                               "--pe-owned", "no", "--nonpayment-reported", "yes")
        self.assertExit(res2, 0, res2.stdout + res2.stderr)
        rows2 = [r for r in self._rows(STAGES_REL) if r["platform"] == "NonPayCo"]
        self.assertEqual(rows2[-1]["stage"], "dropped")

        self.sb.script("gig.py", "bank", "PEOwnedCo",
                        "--work-type", "expert_calls", "--rate-hr", "70")
        res3 = self.sb.script("gig.py", "screen", "PEOwnedCo",
                               "--defense", "pass", "--a16z-led", "no",
                               "--pe-owned", "yes", "--nonpayment-reported", "no")
        self.assertExit(res3, 0, res3.stdout + res3.stderr)
        rows3 = [r for r in self._rows(STAGES_REL) if r["platform"] == "PEOwnedCo"]
        self.assertEqual(rows3[-1]["stage"], "screened", "pe_owned alone must not auto-drop")

    def test_06_stage_transitions_are_monotonic(self):
        self.sb.script("gig.py", "bank", "MonoCo",
                        "--work-type", "persona_build", "--rate-hr", "55")
        self.sb.script("gig.py", "screen", "MonoCo",
                        "--defense", "pass", "--a16z-led", "no",
                        "--pe-owned", "no", "--nonpayment-reported", "no")
        self.sb.script("gig.py", "stage", "MonoCo", "--stage", "applied")
        self.sb.script("gig.py", "stage", "MonoCo", "--stage", "active")
        # backward move refused
        res = self.sb.script("gig.py", "stage", "MonoCo", "--stage", "screened")
        self.assertNotEqual(res.returncode, 0, "a backward stage move must be refused")
        rows = [r for r in self._rows(STAGES_REL) if r["platform"] == "MonoCo"]
        self.assertEqual(rows[-1]["stage"], "active", "the refused move must not have written a row")

    def test_07_paid_may_repeat(self):
        self.sb.script("gig.py", "bank", "PaidCo",
                        "--work-type", "fractional_pm", "--rate-hr", "60")
        self.sb.script("gig.py", "screen", "PaidCo",
                        "--defense", "pass", "--a16z-led", "no",
                        "--pe-owned", "no", "--nonpayment-reported", "no")
        self.sb.script("gig.py", "stage", "PaidCo", "--stage", "applied")
        self.sb.script("gig.py", "stage", "PaidCo", "--stage", "active")
        res1 = self.sb.script("gig.py", "stage", "PaidCo", "--stage", "paid")
        self.assertExit(res1, 0, res1.stdout + res1.stderr)
        res2 = self.sb.script("gig.py", "stage", "PaidCo", "--stage", "paid")
        self.assertExit(res2, 0, "paid must be allowed to repeat: " + res2.stdout + res2.stderr)
        rows = [r for r in self._rows(STAGES_REL) if r["platform"] == "PaidCo"]
        self.assertEqual(sum(1 for r in rows if r["stage"] == "paid"), 2)


class GigIncomeTests(SandboxTest):
    SANDBOX_NAME = "gig_income"

    def _rows(self, rel):
        return [json.loads(l) for l in self.sb.lines(rel)]

    def test_01_income_computed_never_typed(self):
        """IncomeComputed: the CLI has no --earned flag at all; the stored row's earned always
        equals hours * rate_hr from the row's own fields."""
        res = self.sb.script("gig.py", "income", "IncomeCo",
                              "--week-of", "2026-09-08", "--hours", "40", "--rate-hr", "50")
        self.assertExit(res, 0, res.stdout + res.stderr)
        # The sandbox copies the live log, which already carries seeded rows; count only ours.
        rows = [r for r in self._rows(INCOME_REL) if r.get("company_key") == "incomeco"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["earned"], 40 * 50)
        # There is no --earned flag to even attempt to pass.
        help_res = self.sb.script("gig.py", "income", "--help")
        self.assertNotIn("--earned", help_res.stdout)

    def test_02_report_seven_day_math(self):
        """ReportSevenDayMath: gig.py report sums trailing-7-day hours/earned correctly with a
        denominator, off week_of rows relative to today."""
        # Reset the income log: this class shares one sandbox across tests (harness convention),
        # and test_01 already wrote a Zzwork row that would otherwise double-count here.
        self.sb.write(INCOME_REL, "")
        today = date.today()
        in_window = (today - timedelta(days=3)).isoformat()
        out_of_window = (today - timedelta(days=20)).isoformat()
        self.sb.script("gig.py", "income", "Zzwork",
                        "--week-of", in_window, "--hours", "40", "--rate-hr", "50")
        self.sb.script("gig.py", "income", "Zzwork",
                        "--week-of", out_of_window, "--hours", "10", "--rate-hr", "50")
        # Story 7 (2026-09-13): the gig lane is opt-in, off by default -- this test proves the
        # trailing-window math, so it opts in explicitly (see tests/test_gig_optin.py for the
        # switch's own off/on/malformed coverage).
        res = self.sb.script("gig.py", "report", "--json", GIG_LANE_ENABLED="1")
        self.assertExit(res, 0, res.stdout + res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data["trailing_7_days"]["earned"], 40 * 50)
        self.assertEqual(data["trailing_7_days"]["hours"], 40)
        self.assertEqual(data["trailing_7_days"]["denominator_days"], 7)
        # the 28-day window must include both rows
        self.assertEqual(data["trailing_28_days"]["hours"], 50)
        self.assertEqual(data["trailing_28_days"]["denominator_days"], 28)


if __name__ == "__main__":
    unittest.main()
