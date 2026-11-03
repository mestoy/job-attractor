#!/usr/bin/env python3
"""Rehearsal run 3: doctor ended a clean Full-service Setup on one blocking item, the three contact
placeholders (site, email, phone), which Setup makes optional. When setup is complete on file (the
fold writes "- Level of service:" into documents/PROFILE.md from the app's own answers), those
three are advisory with a line naming Setup as the place to add them; the name stays blocking, and
without a finished Setup the old red stands."""
import os
import _roots
import shutil
import subprocess
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(KIT, "scripts", "doctor.py")


def _sandbox(setup_done, name_set=True):
    root = tempfile.mkdtemp(prefix="doctor-contact-")
    os.makedirs(os.path.join(root, "scripts")); os.makedirs(os.path.join(root, "documents"))
    src = open(os.path.join(KIT, "scripts", "kit_config.py"), encoding="utf-8").read()
    with open(os.path.join(root, "scripts", "kit_config.py"), "w", encoding="utf-8") as fh:
        fh.write(src)
        fh.write('\nOWNER_NAME = "%s"\n' % ("Dalisay Reyes" if name_set else "Your Name"))
        fh.write('OWNER_SITE = "yoursite.example"\nOWNER_EMAIL = "you@example.com"\nOWNER_PHONE = "555-0100"\n')
    if setup_done:
        with open(os.path.join(root, "documents", "PROFILE.md"), "w") as fh:
            fh.write("# Profile\n\n- Name: Dalisay Reyes\n- Contact: not answered yet\n- Level of service: full service\n")
    return root


def _section1(root):
    env = dict(os.environ); env.pop("GIT_DIR", None); _roots.point_env(env, root)
    p = subprocess.run(["python3", DOCTOR], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    return out.split("[1] your identity", 1)[1].split("\n[2]", 1)[0] if "[1] your identity" in out else out


class TestOptionalContactAfterSetup(unittest.TestCase):
    def test_setup_complete_makes_contact_advisory(self):
        root = _sandbox(setup_done=True)
        try:
            sec = _section1(root)
            for line in sec.splitlines():
                if "OWNER_SITE" in line or "OWNER_EMAIL" in line or "OWNER_PHONE" in line or "contact" in line.lower():
                    self.assertNotIn("🔴", line, line)
            self.assertIn("⚠️", sec)
            self.assertIn("Setup", sec)
        finally:
            shutil.rmtree(root)

    def test_name_still_blocks_even_after_setup(self):
        root = _sandbox(setup_done=True, name_set=False)
        try:
            sec = _section1(root)
            self.assertIn("🔴", sec); self.assertIn("OWNER_NAME", sec)
        finally:
            shutil.rmtree(root)

    def test_without_setup_the_old_red_stands(self):
        root = _sandbox(setup_done=False)
        try:
            sec = _section1(root)
            self.assertIn("🔴", sec); self.assertIn("OWNER_EMAIL", sec)
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
