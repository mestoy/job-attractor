"""A hard time budget for a test (BUG-568). Not a test file.

A browser test that waits on something that never comes holds the shared slot for every seat, and a hang guards nothing. `bounded` gives a test a budget: when it runs out, the test FAILS
LOUDLY (an AssertionError that names the test and the budget, and every thread's stack is dumped to stderr so the wait is visible) instead of waiting forever. It works through SIGALRM in the
main thread, so it interrupts what a timeout argument cannot: a `page.evaluate` that never returns, a busy loop in the page, a blocked read. The alarm is cleared and the old handler restored
after every test. Where SIGALRM does not exist (Windows) or the test is not on the main thread, the test runs unguarded and says nothing: this is a guard against a stall, not a speed rule.

  stall_guard.bound_class(Cls)            bound every test method (inherited ones too), the class fixtures and the cleanups of Cls
  stall_guard.bound_module(globals())     do that for every TestCase defined in a module
  KIT_TEST_STALL_SECONDS=90               change the per-test budget (default 60; a value that is not a positive whole number means the default, never "no guard")

Never raise the budget to make a slow test pass: a test that needs more than a minute should be split.
"""
import faulthandler
import functools
import os
import signal
import sys
import threading
import unittest

DEFAULT_SECONDS = 60
FIXTURE_SECONDS = 45           # a browser start or stop (a few seconds when it works)
CLEANUP_SECONDS = 30


class Stalled(AssertionError):
    """The test did not finish inside its budget."""


# When True (the default, so a plain `python3 -m unittest` is safe too), a stall in a CLEANUP or a CLASS FIXTURE ends the whole run at once with exit code 75 and a plain message. A page that
# spins forever cannot be closed (Playwright's close waits on it, measured: still stuck after 20 s), so after a stall the browser state is not trustworthy and waiting longer only holds the
# shared slot. Unit tests of the guard turn it off to see a failure instead.
ABORT_ON_FIXTURE_STALL = True
EXIT_STALLED = 75


def budget():
    try:
        n = int(os.environ.get("KIT_TEST_STALL_SECONDS", ""))
    except ValueError:
        return DEFAULT_SECONDS
    return n if n > 0 else DEFAULT_SECONDS


def _usable():
    return hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()


SWALLOW_LIMIT = 4          # firings (the first at the budget, then one a second) before a test that keeps swallowing the interruption ends the run


def _run_bounded(seconds, label, call, abort=False, recorded_by_unittest=False):
    """Run `call` under a budget. `recorded_by_unittest` is True for cleanups and class fixtures: unittest catches whatever they raise and records it itself, so a swallowed stall there is
    already on the record and is not raised a second time (that would escape the runner)."""
    if not _usable():
        return call()
    fired = []
    message = ("this test stalled for %d s, so it was failed instead of waiting forever (a bounded wait should have failed it sooner): %s" % (seconds, label))

    def on_alarm(_sig, _frame):
        fired.append(1)
        if len(fired) == 1:
            print("\n=== STALL: %s did not finish in %d s; stacks follow ===" % (label, seconds), file=sys.stderr, flush=True)
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        if abort and ABORT_ON_FIXTURE_STALL and len(fired) == 1:
            print("\nABORTED: %s stalled for %d s after an earlier failure, so the browser cannot be trusted; the run stops here (exit %d) so the shared slot is released." % (label, seconds, EXIT_STALLED),
                  file=sys.stderr, flush=True)
            os._exit(EXIT_STALLED)
        if len(fired) >= SWALLOW_LIMIT:
            print("\nABORTED: %s swallowed the stall interruption %d times (a broad except around the hang), so the run stops here (exit %d) so the shared slot is released." % (label, len(fired), EXIT_STALLED),
                  file=sys.stderr, flush=True)
            os._exit(EXIT_STALLED)
        signal.setitimer(signal.ITIMER_REAL, 1.0)          # if this interruption is swallowed, interrupt again in a second
        raise Stalled(message)
    old = signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(seconds)
    try:
        result = call()
    except BaseException as err:
        if fired and not isinstance(err, Stalled) and not recorded_by_unittest:
            raise Stalled(message) from err                     # the stall was swallowed and something ELSE was raised afterwards: it is still the stall
        raise
    else:
        if fired and not recorded_by_unittest:
            raise Stalled(message)                              # the stall was swallowed and the test went on to finish: it must still FAIL, whatever it caught
        return result
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def bounded(fn, seconds=None):
    if getattr(fn, "_stall_bounded", False):
        return fn

    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        return _run_bounded(seconds or budget(), self.id(), lambda: fn(self, *a, **k))
    wrapper._stall_bounded = True
    return wrapper


def _bounded_classmethod(cls, name, seconds):
    raw = cls.__dict__.get(name)
    if raw is None:
        raw = getattr(cls, name)                   # inherited: wrap the bound call on this class
        inner = raw.__func__ if hasattr(raw, "__func__") else raw
    else:
        inner = raw.__func__
    if getattr(inner, "_stall_bounded", False):
        return

    @functools.wraps(inner)
    def wrapper(klass):
        return _run_bounded(seconds, "%s.%s" % (klass.__name__, name), lambda: inner(klass), abort=True, recorded_by_unittest=True)
    wrapper._stall_bounded = True
    setattr(cls, name, classmethod(wrapper))


def bound_class(cls, seconds=None, cleanup_seconds=None):
    """Bound every test method of `cls` (inherited ones included), its class fixtures and its cleanups (`cleanup_seconds`, else `seconds`, else CLEANUP_SECONDS)."""
    for name in dir(cls):
        if name.startswith("test") and callable(getattr(cls, name)):
            setattr(cls, name, bounded(getattr(cls, name), seconds))
    fixture = max(FIXTURE_SECONDS, seconds or 0) if seconds is None else seconds
    for name in ("setUpClass", "tearDownClass"):
        _bounded_classmethod(cls, name, fixture)
    original = cls.doCleanups
    if not getattr(original, "_stall_bounded", False):
        def do_cleanups(self):
            return _run_bounded(cleanup_seconds or seconds or CLEANUP_SECONDS, self.id() + " (cleanups)", lambda: original(self), abort=True, recorded_by_unittest=True)
        do_cleanups._stall_bounded = True
        cls.doCleanups = do_cleanups
    return cls


def bound_module(namespace, seconds=None):
    """bound_class for every unittest.TestCase subclass defined in the module whose globals are `namespace`."""
    for obj in list(namespace.values()):
        if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and obj.__module__ == namespace.get("__name__"):
            bound_class(obj, seconds)


class _TimedResult(unittest.TextTestResult):
    def startTest(self, test):
        import time
        self._t0 = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        import time
        self.stream.writeln("    (%.1f s)" % (time.monotonic() - self._t0))
        super().stopTest(test)


def timed_main(**kw):
    """unittest.main for a browser file: verbose, one line per test with its seconds (so a long run is never silent), and (as everywhere) a stall in a cleanup or fixture aborts the run (exit 75)."""
    kw.setdefault("verbosity", 2)
    kw.setdefault("testRunner", unittest.TextTestRunner(resultclass=_TimedResult, verbosity=kw["verbosity"]))
    unittest.main(**kw)


def timed_run(suite, verbosity=2):
    """timed_main for an explicit suite; returns the exit code (0 all passed, 1 a failure; a stall in a cleanup or fixture never returns: exit 75)."""
    result = unittest.TextTestRunner(resultclass=_TimedResult, verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1
