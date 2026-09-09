#!/usr/bin/env python3
"""Tests for tests/run_all.sh's live-store drift guard — kit #37.

The guard's `fingerprint()` function hashed an ENUMERATED list of files, and no path under
`documents/state/` was on that list. A test run that mutated a file under `documents/state/`
(`weights-derive.json`, a `company.jsonl` fixture row, ...) went undetected: BEFORE and AFTER
fingerprints matched, so the suite reported clean even though it had corrupted real state.

This pins the fix at the source: it extracts the ACTUAL `fingerprint()` function body out of
tests/run_all.sh (never a reimplementation, so the test can't drift from the product code it is
proving), runs it against a sandboxed repo root with REPO pointed at a temp dir, and asserts that
writing a new file under documents/state/ changes the fingerprint.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_ALL = os.path.join(REPO_ROOT, "tests", "run_all.sh")


def _extract_fingerprint_function():
    src = open(RUN_ALL).read()
    m = re.search(r"\nfingerprint\(\) \{\n(?:.*\n)*?^\}\n", src, re.MULTILINE)
    if not m:
        raise AssertionError("could not locate fingerprint() in tests/run_all.sh — did it move?")
    return m.group(0)


def _run_fingerprint(repo_dir):
    """Runs the real fingerprint() function (sourced verbatim) with REPO set to a sandbox."""
    script = "#!/usr/bin/env bash\nset -uo pipefail\nREPO=%r\n%s\nfingerprint\n" % (
        repo_dir, _extract_fingerprint_function())
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert p.returncode == 0, f"fingerprint() itself failed:\n{p.stdout}\n{p.stderr}"
    return p.stdout


class StateDirectoryFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.mkdtemp(prefix="run_all_fingerprint_")
        os.makedirs(os.path.join(self.sandbox, "documents", "state"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)

    def test_a_new_file_under_documents_state_trips_the_guard(self):
        before = _run_fingerprint(self.sandbox)
        with open(os.path.join(self.sandbox, "documents", "state", "person-weights.jsonl"), "w") as f:
            f.write('{"drifted": true}')
        after = _run_fingerprint(self.sandbox)
        self.assertNotEqual(
            before, after,
            "a write under documents/state/ must change the fingerprint — the guard is blind to "
            "anything not on its enumerated list")

    def test_weights_derive_json_content_change_is_ignored_by_name(self):
        target = os.path.join(self.sandbox, "documents", "state", "weights-derive.json")
        with open(target, "w") as f:
            f.write('{"last_run": "2026-09-08T00:00:00+00:00"}')
        before = _run_fingerprint(self.sandbox)
        with open(target, "w") as f:
            f.write('{"last_run": "2026-09-09T00:00:00+00:00"}')
        after = _run_fingerprint(self.sandbox)
        self.assertEqual(
            before, after,
            "weights-derive.json is a witness file that stamps last_run on every derivation by "
            "design — it must be ignored by name, not trip the guard")

    def test_a_mutated_existing_file_under_documents_state_trips_the_guard(self):
        target = os.path.join(self.sandbox, "documents", "state", "company.jsonl")
        with open(target, "w") as f:
            f.write('{"company": "Acme"}\n')
        before = _run_fingerprint(self.sandbox)
        with open(target, "a") as f:
            f.write('{"company": "Injected"}\n')
        after = _run_fingerprint(self.sandbox)
        self.assertNotEqual(before, after, "editing an existing state file must trip the guard too")


if __name__ == "__main__":
    unittest.main()
