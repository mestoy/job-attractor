#!/usr/bin/env python3
"""BUG-135: the remote veto in rank_criteria._score_fields must read the VERDICT, not topic words.

The recorded remote field is PROSE the screener wrote. A clean seat is often proven by NAMING the
disqualifiers it lacks ("No hybrid, RTO, or relocation clause"), so a bare keyword scan vetoes exactly
the confirmations. Measured live on MinIO: three clean recordings each vetoed, the seat verified
Remote-US on the company's own Greenhouse all three times. The veto is silent (banked_topup falls
through to the unscreened default), so a screened SURVIVOR reappears as work still owed.

RED before the fix (the ✅-marked clean prose is vetoed on the word 'hybrid'); GREEN after (the ✅/🔴
verdict marker decides, with a negation-aware fallback when no marker is present)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import rank_criteria


def _remote_veto(remote_field):
    """Return the veto reason if _score_fields vetoes on remote, else None. Other fields are benign
    so only veto 1 (remote) can fire."""
    score, reason = rank_criteria._score_fields(
        "Acme", "payments", remote_field, "", "✅ VC-backed, not PE", "boss (src)", "praise")
    if score is None and "remote" in reason.lower():
        return reason
    return None


class RemoteGateNegationAware(unittest.TestCase):
    def test_clean_prose_that_names_the_disqualifiers_is_not_vetoed(self):
        # the three live MinIO recordings, each verified Remote-US on Greenhouse
        for clean in [
            "✅ No hybrid, RTO, metro-lock or travel clause in the posting",
            "✅ carries no office-attendance, relocation, metro-restriction or travel clause",
            "✅ VERIFIED own Greenhouse: 6 of 7 reqs `Remote - USA`",
        ]:
            self.assertIsNone(_remote_veto(clean),
                              "a ✅-marked clean remote confirmation must not be vetoed on the "
                              "disqualifier words it names: %r" % clean)

    def test_a_red_marked_field_still_vetoes(self):
        self.assertIsNotNone(_remote_veto("🔴 hybrid, 3 days a week in office required"),
                             "a 🔴-marked disqualifying arrangement must still veto")

    def test_unmarked_disqualifier_without_offset_still_vetoes(self):
        # no verdict marker at all → strict scan; a bare disqualifier vetoes
        self.assertIsNotNone(_remote_veto("relocation to Austin required within 6 months"),
                             "an unmarked disqualifying arrangement must still veto")

    def test_unmarked_confirm_phrase_does_not_offset_a_real_disqualifier(self):
        # panel A2 / no-regression: an UNMARKED field where a confirm phrase co-occurs with a real
        # disqualifier must STILL veto. The old bare scan vetoed this; a confirm-offset would
        # false-pass a genuinely non-remote seat, which is worse than the over-veto BUG-135 fixed.
        self.assertIsNotNone(
            _remote_veto("remote-first culture but the role requires relocation to NYC"),
            "an unmarked confirm phrase must not launder a co-occurring hard disqualifier past the veto")

    def test_red_marker_wins_over_check_mark(self):
        # a stated disqualification dominates a ✅ elsewhere in the field (fail-safe)
        self.assertIsNotNone(_remote_veto("✅ great comp, 🔴 hybrid 3 days in office required"),
                             "a 🔴 must veto even when a ✅ is also present")

    def test_unconfirmed_empty_remote_still_vetoes(self):
        self.assertIsNotNone(_remote_veto(""), "an empty/unconfirmed remote field is not a pass")


if __name__ == "__main__":
    unittest.main()
