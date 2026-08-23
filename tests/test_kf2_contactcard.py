#!/usr/bin/env python3
"""Cluster A (kit#60 + kit#55 items 2 and 4).

kit#60: contact_card never read contact-roles.jsonl (see test_contact_card.py in main for the
card-level coverage; that file is not ported to the kit tree, so contact_card's own reader logic
is covered directly here where the kit's copy lives).

kit#55 #2: no terminal state for a draft the operator has decided against sending, so a retired
draft nagged pair_brief.stale_drafted() forever. Fixed by adding "discarded" (matching the naming
main already shipped for the identical mechanism) to log_linkedin_send's --status choices and
NOT_DELIVERED, plus the shell-mirrored copy in consistency-check.sh.

kit#55 #4: durability-check.sh measured "pushed offsite" against the branch's configured
upstream, which on a kit-tracking install IS the kit remote — so an operator's own commits (always
ahead of the kit by definition) were reported as "not pushed offsite" even when a real private
remote held everything.

⚠️ NEW FILE, NOT test_gates.py (collision note): log_linkedin_send.py is also touched by a
parallel cluster (company/name derivation). Keeping this cluster's coverage in its own file means
the two merges never fight over the same test-file diff.
"""
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

log_linkedin_send = importlib.import_module("log_linkedin_send")
pair_brief = importlib.import_module("pair_brief")
contact_card = importlib.import_module("contact_card")
contact_signals = importlib.import_module("contact_signals")


# ─────────────────────────────────────────────────────────────────────────────
# kit#55 #2 — the `discarded` terminal state
# ─────────────────────────────────────────────────────────────────────────────
class DiscardedStatusTests(unittest.TestCase):
    def test_discarded_is_an_accepted_status_choice(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "log_linkedin_send.py"), "--help"],
            capture_output=True, text=True)
        self.assertIn("discarded", proc.stdout,
                      "the --status flag's help text does not advertise 'discarded'")

    def test_discarded_is_in_not_delivered(self):
        self.assertIn("discarded", log_linkedin_send.NOT_DELIVERED)

    def test_discarded_is_not_in_unsent_statuses(self):
        """NARROWER ON PURPOSE. A discarded draft is TERMINAL — nothing is waiting on a human —
        unlike `drafted`/`staged`, which are still open. Confusing the two would make
        stale_drafted() nag about a decision already made."""
        self.assertNotIn("discarded", log_linkedin_send.UNSENT_STATUSES)

    def test_the_shell_mirrored_copy_matches(self):
        """NOT_DELIVERED cannot be imported into consistency-check.sh — it lives in a heredoc — so
        a hand-mirrored copy must be kept in sync by hand, and this is the test that catches drift
        between the two."""
        sh = open(os.path.join(SCRIPTS, "consistency-check.sh"), encoding="utf-8").read()
        m = re.search(r"NOT_DELIVERED\s*=\s*\{([^}]*)\}", sh)
        self.assertIsNotNone(m, "consistency-check.sh no longer defines NOT_DELIVERED")
        shell_set = set(re.findall(r'"([a-z]+)"', m.group(1)))
        self.assertEqual(shell_set, log_linkedin_send.NOT_DELIVERED,
                         "consistency-check.sh's NOT_DELIVERED drifted from log_linkedin_send.py's")

    def test_a_discarded_row_can_be_logged(self):
        tmp = tempfile.mkdtemp(prefix="kf2-discard-")
        try:
            os.makedirs(os.path.join(tmp, "documents"), exist_ok=True)
            log = os.path.join(tmp, "documents", "send-log.jsonl")
            env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp)
            proc = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "log_linkedin_send.py"),
                 "--path", log, "--rung", "warm", "--to", "linkedin:janedoe",
                 "--segment", "segment-a", "--status", "discarded", "--no-targets"],
                capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            rows = [json.loads(l) for l in open(log, encoding="utf-8") if l.strip()]
            self.assertEqual(rows[-1]["status"], "discarded")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# kit#55 #2 — end to end: a discarded row must stop nagging pair_brief.stale_drafted()
# ─────────────────────────────────────────────────────────────────────────────
class StaleDraftedSkipsDiscardedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kf2-stale-")
        os.makedirs(os.path.join(self.tmp, "documents"), exist_ok=True)
        self.log = os.path.join(self.tmp, "documents", "send-log.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rows):
        with open(self.log, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def test_a_stale_drafted_row_is_reported(self):
        self._write([{"to": "janedoe", "subject": "Hello", "date": "2026-01-01",
                     "status": "drafted", "company": "Zzz Co"}])
        out = pair_brief.stale_drafted(today="2026-06-01", repo=self.tmp)
        self.assertEqual(len(out), 1, "a genuinely stale drafted row was not reported")

    def test_a_discarded_row_stops_the_nag(self):
        """THE FIX. The operator decided against sending; the row must not haunt every future
        session-start brief. Two rows for the SAME message: the original stage, then the
        discard — the log is append-only, so a decision is a NEW row, not an edit."""
        self._write([
            {"to": "janedoe", "subject": "Hello", "date": "2026-01-01",
             "status": "drafted", "company": "Zzz Co"},
            {"to": "janedoe", "subject": "Hello", "date": "2026-01-01",
             "status": "discarded", "company": "Zzz Co"},
        ])
        out = pair_brief.stale_drafted(today="2026-06-01", repo=self.tmp)
        self.assertEqual(out, [], "a discarded draft is still nagging stale_drafted()")


# ─────────────────────────────────────────────────────────────────────────────
# kit#60 — contact_card reads contact-roles.jsonl (ROLE_CACHE)
# ─────────────────────────────────────────────────────────────────────────────
class ContactCardReadsRoleCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kf2-rolecache-")
        os.makedirs(os.path.join(self.tmp, "documents", "state"), exist_ok=True)
        self._real_cc_repo = contact_card.REPO
        self._real_cs_repo = contact_signals.REPO
        contact_card.REPO = contact_signals.REPO = self.tmp
        self._real_role_cache_path = contact_signals.ROLE_CACHE
        contact_signals.ROLE_CACHE = os.path.join(self.tmp, "documents", "state",
                                                   "contact-roles.jsonl")
        contact_signals._ROLE_CACHE = None

    def tearDown(self):
        import shutil
        contact_card.REPO = self._real_cc_repo
        contact_signals.REPO = self._real_cs_repo
        contact_signals.ROLE_CACHE = self._real_role_cache_path
        contact_signals._ROLE_CACHE = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_role(self, row):
        with open(contact_signals.ROLE_CACHE, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def test_grep_confirms_the_reader_is_wired_in(self):
        """The exact repro line from kit#60: `grep -c "record_role\\|ROLE_CACHE\\|role_records"
        scripts/contact_card.py` used to return 0. Pin it at 0 no longer."""
        src = open(os.path.join(SCRIPTS, "contact_card.py"), encoding="utf-8").read()
        self.assertIn("contact_signals", src)
        self.assertIn("verified_role", src)

    def test_a_verified_role_is_readable_through_contact_cards_own_helper(self):
        self._write_role({"name": "Jane Tester", "title": "VP Product", "company": "Zzz Co",
                          "still_there": True, "verified_on": "2026-08-15",
                          "source": "linkedin.com/in/jane-doe",
                          "source_type": "linkedin-live", "note": ""})
        row = contact_card._verified_role("Jane Tester")
        self.assertIsNotNone(row, "contact_card._verified_role did not find the recorded row")
        self.assertEqual(row["company"], "Zzz Co")

    def test_the_frozen_title_warning_is_conditional(self):
        """kit#60's second half: the warning must not be unconditional. `_role_is_fresh` is the
        gate; confirm it actually discriminates fresh from stale rather than always returning
        True (which would make the warning silently vanish for everyone) or always False (which
        would make the ported reader pointless)."""
        import datetime
        fresh = {"verified_on": datetime.date.today().isoformat()}
        stale = {"verified_on": "2020-01-01"}
        self.assertTrue(contact_card._role_is_fresh(fresh))
        self.assertFalse(contact_card._role_is_fresh(stale))
        self.assertFalse(contact_card._role_is_fresh(None))
        self.assertFalse(contact_card._role_is_fresh({}))


# ─────────────────────────────────────────────────────────────────────────────
# kit#55 #4 — durability-check.sh measures against the wrong remote
# ─────────────────────────────────────────────────────────────────────────────
class DurabilityCheckPrivateRemoteTests(unittest.TestCase):
    """A live git sandbox: a fake 'kit' remote (URL matching the canonical kit) plus a fake
    'origin' private remote, both pointed at real local bare repos so `git fetch`/`rev-list`
    work without touching the network. The bug this proves fixed: the check must name and use
    the PRIVATE remote, never the kit remote, however the branch's upstream is configured."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kf2-durability-")
        self.work = os.path.join(self.tmp, "work")
        # durability-check.sh does `cd "$(dirname "$0")/.."` at its own top, so it always
        # operates on ITS OWN parent directory regardless of the caller's cwd — a copy of the
        # script has to live inside the sandbox repo at scripts/durability-check.sh, the same
        # relative place it lives in a real install, or it silently checks the real repo instead.
        os.makedirs(os.path.join(self.work, "scripts"), exist_ok=True)
        import shutil as _shutil
        _shutil.copy(os.path.join(SCRIPTS, "durability-check.sh"),
                    os.path.join(self.work, "scripts", "durability-check.sh"))
        self.kit_bare = os.path.join(self.tmp, "kit-bare.git")
        self.origin_bare = os.path.join(self.tmp, "origin-bare.git")
        for d in (self.kit_bare, self.origin_bare):
            subprocess.run(["git", "init", "--bare", "-q", d], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.work], check=True)
        subprocess.run(["git", "-C", self.work, "config", "user.email", "test@example.com"])
        subprocess.run(["git", "-C", self.work, "config", "user.name", "Test"])
        open(os.path.join(self.work, "f.txt"), "w").write("1")
        subprocess.run(["git", "-C", self.work, "add", "f.txt"], check=True)
        subprocess.run(["git", "-C", self.work, "commit", "-q", "-m", "one"], check=True)
        subprocess.run(["git", "-C", self.work, "remote", "add", "kit", self.kit_bare], check=True)
        subprocess.run(["git", "-C", self.work, "remote", "add", "origin", self.origin_bare],
                       check=True)
        subprocess.run(["git", "-C", self.work, "push", "-q", "-u", "kit", "main"], check=True)
        subprocess.run(["git", "-C", self.work, "push", "-q", "origin", "main"], check=True)
        # Ahead of the KIT remote by one commit, but IN SYNC with origin (the private remote) —
        # exactly the state the reported bug measured wrong.
        open(os.path.join(self.work, "g.txt"), "w").write("1")
        subprocess.run(["git", "-C", self.work, "add", "g.txt"], check=True)
        subprocess.run(["git", "-C", self.work, "commit", "-q", "-m", "two"], check=True)
        subprocess.run(["git", "-C", self.work, "push", "-q", "origin", "main"], check=True)
        # Tracking branch points at the KIT remote — the exact real-world shape from the issue.
        subprocess.run(["git", "-C", self.work, "branch", "-q", "--set-upstream-to=kit/main"],
                       check=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self):
        script = os.path.join(self.work, "scripts", "durability-check.sh")
        return subprocess.run(["bash", script], cwd=self.work, capture_output=True, text=True)

    def test_reports_in_sync_against_the_private_remote_not_the_kit(self):
        out = self._run()
        section = out.stdout.split("Offsite backup")[1]
        self.assertIn("in sync with private remote 'origin'", section,
                      "did not correctly identify origin as the private remote")
        self.assertNotIn("not pushed", section,
                         "reported unpushed commits despite being fully synced with the private "
                         "remote — this is the exact false-positive the fix closes")

    def test_never_reports_an_ahead_count_against_the_kit_remote(self):
        """The regression itself: comparing against `@{u}` (which tracks kit/main here) would
        say '1 local commit(s) not pushed offsite'. That number must never appear."""
        out = self._run()
        section = out.stdout.split("Offsite backup")[1]
        self.assertNotRegex(section, r"\d+ local commit\(s\) not pushed",
                            "an ahead-count warning fired — it is comparing against the wrong remote")

    def test_names_the_remote_it_checked(self):
        """kit#55's suggested fix, verbatim: 'name the remote it checked in the pass/warn line.'"""
        out = self._run()
        self.assertIn("'origin'", out.stdout)


if __name__ == "__main__":
    unittest.main()
