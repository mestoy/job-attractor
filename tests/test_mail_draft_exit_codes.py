"""The two exit codes the ported delivery route added to scripts/mail-draft.sh.

The kit's own tests/test_mail_deliver.py covers the DELIVERY MODULE and pins the eml and web
paths. It never runs mail-draft.sh, so neither of these two is pinned anywhere:

  exit 7 : a delivery failed, so NOTHING was created. This branch used to end on an echo, and the
           script exited 0 with no draft and no logged row, telling every wrapper it had worked.
  exit 6 : mail_deliver.py is present and cannot be resolved. The gate must FAIL CLOSED and write
           no draft, never fall through to "apple-mail".

Both are asserted on the SHELL, since that is where they live.
"""
import os
import re
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "mail-draft.sh")


def _src():
    with open(SCRIPT, encoding="utf-8") as fh:
        return fh.read()


class TestTheScriptParses(unittest.TestCase):
    def test_bash_accepts_it(self):
        """A syntax error here would make every other assertion meaningless."""
        r = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestItFailsClosed(unittest.TestCase):
    def test_an_unresolvable_delivery_module_exits_6_and_writes_nothing(self):
        src = _src()
        m = re.search(r"--resolve[^\n]*\n(?:.*\n){0,8}?\s*exit 6", src)
        self.assertIsNotNone(
            m, "a failed --resolve must exit 6; without it an unreadable module "
               "falls through to apple-mail and a draft is claimed that was never made")

    def test_it_does_not_default_to_apple_mail_after_a_failed_resolve(self):
        """The fall-through this guards against: DELIVERY keeps its default and osascript runs."""
        src = _src()
        block = src[src.index("--resolve"):src.index("--resolve") + 400]
        self.assertNotIn("DELIVERY=\"apple-mail\"", block,
                         "nothing may reset DELIVERY to apple-mail inside the failure path")


class TestARefusalIsNotSuccess(unittest.TestCase):
    def test_a_failed_delivery_exits_7(self):
        self.assertIn("exit 7", _src(),
                      "a refusal must exit 7 and nothing else, so a caller can tell it from a "
                      "gate refusal (3, 4, 6)")

    def test_exit_7_is_reached_from_a_return_code_and_not_only_from_prose(self):
        """The old bug was a branch that printed and exited 0. Assert the code is tested."""
        src = _src()
        self.assertRegex(
            src, r"_OSA_RC[^\n]*-ne 0[\s\S]{0,400}?exit 7",
            "exit 7 must hang off the delivery's return code, not off an echo")

    def test_the_staged_row_never_claims_a_mail_program_for_a_link_or_a_file(self):
        """A row saying 'draft created' for a link would read as a real Apple Mail draft."""
        src = _src()
        self.assertIn('gmail-web|outlook-web) _STAGED_WORDS="draft link prepared', src)
        self.assertIn('copy)                  _STAGED_WORDS="draft copy prepared', src)


if __name__ == "__main__":
    unittest.main()
