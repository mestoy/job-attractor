#!/usr/bin/env python3
"""BUG-684: a browser test that skips must not read as green (tests/_browser_skip_plugin.py, loaded by tests/conftest.py).

Each case runs pytest in a subprocess on a tiny file of its own that skips the way the real browser files do, with the plugin loaded,
so no browser is needed here. Run: python3 -m unittest tests.test_browser_skips_are_loud"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

SAMPLE = '''
import pytest

def test_a_browser_case():
    pytest.skip("headless Chromium not available at /nowhere")

def test_another_browser_case():
    pytest.skip("playwright is not installed")

def test_an_unrelated_skip():
    pytest.skip("only runs on a Mac")

def test_a_pass():
    assert True
'''


def run_pytest(env_extra, sample=SAMPLE):
    d = tempfile.mkdtemp(prefix="bskip-", dir=os.environ.get("TMPDIR"))
    try:
        fp = os.path.join(d, "test_sample.py")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(sample)
        env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_BROWSERS", "PLAYWRIGHT_BROWSERS_PATH")}
        env.update(env_extra)
        env["PYTHONPATH"] = HERE
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "_browser_skip_plugin", "-p", "no:cacheprovider", "--rootdir", d, fp],
                           env=env, capture_output=True, text=True, cwd=d)
        return p.returncode, p.stdout + p.stderr
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


class BrowserSkipsAreLoud(unittest.TestCase):
    def test_with_nothing_set_the_run_says_so_once_with_the_count_and_both_variables(self):
        code, out = run_pytest({})
        self.assertEqual(code, 0, "without REQUIRE_BROWSERS the run still exits 0; it is loud, not failing")
        loud = [ln for ln in out.splitlines() if ln.startswith("!!")]
        self.assertEqual(len(loud), 1, "exactly one loud line: %r" % out[-600:])
        self.assertIn("2 browser test case(s) were SKIPPED", loud[0], "the count is the browser skips only, not the unrelated one")
        self.assertIn("PLAYWRIGHT_BROWSERS_PATH", loud[0])
        self.assertIn("REQUIRE_BROWSERS=1", loud[0])

    def test_with_require_browsers_a_browser_skip_is_a_failure_that_names_why(self):
        code, out = run_pytest({"REQUIRE_BROWSERS": "1"})
        self.assertNotEqual(code, 0, "a skipped browser case fails the run")
        self.assertIn("2 failed", out)
        self.assertIn("headless Chromium not available at /nowhere", out)
        self.assertIn("REQUIRE_BROWSERS=1 is set", out)
        self.assertNotIn("\n!!", out, "no loud line when the run already fails")

    def test_an_unrelated_skip_stays_a_skip_even_when_browsers_are_required(self):
        only = 'import pytest\ndef test_x():\n    pytest.skip("only runs on a Mac")\ndef test_y():\n    assert True\n'
        code, out = run_pytest({"REQUIRE_BROWSERS": "1"}, only)
        self.assertEqual(code, 0)
        self.assertIn("1 skipped", out)
        self.assertNotIn("!!", out)

    def test_a_module_level_browser_skip_fails_too_when_required(self):
        mod = 'import pytest\npytest.skip("no headless Chromium", allow_module_level=True)\ndef test_x():\n    assert True\n'
        code, out = run_pytest({"REQUIRE_BROWSERS": "1"}, mod)
        self.assertNotEqual(code, 0)
        code2, out2 = run_pytest({}, mod)
        self.assertIn(code2, (0, 5), "pytest's own exit for a file that skipped at collection (5 = nothing collected), not ours")
        self.assertIn("!!", out2)
        self.assertIn("1 browser test case(s) were SKIPPED", out2)

    def test_an_expected_failure_naming_playwright_stays_xfailed_and_is_not_counted(self):
        # pytest reports xfail (and unittest.expectedFailure) as a skip with wasxfail set; its text can name the browser. It is neither a skip nor a failure.
        xf = ('import pytest\n'
              'def test_pytest_xfail():\n    pytest.xfail("known: playwright browser.new_page times out here")\n'
              '@pytest.mark.xfail(reason="headless Chromium flake, BUG-1", strict=False)\n'
              'def test_marked_xfail():\n    raise RuntimeError("browser.new_page failed (chromium)")\n'
              'import unittest\n'
              'class T(unittest.TestCase):\n    @unittest.expectedFailure\n    def test_unittest_expected(self):\n        raise RuntimeError("playwright launch failed")\n'
              'def test_a_pass():\n    assert True\n')
        for env in ({"REQUIRE_BROWSERS": "1"}, {}):
            code, out = run_pytest(env, xf)
            self.assertEqual(code, 0, "an expected failure does not fail the run (env %r): %s" % (env, out[-500:]))
            self.assertIn("3 xfailed", out)
            self.assertNotIn("failed", out.replace("xfailed", ""))
            self.assertNotIn("!!", out, "and it is not counted as a skipped browser case")

    def test_a_bare_word_browser_is_not_a_browser_skip(self):
        # "Safari browser" is a platform skip, not a missing Chromium: only chromium, playwright or headless name the missing tool.
        mac = 'import pytest\ndef test_x():\n    pytest.skip("only on a Mac with Safari browser")\ndef test_y():\n    assert True\n'
        code, out = run_pytest({"REQUIRE_BROWSERS": "1"}, mac)
        self.assertEqual(code, 0, out[-400:])
        self.assertIn("1 skipped", out)
        code, out = run_pytest({}, mac)
        self.assertNotIn("!!", out)

    def test_conftest_loads_the_plugin_so_every_pytest_run_passes_through_it(self):
        with open(os.path.join(HERE, "conftest.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("from _browser_skip_plugin import", src)
        for hook in ("pytest_runtest_makereport", "pytest_make_collect_report", "pytest_terminal_summary"):
            self.assertIn(hook, src.split("_browser_skip_plugin import", 1)[1].split("\n", 1)[0])


if __name__ == "__main__":
    unittest.main()
