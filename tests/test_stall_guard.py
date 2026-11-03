#!/usr/bin/env python3
"""BUG-568: a browser test that waits on something that never comes holds the shared slot for every seat, and a hang guards nothing. tests/stall_guard.py gives a test a HARD time budget:
when it runs out the test FAILS LOUDLY (an AssertionError that names the test and the budget, with every thread's stack dumped to stderr) instead of waiting forever. This file tests the
guard itself with plain Python hangs (no browser, so it runs anywhere): a loop that never ends, a sleep that is too long, a hang in a class fixture and in a cleanup; a fast test and a test
that fails for its own reason are left exactly as they were. Run: python3 -m unittest tests.test_stall_guard
"""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stall_guard   # noqa: E402

BUDGET = 1      # seconds, for the tests below


class F(object):
    """The deliberately bad tests, held in a plain class so unittest discovery never runs them as real tests."""

    class Hangs(unittest.TestCase):
        def test_a_loop_that_never_ends(self):
            while True:
                time.sleep(0.01)

        def test_a_wait_that_is_far_too_long(self):
            time.sleep(30)

        def test_fast(self):
            pass

        def test_fails_for_its_own_reason(self):
            self.assertEqual(1, 2, "my own message")

        def test_a_busy_loop_in_python_code(self):
            n = 0
            while True:
                n += 1

        # R215: a test that WRAPS the hang in a broad except used to swallow the stall and PASS
        def test_swallowed_by_except_exception(self):
            try:
                time.sleep(30)
            except Exception:
                pass

        def test_swallowed_by_a_bare_except(self):
            try:
                time.sleep(30)
            except:      # noqa: E722
                pass

        def test_swallowed_by_except_base_exception(self):
            try:
                time.sleep(30)
            except BaseException:
                pass

        def test_swallowed_then_it_raises_something_else(self):
            try:
                time.sleep(30)
            except BaseException:
                raise ValueError("a different failure after the stall was swallowed")

    class HangsInTheClassFixture(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            time.sleep(30)

        def test_never_reached(self):
            pass


    class HangsInACleanup(unittest.TestCase):
        def test_passes_but_its_cleanup_hangs(self):
            self.addCleanup(time.sleep, 30)


    class FromAnotherModule(unittest.TestCase):
        """A base nobody bounds: ReturningPerson (in another test module) is one, and its tests run inside test_bug403_headers's classes."""

        def test_a_loop_that_never_ends(self):
            while True:
                time.sleep(0.01)

    class Inherited(FromAnotherModule):
        """Tests come in through inheritance too, from a base class that was never bounded itself."""




for _cls in (F.Hangs, F.HangsInTheClassFixture, F.HangsInACleanup, F.Inherited):
    stall_guard.bound_class(_cls, BUDGET)
del _cls          # a leftover module name that is a TestCase would be discovered and run as a real test


def run(case, name):
    result = unittest.TestResult()
    started = time.monotonic()
    suite = unittest.TestSuite([case(name)] if name else [unittest.defaultTestLoader.loadTestsFromTestCase(case)])
    suite.run(result)
    return result, time.monotonic() - started


class TheGuard(unittest.TestCase):
    def setUp(self):
        self._abort = stall_guard.ABORT_ON_FIXTURE_STALL
        stall_guard.ABORT_ON_FIXTURE_STALL = False                                                # these tests want to SEE a failure; the abort is tested in a child process below
        self.addCleanup(setattr, stall_guard, "ABORT_ON_FIXTURE_STALL", self._abort)

    def failure_text(self, result):
        return "\n".join(t for _c, t in result.failures + result.errors)

    def test_an_endless_loop_fails_loudly_inside_the_budget(self):
        for name in ("test_a_loop_that_never_ends", "test_a_wait_that_is_far_too_long", "test_a_busy_loop_in_python_code"):
            result, took = run(F.Hangs, name)
            self.assertEqual(len(result.failures), 1, (name, result.failures, result.errors))
            self.assertIn("stalled", self.failure_text(result))
            self.assertIn(name, self.failure_text(result))
            self.assertIn("%d s" % BUDGET, self.failure_text(result))
            self.assertLess(took, BUDGET + 3, name)

    def test_a_test_that_swallows_the_stall_still_FAILS(self):
        for name in ("test_swallowed_by_except_exception", "test_swallowed_by_a_bare_except", "test_swallowed_by_except_base_exception"):
            result, took = run(F.Hangs, name)
            self.assertEqual(len(result.failures), 1, (name, result.failures, result.errors))
            self.assertIn("stalled", self.failure_text(result), name)
            self.assertLess(took, BUDGET + 3, name)

    def test_a_stall_swallowed_and_followed_by_another_error_is_still_reported_as_the_stall(self):
        result, _t = run(F.Hangs, "test_swallowed_then_it_raises_something_else")
        text = self.failure_text(result)
        self.assertEqual(len(result.failures) + len(result.errors), 1)
        self.assertIn("stalled", text)
        self.assertEqual(len(result.failures), 1, "it must be the stall (a failure), not the ValueError (an error)")

    def test_a_loop_that_swallows_every_interruption_ends_the_run_with_exit_75(self):
        """The last resort: an alarm that is swallowed again and again must not hold the slot. After a few more firings the run is ended at once (exit 75)."""
        import subprocess
        code = (
            "import sys, time, unittest\n"
            "sys.path.insert(0, %r)\n"
            "import stall_guard\n"
            "class T(unittest.TestCase):\n"
            "    def test_swallows_forever(self):\n"
            "        while True:\n"
            "            try: time.sleep(0.05)\n"
            "            except BaseException: pass\n"
            "stall_guard.bound_class(T, 1)\n"
            "stall_guard.timed_main(argv=['x'])\n") % HERE
        started = time.monotonic()
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        took = time.monotonic() - started
        self.assertEqual(done.returncode, stall_guard.EXIT_STALLED, done.stderr[-600:])
        self.assertIn("ABORTED", done.stderr)
        self.assertIn("swallowed", done.stderr)
        self.assertLess(took, 12)

    def test_a_fast_test_and_a_test_that_fails_for_its_own_reason_are_left_alone(self):
        result, _t = run(F.Hangs, "test_fast")
        self.assertEqual((result.testsRun, result.failures, result.errors), (1, [], []))
        result, _t = run(F.Hangs, "test_fails_for_its_own_reason")
        self.assertEqual(len(result.failures), 1)
        self.assertIn("my own message", self.failure_text(result))
        self.assertNotIn("stalled", self.failure_text(result))

    def test_a_hang_in_the_class_fixture_fails_loudly(self):
        result, took = run(F.HangsInTheClassFixture, None)
        self.assertTrue(result.errors or result.failures)
        self.assertIn("stalled", self.failure_text(result))
        self.assertLess(took, BUDGET + 3)

    def test_a_hang_in_a_cleanup_fails_loudly(self):
        result, took = run(F.HangsInACleanup, "test_passes_but_its_cleanup_hangs")
        self.assertTrue(result.errors or result.failures)
        self.assertIn("stalled", self.failure_text(result))
        self.assertLess(took, BUDGET + 3)

    def test_inherited_tests_are_bounded_too(self):
        result, took = run(F.Inherited, "test_a_loop_that_never_ends")
        self.assertEqual(len(result.failures), 1)
        self.assertLess(took, BUDGET + 3)

    def test_the_alarm_is_cleared_and_the_handler_restored_after_every_test(self):
        import signal
        before = signal.getsignal(signal.SIGALRM)
        run(F.Hangs, "test_fast")
        run(F.Hangs, "test_a_loop_that_never_ends")
        self.assertEqual(signal.alarm(0), 0)
        self.assertEqual(signal.getsignal(signal.SIGALRM), before)

    def test_run_through_timed_main_a_stall_in_a_cleanup_aborts_the_whole_run_with_exit_75(self):
        """A page that spins forever cannot be closed, so after a stall the run must END (releasing the shared slot), not wait on the next cleanup."""
        import subprocess
        code = (
            "import sys, time, unittest\n"
            "sys.path.insert(0, %r)\n"
            "import stall_guard\n"
            "class T(unittest.TestCase):\n"
            "    def test_hang(self):\n"
            "        self.addCleanup(time.sleep, 30)\n"
            "        while True: time.sleep(0.01)\n"
            "    def test_zzz_after(self):\n"
            "        print('SHOULD NOT RUN')\n"
            "stall_guard.bound_class(T, 1)\n"
            "stall_guard.timed_main(argv=['x'])\n") % HERE
        started = time.monotonic()
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        took = time.monotonic() - started
        self.assertEqual(done.returncode, stall_guard.EXIT_STALLED, done.stderr[-600:])
        self.assertIn("ABORTED", done.stderr)
        self.assertIn("test_hang", done.stderr)
        self.assertIn("stalled for", done.stderr)
        self.assertNotIn("SHOULD NOT RUN", done.stdout + done.stderr)
        self.assertLess(took, 15)

    def test_a_clean_run_through_timed_main_prints_the_seconds_per_test_and_exits_0(self):
        import subprocess
        code = ("import sys, unittest\nsys.path.insert(0, %r)\nimport stall_guard\n"
                "class T(unittest.TestCase):\n    def test_ok(self): pass\nstall_guard.bound_class(T, 5)\nstall_guard.timed_main(argv=['x'])\n") % HERE
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-600:])
        self.assertRegex(done.stderr, r"test_ok .* ok")
        self.assertRegex(done.stderr, r"\([0-9.]+ s\)")

    def test_the_default_budgets_are_the_ones_the_docstring_promises(self):
        """Raising a budget to make a slow test pass is how a stall guard dies; if one must change, this test changes with it and the reason is in the diff."""
        self.assertEqual((stall_guard.DEFAULT_SECONDS, stall_guard.FIXTURE_SECONDS, stall_guard.CLEANUP_SECONDS), (60, 45, 30))

    def test_the_budget_comes_from_the_environment_when_none_is_given(self):
        old = os.environ.get("KIT_TEST_STALL_SECONDS")
        os.environ["KIT_TEST_STALL_SECONDS"] = "7"
        try:
            self.assertEqual(stall_guard.budget(), 7)
            os.environ["KIT_TEST_STALL_SECONDS"] = "nonsense"
            self.assertEqual(stall_guard.budget(), stall_guard.DEFAULT_SECONDS)
            os.environ["KIT_TEST_STALL_SECONDS"] = "0"
            self.assertEqual(stall_guard.budget(), stall_guard.DEFAULT_SECONDS)                       # zero would mean no guard at all
        finally:
            if old is None:
                os.environ.pop("KIT_TEST_STALL_SECONDS", None)
            else:
                os.environ["KIT_TEST_STALL_SECONDS"] = old


if __name__ == "__main__":
    unittest.main()
