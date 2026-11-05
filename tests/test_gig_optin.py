#!/usr/bin/env python3
"""test_gig_optin.py -- red-first tests for story 7 (iteration 2, 2026-09-13): the gig lane

becomes opt-in, off by default. The owner's ruling, verbatim: "remember, the gig part of the
pipeline should be optional. the boss hunting pipeline is the core part." One switch --
`GIG_LANE_ENABLED` -- read by scripts/gig.py (`cmd_report`), the gig line in scripts/pair_brief.py
(`gig_alternate`) (the kit's page builder has no gig deck, so there is no `build_gigs` check here). Off is the
default: absent, empty, or malformed values must all read as off, never guessed on.

Edge cases covered: switch absent, malformed value, on with empty logs, off with logs present,
kit default (a fresh checkout with no env var set at all).

Run standalone: python3 -m unittest tests.test_gig_optin -v
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")

sys.path.insert(0, HERE)
from harness import SandboxTest  # noqa: E402

sys.path.insert(0, SCRIPTS)
import pair_brief  # noqa: E402

_gig_spec = importlib.util.spec_from_file_location("_gig_for_optin_test",
                                                     os.path.join(SCRIPTS, "gig.py"))
gig = importlib.util.module_from_spec(_gig_spec)
_gig_spec.loader.exec_module(gig)

STAGES_REL = os.path.join("documents", "state", "gig-stages.jsonl")
INCOME_REL = os.path.join("documents", "state", "gig-income.jsonl")


def _seed_gig_rows(repo):
    """One screened, clean platform plus an income row -- proof that logs existing is not, by
    itself, enough to produce output while the switch is off."""
    stages = os.path.join(repo, "documents", "state", "gig-stages.jsonl")
    income = os.path.join(repo, "documents", "state", "gig-income.jsonl")
    os.makedirs(os.path.dirname(stages), exist_ok=True)
    with open(stages, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": "2026-09-13T00:00:00+00:00", "company_key": "zzwork", "platform": "Zzwork",
            "stage": "screened", "work_type": "expert_calls", "rate_hr": 55,
            "effective_rate_hr": None, "onboarding_step": "", "gates": {}, "red_flags": [],
            "sources": [], "note": "", "needs_his_call": False,
        }) + "\n")
    with open(income, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2026-09-13T00:00:00+00:00", "company_key": "zzwork",
                             "week_of": "2026-09-07", "hours": 20, "rate_hr": 55,
                             "earned": 1100.0}) + "\n")


def _repo_fixture(with_rows=False):
    tmp = tempfile.mkdtemp(prefix="gig-optin-")
    os.makedirs(os.path.join(tmp, "documents", "state"), exist_ok=True)
    os.symlink(SCRIPTS, os.path.join(tmp, "scripts"))
    if with_rows:
        _seed_gig_rows(tmp)
    return tmp


# ── unit: gig.gig_lane_enabled() itself ─────────────────────────────────────────────────────

class GigLaneEnabledSwitch(unittest.TestCase):
    def test_absent_is_off(self):
        self.assertFalse(gig.gig_lane_enabled(env={}))

    def test_kit_default_is_off(self):
        # A fresh checkout ships no GIG_LANE_ENABLED at all in its real environment.
        env = dict(os.environ)
        env.pop("GIG_LANE_ENABLED", None)
        self.assertFalse(gig.gig_lane_enabled(env=env))

    def test_malformed_value_is_off(self):
        for bad in ("banana", "2", "-1", "TRU", " ", "onn", "yesish"):
            self.assertFalse(gig.gig_lane_enabled(env={"GIG_LANE_ENABLED": bad}),
                              f"{bad!r} must read as off, never guessed on")

    def test_recognized_on_values(self):
        for good in ("1", "true", "True", "yes", "YES", "on", "  on  "):
            self.assertTrue(gig.gig_lane_enabled(env={"GIG_LANE_ENABLED": good}))

    def test_recognized_off_values(self):
        for off in ("0", "false", "no", "off", ""):
            self.assertFalse(gig.gig_lane_enabled(env={"GIG_LANE_ENABLED": off}))


# ── scripts/gig.py: cmd_report respects the switch ──────────────────────────────────────────

class GigReportOffWithLogsPresent(SandboxTest):
    SANDBOX_NAME = "gig_optin_report"

    def test_off_with_logs_present_produces_no_queue_or_income(self):
        self.sb.script("gig.py", "bank", "Zzwork", "--work-type", "expert_calls",
                        "--rate-hr", "55")
        self.sb.script("gig.py", "income", "Zzwork", "--week-of", "2026-09-07",
                        "--hours", "20", "--rate-hr", "55")
        res = self.sb.script("gig.py", "report", "--json")  # switch not set -> off
        self.assertExit(res, 0, res.stdout + res.stderr)
        data = json.loads(res.stdout)
        self.assertFalse(data.get("enabled", False))
        self.assertFalse(any(rows for rows in data.get("queue", {}).values()))
        self.assertEqual(data["trailing_7_days"]["earned"], 0)
        self.assertEqual(data["trailing_28_days"]["hours"], 0)

    def test_malformed_switch_also_produces_no_output(self):
        self.sb.script("gig.py", "bank", "Zzwork", "--work-type", "expert_calls",
                        "--rate-hr", "55")
        res = self.sb.script("gig.py", "report", "--json", GIG_LANE_ENABLED="not-a-bool")
        self.assertExit(res, 0, res.stdout + res.stderr)
        data = json.loads(res.stdout)
        self.assertFalse(data.get("enabled", False))
        self.assertFalse(any(rows for rows in data.get("queue", {}).values()))


class GigReportOnWithEmptyLogs(SandboxTest):
    SANDBOX_NAME = "gig_optin_report_on_empty"

    def test_on_with_empty_logs_is_enabled_and_empty_not_broken(self):
        # The sandbox is an rsync of the live repo, so its own gig-stages/-income logs may carry
        # real banked rows already -- clear them so this test proves the empty-log shape, not
        # whatever happens to be live today.
        self.sb.write(STAGES_REL, "")
        self.sb.write(INCOME_REL, "")
        res = self.sb.script("gig.py", "report", "--json", GIG_LANE_ENABLED="1")
        self.assertExit(res, 0, res.stdout + res.stderr)
        data = json.loads(res.stdout)
        self.assertTrue(data.get("enabled", False))
        self.assertFalse(any(rows for rows in data.get("queue", {}).values()))
        self.assertEqual(data["trailing_7_days"]["earned"], 0)


class GigReportOnWithLogsPresent(SandboxTest):
    SANDBOX_NAME = "gig_optin_report_on"

    def test_on_with_logs_present_reports_them(self):
        self.sb.script("gig.py", "bank", "Zzwork", "--work-type", "expert_calls",
                        "--rate-hr", "55")
        res = self.sb.script("gig.py", "report", "--json", GIG_LANE_ENABLED="true")
        self.assertExit(res, 0, res.stdout + res.stderr)
        data = json.loads(res.stdout)
        self.assertTrue(data.get("enabled", False))
        self.assertTrue(any(rows for rows in data.get("queue", {}).values()))


# ── scripts/pair_brief.py: gig_alternate() respects the switch ─────────────────────────────

class GigAlternateOffWithRowsPresent(unittest.TestCase):
    def test_off_with_rows_present_returns_none(self):
        tmp = _repo_fixture(with_rows=True)
        env_backup = os.environ.pop("GIG_LANE_ENABLED", None)
        try:
            self.assertIsNone(pair_brief.gig_alternate(repo=tmp))
        finally:
            if env_backup is not None:
                os.environ["GIG_LANE_ENABLED"] = env_backup

    def test_malformed_switch_also_returns_none(self):
        tmp = _repo_fixture(with_rows=True)
        os.environ["GIG_LANE_ENABLED"] = "sure why not"
        try:
            self.assertIsNone(pair_brief.gig_alternate(repo=tmp))
        finally:
            del os.environ["GIG_LANE_ENABLED"]


class GigAlternateOnWithEmptyLogs(unittest.TestCase):
    def test_on_with_empty_logs_returns_none_not_broken(self):
        tmp = _repo_fixture(with_rows=False)
        os.environ["GIG_LANE_ENABLED"] = "1"
        try:
            self.assertIsNone(pair_brief.gig_alternate(repo=tmp))
        finally:
            del os.environ["GIG_LANE_ENABLED"]


class GigAlternateOnWithRowsPresent(unittest.TestCase):
    def test_on_with_rows_present_still_names_the_platform(self):
        tmp = _repo_fixture(with_rows=True)
        os.environ["GIG_LANE_ENABLED"] = "yes"
        try:
            alt = pair_brief.gig_alternate(repo=tmp)
            self.assertIsNotNone(alt)
            self.assertIn("Zzwork", alt["state"])
        finally:
            del os.environ["GIG_LANE_ENABLED"]


if __name__ == "__main__":
    unittest.main()
