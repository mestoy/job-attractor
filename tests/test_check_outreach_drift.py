"""BUG-008 (kit drift, closed 2026-09-12): check_outreach.py in the kit had fallen behind the
reference copy on MECHANISM, not just on wording. Each test below is one class of drift that a
partner would want, ported with its literal generalized through kit_config:

  * ingredient 3 accepts a plain stated want ("I'd like to be ...") and a stated desired state
    ("Being the first PM on your team sounds amazing / sounds like my kind of problem")
  * ingredient 5 accepts "N percent", a comma-grouped number ("75,000-plus"), a direct
    "work directly for you" offer, and the same desired-state sentence
  * RETIRED_PATTERNS match across a soft line wrap ("2 million\n  people use"), as the résumé
    gate already did, so the FIRST gate cannot be blind to what the LAST gate catches
  * the engineer-implication guardrail reads kit_config.ROLE_IMPLY_PATTERNS instead of a
    hard-coded tuple that named the kit author's own employers

RED before the port, GREEN after. Every widening keeps a control body that must still fail, so
the detector grows by one idiom, never by a hole. No owner literal appears in this file.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import check_outreach  # noqa: E402

SIG = "\n\n\nYour Name\nhttps://www.yoursite.example\n"

BASE = (
    "Happy Friday, Skylar! I really like your smart move of putting the coaching inside the tools "
    "people already open instead of shipping one more app.\n\n"
    "People copy what they see peers do, and it showed up across Patunay Verify's own launch notes. "
    "I designed an enablement program for a 160-person company from 11 interviews and 19 surveys.\n\n"
)


def _missing(body, n, rung="cold-boss"):
    fails, _warns = check_outreach.check_ingredients(body, rung)
    return any(f.startswith(f"ingredient {n} ") for f in fails)


def _run_main(body, *args):
    """Run main() in-process so a patched module global (RETIRED_PATTERNS, ROLE_IMPLY_PATTERNS)
    is the one the gate reads. Returns (exit code, stdout)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(body)
        path = fh.name
    out = io.StringIO()
    argv = sys.argv
    try:
        sys.argv = ["check_outreach.py", path, *args]
        with contextlib.redirect_stdout(out):
            try:
                check_outreach.main()
                rc = 0
            except SystemExit as e:
                rc = int(e.code or 0)
    finally:
        sys.argv = argv
        os.unlink(path)
    return rc, out.getvalue()


class Ingredient3Wants(unittest.TestCase):
    def test_i_would_like_to_be_is_a_want(self):
        self.assertFalse(_missing(BASE + "I'd like to be your first PM.\n\nThanks for naming it." + SIG, 3))

    def test_desired_state_sounds_amazing_is_a_want(self):
        self.assertFalse(_missing(BASE + "Being the first PM on your team sounds amazing.\n\nThanks." + SIG, 3))

    def test_desired_state_sounds_like_is_a_want(self):
        self.assertFalse(_missing(
            BASE + "Being the PM on your forms team sounds like my kind of problem.\n\nThanks." + SIG, 3))

    def test_no_want_still_fails(self):
        self.assertTrue(_missing(BASE + "Thanks for naming the plateau out loud." + SIG, 3))


class Ingredient5Offers(unittest.TestCase):
    OFFERLESS = (
        "Happy Wednesday, Pat! I like that you credited your team when you shipped an LLM into "
        "trades simulations. At my last employer I rewrote a rule that had drifted from reality.\n\n"
        "I'd like to be your next Director of Product.\n\n"
    )

    def test_percent_symbol_passes(self):
        self.assertFalse(_missing(self.OFFERLESS.replace("reality.", "reality, cutting handling time 22%.") + SIG, 5))

    def test_percent_word_passes(self):
        self.assertFalse(_missing(self.OFFERLESS.replace("reality.", "reality, cutting handling time 22 percent.") + SIG, 5))

    def test_comma_grouped_number_passes(self):
        self.assertFalse(_missing(self.OFFERLESS.replace("reality.", "reality for 75,000-plus vendors.") + SIG, 5))

    def test_work_directly_for_you_passes(self):
        body = self.OFFERLESS.replace("I'd like to be your next Director of Product.",
                                      "I'd love to work directly for you as your Senior PM.")
        self.assertFalse(_missing(body + SIG, 5))

    def test_desired_state_passes(self):
        body = self.OFFERLESS.replace("I'd like to be your next Director of Product.",
                                      "Being the first PM on your team sounds amazing.")
        self.assertFalse(_missing(body + SIG, 5))

    def test_no_offer_still_fails(self):
        self.assertTrue(_missing(self.OFFERLESS + SIG, 5))


class RetiredPatternsFlattenLineWraps(unittest.TestCase):
    def setUp(self):
        self._saved = check_outreach.RETIRED_PATTERNS
        # literal spaces on purpose: only the flattened body can match a claim wrapped across a line
        check_outreach.RETIRED_PATTERNS = [(r"2 million people use", '"2 million people use"')]
        self.addCleanup(lambda: setattr(check_outreach, "RETIRED_PATTERNS", self._saved))

    def test_wrapped_claim_is_caught(self):
        rc, out = _run_main("Hi, Sam!\n\nAbout 2 million\n  people use it today.\n", "--type", "reply")
        self.assertEqual(rc, 1, out)
        self.assertIn("retired/incorrect claim", out)

    def test_true_sentence_stays_clean(self):
        rc, out = _run_main("Hi, Sam!\n\nAbout 2 million residents are served by it.\n", "--type", "reply")
        self.assertNotIn("retired/incorrect claim", out)


class EngineerClaimsComeFromKitConfig(unittest.TestCase):
    def test_no_author_employer_literals_in_source(self):
        src = open(os.path.join(SCRIPTS, "check_outreach.py"), encoding="utf-8").read().lower()
        for leak in ("onpay", "rise8", "$35b"):
            self.assertNotIn(leak, src, f"kit author literal {leak!r} is baked into the kit script")

    def test_configured_employer_pattern_fires(self):
        saved = check_outreach.ROLE_IMPLY_PATTERNS
        check_outreach.ROLE_IMPLY_PATTERNS = [
            (r"\bi\s+built\b[^.]{0,40}?\bacme\b[^.]{0,25}\bapi\b", "claims authorship of Acme's API")]
        self.addCleanup(lambda: setattr(check_outreach, "ROLE_IMPLY_PATTERNS", saved))
        rc, out = _run_main("Hi, Sam!\n\nI built Acme's payments API last year.\n", "--type", "reply")
        self.assertEqual(rc, 1, out)
        self.assertIn("honesty guardrail: claims authorship of Acme's API", out)

    def test_generic_engineer_background_claim_still_fires(self):
        """The generic third pattern ships in kit_config; a body that says 'as an engineer' must
        still fail with the default config, so removing the hard-coded tuple did not weaken the gate."""
        rc, out = _run_main("Hi, Sam!\n\nAs an engineer I moved 24 systems onto one platform.\n", "--type", "reply")
        self.assertEqual(rc, 1, out)
        self.assertIn("honesty guardrail", out)


if __name__ == "__main__":
    unittest.main()
