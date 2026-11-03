#!/usr/bin/env python3
"""Pre-launch audit F10: doctor names the python3 it runs on, green at 3.9 or newer."""
import os
import _roots
import shutil
import subprocess
import sys
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(KIT, "scripts", "doctor.py")


class TestDoctorPythonVersion(unittest.TestCase):
    def test_section_four_names_the_running_python(self):
        root = tempfile.mkdtemp(prefix="doctor-py-")
        try:
            os.makedirs(os.path.join(root, "scripts"))
            shutil.copy(os.path.join(KIT, "scripts", "kit_config.py"), os.path.join(root, "scripts", "kit_config.py"))
            env = dict(os.environ); env.pop("GIT_DIR", None); _roots.point_env(env, root)
            p = subprocess.run([sys.executable, DOCTOR], cwd=root, env=env, capture_output=True, text=True, timeout=120)
            out = p.stdout + p.stderr
            sec = out.split("[4] optional tools", 1)[1].split("\n\n", 1)[0]
            v = "%d.%d" % (sys.version_info.major, sys.version_info.minor)
            line = [l for l in sec.splitlines() if "python3 " + v in l]
            self.assertTrue(line, sec)
            self.assertIn("✅" if sys.version_info >= (3, 9) else "🔴", line[0])
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
