"""kit#227: mail-draft.sh --dry-run runs every gate and writes NOTHING.

A partner's ask (queued via kit #225/#226): a partner should be able to run mail-draft.sh against a
real company and see every gate's verdict (dedup, blocked list, build-ruling, résumé attach,
praise/LaCivita checks, the résumé-panel receipt, the rest) exactly as a real send would evaluate
them, with zero side effects — no draft created, no send-log write, no state touched anywhere.
app_sync.py already carries this --dry-run pattern; this ports it to mail-draft.sh.

Two things this test proves:
  1. A --dry-run call that clears every gate writes NOTHING (no draft file, no send-log row, no
     outreach_log/correspondence-log touch) and still exits 0.
  2. A --dry-run call still hits a real gate failure (here: the résumé-panel receipt, which is
     the one gate that historically only ran AFTER the draft/file was already written) and exits
     nonzero for it — a dry run that always reports success regardless of the gates is worthless.
"""
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")


class DryRunSandbox:
    def __init__(self, name):
        self.root = os.path.join(scratch_root(), name)

    def build(self):
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "documents"))
        shutil.copytree(SCRIPTS, os.path.join(self.root, "scripts"))
        binp = os.path.join(self.root, "bin")
        os.makedirs(binp)
        for stub in ("osascript", "dig"):
            f = os.path.join(binp, stub)
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\nexit 0\n")
            os.chmod(f, 0o755)
        self.body = os.path.join(self.root, "body.txt")
        with open(self.body, "w", encoding="utf-8") as fh:
            fh.write("Hi, Jane!\n\nGood to reconnect, no ask.\n")
        return self

    def run(self, extra_args):
        env = dict(os.environ, PATH=os.path.join(self.root, "bin") + os.pathsep + os.environ.get("PATH", ""))
        return subprocess.run(
            ["bash", os.path.join(self.root, "scripts", "mail-draft.sh"),
             "--to", "jane@example.test", "--subject", "Hello", "--body-file", self.body,
             "--rung", "warm", "--force", "--targets", "SomeCo", "--name", "Jane Doe"] + extra_args,
            capture_output=True, text=True, env=env, timeout=300)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class TestDryRunWritesNothingOnAPass(unittest.TestCase):
    def setUp(self):
        self.sb = DryRunSandbox("test-kit227-dry-run-pass").build()
        self.done = self.sb.run(["--dry-run", "--no-resume"])
        self.out = self.done.stdout + self.done.stderr

    def tearDown(self):
        self.sb.cleanup()

    def test_exits_zero(self):
        self.assertEqual(0, self.done.returncode, self.out[-2000:])

    def test_says_dry_run(self):
        self.assertIn("DRY RUN", self.out, self.out[-2000:])

    def test_no_send_log_written(self):
        slog = os.path.join(self.sb.root, "documents", "send-log.jsonl")
        self.assertFalse(os.path.exists(slog) and os.path.getsize(slog) > 0,
                          "send-log.jsonl should be empty/absent after --dry-run:\n" + self.out[-2000:])

    def test_no_outreach_log_written(self):
        olog = os.path.join(self.sb.root, "outreach_log.md")
        self.assertFalse(os.path.exists(olog),
                          "outreach_log.md should not exist after --dry-run:\n" + self.out[-2000:])

    def test_no_correspondence_log_written(self):
        clog = os.path.join(self.sb.root, "documents", "correspondence-log.md")
        self.assertFalse(os.path.exists(clog),
                          "correspondence-log.md should not exist after --dry-run:\n" + self.out[-2000:])

    def test_no_eml_or_copy_file_written(self):
        for suffix in (".eml", ".copy.txt", ".link.txt"):
            p = os.path.splitext(self.sb.body)[0] + suffix
            self.assertFalse(os.path.exists(p), f"{p} should not exist after --dry-run")


class TestDryRunStillHitsAGateFailure(unittest.TestCase):
    """The résumé-panel receipt gate is the one that, before this fix, only ran AFTER the draft
    or file was already written. A --dry-run that skips straight past it and reports a clean pass
    would misrepresent what a real send would do. Use a thank-you (POST_CONTACT) rung so every
    OTHER gate (LaCivita, praise, segment, the outreach panel, the BUILD gate) is genuinely
    skipped rather than --force-bypassed — a --force also bypasses the résumé-panel gate, which
    would make it impossible to prove THIS gate is the one still firing. Seed send-log.jsonl with
    a real prior "sent" row for the company, which is what a thank-you's inverse dedup requires,
    and attach a plain-text file with a real, unreviewed text layer (no --force) so the résumé
    panel gate — and only that gate — is the one left standing between this run and a clean pass.
    """

    def setUp(self):
        self.sb = DryRunSandbox("test-kit227-dry-run-gate-still-fires").build()
        with open(os.path.join(self.sb.root, "documents", "send-log.jsonl"), "w", encoding="utf-8") as fh:
            fh.write('{"status": "sent", "company": "SomeCo", "date": "2026-09-01", '
                     '"to": "old@example.test"}\n')
        resume = os.path.join(self.sb.root, "resume.txt")
        with open(resume, "w", encoding="utf-8") as fh:
            fh.write("Jane Doe — Resume\nSome Company, Product Manager, 2020-2026\n")
        self.resume = resume

    def tearDown(self):
        self.sb.cleanup()

    def run_thankyou(self, extra_args):
        env = dict(os.environ, PATH=os.path.join(self.sb.root, "bin") + os.pathsep + os.environ.get("PATH", ""))
        return subprocess.run(
            ["bash", os.path.join(self.sb.root, "scripts", "mail-draft.sh"),
             "--to", "jane@example.test", "--subject", "Thanks!", "--body-file", self.sb.body,
             "--rung", "thank-you", "--company", "SomeCo"] + extra_args,
            capture_output=True, text=True, env=env, timeout=300)

    def test_dry_run_still_blocks_on_missing_resume_panel_receipt(self):
        done = self.run_thankyou(["--dry-run", "--attach", self.resume])
        out = done.stdout + done.stderr
        self.assertNotEqual(0, done.returncode,
                             "a --dry-run with no résumé-panel receipt should still fail that "
                             "gate, exactly as a real send would:\n" + out[-2000:])
        self.assertIn("résumé-panel receipt", out, out[-2000:])
        # No draft/log side effects even on a gate failure that also would have blocked a real send.
        slog = os.path.join(self.sb.root, "documents", "send-log.jsonl")
        with open(slog, encoding="utf-8") as fh:
            self.assertEqual(1, len(fh.readlines()), "the seeded row must be the only row — dry-run wrote nothing new")

    def test_the_same_send_for_real_would_also_be_blocked_pre_write(self):
        """Control: without --dry-run, the same call is ALSO blocked before any write — proving
        the résumé-panel gate genuinely blocks this exact input rather than something else."""
        done = self.run_thankyou(["--attach", self.resume])
        out = done.stdout + done.stderr
        self.assertNotEqual(0, done.returncode, out[-2000:])
        self.assertIn("résumé-panel receipt", out, out[-2000:])


if __name__ == "__main__":
    unittest.main()
