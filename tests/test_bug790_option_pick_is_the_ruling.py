#!/usr/bin/env python3
"""BUG-790: an option pick is that option's ruling. The words typed after "#1" (or after a clicked
label) are his reasons: they may narrow a BUILD to OTHER, but they never turn the pick into a SKIP
and never write a hold on a contact. A hold is written only when the chosen option is itself a
hold, skip, pass or drop option, or the bare answer is a skip word with no options (BUG-233).

Regression fixture: the 2026-11-02 answer that put a SKIPPED hold on a contact the option named.
Every name below is invented. The test drives the real hook (`record_decision.py` over stdin) in a
child process per copy, with its own scratch project dir and HOME, so it never touches the live
ledger, key or contact store. Copies under test: this tree's scripts, plus partner-starter's when
this tree has one (AJS); the kit's own tests run the kit's copy from its own tree."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TREES = [os.path.join(REPO, "scripts")]
if os.path.isdir(os.path.join(REPO, "partner-starter", "scripts")):
    TREES.append(os.path.join(REPO, "partner-starter", "scripts"))

NEXT_STEP = "NEXT-STEP · what now? LADDER 2026-11-02 · sent 1 · replied 1 · rate 100% · 3-3-3 0/3"
HEADER = "Next move"
TODAY = ("#1; I'm not going to ask Dana the client because I already decided I will apply; "
         "i talked to Trina for more than 1 hour and I am comfortable applying with what I know; "
         "you can ask me questions if you want")


def opts(*labels):
    return [{"label": l, "description": "x"} for l in labels]


ANDY = opts("Default pick: Zorblat Fakeperson", "Refill the board with a discovery run", "Bug and test work")


def contacts():
    return {"contacts": {"Zorblat Fakeperson": {"closeness": "know-well", "outreach_status": "",
                                               "source": "stated-by-owner"}}}


class Run:
    """One hook run in a scratch project dir; the store bytes before and after are compared."""

    def __init__(self, tree, answer, options, question=NEXT_STEP):
        self.d = tempfile.mkdtemp(prefix="b790-")
        os.makedirs(os.path.join(self.d, "documents"))
        self.store = os.path.join(self.d, "documents", "contact-closeness.json")
        with open(self.store, "w", encoding="utf-8") as fh:
            json.dump(contacts(), fh, sort_keys=True)
        with open(self.store, "rb") as fh:
            self.before = fh.read()
        # Each run uses its own COPY of the scripts folder: the partner and kit copies find their ledger
        # and key beside the script, not in CLAUDE_PROJECT_DIR, so running them in place would write into
        # the real tree. No key exists in the scratch dir, so the row lands unsigned, which still records
        # the ruling this test reads.
        shutil.copytree(tree, os.path.join(self.d, "scripts"), ignore=shutil.ignore_patterns("__pycache__"))
        payload = {"session_id": "t790", "tool_input": {"questions": [
            {"question": question, "header": HEADER, "options": options}]},
            "tool_response": {"answers": {question: answer}}}
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.d, HOME=self.d)
        env.pop("JOBKIT_OWNER_ID", None)
        self.proc = subprocess.run([sys.executable, os.path.join(self.d, "scripts", "record_decision.py")],
                                   input=json.dumps(payload), capture_output=True, text=True,
                                   env=env, cwd=self.d, timeout=60)
        with open(self.store, "rb") as fh:
            self.after = fh.read()
        self.ledger = os.path.join(self.d, "documents", "decision-ledger.jsonl")
        self.store = os.path.join(self.d, "documents", "contact-closeness.json")

    def ruling(self):
        with open(self.ledger, encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        return rows[-1]["ruling"]

    def row(self):
        return json.load(open(self.store, encoding="utf-8"))["contacts"]["Zorblat Fakeperson"]

    def close(self):
        shutil.rmtree(self.d, ignore_errors=True)


class Base(unittest.TestCase):
    def run_all(self, answer, options, check, question=NEXT_STEP):
        for tree in TREES:
            with self.subTest(tree=os.path.relpath(tree, REPO)):
                r = Run(tree, answer, options, question)
                try:
                    check(r)
                finally:
                    r.close()


class R1TodaysStringIsTheRegressionFixture(Base):
    def test_ruling_other_store_untouched_nothing_printed(self):
        def check(r):
            self.assertEqual(r.ruling(), "OTHER", r.proc.stderr)
            self.assertEqual(r.before, r.after, "the contact store changed")
            self.assertNotIn("SKIPPED", r.proc.stdout + r.proc.stderr)
        self.run_all(TODAY, ANDY, check)


class R2TheBarePickIsUnchanged(Base):
    def test_bare_pick(self):
        def check(r):
            self.assertEqual(r.ruling(), "OTHER")
            self.assertEqual(r.before, r.after)
        self.run_all("#1", ANDY, check)


class R3FreeTextNeverFlipsAPick(Base):
    CASES = ["#1; skip it", "#1 but skip it", "#1 hold Zorblat", "#1 not now"]

    def test_no_hold_and_one_seat_line_only_when_a_hold_word_is_there(self):
        for ans in self.CASES:
            def check(r, ans=ans):
                self.assertEqual(r.ruling(), "OTHER", ans)
                self.assertEqual(r.before, r.after, f"{ans!r} wrote a hold")
                if any(w in ans for w in ("skip", "hold")):
                    self.assertIn("record_decision: option 1 recorded; the words after it carry", r.proc.stderr, ans)
                    self.assertIn("confirm with him in a picker before any hold", r.proc.stderr, ans)
                else:
                    self.assertNotIn("confirm with him in a picker", r.proc.stderr, ans)
            self.run_all(ans, ANDY, check)

    def test_the_line_is_absent_when_the_free_text_has_no_hold_word(self):
        def check(r):
            self.assertNotIn("confirm with him in a picker", r.proc.stderr)
        self.run_all(TODAY, ANDY, check)


class R3bAClickedLiftLabelIsNotAHold(Base):
    """82's replay: a clicked "lift the hold" label read as SKIP and held the contact (2026-09-12)."""

    def test_clicked_lift_label_writes_no_hold(self):
        lab = "Pushed. Verify Zorblat Fakeperson and lift the hold (Recommended)"
        def check(r):
            self.assertEqual(r.before, r.after, "a lift label wrote a hold")
        self.run_all(lab, opts(lab, "Refill the board with a discovery run"), check)


class R4ASkipLabelStillHolds(Base):
    def test_skip_label_picked_as_a_number(self):
        def check(r):
            # All copies resolve "#1" to the label before classifying (BUG-794 N2), so the ruling is SKIP.
            self.assertEqual(r.ruling(), "SKIP")
            self.assertTrue(r.row().get("outreach_status", "").startswith("PAUSED-by"))
            self.assertIn("Skip Zorblat Fakeperson", r.row().get("paused_note", ""))
        self.run_all("#1", opts("Skip Zorblat Fakeperson", "Other"), check)

    def test_hold_label_clicked(self):
        def check(r):
            self.assertTrue(r.row().get("outreach_status", "").startswith("PAUSED-by"))
            self.assertIn("Hold Zorblat Fakeperson", r.row().get("paused_note", ""))
        self.run_all("Hold Zorblat Fakeperson, recompute", opts("Hold Zorblat Fakeperson, recompute", "Other"), check)

    def test_pass_and_drop_labels_hold(self):
        for lab in ("Pass on Zorblat Fakeperson", "Drop Zorblat Fakeperson"):
            def check(r, lab=lab):
                self.assertTrue(r.row().get("outreach_status", "").startswith("PAUSED-by"), lab)
            self.run_all(lab, opts(lab, "Other"), check)

    def test_a_bare_skip_with_no_options_is_still_a_skip(self):
        def check(r):
            self.assertEqual(r.ruling(), "SKIP")
        self.run_all("skip", [], check, question="Skip Zorblat Fakeperson?")

    def test_a_typed_skip_word_with_no_pick_still_holds_the_named_contact(self):
        def check(r):
            self.assertTrue(r.row().get("outreach_status", "").startswith("PAUSED-by"))
        self.run_all("skip it", [], check, question="Skip Zorblat Fakeperson for now?")


class R5TheBuildVetoSurvives(Base):
    BUILD_Q = "Build the outreach email for Alpha Co? Pat Fakeboss is the boss."
    BUILD_OPTS = opts("Build it for Alpha Co", "Not yet")

    def test_a_negation_after_a_build_pick_is_not_a_build(self):
        def check(r):
            self.assertNotEqual(r.ruling(), "BUILD")
            self.assertNotEqual(r.ruling(), "SKIP")
        self.run_all("#1 but I'm not sure about the boss", self.BUILD_OPTS, check, question=self.BUILD_Q)

    def test_the_clicked_build_label_still_builds(self):
        def check(r):
            self.assertEqual(r.ruling(), "BUILD")
        self.run_all("Build it for Alpha Co", self.BUILD_OPTS, check, question=self.BUILD_Q)


class R6TheThreeCopiesCarryOneHunk(unittest.TestCase):
    def test_the_helper_text_is_identical_across_the_copies_under_test(self):
        def hunk(tree):
            s = open(os.path.join(tree, "record_decision.py"), encoding="utf-8").read()
            a = s.index("# BUG-790: an option pick IS that option's ruling")
            return s[a:s.index("def apply_hold_or_lift(")]
        texts = {t: hunk(t) for t in TREES}
        self.assertEqual(len(set(texts.values())), 1, "the BUG-790 helper differs between copies")


class R7TheNicknameCompanyIsAKnownDefect(unittest.TestCase):
    """extract_company reads 'Trina' (a nickname) from today's string. Not fixed here; BUG-792 owns it.
    This asserts the defect so the follow-up has a red test waiting: when BUG-792 lands, flip it."""

    def test_trina_is_still_extracted(self):
        for tree in TREES:
            with self.subTest(tree=os.path.relpath(tree, REPO)):
                d = tempfile.mkdtemp(prefix="b790c-")
                try:
                    os.makedirs(os.path.join(d, "documents"))
                    r = Run(tree, TODAY, ANDY)
                    try:
                        with open(r.ledger, encoding="utf-8") as fh:
                            company = json.loads(fh.read().splitlines()[-1])["company"]
                    finally:
                        r.close()
                    self.assertEqual(company, "Trina", "BUG-792 may have landed: flip this test")
                finally:
                    shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
