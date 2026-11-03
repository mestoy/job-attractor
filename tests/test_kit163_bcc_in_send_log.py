"""kit#163 (1 of 2): mail-draft.sh's `--bcc` is a sanctioned option and the AppleScript adds
the BCC recipients to the compose window, but the send-log row never carried them, so prior-
contact/dedup checks (which read the send log) couldn't see the BCC address was also
contacted. Adds a "bcc" field to the row.

mail-draft.sh shells out to osascript (macOS-only) and can't run in this container -- covered
here the same way BUG-254 covers --from: a real subprocess run with osascript/dig stubbed to
exit 0, checking the pure-Python send-log write.

Fixtures are fictional, never a real address from the private repo.
"""
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
sys.path.insert(0, SCRIPTS)


class Kit163BccInSendLogTests(unittest.TestCase):
    def _sandbox_send(self, *extra):
        sb = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, sb, True)
        shutil.copytree(SCRIPTS, os.path.join(sb, "scripts"))
        os.makedirs(os.path.join(sb, "documents"))
        bind = os.path.join(sb, "bin")
        os.makedirs(bind)
        for stub in ("osascript", "dig"):
            p = os.path.join(bind, stub)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\nexit 0\n")
            os.chmod(p, 0o755)
        body = os.path.join(sb, "body.txt")
        with open(body, "w", encoding="utf-8") as fh:
            fh.write("Hi, Jane!\n\nGood to reconnect, no ask.\n")
        env = dict(os.environ, PATH=bind + os.pathsep + os.environ.get("PATH", ""))
        args = ["--to", "jane@example.test", "--subject", "Hello", "--body-file", body,
                "--rung", "warm", "--no-resume", "--force", "--targets", "SomeCo", *extra]
        result = subprocess.run(["bash", os.path.join(sb, "scripts", "mail-draft.sh"), *args],
                                 capture_output=True, text=True, env=env)
        slog = os.path.join(sb, "documents", "send-log.jsonl")
        rows = [json.loads(l) for l in open(slog, encoding="utf-8")] if os.path.exists(slog) else []
        return result, rows

    def test_a_no_bcc_flag_writes_an_empty_bcc_list(self):
        result, rows = self._sandbox_send()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(rows, "mail-draft wrote no send-log row")
        self.assertEqual(rows[-1].get("bcc"), [])

    def test_b_bcc_flag_lands_in_the_send_log_row(self):
        result, rows = self._sandbox_send(
            "--bcc", "cc1@example.invalid,cc2@example.invalid")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(rows)
        self.assertEqual(rows[-1].get("bcc"),
                         ["cc1@example.invalid", "cc2@example.invalid"])


if __name__ == "__main__":
    unittest.main()
