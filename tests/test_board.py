"""The Board (2026-09-10): one page over the cards, the send log and the passive sampler.

The load-bearing claim under test is the honest-gate rule: a gate with no section on the card
reads UNRESOLVED, never PASS, because silence is not clearance. Fixtures are fictional companies
in a temp repo; no live store is read or written.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import board  # noqa: E402

FULL_CARD = """# Widgetronics · regulated-workflow (fictional) · panel 80/74/78 mean 77.3 · STATUS: 🟡 RADAR (ruled) · boss Casey Doherty (Chief Product Officer) · remote PASS · 2026-09-09

## 0. Dedup check
check_dup.py: 🟢 NEW, safe to screen.

## 1. Blocked list / hard filters
CLEAN.

## 2. Industry news & layoffs (12 mo)
None found. PASS.

## 3. Culture
Glassdoor unavailable, read owed

## 4. Leadership and retention
No churn signal. PASS.

## 5. Remote reality
Their own words: fully remote. PASS.

## 6. Ownership
Venture seed, no PE. PASS.

## 7. Boss
Casey Doherty, CPO — CONFIRMED via two independent primary sources.

## 8. Product team
4 named. FOUND.

## 9. Live PM req
None listed.

## Gate still owed
- LinkedIn People tab for a product leader https://example.invalid/people
"""

# Same company shape, but four gate sections simply absent — the silence case.
THIN_CARD = """# Sprocketly · fictional · panel 70/68/72 mean 70 · boss not yet named · 2026-09-08

## 1. Blocked list / hard filters
CLEAN.

## 3. Culture
Too thin to screen, UNPROVEN.
"""

RULED_CARD = """# Gearhouse · fictional · panel 60/60/60 mean 60 · STATUS: 🔴 DROPPED filter 1 (remote) · 2026-09-08

## 1. Blocked list / hard filters
FAIL — remote hard fail.
"""


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        st = os.path.join(self.repo, "documents", "state")
        os.makedirs(os.path.join(st, "scorecards"))
        for name, text in (("widgetronics-card-2026-09-09.md", FULL_CARD),
                           ("sprocketly-card-2026-09-08.md", THIN_CARD),
                           ("gearhouse-card-2026-09-08.md", RULED_CARD)):
            with open(os.path.join(st, name), "w", encoding="utf-8") as f:
                f.write(text)
        with open(os.path.join(self.repo, "documents", "send-log.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"date": "2026-09-10", "company": "A", "replied": True}) + "\n")
            f.write(json.dumps({"date": "2026-09-10", "company": "B", "replied": False,
                                "from_address": "someone@example.com",
                                "sender_experiment": "baseline closed at 1 sent, 1 replied"}) + "\n")
        with open(os.path.join(st, "mac-time-summary.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"date": "2026-09-10",
                                "minutes": {"find": 5, "screen": 40, "card_and_rule": 10,
                                            "build_and_send": 3, "other": 2},
                                "gap_minutes": 7, "samples": 60}) + "\n")
        with open(os.path.join(st, "scorecards", "INDEX.md"), "w", encoding="utf-8") as f:
            f.write("| Widgetronics | https://claude.ai/code/artifact/"
                    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee | widgetronics-2026-09-09.html |\n")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    # ── the honest-gate rule ──────────────────────────────────────────────────────────────
    def test_absent_gate_section_is_unresolved_never_pass(self):
        states = dict((k, s) for k, _l, s in board.gates_for(THIN_CARD))
        self.assertEqual(states["news"], "none")
        self.assertEqual(states["ownership"], "none")
        self.assertEqual(states["boss"], "none")
        self.assertEqual(states["live_req"], "none")
        self.assertEqual(board.LABEL["none"], "UNRESOLVED")
        self.assertNotEqual(board.LABEL["none"], "PASS")

    def test_gate_states_read_from_the_prose(self):
        states = dict((k, s) for k, _l, s in board.gates_for(FULL_CARD))
        self.assertEqual(states["blocked"], "good")
        self.assertEqual(states["culture"], "owed")     # "read owed" beats any passing word
        self.assertEqual(states["boss"], "good")
        self.assertEqual(states["dedup"], "good")

    def test_a_failing_word_beats_a_passing_one_in_the_same_section(self):
        self.assertEqual(board.gate_state("CLEAN overall but remote is a hard FAIL"), "bad")

    def test_all_ten_gates_are_reported_in_standing_order(self):
        gates = board.gates_for(THIN_CARD)
        self.assertEqual(len(gates), 10)
        self.assertEqual(gates[0][0], "dedup")
        self.assertEqual([g[0] for g in gates][-1], "live_req")

    # ── header parsing ────────────────────────────────────────────────────────────────────
    def test_header_fields(self):
        h = board.parse_header(FULL_CARD.splitlines()[0])
        self.assertEqual(h["company"], "Widgetronics")
        self.assertEqual(h["seats"], (80, 74, 78))
        self.assertEqual(h["mean"], 77.3)
        self.assertEqual(h["remote"], "PASS")
        self.assertIn("Casey Doherty", h["boss"])
        self.assertEqual(h["date"], "2026-09-09")

    def test_mean_is_derived_when_only_seats_are_given(self):
        h = board.parse_header("# X · panel 80/70/75 · STATUS: RADAR")
        self.assertEqual(h["mean"], 75.0)

    def test_boss_confidence_grades_the_boss_gate(self):
        self.assertEqual(board.boss_confidence(FULL_CARD), "two-source")
        self.assertEqual(board.boss_confidence(THIN_CARD), "no boss gate")

    # ── the batch ─────────────────────────────────────────────────────────────────────────
    def test_the_page_opens_on_the_next_action_not_on_state(self):
        """His ruling 2026-09-10: when he opens it, it must be obvious what to do. The active
        step leads; the floors and the ladder are demoted behind a disclosure."""
        out = board.render(self.repo, "2026-09-10")
        self.assertIn("<h1>What to do now</h1>", out)
        self.assertIn("<h2>Rule 1 card</h2>", out)
        self.assertLess(out.index('id="now"'), out.index("Where the pipeline stands"))
        self.assertIn("Sprocketly", out)        # scored, no STATUS token
        self.assertNotIn(">Gearhouse<", out)    # already ruled DROP

    def test_highest_mean_leads_inside_a_step(self):
        """His ruling 2026-09-10: value leads, age breaks ties. Oldest-first was surfacing
        near-certain PARKs above the only card that needed a decision."""
        st = os.path.join(self.repo, "documents", "state")
        with open(os.path.join(st, "topscore-card-2026-09-01.md"), "w", encoding="utf-8") as f:
            f.write("# Topscore \u00b7 fictional \u00b7 panel 90/90/90 mean 90\n\n## 3. Culture\nUNPROVEN.\n")
        out = board.render(self.repo, "2026-09-10")
        self.assertLess(out.index("Topscore"), out.index("Sprocketly"))  # 90.0 before 70.0
        self.assertIn("Highest panel mean first", out)

    def test_the_path_shows_position_and_ends_at_the_mission(self):
        out = board.render(self.repo, "2026-09-10")
        self.assertEqual(out.count('class="step'), 6)
        self.assertIn('class="step here"', out)
        self.assertIn("2 offers", out)
        self.assertIn("by Dec 31", out)
        self.assertIn('class="step seat"', out)   # seat work shown, greyed, not assigned to him

    def test_priority_is_nearest_an_offer_first(self):
        """Send outranks build outranks rule. A staged note today wins even when cards wait."""
        cards = board.load_cards(self.repo)
        ruled, _ = board.resolve_stages(self.repo)
        batch = [c for s, c in cards.items()
                 if ruled.get(s) == "carded_unruled" and c["head"]["mean"] is not None]
        self.assertEqual(board.next_action(cards, ruled, batch, self.repo, "2026-09-10")[0], "rule")
        p = os.path.join(self.repo, "documents", "send-log.jsonl")
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"status": "drafted", "date": "2026-09-10",
                                "company": "Widgetronics", "to": "x@y.invalid"}) + "\n")
        self.assertEqual(board.next_action(cards, ruled, batch, self.repo, "2026-09-10")[0], "send")

    def test_stale_drafts_are_hygiene_never_a_next_action(self):
        """Seven rows on the real install date to July and one names a company already sent."""
        p = os.path.join(self.repo, "documents", "send-log.jsonl")
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"status": "drafted", "date": "2026-07-29",
                                "company": "Old Co", "to": "z@y.invalid"}) + "\n")
        cards = board.load_cards(self.repo)
        ruled, _ = board.resolve_stages(self.repo)
        batch = [c for s, c in cards.items()
                 if ruled.get(s) == "carded_unruled" and c["head"]["mean"] is not None]
        key, payload = board.next_action(cards, ruled, batch, self.repo, "2026-09-10")
        self.assertEqual(key, "rule")                    # the old draft is not the next action
        self.assertEqual(len(payload["stale"]), 1)
        out = board.render(self.repo, "2026-09-10")
        self.assertIn("still marked drafted in the send log", out)

    def test_guided_hides_passing_gates_diy_shows_all(self):
        guided = board.render(self.repo, "2026-09-10", level="guided")
        diy = board.render(self.repo, "2026-09-10", level="diy")
        self.assertIn("more passing", guided)
        self.assertNotIn("more passing", diy)

    def test_ladder_counts_sends_that_reached_a_person_not_rows(self):
        """The material defect e4 caught: a raw row count includes drafted, discarded and bounced
        rows, understating the reply rate and hiding the bounces."""
        p = os.path.join(self.repo, "documents", "send-log.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for st, rep in (("sent", True), ("sent", False), ("replied", True),
                            ("bounced", False), ("bounced", False),
                            ("drafted", False), ("discarded", False), ("submitted", False)):
                f.write(json.dumps({"status": st, "replied": rep}) + "\n")
        lad = board.ladder(self.repo)
        self.assertEqual(lad["reached"], 3)      # 2 sent + 1 replied, never the other 5 rows
        self.assertEqual(lad["replied"], 2)
        self.assertEqual(lad["bounced"], 2)
        self.assertEqual(lad["excluded"], 5)
        out = board.render(self.repo, "2026-09-10")
        self.assertIn("66.7%", out)              # 2 of 3, not 2 of 8
        self.assertIn("2 bounced", out)

    def test_an_inbound_reply_row_is_not_a_send(self):
        """The one inbound row on file carries status "replied", which is in REACHED, so it rode
        the denominator from 2026-07-21 and inflated every ladder figure by one. Direction settles
        what a row is, not status."""
        p = os.path.join(self.repo, "documents", "send-log.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"status": "sent", "replied": True}) + "\n")
            f.write(json.dumps({"status": "sent", "replied": False}) + "\n")
            f.write(json.dumps({"direction": "inbound", "status": "replied",
                                "company": "Fictional Co", "rung": "warm"}) + "\n")
        lad = board.ladder(self.repo)
        self.assertEqual(lad["reached"], 2)          # not 3; the inbound row is not a send
        self.assertEqual(lad["replied"], 1)
        self.assertNotIn("replied", lad["by_status"])  # kept out of the send census entirely

    def test_an_outbound_row_marked_replied_still_counts(self):
        """The guard on the fix above: only DIRECTION excludes a row. An outbound row that ended
        in a reply is still a send and still belongs in the denominator."""
        p = os.path.join(self.repo, "documents", "send-log.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"status": "replied", "replied": True}) + "\n")
        lad = board.ladder(self.repo)
        self.assertEqual(lad["reached"], 1)
        self.assertEqual(lad["replied"], 1)

    def test_domain_split_and_baseline_note(self):
        lad = board.ladder(self.repo)
        self.assertEqual(lad["by_domain"], {})   # fixture rows carry no status, so none reached
        p = os.path.join(self.repo, "documents", "send-log.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"status": "sent", "replied": False,
                                "from_address": "someone@example.com",
                                "sender_experiment": "baseline closed at 1 sent, 1 replied"}) + "\n")
        lad = board.ladder(self.repo)
        self.assertEqual(lad["by_domain"]["example.com"], [1, 0])
        self.assertIn("baseline closed", lad["note"])

    def test_owed_read_text_is_cleaned_not_chopped(self):
        self.assertEqual(board.clean("**Bold** and `code` here"), "Bold and code here")
        self.assertEqual(board.clean("[label](https://x.invalid) tail"), "label tail")
        out = board.clean("word " * 60, limit=40)
        self.assertTrue(out.endswith("…"))
        self.assertFalse(out.rstrip("…").endswith(" "))
        self.assertNotIn("**", board.render(self.repo, "2026-09-10"))

    def test_unfilled_owner_name_is_omitted_not_printed(self):
        out = board.render(self.repo, "2026-09-10")
        self.assertNotIn("for Your ", out)
        self.assertIn("Generated by scripts/board.py", out)

    def test_hand_time_present_and_absent(self):
        self.assertEqual(board.hand_time(self.repo, "2026-09-10")["minutes"]["screen"], 40)
        self.assertIsNone(board.hand_time(self.repo, "2026-09-11"))
        self.assertIn("no samples yet", board.render(self.repo, "2026-09-11"))

    def test_owed_reads_listed_once_with_their_url(self):
        out = board.render(self.repo, "2026-09-10")
        self.assertEqual(out.count("LinkedIn People tab for a product leader"), 1)
        self.assertIn("https://example.invalid/people", out)

    def test_scorecard_link_used_when_published(self):
        self.assertEqual(board.scorecard_links(self.repo)["widgetronics"],
                         "https://claude.ai/code/artifact/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    # ── page shape ────────────────────────────────────────────────────────────────────────
    def test_page_carries_charset_and_the_canonical_palette(self):
        out = board.render(self.repo, "2026-09-10")
        self.assertTrue(out.lstrip().startswith('<meta charset="utf-8">'))
        self.assertIn("<title>Job Attractor Board</title>", out)

    def test_page_never_offers_a_write_path(self):
        """v1 is read-and-decide: no form, no button, no fetch."""
        out = board.render(self.repo, "2026-09-10").lower()
        for forbidden in ("<form", "<button", "fetch(", "xmlhttprequest", "localstorage"):
            self.assertNotIn(forbidden, out, forbidden)

    def test_writes_the_file(self):
        out = os.path.join(self.repo, "documents", "state", "board.html")
        board.main(["--repo", self.repo, "--date", "2026-09-10"])
        self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
