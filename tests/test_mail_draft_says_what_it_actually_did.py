"""mail-draft.sh must not claim a mail-program draft when it wrote a FILE.

⛔ WHY: on the eml route the script writes a .eml file and says so plainly, and then its last line
says "OK: draft created in Apple Mail (visible, NOT sent)." Nothing is in Apple Mail. On Linux
there is no Apple Mail at all. The outreach_log entry it writes says "STAGED (draft created,
awaiting your send)" for every route.

The script already computes the right words per route in `_STAGED_WORDS` — kit #145 added that
exact fix — but the value was never used anywhere, because the block that sets it had been ported
into the middle of a Python heredoc and did nothing at all.

check_dup reads the STAGED wording to tell an in-flight draft from a real send, so this is not
only a politeness: the record has to say what happened.
"""
import json
import os
import sys
import shutil
import subprocess
import unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
SANDBOX = os.path.join(scratch_root(), "test-mail-draft-says")
class TestItSaysWhatItDid(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        os.makedirs(os.path.join(SANDBOX, "documents"))
        shutil.copytree(SCRIPTS, os.path.join(SANDBOX, "scripts"))
        binp = os.path.join(SANDBOX, "bin")
        os.makedirs(binp)
        for stub in ("osascript", "dig"):
            f = os.path.join(binp, stub)
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\nexit 0\n")
            os.chmod(f, 0o755)
        body = os.path.join(SANDBOX, "body.txt")
        with open(body, "w", encoding="utf-8") as fh:
            fh.write("Hi, Jane!\n\nGood to reconnect, no ask.\n")
        env = dict(os.environ, PATH=binp + os.pathsep + os.environ.get("PATH", ""))
        self.run = subprocess.run(
            ["bash", os.path.join(SANDBOX, "scripts", "mail-draft.sh"),
             "--to", "jane@example.test", "--subject", "Hello", "--body-file", body,
             "--rung", "warm", "--no-resume", "--force", "--targets", "SomeCo",
             "--name", "Jane Doe"],
            capture_output=True, text=True, env=env, timeout=300)
        self.out = self.run.stdout + self.run.stderr

    def tearDown(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)

    def test_it_took_the_file_route(self):
        """A control. On a Mac this would be the osascript route and the claims below would be
        true, so the assertions only mean something once the file route is confirmed."""
        self.assertIn("delivery: eml", self.out,
                      "this run did not take the .eml file route:\n" + self.out[-1500:])

    def test_it_does_not_claim_a_draft_is_in_apple_mail(self):
        self.assertNotIn("draft created in Apple Mail", self.out,
                         "the script wrote a file and then said the draft is in Apple Mail. On "
                         "this machine Apple Mail does not exist.")

    def test_the_outreach_log_says_a_file_was_written(self):
        log = os.path.join(SANDBOX, "outreach_log.md")
        self.assertTrue(os.path.exists(log), "no outreach_log.md was written:\n" + self.out[-1500:])
        with open(log, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("draft", body, "the STAGED record must carry the word check_dup reads")
        self.assertNotIn("STAGED (draft created, awaiting your send)", body,
                         "the STAGED record claims a mail-program draft on a route that wrote a "
                         "file; _STAGED_WORDS already holds the right words for each route")

    def test_the_send_log_row_exists(self):
        """The row this file's sibling test covers, asserted here too because a run that says the
        right words and records nothing is not better than one that says the wrong words."""
        slog = os.path.join(SANDBOX, "documents", "send-log.jsonl")
        self.assertTrue(os.path.exists(slog), "no send-log.jsonl:\n" + self.out[-1500:])
        rows = [json.loads(l) for l in open(slog, encoding="utf-8") if l.strip()]
        self.assertTrue(rows, "send-log.jsonl is empty")
        self.assertEqual("Jane Doe", rows[-1].get("to_name"))


if __name__ == "__main__":
    unittest.main()
