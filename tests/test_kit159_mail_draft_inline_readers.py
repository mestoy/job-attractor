"""kit#159 (a): mail-draft.sh has two inline Python heredocs that read send-gate stores directly,
separate from check_dup.py -- the --next-target 7-day-wait check (PYWAIT, send-log.jsonl and
outreach_log.md) and the send-body company-mention scan (PYBODY, blocked-employers-list.md and
job_search_tracker.csv). Both used to open with errors="ignore", so a corrupted store silently
read as "nothing found" instead of refusing: PYWAIT computed best=None -> days=999 -> "OK", waving
the pivot through as if the company had never been contacted; PYBODY's stores_read still counted a
corrupted file as read, so the positive control (stores_read == 0 -> BLOCKED) never fired. Both
heredocs are extracted with the same helper tests/test_mail_draft_heredocs_are_valid_python.py
uses and run as real subprocesses against fixture roots. Fixtures are fictional.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPT = os.path.join(KIT, "scripts", "mail-draft.sh")

HEREDOC = re.compile(r"""python3\b[^\n]*?<<\s*'?([A-Z][A-Z0-9_]*)'?""")


def _heredocs():
    with open(SCRIPT, encoding="utf-8") as fh:
        lines = fh.readlines()
    out = {}
    i = 0
    while i < len(lines):
        m = HEREDOC.search(lines[i])
        if not m:
            i += 1
            continue
        tag = m.group(1)
        j = i + 1
        body = []
        while j < len(lines) and lines[j].rstrip("\n").strip() != tag:
            body.append(lines[j])
            j += 1
        out[tag] = "".join(body)
        i = j + 1
    return out


_BODIES = _heredocs()


def _run(tag, argv):
    # mail-draft.sh passes SENDLOG_SCRIPTS="$HERE" to the heredocs that read the send log through sendlog_lock (BUG-687); the test stands in for that
    return subprocess.run([sys.executable, "-c", _BODIES[tag]] + argv, capture_output=True, text=True,
                          env=dict(os.environ, SENDLOG_SCRIPTS=os.path.join(KIT, "scripts")))


class NextTargetWaitCheck(unittest.TestCase):
    """PYWAIT: sys.argv = [company, root]."""

    def setUp(self):
        self.root = tempfile.mkdtemp(dir=os.environ.get("TMPDIR"))
        os.makedirs(os.path.join(self.root, "documents"), exist_ok=True)

    def test_a_clean_send_log_computes_block_within_7_days(self):
        with open(os.path.join(self.root, "documents", "send-log.jsonl"), "w", encoding="utf-8") as f:
            import json, datetime as dt
            f.write(json.dumps({"status": "sent", "company": "Acme Robotics",
                                 "date": dt.date.today().isoformat()}) + "\n")
        p = _run("PYWAIT", ["Acme Robotics", self.root])
        self.assertTrue(p.stdout.startswith("BLOCK"), (p.stdout, p.stderr))

    def test_no_stores_at_all_reads_as_ok_not_a_refusal(self):
        # genuinely nothing on disk yet (fresh install) -- os.path.isfile guards both reads
        p = _run("PYWAIT", ["Acme Robotics", self.root])
        self.assertTrue(p.stdout.startswith("OK"), (p.stdout, p.stderr))

    def test_bad_encoding_in_send_log_refuses_instead_of_reading_as_ok(self):
        with open(os.path.join(self.root, "documents", "send-log.jsonl"), "wb") as f:
            f.write(b'{"status": "sent"}\n\xff\xfe garbage\n')
        p = _run("PYWAIT", ["Acme Robotics", self.root])
        self.assertTrue(p.stdout.startswith("CANTVERIFY"), (p.stdout, p.stderr))

    def test_bad_encoding_in_outreach_log_refuses_instead_of_reading_as_ok(self):
        with open(os.path.join(self.root, "outreach_log.md"), "wb") as f:
            f.write(b"## 2026-01-01 \xff\xfe garbage\n")
        p = _run("PYWAIT", ["Acme Robotics", self.root])
        self.assertTrue(p.stdout.startswith("CANTVERIFY"), (p.stdout, p.stderr))


class BodyVocabularyScan(unittest.TestCase):
    """body_gates.py targets (was the PYBODY heredoc): sys.argv = [data root, bodyfile, targets]. Slice J: the first argument was the scripts dir and is now the DATA ROOT the stage runs on."""

    def setUp(self):
        self.root = tempfile.mkdtemp(dir=os.environ.get("TMPDIR"))
        os.makedirs(os.path.join(self.root, "documents"), exist_ok=True)
        self.here = os.path.join(self.root, "scripts")
        os.makedirs(self.here, exist_ok=True)
        self.bodyfile = os.path.join(self.root, "body.txt")
        with open(self.bodyfile, "w", encoding="utf-8") as f:
            f.write("Hello, I'd love to connect about the role.\n")

    def _run_body(self):
        # BUG-202 item 2: the cross-check moved out of the mail-draft.sh heredoc into scripts/body_gates.py (one source for the send
        # path and preflight_note.py), so the same stores are exercised through its CLI.
        return subprocess.run([sys.executable, os.path.join(KIT, "scripts", "body_gates.py"), "targets",
                               self.root, self.bodyfile, ""], capture_output=True, text=True)

    def test_a_bad_encoding_blocked_list_does_not_silently_count_as_read(self):
        with open(os.path.join(self.root, "documents", "blocked-employers-list.md"), "wb") as f:
            f.write(b"- Acme \xff\xfe garbage\n")
        with open(os.path.join(self.root, "job_search_tracker.csv"), "w", encoding="utf-8") as f:
            f.write("company\nAcme Robotics\n")
        p = self._run_body()
        # the tracker CSV alone is enough to satisfy the positive control -- not blocked
        self.assertEqual(p.returncode, 0, (p.stdout, p.stderr))
        self.assertNotIn("neither known-company store could be read", p.stderr)

    def test_both_stores_bad_encoding_trips_the_positive_control(self):
        with open(os.path.join(self.root, "documents", "blocked-employers-list.md"), "wb") as f:
            f.write(b"- Acme \xff\xfe garbage\n")
        with open(os.path.join(self.root, "job_search_tracker.csv"), "wb") as f:
            f.write(b"company\n\xff\xfe garbage\n")
        p = self._run_body()
        self.assertNotEqual(p.returncode, 0, (p.stdout, p.stderr))
        self.assertIn("neither known-company store could be read", p.stderr)


if __name__ == "__main__":
    unittest.main()
