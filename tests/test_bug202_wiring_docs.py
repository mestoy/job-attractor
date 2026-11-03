"""BUG-202 wiring: the documented co-construction and send sequence names scripts/preflight_note.py BEFORE the reviewer panel
(scripts/review_outreach.py), with an advisory run after every beat pick. The panel receipt is bound to the body's hash, so
the order is the point."""
import os
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = ".claude/skills/pairing-model/SKILL.md"
CHECKLIST = "partner-docs/workflow-checklist.md"
BODY = "partner-docs/email-body-checklist.md"


def read(rel):
    with open(os.path.join(KIT, rel), encoding="utf-8") as fh:
        return fh.read()


class DocumentedSequenceNamesPreflightBeforeThePanel(unittest.TestCase):
    def test_the_checklist_names_preflight_before_the_reviewer_panel(self):
        text = read(CHECKLIST)
        self.assertLess(text.index("preflight_note.py"), text.index("review_outreach.py"))

    def test_the_pairing_skill_runs_advisory_after_each_pick_and_hard_before_the_panel(self):
        text = read(SKILL)
        self.assertIn("AFTER EVERY PICK", text)
        self.assertIn("named fix to beat N", text)
        self.assertNotIn("is folded into the NEXT beat", text)
        self.assertLess(text.index("--advisory"), text.index("3. **ITERATE TO APPROVAL"))
        self.assertLess(text.index("(no `--advisory`)"), text.index("review_outreach.py"))

    def test_the_email_body_checklist_points_at_preflight(self):
        self.assertIn("preflight_note.py", read(BODY))

    def test_every_script_the_docs_name_exists(self):
        for script in ("preflight_note.py", "review_outreach.py", "body_gates.py"):
            self.assertTrue(os.path.isfile(os.path.join(KIT, "scripts", script)), script)


if __name__ == "__main__":
    unittest.main()
