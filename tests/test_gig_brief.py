"""test_gig_brief.py -- red-first tests for G2 (documents/state/gig-stories-2026-09-13.md):
the gig line in the daily brief, `gig_alternate()`, placed before `bug_alternate()`, never the
derived default.

Run standalone: python3 -m unittest tests.test_gig_brief -v
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import pair_brief  # noqa: E402


def _seed_gig_rows(repo):
    """Two screened platforms (one clean, one on hold), one active + income row, so a real
    `gig.py report --json` has something to report. Writes directly to the JSONL stores rather
    than shelling to gig.py, so this test does not depend on gig.py's CLI surface staying the
    same shape."""
    stages = os.path.join(repo, "documents", "state", "gig-stages.jsonl")
    income = os.path.join(repo, "documents", "state", "gig-income.jsonl")
    os.makedirs(os.path.dirname(stages), exist_ok=True)
    rows = [
        {"ts": "2026-09-13T00:00:00+00:00", "company_key": "zzwork", "platform": "Zzwork",
         "stage": "active", "work_type": "expert_calls", "rate_hr": 50, "effective_rate_hr": None,
         "onboarding_step": "", "gates": {}, "red_flags": [], "sources": [], "note": "",
         "needs_his_call": False},
        {"ts": "2026-09-13T00:01:00+00:00", "company_key": "workmate", "platform": "Workmate",
         "stage": "screened", "work_type": "eval_rubric", "rate_hr": 55, "effective_rate_hr": None,
         "onboarding_step": "", "gates": {}, "red_flags": [], "sources": [], "note": "",
         "needs_his_call": False},
        {"ts": "2026-09-13T00:02:00+00:00", "company_key": "holdco", "platform": "HoldCo",
         "stage": "screened", "work_type": "eval_rubric", "rate_hr": 60, "effective_rate_hr": None,
         "onboarding_step": "", "gates": {"a16z_led": "yes"},
         "red_flags": ["needs his call (a16z-led)"], "sources": [], "note": "",
         "needs_his_call": True},
    ]
    with open(stages, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    with open(income, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2026-09-13T00:00:00+00:00", "company_key": "zzwork",
                             "week_of": "2026-09-07", "hours": 20, "rate_hr": 50,
                             "earned": 1000.0}) + "\n")


class GigAlternateAbsentWhenNoRows(unittest.TestCase):
    def test_no_gig_rows_returns_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "documents", "state"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "scripts"), exist_ok=True)
            # gig.py needs to be reachable for a subprocess/import based reader; point at the
            # real scripts dir's gig.py by repo, with an empty state dir.
            self.assertIsNone(pair_brief.gig_alternate(repo=REPO_EMPTY_FIXTURE()))


def REPO_EMPTY_FIXTURE():
    """A throwaway repo shape with scripts/ symlinked to the real one and an empty state dir, so
    gig.py finds nothing to report."""
    import tempfile
    tmp = tempfile.mkdtemp(prefix="gig-brief-empty-")
    os.makedirs(os.path.join(tmp, "documents", "state"), exist_ok=True)
    os.symlink(SCRIPTS, os.path.join(tmp, "scripts"))
    return tmp


class GigAlternateNamesNextPlatform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp(prefix="gig-brief-named-")
        os.makedirs(os.path.join(cls.tmp, "documents", "state"), exist_ok=True)
        os.symlink(SCRIPTS, os.path.join(cls.tmp, "scripts"))
        _seed_gig_rows(cls.tmp)

    def setUp(self):
        # Story 7 (2026-09-13): the gig lane is opt-in, off by default. This test proves the
        # platform-naming behavior, so it opts in explicitly (see tests/test_gig_optin.py for the
        # switch's own off/on/malformed/default coverage).
        self._env_backup = os.environ.get("GIG_LANE_ENABLED")
        os.environ["GIG_LANE_ENABLED"] = "1"

    def tearDown(self):
        if self._env_backup is None:
            os.environ.pop("GIG_LANE_ENABLED", None)
        else:
            os.environ["GIG_LANE_ENABLED"] = self._env_backup

    def test_names_the_first_clean_screened_platform_and_trailing_7_days(self):
        alt = pair_brief.gig_alternate(repo=self.tmp)
        self.assertIsNotNone(alt)
        # HoldCo carries a hold flag (needs his call, a16z-led) and must be skipped; Workmate is
        # the first clean screened row.
        self.assertIn("Workmate", alt["description"] if "description" in alt else alt["state"])
        self.assertNotIn("HoldCo", alt["description"] if "description" in alt else alt["state"])
        self.assertIn("$", alt["state"])
        self.assertIn("h trailing 7 days", alt["label"])
        # never the 🧭 default badge
        self.assertNotEqual("🧭", alt["badge"])
        self.assertEqual("💼", alt["badge"])


class GigAlternateBeforeBugNeverDefault(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp(prefix="gig-brief-order-")
        os.makedirs(os.path.join(cls.tmp, "documents", "state"), exist_ok=True)
        os.makedirs(os.path.join(cls.tmp, "documents"), exist_ok=True)
        os.symlink(SCRIPTS, os.path.join(cls.tmp, "scripts"))
        _seed_gig_rows(cls.tmp)
        with open(os.path.join(cls.tmp, "documents", "BUG-LOG.md"), "w", encoding="utf-8") as fh:
            fh.write("## OPEN\n- [ ] **BUG-999** 🔴 **A test bug for ordering**\n\n## FIXED\n")

    def setUp(self):
        # Story 7 (2026-09-13): the gig lane is opt-in, off by default. This test proves the
        # ordering/never-default behavior with a gig alternate present, so it opts in explicitly
        # (see tests/test_gig_optin.py for the switch's own off/on/malformed/default coverage).
        self._env_backup = os.environ.get("GIG_LANE_ENABLED")
        os.environ["GIG_LANE_ENABLED"] = "1"

    def tearDown(self):
        if self._env_backup is None:
            os.environ.pop("GIG_LANE_ENABLED", None)
        else:
            os.environ["GIG_LANE_ENABLED"] = self._env_backup

    def test_default_unchanged_and_gig_sits_immediately_before_bug(self):
        # A clean derive() over a synthetic P3 state: no stale drafts/inbound/tripwires, closed
        # False so the send-shaped default fires -- same shape test_pair_gate.py's own P3 tests
        # use, but through derive()'s public seam so bug_alternate/gig_alternate both get a turn.
        state = {
            "today": "2026-09-13", "stale_drafted": [], "inbound": [], "tripwires": [],
            "sends_today": 0, "target": ("Acme Co · cold-boss rung", "rank"),
            "referred_gap": False, "warm_sends": 0, "referrals": [],
            "now": __import__("datetime").datetime(2026, 9, 13, 10, 0),
        }
        d = pair_brief.decide(state)
        default_before = d["default"]

        alt_gig = pair_brief.gig_alternate(repo=self.tmp)
        alt_bug = pair_brief.bug_alternate(repo=self.tmp)
        self.assertIsNotNone(alt_gig)
        self.assertIsNotNone(alt_bug)

        d2 = dict(d)
        galts = list(d2.get("alternates", [])) + [alt_gig]
        galts = galts + [alt_bug]
        d2["alternates"] = galts

        # the derived default itself is untouched by adding the gig alternate
        self.assertEqual(default_before, d["default"])
        self.assertNotIn("Gig lane", d["default"])

        labels = [a["label"] for a in d2["alternates"]]
        self.assertEqual(labels[-1], alt_bug["label"], "bug alternate must stay last")
        self.assertEqual(labels[-2], alt_gig["label"],
                          "gig alternate must sit immediately before the bug alternate")

    def test_derive_itself_places_gig_immediately_before_bug(self):
        """The real seam: derive() must append gig_alternate() before bug_alternate(), and the
        module's own never-default guard must keep 'Gig lane' out of d['default']."""
        d = pair_brief.derive(today="2026-09-13", repo=self.tmp)
        labels = [a["label"] for a in d["alternates"]]
        self.assertTrue(labels, "expected at least the gig and bug alternates")
        self.assertTrue(labels[-1].lower().startswith("bug"),
                         f"bug alternate must be last, got {labels[-1]!r}")
        self.assertIn("Gig lane", labels[-2], "gig alternate must sit immediately before bug")
        self.assertNotIn("Gig lane", d["default"], "gig status must never be the derived default")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class GigAlternateNamesTheOpportunity(unittest.TestCase):
    """2026-09-27: every status ask names the opportunity, never just the platform."""

    def setUp(self):
        import tempfile
        self._env = os.environ.get("GIG_LANE_ENABLED")
        os.environ["GIG_LANE_ENABLED"] = "1"
        self.tmp = tempfile.mkdtemp(prefix="gig-brief-opp-")
        os.makedirs(os.path.join(self.tmp, "documents", "state"), exist_ok=True)
        os.symlink(SCRIPTS, os.path.join(self.tmp, "scripts"))
        row = {"ts": "2026-09-13T00:00:00+00:00", "company_key": "multico", "platform": "MultiCo",
               "opportunity": "Reviewer", "stage": "screened", "work_type": "eval_rubric",
               "rate_hr": 55, "effective_rate_hr": None, "onboarding_step": "", "gates": {},
               "red_flags": [], "sources": [], "note": "", "needs_his_call": False}
        with open(os.path.join(self.tmp, "documents", "state", "gig-stages.jsonl"), "w") as fh:
            fh.write(json.dumps(row) + "\n")

    def tearDown(self):
        if self._env is None:
            os.environ.pop("GIG_LANE_ENABLED", None)
        else:
            os.environ["GIG_LANE_ENABLED"] = self._env

    def test_state_names_platform_and_opportunity(self):
        alt = pair_brief.gig_alternate(repo=self.tmp)
        self.assertIn("MultiCo: Reviewer", alt["state"])
