"""BUG-684: a browser test that skips must not read as green.

Browser test files skip when Chromium is missing, each with its own check and its own reason, and a run with
PLAYWRIGHT_BROWSERS_PATH unset skipped all 59 cases of J2 and exited 0. This pytest plugin (loaded by tests/conftest.py, so every
pytest run passes through it) treats a skip whose reason names Chromium, Playwright or headless as a browser skip (an expected failure is not a skip), and:
  - REQUIRE_BROWSERS=1 set: the skip becomes a FAILURE that names the reason, so a gate that needs the browser cannot pass without it.
  - REQUIRE_BROWSERS unset: the run prints ONE loud line at the end naming both variables and the count of cases that did not run.
A skip for any other reason is left alone. Files run with `python3 -m unittest` do not pass through pytest; the ones that mention
REQUIRE_BROWSERS honor it themselves."""
import os
import re

import pytest

# Only the tool itself names a missing browser: a bare "browser" also appears in platform skips ("only on a Mac with Safari browser").
_BROWSER_SKIP = re.compile(r"chromium|playwright|headless", re.I)
_SKIPPED_FOR_BROWSER = []


def _required():
    return os.environ.get("REQUIRE_BROWSERS") == "1"


def _reason(rep):
    lr = rep.longrepr
    if isinstance(lr, tuple) and len(lr) == 3:
        return str(lr[2])
    return str(lr)


def _judge(rep, where):
    """Called with a finished report; turns a browser skip into a failure when browsers are required, else counts it."""
    if not rep.skipped:
        return
    if hasattr(rep, "wasxfail"):
        return   # pytest reports xfail and unittest.expectedFailure as a skip with wasxfail set; an expected failure is neither a skip nor a failure
    reason = _reason(rep)
    if not _BROWSER_SKIP.search(reason):
        return
    if _required():
        rep.outcome = "failed"
        rep.longrepr = ("REQUIRE_BROWSERS=1 is set, so a browser skip is a failure. %s skipped: %s\n"
                        "Set PLAYWRIGHT_BROWSERS_PATH to where Playwright keeps its browsers (usually ~/.cache/ms-playwright)." % (where, reason))
    else:
        _SKIPPED_FOR_BROWSER.append(where)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    _judge(outcome.get_result(), item.nodeid)


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    _judge(outcome.get_result(), getattr(collector, "nodeid", "collection"))


def pytest_terminal_summary(terminalreporter):
    n = len(_SKIPPED_FOR_BROWSER)
    if n and not _required():
        terminalreporter.write_line(
            "!! %d browser test case(s) were SKIPPED, not run, so this run proves nothing about the pages: set PLAYWRIGHT_BROWSERS_PATH "
            "(usually $HOME/.cache/ms-playwright) and REQUIRE_BROWSERS=1 so a missing browser fails the run." % n, red=True, bold=True)
