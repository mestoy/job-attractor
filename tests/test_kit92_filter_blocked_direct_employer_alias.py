"""kit#92, second mechanism: employers.is_blocked() (each entity's own `aliases` array) was
never called directly by filter_blocked.py -- only reachable transitively, when it happens to
be reachable at all, through check_dup.blocked_key_hit() -> screen_sweep.blocked_keys_from_list()
-> employers.blocked_keys(). classify() now also calls employers.is_blocked() directly, so a
registry alias blocks even on a path where blocked_key_hit() itself misses -- widening only,
never narrowing an existing refusal.

Verified separately (5 ways) that the transitive path already catches a plain registry-alias
case end to end; this test isolates the NEW direct call so it is provably wired and provably
inert (never removes a refusal, never crashes) when the registry is absent.
"""
import importlib
import json
import os
import _roots
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import screen_sweep  # noqa: E402
import employers  # noqa: E402
import filter_blocked  # noqa: E402


class TestDirectEmployerAliasWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        docs = os.path.join(self.tmp.name, "documents")
        os.makedirs(docs, exist_ok=True)
        with open(os.path.join(docs, "blocked-employers-list.md"), "w", encoding="utf-8") as fh:
            fh.write("# Blocked employers\n\n- **Fakemonth Corp** (blocked, filter 8)\n")
        with open(os.path.join(docs, "employers.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "key": screen_sweep.canon("Fakemonth Corp"),
                "display": "Fakemonth Corp",
                "aliases": ["FKM"],
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

    def test_a_registry_alias_blocks_even_when_blocked_key_hit_itself_misses(self):
        # Simulates a path where the transitive route misses (a stale/mocked check_dup layer),
        # isolating whether classify()'s OWN direct employers.is_blocked() call is truly wired.
        with mock.patch.object(filter_blocked, "blocked_key_hit", return_value=None):
            status, detail = filter_blocked.classify("FKM")
        self.assertEqual(status, "BLOCKED")

    def test_b_an_existing_refusal_is_never_removed(self):
        # The transitive path alone already blocks the declared name; the new code must not
        # somehow short-circuit past that existing refusal.
        status, detail = filter_blocked.classify("Fakemonth Corp")
        self.assertEqual(status, "BLOCKED")

    def test_c_no_registry_present_behaves_exactly_as_before_no_crash(self):
        os.remove(os.path.join(self.tmp.name, "documents", "employers.jsonl"))
        importlib.reload(employers)
        self.assertFalse(employers.available())
        status, detail = filter_blocked.classify("Some Unrelated Startup")
        self.assertEqual(status, "CLEAN")

    def test_d_unrelated_company_stays_clean(self):
        status, detail = filter_blocked.classify("Some Unrelated Startup")
        self.assertEqual(status, "CLEAN")


if __name__ == "__main__":
    unittest.main()
