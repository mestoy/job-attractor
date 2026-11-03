#!/usr/bin/env python3
"""Tests for partner-starter/scripts/build_rate.py.

Two metrics, two failure modes to pin down:

  1. notes_built must count one row per staged note from the send log and drop
     the stale `drafted` row that sits beside an already-delivered row for the
     same company.

  2. transitions_from_git must count a card ENTERING BUILD from git history and
     must NOT be fooled by the prose that breaks a naive keyword count: "BUILD
     gate", "build the send", "BUILD floor", "no BUILD row", "card-build". A
     decision-ledger file full of those phrases is planted in the fixture
     repo; the transition count must be identical with and without it.

The fixture is a real git repo built in a temp dir with pinned author dates, so
the `git log --follow` / `git cat-file` path under test is the production one.
Nothing here touches this kit's own tree except one read-only presence check.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, KIT_SCRIPTS)
import build_rate  # noqa: E402

# Exactly the shape of phrases that make a naive keyword count read as
# ever-ruled-BUILD.
CONTAMINATED_PHRASES = [
    "BUILD gate",
    "build the send",
    "BUILD floor",
    "cleared the BUILD gate before staging",
    "BUILD floor is 70 mean",
    "no BUILD row, no staging",
    "Dedup-at-card-build bug draft (seat 02, 2026-09-09)",
    "returns as BUILD candidate (Owner, ruled 2026-09-10)",
    "STATUS: 🟣 PARK (Owner — body banked, no BUILD row, no staging)",
]

REAL_VERDICT_LINES = [
    "# X · payments · STATUS: 🟢 BUILD (Owner, ruled 2026-09-10, ledger e4) · boss Y",
    "# X · payments · STATUS: 🔵 BUILD (Owner, ruled BUILD 2026-09-10) · LIVE",
    "# X · applied-ai · STATUS: BUILD (Owner, 2026-09-09 ~17:40 ET card picker)",
    "# X · applied-ai/insurtech · LIVE · panel 78/74/76 mean 76 · BUILD (Owner, 2026-09-08)",
    "# X · applied-ai · STATUS: ✅ SENT 2026-09-09 (was BUILD, Owner card picker)",
]


def _git(repo, *args, **kw):
    env = dict(os.environ)
    env.update(kw.pop("env", {}))
    env.setdefault("GIT_AUTHOR_NAME", "T")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.invalid")
    env.setdefault("GIT_COMMITTER_NAME", "T")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.invalid")
    res = subprocess.run(["git"] + list(args), cwd=repo, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), res.stderr))
    return res.stdout


def _commit(repo, day, msg):
    stamp = "%sT12:00:00+00:00" % day
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg,
         env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})


def _write(repo, rel, text):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class VerdictDetectorTest(unittest.TestCase):
    def test_real_verdict_forms_are_detected(self):
        for line in REAL_VERDICT_LINES:
            self.assertTrue(build_rate.is_build_verdict(line),
                            "should be a BUILD verdict: %r" % line)

    def test_contaminated_phrases_are_never_verdicts(self):
        for phrase in CONTAMINATED_PHRASES:
            self.assertFalse(
                build_rate.is_build_verdict("# Acme · payments · " + phrase),
                "ledger/prose phrase must NOT count as a verdict: %r" % phrase)

    def test_empty_and_plain_lines(self):
        self.assertFalse(build_rate.is_build_verdict(""))
        self.assertFalse(build_rate.is_build_verdict(None))
        self.assertFalse(build_rate.is_build_verdict("# Acme · payments · RADAR"))


class FixtureRepoMixin(object):
    """A git repo whose BUILD transitions are known by construction.

    Timeline (author dates pinned):
      09-01  a-card: RADAR                      | h-card: BUILD  (before window)
      09-02  a-card -> BUILD                    | b-card born BUILD
             c-card: RADAR forever
             d-card: header says "BUILD gate"   (contamination)
             e-card: header says "no BUILD row" (negation)
             f-card: "Dedup-at-card-build ..."  (lowercase prose)
      09-03  g-card: SENT (was BUILD)           | a-card renamed (rename survival)
      Plus documents/decision-ledger.jsonl stuffed with contaminated prose.

    In-window (since 09-02) transitions: a, b, g, i -> 4
    Before window: h -> 1
    """

    SINCE = "2026-09-02"

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="build_rate_fx_")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.name", "T")
        _git(self.repo, "config", "user.email", "t@example.invalid")

        _write(self.repo, "documents/state/a-card-2026-09-01.md",
               "# Alpha · payments · STATUS: 🟡 RADAR · boss A · 2026-09-01\nbody\n")
        _write(self.repo, "documents/state/h-card-2026-09-01.md",
               "# Hotel · payments · STATUS: 🟢 BUILD (Owner, ruled 2026-09-01) · boss H\nbody\n")
        _commit(self.repo, "2026-09-01", "snapshot")

        _write(self.repo, "documents/state/a-card-2026-09-01.md",
               "# Alpha · payments · STATUS: 🟢 BUILD (Owner, ruled 2026-09-02, ledger e4) · boss A\nbody\n")
        _write(self.repo, "documents/state/b-card-2026-09-02.md",
               "# Bravo · fintech · STATUS: 🔵 BUILD (Owner, ruled BUILD 2026-09-02) · LIVE\nbody\n")
        _write(self.repo, "documents/state/c-card-2026-09-02.md",
               "# Charlie · payments · STATUS: 🟡 RADAR · boss C · 2026-09-02\nbody\n")
        # j-card goes LIVE -> SENT without a BUILD header ever being committed.
        # Its BUILD entry is real but UNOBSERVABLE; it must be reported as such.
        _write(self.repo, "documents/state/j-card-2026-09-02.md",
               "# Juliet · fintech · STATUS: LIVE · boss J · 2026-09-02\nbody\n")
        _write(self.repo, "documents/state/d-card-2026-09-02.md",
               "# Delta · payments · STATUS: 🟡 RADAR (cleared the BUILD gate but held at the BUILD floor)\nbody\n")
        _write(self.repo, "documents/state/e-card-2026-09-02.md",
               "# Echo · fintech · STATUS: 🟣 PARK (Owner — body banked, no BUILD row, no staging)\nbody\n")
        _write(self.repo, "documents/state/f-card-build-bug-2026-09-02.md",
               "# Dedup-at-card-build bug draft (seat 02, 2026-09-02)\nbody\n")
        _write(self.repo, "documents/decision-ledger.jsonl",
               "".join(json.dumps({"company": "Co%d" % i,
                                   "note": "cleared the BUILD gate; build the send; BUILD floor is 70"}) + "\n"
                       for i in range(139)))
        _commit(self.repo, "2026-09-02", "snapshot")

        # i-card: ruled 09-02 in its PROSE but not committed until 09-03. The
        # counted date must be the COMMIT date (09-03); the prose date is
        # advisory only, and the gap is the commit lag.
        _write(self.repo, "documents/state/i-card-2026-09-02.md",
               "# India · payments · STATUS: 🔵 BUILD (Owner, ruled BUILD 2026-09-02; STAGED) · LIVE\nbody\n")
        _write(self.repo, "documents/state/g-card-2026-09-03.md",
               "# Golf · insurtech · STATUS: ✅ SENT 2026-09-03 (was BUILD, Owner card picker) · boss G\nbody\n")
        _write(self.repo, "documents/state/j-card-2026-09-02.md",
               "# Juliet · fintech · STATUS: ✅ SENT 2026-09-03 (was LIVE) · boss J\nbody\n")
        _git(self.repo, "mv",
             "documents/state/a-card-2026-09-01.md",
             "documents/state/alpha-card-2026-09-01.md")
        _commit(self.repo, "2026-09-03", "snapshot")

        self._write_send_log()

    def _write_send_log(self, rows=None):
        if rows is None:
            rows = [
                # 09-02: three real notes
                {"date": "2026-09-02", "company": "One", "status": "sent"},
                {"date": "2026-09-02", "company": "Two", "status": "sent"},
                {"date": "2026-09-02", "company": "Three", "status": "replied"},
                # 09-03: two real notes + one stale drafted duplicate
                {"date": "2026-09-03", "company": "Acme", "status": "drafted"},
                {"date": "2026-09-03", "company": "Acme", "status": "sent"},
                {"date": "2026-09-03", "company": "Four", "status": "sent"},
                # 09-04: a drafted row with NO delivered sibling -- a real built note
                {"date": "2026-09-04", "company": "Zzyzx Sprockets", "status": "drafted"},
                {"date": "2026-09-04", "company": "Five", "status": "bounced"},
                # outside the window
                {"date": "2026-08-01", "company": "Old", "status": "sent"},
            ]
        _write(self.repo, "documents/send-log.jsonl",
               "".join(json.dumps(r) + "\n" for r in rows))


class NotesBuiltTest(FixtureRepoMixin, unittest.TestCase):
    def test_counts_by_day_excluding_duplicate_drafts(self):
        rep = build_rate.notes_built(self.repo, "2026-09-02", "2026-09-04")
        self.assertEqual(rep["by_day"],
                         {"2026-09-02": 3, "2026-09-03": 2, "2026-09-04": 2})
        self.assertEqual(rep["total"], 7)

    def test_raw_counts_are_returned_so_the_arithmetic_is_inspectable(self):
        rep = build_rate.notes_built(self.repo, "2026-09-02", "2026-09-04")
        self.assertEqual(rep["raw_by_day"]["2026-09-03"], 3)
        self.assertEqual(rep["by_day"]["2026-09-03"], 2)
        self.assertEqual(rep["raw_total"] - rep["total"], rep["excluded_count"])

    def test_the_excluded_row_is_named_not_just_counted(self):
        rep = build_rate.notes_built(self.repo, "2026-09-02", "2026-09-04")
        self.assertEqual(rep["excluded_count"], 1)
        self.assertEqual(rep["excluded_duplicate_drafts"][0]["company"], "Acme")
        self.assertEqual(rep["excluded_duplicate_drafts"][0]["status"], "drafted")

    def test_a_lone_drafted_row_is_still_a_built_note(self):
        rep = build_rate.notes_built(self.repo, "2026-09-04", "2026-09-04")
        self.assertEqual(rep["total"], 2)  # Zzyzx Sprockets drafted + Five bounced
        self.assertEqual(rep["excluded_count"], 0)

    def test_window_bounds_are_inclusive_and_exclude_outside_rows(self):
        rep = build_rate.notes_built(self.repo, "2026-09-02", "2026-09-04")
        self.assertNotIn("2026-08-01", rep["raw_by_day"])
        self.assertEqual(rep["window_days"], 3)

    def test_method_string_names_its_source_and_granularity(self):
        rep = build_rate.notes_built(self.repo, "2026-09-02", "2026-09-04")
        self.assertIn("send-log.jsonl", rep["method"])
        self.assertIn("day", rep["method"].lower())


class TransitionsFromGitTest(FixtureRepoMixin, unittest.TestCase):
    def test_counts_cards_entering_build(self):
        rep = build_rate.transitions_from_git(self.repo, self.SINCE)
        cards = sorted(os.path.basename(t["card"]) for t in rep["transitions"])
        self.assertEqual(cards, ["alpha-card-2026-09-01.md",
                                 "b-card-2026-09-02.md",
                                 "g-card-2026-09-03.md",
                                 "i-card-2026-09-02.md"])
        self.assertEqual(rep["total"], 4)
        self.assertEqual(rep["by_day"], {"2026-09-02": 2, "2026-09-03": 2})

    def test_rename_is_followed_so_the_transition_keeps_its_original_date(self):
        rep = build_rate.transitions_from_git(self.repo, self.SINCE)
        alpha = [t for t in rep["transitions"]
                 if t["card"].endswith("alpha-card-2026-09-01.md")][0]
        # The file was renamed on 09-03; --follow must still date the entry 09-02.
        self.assertEqual(alpha["date"], "2026-09-02")

    def test_contaminated_headers_are_not_counted(self):
        rep = build_rate.transitions_from_git(self.repo, self.SINCE)
        counted = " ".join(t["card"] for t in rep["transitions"])
        for name in ("d-card", "e-card", "f-card-build-bug", "c-card"):
            self.assertNotIn(name, counted,
                             "%s must not count as entering BUILD" % name)

    def test_a_ledger_full_of_build_gate_prose_changes_nothing(self):
        before = build_rate.transitions_from_git(self.repo, self.SINCE)["total"]
        ledger = os.path.join(self.repo, "documents", "decision-ledger.jsonl")
        with open(ledger, "a", encoding="utf-8") as fh:
            for i in range(500):
                fh.write(json.dumps({
                    "company": "Extra%d" % i,
                    "note": "ruled BUILD; cleared the BUILD gate; build the send",
                }) + "\n")
        _commit(self.repo, "2026-09-03", "more ledger")
        after = build_rate.transitions_from_git(self.repo, self.SINCE)["total"]
        self.assertEqual(before, after, "ledger prose leaked into the count")
        self.assertEqual(after, 4)

    def test_post_window_entries_are_reported_not_silently_dropped(self):
        rep = build_rate.transitions_from_git(self.repo, self.SINCE,
                                              until="2026-09-02")
        self.assertEqual(rep["total"], 2)
        self.assertEqual(rep["after_window_count"], 2)   # g and i land 09-03
        self.assertEqual(rep["window_days"], 1)

    def test_both_rates_share_one_window(self):
        rep = build_rate.rate_report(self.repo, 3, anchor="2026-09-04")
        self.assertEqual(rep["notes_built"]["window_days"],
                         rep["transitions_from_git"]["window_days"])
        self.assertEqual(rep["transitions_from_git"]["as_of"],
                         rep["window_end"])

    def test_pre_window_entries_are_reported_not_silently_dropped(self):
        rep = build_rate.transitions_from_git(self.repo, self.SINCE)
        self.assertEqual(rep["before_window_count"], 1)
        self.assertTrue(rep["before_window"][0]["card"].endswith("h-card-2026-09-01.md"))

    def test_a_card_that_never_reached_build_is_accounted_for(self):
        rep = build_rate.transitions_from_git(self.repo, self.SINCE)
        # c, d, e, f, j never show a BUILD header.
        self.assertEqual(rep["cards_never_build"], 5)
        self.assertEqual(rep["cards_examined"], rep["cards_total"])
        self.assertEqual(rep["skipped_count"], 0)

    def test_exhausted_budget_reports_skipped_cards_rather_than_truncating(self):
        rep = build_rate.transitions_from_git(self.repo, self.SINCE, time_budget_s=-1.0)
        self.assertEqual(rep["skipped_count"], rep["cards_total"])
        self.assertEqual(rep["cards_examined"], 0)
        self.assertIn("time budget", rep["skipped"][0]["reason"])

    def test_commit_date_wins_over_the_prose_date_but_the_lag_is_reported(self):
        rep = build_rate.transitions_from_git(self.repo, self.SINCE)
        india = [t for t in rep["transitions"]
                 if t["card"].endswith("i-card-2026-09-02.md")][0]
        self.assertEqual(india["date"], "2026-09-03")          # counted: commit
        self.assertEqual(india["stated_ruling_date"], "2026-09-02")  # advisory
        self.assertEqual(india["commit_lag_days"], 1)

    def test_a_card_sent_without_a_committed_build_header_is_declared_unobservable(self):
        rep = build_rate.transitions_from_git(self.repo, self.SINCE)
        counted = " ".join(t["card"] for t in rep["transitions"])
        self.assertNotIn("j-card", counted)
        self.assertEqual(rep["sent_without_observed_build"], 1)
        self.assertIn("FLOOR", rep["coverage_note"])

    def test_method_string_states_the_day_granularity_limitation(self):
        rep = build_rate.transitions_from_git(self.repo, self.SINCE)
        self.assertIn("DAY ONLY", rep["method"])
        self.assertIn("git log --follow", rep["method"])

    def test_module_docstring_states_the_day_granularity_limitation(self):
        self.assertIn("DAY GRANULARITY ONLY", build_rate.__doc__)


class RateReportTest(FixtureRepoMixin, unittest.TestCase):
    def test_both_metrics_are_returned_separately_and_never_merged(self):
        rep = build_rate.rate_report(self.repo, 3, anchor="2026-09-04")
        self.assertEqual(rep["window_start"], "2026-09-02")
        self.assertEqual(rep["window_end"], "2026-09-04")
        self.assertEqual(rep["notes_built"]["total"], 7)
        self.assertEqual(rep["transitions_from_git"]["total"], 4)
        self.assertNotEqual(rep["notes_built"]["method"],
                            rep["transitions_from_git"]["method"])
        self.assertIn("Do not sum", rep["conflation_warning"])

    def test_anchor_defaults_to_the_latest_send_log_date(self):
        rep = build_rate.rate_report(self.repo, 1)
        self.assertEqual(rep["window_end"], "2026-09-04")

    def test_rates_are_raw_counts_over_window_days(self):
        rep = build_rate.rate_report(self.repo, 3, anchor="2026-09-04")
        n = rep["notes_built"]
        self.assertAlmostEqual(n["per_day"], round(n["total"] / 3.0, 2))

    def test_window_days_must_be_positive(self):
        with self.assertRaises(ValueError):
            build_rate.rate_report(self.repo, 0)

    def test_cli_runs_and_emits_json(self):
        script = os.path.join(KIT_SCRIPTS, "build_rate.py")
        res = subprocess.run(
            [sys.executable, script, "--repo", self.repo, "--window-days", "3",
             "--anchor", "2026-09-04", "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        payload = json.loads(res.stdout)
        self.assertEqual(payload["notes_built"]["total"], 7)
        self.assertEqual(payload["transitions_from_git"]["total"], 4)


class FreshInstallTest(unittest.TestCase):
    """A partner's install may have no card history yet, and no send log yet.

    This is the case the port has to answer for that the original main-repo
    file never had to: main's send log and card corpus always exist. Both
    metrics must report an honest empty/zero result here, never a crash and
    never a fabricated rate.
    """

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="build_rate_fresh_")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.name", "T")
        _git(self.repo, "config", "user.email", "t@example.invalid")
        os.makedirs(os.path.join(self.repo, "documents", "state"), exist_ok=True)

    def test_no_cards_yet_is_an_honest_empty_report_not_a_crash(self):
        rep = build_rate.transitions_from_git(self.repo, "2026-01-01")
        self.assertEqual(rep["cards_total"], 0)
        self.assertEqual(rep["total"], 0)
        self.assertEqual(rep["cards_never_build"], 0)
        self.assertIn("FLOOR", rep["coverage_note"])

    def test_no_send_log_yet_raises_rather_than_fabricating_a_rate(self):
        # No documents/send-log.jsonl has been created. notes_built reads the
        # file directly and must fail loudly (FileNotFoundError), not report a
        # silent zero that would be indistinguishable from "zero notes built".
        with self.assertRaises(FileNotFoundError):
            build_rate.notes_built(self.repo, "2026-01-01", "2026-01-02")


class LivePresenceTest(unittest.TestCase):
    """Read-only: the ported script exists in this kit tree and is importable
    with no import-time dependency on any main-only module or absolute path."""

    def test_ported_file_exists_in_the_kit_tree(self):
        self.assertTrue(os.path.exists(os.path.join(KIT_SCRIPTS, "build_rate.py")))

    def test_module_has_no_hardcoded_absolute_repo_path(self):
        with open(os.path.join(KIT_SCRIPTS, "build_rate.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("/workspaces/" "ai-job-search", src)
        self.assertNotIn("/home/", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
