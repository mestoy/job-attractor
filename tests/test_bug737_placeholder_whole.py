#!/usr/bin/env python3
"""BUG-737 (b): check_store_data's template filter matches a template value WHOLE.

The shipped profile's placeholders ("[YOUR NAME]", "Jane Doe", "you@example.com", "555-0100") name nobody and are skipped. A real partner named
John or Jane is NOT a placeholder: the old prefix match (^jane, ^john, ^example, ^your) skipped "John Smith" and "johnsmith@..." so the gate
never searched the store data for that person (it failed open). Every name below is invented.
  python3 -m unittest tests.test_bug737_placeholder_whole -v     (from the tree root; the file works unchanged in the kit and partner-starter)
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)


def _load():
    spec = importlib.util.spec_from_file_location("check_store_data_bug737", os.path.join(SCRIPTS, "check_store_data.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


csd = _load()

TEMPLATE = ["[YOUR NAME]", "[CITY, STATE]", "[your.email@example.com]", "Your Name", "your name", "you@example.com",
            "yoursite.example", "yourdomain.example", "Jane Doe", "John Doe", "jane doe", "555-0100", "example.com",
            "example", "placeholder",
            # BUG-745: half-edited template shapes
            "yourname@example.com", "your.name@example.com", "pat@example.org", "pat@mail.example.net", "pat@site.example", "pat@host.test",
            "https://yoursite.com", "www.example.com", "http://www.example.com", "+1 555-0100", "(555) 010-0100", "5550100",
            "555.0100", "<you@example.com>", "<yourname@example.com>", "[YOUR NAME]"]
REAL = ["John Fixtureson", "Jane Testcase", "johnfixtureson@mcfixture.invalid", "jane.testcase@mcfixture.invalid", "Johnny Placeholderson",
        "Yourvale Fixture", "Exampleton Testcase", "Janet Doe-Fixture", "202-555-0143", "Placeholderia Corp",
        # BUG-745: real values and edge shapes that must stay
        "john@acme.io", "pat@mcfixture.invalid", "fictional@example.invalid", "Pat Smith [she/her]", "Pat [Q] Smith", "https://acmefixture.io",
        "www.acmefixture.io", "5550143", "+1 202-555-0100"]


class PlaceholderIsMatchedWhole(unittest.TestCase):
    def test_every_template_value_is_still_a_placeholder(self):
        for v in TEMPLATE:
            with self.subTest(value=v):
                self.assertTrue(csd._PLACEHOLDER.search(v), "%r is a template value and must still be skipped" % v)

    def test_a_real_value_that_starts_like_a_template_word_is_not_a_placeholder(self):
        for v in REAL:
            with self.subTest(value=v):
                self.assertIsNone(csd._PLACEHOLDER.search(v), "%r is a real value and must not be skipped" % v)


class IdentityReadsARealJohnButNotTheTemplate(unittest.TestCase):
    def _identity(self, name_line):
        base = tempfile.mkdtemp(prefix="b737-")
        self.addCleanup(shutil.rmtree, base, True)
        prof = os.path.join(base, ".claude", "skills", "job-application-assistant")
        os.makedirs(prof)
        with open(os.path.join(prof, "01-candidate-profile.md"), "w", encoding="utf-8") as fh:
            fh.write("# Candidate Profile\n\n## Identity\n- **Name:** %s\n" % name_line)
        saved = {k: os.environ.pop(k, None) for k in list(os.environ) if k.startswith("JOBKIT_OWNER_")}
        self.addCleanup(lambda: os.environ.update({k: v for k, v in saved.items() if v is not None}))
        return [(k, v) for k, v in csd.identity(base)]

    def test_a_real_john_is_part_of_the_vocabulary(self):
        self.assertIn(("name", "John Fixtureson"), self._identity("John Fixtureson"))

    def test_the_shipped_template_name_is_not(self):
        self.assertNotIn(("name", "[YOUR NAME]"), self._identity("[YOUR NAME]"))
        self.assertNotIn(("name", "Jane Doe"), self._identity("Jane Doe"))


if __name__ == "__main__":
    unittest.main()
