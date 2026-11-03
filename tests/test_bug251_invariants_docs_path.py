"""BUG-251 (seat 90): check_rulings.py looked for HARD-INVARIANTS.md under documents/ or
partner-docs/ only; partner-starter itself keeps it at docs/, so the check always reported
"unreadable" and exited 2 on this install.

Fictional two-directory fixture, not dependent on which real path this particular repo
checkout happens to ship the file under.
"""
import importlib
import os
import _roots
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))

import check_rulings  # noqa: E402


class Bug251InvariantsDocsPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bug251-")
        self._restore_roots = _roots.set_roots(self.tmp)

    def tearDown(self):
        self._restore_roots()
        importlib.reload(check_rulings)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_docs_hard_invariants_is_found_when_no_other_copy_exists(self):
        docs_dir = os.path.join(self.tmp, "docs")
        os.makedirs(docs_dir)
        expected = os.path.join(docs_dir, "HARD-INVARIANTS.md")
        with open(expected, "w", encoding="utf-8") as fh:
            fh.write("# fictional invariants fixture\n")
        importlib.reload(check_rulings)
        self.assertEqual(check_rulings.INVARIANTS, expected)


if __name__ == "__main__":
    unittest.main()
