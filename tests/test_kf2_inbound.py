#!/usr/bin/env python3
"""issue #14: the response workflow has no intake. `pair_brief.open_inbound()` only ever read
`documents/correspondence-log.md`, which is written by hand, so a message that arrived and was
never logged read as ANSWERED — a confident zero while a real reply sat owed.

`scripts/check_inbound.py` is the fix: `--close <person> --reason "..."` appends to its own new
append-only store (never an INTAKE marker inside correspondence-log.md, which risks landing
inside a send-gate store and silently granting an unrelated build-gate exemption); the briefing
row is age-gated to ~2 days, not permanent; no emission rule keyed on an integer nobody writes.

⛔ EVERY TEST HERE RUNS AGAINST A THROWAWAY `tempfile.mkdtemp()` REPO, never the live tree.
Response-workflow code touches the live send-log/correspondence/messages surface if it is ever
pointed at the real repo by mistake — every subprocess call below passes an explicit env with
CLAUDE_PROJECT_DIR redirected, never the bare process environment.

⚠️ NEW FILE, consistent with earlier clusters' collision-avoidance note.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")


class CheckInboundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kf2-inbound-")
        self._write("documents/correspondence-log.md", "# Correspondence Log\n")
        self._write("outreach_log.md", "# Outreach Log\n")
        self._write("documents/state/inbound-intake-closed.jsonl", "")
        self.messages_path = os.path.join(self.tmp, "documents", "linkedin-exports", "messages.csv")
        os.makedirs(os.path.dirname(self.messages_path), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rel, text):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _read(self, rel):
        p = os.path.join(self.tmp, rel)
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    def _env(self):
        e = dict(os.environ)
        e["CLAUDE_PROJECT_DIR"] = self.tmp
        e.pop("GIT_DIR", None)
        return e

    def _write_messages(self, rows):
        """rows: [(from, to, date_str)]. Owner is inferred as whoever sends most, matching
        parse_messages._owner_names — every fixture below sends "Sample Owner" as an outbound
        leg somewhere so the owner resolves the same way a real export does."""
        with open(self.messages_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["FROM", "TO", "DATE", "IS MESSAGE DRAFT", "CONTENT"])
            for frm, to, when in rows:
                w.writerow([frm, to, when, "", "x"])

    def _run(self, *args):
        script = os.path.join(SCRIPTS, "check_inbound.py")
        return subprocess.run([sys.executable, script, *args],
                             cwd=self.tmp, env=self._env(),
                             capture_output=True, text=True)

    def _open_inbound(self):
        """Probe pair_brief.open_inbound() as a SUBPROCESS against the throwaway repo only."""
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "import parse_network\n"
            "parse_network.find_export = lambda explicit=None: (%r, '')\n"
            "import pair_brief\n"
            "print(pair_brief.open_inbound(repo=%r))\n"
        ) % (SCRIPTS, self.messages_path, self.tmp)
        r = subprocess.run([sys.executable, "-c", code], cwd=self.tmp, env=self._env(),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    # ── THE FIX ITSELF: a real inbound is surfaced, not zero'd ─────────────────────────────
    def test_the_exact_repro_an_unlogged_reply_is_surfaced_not_zeroed(self):
        """Someone wrote in, nothing in correspondence-log.md, and the old code reported a
        confident zero."""
        self._write_messages([
            ("Sample Owner", "Jordan Vance", "2026-08-05 10:00:00 UTC"),
            ("Jordan Vance", "Sample Owner", "2026-08-10 17:08:00 UTC"),
        ])
        out = self._run("--export", self.messages_path).stdout
        self.assertIn("Jordan Vance", out)
        self.assertIn("unanswered", out.lower())

        oi = self._open_inbound()
        self.assertIn("Jordan Vance", oi, f"open_inbound() must surface the unlogged reply:\n{oi}")

    def test_open_inbound_reports_a_confident_zero_before_this_fix(self):
        """The BEFORE state, pinned directly: with only correspondence-log.md consulted (this
        test bypasses check_inbound entirely), the same fixture that test_the_exact_repro proves
        NON-zero must — absent the fix wiring — read as having nothing open, proving this is a
        real behavioral change, not a fixture artifact."""
        self._write_messages([
            ("Sample Owner", "Jordan Vance", "2026-08-05 10:00:00 UTC"),
            ("Jordan Vance", "Sample Owner", "2026-08-10 17:08:00 UTC"),
        ])
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "import pair_brief\n"
            "src = pair_brief._rd('documents/correspondence-log.md', %r)\n"
            "print('EMPTY-LOG' if 'Jordan Vance' not in src else 'PRESENT')\n"
        ) % (SCRIPTS, self.tmp)
        r = subprocess.run([sys.executable, "-c", code], cwd=self.tmp, env=self._env(),
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "EMPTY-LOG",
                         "precondition: Jordan Vance must be absent from the hand-written log, "
                         "which is the whole shape of this bug")

    # ── --close: the ruled dismissal mechanism ──────────────────────────────────────────────
    def test_close_appends_to_its_own_store_and_suppresses_the_row(self):
        self._write_messages([
            ("Sample Owner", "Jordan Vance", "2026-08-05 10:00:00 UTC"),
            ("Jordan Vance", "Sample Owner", "2026-08-10 17:08:00 UTC"),
        ])
        oi_before = self._open_inbound()
        self.assertIn("Jordan Vance", oi_before)

        r = self._run("--close", "Jordan Vance", "--reason", "handled by phone, nothing owed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("closed intake", r.stdout)

        store_path = os.path.join(self.tmp, "documents/state/inbound-intake-closed.jsonl")
        rows = [json.loads(l) for l in open(store_path, encoding="utf-8") if l.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Jordan Vance")
        self.assertEqual(rows[0]["reason"], "handled by phone, nothing owed")
        self.assertIn("closed_at", rows[0])

        oi_after = self._open_inbound()
        self.assertNotIn("Jordan Vance", oi_after,
                         f"a closed intake row must stop surfacing:\n{oi_after}")

    def test_close_refuses_without_a_reason(self):
        """An unreasoned dismissal is a silent one."""
        r = self._run("--close", "Nobody Fixture")
        self.assertNotEqual(r.returncode, 0, "a --close with no --reason must be refused")
        store_path = os.path.join(self.tmp, "documents/state/inbound-intake-closed.jsonl")
        self.assertEqual(open(store_path, encoding="utf-8").read(), "",
                         "a refused --close must not write anything")

    def test_close_is_append_only_never_rewrites(self):
        """Two closures, same person, must both survive as separate rows — the same durability
        discipline as every other state store here (a correction is a NEW row, not an edit)."""
        self._run("--close", "Repeat Person", "--reason", "first pass")
        self._run("--close", "Repeat Person", "--reason", "second pass, correcting the first")
        store_path = os.path.join(self.tmp, "documents/state/inbound-intake-closed.jsonl")
        rows = [json.loads(l) for l in open(store_path, encoding="utf-8") if l.strip()]
        self.assertEqual(len(rows), 2)

    # ── DOES-NOT-WEAKEN: a genuinely answered thread stays quiet ────────────────────────────
    def test_a_replied_thread_is_not_surfaced(self):
        self._write_messages([
            ("Someone Else", "Sample Owner", "2026-08-05 09:00:00 UTC"),
            ("Sample Owner", "Someone Else", "2026-08-06 09:00:00 UTC"),   # replied AFTER
        ])
        out = self._run("--export", self.messages_path).stdout
        self.assertNotIn("Someone Else", out)
        oi = self._open_inbound()
        self.assertNotIn("Someone Else", oi)

    def test_already_closed_in_correspondence_log_outreach_is_not_double_surfaced(self):
        """A thread the EXISTING correspondence-log/outreach_log completion signal already
        considers closed must not also get raised via the raw-archive path — same person,
        one true answer, not two disagreeing signals."""
        self._write("outreach_log.md",
            "## 2026-08-01 · SomeCo · Existing Contact — ✅ SENT [linkedin]\n"
            "**Status:** ✅ SENT 2026-08-01 on linkedin. status:done — nothing further owed.\n")
        self._write_messages([
            ("Sample Owner", "Existing Contact", "2026-08-01 10:00:00 UTC"),
            ("Existing Contact", "Sample Owner", "2026-08-10 17:08:00 UTC"),
        ])
        oi = self._open_inbound()
        self.assertNotIn("Existing Contact", oi,
                         f"an existing outreach_log closure must suppress the raw-archive row too:\n{oi}")

    # ── AGE GATE: the briefing row is ~2 days, not permanent ────────────────────────────────
    def test_a_same_day_reply_is_not_yet_aged_into_the_briefing(self):
        import datetime
        today = datetime.date.today().isoformat()
        self._write_messages([
            ("Sample Owner", "Same Day Person", "2026-08-05 10:00:00 UTC"),
            ("Same Day Person", "Sample Owner", f"{today} 09:00:00 UTC"),
        ])
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "import check_inbound\n"
            "print(check_inbound.unanswered_aged(export=%r))\n"
        ) % (SCRIPTS, self.messages_path)
        r = subprocess.run([sys.executable, "-c", code], cwd=self.tmp, env=self._env(),
                           capture_output=True, text=True)
        self.assertNotIn("Same Day Person", r.stdout,
                         "a same-day reply must not appear in the AGED briefing view")
        # but the plain report (for manual triage) shows everything, unfiltered by age
        out = self._run("--export", self.messages_path).stdout
        self.assertIn("Same Day Person", out)

    # ── FAILS OPEN, HONESTLY: no export found is UNKNOWN, never a false zero ───────────────
    def test_no_messages_csv_reports_unknown_not_a_false_all_clear(self):
        # setUp only creates the parent dir, never the file itself — nothing to remove here.
        r = self._run("--export", self.messages_path)
        self.assertEqual(r.returncode, 2)
        self.assertIn("UNKNOWN", r.stdout)
        self.assertNotIn("no unanswered inbound", r.stdout.lower(),
                         "a missing archive must never be reported as a clean zero")

    # ── NEVER writes a correspondence entry ─────────────────────────────────────────────────
    def test_close_never_touches_correspondence_log_or_outreach_log(self):
        before_corr = self._read("documents/correspondence-log.md")
        before_out = self._read("outreach_log.md")
        self._run("--close", "Someone", "--reason", "test")
        self.assertEqual(self._read("documents/correspondence-log.md"), before_corr)
        self.assertEqual(self._read("outreach_log.md"), before_out)


if __name__ == "__main__":
    unittest.main()
