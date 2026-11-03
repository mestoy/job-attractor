#!/usr/bin/env python3
"""mail_deliver.py: get the note (and the résumé) to somewhere the person can act on it, in ANY mail client.

mail-draft.sh runs every gate, then has to put the note somewhere. It used to know one place, Apple Mail,
through AppleScript, and when that failed it said so and behaved as if a draft existed. This is the part
that puts the note somewhere, so a person on Linux, or on Outlook, Thunderbird or Gmail, still gets it.

⛔ THIS IS NOT A SEND ROUTE AND IT IS NOT AN UNGATED ONE. mail-draft.sh calls it only AFTER the lint, the
dedup, the rung's evidence and the BUILD gate have passed, and it still writes the send-log row. Nothing
here sends anything. `--deliver` REFUSES to run unless mail-draft.sh vouches for the call with a token it
computes at that moment (see gate_token). That is DEFENSE IN DEPTH, NOT PROOF: anything that can read
mail-draft.sh or this file can compute the token. It stops a person or an agent from running
`mail_deliver.py --deliver ... --open` by hand and skipping every check and the send-log row; it does not stop
someone who is deliberately forging it. Every message says what exists and what does not, and never claims a draft was
created when it was not.

The five clients are the ones the app shows (app/design/phases/build.py): gmail, outlook, apple-mail,
phone, other ("apple" and "thunderbird" are accepted as aliases). What each gets:
  apple-mail  a real draft in Apple Mail through AppleScript (lives in mail-draft.sh; this module only decides
              whether it can work). The app cannot script Mail, so it gives copy steps instead; this can.
  gmail       a web compose link (Gmail in a browser tab, note filled in) plus a copy file. The app does the
              same, and its author's own probe found a mailto link does nothing in the Artifact viewer while
              this web link opened filled in. That probe was in the viewer, so from a terminal it is likely,
              not verified.
  outlook     the web compose link AND a .eml for desktop Outlook, both hedged with the shared file's own
              wording, plus the copy file.
  phone       a copy file, and how to get it onto the phone.
  other       a .eml (with `X-Unsent: 1`, which a client may or may not honor) plus the copy file.
The copy file (<note>.copy.txt) is the CLI's version of the app's three copy buttons: To, Subject, Body.

Usage (mail-draft.sh calls the first two):
  mail_deliver.py --resolve [client]                      -> "<delivery>|<why>"
  mail_deliver.py --deliver <delivery> --to A --subject S --body-file F [--bcc B] [--attach P] [--from X]
  mail_deliver.py --detect          what would be used here, and why (doctor.py shows this)
  mail_deliver.py --guide [client]  the exact steps for a client, including what this will NOT do
  mail_deliver.py --remember <client>  gmail | outlook | apple-mail | phone | other
Exit: 0 ok · 2 usage · 7 nothing usable was produced (the message says what to do instead)
Stdlib only. Writes only next to the note and under documents/state/mail-client.json.
"""
import json
import mimetypes
import os
import platform
import shutil
import subprocess
import sys
import urllib.parse
from email.message import EmailMessage

HERE = os.path.dirname(os.path.abspath(__file__))
# The install this script lives in, never the session root (CLAUDE_PROJECT_DIR): a session rooted elsewhere would save the client choice in a
# different folder (kit #156). Only an explicit JOBSEARCH_DATA_ROOT redirects.
REPO = os.path.abspath(os.environ.get("JOBSEARCH_DATA_ROOT") or os.path.dirname(HERE))
STATE_FILE = os.path.join(REPO, "documents", "state", "mail-client.json")

# ── ONE SOURCE: scripts/mail_clients.json ────────────────────────────────────────────────────────────
# The client list, labels, web compose bases, subject parameters, the link length limit, the shared hedges and
# sentences all live in that file and NOWHERE else (tests/test_mail_clients_single_source.py enforces it). They
# used to be constants here AND in the app's build.py, which could agree only by luck.
CLIENTS_FILE = os.path.join(HERE, "mail_clients.json")


def _load_clients():
    try:
        with open(CLIENTS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"⛔ scripts/mail_clients.json could not be read ({type(exc).__name__}). Run Sync Kit "
                         "again so the file arrives, then re-run this.")


_DATA = _load_clients()
# Deliveries: apple-mail (AppleScript, in mail-draft.sh) | eml | gmail-web | outlook-web | copy
DELIVERIES = tuple(dict.fromkeys(c["delivery"] for c in _DATA["clients"]))
# What the person uses -> how this delivers to it. The keys are the app's, so a person sees one list.
CLIENTS = {c["key"]: c["delivery"] for c in _DATA["clients"]}
CLIENT_LABELS = {c["key"]: c["label"] for c in _DATA["clients"]}
ALIASES = dict(_DATA["aliases"])
MAIL_BASE = {c["key"]: c["web"]["base"] for c in _DATA["clients"] if c.get("web")}
SUBJECT_PARAM = {c["key"]: c["web"]["subject_param"] for c in _DATA["clients"] if c.get("web")}
MAIL_URL_MAX = int(_DATA["url_max"])
HEDGES = {c["key"]: c["hedge"] for c in _DATA["clients"] if c.get("hedge")}
WHY_IT_DIFFERS = {c["key"]: c["why_it_differs"] for c in _DATA["clients"] if c.get("why_it_differs")}
STRINGS = dict(_DATA["strings"])
OUTLOOK_HEDGE = HEDGES["outlook"]
EXIT_NOTHING = 7
GATE_ENV = "MAIL_DRAFT_GATED"


def gate_token(ppid, body_file, to):
    """The vouch mail-draft.sh computes (sha256 of "gated:<its pid>:<note path>:<recipient>") and this side
    recomputes with its own parent pid. Defense in depth, not proof: see the module docstring."""
    import hashlib
    return hashlib.sha256(f"gated:{ppid}:{body_file}:{to}".encode("utf-8")).hexdigest()


def vouched(body_file, to):
    return os.environ.get(GATE_ENV, "") == gate_token(os.getppid(), body_file, to)


def _read_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def canonical(client):
    """A client name as the app spells it ('apple' and 'thunderbird' are accepted aliases), or ''."""
    c = str(client or "").strip().lower()
    c = ALIASES.get(c, c)
    return c if c in CLIENTS else ""


def remembered():
    """The client the person told us they use, or ''. Any read trouble is 'not asked yet', never an error."""
    return canonical(_read_state().get("client"))


def remember(client):
    c = canonical(client)
    if not c:
        raise ValueError(f"unknown client '{client}'. One of: {', '.join(CLIENTS)}")
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    import datetime
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"client": c, "delivery": CLIENTS[c], "asked": datetime.date.today().isoformat()}, fh, indent=2)
    os.replace(tmp, STATE_FILE)
    return c


def apple_mail_available():
    """(True, why) only when this is macOS, osascript exists and Mail answers. Otherwise (False, why not)."""
    if platform.system() != "Darwin":
        return False, f"this is {platform.system() or 'not macOS'}, and Apple Mail exists only on a Mac"
    if not shutil.which("osascript"):
        return False, "osascript was not found"
    try:
        p = subprocess.run(["osascript", "-e", 'id of application "Mail"'], capture_output=True,
                           text=True, timeout=8)
    except Exception as exc:
        return False, f"Mail did not answer ({type(exc).__name__})"
    return (True, "this is a Mac and Mail is installed") if p.returncode == 0 else (
        False, "Mail is not installed or did not answer")


def resolve(choice=""):
    """(delivery, why). Explicit choice beats what the person told us, which beats auto-detection."""
    choice = (choice or "").strip().lower()
    if choice and choice != "auto":
        if choice in DELIVERIES:
            return choice, "you chose it with --client"
        c = canonical(choice)
        if c:
            return CLIENTS[c], f"you said you use {CLIENT_LABELS[c]}"
        raise ValueError(f"unknown --client '{choice}'. One of: auto, {', '.join(CLIENTS)} "
                         f"(or a delivery: {', '.join(DELIVERIES)})")
    r = remembered()
    if r:
        return CLIENTS[r], f"you told us you use {CLIENT_LABELS[r]}"
    ok, why = apple_mail_available()
    if ok:
        return "apple-mail", f"chosen automatically: {why}"
    return "eml", f"chosen automatically, as a file: {why}"


# ── the deliveries this module makes ────────────────────────────────────────────────────────────────

def _stem(body_file):
    return os.path.splitext(os.path.abspath(body_file))[0]


def eml_path(body_file):
    return _stem(body_file) + ".eml"


def link_path(body_file):
    return _stem(body_file) + ".link.txt"


def copy_path(body_file):
    return _stem(body_file) + ".copy.txt"


def build_eml(to, subject, body, bcc="", attach="", from_addr=""):
    """The message as bytes. `X-Unsent: 1` is the header Outlook and Thunderbird read as "open for editing"."""
    m = EmailMessage()
    if from_addr:
        m["From"] = from_addr
    m["To"] = to
    if bcc:
        m["Bcc"] = bcc
    m["Subject"] = subject
    m["X-Unsent"] = "1"
    m.set_content(body)
    if attach:
        with open(attach, "rb") as fh:
            data = fh.read()
        ctype = mimetypes.guess_type(attach)[0] or "application/octet-stream"
        maintype, _, subtype = ctype.partition("/")
        m.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream",
                         filename=os.path.basename(attach))
    return m.as_bytes()


def build_compose_url(client, to, subject, body):
    """(url, whole). The web compose link, built the way the app builds it. Only a real address goes in To.
    Past MAIL_URL_MAX the body stays out (whole is False) and the person is told to paste it in."""
    base = MAIL_BASE[client]
    q = urllib.parse.quote
    parts = []
    if to and "@" in to[1:]:
        parts.append("to=" + q(to, safe=""))
    parts.append(SUBJECT_PARAM[client] + "=" + q(subject or "", safe=""))
    head = base + ("&" if "?" in base else "?") + "&".join(parts)
    full = head + "&body=" + q(body or "", safe="")
    return (full, True) if len(full) <= MAIL_URL_MAX else (head, False)


def build_copy_text(to, subject, body, bcc="", attach=""):
    """The CLI's three copy buttons: To, Subject, Body, each clearly separated, ready to select and copy."""
    lines = ["── To ──", to, "", "── Subject ──", subject, "", "── Body ──", body.rstrip("\n"), ""]
    if bcc:
        lines += ["── Bcc (add these yourself) ──", bcc, ""]
    if attach:
        lines += ["── Attach your résumé ──", attach, ""]
    return "\n".join(lines)


def _say(lines):
    for line in lines:
        print(line)


def _nothing(what, note_hint, extra=()):
    _say([f"⛔ No draft was created and {what}."] + list(extra) +
         [f"   Your note is still in {note_hint}: copy it into your mail program, attach your",
          "   résumé, and press Send yourself."])
    return EXIT_NOTHING


def _write(path, data, mode="w"):
    if mode == "wb":
        with open(path, "wb") as fh:
            fh.write(data)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data)


def _copy_steps(path):
    return [f"   Copy steps (open {path}):",
            "     1. Open your mail and start a new message.",
            "     2. Copy the To line from that file and paste it into To.",
            "     3. Copy the Subject and paste it into Subject.",
            "     4. Copy the Body and paste it into the message."]


def deliver(kind, to, subject, body_file, bcc="", attach="", from_addr="", opener=False):
    """Make the delivery and say exactly what now exists. Returns the exit code."""
    if kind not in DELIVERIES or kind == "apple-mail":
        _say([f"⛔ mail_deliver: cannot deliver by '{kind}' here."])
        return 2
    try:
        with open(body_file, encoding="utf-8") as fh:
            body = fh.read()
    except OSError as exc:
        return _nothing(f"no file was written: I could not read your note ({exc})", body_file)
    if attach and not os.path.isfile(attach):
        _say([f"⛔ No draft was created and no file was written: the résumé file is not there ({attach}).",
              "   Rebuild it or fix the path, then run this again."])
        return EXIT_NOTHING
    made, notes = [], []
    try:
        # the copy file first: every non-Apple delivery falls back to it
        _write(copy_path(body_file), build_copy_text(to, subject, body, bcc, attach))
        made.append(copy_path(body_file))
        if kind in ("eml", "outlook-web"):
            _write(eml_path(body_file), build_eml(to, subject, body, bcc, attach, from_addr), "wb")
            made.append(eml_path(body_file))
        web = {"gmail-web": "gmail", "outlook-web": "outlook"}.get(kind)
        url, whole = ("", True)
        if web:
            url, whole = build_compose_url(web, to, subject, body)
            _write(link_path(body_file), url + "\n")
            made.append(link_path(body_file))
    except Exception as exc:                      # a header the mail format refuses (a newline in the subject)
        for f in made:
            try:
                os.remove(f)
            except OSError:
                pass
        return _nothing(f"no file was written ({type(exc).__name__}: {exc})", body_file)
    cp = copy_path(body_file)
    if kind == "eml":
        _say([f"📄 I wrote your note to {eml_path(body_file)}" + (" with your résumé attached." if attach else "."),
              "   Nothing is in your mailbox yet and nothing was sent. Open that file in your mail program,",
              "   check it, and press Send yourself. If it opens as a message you cannot edit, use Forward or",
              f"   Edit as New Message. If your program cannot open it, use the copy file: {cp}"])
    elif kind == "copy":
        _say([f"📄 I wrote your note as text you can copy, in {cp}.",
              "   Nothing is in your mailbox yet and nothing was sent. Get that file onto your phone (AirDrop it,",
              "   or email it to yourself), open your mail app, start a new message and copy each part in."])
        _say(_copy_steps(cp))
    else:                                          # gmail-web | outlook-web
        name = CLIENT_LABELS[web]
        _say([f"🔗 I made a link that opens a new message in {name} (in your browser) with your note filled in.",
              f"   It is saved in {link_path(body_file)}. Nothing is in your mailbox yet and nothing was sent."])
        if web == "outlook":
            _say([f"   {OUTLOOK_HEDGE}",
                  f"   I also wrote {eml_path(body_file)} for desktop Outlook" + (" with your résumé attached." if attach else ".")
                  + " If it opens as a message you cannot edit, use Forward or Edit as New Message."])
            _say(_copy_steps(cp))
        else:
            _say([f"   {HEDGES['gmail']} If nothing opens, or the message comes up blank, use the copy file: {cp}"])
        if not whole:
            _say([f"   {STRINGS['too_long']} It is in {cp}."])
        if to and "@" not in to[1:]:
            _say([f"   The To line stays empty because that is not an address yet. {STRINGS['add_address']}"])
        if bcc:
            _say([f"   Add the Bcc addresses yourself: {bcc}"])
        if attach:
            _say([f"   A link cannot carry a file. Attach your résumé yourself: {attach}"])
        if opener:
            cmd = "open" if platform.system() == "Darwin" else "xdg-open"
            if shutil.which(cmd):
                subprocess.run([cmd, url], check=False)
                _say([f"   Opened it with {cmd}."])
            else:
                _say([f"   {cmd} was not found, so I did not open it. Paste the link from "
                      f"{link_path(body_file)} into your browser."])
        else:
            _say([f"   To open it: {'open' if platform.system() == 'Darwin' else 'xdg-open'} \"$(cat {link_path(body_file)})\""])
    return 0


def _send_line(client):
    h = STRINGS["send_head"]
    return f"Then: {h[0].lower() + h[1:]} in {CLIENT_LABELS[client]}, then tell the kit you sent it."


GUIDES = {
    "gmail": [
        "Gmail in a browser. mail-draft.sh makes a link that opens a new Gmail message in your browser with your",
        "note filled in, and a copy file for the parts.",
        HEDGES["gmail"] + " If nothing opens, or the message comes up blank, use the copy file.",
        _send_line("gmail"),
    ],
    "outlook": [
        "Outlook. mail-draft.sh makes a web link (Outlook in your browser) and, for desktop Outlook, a .eml file",
        "next to your note with your résumé inside it, plus a copy file for the parts.",
        HEDGES["outlook"],
        "If the .eml opens as a message you cannot edit, use Forward or Edit as New Message.",
        _send_line("outlook"),
    ],
    "apple-mail": [
        "Apple Mail. mail-draft.sh makes a real draft in Mail with your résumé attached. Nothing is sent: you",
        "open the draft, check it and press Send in Mail, then tell the kit you sent it.",
        "Why this differs from the app: " + WHY_IT_DIFFERS["apple-mail"],
        "The first time, macOS asks whether Terminal may control Mail. Click OK. If you clicked Don't Allow,",
        "open System Settings > Privacy & Security > Automation, find Terminal and turn on Mail.",
    ],
    "phone": [
        "On your phone. mail-draft.sh writes your note as text you can copy (a .copy.txt next to it). Get that",
        "file onto your phone (AirDrop it, or email it to yourself), open your mail app, start a new message and",
        "copy each part in. " + STRINGS["send_head"] + ", then tell the kit you sent it.",
    ],
    "other": [
        "Another mail program (Thunderbird and others). mail-draft.sh writes a .eml file next to your note with your",
        "résumé inside it, plus a copy file. Open the .eml in your program. If it shows as a message you cannot",
        "edit, use Forward or Edit as New Message. If it does not open, use the copy file: start a new message and",
        "copy each part in. " + STRINGS["send_head"] + ", then tell the kit you sent it.",
    ],
}


def guide(client=""):
    c = canonical(client) or remembered()
    if c not in GUIDES:
        return ["Which mail do you use?  " + " · ".join(CLIENTS),
                "Then run:  python3 scripts/mail_deliver.py --guide <that name>",
                "and to keep the answer:  python3 scripts/mail_deliver.py --remember <that name>"]
    return GUIDES[c] + ["", "This never sends anything, and it never skips a check: the lint, the dedup and the",
                        "rung's evidence still run first."]


def detect_line():
    d, why = resolve("")
    return f"mail-draft.sh will use: {d} ({why})"


def main(argv):
    a = argv[1:]
    if not a:
        print(__doc__)
        return 2

    def opt(name, default=""):
        return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default
    try:
        if a[0] == "--resolve":
            d, why = resolve(a[1] if len(a) > 1 else "")
            print(f"{d}|{why}")
            return 0
        if a[0] == "--detect":
            print(detect_line())
            return 0
        if a[0] == "--guide":
            print("\n".join(guide(a[1] if len(a) > 1 else "")))
            return 0
        if a[0] == "--remember":
            if len(a) < 2:
                print("usage: mail_deliver.py --remember <gmail|outlook|apple-mail|phone|other>")
                return 2
            c = remember(a[1])
            print(f"Noted: you use {CLIENT_LABELS[c]}. mail-draft.sh will deliver by {CLIENTS[c]}. "
                  f"(Saved in {os.path.relpath(STATE_FILE, REPO)}; change it any time.)")
            return 0
        if a[0] == "--deliver":
            if not vouched(opt("--body-file"), opt("--to")):
                print("⛔ Nothing was made. `mail_deliver.py --deliver` only runs from mail-draft.sh, after its checks")
                print("   (the lint, the dedup, the rung's evidence and the BUILD gate) and with the send recorded. Run")
                print("   scripts/mail-draft.sh instead, and use --client to choose where the draft goes.")
                return 2
            return deliver(a[1] if len(a) > 1 else "", opt("--to"), opt("--subject"), opt("--body-file"),
                           opt("--bcc"), opt("--attach"), opt("--from"), opener="--open" in a)
    except ValueError as exc:
        print(f"⛔ {exc}")
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
