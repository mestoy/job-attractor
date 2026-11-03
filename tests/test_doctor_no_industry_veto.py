#!/usr/bin/env python3
"""Rehearsal run 2's amber: after a clean Setup where the person honestly answered "None yet" to
industry vetoes, doctor still blocked twice on an empty INDUSTRY_VETO. The fold now writes
NO_INDUSTRY_VETO = True for that case; doctor treats the marker as answered."""
import os
import _roots
import shutil
import subprocess
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(KIT, "scripts", "doctor.py")


def _sandbox(marker):
    root = tempfile.mkdtemp(prefix="doctor-veto-")
    os.makedirs(os.path.join(root, "scripts"))
    src = open(os.path.join(KIT, "scripts", "kit_config.py"), encoding="utf-8").read()
    with open(os.path.join(root, "scripts", "kit_config.py"), "w", encoding="utf-8") as fh:
        fh.write(src)
        fh.write("\nINDUSTRY_VETO = []\n")
        if marker:
            fh.write("NO_INDUSTRY_VETO = True\n")
    return root


def _section1(root):
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    _roots.point_env(env, root)
    p = subprocess.run(["python3", DOCTOR], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    return out.split("[1] your identity", 1)[1].split("\n[2]", 1)[0] if "[1] your identity" in out else out


class TestNoIndustryVetoByChoice(unittest.TestCase):
    def test_marker_reads_as_answered(self):
        root = _sandbox(marker=True)
        try:
            sec = _section1(root)
            self.assertIn("no industry vetoes, by your choice", sec)
            for line in sec.splitlines():
                if "INDUSTRY_VETO" in line or "industry veto" in line.lower():
                    self.assertNotIn("🔴", line, line)
        finally:
            shutil.rmtree(root)

    def test_no_marker_still_blocks(self):
        root = _sandbox(marker=False)
        try:
            sec = _section1(root)
            self.assertIn("🔴", sec)
            self.assertIn("INDUSTRY_VETO is empty", sec)
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
