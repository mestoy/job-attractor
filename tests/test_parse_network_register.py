#!/usr/bin/env python3
"""Kit #81 (Matthew, 2026-09-08): parse_network never wrote documents/state/contact.jsonl.

Three defects in the shipped file: `_register_contacts` was defined and never called, it referenced
an undefined `_REGISTERED_FIELDS`, and the `__main__` guard sat ABOVE the function so a wired-in
call raised NameError at run time. Plus one that showed up once it ran: the re-run signature was
keyed on the squashed name while the stored rows are keyed on the LinkedIn handle ("li:<slug>"),
so a second parse of the same export appended every row again.

These tests run the PRODUCTION script as a subprocess against a temp repo, the same way
test_closeness_admission.py does, and read the store the readers read (`state._read_raw`).
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

FIXTURE_CSV = (
    "Notes:\n\n"
    "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
    "Pat,Fixture,https://www.linkedin.com/in/pat-fixture-builds,,Kirkwall Data Co,Senior Product Manager,09 Jun 2020\n"
    "Plain,Person,https://www.linkedin.com/in/plain-person,,Kirkwall Data Co,Product Manager,10 Jun 2020\n"
    "No,Slug,,,Kirkwall Data Co,Analyst,11 Jun 2020\n"
)


class RegisterContactsTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="kit-81-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        os.makedirs(os.path.join(self.root, "documents", "linkedin-exports"))
        os.makedirs(os.path.join(self.root, "documents", "state"))
        self.csv = os.path.join(self.root, "documents", "linkedin-exports", "Connections-09-08-2026.csv")
        open(self.csv, "w").write(FIXTURE_CSV)
        open(os.path.join(self.root, "documents", "blocked-employers-list.md"), "w").write("# blocked\n")
        open(os.path.join(self.root, "job_search_tracker.csv"), "w").write(
            "date,company,role,url,loc,salary,status\n")
        self.store = os.path.join(self.root, "documents", "state", "contact.jsonl")

    def _run(self, *extra):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": self.root}
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "parse_network.py"),
                            self.csv, "--force", *extra],
                           cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout

    def _rows(self):
        if not os.path.exists(self.store):
            return []
        return [json.loads(l) for l in open(self.store, encoding="utf-8") if l.strip()]

    def test_guard_sits_below_every_def(self):
        """Defect 3: the __main__ guard must be the LAST statement, or main() runs before the
        function it calls is defined."""
        src = open(os.path.join(SCRIPTS, "parse_network.py"), encoding="utf-8").read()
        guard = src.index('if __name__ == "__main__":')
        self.assertGreater(guard, src.rindex("\ndef "), "the __main__ guard sits above a def")
        self.assertIn("_REGISTERED_FIELDS = (", src, "defect 2: the constant is not defined")

    def test_first_parse_writes_every_slugged_row_keyed_on_the_handle(self):
        out = self._run()
        rows = self._rows()
        self.assertEqual(len(rows), 2, out)             # the slugless row has nothing durable to add
        keys = sorted(r.get("key") for r in rows)
        self.assertEqual(keys, ["li:pat-fixture-builds", "li:plain-person"])
        for r in rows:
            self.assertEqual(r.get("as_of"), "2026-09-08")
            self.assertEqual(r.get("as_of_source"), "export:Connections-09-08-2026.csv")

    def test_second_parse_of_the_same_export_writes_nothing(self):
        self._run()
        n1 = len(self._rows())
        out = self._run()
        self.assertEqual(len(self._rows()), n1, "re-run appended rows again:\n" + out)

    def test_vanity_slug_resolves_by_name_lookup(self):
        """The symptom in #81: a vanity slug keyed as one word the pool never matched."""
        self._run()
        os.environ["CLAUDE_PROJECT_DIR"] = self.root
        self.addCleanup(lambda: os.environ.pop("CLAUDE_PROJECT_DIR", None))
        import state
        importlib.reload(state)
        rec = state.current("contact", "Pat Fixture",
                            linkedin="https://www.linkedin.com/in/pat-fixture-builds")
        self.assertTrue(rec, "the vanity-slug contact did not resolve")
        self.assertEqual((rec.get("payload") or {}).get("company"), "Kirkwall Data Co")

    def test_no_register_flag_leaves_the_store_alone(self):
        self._run("--no-register")
        self.assertFalse(os.path.exists(self.store))


if __name__ == "__main__":
    unittest.main()
