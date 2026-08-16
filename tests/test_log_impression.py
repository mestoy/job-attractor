#!/usr/bin/env python3
"""Tests for scripts/log_impression.py — the TARGET-IMPRESSION logger (the BUG-185 fix).

Built 2026-08-14 (Fable's Phase-2 design, Opus build). The hook runs in the PostToolUse/
AskUserQuestion chain AFTER record_decision.py and records, systematically, BOTH what the ranker
SURFACED (the picker's options) and what the user DID (his answer). That is the raw material Phase 3's
verdict miner turns into accepted / rejected / passed-over labels — captured every time, not only when
the assistant remembers (which was BUG-185).

WHAT THESE PIN:
  1. The pair picker (NEXT-STEP marker) and target-shaped pickers are logged; ordinary pickers are not.
  2. The TARGET SHAPE is read from label AND description (the pair picker carries it in description).
  3. The passed-over signal is DERIVABLE (surfaced-top parsed, chosen index recorded) — facts, not verdicts.
  4. FAIL-OPEN: a malformed payload never writes and never blocks (exit 0 always).
  5. GENERIC: the mechanism records whatever a non-owner payload carries.
  6. The settings wiring places this hook AFTER record_decision.py.

Payloads are synthetic and piped through the sandbox hook runner; nothing here touches live state.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import SandboxTest, LIVE_REPO  # noqa: E402

STORE = "documents/state/target-impressions.jsonl"


def _payload(questions, answers, session="sess-1"):
    return {"session_id": session,
            "tool_input": {"questions": questions},
            "tool_response": {"answers": answers}}


def _pair_question(answer_label):
    # The real pair picker: NEXT-STEP marker in the question; the target lives in option 1's
    # DESCRIPTION, not its label (this is the shape the logger must handle).
    q = {"question": "NEXT-STEP · what now? LADDER 2026-08-14 · sent 417 · replied 66 · rate 15.8%",
         "header": "Next move",
         "options": [
             {"label": "Start the next loop (Andy's)",
              "description": "🧭 next initial contact: Dana Rivera · Global Director, "
                             "Development @ 350.org · rung cold-stranger (1-2). Source: rank_people."},
             {"label": "Phase 2 of the ranker",
              "description": "🐞 the impression-logger hook."},
             {"label": "Stop for the day", "description": "🟢 your call."}]}
    return _payload([q], {q["question"]: answer_label})


class ImpressionLoggerTests(SandboxTest):
    SANDBOX_NAME = "impressions"

    def setUp(self):
        # Start from an empty store so count-asserting tests are deterministic in the shared sandbox.
        p = self.sb.path(STORE)
        if os.path.exists(p):
            os.unlink(p)

    def _rows(self):
        return [json.loads(l) for l in self.sb.lines(STORE)]

    # 1 ─────────────────────────────────────────────────────────────────────────────────────────
    def test_pair_picker_writes_one_row(self):
        r = self.sb.hook("log_impression.py", _pair_question("Phase 2 of the ranker"))
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "target-impression")
        self.assertEqual(rows[0]["trigger"], "pair-marker")
        self.assertEqual(rows[0]["header"], "Next move")

    # 2 ─────────────────────────────────────────────────────────────────────────────────────────
    def test_surfaced_top_and_chosen_captured(self):
        self.sb.hook("log_impression.py", _pair_question("Phase 2 of the ranker"))
        row = self._rows()[0]
        # option 1's target parsed from its DESCRIPTION
        self.assertEqual(row["surfaced_top"]["name"], "Dana Rivera")
        self.assertEqual(row["surfaced_top"]["company"], "350.org")
        self.assertTrue(row["options"][0]["is_default"])
        self.assertEqual(row["options"][0]["target"]["name"], "Dana Rivera")
        # the user chose option 2, not the surfaced default
        self.assertEqual(row["chosen"]["idx"], 2)
        self.assertFalse(row["chosen"]["off_list"])

    # 3 ─────────────────────────────────────────────────────────────────────────────────────────
    def test_option_number_answer_resolves(self):
        # Answer arrives as "#1" — resolve_option_answer maps it to option 1's label.
        self.sb.hook("log_impression.py", _pair_question("#1"))
        row = self._rows()[0]
        self.assertEqual(row["chosen"]["idx"], 1)
        self.assertEqual(row["chosen"]["resolved"], "Start the next loop (Andy's)")

    # 4 ─────────────────────────────────────────────────────────────────────────────────────────
    def test_passed_over_encoding(self):
        # Everything Phase 3 needs to derive passed-over(Edmonson): the surfaced target sits on an
        # un-chosen option, and chosen.idx points elsewhere. No verdict field is asserted here.
        self.sb.hook("log_impression.py", _pair_question("Phase 2 of the ranker"))
        row = self._rows()[0]
        surfaced = row["options"][0]["target"]
        self.assertIsNotNone(surfaced)
        self.assertNotEqual(row["chosen"]["idx"], 1, "the surfaced default was NOT chosen")
        self.assertNotIn("verdict", row, "the logger records facts, never a derived label")

    # 5 ─────────────────────────────────────────────────────────────────────────────────────────
    def test_off_list_free_text_recorded(self):
        p = _pair_question("actually let's do something else entirely")
        self.sb.hook("log_impression.py", p)
        row = self._rows()[0]
        self.assertTrue(row["chosen"]["off_list"])
        self.assertIsNone(row["chosen"]["idx"])
        self.assertIn("something else", row["chosen"]["answer"])

    # 6 ─────────────────────────────────────────────────────────────────────────────────────────
    def test_malformed_payload_fails_open(self):
        r = self.sb.script("log_impression.py", stdin="not json at all {{{")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.sb.lines(STORE), [], "nothing written on a garbage payload")
        # a structurally-odd payload (questions is not a list) also fails open
        r = self.sb.hook("log_impression.py",
                         {"session_id": "s", "tool_input": {"questions": "nope"},
                          "tool_response": {"answers": {}}})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.sb.lines(STORE), [])

    # 7 ─────────────────────────────────────────────────────────────────────────────────────────
    def test_non_target_picker_ignored(self):
        q = {"question": "Build a tailored resume for ZZTestCo, or skip?",
             "header": "Resume", "options": [{"label": "Build it"}, {"label": "Skip"}]}
        r = self.sb.hook("log_impression.py", _payload([q], {q["question"]: "Skip"}))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.sb.lines(STORE), [], "a non-target picker writes nothing")

    # 8 ─────────────────────────────────────────────────────────────────────────────────────────
    def test_double_invocation_no_double_write(self):
        p = _pair_question("Phase 2 of the ranker")
        self.sb.hook("log_impression.py", p)
        self.sb.hook("log_impression.py", p)  # identical PostToolUse fired twice
        self.assertEqual(len(self._rows()), 1, "the impression_key dedupe collapses the double write")

    # 9 ─────────────────────────────────────────────────────────────────────────────────────────
    def test_generic_non_owner_target_picker(self):
        # A target picker OUTSIDE the pair, with invented names — no marker, matched on target shape.
        q = {"question": "Which of these three should you reach first?",
             "header": "Who first",
             "options": [
                 {"label": "Priya Raman · CTO @ Lumen Labs · rung 8"},
                 {"label": "Devon Msomi · VP Product @ Northwind · rung 8"},
                 {"label": "Refill the board"}]}
        r = self.sb.hook("log_impression.py", _payload([q], {q["question"]: q["options"][1]["label"]}))
        self.assertEqual(r.returncode, 0)
        row = self._rows()[0]
        self.assertEqual(row["trigger"], "target-shaped-option")
        self.assertEqual(row["options"][0]["target"]["name"], "Priya Raman")
        self.assertEqual(row["options"][0]["target"]["company"], "Lumen Labs")
        self.assertEqual(row["chosen"]["idx"], 2)

    # S1 ─── red-team regression: prefix match must not let a short label swallow a longer answer ──
    def test_prefix_match_picks_the_most_specific_label(self):
        q = {"question": "NEXT-STEP · what now? LADDER x", "header": "Next move",
             "options": [{"label": "Start"}, {"label": "Start the next loop"}]}
        # non-exact answer "Start the next" must resolve to option 2, never option 1 (the old
        # bidirectional prefix match returned idx 1 and flipped accepted vs passed-over).
        self.sb.hook("log_impression.py", _payload([q], {q["question"]: "Start the next"}))
        self.assertEqual(self._rows()[0]["chosen"]["idx"], 2)

    # S2 ─── red-team regression: a '|' in a label must not collide two different option sets ──────
    def test_pipe_in_label_does_not_collide(self):
        qa = {"question": "NEXT-STEP · pick", "header": "Next move",
              "options": [{"label": "x|y"}, {"label": "z"}]}
        qb = {"question": "NEXT-STEP · pick", "header": "Next move",
              "options": [{"label": "x"}, {"label": "y|z"}]}
        self.sb.hook("log_impression.py", _payload([qa], {qa["question"]: "x|y"}))
        self.sb.hook("log_impression.py", _payload([qb], {qb["question"]: "x"}))
        # The old '|'-joined key hashed both to "…|x|y|z" and dropped the second; distinct payloads
        # must produce distinct keys and both land.
        self.assertEqual(len(self._rows()), 2)

    # S3 ─── red-team regression: an '@' in the first segment must not shadow the company ────
    # (uses an email-style handle without a TLD, so it exercises the '@' case without shipping an
    # email address, which the kit's PII gate blocks outright)
    def test_at_in_first_segment_still_parses_company(self):
        q = {"question": "Who first?", "header": "Who first",
             "options": [{"label": "Priya Raman (priya@lumen) · VP @ Northwind · rung 8"},
                         {"label": "Refill the board"}]}
        self.sb.hook("log_impression.py", _payload([q], {q["question"]: "Refill the board"}))
        row = self._rows()[0]
        self.assertEqual(row["trigger"], "target-shaped-option")
        self.assertEqual(row["options"][0]["target"]["company"], "Northwind")
        self.assertEqual(row["options"][0]["target"]["rung"], "8")

    # 10 ────────────────────────────────────────────────────────────────────────────────────────
    def test_settings_wiring_places_hook_after_record_decision(self):
        # The kit ships the wiring in a settings example (which /setup copies into .claude/). The
        # source lives at the repo root in partner-starter and at .claude/settings.example.json once
        # assembled into the kit, so accept whichever is present.
        _cand = [os.path.join(LIVE_REPO, "settings.example.json"),
                 os.path.join(LIVE_REPO, ".claude", "settings.example.json")]
        _path = next((p for p in _cand if os.path.exists(p)), _cand[0])
        with open(_path, encoding="utf-8") as fh:
            s = json.load(fh)
        post = s.get("hooks", {}).get("PostToolUse", [])
        aq = next((e for e in post if e.get("matcher") == "AskUserQuestion"), None)
        self.assertIsNotNone(aq, "there must be a PostToolUse AskUserQuestion entry")
        cmds = [h.get("command", "") for h in aq.get("hooks", [])]
        rec = next(i for i, c in enumerate(cmds) if "record_decision.py" in c)
        imp = next((i for i, c in enumerate(cmds) if "log_impression.py" in c), None)
        self.assertIsNotNone(imp, "log_impression.py must be wired into the chain")
        self.assertGreater(imp, rec, "the impression logger runs AFTER the decision ledger")


# NOTE: keep this the LAST thing in the file (the documented unittest.main()-ordering footgun).
if __name__ == "__main__":
    unittest.main()
