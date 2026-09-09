"""kit#68 — consistency-check.sh's ACTIVE-list message still carries the retired "N/10 cap" rule.

Main retired the boss-hunt-list cap on 2026-08-19 (Michael: "no ceiling replaced it — the active
board is worked as wide as AI orchestration can carry") and now prints
`✅ ACTIVE list {n} (boss-hunt tier, no cap)` unconditionally, with no 🔴 branch for n > 10. The
kit's copy of consistency-check.sh never got that fix: it still prints a 🔴 "cap is 10" line above
10 rows and an "{n}/10" line at or below it.

Sandbox pattern follows tests/test_kf2_contactcard.py's DurabilityCheckPrivateRemoteTests: a
throwaway directory holding its own copy of scripts/ (so the script's own `sys.path.insert(0,
"scripts")` heredocs resolve) plus a documents/green-board.md fixture, run with
`subprocess.run(["bash", script], cwd=work, ...)`. The real repo's documents/green-board.md is
never touched — it is one of the six stores tests/run_all.sh fingerprints for live-store drift.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)


def section(out: str, n: int) -> str:
    """Text of consistency-check section [n], up to the next '[' header."""
    m = re.search(rf"^\[{n}\][^\n]*\n(.*?)(?=^\[\d+\]|\Z)", out, re.S | re.M)
    return m.group(1) if m else out


class ActiveListNoCapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit68-active-cap-")
        shutil.copytree(os.path.join(KIT, "scripts"), os.path.join(self.tmp, "scripts"))
        os.makedirs(os.path.join(self.tmp, "documents"), exist_ok=True)
        hdr = ("| # | Company | Lane | Remote✓ | Culture | Non-PE | Boss + email "
               "| Primary praise (URL) | Status |\n|---|---|---|---|---|---|---|---|---|\n")
        rows = "".join(f"| {i} | Co{i} | l | r | c | p | b | u | ⏳ READY |\n" for i in range(1, 12))
        with open(os.path.join(self.tmp, "documents", "green-board.md"), "w", encoding="utf-8") as fh:
            fh.write("# board\n" + hdr + rows)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self):
        script = os.path.join(self.tmp, "scripts", "consistency-check.sh")
        return subprocess.run(["bash", script], cwd=self.tmp, capture_output=True, text=True)

    def test_eleven_active_rows_print_the_no_cap_line(self):
        out = self._run().stdout
        sec = section(out, 14)
        self.assertIn("ACTIVE list 11 (boss-hunt tier, no cap)", sec,
                      "did not print main's retired-cap line for 11 ACTIVE rows")

    def test_eleven_active_rows_trip_no_red_cap_warning(self):
        out = self._run().stdout
        sec = section(out, 14)
        self.assertNotIn("🔴", sec,
                         "the retired '/10 cap' 🔴 branch fired for a count above the old cap")
        self.assertNotIn("cap is 10", sec,
                         "the retired '/10 cap' rule text is still being printed")
        self.assertNotIn("11/10", sec, "the retired 'N/10' framing is still being printed")


if __name__ == "__main__":
    unittest.main()
