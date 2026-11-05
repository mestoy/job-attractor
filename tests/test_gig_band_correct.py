#!/usr/bin/env python3
"""Tests for BUG-750 (a posted rate BAND) and BUG-749 (a `correct` path) in scripts/gig.py.

Runs the PRODUCTION script as a subprocess inside a sandbox (harness.Sandbox), the same shape as
test_gig.py. Every platform name here is obviously fake (a "ZZ" prefix and a "Test Co" suffix).

BUG-750: `bank` takes --rate-low and --rate-high. The below-floor flag fires only when the HIGH end
is under $50. A band whose high end EQUALS the floor clears it. A single --rate-hr behaves exactly as
before, and a row written before this change (no band fields) still reads.

BUG-749: `correct` appends a row that points at the row it supersedes (by 1-based row number in the
append-only log, never by timestamp, since two rows can share one). It skips the monotonic check on
purpose, because it exists to fix a stage that was never true. Readers take the latest row, so the
correction wins. A correction can itself be corrected. `reopen` never restores a superseded stage.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import SandboxTest  # noqa: E402

STAGES_REL = os.path.join("documents", "state", "gig-stages.jsonl")


class GigBandCorrectBase(SandboxTest):
    SANDBOX_NAME = "gig_band_correct"

    def _rows(self):
        return [json.loads(l) for l in self.sb.lines(STAGES_REL)]

    def _for(self, platform):
        return [r for r in self._rows() if r["platform"] == platform]

    def _bank(self, name, *extra, work_type="eval_rubric"):
        return self.sb.script("gig.py", "bank", name, "--work-type", work_type, *extra)

    def _stage(self, name, stage, *extra):
        return self.sb.script("gig.py", "stage", name, "--stage", stage, *extra)

    def _screen(self, name, **over):
        args = {"defense": "pass", "a16z-led": "no", "pe-owned": "no", "nonpayment-reported": "no"}
        args.update(over)
        flat = []
        for k, v in args.items():
            flat += ["--" + k, v]
        return self.sb.script("gig.py", "screen", name, *flat)

    def _correct(self, name, *extra):
        return self.sb.script("gig.py", "correct", name, *extra)

    def _report(self):
        res = self.sb.script("gig.py", "report", "--json", GIG_LANE_ENABLED="1")
        self.assertExit(res, 0, res.stdout + res.stderr)
        return json.loads(res.stdout)

    def _stage_in_report(self, platform, opportunity=None):
        data = self._report()
        for stage, rows in data["queue"].items():
            for r in rows:
                if r["platform"] == platform and (opportunity is None or r["opportunity"] == opportunity):
                    return stage
        return None


class RateBandTests(GigBandCorrectBase):
    """BUG-750."""

    def test_band_that_clears_the_floor_is_not_flagged(self):
        res = self._bank("ZZBand Clear Test Co", "--rate-low", "45", "--rate-high", "90")
        self.assertExit(res, 0, res.stdout + res.stderr)
        row = self._for("ZZBand Clear Test Co")[0]
        self.assertNotIn("below floor", row["red_flags"])
        self.assertEqual(row["rate_low"], 45.0)
        self.assertEqual(row["rate_high"], 90.0)

    def test_band_with_high_end_under_floor_is_flagged(self):
        res = self._bank("ZZBand Low Test Co", "--rate-low", "20", "--rate-high", "49")
        self.assertExit(res, 0, res.stdout + res.stderr)
        row = self._for("ZZBand Low Test Co")[0]
        self.assertIn("below floor", row["red_flags"])
        self.assertEqual(row["stage"], "banked", "a flag never drops the row")

    def test_band_with_high_end_equal_to_floor_is_not_flagged(self):
        res = self._bank("ZZBand Equal Test Co", "--rate-low", "30", "--rate-high", "50")
        self.assertExit(res, 0, res.stdout + res.stderr)
        self.assertNotIn("below floor", self._for("ZZBand Equal Test Co")[0]["red_flags"])

    def test_band_stores_rate_hr_as_the_low_end_for_old_readers(self):
        self._bank("ZZBand Legacy Test Co", "--rate-low", "45", "--rate-high", "90")
        self.assertEqual(self._for("ZZBand Legacy Test Co")[0]["rate_hr"], 45.0)

    def test_single_rate_below_floor_still_flags(self):
        self._bank("ZZSingle Low Test Co", "--rate-hr", "35")
        row = self._for("ZZSingle Low Test Co")[0]
        self.assertIn("below floor", row["red_flags"])
        self.assertNotIn("rate_low", row, "a single-rate row carries no band fields")

    def test_single_rate_at_or_above_floor_does_not_flag(self):
        self._bank("ZZSingle Ok Test Co", "--rate-hr", "50")
        self.assertNotIn("below floor", self._for("ZZSingle Ok Test Co")[0]["red_flags"])

    def test_no_rate_at_all_is_not_a_floor_violation(self):
        self._bank("ZZNoRate Test Co")
        row = self._for("ZZNoRate Test Co")[0]
        self.assertNotIn("below floor", row["red_flags"])
        self.assertIsNone(row["rate_hr"])

    def test_band_with_a_single_rate_is_refused(self):
        res = self._bank("ZZBoth Test Co", "--rate-hr", "60", "--rate-low", "45", "--rate-high", "90")
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(self._for("ZZBoth Test Co"), [], "a refused bank writes nothing")

    def test_low_above_high_is_refused(self):
        res = self._bank("ZZInverted Test Co", "--rate-low", "90", "--rate-high", "45")
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(self._for("ZZInverted Test Co"), [])

    def test_one_end_alone_is_refused(self):
        for flag in ("--rate-low", "--rate-high"):
            res = self._bank("ZZHalf Test Co", flag, "45")
            self.assertNotEqual(res.returncode, 0, flag)
        self.assertEqual(self._for("ZZHalf Test Co"), [])

    def test_zero_or_negative_band_is_refused(self):
        res = self._bank("ZZZero Test Co", "--rate-low", "0", "--rate-high", "10")
        self.assertNotEqual(res.returncode, 0)
        res = self._bank("ZZZero Test Co", "--rate-low", "-5", "--rate-high", "10")
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(self._for("ZZZero Test Co"), [])

    def test_effective_rate_still_overrides_a_band(self):
        self._bank("ZZBand Eff Test Co", "--rate-low", "45", "--rate-high", "90",
                   "--effective-rate-hr", "30")
        self.assertIn("below floor", self._for("ZZBand Eff Test Co")[0]["red_flags"])

    def test_screen_and_stage_carry_the_band_and_keep_the_flag_rule(self):
        self._bank("ZZBand Carry Test Co", "--rate-low", "45", "--rate-high", "90")
        self.assertExit(self._screen("ZZBand Carry Test Co"), 0)
        self.assertExit(self._stage("ZZBand Carry Test Co", "applied"), 0)
        last = self._for("ZZBand Carry Test Co")[-1]
        self.assertEqual((last["rate_low"], last["rate_high"]), (45.0, 90.0))
        self.assertNotIn("below floor", last["red_flags"])

    def test_banded_low_flagged_band_stays_flagged_through_a_stage(self):
        self._bank("ZZBand Stay Test Co", "--rate-low", "20", "--rate-high", "40")
        self.assertExit(self._stage("ZZBand Stay Test Co", "screened"), 0)
        last = self._for("ZZBand Stay Test Co")[-1]
        self.assertIn("below floor", last["red_flags"])
        self.assertEqual(last["rate_high"], 40.0)

    def test_old_row_without_band_fields_reads_through_report_and_stage(self):
        legacy = {"ts": "2026-09-01T00:00:00+00:00", "company_key": "zzlegacyoldtest",
                  "platform": "ZZLegacyOld Test Co", "opportunity": "ZZLegacyOld Test Co",
                  "stage": "banked", "work_type": "eval_rubric", "rate_hr": 35.0,
                  "effective_rate_hr": None, "onboarding_step": "", "gates": {},
                  "red_flags": [], "sources": [], "note": "", "needs_his_call": False}
        existing = self.sb.read(STAGES_REL)
        self.sb.write(STAGES_REL, existing + json.dumps(legacy) + "\n")
        self.assertEqual(self._stage_in_report("ZZLegacyOld Test Co"), "banked")
        self.assertExit(self._stage("ZZLegacyOld Test Co", "screened"), 0)
        last = self._for("ZZLegacyOld Test Co")[-1]
        self.assertIn("below floor", last["red_flags"], "a legacy low single rate still flags")
        self.assertNotIn("rate_low", last)


class CorrectTests(GigBandCorrectBase):
    """BUG-749."""

    SANDBOX_NAME = "gig_correct"

    def _to_applied(self, name):
        self.assertExit(self._bank(name, "--rate-hr", "80"), 0)
        self.assertExit(self._screen(name), 0)
        self.assertExit(self._stage(name, "applied"), 0)

    def test_correct_appends_a_row_pointing_at_the_row_it_supersedes(self):
        name = "ZZCorrect One Test Co"
        self._to_applied(name)
        before = len(self._rows())
        res = self._correct(name, "--stage", "screened", "--reason", "I never applied")
        self.assertExit(res, 0, res.stdout + res.stderr)
        rows = self._rows()
        self.assertEqual(len(rows), before + 1, "append-only: one new row, nothing edited")
        new = rows[-1]
        self.assertTrue(new["correction"])
        self.assertEqual(new["stage"], "screened")
        self.assertEqual(new["supersedes_stage"], "applied")
        self.assertEqual(new["supersedes_row"], before)
        self.assertEqual(new["supersedes_ts"], rows[before - 1]["ts"])
        self.assertEqual(new["correction_reason"], "I never applied")

    def test_readers_use_the_corrected_stage(self):
        name = "ZZCorrect Read Test Co"
        self._to_applied(name)
        self.assertEqual(self._stage_in_report(name), "applied")
        self._correct(name, "--stage", "screened", "--reason", "I never applied")
        self.assertEqual(self._stage_in_report(name), "screened")

    def test_the_log_keeps_both_rows(self):
        name = "ZZCorrect Both Test Co"
        self._to_applied(name)
        self._correct(name, "--stage", "screened", "--reason", "I never applied")
        stages = [r["stage"] for r in self._for(name)]
        self.assertEqual(stages, ["banked", "screened", "applied", "screened"])

    def test_a_correction_can_be_corrected_and_points_at_the_correction(self):
        name = "ZZCorrect Twice Test Co"
        self._to_applied(name)
        self.assertExit(self._correct(name, "--stage", "screened", "--reason", "never applied"), 0)
        n = len(self._rows())
        self.assertExit(self._correct(name, "--stage", "applied", "--reason", "I did apply after all"), 0)
        last = self._rows()[-1]
        self.assertEqual(last["supersedes_row"], n, "points at the correction, not the original")
        self.assertEqual(last["supersedes_stage"], "screened")
        self.assertTrue(last["correction"])
        self.assertEqual(self._stage_in_report(name), "applied")

    def test_row_flag_can_target_an_earlier_row_of_the_same_opportunity(self):
        name = "ZZCorrect Row Test Co"
        self._to_applied(name)
        rows = self._rows()
        screened_row = max(i for i, r in enumerate(rows, 1)
                           if r["platform"] == name and r["stage"] == "screened")
        res = self._correct(name, "--stage", "banked", "--reason", "bad screen",
                            "--row", str(screened_row))
        self.assertExit(res, 0, res.stdout + res.stderr)
        self.assertEqual(self._rows()[-1]["supersedes_row"], screened_row)

    def test_correcting_an_earlier_row_leaves_the_current_stage_alone(self):
        name = "ZZCorrect Hist Test Co"
        self._to_applied(name)
        rows = self._rows()
        screened_row = max(i for i, r in enumerate(rows, 1)
                           if r["platform"] == name and r["stage"] == "screened")
        res = self._correct(name, "--stage", "banked", "--reason", "the screen never happened",
                            "--row", str(screened_row))
        self.assertExit(res, 0, res.stdout + res.stderr)
        last = self._rows()[-1]
        self.assertEqual(last["stage"], "applied", "the true current stage must survive")
        self.assertEqual(last["corrected_stage"], "banked")
        self.assertEqual(last["supersedes_row"], screened_row)
        self.assertEqual(last["supersedes_stage"], "screened")
        self.assertEqual(self._stage_in_report(name), "applied")
        self.assertIn("current stage stays applied", res.stdout)

    def test_correcting_an_earlier_row_of_a_dropped_opportunity_keeps_the_drop(self):
        name = "ZZCorrect HistDrop Test Co"
        self._to_applied(name)
        self.assertExit(self._stage(name, "dropped", "--reason", "passed"), 0)
        rows = self._rows()
        applied_row = max(i for i, r in enumerate(rows, 1)
                          if r["platform"] == name and r["stage"] == "applied")
        self.assertExit(self._correct(name, "--stage", "screened", "--reason", "never applied",
                                      "--row", str(applied_row)), 0)
        last = self._rows()[-1]
        self.assertEqual(last["stage"], "dropped")
        self.assertEqual(last["drop_reason"], "passed")
        self.assertEqual(self._stage_in_report(name), "dropped")

    def test_undoing_a_drop_clears_the_drop_reason(self):
        name = "ZZCorrect Undrop Test Co"
        self._to_applied(name)
        self.assertExit(self._stage(name, "dropped", "--reason", "mis-dropped"), 0)
        self.assertExit(self._correct(name, "--stage", "applied", "--reason", "I never dropped it"), 0)
        last = self._rows()[-1]
        self.assertEqual(last["stage"], "applied")
        self.assertNotIn("drop_reason", last, "a live row must not carry a drop reason")
        self.assertEqual(self._stage_in_report(name), "applied")

    def test_row_flag_from_another_opportunity_is_refused(self):
        a, b = "ZZCorrect Own Test Co", "ZZCorrect Other Test Co"
        self._to_applied(a)
        self._to_applied(b)
        other_row = max(i for i, r in enumerate(self._rows(), 1) if r["platform"] == b)
        before = len(self._rows())
        res = self._correct(a, "--stage", "screened", "--reason", "x", "--row", str(other_row))
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(len(self._rows()), before)

    def test_row_number_out_of_range_is_refused(self):
        name = "ZZCorrect Range Test Co"
        self._to_applied(name)
        before = len(self._rows())
        for bad in ("0", "-1", "9999"):
            res = self._correct(name, "--stage", "screened", "--reason", "x", "--row", bad)
            self.assertNotEqual(res.returncode, 0, bad)
        self.assertEqual(len(self._rows()), before)

    def test_a_no_op_correction_is_refused(self):
        name = "ZZCorrect Noop Test Co"
        self._to_applied(name)
        before = len(self._rows())
        res = self._correct(name, "--stage", "applied", "--reason", "same")
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(len(self._rows()), before)

    def test_a_reason_is_required(self):
        name = "ZZCorrect Reason Test Co"
        self._to_applied(name)
        before = len(self._rows())
        res = self._correct(name, "--stage", "screened")
        self.assertNotEqual(res.returncode, 0)
        res = self._correct(name, "--stage", "screened", "--reason", "   ")
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(len(self._rows()), before)

    def test_an_unknown_platform_or_opportunity_is_refused(self):
        res = self._correct("ZZNever Banked Test Co", "--stage", "screened", "--reason", "x")
        self.assertNotEqual(res.returncode, 0)
        name = "ZZCorrect Opp Test Co"
        self._to_applied(name)
        res = self._correct(name, "--opportunity", "No Such Role", "--stage", "screened",
                            "--reason", "x")
        self.assertNotEqual(res.returncode, 0)

    def test_an_invalid_stage_is_refused(self):
        name = "ZZCorrect Stage Test Co"
        self._to_applied(name)
        res = self._correct(name, "--stage", "hired", "--reason", "x")
        self.assertNotEqual(res.returncode, 0)

    def test_a_forward_correction_past_a_hard_drop_gate_is_refused(self):
        name = "ZZCorrect Gate Test Co"
        self.assertExit(self._bank(name, "--rate-hr", "80"), 0)
        self.assertExit(self._screen(name, defense="drop"), 0)
        self.assertEqual(self._stage_in_report(name), "dropped")
        before = len(self._rows())
        res = self._correct(name, "--stage", "applied", "--reason", "x")
        self.assertNotEqual(res.returncode, 0, "a correction must not bypass the re-screen rule")
        self.assertEqual(len(self._rows()), before)

    def test_a_correction_to_dropped_sets_the_drop_reason(self):
        name = "ZZCorrect Drop Test Co"
        self._to_applied(name)
        res = self._correct(name, "--stage", "dropped", "--reason", "he passed")
        self.assertExit(res, 0, res.stdout + res.stderr)
        last = self._rows()[-1]
        self.assertEqual(last["stage"], "dropped")
        self.assertEqual(last["drop_reason"], "he passed")

    def test_the_next_normal_stage_moves_forward_from_the_corrected_stage(self):
        name = "ZZCorrect Fwd Test Co"
        self._to_applied(name)
        self._correct(name, "--stage", "screened", "--reason", "I never applied")
        res = self._stage(name, "applied")
        self.assertExit(res, 0, "moving forward from the corrected stage must be allowed")
        self.assertEqual(self._stage_in_report(name), "applied")

    def test_a_normal_backward_stage_move_is_still_refused(self):
        name = "ZZCorrect Back Test Co"
        self._to_applied(name)
        res = self._stage(name, "screened")
        self.assertNotEqual(res.returncode, 0, "only `correct` may move a stage backward")

    def test_reopen_does_not_restore_a_superseded_stage(self):
        name = "ZZCorrect Reopen Test Co"
        self._to_applied(name)
        self.assertExit(self._correct(name, "--stage", "screened", "--reason", "never applied"), 0)
        self.assertExit(self._stage(name, "dropped", "--reason", "passed"), 0)
        res = self.sb.script("gig.py", "reopen", name, "--reason", "changed my mind")
        self.assertExit(res, 0, res.stdout + res.stderr)
        self.assertEqual(self._rows()[-1]["stage"], "screened",
                         "the superseded 'applied' was never true, so reopen lands at 'screened'")

    def test_old_hand_written_correction_rows_still_read(self):
        legacy = {"ts": "2026-10-27T14:09:46+00:00", "company_key": "zzhandwrittentest",
                  "platform": "ZZHandWritten Test Co", "opportunity": "ZZHandWritten Test Co",
                  "stage": "screened", "work_type": "eval_rubric", "rate_hr": 60.0,
                  "effective_rate_hr": None, "onboarding_step": "", "gates": {},
                  "red_flags": [], "sources": [],
                  "note": "correction, not a stage move: his words", "needs_his_call": False}
        applied = dict(legacy, ts="2026-09-29T00:00:00+00:00", stage="applied", note="")
        existing = self.sb.read(STAGES_REL)
        self.sb.write(STAGES_REL, existing + json.dumps(applied) + "\n" + json.dumps(legacy) + "\n")
        self.assertEqual(self._stage_in_report("ZZHandWritten Test Co"), "screened")
        res = self._correct("ZZHandWritten Test Co", "--stage", "banked", "--reason", "x")
        self.assertExit(res, 0, res.stdout + res.stderr)
        self.assertEqual(self._rows()[-1]["supersedes_stage"], "screened")

    def test_correct_carries_the_band_and_flags_forward(self):
        name = "ZZCorrect Band Test Co"
        self.assertExit(self._bank(name, "--rate-low", "45", "--rate-high", "90"), 0)
        self.assertExit(self._screen(name), 0)
        self.assertExit(self._stage(name, "applied"), 0)
        self.assertExit(self._correct(name, "--stage", "screened", "--reason", "never applied"), 0)
        last = self._rows()[-1]
        self.assertEqual((last["rate_low"], last["rate_high"]), (45.0, 90.0))
        self.assertNotIn("below floor", last["red_flags"])


if __name__ == "__main__":
    unittest.main()
