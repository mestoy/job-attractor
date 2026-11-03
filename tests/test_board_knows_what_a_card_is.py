"""board.load_cards must take only files that ARE cards, by the shape of their name.

⛔ WHAT HAPPENED, 2026-09-21: the owner's "Awaiting a decision" queue held a card that was a
planning memo, named `<topic>-card-supply-<date>.md`. It matched
the `*-card-*.md` glob, and the only filter was NOT_A_CARD, a list of substrings someone happened
to add. The memo contained none of them, so it became a card on his board.

⛔ AND ANOTHER FILE WAS SAFE ONLY BY LUCK. `dedup-card-build-bug-draft-02-2026-09-09.md` is a bug
draft. It was kept off his board because its name happens to contain `dedup-card`, one of those
substrings. Nothing about it being a draft kept it out.

WHY THE NAME AND NOT THE CONTENT: the headers were measured. Real cards such as "Example Co —
resolution card, 2026-09-04" carry no `·` fields at all, exactly like the non-cards. Any content
rule that drops the memo also drops real, unresearched companies.

THE RULE: a card is `<slug>-card-<YYYY-MM-DD>.md`, with an optional `-render` variant. Words
between `-card-` and the date mean it is some other kind of document.
"""
import os
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import board  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402

SANDBOX = os.path.join(scratch_root(), "test-board-cards")
A_CARD = "# {name} — resolution card, 2026-09-04\n\nsome research\n"

REAL = {
    # ⛔ OBVIOUSLY FAKE NAMES, ON PURPOSE. partner-starter ships to other people, so a fixture
    # here must never carry a real company or a real person. The SHAPES are what is tested;
    # they match the real files exactly. Five thin, unresearched cards: the controls.
    "fake-alpha-card-2026-09-04.md": "Fake Alpha Co",
    "fake-bravo-card-2026-09-04.md": "Fake Bravo Co",
    "fake-charlie-consortium-card-2026-09-04.md": "Fake Charlie Consortium",
    "fake-delta-card-2026-09-04.md": "Fake Delta Co",
    "fake-echo-card-2026-09-05.md": "Fake Echo Co",
    # A render variant. In the owner's real data the render is the newest RULED card for its
    # company, so it must stay a card.
    "fake-foxtrot-card-2026-09-10-render.md": "Fake Foxtrot Co",
}
NOT_CARDS = {
    # The memo that reached his queue.
    "fake-plan-card-supply-2026-09-19.md": "A planning memo, re-cut",
    # ⛔ THE BROKEN WORLD: a bug draft WITHOUT the lucky `dedup-card` substring. The old
    # denylist would have let this one through. It must be refused because it is a draft.
    "boss-card-build-bug-draft-02-2026-09-09.md": "Boss-at-card-build bug draft",
    # Two kinds of document that share the card shape exactly, so they are named.
    "fake-person-call-card-2026-09-08.md": "Fake Person — call card",
    "panel-calibration-card-2026-09-08.md": "Panel calibration card",
}


class BoardKnowsWhatACardIs(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        state = os.path.join(SANDBOX, "documents", "state")
        os.makedirs(state)
        for name, title in list(REAL.items()) + list(NOT_CARDS.items()):
            with open(os.path.join(state, name), "w", encoding="utf-8") as fh:
                fh.write(A_CARD.format(name=title))
        self.cards = board.load_cards(SANDBOX)

    def tearDown(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)

    def test_every_real_card_is_still_a_card(self):
        """The control. A rule that refuses everything also refuses the memo."""
        for name in REAL:
            slug = board.card_slug(name)
            self.assertIn(slug, self.cards, "%s is a real card and was dropped" % name)

    def test_the_memo_is_not_a_card(self):
        self.assertNotIn("fake-plan", self.cards,
                         "a planning memo reached his decision queue as a card")

    def test_a_draft_is_refused_on_principle_not_by_luck(self):
        self.assertNotIn("boss", self.cards,
                         "a bug draft became a card. The old denylist caught drafts only when "
                         "their name happened to contain `dedup-card`.")

    def test_the_two_named_kinds_stay_out(self):
        self.assertNotIn("fake-person", self.cards, "a call card for a person became a card")
        self.assertNotIn("panel-calibration", self.cards, "a calibration doc became a card")

    def test_the_render_variant_is_the_card_it_came_from(self):
        self.assertIn("fake-foxtrot", self.cards)
        self.assertTrue(self.cards["fake-foxtrot"]["path"].endswith("-render.md"))


class TheVerdictScannerAgrees(unittest.TestCase):
    """⛔ THE SECOND COPY OF THE RULE. load_cards was fixed first and his board dropped to 101
    cards, but resolve_stages delegates to depth_report.scan_cards, which had its OWN glob and its
    OWN copy of NOT_A_CARD. It still gave the memo a stage, `carded_unruled`, so the memo went on
    counting as an unruled card in the card floor and in every queue count, after it had stopped
    being a card. A fix in one of two copies of a rule is a fix in neither.
    """

    def setUp(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        state = os.path.join(SANDBOX, "documents", "state")
        os.makedirs(state)
        for name, title in list(REAL.items()) + list(NOT_CARDS.items()):
            with open(os.path.join(state, name), "w", encoding="utf-8") as fh:
                fh.write(A_CARD.format(name=title))
        import depth_report
        self.stages, _owed, _skipped = depth_report.scan_cards(SANDBOX)
        self.cards = board.load_cards(SANDBOX)

    def tearDown(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)

    def test_the_scanner_saw_the_real_cards(self):
        """A control: a scanner that sees nothing also gives the memo no stage."""
        for name in REAL:
            self.assertIn(board.card_slug(name), self.stages)

    def test_the_memo_has_no_stage(self):
        self.assertNotIn("fake-plan", self.stages,
                         "the memo is no longer a card but still counts as an unruled one")

    def test_the_two_views_name_the_same_cards(self):
        self.assertEqual(sorted(self.cards), sorted(self.stages),
                         "the board and the verdict scanner disagree about what a card is")


class OneDefinitionAndNothingSilent(unittest.TestCase):
    """Two follow-ups from the verifier's pass on 0aa3552a."""

    def test_the_slug_comes_from_the_same_rule(self):
        """(b) card_slug and CARD_NAME_RE disagreed. `^(.*?)-card-` stops at the FIRST `-card-`,
        while the rule's slug group backtracks to the one before the date. For a name with
        `-card-` inside the slug they gave two different slugs for one file."""
        import depth_report
        name = "weird-card-y-card-2026-09-03.md"
        rule = depth_report.CARD_NAME_RE.match(name).group("slug")
        self.assertEqual("weird-card-y", rule, "the fixture no longer exercises the disagreement")
        self.assertEqual(rule, board.card_slug(name),
                         "card_slug and the card rule name the same file differently")

    def _scan(self, names):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        state = os.path.join(SANDBOX, "documents", "state")
        os.makedirs(state)
        for n in names:
            with open(os.path.join(state, n), "w", encoding="utf-8") as fh:
                fh.write(A_CARD.format(name="Fake Co"))
        self.addCleanup(shutil.rmtree, SANDBOX, True)
        import depth_report
        return depth_report.scan_cards(SANDBOX)

    def test_a_refused_file_is_recorded_with_its_reason(self):
        """(c) A refused file used to vanish. Now it is in `skipped`, with why."""
        _stages, _owed, skipped = self._scan(["fake-plan-card-supply-2026-09-19.md"])
        reasons = dict(skipped)
        self.assertIn("fake-plan-card-supply-2026-09-19.md", reasons,
                      "a file the card rule refused left no trace")
        self.assertTrue(reasons["fake-plan-card-supply-2026-09-19.md"],
                        "a refusal with no reason cannot be acted on")

    def test_a_card_with_the_wrong_case_is_visible_not_silent(self):
        """⛔ THE BROKEN WORLD: a real card someone named with a capital C. The glob is
        case-sensitive, so it never even reached the rule and vanished without a word."""
        _stages, _owed, skipped = self._scan(["Fake-Upper-Card-2026-09-04.md"])
        reasons = dict(skipped)
        self.assertIn("Fake-Upper-Card-2026-09-04.md", reasons,
                      "a card named with a capital C was dropped silently")
        self.assertIn("case", reasons["Fake-Upper-Card-2026-09-04.md"].lower())

    def test_real_cards_are_not_reported_as_skipped(self):
        """The control: a report that lists every card as skipped is noise and gets ignored."""
        stages, _owed, skipped = self._scan(["fake-alpha-card-2026-09-04.md"])
        self.assertIn("fake-alpha", stages)
        self.assertEqual([], skipped)


if __name__ == "__main__":
    unittest.main()
