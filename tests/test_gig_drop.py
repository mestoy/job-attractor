#!/usr/bin/env python3
"""Tests for gig.py's manual `dropped` stage (2026-09-27): `stage --stage dropped --reason`
is the app's Pass key and the way to retire a stale opportunity (the old zzmicro guess rows).
The log stays append-only; dropped is terminal and reachable from any stage.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import SandboxTest  # noqa: E402

STAGES_REL = os.path.join("documents", "state", "gig-stages.jsonl")


class ManualDrop(SandboxTest):
    SANDBOX_NAME = "gig_drop"

    def _rows(self):
        return [json.loads(l) for l in self.sb.lines(STAGES_REL)]

    def _bank(self, platform, opp=None, rate="55"):
        args = ["bank", platform, "--work-type", "eval_rubric", "--rate-hr", rate]
        if opp:
            args += ["--opportunity", opp]
        res = self.sb.script("gig.py", *args)
        self.assertExit(res, 0, res.stdout + res.stderr)

    def test_stage_accepts_dropped_with_reason(self):
        self._bank("DropMe")
        res = self.sb.script("gig.py", "stage", "DropMe", "--stage", "dropped",
                              "--reason", "passed")
        self.assertExit(res, 0, res.stdout + res.stderr)
        last = [r for r in self._rows() if r["platform"] == "DropMe"][-1]
        self.assertEqual(last["stage"], "dropped")
        self.assertEqual(last["drop_reason"], "passed")

    def test_dropped_requires_a_reason(self):
        self._bank("NoReason")
        res = self.sb.script("gig.py", "stage", "NoReason", "--stage", "dropped")
        self.assertNotEqual(res.returncode, 0)

    def test_reason_only_with_dropped(self):
        self._bank("ReasonOnly")
        res = self.sb.script("gig.py", "stage", "ReasonOnly", "--stage", "applied",
                              "--reason", "x")
        self.assertNotEqual(res.returncode, 0)

    def test_drop_from_active_and_log_stays_append_only(self):
        self._bank("Old", rate="90")
        self.sb.script("gig.py", "stage", "Old", "--stage", "applied")
        self.sb.script("gig.py", "stage", "Old", "--stage", "active")
        before = len(self._rows())
        res = self.sb.script("gig.py", "stage", "Old", "--stage", "dropped",
                              "--reason", "guessed rate, not the real gig")
        self.assertExit(res, 0, res.stdout + res.stderr)
        self.assertEqual(len(self._rows()), before + 1)

    def test_drop_is_terminal(self):
        self._bank("Gone")
        self.sb.script("gig.py", "stage", "Gone", "--stage", "dropped", "--reason", "passed")
        res = self.sb.script("gig.py", "stage", "Gone", "--stage", "applied")
        self.assertNotEqual(res.returncode, 0)

    def test_drop_one_opportunity_leaves_its_sibling(self):
        self._bank("Two", "Old")
        self._bank("Two", "Real")
        self.sb.script("gig.py", "stage", "Two", "--opportunity", "Old",
                        "--stage", "dropped", "--reason", "stale")
        rep = json.loads(self.sb.script("gig.py", "report", "--json", GIG_LANE_ENABLED="1").stdout)
        self.assertEqual([r["opportunity"] for r in rep["queue"]["dropped"] if r["platform"] == "Two"], ["Old"])
        self.assertEqual([r["opportunity"] for r in rep["queue"]["banked"] if r["platform"] == "Two"], ["Real"])


class Reopen(SandboxTest):
    """BUG-699: a mistaken drop can be reopened, forward-only, with his reason on a new row.
    Fictional platforms only (example.test); the log is never edited, only appended."""
    SANDBOX_NAME = "gig_reopen"

    def _rows(self):
        return [json.loads(l) for l in self.sb.lines(STAGES_REL)]

    def _for(self, platform):
        return [r for r in self._rows() if r["platform"] == platform]

    def _ok(self, *args):
        res = self.sb.script("gig.py", *args)
        self.assertExit(res, 0, res.stdout + res.stderr)
        return res

    def _bank(self, platform, rate="55"):
        self._ok("bank", platform, "--work-type", "eval_rubric", "--rate-hr", rate)

    def _screen(self, platform, nonpay="no", defense="pass"):
        return self.sb.script("gig.py", "screen", platform, "--defense", defense,
                              "--a16z-led", "no", "--pe-owned", "no",
                              "--nonpayment-reported", nonpay)

    def _drop(self, platform, why="passed"):
        self._ok("stage", platform, "--stage", "dropped", "--reason", why)

    def _reopen(self, platform, why="I misread the complaint"):
        return self.sb.script("gig.py", "reopen", platform, "--reason", why)

    def test_reopen_lands_at_the_stage_held_before_the_drop(self):
        for stage, expect in (("screened", "screened"), ("applied", "applied"),
                              ("active", "active"), ("paid", "active")):
            name = "Reopen " + stage.title()
            self._bank(name)
            if stage != "banked":
                self._ok("stage", name, "--stage", "screened")
            for s in ("applied", "active", "paid"):
                if stage in ("applied", "active", "paid") and s in ("applied", "active", "paid"):
                    self._ok("stage", name, "--stage", s)
                    if s == stage:
                        break
            self._drop(name)
            res = self._reopen(name)
            self.assertExit(res, 0, res.stdout + res.stderr)
            self.assertEqual(self._for(name)[-1]["stage"], expect, stage)

    def test_a_banked_drop_reopens_at_banked(self):
        self._bank("Reopen Banked")
        self._drop("Reopen Banked")
        self.assertExit(self._reopen("Reopen Banked"), 0)
        self.assertEqual(self._for("Reopen Banked")[-1]["stage"], "banked")

    def test_screen_hard_drop_reopens_at_banked_with_the_gate_label(self):
        self._bank("Hard Drop Co")
        self.assertExit(self._screen("Hard Drop Co", nonpay="yes"), 0)
        self.assertEqual(self._for("Hard Drop Co")[-1]["stage"], "dropped")
        self.assertNotIn("drop_reason", self._for("Hard Drop Co")[-1])
        before = len(self._rows())
        self.assertExit(self._reopen("Hard Drop Co"), 0)
        self.assertEqual(len(self._rows()), before + 1)
        row = self._for("Hard Drop Co")[-1]
        self.assertEqual(row["stage"], "banked")
        self.assertEqual(row["prior_drop_reason"], "screen: nonpayment_reported=yes")
        self.assertEqual(row["reopen_reason"], "I misread the complaint")
        self.assertEqual(row["reopened_from_ts"], self._for("Hard Drop Co")[-2]["ts"])
        self.assertEqual(row["gates"]["nonpayment_reported"], "yes")
        self.assertIn("[reopened ", row["note"])
        self.assertIn("I misread the complaint", row["note"])

    def test_defense_hard_drop_label(self):
        self._bank("Defense Co")
        self.assertExit(self._screen("Defense Co", defense="drop"), 0)
        self.assertExit(self._reopen("Defense Co"), 0)
        self.assertEqual(self._for("Defense Co")[-1]["prior_drop_reason"], "screen: defense=drop")

    def test_manual_drop_reason_is_carried_and_flags_stay(self):
        self._bank("Flag Co", rate="40")
        self._drop("Flag Co", "too low")
        self.assertExit(self._reopen("Flag Co"), 0)
        row = self._for("Flag Co")[-1]
        self.assertEqual(row["prior_drop_reason"], "too low")
        self.assertIn("below floor", row["red_flags"])

    def test_a_legacy_row_with_no_opportunity_key_is_found(self):
        legacy = {"ts": "2026-01-01T00:00:00+00:00", "company_key": "legacyexample",
                  "platform": "Legacy Example", "stage": "banked", "work_type": "eval_rubric",
                  "rate_hr": 45, "effective_rate_hr": None, "onboarding_step": "",
                  "gates": {"defense": None, "a16z_led": None, "pe_owned": None,
                            "nonpayment_reported": None},
                  "red_flags": ["below floor"], "sources": [], "note": "", "needs_his_call": False}
        drop = dict(legacy, ts="2026-01-02T00:00:00+00:00", opportunity="Legacy Example",
                    stage="dropped",
                    gates={"defense": "pass", "a16z_led": "no", "pe_owned": "no",
                           "nonpayment_reported": "yes"})
        with open(self.sb.path(STAGES_REL), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(legacy) + "\n" + json.dumps(drop) + "\n")
        self.assertExit(self._reopen("Legacy Example"), 0)
        self.assertEqual(self._for("Legacy Example")[-1]["stage"], "banked")

    def test_reopen_needs_a_reason(self):
        self._bank("No Why Co")
        self._drop("No Why Co")
        res = self.sb.script("gig.py", "reopen", "No Why Co")
        self.assertNotEqual(res.returncode, 0)
        res = self.sb.script("gig.py", "reopen", "No Why Co", "--reason", "  ")
        self.assertNotEqual(res.returncode, 0)

    def test_reopen_on_a_live_opportunity_is_refused(self):
        self._bank("Live Co")
        res = self._reopen("Live Co")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("nothing to reopen", res.stdout + res.stderr)

    def test_stage_still_cannot_leave_dropped(self):
        self._bank("Still Gone")
        self._drop("Still Gone")
        res = self.sb.script("gig.py", "stage", "Still Gone", "--stage", "screened")
        self.assertNotEqual(res.returncode, 0)

    def test_a_carried_hard_drop_gate_blocks_forward_until_a_rescreen(self):
        self._bank("Gate Co")
        self._screen("Gate Co", nonpay="yes")
        self.assertExit(self._reopen("Gate Co"), 0)
        n = len(self._rows())
        res = self.sb.script("gig.py", "stage", "Gate Co", "--stage", "applied")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("re-screen first", res.stdout + res.stderr)
        self.assertEqual(len(self._rows()), n)
        # a re-screen with the complaint resolved writes the gate fresh and moves it on
        self.assertExit(self._screen("Gate Co", nonpay="no"), 0)
        self.assertEqual(self._for("Gate Co")[-1]["stage"], "screened")
        self._ok("stage", "Gate Co", "--stage", "applied")
        self.assertEqual(self._for("Gate Co")[-1]["stage"], "applied")
        # the reopen row is still in the log
        self.assertTrue(any("reopened_from_ts" in r for r in self._for("Gate Co")))

    def test_a_rescreen_with_the_complaint_still_yes_drops_again(self):
        self._bank("Gate Again")
        self._screen("Gate Again", nonpay="yes")
        self.assertExit(self._reopen("Gate Again"), 0)
        self.assertExit(self._screen("Gate Again", nonpay="yes"), 0)
        self.assertEqual(self._for("Gate Again")[-1]["stage"], "dropped")

    def test_a_reopened_gate_row_can_still_be_dropped_with_a_reason(self):
        self._bank("Drop Again")
        self._screen("Drop Again", nonpay="yes")
        self.assertExit(self._reopen("Drop Again"), 0)
        self._drop("Drop Again", "second look, still no")
        self.assertEqual(self._for("Drop Again")[-1]["stage"], "dropped")
        self.assertExit(self._reopen("Drop Again", "changed my mind again"), 0)
        self.assertEqual(self._for("Drop Again")[-1]["reopen_reason"], "changed my mind again")

    def test_a_same_stage_note_is_not_a_forward_move(self):
        self._bank("Later Co")
        self._screen("Later Co", nonpay="yes")
        self.assertExit(self._reopen("Later Co"), 0)
        self._ok("stage", "Later Co", "--stage", "banked", "--note", "later")

    def test_report_marks_a_reopened_row(self):
        self._bank("Report Co")
        self._drop("Report Co")
        self.assertExit(self._reopen("Report Co", "wrong call"), 0)
        rep = json.loads(self.sb.script("gig.py", "report", "--json", GIG_LANE_ENABLED="1").stdout)
        row = [r for r in rep["queue"]["banked"] if r["platform"] == "Report Co"][0]
        self.assertTrue(row["reopened"])
        self.assertEqual(row["reopen_reason"], "wrong call")
        self.assertRegex(row["reopen_date"], r"^\d{4}-\d{2}-\d{2}$")
        txt = self.sb.script("gig.py", "report", GIG_LANE_ENABLED="1").stdout
        self.assertIn("reopened", txt)
        self.assertIn("wrong call", txt)


if __name__ == "__main__":
    unittest.main()
