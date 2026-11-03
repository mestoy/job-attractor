#!/usr/bin/env python3
"""Tests for scripts/seat_liveness.py -- passive fleet stamps, red first.

From documents/plan-seat-liveness-2026-09-13.md, approved 2026-09-13 15:58 ET. Proves: a hook
payload stamps session id/event/ts (StampOnEvent), a role seat is stale at 20 minutes and an
unassigned one at 60 (StaleAfterThreshold), assign wins over a prior claim on the same session
(AssignWinsOverClaim), a garbage state file is replaced rather than crashing the reader
(CorruptFileRecovers), and the report lists role and minutes quiet without printing an alert
(ReportListsRoleAndMinutesQuiet).

Runs in-process against an isolated state file (no real session ids, fixture names only) so it
stays fast; scripts/seat_liveness.py takes an explicit `path=` on every function precisely so
tests never need to touch documents/state/seat-liveness.json.
"""
import json
import os
import _roots
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import seat_liveness as sl  # noqa: E402


class SeatLivenessTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(prefix="seat-liveness-test-", suffix=".json")
        os.close(fd)
        os.remove(self.path)  # start from "file does not exist yet"

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)
        tmp = self.path + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)

    # ---- StampOnEvent ----
    def test_stamp_on_event_records_session_event_and_ts(self):
        payload = {"session_id": "fixture-session-aaa", "cwd": "/fixture/repo"}
        sid = sl.stamp_event(payload, "PostToolUse", path=self.path)
        self.assertEqual(sid, "fixture-session-aaa")
        state = sl.load_state(self.path)
        row = state["fixture-session-aaa"]
        self.assertEqual(row["last_event"], "PostToolUse")
        self.assertIn("last_ts", row)
        # ts round-trips as a real ISO timestamp
        self.assertIsNotNone(sl._parse_ts(row["last_ts"]))
        self.assertEqual(row["cwd"], "/fixture/repo")

    def test_stamp_on_event_missing_session_id_is_a_noop(self):
        sid = sl.stamp_event({"cwd": "/x"}, "Stop", path=self.path)
        self.assertIsNone(sid)
        self.assertEqual(sl.load_state(self.path), {})

    # ---- StaleAfterThreshold ----
    def test_role_seat_stale_after_twenty_minutes(self):
        now = datetime.now(timezone.utc)
        state = {
            "fixture-role-seat": {
                "role": "orchestrator",
                "last_ts": (now - timedelta(minutes=21)).isoformat(),
                "last_event": "Stop",
            }
        }
        sl.save_state(state, self.path)
        rows = sl.fleet_rows(self.path, now=now)
        row = next(r for r in rows if r["session_id"] == "fixture-role-seat")
        self.assertTrue(row["stale"])

    def test_role_seat_not_stale_under_twenty_minutes(self):
        now = datetime.now(timezone.utc)
        state = {
            "fixture-role-seat-2": {
                "role": "engineer",
                "last_ts": (now - timedelta(minutes=10)).isoformat(),
                "last_event": "Stop",
            }
        }
        sl.save_state(state, self.path)
        rows = sl.fleet_rows(self.path, now=now)
        row = next(r for r in rows if r["session_id"] == "fixture-role-seat-2")
        self.assertFalse(row["stale"])

    def test_unassigned_seat_stale_only_after_sixty_minutes(self):
        now = datetime.now(timezone.utc)
        state = {
            "fixture-unassigned": {
                "last_ts": (now - timedelta(minutes=45)).isoformat(),
                "last_event": "UserPromptSubmit",
            }
        }
        sl.save_state(state, self.path)
        rows = sl.fleet_rows(self.path, now=now)
        row = next(r for r in rows if r["session_id"] == "fixture-unassigned")
        self.assertFalse(row["stale"], "45 minutes quiet is under the 60-minute unassigned floor")

        state["fixture-unassigned"]["last_ts"] = (now - timedelta(minutes=61)).isoformat()
        sl.save_state(state, self.path)
        rows = sl.fleet_rows(self.path, now=now)
        row = next(r for r in rows if r["session_id"] == "fixture-unassigned")
        self.assertTrue(row["stale"])

    # ---- AssignWinsOverClaim ----
    def test_assign_wins_over_prior_claim(self):
        sl.save_state({"fixture-conflict-session": {
            "role": "self-claimed-role",
            "claimed_by": "claim",
            "last_ts": sl.now_iso(),
            "last_event": "claim",
        }}, self.path)
        sid = sl.assign("fixture-conflict-session", "assigned-role", path=self.path)
        self.assertEqual(sid, "fixture-conflict-session")
        state = sl.load_state(self.path)
        row = state["fixture-conflict-session"]
        self.assertEqual(row["role"], "assigned-role")
        self.assertEqual(row["claimed_by"], "assign")

    def test_assign_matches_by_prefix(self):
        sl.save_state({"fixture-abc123-longid": {
            "last_ts": sl.now_iso(), "last_event": "Stop",
        }}, self.path)
        sid = sl.assign("fixture-abc123", "design", path=self.path)
        self.assertEqual(sid, "fixture-abc123-longid")

    # ---- CorruptFileRecovers ----
    def test_corrupt_file_recovers_without_crashing(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json at all")
        # a read never raises
        state = sl.load_state(self.path)
        self.assertEqual(state, {})
        # nor does a stamp on top of a corrupt file -- it replaces it
        sid = sl.stamp_event({"session_id": "fixture-after-corrupt"}, "Stop", path=self.path)
        self.assertEqual(sid, "fixture-after-corrupt")
        state = sl.load_state(self.path)
        self.assertIn("fixture-after-corrupt", state)

    def test_hook_cli_never_raises_on_garbage_stdin(self):
        # exercises the real subprocess path end to end, garbage-in
        import subprocess
        script = os.path.join(os.path.dirname(sl.__file__), "seat_liveness.py")
        env = dict(os.environ)
        _roots.point_env(env, tempfile.mkdtemp(prefix="seat-liveness-hook-"))
        res = subprocess.run(
            [sys.executable, script, "--hook", "Stop"],
            input="not json{{{", capture_output=True, text=True, env=env,
        )
        self.assertEqual(res.returncode, 0)

    # ---- ReportListsRoleAndMinutesQuiet ----
    def test_report_lists_role_and_minutes_quiet(self):
        now = datetime.now(timezone.utc)
        state = {
            "fixture-report-orchestrator": {
                "role": "orchestrator",
                "last_ts": (now - timedelta(minutes=5)).isoformat(),
                "last_event": "Stop",
            },
            "fixture-report-stale-design": {
                "role": "design",
                "last_ts": (now - timedelta(minutes=30)).isoformat(),
                "last_event": "PostToolUse",
            },
        }
        sl.save_state(state, self.path)
        text = sl.report(path=self.path, now=now)
        self.assertIn("orchestrator", text)
        self.assertIn("design", text)
        self.assertIn("5.0m", text)
        self.assertIn("🔴", text)   # the stale design seat is flagged
        self.assertIn("🟢", text)   # the fresh orchestrator seat is quiet, not alarmed

    def test_report_drops_sessions_quiet_over_24_hours(self):
        now = datetime.now(timezone.utc)
        state = {
            "fixture-ancient": {
                "role": "orchestrator",
                "last_ts": (now - timedelta(hours=30)).isoformat(),
                "last_event": "Stop",
            }
        }
        sl.save_state(state, self.path)
        rows = sl.fleet_rows(self.path, now=now)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
