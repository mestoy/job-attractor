"""mail_deliver.py: getting the note (and the résumé) somewhere a person can act on it, in any mail client.

The rule this pins: it never says a draft exists when none does, it never sends, and it names what it did NOT
do (a link cannot carry a file; a file may open read-only in some programs). Fictional fixtures only."""
import contextlib
import email
import io
import os
import platform
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

import mail_deliver as md  # noqa: E402

BODY = "Hi, Jane!\n\nCafé résumé naïve — and an emoji 🙂 & a line break.\nSecond line.\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mail-deliver-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.body = os.path.join(self.tmp, "body.txt")
        with open(self.body, "w", encoding="utf-8") as fh:
            fh.write(BODY)
        self.pdf = os.path.join(self.tmp, "Fictional Owner - Resume - Acme.pdf")
        with open(self.pdf, "wb") as fh:
            fh.write(b"%PDF-1.4 fictional resume bytes\n%%EOF\n")
        self._state = os.path.join(self.tmp, "state", "mail-client.json")
        p = mock.patch.object(md, "STATE_FILE", self._state)
        p.start()
        self.addCleanup(p.stop)

    def run_deliver(self, *args, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = md.deliver(*args, **kw)
        return rc, buf.getvalue()

    def stub_osascript(self, rc):
        d = os.path.join(self.tmp, "bin")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "osascript")
        with open(p, "w") as fh:
            fh.write(f"#!/bin/sh\nexit {rc}\n")
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        return d


class EmlTests(Base):
    def test_the_file_parses_back_with_every_header_the_body_and_the_resume(self):
        raw = md.build_eml("jane@example.test", "Hello ☕", BODY, "b1@example.test,b2@example.test", self.pdf,
                           "me@example.test")
        m = email.message_from_bytes(raw)
        self.assertEqual(m["To"], "jane@example.test")
        self.assertEqual(m["From"], "me@example.test")
        self.assertIn("b1@example.test", m["Bcc"])
        self.assertEqual(str(email.header.make_header(email.header.decode_header(m["Subject"]))), "Hello ☕")
        self.assertEqual(m["X-Unsent"], "1")
        parts = list(m.walk())
        text = next(p for p in parts if p.get_content_type() == "text/plain")
        self.assertEqual(text.get_payload(decode=True).decode("utf-8").replace("\r\n", "\n"), BODY)
        att = next(p for p in parts if p.get_filename())
        self.assertEqual(att.get_filename(), "Fictional Owner - Resume - Acme.pdf")
        self.assertEqual(att.get_content_type(), "application/pdf")
        with open(self.pdf, "rb") as fh:
            self.assertEqual(att.get_payload(decode=True), fh.read())

    def test_no_from_and_no_bcc_are_simply_absent(self):
        m = email.message_from_bytes(md.build_eml("jane@example.test", "Hello", BODY))
        self.assertIsNone(m["From"])
        self.assertIsNone(m["Bcc"])

    def test_deliver_writes_the_file_beside_the_note_and_says_what_does_not_exist_yet(self):
        rc, out = self.run_deliver("eml", "jane@example.test", "Hello", self.body, attach=self.pdf)
        self.assertEqual(rc, 0, out)
        path = os.path.join(self.tmp, "body.eml")
        self.assertTrue(os.path.isfile(path))
        self.assertIn(path, out)
        self.assertIn("with your résumé attached", out)
        self.assertIn("Nothing is in your mailbox yet and nothing was sent", out)
        self.assertIn("Forward or", out)                      # the honest hedge, not a claim it opens editable
        self.assertIn("use the copy file", out)
        self.assertNotIn("draft created", out.lower())

    def test_without_a_resume_the_message_does_not_claim_one(self):
        rc, out = self.run_deliver("eml", "jane@example.test", "Hello", self.body)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("résumé attached", out)

    def test_a_missing_resume_file_writes_nothing_and_exits_7(self):
        rc, out = self.run_deliver("eml", "jane@example.test", "Hello", self.body,
                                   attach=os.path.join(self.tmp, "nope.pdf"))
        self.assertEqual(rc, 7, out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "body.eml")))
        self.assertIn("No draft was created and no file was written", out)

    def test_a_subject_the_mail_format_refuses_writes_nothing_and_says_where_the_note_is(self):
        rc, out = self.run_deliver("eml", "jane@example.test", "Hello\nBcc: evil@example.test", self.body)
        self.assertEqual(rc, 7, out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "body.eml")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "body.copy.txt")))    # nothing half-written is left
        self.assertIn(self.body, out)
        self.assertIn("press Send yourself", out)

    def test_an_unreadable_note_exits_7_with_the_path(self):
        rc, out = self.run_deliver("eml", "jane@example.test", "Hello", os.path.join(self.tmp, "gone.txt"))
        self.assertEqual(rc, 7, out)
        self.assertIn("gone.txt", out)


class WebLinkTests(Base):
    """The app's web compose links (build.py _MAIL_BASE, mailComposeUrl), not mailto: a mailto link did nothing in
    the Artifact viewer while the web compose page opened with the draft filled in (his probe, 2026-09-14)."""

    def test_the_gmail_link_is_built_the_way_the_app_builds_it(self):
        url, whole = md.build_compose_url("gmail", "jane@example.test", "Hello & hi", BODY)
        self.assertTrue(url.startswith("https://mail.google.com/mail/?view=cm&fs=1&to=jane%40example.test&su=Hello%20%26%20hi"), url)
        self.assertIn("&body=", url)
        self.assertIn("%0A", url)                      # line break
        self.assertIn("%C3%A9", url)                   # é
        self.assertNotIn("mailto", url)
        self.assertTrue(whole)

    def test_outlook_uses_subject_not_su(self):
        url, _whole = md.build_compose_url("outlook", "jane@example.test", "Hello", BODY)
        self.assertTrue(url.startswith("https://outlook.office.com/mail/deeplink/compose?to=jane%40example.test&subject=Hello"), url)
        self.assertNotIn("&su=", url)

    def test_only_a_real_address_goes_in_to(self):
        url, _ = md.build_compose_url("gmail", "the boss at Acme", "Hello", BODY)
        self.assertNotIn("to=", url)

    def test_a_long_note_keeps_the_body_out_and_says_to_paste_it(self):
        url, whole = md.build_compose_url("gmail", "jane@example.test", "Hello", "word " * 600)
        self.assertFalse(whole)
        self.assertNotIn("body=", url)
        self.assertLessEqual(len(url), md.MAIL_URL_MAX)
        with open(self.body, "w", encoding="utf-8") as fh:
            fh.write("word " * 600)
        rc, out = self.run_deliver("gmail-web", "jane@example.test", "Hello", self.body)
        self.assertEqual(rc, 0, out)
        self.assertIn("too long to fill in all the way, so the body stays out. Copy the body and", out)

    def test_gmail_delivery_makes_the_link_and_the_copy_file_but_no_eml(self):
        rc, out = self.run_deliver("gmail-web", "jane@example.test", "Hello", self.body, attach=self.pdf,
                                   bcc="b@example.test")
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "body.link.txt")))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "body.copy.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "body.eml")))
        self.assertIn("opens a new message in Gmail", out)
        self.assertIn("Nothing is in your mailbox yet and nothing was sent", out)
        self.assertIn("A link cannot carry a file", out)
        self.assertIn("Add the Bcc addresses yourself: b@example.test", out)
        self.assertIn("use the copy file", out)

    def test_outlook_delivery_offers_the_link_and_the_eml_both_hedged_with_the_apps_label(self):
        rc, out = self.run_deliver("outlook-web", "jane@example.test", "Hello", self.body, attach=self.pdf)
        self.assertEqual(rc, 0, out)
        for name in ("body.link.txt", "body.eml", "body.copy.txt"):
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, name)), name)
        self.assertIn("Not tried on this device yet. If nothing opens, use the copy steps below.", out)
        self.assertIn("Copy steps (open ", out)
        self.assertIn("Forward or Edit as New Message", out)

    def test_phone_delivery_is_a_copy_file_and_says_how_to_get_it_onto_the_phone(self):
        rc, out = self.run_deliver("copy", "jane@example.test", "Hello", self.body, attach=self.pdf)
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "body.copy.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "body.eml")))
        self.assertIn("AirDrop", out)
        text = open(os.path.join(self.tmp, "body.copy.txt"), encoding="utf-8").read()
        for part in ("── To ──", "── Subject ──", "── Body ──", self.pdf):
            self.assertIn(part, text)

    def test_mailto_is_gone(self):
        self.assertFalse(hasattr(md, "build_mailto"))
        with self.assertRaises(ValueError):
            md.resolve("mailto")


class ResolveTests(Base):
    def test_an_explicit_choice_beats_what_they_told_us_which_beats_detection(self):
        md.remember("gmail")
        self.assertEqual(md.resolve("eml")[0], "eml")
        self.assertEqual(md.resolve("")[0], "gmail-web")
        self.assertEqual(md.resolve("outlook")[0], "outlook-web")
        self.assertEqual(md.resolve("apple-mail")[0], "apple-mail")
        self.assertEqual(md.resolve("phone")[0], "copy")

    def test_the_app_five_are_the_client_list_and_the_two_aliases_are_accepted(self):
        self.assertEqual(list(md.CLIENTS), ["gmail", "outlook", "apple-mail", "phone", "other"])
        self.assertEqual(md.resolve("apple")[0], "apple-mail")          # the app's own key
        self.assertEqual(md.resolve("Thunderbird")[0], "eml")           # an alias for "other"
        md.remember("Thunderbird")
        self.assertEqual(md.remembered(), "other")

    def test_auto_is_a_file_on_a_machine_without_apple_mail(self):
        with mock.patch.object(platform, "system", return_value="Linux"):
            d, why = md.resolve("auto")
        self.assertEqual(d, "eml")
        self.assertIn("Linux", why)

    def test_auto_is_apple_mail_only_when_a_mac_has_osascript_and_mail_answers(self):
        good = self.stub_osascript(0)
        with mock.patch.object(platform, "system", return_value="Darwin"), \
                mock.patch.dict(os.environ, {"PATH": good + os.pathsep + os.environ["PATH"]}):
            self.assertEqual(md.resolve("")[0], "apple-mail")
        bad = self.stub_osascript(1)          # osascript exists but Mail does not answer
        with mock.patch.object(platform, "system", return_value="Darwin"), \
                mock.patch.dict(os.environ, {"PATH": bad + os.pathsep + os.environ["PATH"]}):
            d, why = md.resolve("")
        self.assertEqual(d, "eml")
        self.assertIn("Mail", why)

    def test_an_unknown_client_is_refused_by_name(self):
        with self.assertRaises(ValueError) as cm:
            md.resolve("pigeon")
        self.assertIn("pigeon", str(cm.exception))
        with self.assertRaises(ValueError):
            md.remember("pigeon")


class GuideTests(Base):
    def test_no_client_asks_which_one(self):
        text = "\n".join(md.guide(""))
        self.assertIn("Which mail do you use?", text)

    def test_remembering_a_client_is_kept_and_read_back(self):
        md.remember("Outlook")
        self.assertEqual(md.remembered(), "outlook")
        self.assertIn("Outlook", "\n".join(md.guide("")))

    def test_a_corrupt_state_file_is_just_not_asked_yet(self):
        os.makedirs(os.path.dirname(self._state), exist_ok=True)
        with open(self._state, "w") as fh:
            fh.write("{not json")
        self.assertEqual(md.remembered(), "")

    def test_every_guide_says_nothing_is_sent_or_that_you_press_send_and_tells_the_kit(self):
        for client in md.CLIENTS:
            with self.subTest(client=client):
                text = " ".join(md.guide(client))
                self.assertIn("Send", text)
                self.assertIn("tell the kit you sent it", text)
                self.assertNotIn("opens as a draft", text.lower())
                self.assertNotIn("mailto", text.lower())

    def test_the_gmail_guide_carries_his_caveat_and_the_outlook_guide_the_apps_label(self):
        self.assertIn(md.HEDGES["gmail"], " ".join(md.guide("gmail")))
        self.assertIn("likely, not yet checked", md.HEDGES["gmail"])
        self.assertIn(md.OUTLOOK_HEDGE, " ".join(md.guide("outlook")))

    def test_the_apple_mail_guide_says_why_it_differs_from_the_app(self):
        text = " ".join(md.guide("apple-mail"))
        self.assertIn("Why this differs from the app", text)
        self.assertIn("cannot control Mail", text)

    def test_the_guide_says_the_gates_still_run(self):
        self.assertIn("never skips a check", " ".join(md.guide("outlook")))


class SealTests(Base):
    """`--deliver` is not a route of its own: it refuses unless mail-draft.sh vouches for the call. Defense in depth,
    not proof (anything that can read the script can compute the token); it stops a hand-run `--deliver --open` from
    skipping every check and the send-log row."""

    def _cli(self, *args, env_extra=None):
        import subprocess
        env = dict(os.environ)
        env.pop("MAIL_DRAFT_GATED", None)
        env.update(env_extra or {})
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "mail_deliver.py"), "--deliver", *args],
                              capture_output=True, text=True, env=env, cwd=self.tmp)

    def test_a_direct_run_is_refused_and_writes_nothing(self):
        p = self._cli("gmail-web", "--to", "jane@example.test", "--subject", "Hello", "--body-file", self.body, "--open")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("only runs from mail-draft.sh", p.stdout)
        for name in ("body.link.txt", "body.copy.txt", "body.eml"):
            self.assertFalse(os.path.exists(os.path.join(self.tmp, name)), name)

    def test_a_wrong_token_is_refused_too(self):
        p = self._cli("eml", "--to", "jane@example.test", "--subject", "Hello", "--body-file", self.body,
                      env_extra={"MAIL_DRAFT_GATED": "0" * 64})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "body.eml")))

    def test_the_token_the_shell_computes_is_the_one_this_side_accepts(self):
        """The protocol mail-draft.sh uses: a token bound to the calling shell's pid, the note and the recipient."""
        import subprocess
        cmd = ('export MAIL_DRAFT_GATED="$(printf "%s" "gated:$$:$1:$2" | shasum -a 256 | cut -d" " -f1)"; '
               f'python3 "{SCRIPTS}/mail_deliver.py" --deliver eml --to "$2" --subject Hello --body-file "$1"; rc=$?; exit $rc')
        # (`; exit $rc` keeps bash from exec-ing python as its last command, which would change python's parent pid)
        p = subprocess.run(["bash", "-c", cmd, "x", self.body, "jane@example.test"], capture_output=True, text=True,
                           cwd=self.tmp)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "body.eml")))

    def test_the_other_commands_stay_open(self):
        import subprocess
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "mail_deliver.py"), "--guide", "outlook"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)


class CliTests(Base):
    def test_resolve_prints_delivery_bar_reason(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = md.main(["mail_deliver.py", "--resolve", "outlook"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip().split("|")[0], "outlook-web")

    def test_an_unknown_client_on_the_command_line_is_a_usage_error(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = md.main(["mail_deliver.py", "--resolve", "pigeon"])
        self.assertEqual(rc, 2)
        self.assertIn("pigeon", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
