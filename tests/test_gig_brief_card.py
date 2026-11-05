"""test_gig_brief_card.py -- red-first tests for gig slice 1 (plan-gig-slice1-2026-11-04.md): the
GIG CARD block and the income line in the sign-in brief. Every platform is invented (Zzfake
pattern) so the file can ship in the kit and the public CLI.

Run standalone: python3 -m unittest tests.test_gig_brief_card -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import pair_brief  # noqa: E402

TODAY = date(2026, 11, 4)
GATES = {"defense": "pass", "a16z_led": "no", "pe_owned": "no", "nonpayment_reported": "no"}


def _stage(platform, stage, rate=55, note=""):
    return {"ts": "2026-10-01T00:00:00+00:00", "company_key": platform.lower().replace(" ", "-"),
            "platform": platform, "stage": stage, "work_type": "eval_rubric", "rate_hr": rate,
            "effective_rate_hr": None, "onboarding_step": "", "gates": GATES, "red_flags": [],
            "sources": [], "note": note, "needs_his_call": False}


def _repo(rows=None, income=None):
    tmp = tempfile.mkdtemp(prefix="gig-card-brief-")
    os.makedirs(os.path.join(tmp, "documents", "state"))
    os.symlink(SCRIPTS, os.path.join(tmp, "scripts"))
    with open(os.path.join(tmp, "documents", "state", "gig-stages.jsonl"), "w") as fh:
        for r in rows or []:
            fh.write(json.dumps(r) + "\n")
    with open(os.path.join(tmp, "documents", "state", "gig-income.jsonl"), "w") as fh:
        for r in income or []:
            fh.write(json.dumps(r) + "\n")
    return tmp


def _income(platform, week_of, hours, rate):
    return {"ts": "t", "company_key": platform.lower().replace(" ", "-"), "opportunity": platform,
            "week_of": week_of, "hours": hours, "rate_hr": rate, "earned": round(hours * rate, 2)}


class _LaneEnv(unittest.TestCase):
    ON = True

    def setUp(self):
        self._old = os.environ.get("GIG_LANE_ENABLED")
        if self.ON:
            os.environ["GIG_LANE_ENABLED"] = "1"
        else:
            os.environ.pop("GIG_LANE_ENABLED", None)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GIG_LANE_ENABLED", None)
        else:
            os.environ["GIG_LANE_ENABLED"] = self._old


class CardAndLineInTheBrief(_LaneEnv):
    @classmethod
    def setUpClass(cls):
        cls.tmp = _repo([_stage("Zzfake Labs", "screened", note="40 hr/wk"), _stage("Zzwork Inc", "active", rate=70)],
                        [_income("Zzwork Inc", "2026-10-20", 20, 70)])

    def _text(self):
        return pair_brief.render(today=TODAY, repo=self.tmp)

    def test_income_line_sits_directly_under_the_next_block(self):
        # The kit's balancer block is the NEXT line plus its two detail lines; the income line
        # follows it with no blank between, and ahead of the method's read.
        lines = self._text().splitlines()
        nxt = [i for i, l in enumerate(lines) if l.strip().startswith("➡️  NEXT")]
        self.assertTrue(nxt, "the brief needs a NEXT line for this check")
        inc = [i for i, l in enumerate(lines) if l.startswith("Income: nothing logged this week; last logged week of 2026-10-20")]
        self.assertTrue(inc)
        self.assertTrue(all(lines[k].strip() for k in range(nxt[0], inc[0])), "no blank between NEXT and the line")
        self.assertLess(inc[0], next(i for i, l in enumerate(lines) if l.startswith("THE METHOD'S READ")))
        self.assertNotIn("$0 ", lines[inc[0]])

    def test_card_block_sits_between_alternates_and_commands(self):
        t = self._text()
        self.assertLess(t.index("ALTERNATES"), t.index("GIG CARD"))
        self.assertLess(t.index("GIG CARD"), t.index("COMMANDS"))
        block = t[t.index("GIG CARD"):t.index("COMMANDS")]
        self.assertIn("Log hours: Zzwork Inc", block)
        self.assertIn("$70/hr", block)
        self.assertIn("why it fits", block)

    def test_commands_are_in_the_fence_and_nowhere_in_option_text(self):
        t = self._text()
        fence = t.split("```")[1]
        self.assertIn("gig.py income 'Zzwork Inc'", fence)
        before_fence = t[:t.index("```")]
        self.assertNotIn("gig.py income", before_fence)
        question = t[t.index("PICKER QUESTION"):]
        self.assertNotIn("gig.py", question)

    def test_as_json_carries_both(self):
        j = pair_brief.as_json(today=TODAY, repo=self.tmp)
        self.assertEqual(j["gig_card"]["action"], "Log hours")
        self.assertIn("Income:", j["gig_income_line"])

    def test_no_card_says_so_in_one_line(self):
        # An empty install now gets the guided first run (slice 2); "none to show" is what remains
        # once the first run is over (an income row exists) and every gig has been dropped.
        dropped = dict(_stage("Zzgone Co", "dropped"), drop_reason="passed")
        tmp = _repo([dropped], [_income("Zzgone Co", "2026-10-20", 5, 55)])
        t = pair_brief.render(today=TODAY, repo=tmp)
        self.assertIn("Gig card: none to show; bank one with gig.py bank", t)


class LaneOffIsByteIdentical(_LaneEnv):
    ON = False

    def test_render_equals_a_brief_with_the_gig_code_absent(self):
        tmp = _repo([_stage("Zzfake Labs", "screened")], [_income("Zzfake Labs", "2026-10-20", 20, 55)])
        with_code = pair_brief.render(today=TODAY, repo=tmp)
        with mock.patch.object(pair_brief, "_gig_card_pair", return_value=(None, None, False, None)):
            without = pair_brief.render(today=TODAY, repo=tmp)
        self.assertEqual(with_code, without)
        self.assertNotIn("GIG CARD", with_code)

    def test_as_json_keys_are_none(self):
        j = pair_brief.as_json(today=TODAY, repo=_repo([_stage("Zzfake Labs", "screened")]))
        self.assertIn("gig_card", j)
        self.assertIsNone(j["gig_card"])
        self.assertIsNone(j["gig_income_line"])


if __name__ == "__main__":
    unittest.main()
