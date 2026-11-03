"""BUG-569: depth_report (and the board that delegates to it) read a card's verdict token case-sensitively and knew nothing of HOLD and NEW, so a card saying
"drop" or "Radar" was read as unruled and then took the queue's BUILD. The rules, measured first on his real 101 cards and 144 queue headers:

 (a) a verdict word counts in ANY case where a verdict can stand: the first word-like token of the status text after marks and the qualifiers NEW or HOLD; and
     uppercase anywhere, as before. Lowercase prose later in a long status ("was built", "pass") is never read.
 (b) NEW and HOLD are recognized qualifiers, never verdicts and never a stage: "STATUS: NEW . RADAR" stays RADAR (four of his real queue rows), "STATUS: NEW" or
     "STATUS: HOLD" alone give no verdict (the card stays carded_unruled). They are COUNTED as the labels "new" and "held" next to the stages, nothing more. HOLD
     never maps to PARK (PARK is his decision).
 (c) the bare-field form accepts any case under the standing-alone rule; "remote pass" is still not a verdict; two different verdicts conflict in any case.
 (d) one shared reader for depth_report.card_stage, depth_report.queue_statuses and board.parse_header's status.
Fixtures are fictional companies in a temp repo.
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))

import depth_report as dr  # noqa: E402
import board  # noqa: E402


def hdr(status_text):
    return "# Fakeco · fictional · panel 70/70/70 mean 70 · STATUS: %s" % status_text


def card(status_text):
    return hdr(status_text) + "\n\nbody\n"


class StatusReading(unittest.TestCase):
    # ---- (a) any case where a verdict can stand --------------------------------------------------------------------------
    def test_a_lowercase_or_mixed_case_verdict_is_read(self):
        for text, want in (("drop", "DROP"), ("Radar", "RADAR"), ("🔴 dropped 2026-09-08", "DROP"), ("✓ Sent 2026-09-10", "SENT"),
                           ("○ park (decide later)", "PARK"), ("Build", "BUILD"), ("pass", "PASS")):
            with self.subTest(status=text):
                self.assertEqual(dr.card_stage(hdr(text)), want)

    def test_control_the_uppercase_forms_read_as_before(self):
        for text, want in (("🟡 RADAR (ruled)", "RADAR"), ("🔴 DROPPED 2026-09-08 filter 1", "DROP"), ("✅ SENT 2026-09-10", "SENT"), ("🟢 BUILD (ruled)", "BUILD")):
            with self.subTest(status=text):
                self.assertEqual(dr.card_stage(hdr(text)), want)

    def test_lowercase_prose_after_the_real_token_is_never_read(self):
        self.assertEqual(dr.card_stage(hdr("DROP (the build record says pass)")), "DROP")
        self.assertEqual(dr.card_stage(hdr("✓ SENT 2026-09-09 (sent twice; was a radar)")), "SENT")
        self.assertEqual(dr.card_stage(hdr("RADAR · note: pass on the first call")), "RADAR")

    def test_lowercase_prose_with_no_verdict_first_is_not_a_verdict(self):
        self.assertEqual(dr.card_stage(hdr("waiting for a build slot")), "carded_unruled")
        self.assertEqual(dr.card_stage(hdr("see the sent note")), "carded_unruled")

    # ---- R205: a NON-uppercase lead verdict counts only when it STANDS ALONE (end, a separator, "(", a mark or a date), never before "?" or a word ---------
    def test_a_lowercase_lead_word_that_starts_a_sentence_is_prose_not_a_verdict(self):
        for text in ("sent? not yet", "drop me a line if needed", "build out a demo first", "Pass rate checked, see note", "radar plus a live req",
                     "park the idea until Q3"):
            with self.subTest(status=text):
                self.assertEqual(dr.card_stage(hdr(text)), "carded_unruled")
                self.assertEqual(dr.read_status(text)[0], None)

    def test_after_a_hold_qualifier_a_lowercase_verdict_is_prose(self):
        self.assertEqual(dr.read_status("HOLD · park later"), (None, {"held"}))
        self.assertEqual(dr.card_stage(hdr("HOLD · park later")), "carded_unruled")
        self.assertEqual(dr.read_status("HOLD · PARK"), ("PARK", {"held"}))                     # an uppercase verdict after HOLD still reads

    def test_a_lowercase_verdict_that_stands_alone_still_reads(self):
        for text, want in (("drop", "DROP"), ("park (decide later)", "PARK"), ("dropped 2026-09-08", "DROP"), ("radar · segment: fintech", "RADAR"),
                           ("sent — twice", "SENT"), ("build: ruled", "BUILD"), ("pass ✗", "PASS"), ("Radar", "RADAR"), ("sent ✓", "SENT")):
            with self.subTest(status=text):
                self.assertEqual(dr.read_status(text)[0], want)

    def test_uppercase_lead_words_read_whatever_follows(self):
        for text, want in (("DROP me a line if needed", "DROP"), ("SENT? not yet", "SENT"), ("BUILD out a demo first", "BUILD")):
            with self.subTest(status=text):
                self.assertEqual(dr.read_status(text)[0], want)

    # ---- (b) NEW and HOLD are qualifiers, never stages ------------------------------------------------------------------------
    def test_new_before_a_verdict_keeps_the_verdict(self):
        self.assertEqual(dr.card_stage(hdr("NEW · ○ RADAR (batch df-19)")), "RADAR")
        self.assertEqual(dr.card_stage(hdr("New - radar")), "RADAR")
        self.assertEqual(dr.card_stage(hdr("HOLD · PARK")), "PARK")

    def test_new_or_hold_alone_is_no_verdict_and_never_a_stage(self):
        for text in ("NEW", "new", "HOLD", "hold", "● HOLD (waiting on the boss)"):
            with self.subTest(status=text):
                self.assertEqual(dr.card_stage(hdr(text)), "carded_unruled")

    def test_the_labels_new_and_held_are_counted_not_staged(self):
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo, True)
        state = os.path.join(repo, "documents", "state")
        os.makedirs(state)
        for name, status in (("aaa-card-2026-09-01.md", "NEW"), ("bbb-card-2026-09-01.md", "hold"), ("ccc-card-2026-09-01.md", "NEW · RADAR"),
                             ("ddd-card-2026-09-01.md", "🟢 BUILD")):
            with open(os.path.join(state, name), "w", encoding="utf-8") as fh:
                fh.write(card(status))
        stages, _owed, _skipped = dr.scan_cards(repo)
        self.assertEqual(stages, {"aaa": "carded_unruled", "bbb": "carded_unruled", "ccc": "RADAR", "ddd": "BUILD"})
        labels = dr.scan_labels(repo)
        self.assertEqual(labels, {"aaa": {"new"}, "bbb": {"held"}, "ccc": {"new"}})        # a verdict stays, and the card is also labeled new
        c = dr.counts(stages, labels)
        self.assertEqual((c["new"], c["held"]), (2, 1))
        self.assertEqual(c["carded_unruled"], 2)                                         # unchanged: labels never change a stage
        self.assertNotIn("new", dr.STAGE_TOKENS)
        self.assertNotIn("PARK", [s for s, v in stages.items() if s == "bbb"])        # HOLD never became PARK

    # ---- (c) the bare field, qualifiers and conflicts ----------------------------------------------------------------------------
    def test_a_bare_field_verdict_still_only_feeds_the_conflict_check_in_any_case(self):
        # Unchanged by design: a single bare-field verdict does not stage the card (the queue fills it; 45 of his real cards are written this way), so the any-case
        # change must not move them. It still counts toward a conflict, and a qualified field ("remote pass") is still not a verdict.
        for line in ("# Fakeco · fictional · RADAR · panel 70/70/70 · boss X", "# Fakeco · fictional · radar · panel 70/70/70 · boss X",
                     "# Fakeco · fictional · Park · mean 60", "# Fakeco · fictional · remote pass · mean 60", "# Fakeco · fictional · remote PASS · mean 60"):
            with self.subTest(line=line):
                self.assertEqual(dr.card_stage(line), "carded_unruled")

    def test_two_different_verdicts_conflict_in_any_case(self):
        self.assertEqual(dr.card_stage("# Fakeco · fictional · RADAR · x · park ·"), "verdict_conflict")
        self.assertEqual(dr.card_stage("# Fakeco · fictional · radar · x · PARK ·"), "verdict_conflict")

    # ---- the queue reads the same text the same way -----------------------------------------------------------------------------
    def test_the_queue_header_is_read_with_the_same_rules(self):
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo, True)
        os.makedirs(os.path.join(repo, "documents", "state"))
        q = ("## 1 · Fakeco One (fictional) · STATUS: drop\n\n"
             "## 2 · Fakeco Two (fictional) · STATUS: NEW · ○ RADAR (re-verified)\n\n"
             "## 3 · Fakeco Three (fictional) · STATUS: NEW\n\n"
             "## 4 · Fakeco Four (fictional) · STATUS: hold\n\n"
             "## 5 · Fakeco Five (fictional) · STATUS: NEW · note: radar later\n\n"
             "## 6 · Fakeco Six (fictional) · STATUS: DROP (the build record says pass)\n\n")
        with open(os.path.join(repo, "documents", "outreach-queue.md"), "w", encoding="utf-8") as fh:
            fh.write(q)
        got = dr.queue_statuses(repo)
        self.assertEqual(got, {"fakeco-one": "DROP", "fakeco-two": "RADAR", "fakeco-six": "DROP"})

    def test_a_card_that_says_drop_no_longer_takes_the_queues_build(self):
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo, True)
        state = os.path.join(repo, "documents", "state")
        os.makedirs(state)
        with open(os.path.join(state, "fakeco-card-2026-09-01.md"), "w", encoding="utf-8") as fh:
            fh.write(card("drop"))
        with open(os.path.join(repo, "documents", "outreach-queue.md"), "w", encoding="utf-8") as fh:
            fh.write("## 1 · Fakeco (fictional) · STATUS: BUILD\n")
        stages, disagree, basis = dr.resolve(repo)
        self.assertEqual(stages["fakeco"], "DROP")
        self.assertEqual(basis["fakeco"]["source"], "card")
        self.assertEqual([d[0] for d in disagree], ["fakeco"])                               # the queue says BUILD: reported, never applied

    # ---- (d) the board reads the status field with the same reader ----------------------------------------------------------------
    def test_the_boards_header_status_is_found_in_any_case_of_the_key(self):
        self.assertEqual(board.parse_header("# Fakeco · fictional · status: drop")["status"], "drop")
        self.assertEqual(board.parse_header("# Fakeco · fictional · Status: Radar")["status"], "Radar")
        self.assertEqual(board.parse_header("# Fakeco · fictional · STATUS: 🟡 RADAR")["status"], "🟡 RADAR")

    def test_there_is_one_shared_reader(self):
        self.assertTrue(callable(getattr(dr, "read_status", None)))
        verdict, quals = dr.read_status("NEW · ○ radar")
        self.assertEqual((verdict, quals), ("RADAR", {"new"}))
        self.assertEqual(dr.read_status("hold"), (None, {"held"}))
        self.assertEqual(dr.read_status("DROPPED 2026"), ("DROP", set()))

    # ---- his real shapes, as fake files ---------------------------------------------------------------------------------------------
    def test_the_real_data_shapes_change_no_stage(self):
        """From the measurement on his real cards and queue: eleven card headers with a lowercase word LATER in the status (build, pass, sent, New), four queue rows
        'NEW . RADAR', seven plain 'NEW' rows. Read with the new rules, no stage moves and the four radars stay radars."""
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo, True)
        state = os.path.join(repo, "documents", "state")
        os.makedirs(state)
        shapes = [("DROP", "DROP, DROP, DROP, build, PARK, DROP"), ("PARK", "PARK, PARK, PARK, build, RADAR"), ("SENT", "SENT, pass, PASS"),
                  ("SENT", "SENT, SENT, BUILD, build, BUILD, PASS"), ("SENT", "SENT, SENT, sent, RADAR"), ("DROP", "DROP, New"),
                  ("RADAR", "RADAR, RADAR, RADAR, pass"), ("PARK", "PARK, PARK, PARK, build, RADAR, PASS")]
        want = {}
        for i, (stage, status) in enumerate(shapes):
            slug = "shape%d" % i
            with open(os.path.join(state, "%s-card-2026-09-01.md" % slug), "w", encoding="utf-8") as fh:
                fh.write(card(status))
            want[slug] = stage
        stages, _o, _s = dr.scan_cards(repo)
        self.assertEqual(stages, want)
        q = "".join("## %d · Fakeco R%d (fictional) · STATUS: NEW · ○ RADAR (a live req)\n\n" % (i, i) for i in range(4))
        q += "".join("## %d · Fakeco N%d (fictional) · STATUS: NEW\n\n" % (i + 10, i) for i in range(7))
        with open(os.path.join(repo, "documents", "outreach-queue.md"), "w", encoding="utf-8") as fh:
            fh.write(q)
        got = dr.queue_statuses(repo)
        self.assertEqual(sorted(got.values()), ["RADAR"] * 4)                              # the four stay radars; the seven NEW rows give no stage


if __name__ == "__main__":
    unittest.main()
