#!/usr/bin/env python3
"""Regression suite for the ledger-vocabulary cluster (verdict normalization, DROP filter
vocabulary, and the banked-pool writer/gauge split).

Kept OUT of test_gates.py deliberately: rank_criteria.py is a serialization point other work
touches, and a standalone file keeps this cluster's fixtures from drifting with that file's.

Every test below encodes a partner-reported defect:
  * verdict has no closed vocabulary, so a legacy/prose row is silently invisible to every
    consumer that tests `verdict == "SURVIVOR"` (or "DROP") — both directions covered: a good
    SURVIVOR must not vanish, and a WATCH/UNPROVEN row that is not a real verdict must not be
    guessed into one.
  * the DROP filter map has no code for a partner's own real veto reasons, so the largest drop
    bucket lands unclassified, and a mis-stamped filter number is invisible until audit.
  * SURVIVOR rows are written to a store the BANKED pool gauge does not read, so a genuine bank
    reports as zero moved.

Run:  python3 tests/test_ledger_verdict_vocabulary.py   (or via tests/run_all.sh's discovery)
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

import findings_ledger
import reconcile_findings
import rank_criteria


# ─────────────────────────────────────────────────────────────────────────────
# normalize_verdict — the recovery function itself. Both failure directions: a real verdict
# buried in prose must be recovered, and a string that is NOT one of the four real verdicts
# must not be guessed into one.
# ─────────────────────────────────────────────────────────────────────────────
class TestNormalizeVerdict(unittest.TestCase):
    def test_a_clean_token_passes_through(self):
        for v in ("SURVIVOR", "DROP", "UNVERIFIED", "DEFERRED"):
            self.assertEqual(findings_ledger.normalize_verdict(v), v)

    def test_lowercase_is_upcased(self):
        self.assertEqual(findings_ledger.normalize_verdict("survivor"), "SURVIVOR")

    def test_a_leading_emoji_marker_is_stripped(self):
        self.assertEqual(
            findings_ledger.normalize_verdict("🔴 DROP — zero on-lane roles, hybrid-default"),
            "DROP")

    def test_a_trailing_qualifier_in_parens_is_recovered(self):
        self.assertEqual(findings_ledger.normalize_verdict("SURVIVOR (qualified)"), "SURVIVOR")

    def test_a_dated_prose_drop_is_recovered(self):
        self.assertEqual(
            findings_ledger.normalize_verdict("❌ DROP 2026-08-14 — thesis REFUTED"), "DROP")

    def test_none_normalizes_to_empty_not_a_guess(self):
        """FALSE-PASS guard. A row with no verdict field at all must stay a real gap, never a
        default verdict a caller might accidentally treat as meaningful."""
        self.assertEqual(findings_ledger.normalize_verdict(None), "")

    def test_a_non_vocabulary_word_is_not_recovered(self):
        """FALSE-PASS guard. WATCH is not one of the four verdicts. Recovering it would let an
        agent invent new vocabulary that every downstream reader silently accepts."""
        self.assertEqual(
            findings_ledger.normalize_verdict("🟡 WATCH — remote PROVEN, org is contracting"), "")

    def test_unproven_is_not_confused_with_unverified(self):
        """FALSE-PASS guard. 'UNPROVEN' reads close to 'UNVERIFIED' but is not the token that was
        actually written, and guessing the near miss would launder a different claim into the
        vocabulary."""
        self.assertEqual(findings_ledger.normalize_verdict("UNPROVEN — n too small"), "")


# ─────────────────────────────────────────────────────────────────────────────
# survivor_rulings() — rank_criteria.py's own consumer of the ledger. Confirms the normalization
# actually reaches the function partner-feedback named, not just the helper in isolation.
# ─────────────────────────────────────────────────────────────────────────────
class TestSurvivorRulingsRecoversLegacyRows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents", "findings"), exist_ok=True)
        self._prev = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = self.tmp.name
        self.addCleanup(self._restore)
        importlib.reload(findings_ledger)
        importlib.reload(rank_criteria)

    def _restore(self):
        if self._prev is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._prev
        importlib.reload(findings_ledger)
        importlib.reload(rank_criteria)

    def _write(self, *rows):
        path = os.path.join(self.tmp.name, "documents", "findings", "run1.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def test_a_clean_survivor_row_is_promoted(self):
        self._write({"company": "CleanCo", "verdict": "SURVIVOR", "ts": "2026-08-01T00:00:00+00:00"})
        self.assertIn(findings_ledger.canon("CleanCo"), rank_criteria.survivor_rulings())

    def test_a_prose_survivor_row_is_recovered_not_lost(self):
        """kit#63's exact repro: a SURVIVOR row with a qualifier used to fail the raw `==` test
        and fall back to the conservative default, unnoticed."""
        self._write({"company": "QualifiedCo", "verdict": "SURVIVOR (qualified)",
                     "ts": "2026-08-01T00:00:00+00:00"})
        self.assertIn(findings_ledger.canon("QualifiedCo"), rank_criteria.survivor_rulings())

    def test_a_watch_row_is_never_promoted_to_survivor(self):
        """FALSE-PASS guard. WATCH is not SURVIVOR, and normalizing verdicts must not blur that
        line — a widened `survivor_rulings()` would show an unfinished screen a finished badge."""
        self._write({"company": "WatchCo", "verdict": "🟡 WATCH — contracting",
                     "ts": "2026-08-01T00:00:00+00:00"})
        self.assertNotIn(findings_ledger.canon("WatchCo"), rank_criteria.survivor_rulings())


# ─────────────────────────────────────────────────────────────────────────────
# reconcile_findings() classification — the write-back side. A prose verdict must reach the
# SAME bucket (blocked list / banked file) a clean verdict would.
# ─────────────────────────────────────────────────────────────────────────────
class TestReconcileNormalizesLegacyVerdicts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents", "findings"), exist_ok=True)

    def _write(self, run, *rows):
        path = os.path.join(self.tmp.name, "documents", "findings", f"{run}.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def _run(self, *args):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.tmp.name)
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "reconcile_findings.py"), *args],
            capture_output=True, text=True, env=env, cwd=self.tmp.name)

    def test_a_prose_drop_row_reaches_the_blocked_list(self):
        self._write("run1", {"company": "DropCo", "verdict": "❌ DROP on fit — zero roles",
                             "filter": 1, "evidence": "no roles open", "lane": "payments",
                             "ts": "2026-08-01T00:00:00+00:00"})
        r = self._run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("1 DROP(s)", r.stdout)
        with open(os.path.join(self.tmp.name, "documents", "blocked-employers-list.md"),
                  encoding="utf-8") as fh:
            blocked = fh.read()
        self.assertIn("DropCo", blocked)

    def test_a_prose_survivor_row_reaches_the_banked_file(self):
        self._write("run2", {"company": "SurvivorCo", "verdict": "SURVIVOR (qualified)",
                             "lane": "payments", "ts": "2026-08-01T00:00:00+00:00"})
        r = self._run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("1 SURVIVOR(s)", r.stdout)
        import glob
        banked_files = glob.glob(os.path.join(self.tmp.name, "documents", "banked-candidates-*.md"))
        self.assertTrue(banked_files, "no banked-candidates file was written")
        banked_text = ""
        for f in banked_files:
            with open(f, encoding="utf-8") as fh:
                banked_text += fh.read()
        self.assertIn("SurvivorCo", banked_text)

    def test_a_watch_row_is_neither_dropped_nor_banked(self):
        """FALSE-PASS guard. WATCH is not a real verdict; it must land in `other`, not get
        guessed into a blocked-list or banked-file write."""
        self._write("run3", {"company": "WatchCo", "verdict": "🟡 WATCH — contracting",
                             "lane": "payments", "ts": "2026-08-01T00:00:00+00:00"})
        r = self._run()
        blocked_path = os.path.join(self.tmp.name, "documents", "blocked-employers-list.md")
        blocked = open(blocked_path, encoding="utf-8").read() if os.path.exists(blocked_path) else ""
        self.assertNotIn("WatchCo", blocked)
        self.assertNotIn("1 SURVIVOR(s)", r.stdout)


# ─────────────────────────────────────────────────────────────────────────────
# kit#31 — writer and gauge on the SAME store. `banked_keys()` is what the consistency-check
# gauge now calls; this proves it reflects exactly what reconcile_findings.py just wrote.
# ─────────────────────────────────────────────────────────────────────────────
class TestBankedWriterAndGaugeAgree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents", "findings"), exist_ok=True)
        # An empty green-board.md, exactly kit#31's repro shape: nothing for the OLD gauge logic
        # to count, so a pass here can only mean the NEW gauge is reading the right file.
        with open(os.path.join(self.tmp.name, "documents", "green-board.md"), "w") as fh:
            fh.write("# Green board\n\nNothing here yet.\n")

    def _run(self, *args):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.tmp.name)
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "reconcile_findings.py"), *args],
            capture_output=True, text=True, env=env, cwd=self.tmp.name)

    def test_banked_keys_reflects_a_fresh_write(self):
        path = os.path.join(self.tmp.name, "documents", "findings", "run1.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for co in ("Omada Health", "Cohere Health", "Pie Insurance"):
                fh.write(json.dumps({"company": co, "verdict": "SURVIVOR", "lane": "applied-ai",
                                     "ts": "2026-08-12T00:00:00+00:00"}) + "\n")
        r = self._run()
        self.assertIn("3 SURVIVOR(s)", r.stdout)

        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.tmp.name)
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r)\n"
             "from reconcile_findings import banked_keys\n"
             "print(len(banked_keys()))" % SCRIPTS],
            capture_output=True, text=True, env=env, cwd=self.tmp.name)
        self.assertEqual(out.stdout.strip(), "3",
                         "the gauge's own read of banked_keys() must match what was just written, "
                         "not the empty green-board.md (kit#31)")

    def test_nothing_banked_yet_reads_zero_not_a_crash(self):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.tmp.name)
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r)\n"
             "from reconcile_findings import banked_keys\n"
             "print(len(banked_keys()))" % SCRIPTS],
            capture_output=True, text=True, env=env, cwd=self.tmp.name)
        self.assertEqual(out.stdout.strip(), "0")


# ─────────────────────────────────────────────────────────────────────────────
# kit#53 — the DROP filter vocabulary. kit_config.EXTRA_FILTERS extends the base 11 without
# forking reconcile_findings.py, and filter 11's label is driven by kit_config.COMP_FLOOR.
# ─────────────────────────────────────────────────────────────────────────────
class TestFilterVocabularyExtension(unittest.TestCase):
    def setUp(self):
        import kit_config
        self.kit_config = kit_config
        self._prev_extra = getattr(kit_config, "EXTRA_FILTERS", {})
        self._prev_floor = getattr(kit_config, "COMP_FLOOR", 150000)
        self.addCleanup(self._restore)

    def _restore(self):
        self.kit_config.EXTRA_FILTERS = self._prev_extra
        self.kit_config.COMP_FLOOR = self._prev_floor
        importlib.reload(reconcile_findings)

    def test_the_base_eleven_codes_are_present(self):
        self.assertEqual(len(reconcile_findings.FILTERS), 11 + len(self._prev_extra))
        for n in range(1, 12):
            self.assertIn(n, reconcile_findings.FILTERS)

    def test_an_operator_declared_extra_code_is_unioned_in(self):
        """kit#53 point 1/2: a partner's real veto reason (layoffs/leadership instability) must be
        recordable without editing reconcile_findings.py."""
        self.kit_config.EXTRA_FILTERS = {12: "Recent layoffs or leadership instability"}
        importlib.reload(reconcile_findings)
        self.assertEqual(reconcile_findings.FILTERS[12], "Recent layoffs or leadership instability")
        # the base 11 must still be there — a union, never a replace
        self.assertIn(1, reconcile_findings.FILTERS)

    def test_filter_eleven_label_reflects_the_configured_comp_floor(self):
        """kit#53 point 3: filter 11 must name the OPERATOR's floor, not a stranger's $170K."""
        self.kit_config.COMP_FLOOR = 120_000
        importlib.reload(reconcile_findings)
        self.assertIn("$120,000", reconcile_findings.FILTERS[11])
        self.assertNotIn("170", reconcile_findings.FILTERS[11])


# ─────────────────────────────────────────────────────────────────────────────
# kit#53 point 4 — record_finding.py echoes the filter LABEL, not just the number, on success.
# ─────────────────────────────────────────────────────────────────────────────
class TestRecordFindingEchoesFilterLabel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents"), exist_ok=True)
        with open(os.path.join(self.tmp.name, "documents", "segments.md"), "w") as fh:
            fh.write("# segments\n")

    def _run(self, *args):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.tmp.name)
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "record_finding.py"), *args],
            capture_output=True, text=True, env=env, cwd=self.tmp.name)

    def test_a_drop_prints_its_filter_label_not_just_the_number(self):
        """kit#53's own incident: five real DROPs were mis-stamped filter 7 ('Not LGBTQIA+
        friendly') for reasons that were actually layoffs — printing the label at write time,
        not just the bare number, is what would have caught it instantly."""
        r = self._run("--run", "t1", "--lane", "payments", "--company", "WrongCo",
                      "--verdict", "DROP", "--filter", "7",
                      "--evidence", "recent layoffs and leadership churn")
        self.assertEqual(r.returncode, 0)
        self.assertIn("filter 7: Not LGBTQIA+ friendly", r.stdout)

    def test_an_unrecognized_filter_number_says_so_rather_than_a_bare_number(self):
        r = self._run("--run", "t2", "--lane", "payments", "--company", "OddCo",
                      "--verdict", "DROP", "--filter", "999", "--evidence", "some reason")
        self.assertEqual(r.returncode, 0)
        self.assertIn("filter 999:", r.stdout)
        self.assertIn("not recognized", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
