#!/usr/bin/env python3
"""BUG-134 / kit issue #8: check_dup could not tell "already worked" from "waiting to be
worked", so the SCREEN GATE was unrunnable on the banked pool — measured 800 of 814 banked
rows returning ALREADY-SEEN, 14 POSSIBLE, 0 NEW, against the gate's own instruction ("proceed
only on NEW; ALREADY-SEEN/POSSIBLE = STOP"). The banked files say it themselves: "A name in
this file means worth screening, never worth sending."

This pins the record-KIND fix: a company whose ONLY record is a banked-candidates row now
reads NEW-TO-SCREEN (exit 0), while a company that is ALSO genuinely already-seen (blocked, on
the green board, sent) still reads ALREADY-SEEN/POSSIBLE off THAT store — being queued never
weakens a real hit.

⚠️ NEW FILE, NOT test_gates.py: consistent with earlier clusters' collision-avoidance note.
"""
import importlib
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

check_dup = importlib.import_module("check_dup")


class ScreenGateRecordKindTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kf2-screengate-")
        os.makedirs(os.path.join(self.tmp, "documents"), exist_ok=True)
        self._real_repo = check_dup.REPO
        check_dup.REPO = self.tmp
        self._write("documents/blocked-employers-list.md", "# blocked\n")
        self._write("documents/green-board.md", "# green board\n\n")
        self._write("outreach_log.md", "# Outreach Log\n")
        self._write("job_search_tracker.csv", "date,company,role\n")
        self._write("documents/employers.jsonl", "")

    def tearDown(self):
        import shutil
        check_dup.REPO = self._real_repo
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rel, text):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _run(self, company):
        import io, contextlib
        buf = io.StringIO()
        old_argv = sys.argv
        sys.argv = ["check_dup.py", company]
        code = None
        try:
            with contextlib.redirect_stdout(buf):
                try:
                    check_dup.main()
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv = old_argv
        return code, buf.getvalue()

    # ── THE FIX ITSELF ──────────────────────────────────────────────────────────────────────
    def test_a_company_only_in_the_banked_pool_reads_new_to_screen(self):
        self._write("documents/banked-candidates-test.md",
                    "# Banked candidates\n\n> Written by the sweep script.\n\n"
                    "Zzzscreengate Robotics · Some Other Co\n")
        code, out = self._run("Zzzscreengate Robotics")
        self.assertEqual(code, 0, f"a banked-only company must exit 0:\n{out}")
        self.assertIn("NEW-TO-SCREEN", out)
        self.assertIn("banked-candidates", out)

    def test_a_bare_new_company_still_reads_plain_new(self):
        code, out = self._run("Zzzscreengate Nowhere")
        self.assertEqual(code, 0)
        self.assertIn("VERDICT: 🟢 NEW", out)
        self.assertNotIn("NEW-TO-SCREEN", out)

    def test_self_matching_batch_line_no_longer_blocks_the_gate(self):
        """The issue's own root-cause example: a company appears in ITS OWN banked-candidates
        batch line — the normal shape for a freshly-banked row. That match is real (never a
        collision), but a freshly-banked row must pass the gate, not refuse it."""
        self._write("documents/banked-candidates-test.md",
                    "# Banked candidates — agent sweep\n\n"
                    "Zzzscreengate Aecom Analog · Some Other Zzz Co · A Third Zzz Co\n")
        code, out = self._run("Zzzscreengate Aecom Analog")
        self.assertEqual(code, 0, f"a company matching its own banked batch line must exit 0:\n{out}")
        self.assertIn("NEW-TO-SCREEN", out)

    # ── DOES-NOT-WEAKEN: a genuine hit elsewhere still wins ────────────────────────────────
    def test_banked_plus_blocked_still_reads_red(self):
        self._write("documents/banked-candidates-test.md",
                    "# Banked candidates\n\n> Written by the sweep script.\n\n"
                    "Zzzscreengate Blocked Co\n")
        self._write("documents/blocked-employers-list.md",
                    "- **Zzzscreengate Blocked Co** (blocked 2026-08-01): test fixture.\n")
        self._write("documents/employers.jsonl",
                    json.dumps({"key": "zzzscreengateblockedco",
                               "display": "Zzzscreengate Blocked Co", "aliases": [],
                               "status": "blocked"}) + "\n")
        code, out = self._run("Zzzscreengate Blocked Co")
        self.assertEqual(code, 1, f"a genuinely blocked company must still exit 1:\n{out}")
        self.assertIn("BLOCKED", out)

    def test_banked_plus_green_board_still_reads_red(self):
        self._write("documents/banked-candidates-test.md",
                    "# Banked candidates\n\n> Written by the sweep script.\n\n"
                    "Zzzscreengate Greenboard Co\n")
        self._write("documents/green-board.md",
                    "# green board\n\n- Zzzscreengate Greenboard Co — READY\n")
        code, out = self._run("Zzzscreengate Greenboard Co")
        self.assertEqual(code, 1, f"a company on the green board must still read ALREADY-SEEN:\n{out}")
        self.assertIn("ALREADY-SEEN", out)
        self.assertIn("GREEN BOARD", out)
        self.assertIn("banked-candidates", out,
                      "the banked hit must still be visible as context, even though it did not "
                      "decide the verdict")

    def test_banked_plus_sent_still_reads_red(self):
        self._write("documents/banked-candidates-test.md",
                    "# Banked candidates\n\n> Written by the sweep script.\n\n"
                    "Zzzscreengate Sent Co\n")
        self._write("outreach_log.md",
                    "## 2026-08-01 · Zzzscreengate Sent Co · Jane Doe\n**Status:** ✅ SENT\n")
        code, out = self._run("Zzzscreengate Sent Co")
        self.assertEqual(code, 1, f"an already-sent company must still exit 1:\n{out}")
        self.assertIn("ALREADY-SEEN", out)

    def test_send_gate_mode_never_searches_the_banked_store(self):
        """--send-gate scope is unchanged: banked was never in SEND_GATE_STORES before this
        fix, and it must not become reachable through the new QUEUED_STORES path either."""
        self._write("documents/banked-candidates-test.md",
                    "# Banked candidates\n\n> Written by the sweep script.\n\n"
                    "Zzzscreengate Sendgate Co\n")
        old_argv = sys.argv
        import io, contextlib
        buf = io.StringIO()
        sys.argv = ["check_dup.py", "--send-gate", "Zzzscreengate Sendgate Co"]
        code = None
        try:
            with contextlib.redirect_stdout(buf):
                try:
                    check_dup.main()
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv = old_argv
        self.assertEqual(code, 0)
        self.assertNotIn("banked-candidates", buf.getvalue(),
                         "--send-gate must not search the banked store")


if __name__ == "__main__":
    unittest.main()
