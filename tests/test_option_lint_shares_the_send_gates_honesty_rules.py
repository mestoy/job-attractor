"""BUG-202 item 3: check_preview blocks drafted-outreach previews and labels carrying text the send gate rejects, from ONE
shared function (check_outreach.honesty_fails), never a copy of the lists."""
import os
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


class OptionLintSharesTheSendGate(unittest.TestCase):
    def test_the_rules_live_in_check_outreach_and_check_preview_imports_them(self):
        pre = open(os.path.join(SCRIPTS, "check_preview.py"), encoding="utf-8").read()
        out = open(os.path.join(SCRIPTS, "check_outreach.py"), encoding="utf-8").read()
        self.assertIn("def honesty_fails(", out)
        self.assertIn("honesty_fails", pre)
        self.assertNotIn("RETIRED_PATTERNS", pre)
        self.assertNotIn("ROLE_IMPLY_PATTERNS", pre)

    def test_honesty_fails_flags_a_configured_retired_figure(self):
        sys.path.insert(0, SCRIPTS)
        try:
            import check_outreach
            old = list(check_outreach.RETIRED)
            check_outreach.RETIRED[:] = ["99.9%"]
            try:
                self.assertTrue(any("retired/incorrect figure" in m for m in check_outreach.honesty_fails("We hit 99.9% uptime.")))
                self.assertEqual([], [m for m in check_outreach.honesty_fails("We hit a great uptime.") if "99.9%" in m])
            finally:
                check_outreach.RETIRED[:] = old
        finally:
            sys.path.remove(SCRIPTS)


if __name__ == "__main__":
    unittest.main()
