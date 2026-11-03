"""kit#225: mail-draft.sh --dry-run with no --to still runs every gate and reports the address as its own gate.

A partner's dry run stopped at the argument check ("need --to", exit 2) before any gate ran, but finding the
boss's address is often the last step. Red on 8bd947e: the ADDRESS-line tests (a dry run with no --to used to stop at "need --to" before any gate).
The two "guard" tests pass on 8bd947e on purpose: they pin behavior this change must not alter.
"""
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402
from test_kit227_mail_draft_dry_run import DryRunSandbox  # noqa: E402


def run_no_to(sb, extra):
    env = dict(os.environ, PATH=os.path.join(sb.root, "bin") + os.pathsep + os.environ.get("PATH", ""))
    return subprocess.run(
        ["bash", os.path.join(sb.root, "scripts", "mail-draft.sh"),
         "--subject", "Hello", "--body-file", sb.body,
         "--rung", "warm", "--force", "--targets", "SomeCo", "--name", "Jane Doe"] + extra,
        capture_output=True, text=True, env=env, timeout=300)


class TestDryRunWithoutTo(unittest.TestCase):
    def setUp(self):
        self.sb = DryRunSandbox("test-kit225-dry-run-no-to").build()

    def tearDown(self):
        self.sb.cleanup()

    def test_dry_run_reports_missing_address_and_exits_2(self):
        done = run_no_to(self.sb, ["--dry-run", "--no-resume"])
        out = done.stdout + done.stderr
        self.assertEqual(2, done.returncode, out[-2000:])
        self.assertIn("ADDRESS gate: MISSING", out, out[-2000:])
        self.assertIn("DRY RUN: every gate that does not need an address passed", out, out[-2000:])
        self.assertNotIn("need --to", out, out[-2000:])

    def test_next_target_without_force_reaches_the_person_check_and_the_address_guard_holds(self):
        """No --force, so the already-contacted block at the dedup gate really runs (and the NO_ADDR
        guard with it). SomeCo is seeded as already contacted, which is what opens that block."""
        with open(os.path.join(self.sb.root, "documents", "send-log.jsonl"), "w", encoding="utf-8") as fh:
            fh.write('{"status": "sent", "company": "SomeCo", "date": "2020-01-01", "to": "old@example.test"}\n')
        env = dict(os.environ, PATH=os.path.join(self.sb.root, "bin") + os.pathsep + os.environ.get("PATH", ""))
        done = subprocess.run(
            ["bash", os.path.join(self.sb.root, "scripts", "mail-draft.sh"), "--subject", "Hello",
             "--body-file", self.sb.body, "--rung", "cold-stranger", "--company", "SomeCo",
             "--name", "Jane Doe", "--dry-run", "--no-resume", "--next-target"],
            capture_output=True, text=True, env=env, timeout=300)
        out = done.stdout + done.stderr
        # The person check ran (the NO_ADDR guard held: it neither crashed nor blocked on the
        # placeholder). A later gate (praise source) stops this cold rung, which is out of scope here;
        # the dry-run's own final line is covered by the --force tests.
        self.assertIn("proceeding to the NEXT target type", out, out[-2500:])
        self.assertNotIn("has already been contacted", out, out[-2500:])

    def test_force_run_does_not_blame_the_address_for_the_skipped_check(self):
        done = run_no_to(self.sb, ["--dry-run", "--no-resume", "--next-target"])   # run_no_to passes --force
        out = done.stdout + done.stderr
        self.assertIn("ADDRESS gate: MISSING", out, out[-2000:])
        self.assertNotIn("--next-target check", out, out[-2000:])

    def test_dry_run_writes_nothing(self):
        done = run_no_to(self.sb, ["--dry-run", "--no-resume"])
        # The run must have got past the gates, or "nothing written" below would be an empty check.
        self.assertIn("ADDRESS gate: MISSING", done.stdout + done.stderr, (done.stdout + done.stderr)[-2000:])
        for rel in (("documents", "send-log.jsonl"), ("outreach_log.md"), ("documents", "correspondence-log.md")):
            p = os.path.join(self.sb.root, *rel) if isinstance(rel, tuple) else os.path.join(self.sb.root, rel)
            self.assertFalse(os.path.exists(p) and os.path.getsize(p) > 0, p)

    def test_guard_real_send_without_to_still_stops_at_the_argument_check(self):
        done = run_no_to(self.sb, ["--no-resume"])
        out = done.stdout + done.stderr
        self.assertEqual(2, done.returncode, out[-2000:])
        self.assertIn("need --to", out, out[-2000:])

    def test_guard_a_real_gate_failure_still_blocks_first(self):
        done = run_no_to(self.sb, ["--dry-run", "--rung", "not-a-rung"])
        out = done.stdout + done.stderr
        self.assertEqual(4, done.returncode, out[-2000:])
        self.assertIn("unknown --rung", out, out[-2000:])


if __name__ == "__main__":
    unittest.main()
