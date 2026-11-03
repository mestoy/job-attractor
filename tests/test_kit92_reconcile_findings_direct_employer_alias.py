"""kit#92, second mechanism, second Step 0 script: reconcile_findings.py's SURVIVOR gate keyed
off `blocked_keys` (built once from blocked_keys_from_list(), transitively registry-aware when
available) with no DIRECT employers.is_blocked() call. Widen-only addition mirrors the
filter_blocked.py fix: a survivor is never banked on a path where the transitive registry
lookup misses.
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
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)

import screen_sweep  # noqa: E402
import employers  # noqa: E402


class TestReconcileDirectEmployerAliasWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        docs = os.path.join(self.tmp.name, "documents")
        findings = os.path.join(docs, "findings")
        os.makedirs(findings, exist_ok=True)
        with open(os.path.join(docs, "blocked-employers-list.md"), "w", encoding="utf-8") as fh:
            fh.write("# Blocked employers\n\n- **Fakemonth Corp** (blocked, filter 8)\n")
        with open(os.path.join(docs, "employers.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "key": screen_sweep.canon("Fakemonth Corp"),
                "display": "Fakemonth Corp",
                "aliases": ["FKM"],
                "status": "blocked",
            }) + "\n")
        # one SURVIVOR row naming the alias -- a real screen agent would never write "Fakemonth
        # Corp" here since that's the declared name; the whole point of an alias is it looks like
        # a DIFFERENT, clean company to anyone not consulting the registry.
        with open(os.path.join(findings, "run1.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "company": "FKM", "verdict": "SURVIVOR", "ts": "2026-09-26T00:00:00Z",
                "lane": "test",
            }) + "\n")

        self._restore_roots = _roots.set_roots(self.tmp.name)
        self._real_repo = screen_sweep.REPO
        screen_sweep.REPO = self.tmp.name
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        self.addCleanup(self._restore)
        importlib.reload(employers)
        self.rf = importlib.reload(importlib.import_module("reconcile_findings"))

    def _restore(self):
        self._restore_roots()
        screen_sweep.REPO = self._real_repo
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        importlib.reload(employers)
        importlib.reload(importlib.import_module("reconcile_findings"))

    def test_a_alias_survivor_is_not_banked_when_the_transitive_lookup_misses(self):
        # Simulate the transitive path missing (the exact class of failure the direct call
        # exists to catch), isolating whether the NEW direct is_blocked() call actually fires.
        with mock.patch.object(self.rf, "blocked_keys_from_list", return_value=set()):
            rc = self.rf.reconcile(dry=True)
        self.assertEqual(rc, 0, "a banked alias-blocked survivor should have skipped, not written")

    def test_b_transitive_path_alone_still_catches_it_unmocked(self):
        rc = self.rf.reconcile(dry=True)
        self.assertEqual(rc, 0)

    def test_c_no_registry_present_behaves_as_before_no_crash(self):
        os.remove(os.path.join(self.tmp.name, "documents", "employers.jsonl"))
        importlib.reload(employers)
        self.rf = importlib.reload(importlib.import_module("reconcile_findings"))
        self.assertFalse(employers.available())
        # An unrelated survivor with no registry at all must still reconcile cleanly.
        with open(os.path.join(self.tmp.name, "documents", "findings", "run2.jsonl"),
                  "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "company": "Some Unrelated Startup", "verdict": "SURVIVOR",
                "ts": "2026-09-26T00:00:01Z", "lane": "test",
            }) + "\n")
        rc = self.rf.reconcile(only_run="run2", dry=True)
        self.assertEqual(rc, 1)  # a real, clean survivor: banked, needs review (dry)


if __name__ == "__main__":
    unittest.main()
