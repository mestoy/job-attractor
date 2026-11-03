"""BUG-784: a SomeCo fixture send landed in the owner's REAL logs (send-log.jsonl, correspondence-log.md, outreach_log.md).

⛔ WHAT HAPPENED (2026-10-28 16:25:35 UTC, found by a reviewer's transcript, not by a test). A reviewer ran
`CLAUDE_PROJECT_DIR=<the real install> python3 -m pytest tests/test_bug254_from_address.py tests/test_mail_draft_says_what_it_actually_did.py`
against an archive of 73bd1672, the tree BEFORE a402ab2f taught those two tests to strip the root variables. The result line (16:25:35.7)
read "4 failed, 8 passed" and the row's own ts is 16:25:35. mail-draft.sh resolves its data root as --repo, else JOBSEARCH_DATA_ROOT, else
CLAUDE_PROJECT_DIR, else its own folder (BUG-773), so the copy of the script in the test sandbox wrote to the real install. The script did
what it was built to do. The hole is in the TESTS: any test that runs a copy of a script and inherits the session's root variable writes
outside its sandbox, and a402ab2f fixed two tests by hand while the next one to be written would leak the same way.

THE FIX IS AT THE PACKAGE. Importing `tests` (or harness) now removes both ambient root variables from this process, so a test that forgets
to set its own roots resolves its sandbox copy, never the session's install. tests/_tree_guard.py also refuses a run whose real install
carries a fixture send.

⚠️ NEVER RUN THE SHIPPING SCRIPT WITH THE REAL INSTALL IN REACH. Every run below points at a CANARY, a temp install of its own (a `.git` marker, a
scripts/kit_config.py, and the three log files). If this bug were live, the canary takes the row, not the owner's logs.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402
import _tree_guard  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
LOGS = ("documents/send-log.jsonl", "documents/correspondence-log.md", "outreach_log.md")

# An UNPROTECTED test, the way the two pre-a402ab2f tests were written: copy the scripts into a sandbox, run the copy with whatever
# environment the process inherited, read the row back from the sandbox. PRELUDE decides whether the tests package is imported first.
PROBE = r'''
import json, os, shutil, subprocess, sys
{prelude}
sb = sys.argv[1]
os.makedirs(os.path.join(sb, "documents"))
shutil.copytree(sys.argv[2], os.path.join(sb, "scripts"))
binp = os.path.join(sb, "bin"); os.makedirs(binp)
for stub in ("osascript", "dig"):
    f = os.path.join(binp, stub)
    open(f, "w").write("#!/bin/sh\nexit 0\n"); os.chmod(f, 0o755)
body = os.path.join(sb, "body.txt"); open(body, "w").write("Hi, Jane!\n\nGood to reconnect, no ask.\n")
env = dict(os.environ, PATH=binp + os.pathsep + os.environ.get("PATH", ""))
subprocess.run(["bash", os.path.join(sb, "scripts", "mail-draft.sh"), "--to", "jane@example.test", "--subject", "Hello", "--body-file", body,
                "--rung", "warm", "--no-resume", "--force", "--targets", "SomeCo", "--name", "Jane Doe"],
               capture_output=True, text=True, env=env, timeout=300)
p = os.path.join(sb, "documents", "send-log.jsonl")
print(json.dumps([json.loads(l) for l in open(p)] if os.path.exists(p) else []))
'''


def _walk(root):
    """{relative path: (sha256, mtime_ns)} for every file under root, so an untouched canary is proven byte for byte and stamp for stamp."""
    out = {}
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for n in sorted(files):
            p = os.path.join(d, n)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = (hashlib.sha256(fh.read()).hexdigest(), os.stat(p).st_mtime_ns)
    return out


class TestMailDraftNeverWritesOutsideItsSandbox(unittest.TestCase):
    def setUp(self):
        base = scratch_root()
        self.work = tempfile.mkdtemp(prefix="bug784-", dir=base)
        self.addCleanup(shutil.rmtree, self.work, True)
        self.canary = os.path.join(self.work, "canary")
        os.makedirs(os.path.join(self.canary, "documents"))
        os.makedirs(os.path.join(self.canary, "scripts"))
        os.makedirs(os.path.join(self.canary, ".git"))                       # the marker of an install the owner would call real
        for rel in LOGS:
            with open(os.path.join(self.canary, rel), "w", encoding="utf-8") as fh:
                fh.write("canary: owner's real record, must never change\n")
        with open(os.path.join(self.canary, "scripts", "kit_config.py"), "w", encoding="utf-8") as fh:
            fh.write("# canary install config\n")
        self.before = _walk(self.canary)

    def _probe(self, prelude, canary_vars=("CLAUDE_PROJECT_DIR", "JOBSEARCH_DATA_ROOT")):
        env = dict(os.environ)
        for k in ("CLAUDE_PROJECT_DIR", "JOBSEARCH_DATA_ROOT", "JOBSEARCH_TEST"):
            env.pop(k, None)
        for k in canary_vars:
            env[k] = self.canary
        sb = os.path.join(self.work, "sandbox-%d" % len(os.listdir(self.work)))
        run = subprocess.run([sys.executable, "-c", PROBE.format(prelude=prelude), sb, SCRIPTS], capture_output=True, text=True, env=env,
                             cwd=REPO, timeout=300)
        self.assertEqual(0, run.returncode, "the probe itself failed:\n" + run.stderr[-1500:])
        return json.loads(run.stdout.strip().splitlines()[-1])

    def _canary_unchanged(self):
        self.assertEqual(self.before, _walk(self.canary), "a send landed in the canary install: the owner's real logs would have taken it")

    def test_control_without_the_package_the_canary_takes_the_row(self):
        """A control. mail-draft.sh follows the session's root variable (BUG-773, by design), so a test that inherits it and does not import the
        tests package DOES write the canary. Without this, the passing cases below could be an empty check."""
        rows = self._probe("")
        self.assertEqual([], rows, "the sandbox got the row, so this run did not exercise the inherited root")
        self.assertNotEqual(self.before, _walk(self.canary), "the control did not reach the canary; the cases below prove nothing")

    def test_importing_the_tests_package_keeps_both_variables_off_the_run(self):
        for keys in (("CLAUDE_PROJECT_DIR", "JOBSEARCH_DATA_ROOT"), ("CLAUDE_PROJECT_DIR",), ("JOBSEARCH_DATA_ROOT",)):
            with self.subTest(ambient=keys):
                rows = self._probe("import tests", keys)
                self._canary_unchanged()
                self.assertEqual(1, len(rows), "the sandbox did not receive the send: %r" % rows)
                self.assertEqual(("Jane Doe", "SomeCo", "SomeCo"), (rows[0].get("to_name"), rows[0].get("company"), rows[0].get("targets")))

    def test_importing_the_harness_does_the_same(self):
        rows = self._probe("import sys; sys.path.insert(0, 'tests'); import harness")
        self._canary_unchanged()
        self.assertEqual(1, len(rows), "the sandbox did not receive the send: %r" % rows)

    def test_the_two_named_tests_stay_inside_their_sandbox_under_an_ambient_canary(self):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.canary, JOBSEARCH_DATA_ROOT=self.canary)
        run = subprocess.run([sys.executable, "-m", "unittest", "tests.test_mail_draft_says_what_it_actually_did", "tests.test_bug254_from_address"],
                             capture_output=True, text=True, env=env, cwd=REPO, timeout=600)
        self.assertEqual(0, run.returncode, "those two tests failed under an ambient canary:\n" + (run.stdout + run.stderr)[-1500:])
        self._canary_unchanged()


class TestFixtureStringsInTheRealLogs(unittest.TestCase):
    """_tree_guard also refuses a run whose real install carries the SomeCo fixture send (the tell of BUG-784)."""

    def _layout(self, send_log="", outreach=""):
        top = tempfile.mkdtemp(prefix="bug784-guard-", dir=scratch_root())
        self.addCleanup(shutil.rmtree, top, True)
        kit = os.path.join(top, "partner-starter")
        os.makedirs(kit)
        os.makedirs(os.path.join(top, "documents"))
        for rel, text in (("documents/send-log.jsonl", send_log), ("documents/correspondence-log.md", ""), ("outreach_log.md", outreach)):
            with open(os.path.join(top, rel), "w", encoding="utf-8") as fh:
                fh.write(text)
        return kit, top

    def test_clean_logs_report_nothing(self):
        kit, _ = self._layout('{"company": "Realco", "to": "a@real.example"}\n', "STAGED Realco\n")
        self.assertEqual([], _tree_guard.fixture_leaks(kit))

    def test_each_fixture_string_in_each_log_is_named(self):
        for text in ("SomeCo", "jane@example.test", "Jane Doe"):
            with self.subTest(string=text):
                kit, _ = self._layout('{"company": "%s"}\n' % text, "")
                self.assertEqual(["documents/send-log.jsonl"], _tree_guard.fixture_leaks(kit))
                kit2, _ = self._layout("", "STAGED %s\n" % text)
                self.assertEqual(["outreach_log.md"], _tree_guard.fixture_leaks(kit2))

    def test_a_kit_with_no_real_install_above_it_is_not_scanned(self):
        top = tempfile.mkdtemp(prefix="bug784-alone-", dir=scratch_root())
        self.addCleanup(shutil.rmtree, top, True)
        kit = os.path.join(top, "kit")
        os.makedirs(kit)
        self.assertEqual([], _tree_guard.fixture_leaks(kit))

    def test_the_guard_leaves_with_status_3_and_names_the_file(self):
        kit, _ = self._layout('{"company": "SomeCo"}\n', "")
        left = []
        out = _tree_guard.check_fixture_leaks(kit, leave=left.append)
        self.assertEqual(["documents/send-log.jsonl"], out)
        self.assertEqual([3], left)


if __name__ == "__main__":
    unittest.main()
