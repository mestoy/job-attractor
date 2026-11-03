"""kit#120: mail-draft.sh's SEGMENT gate is the one script in the pipeline that never adopted
"off-segment", the closed-vocabulary escape valve every OTHER segment-vocabulary consumer
already treats as always available:

  - contact_signals.py: `_VALID_SEGMENTS = set(kit_config.SEGMENT_SLUGS) | {"off-segment"}`
  - record_finding.py's lanes(): `found.add("off-segment")  # always available`
  - balancer.py already reports an "untagged/off-segment" share, excluded from the per-segment
    reply-rate comparison the SEGMENT gate exists to protect

So this is a step-0 finding, not the design question it first looked like: the issue's own
"suggested direction #1" (an escape-valve slug, excluded from the comparison) was ALREADY BUILT
and adopted everywhere except the one gate a partner actually hit it at. This closes that one gap;
it does not touch the closed vocabulary itself, which stays an install-level choice.

Tests run the REAL bash text, extracted by anchor (same technique test_kit_push_guard.py uses
for backup.sh's kit-push block), not a Python re-implementation of the gate's logic.
"""
import os
import re
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
MAIL_DRAFT_SH = os.path.join(KIT, "scripts", "mail-draft.sh")


def segment_gate_block():
    """The SEGMENT gate's own if-block, taken verbatim from mail-draft.sh between its comment
    and the `fi` that closes it."""
    text = open(MAIL_DRAFT_SH, encoding="utf-8").read()
    m = re.search(r'(  # SEGMENT gate:.*?\n  fi\n)', text, re.S)
    if not m:
        raise AssertionError("could not find the SEGMENT gate block in mail-draft.sh")
    return m.group(1)


def run_gate(segment, slugs, warm_rung="", post_contact=""):
    script = "set -u\n" + segment_gate_block()
    env = dict(os.environ, SEGMENT=segment, KIT_SEGMENT_SLUGS=slugs,
              WARM_RUNG=warm_rung, POST_CONTACT=post_contact)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)


class TestSegmentGateAcceptsOffSegment(unittest.TestCase):
    def test_a_declared_slug_still_passes(self):
        """Unaffected baseline: an install's own configured slug still works."""
        r = run_gate("product-owner-healthcare", "product-owner-healthcare")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_an_undeclared_free_text_label_is_still_refused(self):
        """Control: the fix must not become a free-text bypass. A lane from a discovery sweep
        ("fintech-b2b-something") is still not a segment."""
        r = run_gate("fintech-b2b-something", "product-owner-healthcare")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not one of your defined segments", r.stderr)

    def test_off_segment_is_accepted_even_when_not_in_the_configured_slugs(self):
        """kit#120. A genuinely-authorized target outside every one of an install's closed
        lanes (fictional stand-ins for the report's real examples: Fakebank Retirement Group,
        Fictional Ads LLC, a telecom-registry subsidiary, an insurance product-manager role
        titled outside the one close slug, and an AI research company — none healthcare/
        regulated/Dynamics) has no honest --segment today except a value the gate refuses on
        principle. off-segment is already the kit-wide answer to exactly this everywhere else
        the vocabulary is checked."""
        r = run_gate("off-segment", "product-owner-healthcare senior-business-analyst-regulated")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_warm_sends_are_unaffected_and_still_skip_the_gate_entirely(self):
        r = run_gate("", "product-owner-healthcare", warm_rung="1")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
