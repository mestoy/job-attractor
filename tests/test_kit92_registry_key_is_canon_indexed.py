"""REAL BUG found by 3f's unmocked v54 review: employers.registry() indexes rows by
row["key"] VERBATIM, while is_blocked() looks up canon(name). A hand-edited or imported row
whose own "key" field isn't already in canon() form is invisible to is_blocked() under its OWN
declared name -- "Northwind Holdings" with key "northwind-holdings" (hyphens, not canon'd) reads
CLEAN, although the row is right there with status "blocked". Fix: canon() the key at index
time, same as aliases already are.
"""
import importlib
import json
import os
import _roots
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import screen_sweep  # noqa: E402
import employers  # noqa: E402


class TestRegistryKeyIsCanonIndexed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        docs = os.path.join(self.tmp.name, "documents")
        os.makedirs(docs, exist_ok=True)
        with open(os.path.join(docs, "blocked-employers-list.md"), "w", encoding="utf-8") as fh:
            fh.write("# Blocked employers\n\n")
        # The declared "key" is NOT canon() form: it keeps a hyphen, canon() strips punctuation
        # entirely. A hand-edited or imported row is exactly how this shape reaches the file --
        # declare_blocked() itself always writes canon(display), so this simulates the other path.
        with open(os.path.join(docs, "employers.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "key": "northwind-holdings",
                "display": "Northwind Holdings",
                "aliases": [],
                "status": "blocked",
            }) + "\n")

        self._restore_roots = _roots.set_roots(self.tmp.name)
        self._real_repo = screen_sweep.REPO
        screen_sweep.REPO = self.tmp.name
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        self.addCleanup(self._restore)
        self.employers = importlib.reload(employers)

    def _restore(self):
        self._restore_roots()
        screen_sweep.REPO = self._real_repo
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        importlib.reload(employers)

    def test_a_non_canon_key_row_still_blocks_under_its_own_declared_name(self):
        self.assertTrue(self.employers.is_blocked("Northwind Holdings"))

    def test_b_the_canon_form_of_the_key_is_in_blocked_keys(self):
        self.assertIn(screen_sweep.canon("northwind-holdings"), self.employers.blocked_keys())


if __name__ == "__main__":
    unittest.main()
