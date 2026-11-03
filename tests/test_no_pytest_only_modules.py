#!/usr/bin/env python3
"""Guard: a tests/test_*.py file with module-level `def test_...` functions but no
unittest.TestCase subclass is invisible to run_all.sh (unittest discover only), even
though it looks green. This closes the trap found by the 2026-09-15 sweep
(documents/state/zero-test-modules-2026-09-15.md), where test_phase_build.py held 32
plain pytest-style functions that unittest discovered as zero tests.
"""
import ast
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

# This guard module itself and any file explicitly known to be browser/playwright-based
# are not test_*.py files scanned for pytest-only shape issues in the usual sense, but we
# still scan every tests/test_*.py file including this one and the browser ones -- they
# either have no module-level test_ functions (fine) or already use TestCase (fine).


def _module_level_test_functions(tree):
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            names.append(node.name)
    return names


def _has_testcase_subclass(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
                if base_name == "TestCase":
                    return True
    return False


class TestNoPytestOnlyModules(unittest.TestCase):
    def test_every_test_module_is_unittest_discoverable(self):
        tests_dir = HERE
        offenders = []
        for fname in sorted(os.listdir(tests_dir)):
            if not (fname.startswith("test_") and fname.endswith(".py")):
                continue
            path = os.path.join(tests_dir, fname)
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
            tree = ast.parse(source, filename=path)
            has_plain_tests = bool(_module_level_test_functions(tree))
            has_testcase = _has_testcase_subclass(tree)
            if has_plain_tests and not has_testcase:
                offenders.append(fname)
        self.assertEqual(
            offenders, [],
            "pytest-only module(s) invisible to unittest discover: %s" % offenders,
        )


if __name__ == "__main__":
    unittest.main()
