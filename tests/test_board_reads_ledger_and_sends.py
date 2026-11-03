"""BUG-317: a decision in the ledger, or a delivered send, must reach a card that carries neither a
token nor a queue header. Otherwise a decided card sits in Decide again and the plans pick it up.

Precedence, fill-only: the card's own token > the queue > the ledger (latest row per company).
A delivered send-log row turns a card the ledger (or nothing) put at BUILD or undecided into SENT.
Which ledger rows count (b4, option B, 2026-09-21): a SIGNED hook row, or an UNSIGNED manual row
("manual-devcontainer-no-hooks") whose ruling is BUILD/RADAR/PARK/DROP, or HOLD with an answer that
starts with one of those. A hook-source row whose signature does not verify is forged and ignored.
Every ledger-filled status says where it came from. The send gate (check_preview) is not touched.
"""
import json
import os
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)
from harness import scratch_root  # noqa: E402

SANDBOX = os.path.join(scratch_root(), "test-board-ledger-sends")

CARDS = {
    "fakemonth": "# Fakemonth · applied-ai · LIVE · panel 70\n",
    "fakecertco": "# Fakecertco · applied-ai · LIVE · panel 70\n",
    "fakedrop": "# Fakedrop · govtech · LIVE · panel 70\n",
    "nothing": "# Nothing Fake Co · payments · LIVE · panel 70\n",
    "ruled": "# Ruled Fake Co · payments · LIVE · STATUS: PARK\n",
    "queued": "# Queued Fake Co · payments · LIVE · panel 70\n",
    "forgedco": "# Forged Fake Co · payments · LIVE · panel 70\n",
    "latestco": "# Latest Fake Co · payments · LIVE · panel 70\n",
    "skipco": "# Skip Fake Co · payments · LIVE · panel 70\n",
    "tokenbuild": "# Token Build Co · payments · LIVE · STATUS: BUILD\n",
    "newerbuild": "# Newer Build Co · payments · LIVE · panel 70\n",
    "timedsend": "# Timed Send Co · payments · LIVE · panel 70\n",
}
QUEUE = "# Queue\n\n## 2026-08-01 · Queued Fake Co · STATUS: RADAR\nbody\n"


def manual(company, ruling, answer, ts):
    return {"ts": ts, "session": "s", "question": "q", "header": "h", "answer": answer, "ruling": ruling,
            "company": company, "source": "manual-devcontainer-no-hooks"}


class BoardReadsLedgerAndSends(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        cls.home = os.path.join(SANDBOX, "home")
        repo = cls.repo = os.path.join(SANDBOX, "repo")
        state = os.path.join(repo, "documents", "state")
        os.makedirs(state)
        os.makedirs(cls.home)
        for slug, text in CARDS.items():
            with open(os.path.join(state, "%s-card-2026-09-04.md" % slug), "w", encoding="utf-8") as fh:
                fh.write(text)
        with open(os.path.join(repo, "documents", "outreach-queue.md"), "w", encoding="utf-8") as fh:
            fh.write(QUEUE)
        cls._env = {k: os.environ.get(k) for k in ("HOME", "JOBKIT_LEDGER_KEYFILE")}
        os.environ["HOME"] = cls.home
        keyfile = os.path.join(cls.home, ".jobsearch-ledger-key")
        os.environ["JOBKIT_LEDGER_KEYFILE"] = keyfile
        import ledger_keys as lk
        import ledger_write as lw
        key = lk.mint_key(keyfile)
        ledger = os.path.join(repo, "documents", "decision-ledger.jsonl")
        hook = lambda company, ruling, ts: {"ts": ts, "session": "s", "question": "q", "header": "h",
                                            "answer": "Build it", "ruling": ruling, "company": company,
                                            "source": "posttooluse-hook"}
        lw.append_signed_row(ledger, hook("Fakecertco", "BUILD", "2026-09-04T13:00:00+00:00"), key, lk.key_id(key))
        lw.append_signed_row(ledger, manual("Fakemonth", "HOLD", "PARK; the overlap rule applies", "2026-09-04T13:59:10+00:00"),
                             b"", "", "manual")
        lw.append_signed_row(ledger, manual("Fakedrop", "DROP", "DROP, conduct gate", "2026-09-04T14:00:00+00:00"), b"", "", "manual")
        lw.append_signed_row(ledger, manual("Ruled Fake Co", "BUILD", "BUILD", "2026-09-05T00:00:00+00:00"), b"", "", "manual")
        lw.append_signed_row(ledger, manual("Queued Fake Co", "DROP", "DROP", "2026-09-05T00:00:00+00:00"), b"", "", "manual")
        lw.append_signed_row(ledger, manual("Latest Fake Co", "RADAR", "RADAR", "2026-09-01T00:00:00+00:00"), b"", "", "manual")
        lw.append_signed_row(ledger, manual("Latest Fake Co", "PARK", "PARK", "2026-09-03T00:00:00+00:00"), b"", "", "manual")
        lw.append_signed_row(ledger, manual("Skip Fake Co", "OTHER", "PARK it later maybe", "2026-09-03T00:00:00+00:00"), b"", "", "manual")
        # A BUILD decided AFTER an old send is a new decision (a next target); it must stay BUILD.
        lw.append_signed_row(ledger, hook("Newer Build Co", "BUILD", "2026-09-10T12:00:00+00:00"), key, lk.key_id(key))
        # A send timed after the same-day decision flips; the times are compared in UTC.
        lw.append_signed_row(ledger, hook("Timed Send Co", "BUILD", "2026-09-04T17:13:44+00:00"), key, lk.key_id(key))
        # Forged: a hook-source row whose mac was not made by any key this machine holds.
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(hook("Forged Fake Co", "BUILD", "2026-09-05T00:00:00+00:00"),
                                     mac="0" * 64, kid="nope")) + "\n")
        with open(os.path.join(repo, "documents", "send-log.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"date": "2026-09-04", "company": "Fakecertco", "status": "sent",
                                 "to_name": "Pat Example", "rung": "cold-boss"}) + "\n")
            fh.write(json.dumps({"date": "2026-09-04", "company": "Token Build Co", "status": "sent",
                                 "to_name": "Sam Example", "rung": "cold-boss"}) + "\n")
            fh.write(json.dumps({"date": "2026-08-01", "company": "Newer Build Co", "status": "sent",
                                 "to_name": "Old Target", "rung": "cold-boss"}) + "\n")
            fh.write(json.dumps({"ts": "2026-09-04T13:13:46-04:00", "date": "2026-09-04", "company": "Timed Send Co",
                                 "status": "sent", "to_name": "Pat Example", "rung": "cold-boss"}) + "\n")
        import board
        cls.merged, cls.disagree = board.resolve_stages(repo)
        import depth_report
        cls.basis = depth_report.stage_basis(repo)

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(SANDBOX, ignore_errors=True)

    def test_june_reads_park_from_an_unsigned_manual_hold_row(self):
        self.assertEqual(self.merged["fakemonth"], "PARK")
        self.assertEqual(self.basis["fakemonth"]["source"], "ledger-unsigned")

    def test_fakecertco_signed_build_plus_a_delivered_send_reads_sent(self):
        self.assertEqual(self.merged["fakecertco"], "SENT")

    def test_a_manual_drop_reads_drop(self):
        self.assertEqual(self.merged["fakedrop"], "DROP")

    def test_no_row_stays_undecided(self):
        self.assertEqual(self.merged["nothing"], "carded_unruled")

    def test_the_card_token_wins_and_the_disagreement_is_reported(self):
        self.assertEqual(self.merged["ruled"], "PARK")
        self.assertIn(("ruled", "PARK", "BUILD"), self.disagree)

    def test_the_queue_wins_over_the_ledger(self):
        self.assertEqual(self.merged["queued"], "RADAR")

    def test_a_forged_hook_row_is_ignored(self):
        self.assertEqual(self.merged["forgedco"], "carded_unruled")

    def test_the_latest_row_per_company_wins(self):
        self.assertEqual(self.merged["latestco"], "PARK")

    def test_a_non_verdict_row_is_ignored(self):
        self.assertEqual(self.merged["skipco"], "carded_unruled")

    def test_a_build_decided_after_an_old_send_stays_build(self):
        self.assertEqual(self.merged["newerbuild"], "BUILD")

    def test_a_send_after_the_decision_in_utc_reads_sent(self):
        self.assertEqual(self.merged["timedsend"], "SENT")

    def test_an_explicit_card_build_is_not_turned_into_sent(self):
        self.assertEqual(self.merged["tokenbuild"], "BUILD")

    def test_the_board_basis_says_send_log_for_a_sent_card(self):
        import board
        _m, _d, basis = board.resolve_stages_basis(self.repo)
        self.assertEqual(basis["fakecertco"]["source"], "send-log")
        self.assertEqual(basis["nothing"]["source"], "none")
        self.assertEqual(basis["ruled"]["source"], "card")
        self.assertEqual(basis["queued"]["source"], "queue")

    def test_the_signed_basis_is_labeled_signed(self):
        import depth_report
        stages, _o, _s = depth_report.scan_cards(self.repo)
        led = depth_report.ledger_statuses(self.repo)
        self.assertEqual(led["fakecertco"]["provenance"], "signed")


if __name__ == "__main__":
    unittest.main()
