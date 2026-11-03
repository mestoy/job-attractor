"""kit #165 + kit #228: a draft Mail made is never logged as nothing, and the row says what is known about the attachment.

#165 (false success): the attach call is silent on failure, so the count is read back; zero is exit 7.
#228 (false failure, a partner, Exchange): the re-read itself failed (-1728), the AppleScript errored, the wrapper printed
"Nothing was recorded as staged" and wrote no row, while a good draft sat in Mail. Now every path after
`make new outgoing message` returns a word, the stores are written for every state, and only a draft WITHOUT the
résumé exits 7, after the stores.

osascript does not exist on Linux, so the AppleScript and the wrapper are asserted as shell source, the way
test_mail_draft_exit_codes.py does; the bash state block is also RUN here with fake osascript words. The live proof is
a partner's run on an Exchange account. The same file runs in AJS tests/ and partner-starter/tests/ (REPO resolves per tree)."""
import json
import os
import re
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "mail-draft.sh")
PARTNER = os.path.join(REPO, "partner-starter", "scripts", "mail-draft.sh")
KIT = "/home/vscode/kit-app"


def _src(path=SCRIPT):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _between(src, begin, end):
    i = src.index(begin)
    return src[i:src.index(end, i) + len(end)]


def _applescript(src):
    i = src.index("<<'APPLESCRIPT'")
    return src[i:src.index("\nAPPLESCRIPT\n", i)]


class TheScriptParses(unittest.TestCase):
    def test_bash_still_accepts_it(self):
        r = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_exchange_duplicate_draft_behavior_is_documented_in_the_header(self):
        header = _src().split("set -uo pipefail")[0]
        self.assertIn("Exchange", header)
        self.assertIn("165", header)
        self.assertIn("228", header)


class TheAppleScriptReportsInsteadOfErroring(unittest.TestCase):
    def setUp(self):
        self.osa = _applescript(_src())
        self.make = self.osa.index("make new outgoing message")
        self.try_at = self.osa.index("        try\n", self.make)

    def test_reads_are_inside_try_and_report_words(self):
        self.assertEqual(self.osa[self.make:self.try_at].count("\n"), 1, "the outer try opens on the line after the draft is made")
        end_try = self.osa.index("on error errMsg")
        for stmt in ("set sender of m", "make new to recipient", "make new bcc recipient", "make new attachment"):
            at = self.osa.index(stmt)
            self.assertTrue(self.try_at < at < end_try, "%s sits outside the outer try" % stmt)
        count_at = self.osa.index("count of mail attachments of m")
        self.assertTrue(self.osa[:count_at].rstrip().endswith("try\n                set attachCount to (") or "try" in self.osa[count_at - 120:count_at])
        for word in ("ATTACH_VERIFIED", "ATTACH_UNVERIFIED", "ATTACH_MISSING", "ATTACH_ERROR", "ambiguous"):
            self.assertIn(word, self.osa)
        after = self.osa[self.make:]
        self.assertIsNone(re.search(r'(?m)^\s*error\s+"', after), "no `error` call may remain after the draft is made")

    def test_drafts_lookup_is_scoped_and_unique(self):
        self.assertLess(self.osa.index("set startStamp to current date"), self.make, "the stamp is taken before the draft is made")
        self.assertIn("date received > startStamp", self.osa)
        self.assertIn("whose subject is subj", self.osa)
        self.assertIn("(count of draftMatches) is not 1", self.osa)
        amb = self.osa.index("ATTACH_UNVERIFIED: ambiguous")
        self.assertLess(self.osa.index("(count of draftMatches) is not 1"), amb)
        self.assertLess(amb, self.osa.index('return "ATTACH_VERIFIED"'), "two matches can never reach the verified word")

    def test_retry_then_drafts_lookup_then_unverified(self):
        count = self.osa.index("set attachCount to (count of mail attachments of m)")
        d1 = self.osa.index("delay 1\n", count)
        d2 = self.osa.index("delay 2\n", d1)
        d4 = self.osa.index("delay 4\n", d2)
        lookup = self.osa.index('mailbox "Drafts"', d4)
        unread = self.osa.index('return "ATTACH_UNVERIFIED: unreadable"', lookup)
        self.assertTrue(count < d1 < d2 < d4 < lookup < unread)


class TheWrapperOrdersItsExits(unittest.TestCase):
    def test_wrapper_captures_stdout_and_sets_state(self):
        src = _src()
        self.assertRegex(src, r'osascript - [^\n]*"\$FROM" <<.APPLESCRIPT. >"\$_OSA_OUTFILE"')
        self.assertIn('_OSA_OUT="$(cat "$_OSA_OUTFILE"', src)
        self.assertRegex(src, r'_OSA_RC=\$\?|STATUS=\$\?')
        block = _between(src, "# BEGIN #228 attachment state", "# END #228 attachment state")
        for word, state in (("ATTACH_VERIFIED", "verified"), ("ATTACH_MISSING", "missing"),
                            ("ATTACH_UNVERIFIED: ambiguous (2 drafts)", "unverified"),
                            ("ATTACH_ERROR: Can't get every mail attachment", "attach_error"),
                            ("", "unverified")):
            got = self._state(block, word, attach="/tmp/resume.pdf")
            self.assertEqual(got["state"], state, word)
        self.assertEqual(self._state(block, "ATTACH_NA", attach="")["state"], "n/a")
        self.assertEqual(self._state(block, "ATTACH_UNVERIFIED: ambiguous (2 drafts)", attach="/x")["reason"], "ambiguous (2 drafts)")

    def _state(self, block, word, attach):
        prog = 'DELIVERY=apple-mail; ATTACH="$1"; _OSA_OUT="$2"\n%s\nprintf "%%s|%%s|%%s" "$_ATTACH_STATE" "$_ATTACH_REASON" "$_ATTACH_NOTE"\n' % block
        out = subprocess.run(["bash", "-c", prog, "x", attach, word], capture_output=True, text=True).stdout
        state, reason, note = out.split("|", 2)
        return {"state": state, "reason": reason, "note": note}

    def test_state_words_reach_the_screen_and_all_three_stores(self):
        block = _between(_src(), "# BEGIN #228 attachment state", "# END #228 attachment state")
        unv = self._state(block, "ATTACH_UNVERIFIED: ambiguous (2 drafts)", "/x")["note"]
        self.assertIn("attachment not verified by Mail", unv)
        self.assertIn("ambiguous (2 drafts)", unv)
        for word in ("ATTACH_MISSING", "ATTACH_ERROR: boom"):
            self.assertIn("WITHOUT the résumé", self._state(block, word, "/x")["note"])
        self.assertEqual(self._state(block, "ATTACH_VERIFIED", "/x")["note"], "")
        src = _src()
        self.assertIn("**Attachment:** %s", src)                         # the outreach_log STAGED block
        self.assertIn("${_ATTACH_NOTE:+ · $_ATTACH_NOTE}", src)        # the correspondence-log line
        self.assertIn('echo "⚠️  $_ATTACH_NOTE"', src)                    # the terminal warn line the app already relays

    def test_every_exit_after_the_draft_writes_the_row(self):
        src = _src()
        osa_end = src.index("\nAPPLESCRIPT\n")
        last_store = src.index("OUTBOUND (STAGED")
        exits = [m.start() for m in re.finditer(r"\bexit 7\b", src) if m.start() > osa_end]
        self.assertTrue(exits)
        early = [e for e in exits if e < last_store]
        for e in early:   # the only exit 7 before the stores is the no-draft guard
            self.assertRegex(src[max(0, e - 700):e], r'_OSA_RC"? -ne 0', "an exit 7 before the stores that is not the no-draft guard")
        if "STATUS=$?" in src and "_OSA_RC" not in src:
            self.assertEqual(early, [])

    def test_exit_codes_by_state(self):
        src = _src()
        tail = src[src.index("OUTBOUND (STAGED"):]
        m = re.search(r'case "\$_ATTACH_STATE" in\n\s*missing\|attach_error\) exit 7 ;;\nesac', tail)
        self.assertIsNotNone(m, "missing and attach_error exit 7 after the stores")
        self.assertNotRegex(m.group(0), r"verified\)|unverified\)")


class TheRowCarriesTheFields(unittest.TestCase):
    def test_row_carries_attachment_fields(self):
        src = _src()
        for key in ("attachment_verified", "attachment_state", "attachment_reason"):
            self.assertIn('"%s"' % key, src)
        self.assertTrue('STAGED_STATUS = "staged"' in src or '"status": "drafted"' in src, "the status is unchanged")

    def test_the_new_python_heredocs_compile(self):
        src = _src()
        for tag in ("PYLOG", "PYATT"):
            for m in re.finditer(r"<<'%s'[^\n]*\n(.*?)\n%s\n" % (tag, tag), src, re.S):
                compile(m.group(1), tag, "exec")

    def test_readers_accept_the_new_keys(self):
        # A4: nothing reads the new keys, and a staged row stays a weak hit whatever else it carries.
        import sys
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        import check_dup
        self.assertNotIn("staged", check_dup.SENDLOG_DELIVERED)
        for base in ("scripts", "partner-starter/scripts"):
            root = os.path.join(REPO, base)
            if not os.path.isdir(root):
                continue
            for fn in os.listdir(root):
                if fn.endswith((".py", ".sh")) and fn != "mail-draft.sh":
                    with open(os.path.join(root, fn), encoding="utf-8", errors="ignore") as fh:
                        self.assertNotIn("attachment_verified", fh.read(), "%s reads a key that is not a send" % fn)
        import balancer
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "documents"))
            row = {"ts": "2026-11-02T10:00:00", "date": "2026-11-02", "channel": "email", "status": "staged", "rung": "cold-boss",
                   "to": "x@fake.example", "company": "Fakeco", "attachment_verified": False,
                   "attachment_state": "unverified", "attachment_reason": "ambiguous (2 drafts)"}
            with open(os.path.join(td, "documents", "send-log.jsonl"), "w", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            balancer.recommend(repo=td)


class TheCopiesAgree(unittest.TestCase):
    def test_three_copies_agree(self):
        if not os.path.exists(PARTNER):
            self.skipTest("partner-starter copy is not in this tree")
        a, b = _src(SCRIPT), _src(PARTNER)
        for begin, end in (("-- BEGIN #228 attach-and-verify", "-- END #228 attach-and-verify"),
                           ("# BEGIN #228 attachment state", "# END #228 attachment state")):
            self.assertEqual(_between(a, begin, end), _between(b, begin, end), begin)
        r = subprocess.run(["git", "-C", KIT, "show", "origin/main:scripts/mail-draft.sh"], capture_output=True, text=True)
        if r.returncode == 0 and "BEGIN #228" in r.stdout:    # the kit follows by sync; compare once it has the block
            for begin, end in (("-- BEGIN #228 attach-and-verify", "-- END #228 attach-and-verify"),
                               ("# BEGIN #228 attachment state", "# END #228 attachment state")):
                self.assertEqual(_between(a, begin, end), _between(r.stdout, begin, end), "kit " + begin)


if __name__ == "__main__":
    unittest.main()
