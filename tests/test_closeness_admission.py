#!/usr/bin/env python3
"""BUG-181 LEVER 2 kit-parity mechanism tests.

A STATED strong-tier closeness answer admits a contact to the people pool regardless of title.
Standard library only, no network, no mutation of the live tree (a temp REPO via CLAUDE_PROJECT_DIR).
These assert the MECHANISM, not shipped defaults ([[a-test-over-a-configurable-knob-must-assert-the-mechanism]]):

  classify()             — a no-signal title is "other" without an admit and "senior-ic" WITH one.
  admits_on_closeness()  — fires only for a STATED strong tier; inferred / thin / absent degrade to False.
  READ path              — a stated strong contact with a no-signal title actually appears in the pool
                           `rank_criteria._people_rows()` feeds `rank_people`; and it degrades to
                           title-only admission when NO closeness store exists.
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

parse_network = importlib.import_module("parse_network")
closeness = importlib.import_module("closeness")

FIXTURE_CSV = (
    "Notes:\n\n"
    "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
    "Close,Analyst,,,Kirkwall Data Co,Business Analyst,09 Jun 2020\n"
    "Cold,Analyst,,,Kirkwall Data Co,Business Analyst,09 Jun 2020\n"
    "Inferred,Analyst,,,Kirkwall Data Co,Business Analyst,09 Jun 2020\n"
    "Titled,Person,,,Kirkwall Data Co,Senior Product Manager,09 Jun 2020\n"
)
FIXTURE_CLOSENESS = json.dumps({"contacts": {
    "Close Analyst": {"closeness": "worked-together", "source": "stated-by-owner"},
    "Inferred Analyst": {"closeness": "know-well", "source": "inferred-from-messages"},
}})


class ClassifyMechanism(unittest.TestCase):
    def test_no_signal_title_red_green(self):
        self.assertEqual(parse_network.classify("Business Analyst"), "other",
                         "RED: no title signal, no closeness -> unrankable")
        self.assertEqual(parse_network.classify("Business Analyst", True), "senior-ic",
                         "GREEN: a stated closeness answer admits the same title")

    def test_admit_flag_does_not_disturb_a_real_title(self):
        self.assertEqual(parse_network.classify("Senior Product Manager", True), "product")

    def test_admits_on_closeness_only_stated_strong(self):
        self.assertTrue(closeness.admits_on_closeness({"closeness": "worked-together"}))
        self.assertTrue(closeness.admits_on_closeness({"closeness": "personal-friend",
                                                       "source": "stated"}))
        self.assertFalse(closeness.admits_on_closeness({"closeness": "know-well",
                                                        "source": "inferred-from-messages"}))
        self.assertFalse(closeness.admits_on_closeness({"closeness": "shared-community"}))
        self.assertFalse(closeness.admits_on_closeness({"closeness": "never-spoke"}))
        self.assertFalse(closeness.admits_on_closeness(None))


class ReadPath(unittest.TestCase):
    """The whole write->read seam. The kit's `parse_network` honors CLAUDE_PROJECT_DIR (so the
    WRITER produces warm-network.md in a temp REPO), while the kit's `rank_criteria` pins REPO to its
    install dir — so the READER is pointed at the temp file by patching `rank_criteria.REPO`, which
    is exactly what its `rd()` reads at call time. `_people_rows()` IS the pool `rank_people` iterates,
    so a name appearing here is a name admitted to the pool."""

    def _pool(self, closeness_json):
        root = tempfile.mkdtemp(prefix="kit-lever2-")
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        os.makedirs(os.path.join(root, "documents", "linkedin-exports"))
        csv = os.path.join(root, "documents", "linkedin-exports", "Connections-99-99-2099.csv")
        open(csv, "w").write(FIXTURE_CSV)
        open(os.path.join(root, "documents", "contact-closeness.json"), "w").write(closeness_json)
        open(os.path.join(root, "documents", "blocked-employers-list.md"), "w").write("# blocked\n")
        open(os.path.join(root, "job_search_tracker.csv"), "w").write(
            "date,company,role,url,loc,salary,status\n")
        env = {**os.environ, "CLAUDE_PROJECT_DIR": root}
        w = subprocess.run([sys.executable, os.path.join(SCRIPTS, "parse_network.py"),
                            csv, "--no-register", "--force"],
                           cwd=root, env=env, capture_output=True, text=True)
        self.assertEqual(w.returncode, 0, w.stderr)
        rc = importlib.import_module("rank_criteria")
        saved = rc.REPO
        try:
            rc.REPO = root                       # rd() joins REPO at call time
            return {nm for nm, *_ in rc._people_rows()}
        finally:
            rc.REPO = saved

    def test_stated_strong_contact_is_admitted(self):
        pool = self._pool(FIXTURE_CLOSENESS)
        self.assertIn("Close Analyst", pool, "stated strong tie with a no-signal title must be admitted")
        self.assertNotIn("Cold Analyst", pool, "no closeness answer -> not admitted")
        self.assertNotIn("Inferred Analyst", pool, "inferred tier must NOT admit")
        self.assertIn("Titled Person", pool, "a real PM title still enters on title alone")

    def test_degrades_with_no_store(self):
        pool = self._pool("{}")
        self.assertNotIn("Close Analyst", pool,
                         "empty store -> title-only admission, so the stated contact is not admitted")
        self.assertIn("Titled Person", pool)


if __name__ == "__main__":
    unittest.main()
