#!/usr/bin/env python3
"""Q29 (b): the bare-token claim on the blocked list, plan rev 2 invariants 4 to 6 (Review 125, 125b; kit port of AJS Q29b).

A candidate whose FIRST word is the whole canon key of a blocked entry (`Quorble Technologies` against
`Quorble`) stays 🔴 ALREADY-SEEN and says it "may be a different company with the same name; verify".
A candidate whose first word is only PART of a longer blocked name (`Gladwyn Rose Research` against
`Gladwyn River Fake`) is 🟡 NAME COLLISION. On --send-gate a blocked-list 🟡 BLOCKS (exit 1) until
verified; BUG-244's domain-mismatch 🟡 stays non-blocking (exit 3).

Every name here is obviously fake (Zq... / Gladwyn... / Zorb...): no real company, no real ruling.
Runs the REAL check_dup.py as a subprocess against a temp tree. The kit ships no live blocked list,
so the AJS live-list measurement test is replaced by the seed-loads-clean tests in TestKitPort.
Run: python3 -m unittest tests/test_check_dup_bare_token_collision.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
SCRATCH = "/home/vscode/render/q29k-tok"
NOTE = "may be a different company with the same name; verify"

LIST = """# Blocked employers (FIXTURE; the prose on every row is fake)

**⛔ fixture rows**

- **Quorble** (fixture row one, 2026-07-01). Fake reason text.
- **Plinth** (fixture row two, 2026-07-01). Fake reason text.
- **Sprockwin** (fixture row three, 2026-07-01). Fake reason text.
- **Gladwyn River Fake** (fixture row four, 2026-07-01). Fake reason text.
- **Zzyzx Sprockets** (fixture row five, 2026-07-01). Fake reason text.
- **Brimwick Hollow Networks** (fixture row six, 2026-07-01). Fake reason text.
- **Zorbdom (zorbdom.io)** (fixture row seven with a domain, 2026-07-01). Fake reason text.
- **Zorbkey** (fixture row eight, 2026-07-01). Fake reason text.
- **Zorbkey Labs Fake** (fixture row nine, 2026-07-01). Fake reason text.
- **Quibble Zorbtoken** (fixture row ten, token only as the LAST word, 2026-07-01). Fake reason text.
"""


def make_tree(extra_files=None, extra_list=""):
    os.makedirs(SCRATCH, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="tok_", dir=SCRATCH)
    os.makedirs(os.path.join(tmp, "documents"))
    with open(os.path.join(tmp, "documents", "blocked-employers-list.md"), "w", encoding="utf-8") as fh:
        fh.write(LIST + extra_list)
    for rel, text in (extra_files or {}).items():
        path = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    env = {k: v for k, v in os.environ.items() if k not in ("JOBSEARCH_DATA_ROOT", "JOBSEARCH_TEST")}
    env["CLAUDE_PROJECT_DIR"] = tmp
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "seed_employers.py")],
                       capture_output=True, text=True, env=env, cwd=tmp, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    return tmp


def run_dup(tmp, company, *flags):
    env = {k: v for k, v in os.environ.items() if k not in ("JOBSEARCH_DATA_ROOT", "JOBSEARCH_TEST")}
    env.update(CLAUDE_PROJECT_DIR=tmp, JOBSEARCH_DATA_ROOT=tmp, JOBSEARCH_TEST="1")
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_dup.py"), *flags, company],
                          capture_output=True, text=True, env=env, cwd=tmp, timeout=120)


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = make_tree()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def assertRedWithNote(self, company, *flags):
        r = run_dup(self.tmp, company, *flags)
        self.assertEqual(r.returncode, 1, (company, r.stdout[-700:], r.stderr[-300:]))
        self.assertIn("ALREADY-SEEN", r.stdout, company)
        self.assertIn(NOTE, r.stdout, company)
        return r

    def assertCollision(self, company, token, exit_code, *flags):
        r = run_dup(self.tmp, company, *flags)
        self.assertEqual(r.returncode, exit_code, (company, r.stdout[-700:], r.stderr[-300:]))
        self.assertIn("NAME COLLISION", r.stdout, company)
        self.assertIn(f"'{token}'", r.stdout, company)
        self.assertNotIn("ALREADY-SEEN", r.stdout, company)
        return r


class TestInvariant4(Fixture):
    """A whole key stays 🔴 with the note; part of a longer name is 🟡; the send gate holds both."""

    def test_part_of_a_longer_blocked_name_is_a_collision_naming_the_token(self):
        r = self.assertCollision("Gladwyn Rose Research", "gladwyn", 3)
        self.assertIn("Gladwyn River Fake", r.stdout)

    def test_a_token_that_is_only_the_last_word_of_a_blocked_head_gives_no_collision(self):
        # Review 130 S1: `Zorbtoken` ends the blocked head `Quibble Zorbtoken`; only a head whose
        # FIRST word equals the token counts (not "Quibble LIFE" for "Life ...").
        for flags in ((), ("--send-gate",)):
            r = run_dup(self.tmp, "Zorbtoken Gadgetry", *flags)
            self.assertNotIn("NAME COLLISION", r.stdout, flags)
            # the long token still gives the OLD weak "POSSIBLE" prose mention (exit 3), never a block
            self.assertNotEqual(r.returncode, 1, (flags, r.stdout[-500:]))

    def test_a_one_word_candidate_keeps_its_full_name_needle_verdict(self):
        # Review 125 case 3: a one-word candidate's needle is the FULL name, not a bare token, so
        # `Zzyzx` against `Zzyzx Sprockets` is the existing full-name hit and is unchanged (🔴, exit 1).
        r = run_dup(self.tmp, "Zzyzx")
        self.assertEqual(r.returncode, 1, r.stdout[-500:])
        self.assertIn("ALREADY-SEEN", r.stdout)

    def test_a_whole_key_stays_red_with_the_note(self):
        self.assertRedWithNote("Quorble Technologies")
        self.assertRedWithNote("Plinth Payments")

    def test_send_gate_blocks_all_three_until_verified(self):
        self.assertRedWithNote("Quorble Technologies", "--send-gate")
        self.assertRedWithNote("Plinth Payments", "--send-gate")
        r = self.assertCollision("Gladwyn Rose Research", "gladwyn", 1, "--send-gate")
        self.assertRegex(r.stdout, r"(?i)send.?gate.*(block|hold|verif)|verif.*send")

    def test_kit_gap_no_registry_domain_means_no_domain_downgrade(self):
        # KIT DIVERGENCE (reported, not fixed here): the kit seeder records no `domain` on registry
        # rows, so BUG-244's domain-mismatch downgrade has nothing to compare and a whole-key hit
        # stays red even with a differing --domain. The Q29b path itself runs through the same
        # apply_domain_collision as AJS; when the kit seeder gains domains this should flip to exit 3.
        for flags in ((), ("--send-gate",)):
            r = run_dup(self.tmp, "Zorbdom Platform", "--domain", "zorbdom.ai", *flags)
            self.assertEqual(r.returncode, 1, (flags, r.stdout[-600:]))
            self.assertIn(NOTE, r.stdout)

    def test_a_declared_cleared_candidate_is_the_recorded_verification(self):
        tmp = make_tree(extra_list="- **Gladwyn Rose Research** (NOT blocked, verified a different company 2026-10-04). Fake.\n")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        r = run_dup(tmp, "Gladwyn Rose Research", "--send-gate")
        # Q29b raises neither claim for a cleared candidate, and the 'not blocked' row is demoted to a weak
        # 🟡 (already seen, not a block): the clearing path the printout advises really clears the gate.
        self.assertNotIn("NAME COLLISION", r.stdout)
        self.assertNotIn(NOTE, r.stdout)
        self.assertEqual(r.returncode, 3, r.stdout[-600:])

    def test_the_printed_clearing_advice_works_for_a_collision(self):
        # Replays the advice end to end: 🟡 collision that holds the gate, add the 'not blocked' note, rerun.
        r = run_dup(self.tmp, "Gladwyn Rose Research", "--send-gate")
        self.assertEqual(r.returncode, 1, r.stdout[-400:])
        tmp = make_tree(extra_list="- **Gladwyn Rose Research** (NOT blocked, verified a different company). Fixture.\n")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        r = run_dup(tmp, "Gladwyn Rose Research", "--send-gate")
        self.assertNotEqual(r.returncode, 1, r.stdout[-600:])


class TestInvariant5(Fixture):
    """A real block is still 🔴."""

    def test_canon_hit_full_name_and_whole_key_forms(self):
        r = run_dup(self.tmp, "Brimwickhollownetworks")
        self.assertEqual(r.returncode, 1, r.stdout[-500:])
        self.assertIn("BLOCKED", r.stdout)
        r = run_dup(self.tmp, "Gladwyn River Fake")
        self.assertEqual(r.returncode, 1, r.stdout[-500:])
        self.assertNotIn("NAME COLLISION", r.stdout)
        for name in ("Plinth Payments", "Sprockwin Technologies", "Quorble Technologies"):
            with self.subTest(name=name):
                self.assertRedWithNote(name)

    def test_a_whole_key_wins_when_a_longer_name_shares_it(self):
        # `zorbkey` is a blocked entry AND the first word of `Zorbkey Labs Fake`: the candidate's
        # first word equals a whole key, so it stays 🔴 and is never softened to 🟡.
        self.assertRedWithNote("Zorbkey Widgets")


class TestInvariant6(unittest.TestCase):
    """Other stores unchanged: a bare-token hit in the send log reports the prior contact as today."""

    def test_send_log_bare_token_still_reports(self):
        row = {"ts": "2026-07-01T10:00:00", "company": "Zorbwidgets", "status": "sent", "to": "x@example.invalid", "rung": "cold-boss"}
        tmp = make_tree({"documents/send-log.jsonl": json.dumps(row) + "\n"})
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        r = run_dup(tmp, "Zorbwidgets Gadgetry")
        self.assertEqual(r.returncode, 1, r.stdout[-600:])
        self.assertIn("send log", r.stdout.lower())
        self.assertNotIn("NAME COLLISION", r.stdout)

    def test_a_company_with_no_blocked_word_is_still_new(self):
        tmp = make_tree()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        r = run_dup(tmp, "Qwerty Fakeworks Gadgetry")
        self.assertEqual(r.returncode, 0, r.stdout[-400:])
        self.assertIn("NEW", r.stdout)


class TestKitPort(unittest.TestCase):
    """Kit-only: the shipped seed loads clean under the new parser, and a dead exoneration import
    fails CLOSED (a 'not blocked' line still reads as a block, never as a pass)."""

    def _heads(self, text):
        tmp = tempfile.mkdtemp(prefix="heads_", dir=SCRATCH)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "documents"))
        with open(os.path.join(tmp, "documents", "blocked-employers-list.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        code = (
            "import json,sys; sys.path.insert(0, %r)\n"
            "import check_dup\n"
            "print(json.dumps([[h[2], h[3]] for h in check_dup._blocked_heads()]))\n"
            "print(json.dumps(check_dup.blocked_token_hits('Gladwyn Rose Research')))\n"
        ) % SCRIPTS
        env = {k: v for k, v in os.environ.items() if k not in ("JOBSEARCH_DATA_ROOT", "JOBSEARCH_TEST")}
        env.update(CLAUDE_PROJECT_DIR=tmp, JOBSEARCH_DATA_ROOT=tmp, JOBSEARCH_TEST="1")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=tmp, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        lines = r.stdout.strip().splitlines()
        return json.loads(lines[-2]), json.loads(lines[-1])

    def test_the_shipped_blocked_list_seed_loads_clean(self):
        for rel in ("partner-docs/blocked-employers-list.md",
                    "tests/fixtures/partner-install/documents/blocked-employers-list.md"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                heads, hits = self._heads(fh.read())
            self.assertIsInstance(heads, list, rel)
            self.assertEqual(hits["part"], [], rel)

    def test_an_empty_word_head_is_skipped_not_raised(self):
        heads, hits = self._heads("- **\u2014** nothing but a dash\n- **( )**: parens only\n- **Gladwyn River Fake**: x\n")
        self.assertEqual([h[0] for h in heads], ["gladwynriverfake"])
        self.assertEqual(len(hits["part"]), 1)

    def test_a_dead_exoneration_import_fails_closed(self):
        # With exoneration unimportable _EXONERATED is None: a 'NOT blocked' row must still count as a
        # live head (a block), never be skipped. Run in a child with the module hidden.
        tmp = tempfile.mkdtemp(prefix="dead_", dir=SCRATCH)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "documents"))
        with open(os.path.join(tmp, "documents", "blocked-employers-list.md"), "w", encoding="utf-8") as fh:
            fh.write("- **Gladwyn River Fake** (NOT blocked, verified a different company). Fake.\n")
        code = (
            "import json,sys; sys.path.insert(0, %r)\n"
            "sys.modules['exoneration'] = None\n"
            "import check_dup\n"
            "assert check_dup._EXONERATED is None\n"
            "print(json.dumps(len(check_dup._blocked_heads())))\n"
        ) % SCRIPTS
        env = {k: v for k, v in os.environ.items() if k not in ("JOBSEARCH_DATA_ROOT", "JOBSEARCH_TEST")}
        env.update(CLAUDE_PROJECT_DIR=tmp, JOBSEARCH_DATA_ROOT=tmp, JOBSEARCH_TEST="1")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=tmp, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), 1)


if __name__ == "__main__":
    unittest.main()
