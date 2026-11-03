#!/usr/bin/env python3
"""Proxy 211: doctor tells a new partner about their blocked list as a plain notice, never a block.

An existing but EMPTY blocked list is the normal state of a new install, and the feed reads it as clean. Doctor says so in one ordinary line
("your blocked list is empty") that does not fail the run and does not count as a warning. A MISSING or unreadable list is a different thing:
the added-company screen holds every add until it can read one, so doctor warns, with the fix, and still does not block.
"""
import os
import _roots
import shutil
import subprocess
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(KIT, "scripts", "doctor.py")


def _sandbox(blocked):
    root = tempfile.mkdtemp(prefix="doctor-blocked-", dir="/home/vscode/render" if os.path.isdir("/home/vscode/render") else None)
    os.makedirs(os.path.join(root, "scripts")); os.makedirs(os.path.join(root, "documents"))
    shutil.copy(os.path.join(KIT, "scripts", "kit_config.example.py"), os.path.join(root, "scripts", "kit_config.py"))
    with open(os.path.join(root, "documents", "PROFILE.md"), "w", encoding="utf-8") as fh:
        fh.write("# Profile\n\n- Name: Dalisay Reyes\n- Level of service: full service\n")
    path = os.path.join(root, "documents", "blocked-employers-list.md")
    if blocked == "directory":
        os.makedirs(path)
    elif blocked is not None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(blocked)
    return root


def _section2(root):
    env = dict(os.environ); env.pop("GIT_DIR", None); _roots.point_env(env, root)
    p = subprocess.run(["python3", DOCTOR], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    sec = out.split("[2] your profile", 1)[1].split("\n[3]", 1)[0] if "[2] your profile" in out else out
    return sec, p


class DoctorBlockedList(unittest.TestCase):
    def run_doctor(self, blocked):
        root = _sandbox(blocked)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return _section2(root)

    EMPTY_TABLE = "# Blocked\n\n| Company | Date | Reason |\n|---|---|---|\n| _[Example Co]_ | _2026-01-01_ | _example_ |\n"

    def blocked_lines(self, sec):
        return [ln for ln in sec.splitlines() if "blocked list" in ln.lower()]

    def test_an_empty_list_is_a_plain_notice_and_not_a_block_or_a_warning(self):
        for text in ("", "# Blocked\n\nNothing yet.\n", self.EMPTY_TABLE):
            with self.subTest(text=text[:20]):
                sec, _p = self.run_doctor(text)
                lines = self.blocked_lines(sec)
                self.assertTrue(any("your blocked list is empty" in ln.lower() for ln in lines), sec)
                for ln in lines:
                    self.assertNotIn("🔴", ln)
                    self.assertNotIn("⚠️", ln)

    def test_the_shipped_starter_list_reads_as_empty(self):
        with open(os.path.join(KIT, "partner-docs", "blocked-employers-list.md"), encoding="utf-8") as fh:
            sec, _p = self.run_doctor(fh.read())
        self.assertTrue(any("your blocked list is empty" in ln.lower() for ln in self.blocked_lines(sec)), sec)

    def test_a_list_with_a_company_is_ok(self):
        sec, _p = self.run_doctor("# Blocked\n\n- **Plinth Widgets** (blocked, filter 8)\n")
        lines = self.blocked_lines(sec)
        self.assertTrue(any("✅" in ln for ln in lines), sec)
        self.assertFalse(any("empty" in ln.lower() for ln in lines), sec)

    def test_a_missing_list_is_a_warning_with_the_fix_and_not_a_block(self):
        sec, _p = self.run_doctor(None)
        lines = self.blocked_lines(sec)
        self.assertTrue(any("⚠️" in ln for ln in lines), sec)
        self.assertFalse(any("🔴" in ln for ln in lines), sec)
        self.assertIn("fix:", sec)

    def test_an_unreadable_list_is_a_warning_and_not_a_block(self):
        sec, _p = self.run_doctor("directory")
        lines = self.blocked_lines(sec)
        self.assertTrue(any("⚠️" in ln for ln in lines), sec)
        self.assertFalse(any("🔴" in ln for ln in lines), sec)


if __name__ == "__main__":
    unittest.main()
