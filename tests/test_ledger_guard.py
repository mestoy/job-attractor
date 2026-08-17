#!/usr/bin/env python3
"""BUG-215 fast-follow: the PreToolUse ledger-guard DENIES agent Write/Edit to the safety ledgers.

The --disallowedTools fence could only cover the Edit tool (Claude Code ignores Write path scopes),
so a runaway could still OVERWRITE documents/state/run-budget.jsonl via the Write tool and defeat the
daily cap. This hook is the mechanical close: it must DENY (exit 2) a Write/Edit to a protected
ledger and ALLOW (exit 0) everything else, including the crons' legitimate report/queue writes."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HOOK = os.path.join(REPO, "scripts", "check_ledger_guard.py")


def _run(payload, project_dir=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": project_dir or REPO}
    r = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    return r.returncode, (r.stdout + r.stderr)


def _write(path, tool="Write"):
    return {"tool_name": tool, "tool_input": {"file_path": path}}


class LedgerGuardDenies(unittest.TestCase):
    def test_write_to_run_budget_ledger_is_denied(self):
        rc, out = _run(_write(os.path.join(REPO, "documents", "state", "run-budget.jsonl")))
        self.assertEqual(rc, 2, "Write to the run-budget ledger must be denied")
        self.assertIn("BLOCKED", out)

    def test_edit_to_decision_ledger_is_denied(self):
        rc, _ = _run(_write(os.path.join(REPO, "documents", "decision-ledger.jsonl"), tool="Edit"))
        self.assertEqual(rc, 2, "Edit to the decision ledger must be denied")

    def test_relative_path_to_ledger_is_denied(self):
        rc, _ = _run(_write("documents/state/run-budget.jsonl"))
        self.assertEqual(rc, 2, "a repo-relative path to the ledger must be denied")

    def test_traversal_path_to_ledger_is_denied(self):
        rc, _ = _run(_write(os.path.join(REPO, "documents", "..", "documents", "state",
                                         "run-budget.jsonl")))
        self.assertEqual(rc, 2, "a .. traversal to the ledger must resolve and be denied")

    def test_multiedit_to_ledger_is_denied(self):
        rc, _ = _run(_write(os.path.join(REPO, "documents", "state", "run-budget.jsonl"),
                            tool="MultiEdit"))
        self.assertEqual(rc, 2, "MultiEdit to the ledger must be denied")


class LedgerGuardAllows(unittest.TestCase):
    def test_cron_report_write_is_allowed(self):
        rc, _ = _run(_write(os.path.join(REPO, "documents", "auto-sweep-2026-08-16.md")))
        self.assertEqual(rc, 0, "the auto-sweep report write must be allowed")

    def test_outreach_queue_write_is_allowed(self):
        rc, _ = _run(_write(os.path.join(REPO, "documents", "outreach-queue.md")))
        self.assertEqual(rc, 0, "the prep queue write must be allowed")

    def test_other_state_file_write_is_allowed(self):
        # the guard is scoped to the two ledgers, not all of documents/state
        rc, _ = _run(_write(os.path.join(REPO, "documents", "state", "weights-derive.json")))
        self.assertEqual(rc, 0, "a non-ledger state file is not guarded by this hook")

    def test_read_tool_is_ignored(self):
        rc, _ = _run({"tool_name": "Read", "tool_input": {"file_path":
                     os.path.join(REPO, "documents", "state", "run-budget.jsonl")}})
        self.assertEqual(rc, 0, "reading the ledger is fine; only Write/Edit are guarded")

    def test_malformed_payload_fails_open(self):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": REPO}
        r = subprocess.run([sys.executable, HOOK], input="not json",
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, "an unparseable payload must fail open, never wedge edits")


if __name__ == "__main__":
    unittest.main()
