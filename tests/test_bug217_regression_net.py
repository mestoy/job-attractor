#!/usr/bin/env python3
"""Tests for "Update Kit.command"'s post-pull regression net — BUG-217 part (a).

BUG-217: the kit ships no CI (and the operator ruled DO NOT raise GitHub Actions —
[[do-not-raise-github-actions-ci]]), and `Update Kit.command` used to pull and re-run install.sh
without ever running the bundled `tests/run_all.sh`. A regression could ship silently to every
partner who updates, and the script would still print "You're on the latest version."

The fix: after `install.sh` runs (step 5), if `tests/run_all.sh` exists, run it. A red suite means
the pull SUCCEEDED but the code it delivered did not prove itself — the script now says so loudly,
in the same terminal, and refuses the "you're on the latest" message and its exit-0 status.

Reuses the git/file fixtures from test_update_kit_command.py (`_install_update_kit_command` stubs
install.sh to a no-op, so these tests stay scoped to the NEW step, not the pull/circuit-breaker
logic those tests already cover) and runs the PRODUCTION "Update Kit.command" as a subprocess,
exactly like a partner's double-click would.
"""
import os
import stat
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_update_kit_command import (  # noqa: E402
    TempReposMixin,
    _install_update_kit_command,
    run_update_kit,
    write_file,
)


def _write_stub_run_all(repo, exit_code, output_line):
    p = write_file(repo, "tests/run_all.sh",
                    f"#!/usr/bin/env bash\necho '{output_line}'\nexit {exit_code}\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)


class RegressionNetTests(TempReposMixin, unittest.TestCase):
    """setUp (via TempReposMixin) already gives a partner clone one commit behind the kit, with
    install.sh stubbed to a no-op — exactly what a normal `Update Kit.command` run needs to reach
    the new step 5b after a real, successful pull."""

    def test_green_suite_reaches_youre_on_the_latest(self):
        _write_stub_run_all(self.partner, 0, "GREEN-STUB-RAN")
        self._advance_kit("print('v2')\n", "kit v2")

        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 0, f"stdout:\n{p.stdout}\nstderr:\n{p.stderr}")
        self.assertIn("GREEN-STUB-RAN", p.stdout, "the bundled suite was never actually run")
        self.assertIn("bundled tests are green", p.stdout)
        self.assertIn("You're on the latest version.", p.stdout)

    def test_red_suite_refuses_the_youre_current_message(self):
        """The actual regression this bug names: a red suite must not be reported as current."""
        _write_stub_run_all(self.partner, 1, "RED-STUB-RAN")
        self._advance_kit("print('v2')\n", "kit v2")

        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 1, f"a red suite must fail the update\nstdout:\n{p.stdout}")
        self.assertIn("RED-STUB-RAN", p.stdout, "the bundled suite was never actually run")
        self.assertIn("BUNDLED TESTS ARE RED", p.stdout)
        self.assertNotIn("You're on the latest version.", p.stdout,
                          "a partner with a red suite must never be told they are current")

    def test_missing_run_all_degrades_to_the_old_behavior(self):
        """A kit version that predates run_all.sh (or a stripped install) must not break the
        updater — the new step is conditional on the file existing."""
        self._advance_kit("print('v2')\n", "kit v2")
        # No tests/run_all.sh written at all.
        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 0, f"stdout:\n{p.stdout}\nstderr:\n{p.stderr}")
        self.assertIn("You're on the latest version.", p.stdout)

    def test_documents_and_tracker_are_untouched_when_the_suite_is_red(self):
        """A red suite must still honor the updater's core promise: your private data is
        never touched, whichever way the update lands."""
        write_file(self.partner, "documents/private-note.md", "do not touch me\n")
        _write_stub_run_all(self.partner, 1, "RED-STUB-RAN")
        self._advance_kit("print('v2')\n", "kit v2")

        run_update_kit(self.partner)
        self.assertEqual(
            open(os.path.join(self.partner, "documents", "private-note.md")).read(),
            "do not touch me\n")


if __name__ == "__main__":
    unittest.main()
