"""test_gig_card.py -- red-first tests for gig slice 1 (plan-gig-slice1-2026-11-04.md): the gig
card and the income line, pure functions in gig.py on fixture report data. Every platform here is
invented (Zzfake pattern), so the same file can ship in the kit and the public CLI.

Run standalone: python3 -m unittest tests.test_gig_card -v
"""
import io
import json
import os
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
CLEAN_GATES = {"defense": "pass", "a16z_led": "no", "pe_owned": "no", "nonpayment_reported": "no"}


def _row(platform, stage, rate=55, flags=None, note="", opportunity=None, gates=None, work="eval_rubric"):
    return {"platform": platform, "company_key": platform.lower().replace(" ", "-"),
            "opportunity": opportunity or platform, "rate_hr": rate, "rate_low": None,
            "rate_high": None, "next_step": gig.NEXT_STEP.get(stage, ""), "red_flags": flags or [],
            "drop_reason": "", "note": note, "work_type": work,
            "gates": CLEAN_GATES if gates is None else gates}


def _data(**stages):
    queue = {s: [] for s in gig.STAGES + ["dropped"]}
    queue.update(stages)
    return {"enabled": True, "queue": queue,
            "trailing_7_days": {"hours": 0, "earned": 0, "denominator_days": 7},
            "trailing_28_days": {"hours": 0, "earned": 0, "denominator_days": 28}}


def _inc(platform, week_of, hours=10.0, rate=55.0, opportunity=None):
    return {"ts": "x", "company_key": platform.lower().replace(" ", "-"),
            "opportunity": opportunity or platform, "week_of": week_of, "hours": hours,
            "rate_hr": rate, "earned": round(hours * rate, 2)}


class ApplyCard(unittest.TestCase):
    def test_clean_screened_gives_apply_with_skip_second(self):
        d = _data(screened=[_row("Zzfake Labs", "screened", note="40 hr/wk")])
        c = gig.card(d, [], TODAY)
        self.assertEqual(c["action"], "Apply")
        self.assertEqual(c["platform"], "Zzfake Labs")
        self.assertEqual(c["pay"], "$55/hr")
        self.assertIn("40 hr/wk", c["time"])
        self.assertEqual(len(c["commands"]), 2)
        self.assertIn("--stage applied", c["commands"][0])
        self.assertIn("--stage dropped --reason passed", c["commands"][1])
        self.assertIn("Zzfake Labs", c["commands"][0])

    def test_time_not_recorded_when_the_note_names_no_hours(self):
        c = gig.card(_data(screened=[_row("Zzfake Labs", "screened", note="seems fine")]), [], TODAY)
        self.assertEqual(c["time"], "time: not recorded")

    def test_first_clean_screened_wins_over_a_held_one(self):
        held = _row("Zzhold Co", "screened", flags=["needs his call (a16z-led)"])
        clean = _row("Zzfake Labs", "screened")
        c = gig.card(_data(screened=[held, clean]), [], TODAY)
        self.assertEqual(c["platform"], "Zzfake Labs")
        self.assertEqual(c["action"], "Apply")

    def test_opportunity_rides_every_command_when_it_differs(self):
        r = _row("Zzfake Labs", "screened", opportunity="Rubric project")
        c = gig.card(_data(screened=[r]), [], TODAY)
        for cmd in c["commands"]:
            self.assertIn("--opportunity 'Rubric project'", cmd)

    def test_why_comes_from_the_record_only(self):
        c = gig.card(_data(screened=[_row("Zzfake Labs", "screened")]), [], TODAY)
        self.assertIn("above your $50 floor", c["why"])
        self.assertIn("eval rubric", c["why"])
        self.assertIn("defense", c["why"])
        bare = gig.card(_data(screened=[_row("Zzfake Labs", "screened", work=None, gates={})]), [], TODAY)
        self.assertNotIn("None", bare["why"])
        self.assertNotIn("defense", bare["why"])

    def test_below_floor_alone_is_a_hold_not_an_apply(self):
        r = _row("Zzcheap Co", "screened", rate=40, flags=["below floor"])
        c = gig.card(_data(screened=[r]), [], TODAY)
        self.assertEqual(c["action"], "your call")
        self.assertEqual(len(c["commands"]), 1)
        self.assertIn("--stage dropped --reason passed", c["commands"][0])
        self.assertIn("below your $50 floor", c["why"])

    def test_a_free_text_flag_alone_is_a_hold_too(self):
        r = _row("Zzodd Co", "screened", flags=["slow payer, per a forum"])
        c = gig.card(_data(screened=[r]), [], TODAY)
        self.assertEqual(c["action"], "your call")
        self.assertFalse(any("--stage applied" in x for x in c["commands"]))

    def test_a_flag_free_gig_still_beats_a_flagged_one(self):
        flagged = _row("Zzcheap Co", "screened", rate=40, flags=["below floor"])
        c = gig.card(_data(screened=[flagged, _row("Zzfake Labs", "screened")]), [], TODAY)
        self.assertEqual((c["platform"], c["action"]), ("Zzfake Labs", "Apply"))


class HeldCard(unittest.TestCase):
    def test_needs_his_call_is_your_call_with_skip_only(self):
        r = _row("Zzhold Co", "screened", flags=["needs his call (a16z-led)"])
        c = gig.card(_data(screened=[r]), [], TODAY)
        self.assertEqual(c["action"], "your call")
        self.assertEqual(len(c["commands"]), 1)
        self.assertIn("--stage dropped --reason passed", c["commands"][0])
        self.assertFalse(any("--stage applied" in x for x in c["commands"]))


class LogHoursCard(unittest.TestCase):
    def test_active_with_no_income_this_week_wins_over_screened(self):
        d = _data(screened=[_row("Zzfake Labs", "screened")], active=[_row("Zzwork Inc", "active", rate=70)])
        c = gig.card(d, [_inc("Zzwork Inc", "2026-10-20", 20, 70)], TODAY)
        self.assertEqual(c["action"], "Log hours")
        self.assertEqual(c["platform"], "Zzwork Inc")
        self.assertEqual(len(c["commands"]), 1)
        self.assertIn("gig.py income 'Zzwork Inc'", c["commands"][0])
        self.assertIn("--rate-hr 70", c["commands"][0])
        self.assertIn("--week-of <YYYY-MM-DD>", c["commands"][0])
        self.assertIn("--hours <hours>", c["commands"][0])

    def test_time_names_the_last_logged_week_honestly(self):
        d = _data(active=[_row("Zzwork Inc", "active", rate=70)])
        c = gig.card(d, [_inc("Zzwork Inc", "2026-10-20", 20, 70)], TODAY)
        self.assertIn("0", c["time"])
        self.assertIn("2026-10-20", c["time"])
        self.assertIn("20", c["time"])

    def test_active_with_income_this_week_does_not_win(self):
        d = _data(screened=[_row("Zzfake Labs", "screened")], active=[_row("Zzwork Inc", "active")])
        c = gig.card(d, [_inc("Zzwork Inc", "2026-11-03")], TODAY)
        self.assertEqual(c["platform"], "Zzfake Labs")
        self.assertEqual(c["action"], "Apply")

    def test_income_on_another_opportunity_does_not_count(self):
        d = _data(active=[_row("Zzwork Inc", "active", opportunity="Project B")])
        c = gig.card(d, [_inc("Zzwork Inc", "2026-11-03", opportunity="Project A")], TODAY)
        self.assertEqual(c["action"], "Log hours")

    def test_paid_with_no_income_this_week_also_gets_log_hours(self):
        c = gig.card(_data(paid=[_row("Zzpaid Co", "paid")]), [], TODAY)
        self.assertEqual(c["action"], "Log hours")


class NoCard(unittest.TestCase):
    def test_no_rows_gives_none(self):
        self.assertIsNone(gig.card(_data(), [], TODAY))

    def test_only_banked_and_dropped_gives_none(self):
        d = _data(banked=[_row("Zzfake Labs", "banked")], dropped=[_row("Zzgone Co", "dropped")])
        self.assertIsNone(gig.card(d, [], TODAY))


class IncomeLine(unittest.TestCase):
    def test_this_week_names_dollars_hours_and_next_gig(self):
        d = _data(screened=[_row("Zzfake Labs", "screened")])
        rows = [_inc("Zzwork Inc", "2026-11-03", 12, 70)]
        line = gig.income_line(d, rows, TODAY)
        self.assertEqual(line, "This week: $840 from 12 hours, next: Zzfake Labs")

    def test_never_says_zero_when_the_last_logged_week_is_outside_the_window(self):
        d = _data(active=[_row("Zzwork Inc", "active", rate=70)])
        rows = [_inc("Zzwork Inc", "2026-10-20", 20, 70)]
        line = gig.income_line(d, rows, TODAY)
        self.assertNotIn("$0 ", line)
        self.assertIn("$1400 from 20 hours", line)
        self.assertIn("week of 2026-10-20", line)
        self.assertIn("nothing logged this week", line)
        self.assertIn("next: Zzwork Inc", line)

    def test_no_income_ever_says_so_plainly(self):
        d = _data(screened=[_row("Zzfake Labs", "screened")])
        line = gig.income_line(d, [], TODAY)
        self.assertIn("nothing logged yet", line)
        self.assertIn("next: Zzfake Labs", line)

    def test_no_next_gig_leaves_the_clause_out(self):
        line = gig.income_line(_data(), [_inc("Zzwork Inc", "2026-11-03", 12, 70)], TODAY)
        self.assertEqual(line, "This week: $840 from 12 hours")


class CardCommandToday(unittest.TestCase):
    def test_today_flag_moves_the_window(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            sd = os.path.join(tmp, "documents", "state")
            os.makedirs(sd)
            r = {"ts": "t", "company_key": "zzwork-inc", "platform": "Zzwork Inc", "stage": "active",
                 "rate_hr": 70, "red_flags": [], "gates": CLEAN_GATES, "work_type": "eval_rubric"}
            open(os.path.join(sd, "gig-stages.jsonl"), "w").write(json.dumps(r) + "\n")
            open(os.path.join(sd, "gig-income.jsonl"), "w").write(json.dumps(_inc("Zzwork Inc", "2026-10-20")) + "\n")
            env = dict(os.environ, GIG_LANE_ENABLED="1", CLAUDE_PROJECT_DIR=tmp)
            script = os.path.join(REPO, "scripts", "gig.py")

            def run(day):
                out = subprocess.run([sys.executable, script, "card", "--json", "--today", day],
                                     capture_output=True, text=True, env=env, check=True).stdout
                return json.loads(out)
            self.assertIn("This week:", run("2026-10-22")["income_line"])
            self.assertIn("nothing logged this week", run("2026-11-04")["income_line"])


class CardCommand(unittest.TestCase):
    def _run(self, env_on):
        with tempfile.TemporaryDirectory() as tmp:
            sd = os.path.join(tmp, "documents", "state")
            os.makedirs(sd)
            with open(os.path.join(sd, "gig-stages.jsonl"), "w") as fh:
                r = {"ts": "t", "company_key": "zzfake-labs", "platform": "Zzfake Labs",
                     "stage": "screened", "work_type": "eval_rubric", "rate_hr": 55,
                     "red_flags": [], "gates": CLEAN_GATES, "note": "40 hr/wk"}
                fh.write(json.dumps(r) + "\n")
            open(os.path.join(sd, "gig-income.jsonl"), "w").close()
            old = {k: os.environ.get(k) for k in ("GIG_LANE_ENABLED", "CLAUDE_PROJECT_DIR")}
            try:
                os.environ["CLAUDE_PROJECT_DIR"] = tmp
                if env_on:
                    os.environ["GIG_LANE_ENABLED"] = "1"
                else:
                    os.environ.pop("GIG_LANE_ENABLED", None)
                import importlib
                importlib.reload(gig)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = gig.main(["card", "--json"])
                return rc, json.loads(buf.getvalue())
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                importlib.reload(gig)

    def test_lane_off_prints_enabled_false_only(self):
        rc, out = self._run(False)
        self.assertEqual((rc, out), (0, {"enabled": False}))

    def test_lane_on_prints_card_and_line(self):
        rc, out = self._run(True)
        self.assertEqual(rc, 0)
        self.assertTrue(out["enabled"])
        self.assertEqual(out["card"]["platform"], "Zzfake Labs")
        self.assertEqual(out["card"]["action"], "Apply")
        self.assertIn("next: Zzfake Labs", out["income_line"])


if __name__ == "__main__":
    unittest.main()
