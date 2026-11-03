#!/usr/bin/env python3
"""Review 145 / proxy 166: doctor warns about the industry source, never silently.

* an existing install whose scripts/kit_config.py predates INDUSTRY_CLASSES gets a warning that the
  industry source is idle until the map is copied from kit_config.example.py;
* an empty INDUSTRY_VETO gets a warning that the industry source can veto nothing, because the
  families it vetoes are derived from the person's own veto words (even when they chose "none").
"""
import os
import _roots
import shutil
import subprocess
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(KIT, "scripts", "doctor.py")
EXAMPLE = os.path.join(KIT, "scripts", "kit_config.example.py")


def _sandbox(extra):
    root = tempfile.mkdtemp(prefix="doctor-industry-")
    os.makedirs(os.path.join(root, "scripts"))
    with open(os.path.join(root, "scripts", "kit_config.py"), "w", encoding="utf-8") as fh:
        fh.write(open(EXAMPLE, encoding="utf-8").read())
        fh.write("\n" + extra + "\n")
    return root


def _doctor(root):
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    _roots.point_env(env, root)
    p = subprocess.run(["python3", DOCTOR], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    return p.stdout + p.stderr


class TestDoctorIndustrySource(unittest.TestCase):
    def test_missing_industry_classes_warns(self):
        root = _sandbox('INDUSTRY_VETO = [r"\\bdefense\\b"]\ndel INDUSTRY_CLASSES')
        try:
            out = _doctor(root)
            self.assertIn("INDUSTRY_CLASSES is missing", out)
            line = [l for l in out.splitlines() if "INDUSTRY_CLASSES is missing" in l][0]
            self.assertIn("⚠️", line)
            self.assertNotIn("🔴", line)
        finally:
            shutil.rmtree(root)

    def test_present_industry_classes_does_not_warn(self):
        root = _sandbox('INDUSTRY_VETO = [r"\\bdefense\\b"]')
        try:
            self.assertNotIn("INDUSTRY_CLASSES is missing", _doctor(root))
        finally:
            shutil.rmtree(root)

    def test_empty_veto_warns_the_industry_source_can_veto_nothing_even_by_choice(self):
        root = _sandbox("INDUSTRY_VETO = []\nNO_INDUSTRY_VETO = True")
        try:
            out = _doctor(root)
            self.assertIn("the industry source can veto nothing", out)
        finally:
            shutil.rmtree(root)

    def test_a_veto_regex_that_will_not_compile_is_reported(self):
        root = _sandbox('INDUSTRY_VETO = [r"\\bdefense\\b", "(unclosed"]')
        try:
            out = _doctor(root)
            self.assertIn("does not compile", out)
            self.assertIn("(unclosed", out)
        finally:
            shutil.rmtree(root)

    def test_a_group_with_alternation_is_not_flagged(self):
        # Proxy 184: no static classifier. (casino|gaming)+ resort is a good pattern.
        root = _sandbox('INDUSTRY_VETO = [r"(casino|gaming)+ resort"]')
        try:
            out = _doctor(root)
            self.assertNotIn("nested quantifier", out)
            self.assertNotIn("does not compile", out)
        finally:
            shutil.rmtree(root)

    def test_a_non_compiling_veto_regex_blocks_and_names_the_pattern(self):
        root = _sandbox('INDUSTRY_VETO = [r"\\bdefense\\b", "(unclosed"]')
        try:
            out = _doctor(root)
            line = [l for l in out.splitlines() if "does not compile" in l][0]
            self.assertIn("🔴", line)
            self.assertIn("(unclosed", line)
            self.assertIn("holds", out)
        finally:
            shutil.rmtree(root)

    def test_a_populated_veto_does_not_trigger_that_warning(self):
        root = _sandbox('INDUSTRY_VETO = [r"\\bdefense\\b"]')
        try:
            self.assertNotIn("the industry source can veto nothing", _doctor(root))
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
