#!/usr/bin/env python3
"""Slice B, the script half: scripts/screen_company.py runs the kit's own checks on one company and reports reasons. No network (a stub stands in for check_ats.py).
Run: PYTHONSAFEPATH=1 PYTHONPATH=. python3 -m unittest tests.test_screen_company
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import _fake_repo_sB as R  # noqa: E402

SCRIPT = os.path.join(KIT, "scripts", "screen_company.py")
STUB = os.path.join(HERE, "_ats_stub.py")


def screen(repo, company, slug=None, timeout=None):
    argv = [sys.executable, SCRIPT, "--repo", repo, "--company", company, "--ats-script", STUB]
    if slug:
        argv += ["--slug", slug]
    if timeout:
        argv += ["--ats-timeout", str(timeout)]
    env = dict(os.environ, JOBSEARCH_DATA_ROOT=repo, CLAUDE_PROJECT_DIR=repo)
    proc = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    return proc.returncode, json.loads(proc.stdout)


def by_key(out):
    return {c["key"]: c for c in out["checks"]}


class ScreenCompany(unittest.TestCase):
    def setUp(self):
        self.repo = R.make_repo()
        self.addCleanup(R.drop, self.repo)

    def test_a_clean_company_with_a_live_role_passes_with_reasons(self):
        code, out = screen(self.repo, R.CLEAN_LIVE)
        self.assertEqual(code, 0)
        c = by_key(out)
        self.assertEqual({k: c[k]["state"] for k in ("blocked", "dedup", "live_role")}, {"blocked": "clear", "dedup": "clear", "live_role": "clear"})
        self.assertIn("Fake Product Manager", c["live_role"]["reason"])
        self.assertFalse(out["blocked"])
        self.assertTrue(all(c[k]["reason"] for k in c), "every check carries a reason")

    def test_a_blocked_company_is_blocked_with_the_list_entry_as_the_reason_and_no_board_is_read(self):
        code, out = screen(self.repo, R.BLOCKED)
        c = by_key(out)
        self.assertTrue(out["blocked"])
        self.assertEqual(c["blocked"]["state"], "blocked")
        self.assertIn("defense mission", c["blocked"]["reason"])
        self.assertEqual(out["stop"], c["blocked"]["reason"])
        self.assertNotIn("live_role", c, "a stopped company's careers board is not read")

    def test_a_vetoed_industry_is_blocked(self):
        _c, out = screen(self.repo, R.VETOED)
        self.assertTrue(out["blocked"])
        self.assertIn("gambling", by_key(out)["blocked"]["reason"])

    def test_a_prior_contact_stops_it_and_names_the_record(self):
        _c, out = screen(self.repo, R.SENT)
        c = by_key(out)
        self.assertTrue(out["blocked"])
        self.assertEqual(c["dedup"]["state"], "blocked")
        self.assertRegex(c["dedup"]["reason"], r"prior contact")

    def test_no_live_role_is_a_radar_reach_not_a_stop(self):
        _c, out = screen(self.repo, R.CLEAN_RADAR)
        lr = by_key(out)["live_role"]
        self.assertEqual(lr["state"], "clear")
        self.assertIn("radar", lr["reason"])
        self.assertFalse(out["blocked"])

    def test_an_unreadable_board_is_unknown_and_says_when_it_will_be_known(self):
        _c, out = screen(self.repo, R.CLEAN_NOBOARD)
        lr = by_key(out)["live_role"]
        self.assertEqual(lr["state"], "unknown")
        self.assertTrue(lr["known"])
        self.assertFalse(out["blocked"])

    def test_an_ambiguous_board_is_unknown_not_a_guess(self):
        _c, out = screen(self.repo, "FAKE-AMBIG Name (NOT REAL)")
        lr = by_key(out)["live_role"]
        self.assertEqual(lr["state"], "unknown")
        self.assertIn("more than one", lr["reason"])

    def test_a_slow_board_check_times_out_as_unknown(self):
        _c, out = screen(self.repo, "FAKE-SLOW Co (NOT REAL)", timeout=1)
        lr = by_key(out)["live_role"]
        self.assertEqual(lr["state"], "unknown")
        self.assertIn("too long", lr["reason"])

    def test_a_name_with_no_card_names_what_is_unread_and_when(self):
        _c, out = screen(self.repo, R.CLEAN_LIVE)
        rs = by_key(out)["research"]
        self.assertEqual(rs["state"], "unknown")
        self.assertIn("culture", rs["reason"])
        self.assertIn("30 a day", rs["known"])

    def test_an_empty_blocked_list_and_no_vetoes_reads_unknown_never_a_quiet_pass(self):
        R.drop(self.repo)
        self.repo = R.make_repo(veto=False)
        os.remove(os.path.join(self.repo, "documents", "blocked-employers-list.md"))
        _c, out = screen(self.repo, R.CLEAN_LIVE)
        b = by_key(out)["blocked"]
        self.assertEqual(b["state"], "unknown")
        self.assertIn("blocked list", b["known"])

    def test_a_blocked_reason_carries_no_markdown(self):
        with open(os.path.join(self.repo, "documents", "blocked-employers-list.md"), "w", encoding="utf-8") as fh:
            fh.write("# Blocked\n\n- **FAKEBOLD Works**: **defense mission**, `ruled out`\n")
        _c, out = screen(self.repo, "FAKEBOLD Works")
        reason = by_key(out)["blocked"]["reason"]
        self.assertTrue(out["blocked"], out)
        self.assertNotRegex(reason, r"[*`]")
        self.assertIn("defense mission", reason)

    def test_a_company_with_a_card_names_its_unread_items_and_does_not_promise_a_read_the_page_never_starts(self):
        _c, out = screen(self.repo, "FAKE-CARD Co (NOT REAL)", slug="fake-card-co")
        rs = by_key(out)["research"]
        self.assertEqual(rs["state"], "unknown")
        self.assertTrue(rs["has_card"])
        self.assertTrue(rs["items"])
        self.assertNotIn("today's read", rs["known"])
        self.assertNotIn("queued behind", rs["known"])
        self.assertIn("asks the engine to read them when this card opens", rs["known"])

    def test_a_blank_name_is_refused(self):
        argv = [sys.executable, SCRIPT, "--repo", self.repo, "--company", "  "]
        self.assertEqual(subprocess.run(argv, capture_output=True, text=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
