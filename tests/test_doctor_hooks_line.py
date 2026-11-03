#!/usr/bin/env python3
"""doctor.py section [3]: a green line when the hooks are present and current, and when they are
absent a one-line fix in plain words that names the installer, never a copy command the person
was promised they would not need (rehearsal row 9, 2026-09-14)."""
import os
import _roots
import shutil
import subprocess
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(KIT, "scripts", "doctor.py")
EXAMPLE = os.path.join(KIT, ".claude", "settings.example.json")
if not os.path.exists(EXAMPLE):
    EXAMPLE = os.path.join(KIT, "settings.example.json")


def _sandbox(with_live):
    root = tempfile.mkdtemp(prefix="doctor-hooks-")
    os.makedirs(os.path.join(root, "scripts"))
    os.makedirs(os.path.join(root, ".claude"))
    shutil.copy(os.path.join(KIT, "scripts", "kit_config.py"), os.path.join(root, "scripts", "kit_config.py"))
    shutil.copy(EXAMPLE, os.path.join(root, ".claude", "settings.example.json"))
    if with_live:
        shutil.copy(EXAMPLE, os.path.join(root, ".claude", "settings.json"))
        # every script the example wires must exist on disk, or the check reports them gone
        import json, re
        cfg = json.load(open(EXAMPLE))
        for groups in (cfg.get("hooks") or {}).values():
            for g in groups:
                for h in g.get("hooks") or []:
                    for m in re.finditer(r"scripts/([A-Za-z0-9_.-]+\.(?:py|sh))", h.get("command", "")):
                        open(os.path.join(root, "scripts", m.group(1)), "a").close()
    return root


def _section3(root):
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    _roots.point_env(env, root)
    p = subprocess.run(["python3", DOCTOR], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    return out.split("[3] enforcement hooks", 1)[1].split("\n\n", 1)[0] if "[3] enforcement hooks" in out else ""


class TestDoctorHooksLine(unittest.TestCase):
    def test_present_and_current_is_green(self):
        root = _sandbox(with_live=True)
        try:
            sec = _section3(root)
            self.assertIn("✅", sec)
            self.assertIn("hooks wired", sec)
        finally:
            shutil.rmtree(root)

    def test_absent_names_the_installer_in_plain_words(self):
        root = _sandbox(with_live=False)
        try:
            sec = _section3(root)
            self.assertIn("🔴", sec)
            self.assertIn("bash install.sh .", sec)
            self.assertNotIn("cp .claude", sec, "the fix is the installer, never a copy command")
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
