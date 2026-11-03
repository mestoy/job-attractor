"""BUG-718 C1b (slice 1c-ii): a change made AFTER the person pressed Send is never given up. When the send-log lock is busy, the partner
confirm_sent and the main append spool the change (sendlog_lock.spool) instead of raising SendLogBusy, and say so on stderr.
Fixture only: a temp project, invented names, never a live send-log."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
SCRATCH = "/home/vscode/render" if os.path.isdir("/home/vscode/render") else None


def _load():
    spec = importlib.util.spec_from_file_location("lls_busy_under_test", os.path.join(SCRIPTS, "log_linkedin_send.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Busy(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="busy-", dir=SCRATCH)
        self.addCleanup(shutil.rmtree, self.d, True)
        os.makedirs(os.path.join(self.d, "documents"))
        self.log = os.path.join(self.d, "documents", "send-log.jsonl")
        with open(self.log, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"to": "pat@fixture.example", "status": "drafted", "company": "Zzyx Fakeco", "subject": "Hello",
                                 "date": "2026-11-01", "channel": "email"}) + "\n")
        _old = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = self.d      # the module reads REPO at import: keep every log path inside the temp project
        self.addCleanup(lambda: os.environ.pop("CLAUDE_PROJECT_DIR", None) if _old is None else os.environ.__setitem__("CLAUDE_PROJECT_DIR", _old))
        self.lls = _load()
        self.sl = self.lls.sl

    @contextlib.contextmanager
    def _busy(self):
        real = self.sl.locked

        @contextlib.contextmanager
        def always_busy(*a, **k):
            raise self.lls.SendLogBusy("held by another writer")
            yield
        self.sl.locked = always_busy
        try:
            yield
        finally:
            self.sl.locked = real

    def test_confirm_sent_spools_when_the_lock_is_busy(self):
        err = io.StringIO()
        with self._busy(), contextlib.redirect_stderr(err):
            row, _state = self.lls.confirm_sent("pat@fixture.example", path=self.log, company="Zzyx Fakeco", subject="Hello")
        self.assertTrue(row.get("_spooled"))
        self.assertIn("spooled", err.getvalue())
        spool = os.path.join(self.d, "documents", "send-log.pending.jsonl")
        self.assertTrue(os.path.exists(spool) and open(spool, encoding="utf-8").read().strip(), "the change is on disk in the spool")
        self.assertEqual(json.loads(open(self.log, encoding="utf-8").readline())["status"], "drafted")

    def test_the_spooled_change_is_seen_by_a_reader_and_folds_in_later(self):
        with self._busy(), contextlib.redirect_stderr(io.StringIO()):
            self.lls.confirm_sent("pat@fixture.example", path=self.log, company="Zzyx Fakeco", subject="Hello")
        with self.sl.open_lines(self.log, "ignore") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        self.assertEqual(rows[0]["status"], "sent")
        self.assertEqual(rows[0]["sent_confirmed_by"], self.lls._CONFIRMED_BY)

    def test_the_confirmed_by_value_is_the_owner_word(self):
        self.assertEqual(self.lls._CONFIRMED_BY, self.lls.OWNER_FIRST.lower())

    def test_the_command_says_the_change_is_spooled_on_stdout(self):
        out, err = io.StringIO(), io.StringIO()
        with self._busy(), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.lls.main(["--confirm-sent", "--to", "pat@fixture.example", "--company", "Zzyx Fakeco",
                                  "--subject", "Hello", "--path", self.log])
        self.assertEqual(code, 0)
        self.assertIn("the send-log change is spooled; the next writer folds it in", out.getvalue())


if __name__ == "__main__":
    unittest.main()
