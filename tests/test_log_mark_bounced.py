"""Slice K step 1: `log_linkedin_send.py --mark-bounced --to <address>` (plan rev 4 correction 1, rev 6).

`bounced` is a STATUS, not a funnel stage, and `--confirm-sent` is the writer's only other status flipper. This flag flips the newest row for the recipient
(same_recipient, the match set_stage uses) from sent or staged to bounced, stamps `bounced_at`, and records the history: `bounced_to` (the address that
bounced) and `first_bounced_at` are written once and never overwritten; a second bounce writes `bounced_at` anew. A drafted or bounced row is refused with the reason.
Other rows stay byte-identical. The write takes an flock on <log>.lock. --dry-run previews on a copy.
Run: python3 -m unittest tests.test_log_mark_bounced
"""
import datetime
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import log_linkedin_send as lls  # noqa: E402

TODAY = datetime.date.today().isoformat()


def row(**over):
    r = {"ts": "2026-10-01T09:00:00", "date": "2026-10-01", "channel": "email", "status": "sent", "rung": "cold-boss", "to": "a.person@example.test",
         "company": "Acme Fakeworks", "subject": "A note", "replied": None}
    r.update(over)
    return r


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sk-mb-", dir=os.environ.get("SJ_TMP") or None)
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.log = os.path.join(self.tmp, "send-log.jsonl")

    def put(self, *rows):
        with open(self.log, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    def lines(self):
        return open(self.log, encoding="utf-8").read().splitlines()

    def cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "log_linkedin_send.py"), "--path", self.log, *args], capture_output=True, text=True)


class TheFlagFlipsOneRowAndOnlyOne(Base):
    def test_a_sent_row_flips_and_the_others_are_byte_identical(self):
        a, b, c = row(to="one@example.test", date="2026-09-01"), row(), row(to="three@example.test", date="2026-10-02")
        self.put(a, b, c)
        before = self.lines()
        r = self.cli("--mark-bounced", "--to", "a.person@example.test")
        self.assertEqual(0, r.returncode, r.stderr)
        after = self.lines()
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[2], after[2])
        got = json.loads(after[1])
        self.assertEqual("bounced", got["status"])
        self.assertEqual(TODAY, got["bounced_at"])
        self.assertEqual("a.person@example.test", got["bounced_to"])
        self.assertEqual(TODAY, got["first_bounced_at"])

    def test_a_staged_row_flips_too(self):
        self.put(row(status="staged"))
        self.assertEqual(0, self.cli("--mark-bounced", "--to", "a.person@example.test").returncode)
        self.assertEqual("bounced", json.loads(self.lines()[0])["status"])

    def test_a_drafted_row_is_refused_with_the_reason_and_nothing_changes(self):
        self.put(row(status="drafted"))
        before = self.lines()
        r = self.cli("--mark-bounced", "--to", "a.person@example.test")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("drafted", r.stderr)
        self.assertEqual(before, self.lines())

    def test_a_bounced_row_is_never_flipped_again(self):
        self.put(row(status="bounced", bounced_at="2026-10-02"))
        before = self.lines()
        r = self.cli("--mark-bounced", "--to", "a.person@example.test")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("already bounced", r.stderr)
        self.assertEqual(before, self.lines())

    def test_no_row_for_the_address_is_an_error(self):
        self.put(row())
        r = self.cli("--mark-bounced", "--to", "nobody@example.test")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("no send-log row", r.stderr)

    def test_the_newest_row_for_the_recipient_is_the_one_flipped(self):
        self.put(row(date="2026-09-01", ts="2026-09-01T09:00:00"), row(date="2026-10-01"))
        self.cli("--mark-bounced", "--to", "a.person@example.test")
        l = [json.loads(x) for x in self.lines()]
        self.assertEqual(["sent", "bounced"], [x["status"] for x in l])

    def test_dry_run_previews_a_copy_and_writes_nothing(self):
        self.put(row())
        before = self.lines()
        r = self.cli("--mark-bounced", "--to", "a.person@example.test", "--dry-run")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("bounced", json.loads(r.stdout)["status"])
        self.assertEqual(before, self.lines())
        self.assertFalse(os.path.exists(self.log + ".lock"))


class TheAddressJoinsTheBouncedList(Base):
    def lst(self):
        p = os.path.join(self.tmp, "bounced-addresses.txt")
        return open(p, encoding="utf-8").read().splitlines() if os.path.exists(p) else None

    def test_the_cli_path_writes_the_address_beside_the_log_once(self):
        self.put(row())
        self.assertEqual(0, self.cli("--mark-bounced", "--to", "a.person@example.test").returncode)
        self.assertEqual(["a.person@example.test"], self.lst())
        r = json.loads(self.lines()[0]); r["status"] = "sent"; self.put(r)
        self.cli("--mark-bounced", "--to", "a.person@example.test")
        self.assertEqual(["a.person@example.test"], self.lst(), "never twice")

    def test_a_refused_row_and_a_dry_run_and_a_linkedin_row_write_nothing(self):
        self.put(row(status="drafted"))
        self.cli("--mark-bounced", "--to", "a.person@example.test")
        self.put(row())
        self.cli("--mark-bounced", "--to", "a.person@example.test", "--dry-run")
        self.put(row(to="www.linkedin.example/in/zzyx-widgets-fake-0001"))
        self.cli("--mark-bounced", "--to", "www.linkedin.example/in/zzyx-widgets-fake-0001")
        self.assertIsNone(self.lst())

    def test_the_comment_lines_and_case_of_an_existing_list_are_kept(self):
        open(os.path.join(self.tmp, "bounced-addresses.txt"), "w").write("# kept\n" + "a.person@example.test".title())
        self.put(row())
        self.cli("--mark-bounced", "--to", "a.person@example.test")
        self.assertEqual(["# kept", "a.person@example.test".title()], self.lst())


class TheBounceHistoryIsWrittenOnceAndKept(Base):
    def test_bounced_then_resent_then_bounced_again_keeps_both_addresses_and_both_dates(self):
        self.put(row())
        self.assertEqual(0, self.cli("--mark-bounced", "--to", "a.person@example.test", "--bounced-at", "2026-10-02").returncode)
        # the resend, as mail-draft.sh's in-place rewrite leaves it: new to, staged, history carried, resent_date set
        r = json.loads(self.lines()[0])
        r.update({"to": "b.person@example.test", "status": "staged", "resent_date": "2026-10-03"})
        self.put(r)
        self.assertEqual(0, self.cli("--mark-bounced", "--to", "b.person@example.test", "--bounced-at", "2026-10-05").returncode)
        got = json.loads(self.lines()[0])
        self.assertEqual(1, len(self.lines()))
        self.assertEqual("bounced", got["status"])
        self.assertEqual("a.person@example.test", got["bounced_to"])
        self.assertEqual("2026-10-02", got["first_bounced_at"])
        self.assertEqual("2026-10-05", got["bounced_at"])
        self.assertEqual("b.person@example.test", got["to"])
        self.assertEqual("2026-10-03", got["resent_date"])


class TheWriteTakesTheLock(Base):
    def test_a_held_lock_holds_the_write_back_and_the_lock_file_is_made(self):
        self.put(row())
        fh = open(self.log + ".lock", "a")
        fcntl.flock(fh, fcntl.LOCK_EX)
        p = subprocess.Popen([sys.executable, os.path.join(SCRIPTS, "log_linkedin_send.py"), "--path", self.log, "--mark-bounced", "--to", "a.person@example.test"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.5)
        self.assertIsNone(p.poll(), "the writer did not wait for the lock")
        self.assertEqual("sent", json.loads(self.lines()[0])["status"])
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
        p.communicate(timeout=30)
        self.assertEqual(0, p.returncode)
        self.assertEqual("bounced", json.loads(self.lines()[0])["status"])


if __name__ == "__main__":
    unittest.main()
