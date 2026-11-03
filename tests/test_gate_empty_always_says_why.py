"""An empty gate must always say WHY (K3).

⛔ THE SHAPE THIS GUARDS AGAINST is the one that has cost the most this week: a check returns
nothing and the nothing is read as an answer. `_build_rulings()` returns an empty set for at least
three different reasons, and every one of them reaches the person as the same sentence, "no valid
BUILD ruling recorded":

  1. there is no ledger file at all, which is TRUE and NORMAL on a fresh install;
  2. the ledger cannot be read;
  3. the ledger has rows and no key on this machine verifies them (kit #149, which cost a partner
     nine days).

Only the third had a diagnosis. A person installing for the first time was told their ruling was
missing when they had simply never made one.
"""
import os
import _roots
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import check_preview as cp  # noqa: E402


class TestEveryEmptyStateNamesItsCause(unittest.TestCase):
    """Each case sets the module's LEDGER to a state and asks for the reason."""

    def setUp(self):
        self._ledger = cp.LEDGER

    def tearDown(self):
        cp.LEDGER = self._ledger

    def test_a_missing_ledger_says_so_and_does_not_imply_a_missing_ruling(self):
        cp.LEDGER = os.path.join(tempfile.mkdtemp(), "nope.jsonl")
        _roots.patch_roots(self, os.path.dirname(cp.LEDGER))
        why = cp.gate_empty_reason()
        self.assertTrue(why, "a missing ledger must give a reason, not an empty string")
        self.assertIn("no ledger", why.lower(),
                      "the reason must name the missing ledger, since on a fresh install that is "
                      "normal rather than a fault")

    def test_an_unreadable_ledger_says_so(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "ledger.jsonl")
        os.makedirs(p)  # a directory where a file is expected: open() will fail
        cp.LEDGER = p
        _roots.patch_roots(self, d)
        why = cp.gate_empty_reason()
        self.assertTrue(why, "an unreadable ledger must give a reason")
        self.assertIn("could not be read", why.lower())

    def test_an_empty_ledger_file_says_it_holds_no_rulings(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "ledger.jsonl")
        open(p, "w").close()
        cp.LEDGER = p
        _roots.patch_roots(self, d)
        why = cp.gate_empty_reason()
        self.assertTrue(why, "an empty ledger must give a reason")
        self.assertIn("no build", why.lower())

    def test_the_reason_is_never_empty_in_any_state_we_can_build(self):
        """The rule, stated once: empty with no reason is a failure, not a pass."""
        d = tempfile.mkdtemp()
        states = {
            "missing": os.path.join(d, "absent.jsonl"),
            "empty": os.path.join(d, "empty.jsonl"),
            "junk": os.path.join(d, "junk.jsonl"),
        }
        open(states["empty"], "w").close()
        with open(states["junk"], "w") as fh:
            fh.write("not json at all\n")
        for name, path in states.items():
            with self.subTest(state=name):
                cp.LEDGER = path
                _roots.patch_roots(self, os.path.dirname(path))
                self.assertTrue(cp.gate_empty_reason(),
                                f"the {name} state returned no reason")


if __name__ == "__main__":
    unittest.main()


class TestTheRefusalMessageCarriesTheReason(unittest.TestCase):
    """The reason must reach the PERSON, not only exist in a function nobody calls."""

    def test_the_build_gate_block_prints_why(self):
        src = open(os.path.join(REPO, "scripts", "check_preview.py"), encoding="utf-8").read()
        i = src.index("BUILD GATE not passed")
        window = src[i:i + 500]
        self.assertIn("WHY THE GATE HAS NOTHING", window,
                      "the refusal must name the cause where the person reads it")
        self.assertIn("gate_empty_reason()", window,
                      "the cause must be computed, not a fixed sentence that could be wrong")

    def test_gate_empty_reason_is_not_dead_code(self):
        """A reason function nobody calls is the same failure in a new costume."""
        src = open(os.path.join(REPO, "scripts", "check_preview.py"), encoding="utf-8").read()
        calls = src.count("gate_empty_reason()")
        self.assertGreaterEqual(calls, 2,
                                "gate_empty_reason must be defined AND called at least once")
