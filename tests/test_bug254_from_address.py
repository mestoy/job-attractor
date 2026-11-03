"""BUG-254: mail-draft.sh took no sender, so a deliverability experiment (sending from a
different address than Mail's default account) needed either a manual account switch in
Mail.app or a code change every time. Added --from, defaulting to unchanged behavior when
absent, and logs the sending address in the STAGED SENDLOG v1 marker so
reconcile_outreach_log.py can carry it through to send-log.jsonl for a later by-domain
reply-rate comparison.

mail-draft.sh itself shells out to osascript (macOS-only, per the kit's own README) and
can't run in this container -- covered here by a syntax check plus the two pure-Python
surfaces this bug actually touches: the SENDLOG v1 marker regex and the send-log.jsonl
write, both in reconcile_outreach_log.py.

Fixtures are fictional (never a real address from the private repo, per the PII rule this
test suite runs under).
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

import reconcile_outreach_log as rol  # noqa: E402

MAIL_DRAFT_SH = os.path.join(SCRIPTS, "mail-draft.sh")


class Bug254MailDraftSyntaxTests(unittest.TestCase):
    def test_a_script_is_still_valid_bash(self):
        result = subprocess.run(["bash", "-n", MAIL_DRAFT_SH], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_b_from_flag_and_sender_property_are_wired(self):
        text = open(MAIL_DRAFT_SH, encoding="utf-8").read()
        self.assertIn('--from) FROM="$2"; shift 2;;', text)
        self.assertIn('"$FROM" <<\'APPLESCRIPT\'', text)
        self.assertIn("set sender of m to fromAddr", text)
        # unset stays the pre-existing behavior -- never forced onto every draft
        self.assertIn('if fromAddr is not "" then', text)


class Bug254MailDraftEndToEndTests(unittest.TestCase):
    """Runs the real script (osascript/dig stubbed, same fixture shape test_gates.py's
    TestMailDraftWritesRecipientName already uses) so a regression like FROM being read
    under `set -u` before it's ever assigned -- which broke EVERY invocation, not just
    --from ones, and was only caught by re-running the full suite -- fails here directly
    instead of needing a full-suite run to notice."""

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

    def test_a_no_from_flag_behaves_exactly_as_before(self):
        result, rows = self._sandbox_send()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(rows, "mail-draft wrote no send-log row")
        self.assertEqual(rows[-1].get("from"), "")

    def test_b_from_flag_lands_in_the_send_log_row(self):
        result, rows = self._sandbox_send("--from", "sender@me.invalid")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(rows)
        self.assertEqual(rows[-1].get("from"), "sender@me.invalid")


class Bug254SendlogMarkerTests(unittest.TestCase):
    def test_a_marker_with_a_from_address_is_parsed(self):
        body = (
            '<!-- SENDLOG v1 date=2026-09-10 rung=cold-boss channel=email '
            'to=fictional@example.invalid from=sender@me.invalid subject=Hello -->'
        )
        m = rol.SENDLOG_MARK.search(body)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(4), "fictional@example.invalid")
        self.assertEqual(m.group(5), "sender@me.invalid")
        self.assertEqual(m.group(6), "Hello")

    def test_b_marker_with_no_from_address_still_parses_old_history(self):
        """Backward compatibility: every marker written before --from existed has no from=
        token at all -- must still match exactly as before, from_addr just reads empty."""
        body = (
            '<!-- SENDLOG v1 date=2026-08-10 rung=cold-boss channel=email '
            'to=fictional@example.invalid subject=Hello -->'
        )
        m = rol.SENDLOG_MARK.search(body)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(4), "fictional@example.invalid")
        self.assertIsNone(m.group(5))
        self.assertEqual(m.group(6), "Hello")

    def test_c_parse_carries_from_addr_into_the_candidate_row(self):
        text = (
            "## 2026-09-10 · Fictional Co · fictional@example.invalid — SENT\n"
            "<!-- SENDLOG v1 date=2026-09-10 rung=cold-boss channel=email "
            "to=fictional@example.invalid from=sender@me.invalid subject=Hello -->\n"
        )
        cand, _skipped = rol.parse(text)
        self.assertEqual(len(cand), 1)
        self.assertEqual(cand[0]["from_addr"], "sender@me.invalid")

    def test_d_parse_defaults_from_addr_to_empty_when_marker_has_none(self):
        text = (
            "## 2026-08-10 · Fictional Co · fictional@example.invalid — SENT\n"
            "<!-- SENDLOG v1 date=2026-08-10 rung=cold-boss channel=email "
            "to=fictional@example.invalid subject=Hello -->\n"
        )
        cand, _skipped = rol.parse(text)
        self.assertEqual(len(cand), 1)
        self.assertEqual(cand[0]["from_addr"], "")


if __name__ == "__main__":
    unittest.main()
