"""install.sh must RUN doctor.py at the end and fail when it says something is blocking (K3).

⛔ THE SHAPE: install.sh printed "Something not working? Run: python3 scripts/doctor.py" and then
exited 0. It suggested the check and never ran it. A stranger's first minute ended with DONE on an
install that doctor.py would have refused, and nothing told them.

That is an empty check passing at the worst possible moment, one layer up from a gate that returns
nothing: here the check is never called at all, so its verdict cannot be read as anything.

doctor.py's own contract, from its header: 0 = ready, warnings are fine; 1 = something blocking is
unconfigured. So install.sh only has to run it and honor the code.
"""
import os
import _roots
import re
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(REPO, "install.sh")
DOCTOR = os.path.join(REPO, "scripts", "doctor.py")


def _src():
    with open(INSTALL, encoding="utf-8") as fh:
        return fh.read()


class TestItParses(unittest.TestCase):
    def test_bash_accepts_it(self):
        """A guard: it passes before and after, and without it the rest is noise."""
        r = subprocess.run(["bash", "-n", INSTALL], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestTheDoctorIsRunAndHeeded(unittest.TestCase):
    def _lines(self):
        return [ln for ln in _src().splitlines()]

    def _invocation_lines(self):
        """Lines that RUN doctor.py: not comments, not printf/echo mentioning it."""
        out = []
        for ln in self._lines():
            t = ln.strip()
            if not t or t.startswith("#"):
                continue
            if "doctor.py" not in t:
                continue
            if t.startswith("printf") or t.startswith("echo"):
                continue
            if "python3" in t:
                out.append(t)
        return out

    def test_install_actually_invokes_the_doctor(self):
        """Not a suggestion in a printf. An invocation."""
        self.assertTrue(
            self._invocation_lines(),
            "install.sh must RUN doctor.py, not only print a line telling the person to run it")

    def test_a_blocking_verdict_makes_the_install_fail(self):
        """The whole point: an install that ends DONE on a refused check is the bug.

        ⛔ THIS ASSERTION WAS WRONG ON ITS FIRST WRITING AND PASSED ON THE BROKEN FILE. It looked
        for any `exit N` after the last mention of doctor.py and found the unrelated seed-skipped
        `exit 2` at the end of the file. An assertion anchored on distance rather than on structure
        cannot tell a wired verdict from a coincidence.
        """
        calls = self._invocation_lines()
        self.assertTrue(calls, "nothing runs the doctor, so no verdict can be honored")
        captured = [c for c in calls if "$?" in c or "_DOCTOR_RC" in c]
        self.assertTrue(captured,
                        "the doctor's return code must be captured; a bare call discards it")
        src = _src()
        self.assertIn('exit "$_DOCTOR_RC"', src,
                      "the captured code must reach the caller as the script's own exit")
        # and the exit must be conditional, not unconditional
        self.assertRegex(src, r'if \[ "\$_DOCTOR_RC" -ne 0 \]',
                         "a ready install must still exit 0; the failure must be conditional")

    def test_the_doctor_contract_it_relies_on_is_still_true(self):
        """If doctor.py stopped exiting 1 on a blocking line, the wiring above would be decorative."""
        doc = open(DOCTOR, encoding="utf-8").read()
        self.assertIn("1 = something blocking is unconfigured", doc)
        self.assertIn("def blocking(", doc)


class TestItFiresForReal(unittest.TestCase):
    """⛔ The assertions above read the shell. This one RUNS the doctor, because 48's condition was
    to prove the non-zero exit actually fires rather than to read that it should."""

    def test_the_doctor_exits_non_zero_on_a_blocking_install(self):
        env = _roots.sandbox_env(REPO)
        r = subprocess.run(["python3", DOCTOR], capture_output=True, text=True,
                           env=env, cwd=REPO, timeout=120)
        self.assertIn(r.returncode, (0, 1),
                      f"doctor.py must exit 0 or 1, got {r.returncode}: {r.stderr[:200]}")
        if r.returncode == 1:
            self.assertTrue(r.stdout.strip(), "a blocking exit must say what is blocking")


if __name__ == "__main__":
    unittest.main()
