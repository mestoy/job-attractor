"""Hand the screening gate THE BROKEN WORLD and require it not to say yes.

⛔ WHY: on 2026-09-21 a tree was found whose remote veto returned None for
"remote-first culture but the role requires relocation to NYC". Remote is the absolute veto, the
first line of the card. The cause was not the veto's code, which was byte-identical to a tree
where the same input is refused. It was that `kit_config` did not import, and
`check_screen_gate.py` answers a failed import by emptying EVERY list at once — industry, blocked
employers, politics, PE, remote — because the import is a single tuple and one missing name zeroes
all of it. It prints a red warning to stderr and then returns a pass.

⛔ AND 727 GATE TESTS PASSED IN THAT TREE. A green suite is not a working gate; it is a suite that
was never handed the broken world. Every existing test runs with a healthy config, so not one of
them can tell a gate that screened from a gate that was blind and waved the row through.

So this test builds the broken world on purpose: a copy of scripts/ with kit_config.py removed,
which is exactly what a long-lived install looks like when its config falls behind a name the code
now needs. The assertion is not about which message is printed. It is that a KNOWN DISQUALIFIER
DOES NOT COME BACK CLEAN.

A blind gate is allowed to refuse, to hold, or to error. It is not allowed to pass.
"""
import os
import shutil
import subprocess
import sys
import textwrap
import unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX = os.path.join(scratch_root(), "test-blind-gate")
DISQUALIFIER = "remote-first culture but the role requires relocation to NYC"

PROBE = textwrap.dedent("""
    import json, sys
    sys.path.insert(0, "scripts")
    import check_screen_gate as csg
    import rank_criteria as rc
    score, reason = rc._score_fields(
        "Acme", "payments", %r, "", "✅ VC-backed, not PE", "boss (src)", "praise")
    print("JSON" + json.dumps({
        "config_error": bool(getattr(csg, "CONFIG_ERROR", None)),
        "passed": score is not None,
        "reason": reason or "",
    }))
""")


def _probe(root, remote_field):
    r = subprocess.run([sys.executable, "-c", PROBE % remote_field],
                       cwd=root, capture_output=True, text=True, timeout=120)
    for ln in r.stdout.splitlines():
        if ln.startswith("JSON"):
            import json
            return json.loads(ln[4:])
    raise AssertionError("the probe produced no result:\n%s\n%s" % (r.stdout[-1500:], r.stderr[-1500:]))


class TestABlindGateDoesNotPass(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        os.makedirs(SANDBOX)
        shutil.copytree(os.path.join(REPO, "scripts"), os.path.join(SANDBOX, "scripts"))
        self.blinded = os.path.join(SANDBOX, "scripts", "kit_config.py")
        os.remove(self.blinded)

    def tearDown(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)

    def test_the_world_really_is_broken(self):
        """A control. Without this, 'the gate refused' could mean the config loaded fine and the
        ordinary veto fired, which would prove nothing about blindness."""
        got = _probe(SANDBOX, DISQUALIFIER)
        self.assertTrue(got["config_error"],
                        "kit_config still imported, so the gate was never blinded and the "
                        "assertion below is measuring the healthy path")

    def test_the_healthy_gate_refuses_this_input(self):
        """The other control. The fixture has to be a real disqualifier in a working kit, or a
        refusal in the blind case says nothing about screening."""
        got = _probe(REPO, DISQUALIFIER)
        self.assertFalse(got["config_error"], "this repo's own kit_config did not import")
        self.assertFalse(got["passed"],
                         "a relocation clause passed the gate in a HEALTHY kit; the fixture is "
                         "wrong, or something much worse is true")

    def test_a_blind_gate_does_not_pass_a_relocation_clause(self):
        got = _probe(SANDBOX, DISQUALIFIER)
        self.assertFalse(
            got["passed"],
            "the screening gate could not load its config, said so on stderr, and passed a role "
            "requiring relocation anyway. Remote is the absolute veto. A gate that cannot see "
            "must refuse, not wave the row through: the whole point is that nobody has to know "
            "to check.")


if __name__ == "__main__":
    unittest.main()
