"""test_gig_first_run.py -- red-first tests for gig slice 2 (plan-gig-slice2-2026-11-05.md, rev 4):
first_run_step() and `gig.py guide`, the guided first run on an empty install. Pure functions on
fixture report data; every platform is invented (Zzfake pattern).

Run standalone: python3 -m unittest tests.test_gig_first_run -v
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import gig  # noqa: E402

TODAY = date(2026, 11, 4)
GATES = {"defense": "pass", "a16z_led": "no", "pe_owned": "no", "nonpayment_reported": "no"}
LINES = ("now", "next", "where", "meanwhile")


def _row(platform, stage, rate=55, flags=None, note="", drop_reason="", opportunity=None):
    return {"platform": platform, "company_key": platform.lower().replace(" ", "-"),
            "opportunity": opportunity or platform, "rate_hr": rate, "rate_low": None,
            "rate_high": None, "next_step": gig.NEXT_STEP.get(stage, ""), "red_flags": flags or [],
            "drop_reason": drop_reason, "note": note, "work_type": "eval_rubric", "gates": GATES}


def _data(**stages):
    queue = {s: [] for s in gig.STAGES + ["dropped"]}
    queue.update(stages)
    return {"enabled": True, "queue": queue}


def _inc(platform="Zzwork Inc", week_of="2026-10-20"):
    return {"ts": "t", "company_key": platform.lower().replace(" ", "-"), "opportunity": platform,
            "week_of": week_of, "hours": 10.0, "rate_hr": 55.0, "earned": 550.0}


class EveryStepSaysFourLinesAndHasACommand(unittest.TestCase):
    def check(self, step, label_start):
        self.assertTrue(step["label"].startswith(label_start), step["label"])
        for k in LINES:
            self.assertTrue(step[k] and step[k].strip(), k)
        self.assertTrue(step["commands"])

    def test_no_rows_is_step_1_bank(self):
        s = gig.first_run_step(_data(), [])
        self.check(s, "Step 1 of 4")
        self.assertIn("gig.py bank", s["commands"][0])
        for w in sorted(gig.WORK_TYPES):
            self.assertIn(w, s["commands"][0])

    def test_all_banked_is_step_2_screen_with_the_exact_gate_words(self):
        s = gig.first_run_step(_data(banked=[_row("Zzfake Labs", "banked")]), [])
        self.check(s, "Step 2 of 4")
        self.assertIn("gig.py screen 'Zzfake Labs'", s["commands"][0])
        words = gig.screen_gate_words()
        for dest, flag in (("defense", "--defense"), ("a16z_led", "--a16z-led"),
                           ("pe_owned", "--pe-owned"), ("nonpayment_reported", "--nonpayment-reported")):
            self.assertIn(flag, s["commands"][0])
            for w in words[dest]:
                self.assertIn(w, s["now"] + s["commands"][0])

    def test_clean_screened_is_step_3_apply_with_the_card(self):
        s = gig.first_run_step(_data(screened=[_row("Zzfake Labs", "screened")]), [])
        self.check(s, "Step 3 of 4")
        self.assertEqual(s["card"]["action"], "Apply")
        self.assertIn("--stage applied", s["commands"][0])
        self.assertEqual(s["commands"], s["card"]["commands"])

    def test_flagged_screened_is_your_call_with_skip_only_never_correct(self):
        r = _row("Zzhold Co", "screened", flags=["needs his call (a16z-led)"])
        s = gig.first_run_step(_data(screened=[r]), [])
        self.check(s, "Step 2 of 4")
        self.assertIn("your call", s["label"])
        self.assertIn("needs his call (a16z-led)", s["now"])
        self.assertEqual(len(s["commands"]), 1)
        self.assertIn("--stage dropped --reason passed", s["commands"][0])
        self.assertFalse(any("correct" in c for c in s["commands"]))

    def test_applied_waits_and_prints_the_full_stage_active_command(self):
        s = gig.first_run_step(_data(applied=[_row("Zzfake Labs", "applied")]), [])
        self.check(s, "Step 4 of 4")
        self.assertIn("waiting on them", s["now"])
        self.assertEqual(s["commands"], ["python3 scripts/gig.py stage 'Zzfake Labs' --stage active"])

    def test_active_with_no_income_is_step_4_log_hours_with_the_card(self):
        s = gig.first_run_step(_data(active=[_row("Zzwork Inc", "active", rate=70)]), [])
        self.check(s, "Step 4 of 4")
        self.assertEqual(s["card"]["action"], "Log hours")
        self.assertIn("gig.py income 'Zzwork Inc'", s["commands"][0])

    def test_every_row_dropped_is_step_1_with_the_last_reason(self):
        d = _data(dropped=[_row("Zzgone Co", "dropped", drop_reason="rate too low")])
        s = gig.first_run_step(d, [])
        self.check(s, "Step 1 of 4")
        self.assertIn("Your last one dropped: rate too low", s["now"])


class Precedence(unittest.TestCase):
    def test_active_beats_applied_beats_screened_beats_banked(self):
        d = _data(banked=[_row("Zzb", "banked")], screened=[_row("Zzs", "screened")],
                  applied=[_row("Zza", "applied")], active=[_row("Zzact", "active")])
        self.assertEqual(gig.first_run_step(d, [])["label"].split(",")[0], "Step 4 of 4")
        d["queue"]["active"] = []
        s = gig.first_run_step(d, [])
        self.assertIn("waiting on them", s["now"])
        d["queue"]["applied"] = []
        self.assertTrue(gig.first_run_step(d, [])["label"].startswith("Step 3 of 4"))
        d["queue"]["screened"] = []
        self.assertTrue(gig.first_run_step(d, [])["label"].startswith("Step 2 of 4"))

    def test_a_clean_screened_row_beats_a_flagged_one(self):
        flagged = _row("Zzcheap", "screened", rate=40, flags=["below floor"])
        s = gig.first_run_step(_data(screened=[flagged, _row("Zzfake Labs", "screened")]), [])
        self.assertTrue(s["label"].startswith("Step 3 of 4"))
        self.assertEqual(s["card"]["platform"], "Zzfake Labs")


class TheFirstRunEnds(unittest.TestCase):
    def test_any_income_row_ends_it(self):
        d = _data(screened=[_row("Zzfake Labs", "screened")])
        self.assertIsNone(gig.first_run_step(d, [_inc()]))

    def test_lane_off_data_is_none(self):
        self.assertIsNone(gig.first_run_step({"enabled": False, "queue": {}}, []))


class PinnedToTheRealVocabulary(unittest.TestCase):
    def test_gate_words_equal_the_screen_parsers_choices(self):
        ap = __import__("argparse").ArgumentParser()
        sub = ap.add_subparsers()
        gig._add_screen(sub)
        screen = sub.choices["screen"]
        real = {a.dest: list(a.choices) for a in screen._actions if getattr(a, "choices", None)
                and a.dest in ("defense", "a16z_led", "pe_owned", "nonpayment_reported")}
        self.assertEqual(gig.screen_gate_words(), real)
        self.assertEqual(set(real), {"defense", "a16z_led", "pe_owned", "nonpayment_reported"})

    def test_step_1_lists_exactly_the_work_types(self):
        s = gig.first_run_step(_data(), [])
        listed = set(w for w in gig.WORK_TYPES if w in s["commands"][0])
        self.assertEqual(listed, set(gig.WORK_TYPES))


class GuideCommand(unittest.TestCase):
    def _run(self, lane_on, stages=(), income=()):
        with tempfile.TemporaryDirectory() as tmp:
            sd = os.path.join(tmp, "documents", "state")
            os.makedirs(sd)
            with open(os.path.join(sd, "gig-stages.jsonl"), "w") as fh:
                for r in stages:
                    fh.write(json.dumps(r) + "\n")
            with open(os.path.join(sd, "gig-income.jsonl"), "w") as fh:
                for r in income:
                    fh.write(json.dumps(r) + "\n")
            env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp)
            env.pop("GIG_LANE_ENABLED", None)
            if lane_on:
                env["GIG_LANE_ENABLED"] = "1"
            out = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "gig.py"), "guide"],
                                 capture_output=True, text=True, env=env, check=True).stdout
            js = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "gig.py"), "guide", "--json"],
                                capture_output=True, text=True, env=env, check=True).stdout
            return out, json.loads(js)

    def test_lane_off_says_how_to_turn_it_on_and_nothing_else(self):
        out, js = self._run(False)
        self.assertIn("export GIG_LANE_ENABLED=1", out)
        self.assertEqual(js["enabled"], False)

    def test_lane_on_empty_prints_step_1_and_the_four_lines(self):
        out, js = self._run(True)
        self.assertIn("Step 1 of 4", out)
        for k in ("NOW:", "NEXT:", "WHERE:", "MEANWHILE:"):
            self.assertIn(k, out)
        self.assertIn("gig.py bank", out)
        self.assertEqual(js["first_run"]["label"].split(",")[0], "Step 1 of 4")

    def test_with_an_income_row_the_first_run_is_over(self):
        row = {"ts": "t", "company_key": "zzwork-inc", "platform": "Zzwork Inc", "stage": "active",
               "rate_hr": 70, "red_flags": [], "gates": GATES}
        out, js = self._run(True, [row], [_inc()])
        self.assertIsNone(js["first_run"])
        self.assertIn("first run is over", out)


if __name__ == "__main__":
    unittest.main()
