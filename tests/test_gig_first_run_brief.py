"""test_gig_first_run_brief.py -- red-first tests for gig slice 2 (plan-gig-slice2-2026-11-05.md,
rev 4): the first-run step in the GIG CARD block, and three byte-identical cases against slice 1.
Every platform is invented (Zzfake pattern).

The byte-identical cases run the slice 1 pair_brief.py and gig.py (read from git at BASE) beside the
tip and compare their output; a tree without that commit skips them, visibly.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import pair_brief  # noqa: E402

BASE = "96bcf33c"   # kit main at gig slice 1
TODAY = date(2026, 11, 4)
GATES = {"defense": "pass", "a16z_led": "no", "pe_owned": "no", "nonpayment_reported": "no"}


def _stage(platform, stage, flags=None):
    return {"ts": "2026-10-01T00:00:00+00:00", "company_key": platform.lower().replace(" ", "-"),
            "platform": platform, "stage": stage, "work_type": "eval_rubric", "rate_hr": 55,
            "effective_rate_hr": None, "onboarding_step": "", "gates": GATES,
            "red_flags": flags or [], "sources": [], "note": "", "needs_his_call": False}


def _income(platform, week_of="2026-10-20"):
    return {"ts": "t", "company_key": platform.lower().replace(" ", "-"), "opportunity": platform,
            "week_of": week_of, "hours": 20.0, "rate_hr": 55.0, "earned": 1100.0}


def _repo(rows=(), income=()):
    tmp = tempfile.mkdtemp(prefix="gig-first-run-")
    os.makedirs(os.path.join(tmp, "documents", "state"))
    os.symlink(SCRIPTS, os.path.join(tmp, "scripts"))
    for name, data in (("gig-stages.jsonl", rows), ("gig-income.jsonl", income)):
        with open(os.path.join(tmp, "documents", "state", name), "w") as fh:
            for r in data:
                fh.write(json.dumps(r) + "\n")
    return tmp


class _Lane(unittest.TestCase):
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


class FirstRunInTheBrief(_Lane):
    def test_empty_install_shows_step_1_in_place_of_none_to_show(self):
        t = pair_brief.render(today=TODAY, repo=_repo())
        block = t[t.index("GIG CARD"):t.index("PICKER QUESTION")]
        self.assertIn("Step 1 of 4, bank one", block)
        for k in ("NOW:", "NEXT:", "WHERE:", "MEANWHILE:"):
            self.assertIn(k, block)
        self.assertNotIn("none to show", t)

    def test_command_is_in_the_fence_once_and_not_in_the_block(self):
        t = pair_brief.render(today=TODAY, repo=_repo())
        block = t[t.index("GIG CARD"):t.index("COMMANDS")]
        self.assertNotIn("gig.py bank", block)
        self.assertEqual(t.count("gig.py bank"), 1)
        self.assertIn("gig.py bank", t.split("```")[1])

    def test_step_3_shows_the_label_and_lines_above_slice_1s_card_line(self):
        t = pair_brief.render(today=TODAY, repo=_repo([_stage("Zzfake Labs", "screened")]))
        block = t[t.index("GIG CARD"):t.index("COMMANDS")]
        self.assertIn("Step 3 of 4, apply", block)
        self.assertLess(block.index("Step 3 of 4"), block.index("Apply: Zzfake Labs"))
        fence = t.split("```")[1]
        self.assertEqual(fence.count("--stage applied"), 1)

    def test_as_json_carries_the_step(self):
        j = pair_brief.as_json(today=TODAY, repo=_repo())
        self.assertTrue(j["gig_first_run"]["label"].startswith("Step 1 of 4"))

    def test_with_an_income_row_there_is_no_step(self):
        repo = _repo([_stage("Zzwork Inc", "active")], [_income("Zzwork Inc")])
        t = pair_brief.render(today=TODAY, repo=repo)
        self.assertNotIn("Step ", t[t.index("GIG CARD"):t.index("COMMANDS")])
        self.assertIsNone(pair_brief.as_json(today=TODAY, repo=repo)["gig_first_run"])


def _base_tree():
    """A scripts dir with slice 1's pair_brief.py and gig.py, or None when git cannot supply them."""
    try:
        out = {}
        for name in ("pair_brief.py", "gig.py"):
            out[name] = subprocess.run(["git", "-C", REPO, "show", f"{BASE}:scripts/{name}"],
                                       capture_output=True, text=True, check=True).stdout
    except Exception:
        return None
    d = tempfile.mkdtemp(prefix="gig-base-scripts-")
    for f in os.listdir(SCRIPTS):
        if f not in out:
            try:
                os.symlink(os.path.join(SCRIPTS, f), os.path.join(d, f))
            except OSError:
                pass
    for name, text in out.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    return d


def _root_for(scripts_dir, repo):
    """A root laid out like the workspace (scripts/ beside its siblings) whose scripts/ is the one
    under test and whose documents/ is the fixture's, so each run reads only its own gig.py."""
    r = tempfile.mkdtemp(prefix="gig-cmp-")
    for entry in os.listdir(REPO):
        if entry not in ("scripts", "documents", ".git"):
            os.symlink(os.path.join(REPO, entry), os.path.join(r, entry))
    os.symlink(os.path.join(repo, "documents"), os.path.join(r, "documents"))
    os.symlink(scripts_dir, os.path.join(r, "scripts"))
    return r


def _render_with(scripts_dir, repo):
    r = _root_for(scripts_dir, repo)
    sd = os.path.join(r, "scripts")
    code = ("import sys; sys.path.insert(0, %r); import pair_brief, datetime; "
            "print(pair_brief.render(today=datetime.date(2026, 11, 4), repo=%r))" % (sd, r))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ))
    card = subprocess.run([sys.executable, os.path.join(sd, "gig.py"), "card", "--json", "--today", "2026-11-04"],
                          capture_output=True, text=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=r))
    return out.stdout, card.stdout


class ByteIdenticalToSlice1(_Lane):
    @classmethod
    def setUpClass(cls):
        cls.base = _base_tree()

    def _same(self, repo):
        if not self.base:
            self.skipTest(f"git cannot supply slice 1 ({BASE}) in this tree")
        tip = _render_with(SCRIPTS, repo)
        old = _render_with(self.base, repo)
        self.assertTrue(tip[0].strip() and old[0].strip(), "an empty render proves nothing")
        self.assertEqual(tip[0], old[0])
        self.assertEqual(tip[1], old[1])

    def test_lane_off(self):
        os.environ.pop("GIG_LANE_ENABLED", None)
        self._same(_repo([_stage("Zzfake Labs", "screened")], [_income("Zzfake Labs")]))

    def test_income_row_present_with_only_old_rows(self):
        self._same(_repo([_stage("Zzwork Inc", "active")], [_income("Zzwork Inc")]))

    def test_income_row_present_with_a_fresh_screened_row(self):
        self._same(_repo([_stage("Zzwork Inc", "active"), _stage("Zzfake Labs", "screened")],
                         [_income("Zzwork Inc")]))


if __name__ == "__main__":
    unittest.main()
