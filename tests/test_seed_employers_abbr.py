#!/usr/bin/env python3
"""Q29 (a): the "ABBR (Full Name)" form in seed_employers.py, plan rev 2 invariants 1 to 3 and 7.

A blocked company written `ABBR (Full Name)` must be blocked under BOTH spellings through the
registry's own aliases. The ABBR is aliased only at 4+ characters (ALIAS_MIN), else parked and
printed, so a 3-letter abbreviation never becomes a skeleton key. Fixtures use obviously fake names.

Runs the REAL seeder as a subprocess against a temp tree (CLAUDE_PROJECT_DIR), never the live list.
Run: python3 -m unittest tests.test_seed_employers_abbr
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
SCRATCH = "/home/vscode/render/q29k-abbr"

LIST = """# Blocked employers (FIXTURE, fake names only)

**⛔ fixture rows**

- **ZQNOV (ZQNOV Holdings, fixture ticker)**: fixture reason, 2026-07-01.
- **EWF (Example Widgets Fake)**: fake widget maker, 2026-07-02.
- **ZQI (Zorb Quartz Industries)**: three-letter abbreviation, 2026-07-03.
- **ZCS (Zzyzx Computer Services, Nowhere)**: initials row, 2026-07-04.
- **Zorbposh (zorbposh.vip, consumer ticketing)**: a parenthetical that is not a name, 2026-07-05.
- **Fake Gadget Works (FGW)**: reverse shape, 2026-07-06.
"""


def make_tree():
    os.makedirs(SCRATCH, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="abbr_", dir=SCRATCH)
    os.makedirs(os.path.join(tmp, "documents"))
    with open(os.path.join(tmp, "documents", "blocked-employers-list.md"), "w", encoding="utf-8") as fh:
        fh.write(LIST)
    return tmp


def env_for(tmp):
    env = {k: v for k, v in os.environ.items() if k not in ("JOBSEARCH_DATA_ROOT", "JOBSEARCH_TEST")}
    env["CLAUDE_PROJECT_DIR"] = tmp
    return env


def seed(tmp):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "seed_employers.py")],
                       capture_output=True, text=True, env=env_for(tmp), cwd=tmp, timeout=120)
    assert r.returncode == 0, (r.returncode, r.stdout[-500:], r.stderr[-800:])
    return r.stdout


def probe(tmp, names):
    """{name: [is_blocked, blocked_key_hit]} computed in a child process against the temp tree."""
    code = (
        "import json,sys; sys.path.insert(0, %r)\n"
        "import employers, check_dup\n"
        "names = json.loads(sys.argv[1])\n"
        "print(json.dumps({n: [employers.is_blocked(n), check_dup.blocked_key_hit(n)] for n in names}))\n"
    ) % SCRIPTS
    r = subprocess.run([sys.executable, "-c", code, json.dumps(names)], capture_output=True, text=True,
                       env=env_for(tmp), cwd=tmp, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def registry(tmp):
    with open(os.path.join(tmp, "documents", "employers.jsonl"), encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


class AbbrAliasUnit(unittest.TestCase):
    def setUp(self):
        import seed_employers
        self.s = seed_employers

    def test_abbr_aliases_exists(self):
        self.assertTrue(hasattr(self.s, "abbr_aliases"), "abbr_aliases() is the new pure function")

    def test_first_word_form_whose_full_name_canons_to_the_own_key_adds_nothing(self):
        # canon() already strips "Holdings", so the full name IS the row's key (the ZQNOV row).
        kept, parked = self.s.abbr_aliases("**ZQNOV (ZQNOV Holdings, fixture ticker)**: x", own_keys={"zqnov"})
        self.assertEqual((kept, parked), ([], []))

    def test_first_word_form_keeps_a_full_name_that_canons_differently(self):
        kept, parked = self.s.abbr_aliases("**ZQPAY (ZQPAY Network Fake)**: x", own_keys={"zqpay"})
        self.assertEqual(kept, ["ZQPAY Network Fake"])
        self.assertEqual(parked, [])

    def test_three_letter_abbr_is_parked_not_aliased(self):
        kept, parked = self.s.abbr_aliases("**ZQI (Zorb Quartz Industries)** x", own_keys=set())
        self.assertEqual(kept, ["Zorb Quartz Industries"])
        self.assertEqual(parked, ["ZQI"])

    def test_not_initials_and_not_first_word_is_no_alias(self):
        self.assertEqual(self.s.abbr_aliases("**Zorbposh (zorbposh.vip, consumer ticketing)** x", set()), ([], []))
        self.assertEqual(self.s.abbr_aliases("**ZQX (Acme Widgets)** x", set()), ([], []))

    def test_reverse_shape(self):
        kept, parked = self.s.abbr_aliases("**Fake Gadget Works (FGW)** x", own_keys={"fakegadgetworks"})
        self.assertEqual(kept, [])
        self.assertEqual(parked, ["FGW"])
        kept, parked = self.s.abbr_aliases("**Fake Gadget Works (FAKE)** x", own_keys={"fakegadgetworks"})
        self.assertEqual(kept, ["FAKE"])

    def test_long_or_lowercase_full_name_is_ignored(self):
        self.assertEqual(self.s.abbr_aliases("**ABCD (one Two Three)** x", set()), ([], []))
        self.assertEqual(self.s.abbr_aliases("**ABCD (Alpha Beta Gamma Delta Epsilon Zeta)** x", set()), ([], []))


class AbbrSeeding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = make_tree()
        cls.out = seed(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_inv1_both_spellings_block(self):
        got = probe(self.tmp, ["ZQNOV Holdings", "Zqnov Holdings, Inc.", "ZQNOV"])
        for name, (blocked, key) in got.items():
            self.assertTrue(blocked, f"is_blocked({name!r})")
            self.assertTrue(key and key != "__import_failed__", f"blocked_key_hit({name!r}) -> {key!r}")

    def test_inv1_example_widgets_full_name_is_a_registry_alias(self):
        got = probe(self.tmp, ["Example Widgets Fake", "EWF"])
        self.assertTrue(got["Example Widgets Fake"][0])
        self.assertFalse(got["EWF"][0], "EWF canons to 3 characters: parked, never aliased")

    def test_inv2_no_skeleton_key(self):
        got = probe(self.tmp, ["Zorb Quartz Industries", "ZQI", "Zqi Cream Labs"])
        self.assertTrue(got["Zorb Quartz Industries"][0])
        self.assertFalse(got["ZQI"][0])
        self.assertFalse(got["Zqi Cream Labs"][0])
        self.assertRegex(self.out, r"(?i)parked.*\bZQI\b|\bZQI\b.*parked")

    def test_inv3_initials_not_any_parenthetical(self):
        got = probe(self.tmp, ["Zorbposh", "zorbposh.vip", "consumer ticketing", "Zzyzx Computer Services", "ZCS"])
        self.assertTrue(got["Zorbposh"][0])                 # its own head is still a key
        self.assertFalse(got["zorbposh.vip"][0])
        self.assertFalse(got["consumer ticketing"][0])
        self.assertTrue(got["Zzyzx Computer Services"][0])
        self.assertFalse(got["ZCS"][0])

    def test_reverse_shape_parks_a_three_letter_abbr(self):
        got = probe(self.tmp, ["Fake Gadget Works", "FGW"])
        self.assertTrue(got["Fake Gadget Works"][0])
        self.assertFalse(got["FGW"][0])

    def test_inv7_seeding_twice_adds_no_second_alias(self):
        before = {r["key"]: list(r.get("aliases") or []) for r in registry(self.tmp)}
        seed(self.tmp)
        after = {r["key"]: list(r.get("aliases") or []) for r in registry(self.tmp)}
        self.assertEqual(before, after)
        for k, al in after.items():
            self.assertEqual(len(al), len(set(al)), f"duplicate alias on {k}")

    def test_inv7_registry_equivalence_stays_green(self):
        code = (
            "import json,sys; sys.path.insert(0, %r)\n"
            "import registry_equivalence as r\n"
            "print(json.dumps(r.untraceable_blocked()))\n"
        ) % SCRIPTS
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env=env_for(self.tmp), cwd=self.tmp, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), [])


class DeclareBlockedCallsTheSameFunction(unittest.TestCase):
    def test_a_mid_session_block_gets_its_alias_at_once(self):
        tmp = make_tree()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        reg = os.path.join(tmp, "documents", "employers.jsonl")
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "import employers\n"
            "n = employers.declare_blocked([{'company': 'ZQWF (Zorb Quartz Widgets Fake)', 'ts': '2026-10-04'}], path=%r)\n"
            "print(n, employers.is_blocked('Zorb Quartz Widgets Fake'), employers.is_blocked('ZQWF'))\n"
        ) % (SCRIPTS, reg)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env_for(tmp), cwd=tmp, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(r.stdout.split(), ["1", "True", "True"])


if __name__ == "__main__":
    unittest.main()
