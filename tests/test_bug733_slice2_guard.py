#!/usr/bin/env python3
"""BUG-733 option B, slice 2: the kit-tree fence (tests/_tree_guard.py) really fails a process, and cleans up after itself.

The probes run a CHILD python process against a throwaway copy of a tiny documents tree (JA_TREE_GUARD_ROOT), so the real
partner-starter/documents is never written. Names are fictional."""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _tree_guard  # noqa: E402


def _child(root, body, tmp_cleanup_first=False):
    """Run `body` in a child that installs the guard the way tests/__init__.py does (guard BEFORE tmp_cleanup)."""
    code = textwrap.dedent("""
        import os, sys
        sys.path.insert(0, %r)
        import _tree_guard
        import tmp_cleanup
        import tempfile
    """ % HERE) + textwrap.dedent(body)
    env = dict(os.environ, JA_TREE_GUARD_ROOT=root)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="treeguard-")
        self.addCleanup(__import__("shutil").rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "documents", "state"))
        with open(os.path.join(self.root, "documents", "state", "a.jsonl"), "w") as fh:
            fh.write("one\n")

    def test_diff_names_added_changed_and_removed(self):
        before = _tree_guard.snapshot(self.root)
        with open(os.path.join(self.root, "documents", "state", "a.jsonl"), "a") as fh:
            fh.write("two\n")
        with open(os.path.join(self.root, "documents", "new.md"), "w") as fh:
            fh.write("x")
        self.assertEqual(["documents/new.md", "documents/state/a.jsonl"], _tree_guard.diff(before, _tree_guard.snapshot(self.root)))
        os.remove(os.path.join(self.root, "documents", "state", "a.jsonl"))
        self.assertIn("documents/state/a.jsonl", _tree_guard.diff(before, _tree_guard.snapshot(self.root)))

    def test_the_exempt_witness_file_is_not_counted(self):
        before = _tree_guard.snapshot(self.root)
        with open(os.path.join(self.root, "documents", "state", "weights-derive.json"), "w") as fh:
            fh.write("{}")
        self.assertEqual([], _tree_guard.diff(before, _tree_guard.snapshot(self.root)))

    def test_an_empty_snapshot_is_not_a_pass_it_sees_the_file(self):
        self.assertEqual(["documents/state/a.jsonl"], sorted(_tree_guard.snapshot(self.root)))


class TheProbe(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="treeguard-probe-")
        self.addCleanup(__import__("shutil").rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "documents", "state"))
        with open(os.path.join(self.root, "documents", "state", "a.jsonl"), "w") as fh:
            fh.write("one\n")

    def test_a_write_under_documents_ends_the_process_with_3_names_the_path_and_removes_its_sandbox(self):
        r = _child(self.root, """
            d = tempfile.mkdtemp(prefix="probe-sandbox-")
            print(d)
            open(os.path.join(os.environ["JA_TREE_GUARD_ROOT"], "documents", "state", "probe.jsonl"), "w").write("x")
        """)
        sandbox = r.stdout.strip().splitlines()[-1]
        self.assertEqual(3, r.returncode, r.stdout + r.stderr)
        self.assertIn("documents/state/probe.jsonl", r.stderr)
        self.assertIn("changed during this run", r.stderr)
        self.assertFalse(os.path.exists(sandbox), "the guard's os._exit must not leave this process's temp dir behind")

    def test_a_clean_run_exits_0_and_removes_its_sandbox_too(self):
        r = _child(self.root, """
            d = tempfile.mkdtemp(prefix="probe-sandbox-")
            print(d)
        """)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(r.stdout.strip().splitlines()[-1]))

    def test_a_change_to_the_exempt_file_alone_does_not_fail_the_run(self):
        r = _child(self.root, """
            open(os.path.join(os.environ["JA_TREE_GUARD_ROOT"], "documents", "state", "weights-derive.json"), "w").write("{}")
        """)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)

    def test_a_write_to_a_root_data_file_fails_the_run_too(self):
        open(os.path.join(self.root, "outreach_log.md"), "w").write("# log\n")
        r = _child(self.root, """
            open(os.path.join(os.environ["JA_TREE_GUARD_ROOT"], "outreach_log.md"), "a").write("leak\\n")
        """)
        self.assertEqual(3, r.returncode, r.stdout + r.stderr)
        self.assertIn("outreach_log.md", r.stderr)

    def test_a_deleted_file_fails_the_run(self):
        r = _child(self.root, """
            os.remove(os.path.join(os.environ["JA_TREE_GUARD_ROOT"], "documents", "state", "a.jsonl"))
        """)
        self.assertEqual(3, r.returncode, r.stdout + r.stderr)

    def test_the_real_tree_is_never_written_by_this_file(self):
        real = _tree_guard.snapshot(os.path.dirname(HERE))
        self.addCleanup(lambda: self.assertEqual(real, _tree_guard.snapshot(os.path.dirname(HERE))))


class ThePackageInstallsIt(unittest.TestCase):
    def test_tests_init_imports_the_guard_before_tmp_cleanup(self):
        src = open(os.path.join(HERE, "__init__.py"), encoding="utf-8").read()
        self.assertIn("\nimport _tree_guard", src)
        self.assertNotIn("import tmp_cleanup", src.split("\nimport _tree_guard")[0])

    def test_harness_imports_the_guard_before_tmp_cleanup(self):
        src = open(os.path.join(HERE, "harness.py"), encoding="utf-8").read()
        self.assertLess(src.index("import _tree_guard"), src.index("import tmp_cleanup"))


if __name__ == "__main__":
    unittest.main()
