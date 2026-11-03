#!/usr/bin/env python3
"""Pre-launch audit risk 2 (high): a hook group shipped in settings.example.json without its script
blocks every Bash call with exit 2 on a fresh clone. doctor section [3] must stat every script the
shipped example names and go red on any that is missing from scripts/."""
import json
import os
import _roots
import re
import shutil
import subprocess
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(KIT, "scripts", "doctor.py")
EXAMPLE = os.path.join(KIT, ".claude", "settings.example.json")
if not os.path.exists(EXAMPLE):
    EXAMPLE = os.path.join(KIT, "settings.example.json")


def _scripts_named(cfg):
    found = set()
    for groups in (cfg.get("hooks") or {}).values():
        for g in groups:
            for h in g.get("hooks") or []:
                for m in re.finditer(r"scripts/([A-Za-z0-9_.-]+\.(?:py|sh))", h.get("command", "")):
                    found.add(m.group(1))
    return found


def _sandbox(drop_one):
    root = tempfile.mkdtemp(prefix="doctor-exhooks-")
    os.makedirs(os.path.join(root, "scripts")); os.makedirs(os.path.join(root, ".claude"))
    shutil.copy(os.path.join(KIT, "scripts", "kit_config.py"), os.path.join(root, "scripts", "kit_config.py"))
    cfg = json.load(open(EXAMPLE))
    json.dump(cfg, open(os.path.join(root, ".claude", "settings.example.json"), "w"))
    json.dump(cfg, open(os.path.join(root, ".claude", "settings.json"), "w"))
    names = sorted(_scripts_named(cfg))
    dropped = names[-1] if drop_one else None
    for n in names:
        if n != dropped:
            open(os.path.join(root, "scripts", n), "a").close()
    return root, dropped


def _section3(root):
    env = dict(os.environ); env.pop("GIT_DIR", None); _roots.point_env(env, root)
    p = subprocess.run(["python3", DOCTOR], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    return out.split("[3] enforcement hooks", 1)[1].split("\n\n", 1)[0] if "[3] enforcement hooks" in out else ""


class TestDoctorStatsTheShippedHookScripts(unittest.TestCase):
    def test_every_shipped_script_present_is_green(self):
        root, _ = _sandbox(drop_one=False)
        try:
            sec = _section3(root)
            self.assertIn("✅", sec); self.assertNotIn("🔴", sec)
        finally:
            shutil.rmtree(root)

    def test_a_shipped_script_missing_from_the_kit_is_red_and_named(self):
        root, dropped = _sandbox(drop_one=True)
        try:
            sec = _section3(root)
            self.assertIn("🔴", sec); self.assertIn(dropped, sec)
            self.assertIn("shipped", sec.lower())
        finally:
            shutil.rmtree(root)

    def test_the_kit_itself_ships_every_script_its_example_names(self):
        cfg = json.load(open(EXAMPLE))
        missing = [n for n in _scripts_named(cfg) if not os.path.exists(os.path.join(KIT, "scripts", n))]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
