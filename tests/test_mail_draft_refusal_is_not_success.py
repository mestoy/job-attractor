"""The SHIPPING copy of mail-draft.sh must not report success when no draft was made.

⛔ THIS IS partner-starter/scripts/mail-draft.sh, THE COPY THAT SHIPS. backup.sh:28 names
partner-starter/ the source of truth and :194-201 ships partner-starter/scripts/*.sh, holding back
only kit_config.py. The AJS copy at scripts/mail-draft.sh never reaches anyone.

⛔ EVERY ASSERTION HERE IS BRANCH-AWARE, BY CONSTRUCTION. An earlier instrument searched the whole
file for "Your note is still in $BODYFILE" and passed, because that sentence already exists 253
lines away in the delivery route. A whole-file substring search cannot tell a fixed branch from an
unrelated line that happens to share its words.
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


def _failure_branch():
    """The text from the osascript failure branch to the end of the file, and nothing before it.

    Anchored on the branch's own message so it cannot drift onto another `else`.
    """
    src = _src()
    i = src.index('echo "ERROR creating draft')
    j = src.rindex("\nelse", 0, i)
    return src[j:]


class TestItParses(unittest.TestCase):
    def test_bash_accepts_it(self):
        """A guard, not a proof: it passes before and after. Without it the rest is noise."""
        r = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestTheFailureBranchRefuses(unittest.TestCase):
    def test_the_branch_exits_7(self):
        self.assertIn("exit 7", _failure_branch(),
                      "the osascript failure branch must exit 7, not print and fall off the end")

    def test_the_branch_does_not_merely_print(self):
        """The original bug: `else / echo / fi` and nothing after it, so the script exited 0."""
        branch = _failure_branch()
        self.assertNotRegex(
            branch, r'else\s*\n\s*echo "ERROR creating draft[^\n]*\n\s*fi\s*\Z',
            "the branch still ends on an echo, which exits 0 with no draft")

    def test_the_error_goes_to_stderr_in_this_branch(self):
        self.assertRegex(_failure_branch(),
                         r'echo "ERROR creating draft \(exit \$STATUS\)\." >&2')

    def test_this_branch_says_where_the_note_is(self):
        """Branch-scoped on purpose: the same sentence exists elsewhere in the file."""
        self.assertIn("Your note is still in $BODYFILE", _failure_branch())


class TestStatusCarriesTheDeliveryCode(unittest.TestCase):
    def test_status_is_not_read_from_a_closing_fi(self):
        """`STATUS=$?` after an `if` reads the `fi`, which is 0 either way, so the success path
        was taken unconditionally. Verified by running it before this was changed."""
        src = _src()
        self.assertNotRegex(src, r'\bfi\n\s*STATUS=\$\?',
                            "STATUS must not be read from the exit of a closing fi")
        self.assertIn('STATUS="$_OSA_RC"', src,
                      "STATUS must carry the delivery's own return code")


if __name__ == "__main__":
    unittest.main()
