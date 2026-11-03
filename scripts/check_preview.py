#!/usr/bin/env python3
"""check_preview.py — PreToolUse hook that lints AskUserQuestion text BEFORE the question renders.

Why: AskUserQuestion option labels/descriptions/PREVIEWS are written in YOUR voice, but the
send-time linter (check_outreach.py) only ever sees email *body* files — it never sees a
question's previews. That blind spot lets a banned filler word slip into the option text you
read and approve, over and over, because no manual "write-to-temp-and-lint" habit survives
under volume. This hook makes the scrub mechanical: it reads the PreToolUse payload, scans
every question/option string against the canonical BANNED list, and BLOCKS the tool call on a hit.

FAIL-OPEN by design: any parse/other error → exit 0 (allow). A hook bug must never brick your
questions. Only a real banned-word hit produces a block (exit 2, stderr fed back to the model).

Wired in .claude/settings.json as a PreToolUse hook matching AskUserQuestion.

BUILD GATE: vocabulary is only half the problem. The same hook fires on the tool call that
shows you drafted praise phrasings — including when that question arrives BEFORE any match
scorecard was ever presented and ruled on. Inspecting only VOCABULARY happily approves a
question that skipped the human decision entirely. So it also blocks drafted-outreach-voice
options unless the decision ledger holds a real BUILD ruling, written by the PostToolUse hook
(scripts/record_decision.py) from YOUR actual answer, which the assistant cannot forge.
"""
import sys, os, re, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger_keys as _lk
try:
    from kit_config import (VOICE_MARKERS, RULES_DOC,
                            LEDGER_PATH, LEDGER_KEYFILE)
except Exception:
    VOICE_MARKERS = ["yoursite.example"]
    RULES_DOC = "documents/WORKFLOW-RULES.md"
    LEDGER_PATH = os.environ.get("JOBKIT_LEDGER_PATH") or os.path.join("documents", "decision-ledger.jsonl")
    LEDGER_KEYFILE = os.environ.get("JOBKIT_LEDGER_KEYFILE") or "~/.jobsearch-ledger-key"

# NEWER SETTINGS, IMPORTED SEPARATELY AND ON PURPOSE. These arrived after the first kits shipped,
# so an existing install can have a kit_config.py that predates them. Folding them into the import
# above would mean one missing name makes the WHOLE import fail, silently dropping VOICE_MARKERS,
# RULES_DOC and the ledger path to their placeholder defaults — a gate that looks configured and
# is not. Each name degrades on its own instead.
try:
    from kit_config import OWNER_FIRST
except Exception:
    OWNER_FIRST = "You"
try:
    from kit_config import OWNER_SITE
except Exception:
    OWNER_SITE = "yoursite.example"
try:
    from kit_config import PROOF_POINTS
except Exception:
    PROOF_POINTS = []          # detector (b) simply stays off; (a), (c) and (d) still fire

# ⛔ The ledger of the install THIS script lives in, never CLAUDE_PROJECT_DIR (kit #121). mail-draft.sh
# imports this module from a session that may be rooted anywhere; see record_decision.INSTALL_ROOT.
LEDGER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), LEDGER_PATH)

# Markers that a question is carrying DRAFTED OUTREACH VOICE (a praise beat / hook / phrasing
# option), as opposed to an ordinary planning or scorecard question. Add your own recurring
# tics to VOICE_MARKERS in kit_config.py — the more of your voice is listed, the more reliably
# this tells a drafted message apart from an ordinary question.
#
# ⛔ VOICE_PATTERNS WAS REMOVED HERE, 2026-08-09 (BUG-104). It read:
#     VOICE_PATTERNS = [re.compile(p) for p in VOICE_MARKER_PATTERNS]
# and it was DEAD CODE: defined, never referenced by anything, while a test in tests/test_gates.py
# asserted against it. The live gate is `VOICE_MARKERS`, the substring check in
# _carries_drafted_voice() below. Main removed this on 2026-07-20 and the partner tree did not, so
# for three weeks only PARTNERS carried it. That drift is the real defect here.
#
# 🔴 THE SECOND HALF IS WORSE THAN THE DEAD CODE, and it is why the config knob went too.
# `re.compile(p)` passed no flags, so a `$` in any user pattern anchored to end-of-STRING rather
# than end-of-line. A partner's markers `"Jane,"` and `"Best,"` matched only when the entire input
# WAS that line, so on every real multi-line draft both were inert and the check reported clean.
# ⚖️ A GATE THAT PASSES BY NEVER FIRING IS THE WORST SHAPE, in the words of the partner who reported
# it upstream. It is not a weak gate, it is a gate-shaped hole, and it reads green.
#
# ⚖️ WHY THE KNOB WAS RETIRED TOO rather than rewired with `re.M`. Once this list is gone nothing
# reads `kit_config.VOICE_MARKER_PATTERNS`, and shipping a config setting that changes nothing is
# the same silent-degrader class the kit already carries three of: it invites a user to tune their
# voice detection and quietly does nothing with it. Deleting both leaves ONE mechanism, VOICE_MARKERS,
# which is a plain substring list a person can reason about.
#
# ⛔ IF THE PATTERN PATH EVER COMES BACK: compile with `re.M`, and have its test assert the RULE
# (an `[A-Z]` anchor must not be defeated by a blanket `re.I`) against whatever patterns the USER
# configured, never against the kit's own greeting vocabulary. The old test asserted "Hi, Jane!",
# which fails for every user whose outreach style differs from the default, which is the entire
# purpose of the knob.

def _build_rulings():
    """Companies with a VALID, MAC-authenticated BUILD ruling from the human.

    A first cut of this gate had two holes, both worth knowing because they are easy to
    reintroduce:
      1. Any line in the ledger was trusted, so the agent could simply append a BUILD row
         with the Write tool — the same self-attestation problem that makes
         `--lacivita-check pass` worthless.
      2. It FAILED OPEN on a read error, so corrupting or removing the ledger OPENED the gate.
         An evidence file that is easier to destroy than to satisfy is not a gate.
    Now: rows must carry a valid HMAC written by the PostToolUse hook using a key stored
    OUTSIDE the repo, and any read failure FAILS CLOSED.

    Honest limit: this is tamper-EVIDENT, not tamper-PROOF. Anything with shell access can
    always rewrite local key material. The point is that the honest path stays trivial while
    the dishonest path becomes deliberate, multi-step, and visible in the diff.
    """
    found = set()
    if not os.path.exists(LEDGER):
        return found  # fail CLOSED: no evidence means no authorization
    try:
        with open(LEDGER, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:
        return found  # fail CLOSED
    mac_ok = _ledger_verifier()
    if mac_ok is None:
        # KEY-DOWNGRADE FIXED: the check used to be `if key and not _mac_ok(...)`, so an absent,
        # empty or unreadable key SKIPPED signature verification entirely instead of failing
        # closed. One `rm` of the key file restored full forgeability, silently. No key means no
        # verifiable evidence means no authorization. A deleted install key is recreated fresh,
        # and nothing signed under the old one verifies under the new one.
        return found
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        # BOTH hook sources count. record_chat_ruling.py (UserPromptSubmit) writes
        # source="userpromptsubmit-hook" for a ruling you type in chat rather than click, and this
        # reader used to accept only the PostToolUse source, so every chat-typed approval was
        # signed, stored, and then ignored by the gate that exists to read it. The two shipped
        # scripts disagreed, and the visible symptom was the gate blocking work you had plainly
        # authorized. Keep this list in sync with every writer that ships.
        if row.get("ruling") != "BUILD" or row.get("source") not in (
                "posttooluse-hook", "userpromptsubmit-hook"):
            continue
        if not mac_ok(row):
            continue  # forged, tampered, or signed in ANOTHER install
        if _lk.row_is_peer_minted(row):
            continue  # minted from another session's message or harness text: the row stays as history and authorizes nothing
        co = (row.get("company") or "").strip().lower()
        if not co:
            # SKELETON-KEY FIXED: a BUILD row with no parseable company used to authorize EVERY
            # question, globally and permanently, because the caller fell back to "cannot scope,
            # allow". An unscoped ruling now authorizes NOTHING. A ruling must name what it
            # authorizes, or it is not a ruling.
            continue
        found.add(co)
    return found


def _ledger_verifier():
    """THIS install's MAC check (record_decision.ledger_verifier), or None, which fails CLOSED.

    kit #121: the key is per install and outside every install; rows signed with the pre-#121
    per-HOME key (LEDGER_KEYFILE) verify only through this install's tagged legacy snapshot.
    """
    try:
        import record_decision as _rd
        # Security review L5: name THIS install explicitly. Run as a hook through a symlinked script,
        # Python resolves the symlink for sys.path[0], so record_decision's own INSTALL_ROOT can be
        # the link TARGET's install while LEDGER (above) is this one.
        return _rd.ledger_verifier(LEDGER, legacy_keyfile=LEDGER_KEYFILE,
                                   root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except Exception:
        return None


def gate_empty_reason():
    """WHY the BUILD gate has nothing, in one sentence. NEVER an empty string.

    ⛔ K3. `_build_rulings()` returns an empty set for several different reasons and every one of them used
    to reach the person as the same sentence, "no valid BUILD ruling recorded". On a fresh install the truth
    is "you have not made a ruling yet", which is normal. Ordered from the cheapest thing to check to the
    most specific, so the first true cause wins. The key story is THIS install's key (signing merge,
    2026-10-03): there is one verifier, and the diagnosis reads the same one.
    """
    if not os.path.exists(LEDGER):
        return ("There is no ledger yet (%s). On a new install that is normal: a BUILD ruling is "
                "recorded the first time you make one." % LEDGER)
    try:
        with open(LEDGER, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except Exception as exc:
        return ("The ledger at %s could not be read (%s), so nothing can be authorized. Fix the "
                "file or its permissions." % (LEDGER, type(exc).__name__))
    if not raw.strip():
        return ("The ledger at %s is empty, so it holds no BUILD rulings yet." % LEDGER)
    specific = build_ruling_diagnosis()
    if specific:
        return specific
    rows = [ln for ln in raw.splitlines() if ln.strip()]
    if not _build_rulings():
        return ("The ledger at %s holds %d row(s) and no BUILD ruling this install can use. Either "
                "none is a BUILD, or none names a company." % (LEDGER, len(rows)))
    return ("The ledger at %s holds usable BUILD rulings; none of them names the company in this "
            "question." % LEDGER)


def build_ruling_diagnosis(company=None):
    """"" when the ledger holds no hook-written BUILD row that needs explaining (the plain "no ruling
    recorded" is then true). Otherwise a sentence that names the REAL cause, in terms of THIS install's key:
    the rulings are there, the key is not, or they were signed in another install, or they were recorded
    unsigned and authorize nothing. Asks the one verifier the gate asks (record_decision.ledger_verifier)."""
    try:
        import record_decision as _rd
        rows = []
        with open(LEDGER, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if (isinstance(r, dict) and r.get("ruling") == "BUILD"
                        and r.get("source") in ("posttooluse-hook", "userpromptsubmit-hook")):
                    rows.append(r)
        unsigned = [r for r in rows if not str(r.get("mac", "")).strip()]
        signed = [r for r in rows if str(r.get("mac", "")).strip()]
        status, why, fix = _rd.key_status(root=_install_root())
        if status != "ok" and signed:
            return ("%d signed BUILD rulings exist but this install's signing key is %s: %s. This is a KEY "
                    "problem, not a missing ruling. Fix: %s" % (len(signed), status, why, fix))
        mac_ok = _ledger_verifier()
        ok = sum(1 for r in signed if mac_ok is not None and mac_ok(r))
        if signed and ok == 0:
            return ("%d signed BUILD rulings exist but none verify in this install. They were signed in "
                    "another install, or under a key this install never snapshotted. This is a KEY "
                    "problem, not a missing ruling. If they came from before the kit #121 update, restore "
                    "~/.jobsearch-ledger-key from your backup, then run: python3 scripts/record_decision.py "
                    "--migrate" % len(signed))
        if signed and ok < len(signed):
            return ("%d of %d signed BUILD rulings verify in this install; the other %d were signed in "
                    "another install or under a key this install never snapshotted."
                    % (ok, len(signed), len(signed) - ok))
        if unsigned and not signed:
            return ("%d BUILD rulings were recorded UNSIGNED because this install had no usable signing key "
                    "at the time. They are a record only and authorize nothing. Run: python3 "
                    "scripts/record_decision.py --migrate, then give the ruling again." % len(unsigned))
        return ""
    except Exception:
        return ""


def _install_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _unscoped_build_row(company):
    """First signed BUILD_EXACT row that does NOT authorize `company` (blank or a different one).

    kit #54 fix 3: tells "a ruling exists but isn't scoped here" apart from "no ruling at all".
    """
    try:
        from record_decision import BUILD_EXACT, _norm
    except Exception:
        return None
    co = (company or "").strip().lower()
    if not os.path.exists(LEDGER):
        return None
    mac_ok = _ledger_verifier()
    if mac_ok is None:
        return None
    try:
        lines = open(LEDGER, "r", encoding="utf-8").readlines()
    except Exception:
        return None
    _bounded = lambda a, b: re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", b)
    for line in lines:
        try:
            row = json.loads(line.strip() or "{}")
        except Exception:
            continue
        if (row.get("source") not in ("posttooluse-hook", "userpromptsubmit-hook")
                or _norm(row.get("answer", "")) not in BUILD_EXACT or not mac_ok(row)):
            continue
        rc = (row.get("company") or "").strip().lower()
        if not (rc and co and (_bounded(rc, co) or _bounded(co, rc))):
            return row  # doesn't authorize `company` — this is the unscoped/mismatched row
    return None


_BOSS_PREP_RE = re.compile(r"^(.*?)\b(?:at|for|on)\s+(.+)$")


def _company_tail(co):
    """The part of a ruling's stored company AFTER a boss-then-company preposition ('at'/'for'/
    'on'), or `co` unchanged if none is present (kit#54).

    A row's `company` field is `extract_company()`'s output, and that function's own job is to
    pull a company out of prose that also names a boss ("<boss> at <company>") — so the stored
    value is routinely a boss+company composite, not a bare company name. `_has_build_ruling`
    used to require that WHOLE composite string, verbatim, inside a LATER picker's question text,
    and a later stage rarely repeats the boss's name once it has moved on to a different beat.
    Reported live (a partner, issue #54): a ruling for "<boss> at <company>" read as unscoped
    against a question that named only the company, though the send-time gate (which matches
    against the real --company argument, not question prose) accepted the same row without
    complaint.
    """
    m = _BOSS_PREP_RE.search(co)
    return m.group(2).strip() if m else co


def _company_prefix(co):
    """The part of a ruling's stored company BEFORE the same preposition `_company_tail` splits
    on, or "" if there is none. The tail is only trusted when THIS resolves to a real contact —
    see `_provable_boss_prefix`."""
    m = _BOSS_PREP_RE.search(co)
    return m.group(1).strip() if m else ""


def _provable_boss_prefix(question_text, prefix):
    """True when `prefix` is a name the ledger row's OWN question text already resolves to a
    contact the closeness store knows — not merely a word that happened to sit before "at/for/on".

    kit#54 follow-up (29's review, PROXY P8, 2026-09-22): the first version of the tail split
    trusted ANY text before "at/for/on" as a boss, so a company whose own real name contains one
    of those words ("Compassion for Kids") produced a tail ("Kids") that then authorized an
    unrelated company ("Kids Alliance Network") — a new skeleton key, reproduced end to end by
    29. A tail is now trusted only when its prefix is PROVABLY the boss: it must resolve, via
    the row's own recorded question, to a name the closeness store already carries as a contact.
    Fails closed (False) on any missing store, import error, or non-match — the tail is then not
    tried, same as if `_company_tail` had never split it.
    """
    try:
        import closeness
        from record_decision import extract_person
    except Exception:
        return False
    store = closeness.load()
    if not store:
        return False
    name = extract_person([question_text], store)
    if not name:
        return False
    return closeness.normalize_name(name) == closeness.normalize_name(prefix)


def _build_ruling_questions():
    """{ruling's stored company (lowercased, as `_build_rulings()` keys it) -> that row's own
    `question` text, CASE-PRESERVED}, for every valid signed BUILD row. `_build_rulings()`
    itself discards both the case and the question text once it has the key, and the primary
    authorization check never needs either — this exists only to give `_provable_boss_prefix`
    real prose to resolve a boss's name against (kit#54 follow-up)."""
    out = {}
    mac_ok = _ledger_verifier()
    if mac_ok is None or not os.path.exists(LEDGER):
        return out
    try:
        from record_decision import BUILD_EXACT, _norm
    except Exception:
        return out
    try:
        lines = open(LEDGER, "r", encoding="utf-8").readlines()
    except Exception:
        return out
    for line in lines:
        try:
            row = json.loads(line.strip() or "{}")
        except Exception:
            continue
        if (row.get("source") not in ("posttooluse-hook", "userpromptsubmit-hook")
                or _norm(row.get("answer", "")) not in BUILD_EXACT or not mac_ok(row)):
            continue
        co = (row.get("company") or "").strip().lower()
        if co:
            out[co] = str(row.get("question", ""))
    return out


def _has_build_ruling(tool_input=None):
    """Is there a valid BUILD ruling that plausibly covers THIS question?

    Scoping runs in the reliable direction: instead of parsing a company OUT of the question
    (which tends to grab the recipient's personal name, e.g. "…to Jane Doe", and then
    false-blocks a genuine ruling),
    check whether any AUTHORIZED company name appears IN the question text.
    """
    rulings = _build_rulings()  # already excludes unscoped (company-less) rows
    if not rulings:
        # No valid, company-scoped BUILD ruling exists, so nothing is authorized. The old
        # fallback here was `return True` ("cannot scope, allow"), which was the skeleton key:
        # one ruling with an unparseable company opened the gate globally and permanently.
        return False
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {})).lower()

    def _matches(co):
        # WORD-BOUNDARY match, not a bare substring. A substring test lets a short authorized name
        # authorize an unrelated longer one: BUILD("Ad") would open a question about "Adobe", and
        # a ruling for "Alpha" would open one about "Alphabet Systems".
        return re.search(r"(?<![a-z0-9])" + re.escape(co) + r"(?![a-z0-9])", blob) is not None

    questions = None
    for co in rulings:
        if _matches(co):
            return True
        tail = _company_tail(co)
        if tail == co:
            continue
        prefix = _company_prefix(co)
        # kit#54, narrowed by the follow-up: the tail is tried ONLY when its prefix is provably
        # the boss (a contact the row's own question resolves against the closeness store), never
        # merely because some text sat before "at/for/on" — that was the skeleton key 29 found.
        if not prefix:
            continue
        if questions is None:
            questions = _build_ruling_questions()
        qtext = questions.get(co, "")
        if qtext and _provable_boss_prefix(qtext, prefix) and _matches(tail):
            return True
    return False

def _no_boss_rung_lead(tool_input):
    """A rung-aware LEAD for the BUILD-gate refusal, naming the exemption marker for THIS shape.

    The refusal below prescribes a Boss Match Scorecard, which has NO valid inputs at a warm,
    rung-1-2, referral, inbound or application shape (no boss, no company to screen, no lane,
    nothing for the live-role verify to check). Without this, the operator is handed an impossible
    instruction and has to read this file to find the marker that is the actual escape hatch.

    This detects the shape of the blocked question and returns a short banner that LEADS with the
    applicable marker(s). It is ADVISORY COPY ONLY — it authorizes nothing, matches no store, and
    every real exemption is still gated by its own non-forgeable anchor above. When no no-boss shape
    is recognized it returns "" and the enumeration below (which names all six markers) still stands.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    low = blob.lower()
    hits = []  # (marker, one-line remedy), most-specific shape first
    _greets_a_name = re.search(
        r"(?:^|[\n\r>\"'“]|\s)(?i:hi|hey|hello|dear|greetings|good morning|good afternoon)"
        r"(?:[ \t]*,[ \t]*|[ \t]+)(?i:there(?:[ \t]*,[ \t]*|[ \t]+))?[A-Z][a-z]+", blob)
    if re.search(r"\breferr|\bintroduc|\bvia\b|\bintro\b", low):
        hits.append(("REFERRED: <Contact> VIA <Introducer>",
                     "a rung 8/9 referral is 2nd-degree and has no scorecard; the INTRODUCER must "
                     "appear in documents/warm-network.md."))
    if re.search(r"\brung ?1\b|\brung ?1-2\b|\brung ?2\b|zero-ask|zero ask|common (?:interest|ground)"
                 r"|connect(?:ion)? note|peer note", low):
        hits.append(("RUNG12: <Full Name>",
                     "a rung 1-2 zero-ask connect note to a 1st-degree contact (contact.jsonl or the "
                     "newest Connections-*.csv) with no ask vocabulary needs no BUILD ruling."))
    if re.search(r"follow(?:[ -]?up| ?ing up)|floating .* back|bump(?:ing)? (?:the|my|it)", low):
        hits.append(("FOLLOWUP: <Company>",
                     "a follow-up to a company already SENT in outreach_log.md carries its first "
                     "send's ruling; it needs no fresh one."))
    if re.search(r"\breply\b|\breplied\b|inbound|wrote to (?:me|him)|reached out to (?:me|him)"
                 r"|recruiter|unsolicited", low):
        hits.append(("INBOUND: <Full Name>",
                     "replying to someone who wrote to you first has no campaign; the person must "
                     "appear in an INBOUND header in documents/correspondence-log.md. Missing? "
                     "capture the inbound verbatim first, then re-ask."))
    if re.search(r"screening|free.response|interview (?:story|answer)|application (?:answer|question)"
                 r"|applying\b", low):
        hits.append(("APPLYING: <Company>",
                     "co-creating application/interview content for a role in flight has no boss; the "
                     "company needs a folder under documents/applications/ holding a real artifact."))
    if _greets_a_name or re.search(r"\bwarm(?:[ -]rung)?\b|\bconnector\b", low):
        hits.insert(0, ("WARM-RUNG: <Full Name>",
                        "a rung 5/6/7 warm ask has no boss and no scorecard; the name must appear in "
                        "documents/warm-network.md AND carry a warm-sanctioned tier in "
                        "documents/contact-closeness.json."))
    if not hits:
        return ""
    seen, lines = set(), []
    for marker, remedy in hits:
        if marker in seen:
            continue
        seen.add(marker)
        lines.append(f"     · `{marker}` — {remedy}")
    return ("⛔ THIS BLOCK LOOKS LIKE A NO-BOSS RUNG. The Boss Match Scorecard the message below "
            "prescribes has no valid inputs here (no boss, no company to screen, no lane). Use the "
            "exemption marker for your shape instead:\n" + "\n".join(lines))


def _carries_drafted_voice(tool_input):
    """Does this question show text written in YOUR voice for an outreach message?

    ⚠️ Do NOT "simplify" this back into a scoring loop. It was one, and the count was the defect:
    a marker-counting version needing >=2 hits from a fixed vocabulary was red-teamed twice and
    lost both times — five trivial bypasses, then THIRTEEN more, most of them one character from a
    case that already blocked ("Hi Dana." for "Hi, Dana!", a curly apostrophe in "can't", calling
    it an "opener"). Enumerating what drafted voice looks like is a losing game, because the writer
    picks the words. Enumerate SHAPES instead.

    A later over-correction made LENGTH a primary trigger, which blocked ordinary planning
    questions: a praise beat cannot be written in 40 characters, but neither can a good
    explanation, and a gate that punishes clear explanation trains the wrong behavior.

    Current rule: only STRONG signals fire, and any ONE of them is decisive.
      (a) a greeting addressed to a name
      (b) a first-person credential claim tied to one of YOUR proof points (kit_config.PROOF_POINTS)
      (c) a voice marker (kit_config.VOICE_MARKERS)
      (d) the structure of a finished message: a sign-off over your name
    The WEAK vocabulary (praise/phrasing/beat/angle/hook) DESCRIBES outreach as readily as it
    constitutes it, so it never fires alone at any length. Length may amplify a strong signal; it
    may never promote a weak one. That is why VOICE_PATTERNS is no longer part of the decision.

    Honest limit: this hook only ever sees `tool_input`. Drafted text rendered directly into the
    chat message is invisible to it. That path is covered at the send boundary instead
    (mail-draft.sh BUILD gate), which is the irreversible step and the one that matters.
    """
    fields = list(_strings_from_questions(tool_input))
    # JOIN ON NEWLINES, NOT SPACES. Detector (a) requires a greeting to sit at a line start, a
    # quote, or a double space. A single-space join puts every field after the first into mid-line
    # position, so the greeting detector matches ONLY when the greeting is the very first string in
    # the payload. A real AskUserQuestion always carries `question` before any option, so in
    # production it is never first: "Hi, Dana!" as an option label sails through while the identical
    # text as a bare question blocks. The matcher was correct; the assembly upstream defeated it.
    blob = "\n".join(str(t) for _, t in fields)
    # Normalize curly quotes so a smart-quote paste cannot dodge the ASCII markers.
    low = blob.lower().replace("’", "'").replace("‘", "'")

    # (a) A GREETING ADDRESSED TO A NAME. Greeting word, optional "there", required separator,
    # then a capitalized name of one or two words, then any punctuation or a line break. The
    # separator is REQUIRED (see _GREETING_TO_NAME_RE's own comment): without it, a CamelCase
    # company name that merely starts with a greeting word ("HeyGen", "DearDoc") parses as a
    # greeting addressed to a person, so a real cold-boss company name can false-positive block.
    if re.search(_GREETING_TO_NAME_RE, blob, re.M):
        # Addressing YOU is not drafted outreach — that is the assistant talking to you.
        #
        # Two bugs to keep fixed here. (1) `re.I` must NOT apply to the name anchor: "hi" matches
        # inside "W-hi-ch", and a case-insensitive [A-Z] then captures "ch", so any question
        # containing "Which" fails the exemption and blocks. Keep the greeting keyword loose via an
        # inline group, but require a REAL capital for the name. (2) Collect EVERY addressed name,
        # not the first: "Hi, Dana! … Hi, You!" must block, and "Hi, You! … Hi, Dana!" must not pass.
        # The SAME required separator as the detector above -- these two patterns must agree, or
        # the position-dependence the separator fix closed reopens on this line alone.
        addressed = re.findall(
            r"(?i:hi|hey|hello|dear|morning|good morning)"
            r"(?:[ \t]*,[ \t]*|[ \t]+)([A-Z][a-z]+)", blob)
        SELF = {p.lower() for p in str(OWNER_FIRST).split()} | {"you"}
        if not (addressed and all(n.lower() in SELF for n in addressed)):
            return True

    # (b) A FIRST-PERSON CREDENTIAL CLAIM tied to one of YOUR proof points. Subject may be "I",
    #     "I've", "I have", or "my <noun>"; the verb list is open-ended because the proof point is
    #     the part that makes it your voice. Disabled when PROOF_POINTS is empty (see kit_config).
    _proofs = [p for p in (PROOF_POINTS or []) if str(p).strip()]
    if _proofs and re.search(r"\b(?:i|i'?ve|i have|my [a-z]{3,14})\b[^.!?]{0,80}?"
                             r"(?:" + "|".join(_proofs) + r")", low):
        return True

    # (c) A VOICE MARKER (your recurring tics / your site).
    if any(m in low for m in VOICE_MARKERS):
        return True

    # (d) STRUCTURE OF A FINISHED MESSAGE: a sign-off over your name, whatever the words above it.
    #     The one evasion that carried no tic at all was still a complete email — greeting, body,
    #     name. Built from OWNER_FIRST/OWNER_SITE so it travels with the recipient's identity.
    _first = re.escape(str(OWNER_FIRST).strip().split()[0]) if str(OWNER_FIRST).strip() else "you"
    _site = re.escape(str(OWNER_SITE).strip().lower())
    if re.search(r"(?:^|\n)[ \t]*(?:thanks|cheers|best|talk soon|let'?s talk)[ \t]*[,.!]?[ \t]*\n"
                 r"[ \t]*" + _first + r"\b", blob, re.I) or \
       re.search(r"\n[ \t]*" + _first.lower() + r"[ \t]*\n[ \t]*" + _site, low):
        return True
    return False

def _load_lists():
    """Return (BANNED, banned_hit). The MATCHER travels with the list on purpose.

    BANNED carries no-slop words, a dozen of which double as employer names. A preview names the
    target company in nearly every option you see,
    so a bare lowercase regex here would block the very question that ASKS you about a company
    whose name happens to be a banned word.
    banned_hit() carries the proper-noun logic; importing the list without it is the bug this
    signature exists to prevent.
    """
    try:
        from check_outreach import BANNED, banned_hit
        return BANNED, banned_hit
    except Exception as _e:
        # ⚠️ SILENT UNTIL 2026-09-12, same shape found (and fixed) in verify_resume.py and
        # check_style.py: a failed import fell back to a small hand-copied word list with no
        # announcement anywhere. Kept FAIL OPEN on purpose -- this gate can BLOCK the AskUserQuestion
        # tool call outright (sys.exit(2) below), and every picker in the whole operating model runs
        # through it, so turning a degraded vocabulary into a permanent block would freeze every
        # picker rather than just weaken one check. Loud instead: an immediate stderr print, without
        # wedging the picker gate the way a hard fail here would.
        print(f"⚠️  check_preview: check_outreach did not import ({type(_e).__name__}: {_e}); "
              f"scanning AskUserQuestion previews against a 16-word fallback, not the live list",
              file=sys.stderr)
        fallback = ["actually", "honestly", "genuinely", "simply", "really", "exactly", "exact",
                    "leverage", "delve", "seamless", "robust", "passionate", "proven track record",
                    "tapestry", "testament", "in today's fast-paced", "that's the beauty of"]
        return fallback, (lambda body, w: bool(
            re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", body.lower())))

def _strings_from_questions(tool_input):
    """Yield (field_label, text) for every human-visible string in the AskUserQuestion payload."""
    for qi, q in enumerate(tool_input.get("questions", []) or []):
        if isinstance(q, dict):
            if q.get("question"): yield (f"q{qi+1}.question", q["question"])
            if q.get("header"):   yield (f"q{qi+1}.header", q["header"])
            for oi, o in enumerate(q.get("options", []) or []):
                if isinstance(o, dict):
                    for k in ("label", "description", "preview"):
                        if o.get(k): yield (f"q{qi+1}.opt{oi+1}.{k}", o[k])

def _data_root():
    """The install this script lives in; only an explicit JOBSEARCH_DATA_ROOT redirects (a harness sets it). Never the session root,
    CLAUDE_PROJECT_DIR: a session rooted elsewhere would read a different folder's stores (kit #156)."""
    return os.path.abspath(os.environ.get("JOBSEARCH_DATA_ROOT")
                           or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _roster_names_blob():
    """Lowercased text containing ONLY contact NAMES from documents/warm-network.md.

    The warm/referral exemptions anchor on the named person being a real 1st-degree contact, so we
    match NAMES only — never the whole file, which also holds Title/Company columns and prose.
    Otherwise a cold draft labeled `WARM-RUNG: Product Manager` (a Title cell) would satisfy the
    anchor and bypass the BUILD gate. Names come from two NAME-only sources:
      (1) the 'Name' column of every markdown table (located by its header), and
      (2) the 'Full 1st-degree roster' section (parse_network.py joins 'First Last' with two spaces).
    Fails closed (returns '') on any error.
    """
    try:
        repo = _data_root()
        with open(os.path.join(repo, "documents", "warm-network.md"),
                  encoding="utf-8", errors="ignore") as fh:
            src = fh.read()
    except Exception:
        return ""
    names = []
    m = re.search(r"^##\s+Full 1st-degree roster\b(.*)\Z", src, flags=re.M | re.S)
    if m:
        names.append(m.group(1))
    name_col = None
    for line in src.splitlines():
        if not line.lstrip().startswith("|"):
            name_col = None
            continue
        if set(line.strip()) <= set("|-: "):   # separator row |---|---|
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        low = [c.lower() for c in cells]
        if "name" in low:                       # header row: locate this table's Name column
            name_col = low.index("name")
            continue
        if name_col is not None and len(cells) > name_col:
            names.append(cells[name_col])
    return " \n ".join(names).lower()


def _name_in_roster(name, roster_low):
    """Word-bounded, prefix-fallback membership test of a captured NAME in the roster blob.

    Try the full capture, then progressively shorter leading prefixes down to TWO words (never a
    lone first name, which would collide with every contact who shares it), each matched
    WORD-BOUNDED so a short name cannot match inside a longer one. The fallback also lets
    `WARM-RUNG: Jane Doe Rung-6` resolve to "Jane Doe" when a stray Capitalized token trails the
    name. Requires >=5 alphanumerics so a lone initial cannot pass. Fails closed on empty roster.
    """
    if not roster_low:
        return False
    words = name.split()
    candidates = [" ".join(words[:k]) for k in range(len(words), 1, -1)]  # down to 2 words
    candidates = [c for c in candidates if len(re.sub(r"[^a-z0-9]", "", c.lower())) >= 5]
    for c in candidates:
        if re.search(r"(?<![a-z0-9])" + re.escape(c.lower()) + r"(?![a-z0-9])", roster_low):
            return True
    return False


# Refusal detail collected by the closeness consult below, so the block message can name the
# sanctioned ask and the one-command fix instead of a generic "gate not passed".
_CLOSENESS_REFUSALS = []


def _name_key(s):
    """Normalize a person's name so a credential or title suffix cannot defeat the match.

    🔴 THE DEFECT (2026-08-02). This matcher compared full names with `==`, and LinkedIn's export
    stores whatever the person typed into the surname field. a contact's row reads
    `First Name: Jane`, `Last Name: "Doe, COO"`, so the recorded full name is `Jane Doe, COO`.
    The RUNG12 marker regex above stops at a comma, so it can only ever emit `Jane Doe` — a
    string this function could never match. **The exemption was unreachable for that contact by
    construction**, and the picker blocked a legitimate rung 1-2 note three times.

    This is not one contact. A real export is full of suffixed surnames — `, MBA`, `, PMP®`,
    `, PhD`, `, CSPO`, `♕ [L.I.O.N.] ✔` — and every one of them had the same hole. Same family as
    `rank_criteria._cokey_joins`: two stores spelling one identity differently,
    joined by an equality test that only works when the spellings happen to agree.

    Drops anything after the first comma (the suffix field), bracketed decorations, and every
    non-alphanumeric character, then collapses whitespace. Deliberately NOT fuzzy beyond that: it
    still requires the same given and family name, so it cannot merge two different people.
    """
    s = str(s or "").lower()
    s = s.split(",")[0]                          # ", COO" / ", MBA" / ", PMP®"
    s = re.sub(r"[\[\(].*?[\]\)]", " ", s)       # "[L.I.O.N.]" / "(he/him)"
    s = re.sub(r"[^a-z0-9 ]", " ", s)            # emoji, ®, ✔, punctuation
    return re.sub(r"\s+", " ", s).strip()


def _rung12_person_is_first_degree(name):
    """Is `name` a recorded 1st-degree connection, per documents/state/contact.jsonl (kind=contact)
    or the newest documents/linkedin-exports/Connections-*.csv?

    Unlike the WARM-RUNG anchor, this does NOT consult the closeness store: rung 1-2 is a zero-ask
    connect note, the floor of the ladder, and by design carries no scorecard/closeness expectation
    (HARD-INVARIANTS §"SCREEN DEPTH IS TIERED BY RUNG"). A missing closeness row must not fail this closed.
    """
    repo = _data_root()
    target = _name_key(name)
    if not target:
        return False
    # (1) documents/state/contact.jsonl, kind=contact, payload.name
    try:
        p = os.path.join(repo, "documents", "state", "contact.jsonl")
        with open(p, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("kind") != "contact":
                    continue
                nm = _name_key((row.get("payload") or {}).get("name"))
                if nm and nm == target:
                    return True
    except Exception:
        pass
    # (2) the newest documents/linkedin-exports/Connections-*.csv
    try:
        import glob, csv
        exports = sorted(glob.glob(os.path.join(repo, "documents", "linkedin-exports",
                                                  "Connections-*.csv")))
        if exports:
            newest = exports[-1]
            with open(newest, encoding="utf-8", errors="ignore") as fh:
                # LinkedIn's export prefixes the real header with a "Notes:" preamble; find the
                # real header row before handing off to csv.DictReader.
                lines = fh.readlines()
            start = 0
            for i, ln in enumerate(lines):
                if ln.strip().lower().startswith("first name,last name"):
                    start = i
                    break
            reader = csv.DictReader(lines[start:])
            for row in reader:
                full = f"{(row.get('First Name') or '').strip()} {(row.get('Last Name') or '').strip()}"
                full = _name_key(full)
                if full and full == target:
                    return True
    except Exception:
        pass
    return False


# ⛔ A DEAD DUPLICATE OF `_is_rung12_zero_ask_note` LIVED HERE and was removed 2026-08-11.
# The function was defined TWICE in this file, and the two bodies were functionally identical while
# their docstrings differed: the later copy had been through a style pass (em dashes removed). A
# kit sync had APPENDED the rewritten version instead of replacing the original, so Python used the
# second and the first sat here misleading every reader of the file.
# ⚠️ Nothing behaved wrongly, which is exactly why it survived: a shadowed definition produces no
# error, no warning and no failing test. It is found by reading, or not at all. Reported by the
# partner-side audit, not by anything in the suite.
# 🩹 If you are adding a condition to the rung 1-2 exemption, the LIVE definition is the later one
# in this file. There is now only one.


def _is_reply_to_captured_inbound(tool_input):
    """Is this AskUserQuestion constructing a REPLY to a message someone sent HIM first?

    Added 2026-08-03. THE HOLE THIS CLOSES: every other exemption assumes the pipeline spoke first.
    `FOLLOWUP:` anchors on the company appearing as a SENT record in outreach_log.md, `WARM-RUNG:` /
    `RUNG12:` / `REFERRED:` anchor on a relationship we already hold. An UNSOLICITED inbound has
    none of those. A recruiter emails him cold, he decides to answer, and the BUILD gate demands a
    Boss Match Scorecard and a build/skip ruling for an outreach campaign that does not exist and
    never will. The gate was not catching anything; it had no branch for the case.

    The occasion: 2026-08-03, Jane Doe at Example Staffing (staffing agency) sent an unsolicited contract
    PM req with the client unnamed. you pick "reply and ask who the client is". Co-constructing
    that reply beat by beat is exactly what the outreach rules REQUIRE, and the gate blocked it
    twice, forcing the markdown-table fallback for a message his own method says to send.

    NON-FORGEABLE anchor, same shape as the other four, and this one is SELF-HEALING by design.
    BOTH must hold:
      (a) an explicit `INBOUND: <Full Name>` marker in the question framing, AND
      (b) that person appearing in an INBOUND event header in documents/correspondence-log.md.

    (b) is the load-bearing half. A cold first-contact draft disguised as a reply names someone who
    never wrote to him, so it is in no inbound header and stays blocked. And when the exemption
    legitimately does NOT fire yet, the fix is not to weaken anything, it is to CAPTURE THE INBOUND
    VERBATIM — which is already a standing requirement ([[capture-all-correspondence]]) and is the
    thing the 🔴 "email inbox has NEVER been read by the pipeline" alert has been asking for since
    2026-08-01. The gate therefore pushes toward the missing record instead of around it: answering
    an inbound is only unblocked once the inbound is on the record where the ladder can count it.

    ⚠️ This exemption authorizes REPLYING, not APPLYING. It carries no opinion on the underlying
    role and no BUILD ruling; a résumé, an application or a cold approach to the named client still
    needs its own screen and its own ruling.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    # BUG-202 (Q2 a): the second anchor form `INBOUND: <First> (<Company>)`, for a sender who signed with a first name only.
    # ONE header must carry both (sender token + company inside the sender's own parenthetical); a first name alone stays refused.
    _fc = _inbound_first_name_company(blob)
    if _fc:
        try:
            log = os.path.join(_data_root(), "documents", "correspondence-log.md")
            return os.path.exists(log) and _inbound_header_has(_read(log), _fc[0], _fc[1])
        except Exception:
            return False
    # Same hardened matcher as _is_followup_to_sent_company: marker case-insensitive, name capture
    # case-SENSITIVE and word-shaped (a blanket re.I makes [A-Z] match lowercase prose and turns the
    # anchor into a skeleton key), and no '.' in the class so "INBOUND: Jane Doe. Which
    # angle?" cannot capture trailing sentence text.
    m = re.search(r"(?i:inbound:)\s*([A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){1,3})", blob)
    if not m:
        return False
    words = m.group(1).split()
    candidates = [" ".join(words[:k]) for k in range(len(words), 1, -1)]
    # Floor of 2 words: a first name alone is too collidable against a log this dense with names.
    candidates = [c for c in candidates if len(re.sub(r"[^a-z0-9]", "", c.lower())) >= 5]
    if not candidates:
        return False
    pats = [re.compile(r"(?<![a-z0-9])" + re.escape(c.lower()) + r"(?![a-z0-9])") for c in candidates]
    try:
        repo = _data_root()
        log = os.path.join(repo, "documents", "correspondence-log.md")
        if not os.path.exists(log):
            return False
        src = open(log, encoding="utf-8", errors="ignore").read()
        # Header-scoped, not whole-file. The name must sit in an INBOUND event header, so being
        # merely MENTIONED in someone else's thread annotation does not open the gate. Same header
        # shape pair_brief.inbound_rows() already parses, kept in sync deliberately.
        for head in re.findall(r"^#{2,4}[^\n]*(?:📥|INBOUND)[^\n]*$", src, re.M):
            low = head.lower()
            if any(p.search(low) for p in pats):
                return True
    except Exception:
        return False
    return False


def _reunion_override_for(name, repo=None):
    """Your per-person override of the reunion-first refusal, read from the RAW store.

    The refusal below is deterministic and, without this, has no escape hatch: if you decide the
    gate has misread a relationship, the only ways forward are to route around the gate or to argue
    with it. Neither is a good outcome for a gate you own. A decision you make has to become STATE
    the gate reads.

    Deliberately NARROW so it cannot be laundered onto a cold draft: the record must carry a
    `reunion_override` object naming a `ruled_on` date and a `reason`, it only exists if a human
    wrote it into documents/contact-closeness.json, and it is PER PERSON with no wildcard.

    ⚠️ Reads the RAW json rather than the loaded row. `closeness.load()` normalizes each record onto
    a fixed key set and silently DROPS anything else, so an override written to the file never
    reaches this function through the loaded row.

    BUG-769: reads the DATA ROOT (JOBSEARCH_DATA_ROOT, else the install this script lives in), accepts the override at the TOP LEVEL (key = name) or
    inside the person's own row, matches an exact name first, and resolves a name PREFIX (a capture cut short before a middle initial) only when
    exactly one person carries it: an ambiguous prefix matches nothing.
    """
    import json as _json
    try:
        import closeness as _cl
        # The DATA ROOT, like every other read in this gate (BUG-769), so a redirected install (JOBSEARCH_DATA_ROOT) reads its own file.
        with open(os.path.join(repo or _data_root(), "documents", "contact-closeness.json"), encoding="utf-8") as _fh:
            raw = _json.load(_fh)
    except Exception:
        return None
    want = _cl.normalize_name(name)
    if not want:
        return None
    # The override is written at the TOP LEVEL (key = name) in the live store, while closeness.load() reads only raw["contacts"]; accept it in
    # either place, so the layout can never take a ruling already recorded out of service.
    places = [(k, v) for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict) and k != "contacts"]
    if isinstance(raw.get("contacts"), dict):
        places += [(k, v) for k, v in raw["contacts"].items() if isinstance(v, dict)]
    by_person = {}
    for k, v in places:
        by_person.setdefault(_cl.normalize_name(k), []).append(v)

    def _valid(records):
        for v in records:
            ov = v.get("reunion_override")
            if isinstance(ov, dict) and ov.get("ruled_on") and ov.get("reason"):
                return ov
        return None

    if want in by_person:
        return _valid(by_person[want])          # an exact name wins; a longer name sharing its start never lends its ruling
    # A capture can run SHORT of the stored name (a middle initial: `WARM-RUNG: Pat J. Example` captures "Pat J"). Resolve it only when EXACTLY ONE
    # person carries the prefix, the same rule as the tier lookup in _closeness_verdict: an ambiguous prefix matches nothing, never the first row.
    hits = [k for k in by_person if k.startswith(want + " ")]
    return _valid(by_person[hits[0]]) if len(hits) == 1 else None


def _closeness_verdict(name):
    """Does the closeness store SANCTION a warm-shaped ask to this person? None = no objection.

    A string = REFUSE, and the string carries the sanctioned shape plus the fix for THIS name.

    WHY ROSTER MEMBERSHIP ALONE STOPPED BEING ENOUGH. The roster anchor proves the person is a
    real 1st-degree connection — and a total stranger you cold-connected last month is exactly
    that. Roster membership grants the warm exemption to people you have never spoken to, which is
    the one ask shape the ladder forbids. The store holds YOUR stated relationships; this consult
    makes the exemption run on the relationship instead of the connection.

    FAIL-CLOSED BY RULING (owner, 2026-07-26): with a store PRESENT, an ABSENT row, `never-spoke`,
    `known-level-tbd`, and every HELD state all REFUSE the exemption. A partly-levelled store is
    normal for months, and the block converting into a 30-second `/level-network --name` interview
    is the deliberate trade: it teaches the ladder while it fills the store. Only a store FILE that
    does not exist at all skips the consult (mid-onboarding installs keep working roster-only).
    """
    try:
        import closeness
    except Exception:
        return None  # twin not installed at all: legacy roster-only behavior
    # Resolve the store path at CALL time (same pattern as _roster_names_blob): the hook runtime
    # sets CLAUDE_PROJECT_DIR per invocation, and an import-time constant would go stale.
    repo = _data_root()
    store = closeness.load(os.path.join(repo, "documents", "contact-closeness.json"))
    if store is None:
        return None  # no store yet (mid-onboarding): legacy roster-only behavior
    fix = (f'fix: python3 scripts/level_contacts.py --name "{name}"  '
           f'(or in Claude Code: /level-network --name "{name}") — a 30-second question, '
           f'recorded forever')
    # Same prefix fallback as the roster match: `WARM-RUNG: Jane Doe Rung-6` must find the
    # "Jane Doe" row rather than reading the stray token as an absent contact.
    row, words = None, name.split()
    for k in range(len(words), 1, -1):
        row = closeness.tier_for(" ".join(words[:k]), store)
        if row is not None:
            break
    if row is None:
        # The capture runs SHORT when the roster spelling carries a middle initial: the name class
        # excludes '.', so `WARM-RUNG: Pat J. Example` captures "Pat J". The roster anchor
        # tolerates that (it matches word-bounded inside the blob) and an exact store lookup does
        # not, so the consult would fail closed on a genuine contact whose only distinguishing mark
        # is a middle initial. Match store keys that START WITH the capture, and require EXACTLY
        # ONE: a truncation resolves, while an ambiguous prefix still fails closed rather than
        # borrowing another person's tier.
        prefix = closeness.normalize_name(name)
        hits = [r for k, r in store.items() if k.startswith(prefix + " ")]
        if len(hits) == 1:
            row = hits[0]
    if row is None:
        return (f"no closeness recorded for {name}. A warm rung needs a stated relationship; "
                f"until then the sanctioned shapes are COLD: rung 3-4 hire-me only if they are "
                f"the boss, otherwise rung 1-2 connect with zero ask. {fix}")
    code, detail = closeness.warm_refusal(row)      # the one sanction rule lives in closeness.py (BUG-600)
    if code == "held":
        return (f"{name} is HELD: {detail}. Handling state overrides closeness — do not build for "
                f"them until you clear the hold.")
    if code == "never-spoke":
        return (f"your own store says you and {name} have NEVER SPOKEN, so a warm rung is not "
                f"sanctioned. Sanctioned shapes: rung 3-4 hire-me only if they are the boss, "
                f"otherwise rung 1-2 connect with zero ask. If the store is wrong, {fix}")
    if code == "acquaintance":
        return (f"your own store says you and {name} never spoke beyond a LinkedIn connection, so a warm "
                f"rung is not sanctioned. Sanctioned shapes: rung 3-4 hire-me only if they are the boss, "
                f"otherwise rung 1-2 connect with zero ask. If the store is wrong, {fix}")
    if code == "unlevelled":
        return (f"{name} is known but UNLEVELLED (known-level-tbd) — ask the level before "
                f"building anything. {fix}")
    if code == "unmapped":
        return (f"{name} carries a closeness tier this install does not know ({detail!r}), so a warm "
                f"rung is not sanctioned. {fix}")

    # ── THE REUNION GATE, REFUSAL HALF ──────────────────────────────────────────────────────────
    # closeness.rung_for() already RECOMMENDS a reunion for a strong tie whose thread is dead.
    # Without this, nothing REFUSES the warm ask, and a gate only one half of the pipeline honors
    # is a recommendation. The rule itself (warm_refusal's "cold-strong") is closeness.py's; this
    # half words the refusal and honors the owner's per-person override.
    #
    # ⚠️ A long gap is not automatically decay. Two people who no longer work together may simply
    # have no reason for frequent contact, and treating that as damage produces an apology beat
    # that is not owed. That is what `reunion_override` is for: when you know the relationship
    # better than the timestamps do, record it and the gate stands down.
    if code == "cold-strong":
        if _reunion_override_for(name, repo):
            return None
        state, last = detail
        tier = closeness.TIER_ALIASES.get(row.get("closeness"), row.get("closeness"))
        why = ("they have never written back" if state == closeness.DEPTH_NEVER
               else f"they last wrote on {last}" if last else "the thread is long cold")
        return (f"{name} is a STRONG tie ({tier}) whose thread is cold — {why}. A warm "
                f"rung-7 trio ask is calibrated for WEAK ties, so aimed here it makes the "
                f"ask smaller than the relationship and reads as transactional. Send the "
                f"REUNION first, with no ask; the outreach follows as its own message. If "
                f"the thread is live and the store is stale, re-run "
                f"scripts/parse_messages.py --write, then rebuild. If the gap is simply "
                f"how this relationship runs, record a `reunion_override` for them in "
                f"documents/contact-closeness.json (`ruled_on` + `reason`).")
    return None


def _is_warm_rung_to_known_contact(tool_input):
    """A WARM-rung message (LaCivita 5/6/7) to a real 1st-degree contact is BUILD-gate-EXEMPT.

    A warm rung has no scorecard, no boss, no company to screen and no praise beat, so there is
    nothing for a company-scoped BUILD ruling to attach to; mail-draft.sh's WARM profile gates it on
    --targets dedup instead. Anchors, ALL must hold: (a) an explicit `WARM-RUNG: <Full Name>`
    marker in the question, (b) that person appearing in documents/warm-network.md (your own
    1st-degree export — a cold boss is by definition not in it), AND (c) the closeness store, when
    it exists, sanctioning a warm shape for them (see _closeness_verdict: roster membership proves
    the CONNECTION, only the store proves the RELATIONSHIP).
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    m = re.search(r"(?i:warm[-\s]?rung:)\s*([A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){1,3})", blob)
    if not m:
        return False
    name = " ".join(m.group(1).split())
    if not _name_in_roster(name, _roster_names_blob()):
        return False
    verdict = _closeness_verdict(name)
    if verdict:
        _CLOSENESS_REFUSALS.append(f"WARM-RUNG exemption refused — {verdict}")
        return False
    return True


def _contact_card_shown(name):
    """True when a CONTACT SCORECARD was shown for this person and is still spendable.

    ⭐ THE OPERATOR'S RULING, 2026-08-11, verbatim: *"You should give me a scorecard on a contact
    before starting the co-creation picker. This should be our operating model."*

    🔴 THE HOLE IT CLOSES. The BUILD gate demands a scorecard before any COMPANY or BOSS work, and
    the rung 1-2 and warm-rung exemptions skip it entirely. Three notes were co-created on
    2026-08-11 with the owner never shown who the person was. The exemptions are RIGHT about
    AUTHORIZATION — a zero-ask note needs no build ruling — and were WRONG about INFORMATION.

    📊 THE RECEIPT. `rank_criteria --pool people` offered a named contact at "score 39.6" as the
    day's pick. SIX rows all scored 39.6 and FIVE carried a byte-identical reason. That contact was
    not the highest ranked; they were first in a six-way tie broken by connect date, presented as a
    #1 verdict. Nothing in the flow would have said so.

    ⚖️ THE CARD IS INFORMATION, NOT AUTHORIZATION. It carries no MAC and cannot promote itself. It
    records that they were SHOWN who this person is. Their ruling stays theirs.

    ⛔ OVERRIDE, same idiom as the reunion override above so there is ONE override shape in this
    file rather than two: a per-person `card_override` object in contact-closeness.json naming a
    `ruled_on` date and a `reason`. No global switch, no wildcard.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import contact_card
        if contact_card.was_shown(name):
            return True
    except Exception as _e:
        # Fail OPEN on a missing/broken card module, never closed. This precondition exists to
        # INFORM him, and a crash here would block outreach entirely over a reporting tool.
        # The BUILD gate's own protections are unchanged either way. SILENT UNTIL 2026-09-12:
        # failing open is the right call, but a broken contact_card meant the "was this contact
        # scorecard shown" check quietly always answered yes, with no signal that it never ran.
        print(f"⚠️  check_preview: contact_card did not import ({type(_e).__name__}: {_e}); "
              f"the contact-scorecard-shown check is failing open (assuming yes) for {name!r}",
              file=sys.stderr)
        return True
    return bool(_card_override_for(name))


def _card_override_for(name):
    """The owner's explicit per-person waiver of the card requirement, read from the RAW json.

    ⚠️ RAW, not `row`. `closeness.load()` normalizes onto a fixed key set and silently DROPS
    anything else, so an override written into contact-closeness.json never reaches a caller
    through the loaded record. That cost an hour on 2026-08-04 with the reunion override.
    """
    # ⛔ RESOLVE FROM __file__, exactly like `_reunion_override_for` above. The first cut of this
    # used a module-level `REPO` that DOES NOT EXIST in this file; the NameError was swallowed by
    # the except and the override silently never fired. A bare except that hides a typo is how a
    # working feature reads as a broken one — caught only because a test asserted the override
    # clears the gate and it did not.
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "documents", "contact-closeness.json")
        raw = json.load(open(path, encoding="utf-8")).get("contacts", {})
        import closeness as _cl
        want = _cl.normalize_name(name)
        for k, v in raw.items():
            if _cl.normalize_name(k) != want:
                continue
            ov = v.get("card_override")
            if isinstance(ov, dict) and ov.get("ruled_on") and ov.get("reason"):
                return ov
    except Exception:
        return None
    return None


def _is_referred_via_known_introducer(tool_input):
    """A REFERRAL (LaCivita rung 8/9) is BUILD-gate-EXEMPT. The contact is 2nd-degree by definition,
    so the anchor is the INTRODUCER, not the stranger. Anchors, ALL must hold: (a) an explicit
    `REFERRED: <Contact> VIA <Introducer>` marker, (b) the INTRODUCER appearing in
    documents/warm-network.md, AND (c) the closeness store, when it exists, sanctioning a warm
    shape for the INTRODUCER — someone you never spoke to cannot introduce you, so the consult
    applies to them symmetrically. A cold boss-hunt cannot launder itself as a referral without
    naming a real, related 1st-degree contact as the source.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    m = re.search(r"(?i:referred:)\s*[A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){0,3}\s+(?i:via)\s+"
                  r"([A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){0,3})", blob)
    if not m:
        return False
    introducer = " ".join(m.group(1).split())
    if not _name_in_roster(introducer, _roster_names_blob()):
        return False
    verdict = _closeness_verdict(introducer)
    if verdict:
        _CLOSENESS_REFUSALS.append(
            f"REFERRED exemption refused — the introducer must hold a real relationship: {verdict}")
        return False
    return True


def _is_followup_to_sent_company(tool_input):
    """A FOLLOW-UP to an already-SENT company is BUILD-gate-EXEMPT: its first send already passed the
    gate, and it has no new scorecard. Non-forgeable, BOTH must hold: (a) an explicit
    `FOLLOWUP: <Company>` marker, AND (b) that company appearing as a SENT record in outreach_log.md.
    A cold first-contact disguised as a follow-up names a company that was never sent, so it stays
    blocked. Match WORD-BOUNDED against the block header (try shorter leading prefixes too), and
    require the block body to carry a SENT marker.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    m = re.search(r"(?i:follow[-\s]?up:)\s*([A-Z0-9][\w&\-]*(?:\s+[A-Z0-9][\w&\-]*){0,3})", blob)
    if not m:
        return False
    words = m.group(1).split()
    candidates = [" ".join(words[:k]) for k in range(len(words), 0, -1)]
    candidates = [c for c in candidates if len(re.sub(r"[^a-z0-9]", "", c.lower())) >= 3]
    if not candidates:
        return False
    pats = [re.compile(r"(?<![a-z0-9])" + re.escape(c.lower()) + r"(?![a-z0-9])") for c in candidates]
    try:
        repo = _data_root()
        log = os.path.join(repo, "outreach_log.md")
        if not os.path.exists(log):
            return False
        src = open(log, encoding="utf-8", errors="ignore").read()
        for block in re.split(r"(?=^## )", src, flags=re.M):
            head = block.splitlines()[0] if block.strip() else ""
            if not head.startswith("## "):
                continue
            low_head = head.lower()
            if any(p.search(low_head) for p in pats) and re.search(r"\bsent\b", block, re.I):
                return True
    except Exception:
        return False
    return False


def _rung12_ask_patterns():
    """Reuse check_outreach's _INVITATION_ASK vocabulary rather than duplicating it (a test must
    read the production value). Falls back to a small literal list only if the import fails, so a
    broken import fails toward MORE scrutiny (the normal gate applies), never less."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from check_outreach import _INVITATION_ASK
        return [pat for pat, _why in _INVITATION_ASK]
    except Exception as _e:
        print(f"⚠️  check_preview: check_outreach._INVITATION_ASK did not import "
              f"({type(_e).__name__}: {_e}); rung 1-2 zero-ask exemption running on a 5-pattern "
              f"fallback (fails toward more scrutiny, not less)", file=sys.stderr)
        return [
            re.compile(r"on your radar", re.I),
            re.compile(r"work directly for you", re.I),
            re.compile(r"\bbe considered\b", re.I),
            re.compile(r"looking for a (?:PM|product manager)", re.I),
            re.compile(r"let'?s talk\b", re.I),
        ]


# Extra ask-shape vocabulary named in the rung 1-2 spec that _INVITATION_ASK does not already cover
# (intro/referral/hiring/role/opening/position are ask-shaped in a rung 1-2 note even though they
# never appear in a LinkedIn invitation, which has no room for them).
# 🔴 THESE USED TO BE BARE NOUNS AND THE GATE MEASURED THE WRONG SPEAKER (fixed 2026-08-11).
# The list was `hiring`, `role`, `opening`, `position`, `intro`. A bare noun cannot tell *you asking
# for a job* from *the recipient's own subject matter*, and for a RECRUITER those are the same
# words. Three rung 1-2 zero-ask notes to a staffing-firm partner were all blocked on `\bhiring\b`
# alone, present only because HIS OWN POST was about hiring.
#
# 💥 Recruiters are usually the highest-converting people you can write to, because their job is
# placing candidates. A gate that structurally refuses notes to them is not strict, it is aimed at
# the wrong target.
#
# ⛔ THE PATTERNS ARE NOT DELETED, THEY ARE MADE CONSTRUCTIONAL. RUNG12 exists to stop a real ask
# riding in under a zero-ask marker, and that job still gets done. An ask is a REQUEST directed at
# the recipient about your candidacy, so match the CONSTRUCTION ("any openings", "keep me in mind",
# "introduce me") rather than the topic noun. A question about how someone does their own work is
# not an ask, however many domain nouns it carries.
_RUNG12_EXTRA_ASK = [
    re.compile(r"\bintroduce me\b", re.I),
    re.compile(r"\brefer(?:ral|ring) me\b|\ba referral\b", re.I),
    re.compile(r"\bare you hiring\b|\byou'?re hiring\b|\bhiring for\b|\bwho'?s hiring\b", re.I),
    re.compile(r"\bany (?:openings?|roles?|positions?|opportunit)", re.I),
    re.compile(r"\bopen (?:roles?|positions?|reqs?|headcount)\b", re.I),
    re.compile(r"\bkeep me in mind\b|\bthink of me\b|\bconsider me\b", re.I),
    re.compile(r"\blet me know if (?:you|anything|there)", re.I),
    re.compile(r"\bi'?m looking\b|\bi am looking\b|\bmy (?:resume|résumé|cv)\b", re.I),
    re.compile(r"\bintro to\b|\ban intro\b", re.I),
    re.compile(r"\ba (?:role|position|seat|opening) for me\b", re.I),
]


def _rung12_text_has_ask(blob):
    pats = _rung12_ask_patterns() + _RUNG12_EXTRA_ASK
    return any(p.search(blob) for p in pats)


def _is_rung12_zero_ask_note(tool_input):
    """LaCivita rung 1-2: a zero-ask common-interest note to a recorded 1st-degree connection.

    HARD-INVARIANTS §"SCREEN DEPTH IS TIERED BY RUNG" rules that rung 1-2 has NO scorecard and NO BUILD ruling by
    design; requiring one here is the same category of defect the WARM-RUNG, FOLLOWUP and REFERRED
    exemptions already fix for their own rungs (a legitimate zero-ask connect note kept hitting the
    BUILD gate with no exemption available).

    NON-FORGEABLE anchor, mirroring the other three exemptions — ALL must hold:
      (a) an explicit `RUNG12: <Full Name>` marker in the question framing,
      (b) that person appears in documents/state/contact.jsonl (kind=contact) or the newest
          documents/linkedin-exports/Connections-*.csv (a 1st-degree connection is proven by EITHER
          source; no closeness row is required, rung 1-2 is the floor ask shape, and unlike WARM it
          must not fail closed on a missing closeness record), AND
      (c) NONE of the drafted option/preview text matches ask-shaped vocabulary (the
          check_outreach._INVITATION_ASK list plus intro/referral/hiring/role/opening/position); a
          rung 1-2 note that carries a pitch is not rung 1-2 regardless of the label.
    A cold-boss draft cannot wear this label: naming a scorecard, a build ruling, or `cold-boss`
    context anywhere in the blob forces the normal gate even if (a)-(c) all hold, so the exemption
    cannot be laundered onto content that is plainly cold-boss shaped.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    m = re.search(r"(?i:rung12:)\s*([A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){1,3})", blob)
    if not m:
        return False
    name = " ".join(m.group(1).split())
    low = blob.lower()
    if "cold-boss" in low or "scorecard" in low or "build ruling" in low:
        return False
    if not _rung12_person_is_first_degree(name):
        return False
    if _rung12_text_has_ask(blob):
        return False
    # ⭐ THE CARD PRECONDITION (2026-08-11). Attached HERE rather than at the call site on purpose:
    # `tests/test_gates.py` asserts the literal string `"not _is_rung12_zero_ask_note(tool_input)"`
    # appears in the gate chain, so that line must survive verbatim. The resolved `name` is already
    # in scope here and is the person the card must exist for.
    if not _contact_card_shown(name):
        return False
    return True


def _is_cocreation_for_live_application(tool_input):
    """Is this AskUserQuestion co-creating APPLICATION or INTERVIEW content for a live application?

    THE HOLE THIS CLOSES: every other exemption on this gate assumes OUTREACH. `FOLLOWUP:` wants a
    SENT record, `WARM-RUNG:` / `RUNG12:` / `REFERRED:` want a relationship, `INBOUND:` wants a
    message you received. **Screening answers, application free-response and interview stories have
    none of those**, because there is no boss being approached and no campaign to score. Without
    this branch the gate demands a Boss Match Scorecard for an application screening question and
    blocks the picker, forcing a markdown-table fallback for exactly the work you asked to
    co-construct through the picker.

    NON-FORGEABLE anchor, the same discipline as the other exemptions. BOTH must hold:
      (a) an explicit `APPLYING: <Company>` marker in the question framing, AND
      (b) an application FOLDER for that company under documents/applications/ that contains at
          least one real artifact (a job_posting.md, a JD, or a CV draft).

    (b) is the load-bearing half, and it is deliberately expensive to fake. An application folder
    with the posting in it means the role was read and the work is real. A cold boss-hunt draft
    disguised as an application has no folder and stays blocked.

    ⛔ THIS AUTHORIZES CO-CREATING THE CONTENT, NOT DECIDING TO APPLY. The decision to pursue an
    employer still needs its own screen and its own ruling; this only says that once that decision
    is made and the folder exists, drafting the words belongs in the picker.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    m = re.search(r"(?i:applying:)\s*([A-Za-z][\w'&\-]*(?:\s+[A-Za-z][\w'&\-]*){0,4})", blob)
    if not m:
        return False
    name = m.group(1).strip()
    # Progressive prefixes, longest first, the same shape as the other multi-word anchors. A folder
    # is named for the ROLE as well as the company (`someco_product_manager`), so the full company
    # key will not be a substring of it; the leading token is what actually matches. Floor of 5
    # characters so a short token cannot become a skeleton key across every folder.
    words = name.split()
    candidates = [re.sub(r"[^a-z0-9]", "", " ".join(words[:k]).lower())
                  for k in range(len(words), 0, -1)]
    candidates = [c for c in candidates if len(c) >= 5]
    if not candidates:
        return False
    try:
        repo = _data_root()
        root = os.path.join(repo, "documents", "applications")
        if not os.path.isdir(root):
            return False
        for d in os.listdir(root):
            full = os.path.join(root, d)
            if not os.path.isdir(full):
                continue
            dkey = re.sub(r"[^a-z0-9]", "", d.lower())
            # PREFIX, not substring: the folder must START with the company, so
            # `someco_product_manager` matches "SomeCo Communications" via its leading token, while
            # a company whose name merely appears mid-folder does not open the gate.
            if not any(dkey.startswith(c) for c in candidates):
                continue
            for f in os.listdir(full):
                lf = f.lower()
                if lf.endswith((".docx", ".pdf", ".tex")) or lf in ("job_posting.md", "jd.md"):
                    return True
    except Exception:
        return False
    return False

# Shared by _is_portfolio_self_content and _is_positioning_copy: both exemptions cover
# first-person self-content with no boss, so both must refuse the same outreach/ask/
# boss-address tells rather than drift into two slightly different lists.
_SELF_CONTENT_OUTREACH_SIGNALS = (
    "be on your radar", "can't stop talking about", "so i'm saying", "\U0001f44b",
    "any chance you", "an intro", "referral", "i applied", "i just applied",
    "scorecard", "build ruling", "cold-boss", "you're betting", "the bet you're making",
    "vouch", "reach out to",
)

# Shared with _carries_drafted_voice detector (a) and the DECISION/DESIGN exemptions: a real
# greeting addressed to a name by comma/whitespace separation. Factored out so the exemptions
# refuse the same shape the BUILD gate itself refuses, rather than maintaining a second copy
# that can drift.
#
# ⚠️ THE SEPARATOR IS REQUIRED, NOT OPTIONAL. A prior version read `[ \t]*,?[ \t]*`, where every
# branch is optional, so the greeting word could sit glued directly against the name with
# nothing between them. A CamelCase company name that merely starts with a greeting word then
# parses as a greeting addressed to a person:
#
#     "HiZorbel"  -> "Hi" + "Zorbel"
#     "HeyGen"   -> "Hey" + "Gen"    <- a real AI-video company
#     "DearDoc"  -> "Dear" + "Doc"   <- a real healthtech company
#
# A real greeting always puts a comma or whitespace between the word and the name -- "Hi Dana",
# "Hi, Dana", "Dear Dana,", "Morning, Dana!", "Hey there Dana!" -- and a glued token is one
# word, never an address. Requiring >=1 separator does not weaken the gate; it removes matches
# no greeting can produce.
_GREETING_TO_NAME_RE = (
    # BUG-594 (2026-10-08): the name anchor is a REAL capital. This pattern used to be applied with
    # `re.I`, which turned `[A-Z]` into "any letter", so the option label "Morning items walk"
    # parsed as a greeting addressed to "items walk" and blocked THE PAIR's NEXT-STEP picker twice.
    # The greeting words are case-insensitive through the inline `(?i:...)` groups only. Callers
    # pass `re.M`, never `re.I`.
    #
    # The BARE forms (morning, afternoon, tgif) are also ordinary English nouns ("Morning Brief",
    # "Afternoon Standup"), so they need more than a capitalized word after them: either a comma
    # before the name ("Morning, Dana", with any terminator) or punctuation right after the name
    # ("Morning Dana!"). A newline alone does not count for them. Accepted cost: "Morning Dana"
    # with nothing after the name is not read as a greeting.
    #
    # The NAME token is a capital, any letters or apostrophes, and a lowercase LAST letter. So
    # McKenzie, DeShawn, LaToya and O'Neil match, while an all-caps word ("Hi API,", "Hey AI team")
    # and a single capital do not. Accepted losses: "Hi DANA," (all caps) and "hi dana," (lowercase).
    r"(?:^|[\n\r>\"'“]|\s\s)(?:"
    r"(?i:hi|hey|hello|dear|greetings|good morning|good afternoon|good evening)"
    r"(?:[ \t]*,[ \t]*|[ \t]+)(?:(?i:there)(?:[ \t]*,[ \t]*|[ \t]+))?"
    r"([A-Z][A-Za-z'’]*[a-z](?:[ \t]+[A-Z][A-Za-z'’]*[a-z])?)"
    r"[ \t]*[!,.:;\n\r-]"
    r"|(?i:morning|afternoon|tgif)(?:"
    r"[ \t]*,[ \t]*(?:(?i:there)(?:[ \t]*,[ \t]*|[ \t]+))?"
    r"([A-Z][A-Za-z'’]*[a-z](?:[ \t]+[A-Z][A-Za-z'’]*[a-z])?)[ \t]*[!,.:;\n\r-]"
    r"|[ \t]+(?:(?i:there)(?:[ \t]*,[ \t]*|[ \t]+))?"
    r"([A-Z][A-Za-z'’]*[a-z](?:[ \t]+[A-Z][A-Za-z'’]*[a-z])?)[ \t]*[!,.:;-]"
    r")"
    r")"
)


def _is_portfolio_self_content(tool_input):
    """Is this AskUserQuestion co-creating PORTFOLIO / self-description content (a hero arc, a
    personal-site capsule) about YOUR OWN projects, addressed to no boss?

    THE HOLE THIS CLOSES is the same shape as the APPLYING and INBOUND holes: every other exemption
    on this gate assumes OUTREACH. Portfolio prose is first-person about your own work, destined for
    your website/portfolio, with no boss, no company being screened, and no ask. The drafted-voice
    detector correctly fires on "I built ... with Claude Code" for a cold outreach hook, but that
    same phrase is right for a portfolio arc — and the BUILD gate then demands a Boss Match Scorecard
    that has no inputs, forcing a markdown-table fallback for co-creation work that belongs in the
    picker.

    NON-FORGEABLE anchor, same discipline as the other exemptions. ALL must hold:
      (a) an explicit `PORTFOLIO: <piece>` marker in the question framing,
      (b) a portfolio-revision*.md doc under documents/ whose text contains that <piece> (the
          load-bearing half: your portfolio pieces are a documented, closed set, unlike the infinite
          space of target companies a cold draft could name), AND
      (c) the blob carries NO outreach/ask/boss-address signal (a cold-boss praise beat addresses
          the boss or carries an ask, so it cannot wear this label even if it named a documented
          piece).

    ⛔ AUTHORIZES CO-CREATING PORTFOLIO PROSE, nothing else. It carries no opinion on pursuing any
    employer; a cold approach still needs its own screen and its own ruling.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    low = blob.lower().replace("’", "'").replace("‘", "'")
    m = re.search(r"(?i:portfolio:)\s*([A-Za-z][\w'&\-]*(?:\s+[A-Za-z][\w'&\-]*){0,3})", blob)
    if not m:
        return False
    # (c) cannot be laundered onto outreach: any boss-address / ask / cold-boss signal disqualifies.
    if any(s in low for s in _SELF_CONTENT_OUTREACH_SIGNALS):
        return False
    piece = re.sub(r"[^a-z0-9]", "", m.group(1).lower())
    if len(piece) < 5:
        # A short token cannot become a skeleton key across the doc.
        return False
    # (b) the named piece must appear in a real portfolio-revision doc.
    try:
        repo = _data_root()
        docs = os.path.join(repo, "documents")
        for f in os.listdir(docs):
            if not (f.startswith("portfolio-revision") and f.endswith(".md")):
                continue
            with open(os.path.join(docs, f), "r", encoding="utf-8") as fh:
                if piece in re.sub(r"[^a-z0-9]", "", fh.read().lower()):
                    return True
    except Exception:
        return False
    return False


def _is_positioning_copy(tool_input):
    """Is this AskUserQuestion co-creating POSITIONING copy (a theme line, a LinkedIn About
    section, a personal-site home page) about YOU, addressed to no boss?

    THE HOLE THIS CLOSES is adjacent to the PORTFOLIO hole above: portfolio prose describes a
    specific PROJECT; positioning copy describes YOU (the theme line, the About section, the
    personal-site home page) with no project, no boss, no company, and no ask. The drafted-voice
    detector fires on a first-person credential claim by construction, and the BUILD gate then
    demands a Boss Match Scorecard that has no inputs.

    NON-FORGEABLE anchor, same discipline as PORTFOLIO. ALL must hold:
      (a) an explicit `POSITIONING: <piece>` marker in the question framing,
      (b) a positioning-revision*.md doc under documents/ whose text contains that <piece> (the
          load-bearing half — a small, closed, named set, same shape as portfolio-revision), AND
      (c) the blob carries NO outreach/ask/boss-address signal (shared constant with
          _is_portfolio_self_content).

    ⛔ AUTHORIZES CO-CREATING POSITIONING PROSE, nothing else. It carries no opinion on
    pursuing any employer; a cold approach still needs its own screen and its own ruling.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    low = blob.lower().replace("’", "'").replace("‘", "'")
    m = re.search(r"(?i:positioning:)\s*([A-Za-z][\w'&\-]*(?:\s+[A-Za-z][\w'&\-]*){0,3})", blob)
    if not m:
        return False
    if any(s in low for s in _SELF_CONTENT_OUTREACH_SIGNALS):
        return False
    piece = re.sub(r"[^a-z0-9]", "", m.group(1).lower())
    if len(piece) < 5:
        return False
    try:
        repo = _data_root()
        docs = os.path.join(repo, "documents")
        for f in os.listdir(docs):
            if not (f.startswith("positioning-revision") and f.endswith(".md")):
                continue
            with open(os.path.join(docs, f), "r", encoding="utf-8") as fh:
                if piece in re.sub(r"[^a-z0-9]", "", fh.read().lower()):
                    return True
    except Exception:
        return False
    return False


def _is_design_artifact_decision(tool_input):
    """Is this AskUserQuestion a product/app-design decision about a named design artifact,
    addressed to no boss?

    THE HOLE THIS CLOSES is the same shape as PORTFOLIO and POSITIONING: every other exemption
    assumes OUTREACH or a company being screened. A design-lane picker (an experiment question
    about the app itself, a plan decision) is neither, and none of the outreach-shaped exemption
    markers fit a product decision. This gate's own operating model permits this use.

    NON-FORGEABLE anchor, same discipline as PORTFOLIO/POSITIONING. ALL must hold:
      (a) an explicit `DESIGN: <artifact>` marker in the question framing,
      (b) that <artifact> names a real file under `app/design/` OR a file matching
          `documents/plan-*.md` (the load-bearing half: the artifact must actually exist,
          the same way a portfolio piece must appear in a real portfolio-revision doc), AND
      (c) the blob carries NO outreach/ask/boss-address signal (shared constant with
          _is_portfolio_self_content) and no greeting addressed to a name (shared regex with
          _carries_drafted_voice detector (a)), so a cold-boss draft can never wear this label
          even by naming a real artifact.

    ⛔ AUTHORIZES CO-CREATING/DECIDING APP-DESIGN CONTENT, nothing else. It carries no opinion
    on any employer or send; a cold approach still needs its own screen and its own ruling.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    low = blob.lower().replace("’", "'").replace("‘", "'")
    # NEWLINE join for the greeting check, matching _carries_drafted_voice's own join: the
    # regex's start/double-space anchors are position-dependent, and a single-space join
    # silently defeats them when the greeting sits after other fields.
    nl_blob = "\n".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    # Single token only, unlike PORTFOLIO/POSITIONING's multi-word capture: a filename or plan
    # slug never contains a space, and capturing further words would swallow the rest of the
    # sentence ("DESIGN: plan-x. Withhold the picker...") into the artifact needle.
    m = re.search(r"(?i:design:)\s*([\w][\w'&\-./]*)", blob)
    if not m:
        return False
    if any(s in low for s in _SELF_CONTENT_OUTREACH_SIGNALS):
        return False
    if re.search(_GREETING_TO_NAME_RE, nl_blob, re.M):
        return False
    artifact = m.group(1).strip()
    if len(re.sub(r"[^a-z0-9]", "", artifact.lower())) < 3:
        return False
    try:
        repo = _data_root()
        # (b1) a real file under app/design/, named exactly or as a stem (extension optional).
        design_dir = os.path.join(repo, "app", "design")
        if os.path.isdir(design_dir):
            candidates = {artifact, artifact.rstrip("/")}
            stem = os.path.basename(artifact).split(".")[0]
            for f in os.listdir(design_dir):
                fstem = f.split(".")[0]  # "Framing.dc.html" -> "Framing"
                if f in candidates or fstem == stem or fstem == artifact:
                    return True
        # (b2) a real documents/plan-*.md file naming the artifact in its own filename or text.
        docs = os.path.join(repo, "documents")
        if os.path.isdir(docs):
            needle = re.sub(r"[^a-z0-9]", "", artifact.lower())
            for f in os.listdir(docs):
                if not (f.startswith("plan-") and f.endswith(".md")):
                    continue
                if needle and needle in re.sub(r"[^a-z0-9]", "", f.lower()):
                    return True
                with open(os.path.join(docs, f), "r", encoding="utf-8") as fh:
                    if needle and needle in re.sub(r"[^a-z0-9]", "", fh.read().lower()):
                        return True
    except Exception:
        return False
    return False


def _is_next_step_ladder_picker(tool_input):
    """Is this THE PAIR's own NEXT-STEP picker, not an outreach draft that merely names a
    contact by name?

    THE HOLE THIS CLOSES: the OPERATIONAL PICKERS carve-out scopes the banned-word/AI-tell scan
    to `.preview` fields only when `NEXT-STEP` is present, but it never touched the BUILD GATE
    below — `_carries_drafted_voice` and its exemption chain run unconditionally. A voice marker
    that is a real closer tic in your own sent outreach can also be the literal subject of a
    NEXT-STEP picker asking you to rule on a user-research read of your own site — a THE PAIR
    picker discussing something ordinary can trip the drafted-voice detector on that string
    alone, and none of the outreach-shaped exemptions fit: there is no boss, no company, no
    campaign, no project, and no artifact file to point DESIGN/PORTFOLIO/POSITIONING at.

    NON-FORGEABLE anchor, same discipline as DECISION (no file to check, so the bar is on the
    shape itself, since a NEXT-STEP question is not free-form — check_pair.py independently
    refuses to ever DISPLAY the tool call unless the LADDER stamp it carries matches the live
    ladder computed from outreach_log.md at ask-time). ALL must hold:
      (a) the literal `NEXT-STEP` marker in the question or header (not merely somewhere in an
          option, mirroring the check_pair.py / THE PAIR requirement that the marker sits in
          those two fields),
      (b) a live `LADDER <date>` stamp in the same two fields (check_pair.py's own anchor,
          `LADDER\\s+\\d{4}-\\d{2}-\\d{2}`), so a bare "NEXT-STEP" word dropped into ordinary prose
          cannot borrow this exemption,
      (c) NO `.preview` field carries any text — a NEXT-STEP picker is separately FORBIDDEN from
          carrying `preview` at all (see the OPERATIONAL PICKERS note above), so a payload that
          smuggles a preview in under the marker gets MORE scrutiny, not less, AND
      (d) the blob carries no outreach/ask/boss-address signal and no greeting addressed to a
          name (the same two belts DECISION and DESIGN wear) — a genuine cold-boss draft cannot
          launder itself through this marker just by mentioning "NEXT-STEP" somewhere.

    ⛔ AUTHORIZES DISPLAYING THE PICKER FOR THE PAIR'S OWN NEXT-STEP QUESTION, nothing else. It
    never authorizes a send, a boss ask, or drafted outreach content — those still need their own
    ruling, and (c)/(d) exist precisely so this cannot become that back door.
    """
    qh_blob = " ".join(
        str(t) for f, t in _strings_from_questions(tool_input)
        if f.endswith(".question") or f.endswith(".header")
    )
    if "NEXT-STEP" not in qh_blob:
        return False
    if not re.search(r"LADDER\s+\d{4}-\d{2}-\d{2}", qh_blob):
        return False
    if any(f.endswith(".preview") and str(t).strip()
           for f, t in _strings_from_questions(tool_input)):
        return False
    full_blob = " ".join(str(t) for _f, t in _strings_from_questions(tool_input))
    low = full_blob.lower().replace("’", "'").replace("‘", "'")
    if any(s in low for s in _SELF_CONTENT_OUTREACH_SIGNALS):
        return False
    nl_blob = "\n".join(str(t) for _f, t in _strings_from_questions(tool_input))
    if re.search(_GREETING_TO_NAME_RE, nl_blob, re.M):
        return False
    return True


def _is_operating_decision(tool_input):
    """Is this AskUserQuestion an OPERATING decision from a lane (scope, sequencing, housekeeping
    timing, lane coordination), addressed to no boss?

    An operating decision has no artifact, no boss, and no company, so there is nothing to anchor
    a filename check to, unlike DESIGN. The anchor here is instead the ABSENCE of every shape the
    BUILD gate exists to catch — this gate's own operating model treats "you are making a
    decision" as a standing authorization to display the picker while the underlying issue is
    fixed in the background.

    NON-FORGEABLE anchor (there is no file to check, so the bar is on the content itself). ALL
    must hold:
      (a) an explicit `DECISION: <topic>` marker in the question framing,
      (b) the blob carries NO outreach/ask/boss-address signal (shared constant with
          _is_portfolio_self_content), AND
      (c) the blob carries no greeting addressed to a name (shared regex with
          _carries_drafted_voice detector (a)) — the same shape a genuine cold-boss draft always
          carries ("Hi, Dana! ..."), so a drafted note cannot launder itself through this marker
          just by avoiding the shorter outreach-signal wordlist.

    ⛔ AUTHORIZES DISPLAYING THE PICKER FOR AN OPERATING DECISION, nothing else. It never
    authorizes a send, a boss ask, or outreach content — those still need their own ruling.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    low = blob.lower().replace("’", "'").replace("‘", "'")
    # NEWLINE join for the greeting check, same reasoning as _is_design_artifact_decision:
    # the regex's position anchors need the real field boundaries, not a single space.
    nl_blob = "\n".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    if not re.search(r"(?i:decision:)\s*\S", blob):
        return False
    if any(s in low for s in _SELF_CONTENT_OUTREACH_SIGNALS):
        return False
    if re.search(_GREETING_TO_NAME_RE, nl_blob, re.M):
        return False
    return True


# ── BUG-202 one-pass (plan-bug202-one-pass-2026-11-02, rev 2) ──────────────────────────────────────
# The gate's strength is unchanged: no consent matcher moves, every exemption still needs its record, and a
# diagnosis is ADVICE (the gate still exits 2 without the marker). The block message names the one marker for
# this picker's shape in four lines; the full nine-exemption text lives behind `check_preview.py --guide`.
# ⛔ THE ADVICE NEVER PRINTS A COMMAND THAT CREATES A RECORD. On 2026-10-29 a seat edited an inbound header to
# get a picker through; a command in the advice would make that edit procedural. A missing record is NAMED
# (what must exist, where it comes from), never scripted.

_GATE_EVENTS = os.path.join("documents", "state", "gate-events.jsonl")
_MARKER_PRESENT = re.compile(r"\b(?:WARM-RUNG|INBOUND|FOLLOWUP|RUNG12|REFERRED|APPLYING|POSITIONING)\s*:", re.I)


def _session_id(payload=None):
    return str((payload or {}).get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "") or None


def append_event(kind, outcome, exemption, tool_input, session=None):
    """One row per block or exempted pass: ts, kind (gate, tell), outcome, exemption, marker_present, session.
    Never the question text, never a name. Fail-open: a broken log never blocks a picker. Its only reader is
    scripts/triage_board.py; no gate, hook or brief reads it, so a row can never be mistaken for a decision."""
    try:
        import datetime
        import fcntl
        blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
        row = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "kind": kind, "outcome": outcome, "exemption": exemption,
               "marker_present": bool(_MARKER_PRESENT.search(blob)), "session": session}
        path = os.path.join(_data_root(), _GATE_EVENTS)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
    except Exception:
        pass


def _inbound_headers(src):
    """[(when, sender, parenthetical)] for every INBOUND event header: `### <date> · 📥 INBOUND (..) ← Sender (role, Company)`.
    The sender token is the name right after the arrow; the parenthetical is the sender's own."""
    out = []
    for head in re.findall(r"^#{2,4}[^\n]*(?:📥|INBOUND)[^\n]*$", src, re.M):
        if "←" not in head:
            continue
        rest = head.split("←", 1)[1].strip()
        sender = re.match(r"[^()]*", rest).group(0).strip()
        paren = re.search(r"\(([^)]*)\)", rest)
        when = re.search(r"\d{4}-\d\d-\d\d(?:\s+\d\d:\d\d(?:\s+[A-Z]{2,4})?)?", head)
        out.append((when.group(0) if when else "", sender, paren.group(1) if paren else ""))
    return out


def _word_in(needle, hay):
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(needle.lower()) + r"(?![a-z0-9])", hay.lower()))


def _inbound_first_name_company(blob):
    """`INBOUND: <First> (<Company>)` -> (first, company), else None. Case-sensitive capture, same discipline as the full-name form."""
    m = re.search(r"(?i:inbound:)\s*([A-Z][\w'\-]*)\s*\(([A-Za-z0-9][\w&'.\- ]*)\)", blob)
    return (m.group(1), m.group(2).strip()) if m else None


def _inbound_header_has(src, first, company):
    """True only when ONE header carries BOTH: the first name as its sender token and the company inside the sender's own
    parenthetical. Two headers that together carry both, or a header whose subject names the first name, do not match."""
    if len(re.sub(r"[^a-z0-9]", "", company.lower())) < 3:
        return False
    for _when, sender, paren in _inbound_headers(src):
        words = sender.split()
        # the company slot only: the last comma segment of "(role, Company)", or the whole parenthetical with no comma.
        # Role words in the same parenthetical ("recruiter") must never act as the company (2e F1).
        slot = paren.split(",")[-1].strip() if paren else ""
        if words and words[0].lower() == first.lower() and slot and _word_in(company, slot):
            return True
    return False


def _read(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _own_first_names():
    """The first names a greeting must not be read as the ADDRESSEE: this install's owner, from kit_config.OWNER_FIRST, which
    is the person the draft is written for. Read at call time. Unconfigured (no kit_config, or the placeholder) excludes nothing;
    no name is ever hard-coded here."""
    try:
        import kit_config as _kc
        n = str(getattr(_kc, "OWNER_FIRST", "") or "").strip().lower()
    except Exception:
        n = ""
    return {n} if n and n not in ("you", "your") else set()


def _addressee(tool_input):
    """The draft's ADDRESSEE: the name in the greeting the drafted-voice detector found, else the name after "Reply to" in the
    question or header. Never a capitalized name that only appears in an option."""
    fields = list(_strings_from_questions(tool_input or {}))
    blob = "\n".join(str(t) for _, t in fields)
    for m in re.finditer(_GREETING_TO_NAME_RE, blob, re.M):
        for g in m.groups():
            if g and g.split()[0].lower() not in (_own_first_names() | {"ube"}):
                return g
    for f, t in fields:
        if f.endswith((".question", ".header")):
            m = re.search(r"(?i:\breply to|\bback to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", str(t))
            if m:
                return m.group(1)
    return None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def diagnose_build_block(tool_input):
    """Which exemption this blocked picker looks like, the record found for it, and the ONE marker to add.
    No side effects, no network. Returns {"exemption", "marker", "evidence", "missing"}. It changes nothing about pass or block."""
    none = {"exemption": None, "marker": None, "evidence": None, "missing": None}
    tool_input = tool_input or {}
    fields = list(_strings_from_questions(tool_input))
    head_text = " ".join(str(t) for f, t in fields if f.endswith((".question", ".header")))
    blob = " ".join(str(t) for _, t in fields)
    root = _data_root()
    who = _addressee(tool_input)
    # INBOUND: the addressee wrote to him first.
    if who:
        first = who.split()[0]
        try:
            log = os.path.join(root, "documents", "correspondence-log.md")
            heads = _inbound_headers(_read(log)) if os.path.exists(log) else []
        except Exception:
            heads = []
        mine = [h for h in heads if h[1].split() and h[1].split()[0].lower() == first.lower()]
        if mine:
            when, sender, paren = sorted(mine, key=lambda h: h[0])[-1]
            company = paren.split(",")[-1].strip() if paren else ""
            if len(sender.split()) >= 2 and len(_norm(sender)) >= 5:
                marker = "INBOUND: " + sender
            elif company:
                marker = "INBOUND: %s (%s)" % (sender.split()[0], company)
            else:
                marker = None
            if marker:
                return {"exemption": "INBOUND", "marker": marker, "missing": None,
                        "evidence": "an inbound header from %s dated %s" % (sender.split()[0], when or "undated")}
            return dict(none, exemption="INBOUND",
                        missing="the inbound header for %s names no company, so it cannot anchor a marker; the sender's "
                                "surname or company must be on the record, from his own words; no exemption fits yet." % first)
        if re.search(r"\breply\b", head_text, re.I):
            return dict(none, exemption="INBOUND",
                        missing="an inbound header for %s in correspondence-log.md, from his paste of the message; "
                                "no exemption fits yet." % first)
    # APPLYING: a folder under documents/applications/ named for a company this picker mentions.
    try:
        apps = os.path.join(root, "documents", "applications")
        low = _norm(blob)
        if os.path.isdir(apps):
            for d in sorted(os.listdir(apps)):
                full = os.path.join(apps, d)
                if not os.path.isdir(full):
                    continue
                toks, acc = [], ""
                for t in re.split(r"[-_ ]+", d):
                    toks.append(t)
                    acc = _norm(" ".join(toks))
                    if len(acc) >= 5:
                        break
                has_artifact = any(f.lower().endswith((".docx", ".pdf", ".tex")) or f.lower() in ("job_posting.md", "jd.md")
                                   for f in os.listdir(full))
                if len(acc) >= 5 and acc in low and has_artifact:
                    return {"exemption": "APPLYING", "marker": "APPLYING: " + " ".join(toks), "missing": None,
                            "evidence": "an application folder holding the posting (documents/applications/%s)" % d}
    except Exception:
        pass
    if re.search(r"\bapplication\b|\bapplying\b|\bscreening answer|free.response", blob, re.I):
        return dict(none, exemption="APPLYING",
                    missing="a folder under documents/applications/ that holds the posting (job_posting.md), saved from the "
                            "live posting; no exemption fits yet.")
    # POSITIONING: a positioning-revision*.md that names the piece this picker is about.
    try:
        docs = os.path.join(root, "documents")
        heads_md = []
        for f in sorted(os.listdir(docs)):
            if f.startswith("positioning-revision") and f.endswith(".md"):
                for line in _read(os.path.join(docs, f)).splitlines():
                    if line.lstrip().startswith("#"):
                        heads_md.append(line.lstrip("# ").strip())
        words = re.findall(r"[A-Za-z0-9][\w'&\-]*", head_text)
        for n in (3, 2):
            for i in range(len(words) - n + 1):
                win = " ".join(words[i:i + n])
                if len(_norm(win)) >= 5 and any(_norm(win) == _norm(h) for h in heads_md):
                    return {"exemption": "POSITIONING", "marker": "POSITIONING: " + win, "missing": None,
                            "evidence": "a positioning-revision entry named \"%s\"" % win}
    except Exception:
        pass
    if re.search(r"positioning|headline|about section|theme line", blob, re.I):
        return dict(none, exemption="POSITIONING",
                    missing="a documents/positioning-revision*.md entry that names this piece, written from his own wording; "
                            "no exemption fits yet.")
    return none


def _block_lines(d):
    """The four lines of the block: what it is, the record found or missing, the marker, the pointer to --guide."""
    lines = ["⛔ AskUserQuestion BLOCKED by check_preview: BUILD GATE not passed.",
             "WHY THE GATE HAS NOTHING: " + gate_empty_reason()]
    shape = {"INBOUND": "a reply to someone who wrote to him first", "APPLYING": "application or interview content",
             "POSITIONING": "positioning copy about himself"}.get(d.get("exemption"))
    if d.get("marker"):
        lines.append("This picker looks like %s. The gate found %s." % (shape, d["evidence"]))
        lines.append("Add `%s` to the question and ask again. No record needs editing." % d["marker"])
    else:
        lines.append(("This picker looks like %s, but the record is missing: %s" % (shape, d["missing"])) if shape
                     else "No exemption record matches this picker: no exemption fits yet.")
        lines.append("If the block is right, present the Boss Match Scorecard ending in '👉 YOUR CALL' (workflow-checklist.md step 6, check_ats.py first) "
                     "and wait for his ruling; a green-board READY row has NOT passed this gate.")
    lines.append("Every exemption, in full: python3 scripts/check_preview.py --guide "
                 "(markers: WARM-RUNG:, RUNG12:, REFERRED:, FOLLOWUP:, INBOUND:, APPLYING:)")
    return lines


# The full exemption text the hook used to print on every block (kept verbatim; `--guide` prints it).
def _build_guide():
    return ("⛔ AskUserQuestion BLOCKED by check_preview: BUILD GATE not passed.\n"
                "▶ FIRST, CHECK WHETHER THIS BLOCK IS EVEN CORRECT. The scorecard prescribed below has "
                "no valid inputs at a warm, rung-1-2, referral, inbound or application shape (no boss, "
                "no company to screen, no lane). Each such shape has an exemption MARKER, and the block "
                "clears the moment the right one is present with its non-forgeable anchor:\n"
                "   (a) WARM rung (5/6/7 connector ask)? Exempt via `WARM-RUNG: <Full Name>` where the "
                "name appears in documents/warm-network.md AND the closeness store sanctions a warm "
                "shape for them.\n"
                "   (a2) Rung 1-2 zero-ask connect note to a 1st-degree contact? Exempt via "
                "`RUNG12: <Full Name>` where the name is a recorded connection (contact.jsonl or the "
                "newest Connections-*.csv export) AND the text carries no ask vocabulary.\n"
                "   (a3) Rung 8/9 REFERRAL through someone you know? Exempt via "
                "`REFERRED: <Contact> VIA <Introducer>` where the INTRODUCER appears in "
                "documents/warm-network.md and the closeness store sanctions a warm shape for them. A "
                "referral's contact is 2nd-degree by definition, so it can never satisfy the WARM-RUNG "
                "anchor — this is its marker.\n"
                "   (b) Follow-up/reply/thank-you to a company YOU contacted first? Exempt via "
                "`FOLLOWUP: <Company>`, which requires that company to carry a SENT record in "
                "outreach_log.md.\n"
                "   (b2) Replying to someone who wrote to YOU first (recruiter, inbound cold pitch, "
                "unsolicited note)? That is NOT a follow-up and has no SENT record. Exempt via "
                "`INBOUND: <Full Name>` where that person appears in an INBOUND event header in "
                "documents/correspondence-log.md. If it does not fire, the missing piece is the "
                "RECORD: capture the inbound verbatim first, then re-ask. Replying is authorized; "
                "applying is not.\n"
                "   (b3) Co-creating APPLICATION or INTERVIEW content (screening answers, free-response, "
                "interview stories) for a role already in flight? None of the above will fire, because "
                "there is no boss and no campaign. Exempt via `APPLYING: <Company>` where that company "
                "has a folder under documents/applications/ holding a real artifact (job_posting.md, the "
                "JD, or a cv_draft). If it does not fire, the missing piece is the FOLDER: save the "
                "posting first.\n"
                "▶ IF THE BLOCK IS CORRECT: this question shows drafted outreach text (a praise beat / "
                "hook / phrasing), but the decision ledger holds NO recorded BUILD ruling.\n"
                "Present the Boss Match Scorecard (badge · boss + lane · a 2-3 sentence org/product/"
                "why-this-boss narrative · the screen table · \'👉 YOUR CALL\') with all gaps CLOSED, and "
                "WAIT for an explicit build/skip ruling. The live-role verify (check_ats.py) must have run "
                "first — a 🟡 no-live-role verdict FORCES the radar register.\n"
                "A short go-ahead (\'build\', \'prep these\', \'go\') authorizes the ACTIVITY, not a "
                "specific company. A board row marked READY has NOT passed this gate.\n"
                f"Present the scorecard, let the human rule, then re-ask. See {RULES_DOC}.")


def main():
    if "--guide" in sys.argv[1:]:
        print(_build_guide())
        sys.exit(0)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail-open: no parseable input, don't block
    if payload.get("tool_name") != "AskUserQuestion":
        sys.exit(0)
    tool_input = payload.get("tool_input") or {}
    banned, _hit = _load_lists()
    hits = []
    try:
        _drafted = _carries_drafted_voice(tool_input)
    except Exception:
        _drafted = False
    try:
        from check_outreach import honesty_fails as _honesty_fails
    except Exception as _ie:
        print(f"⚠️  check_preview: check_outreach.honesty_fails did not import ({type(_ie).__name__}: {_ie}); "
              "option text is NOT checked against the send gate's honesty rules", file=sys.stderr)
        _honesty_fails = lambda _t: []   # fail open, loudly: this gate can block every picker
    try:
        for field, text in _strings_from_questions(tool_input):
            for w in banned:
                if _hit(str(text), w):
                    hits.append((field, w))
            if "—" in str(text):
                hits.append((field, "em dash (use commas)"))
            # BUG-202 item 3: text the SEND gate rejects (a retired figure, a dishonest role claim) is blocked here too, from the
            # one shared function. Scope: drafted-outreach PREVIEWS and LABELS only; descriptions discuss the rules.
            if (field.endswith(".preview") or field.endswith(".label")) and _drafted:
                for msg in _honesty_fails(str(text)):
                    hits.append((field, msg))
    except Exception:
        sys.exit(0)  # fail-open on any scan error
    if hits:
        lines = "; ".join(f"{f}: '{w}'" for f, w in hits[:12])
        print("⛔ AskUserQuestion BLOCKED by check_preview: banned AI-tell/format in the option text "
              f"the user will see. Fix and re-ask. Hits — {lines}. "
              "(Previews are in your voice; scrub them like an email body.)",
              file=sys.stderr)
        append_event("tell", "block", None, tool_input, _session_id(payload))
        sys.exit(2)  # block the tool call; stderr is fed back to the model

    # BUILD GATE: drafted outreach voice requires a real, human-supplied BUILD ruling first.
    try:
        _drafted_now = _carries_drafted_voice(tool_input)
        _exempt = None
        if _drafted_now:
            for _name, _fn in (("BUILD-RULING", _has_build_ruling), ("FOLLOWUP", _is_followup_to_sent_company),
                               ("WARM-RUNG", _is_warm_rung_to_known_contact), ("REFERRED", _is_referred_via_known_introducer),
                               ("RUNG12", _is_rung12_zero_ask_note), ("INBOUND", _is_reply_to_captured_inbound),
                               ("APPLYING", _is_cocreation_for_live_application), ("PORTFOLIO", _is_portfolio_self_content),
                               ("POSITIONING", _is_positioning_copy), ("DESIGN", _is_design_artifact_decision),
                               ("OPERATING", _is_operating_decision), ("NEXT-STEP", _is_next_step_ladder_picker)):
                if _fn(tool_input):
                    _exempt = _name
                    break
            if _exempt:
                append_event("gate", "exempt", _exempt, tool_input, _session_id(payload))
        if _drafted_now and _exempt is None:
            if _CLOSENESS_REFUSALS:
                # The closeness consult refused a claimed exemption. Say WHY and name the fix for
                # THIS contact — a fail-closed gate is only livable when the refusal carries the
                # 30-second path out of it, not a pointer to documentation.
                for _r in _CLOSENESS_REFUSALS[:3]:
                    print(f"⛔ {_r}", file=sys.stderr)
            # LEAD with the marker for THIS shape when it reads as a no-boss rung, so the operator is
            # not handed the scorecard prescription that cannot be followed here.
            _lead = _no_boss_rung_lead(tool_input)
            if _lead:
                print(_lead, file=sys.stderr)
            _d = {"exemption": None, "marker": None, "evidence": None, "missing": None}
            try:
                _d = diagnose_build_block(tool_input)
            except Exception:
                pass   # a broken diagnosis must never change pass or block; the generic lines print
            try:
                _bl = _block_lines(_d)
            except Exception:
                _bl = ["⛔ AskUserQuestion BLOCKED by check_preview: BUILD GATE not passed.",
                       "Every exemption, in full: python3 scripts/check_preview.py --guide"]
            for _line in _bl:
                print(_line, file=sys.stderr)
            append_event("gate", "block", _d["exemption"] if _d.get("marker") else None, tool_input, _session_id(payload))
            sys.exit(2)
    except SystemExit:
        raise
    except Exception:
        pass  # fail-open on any gate error

    _nudge_method_read(tool_input)
    sys.exit(0)


def _nudge_method_read(tool_input):
    """ADVISORY: a real decision should carry the METHOD's read, with its suggestion as option 1.

    Why: pickers that lead with the assistant's own preference get rejected, because the human is
    being asked to choose without seeing what the method they adopted would do. Presenting the
    method's reasoning first, in the method's own vocabulary, and defaulting to its suggestion,
    means the choice is informed by the playbook rather than by whatever the assistant favored.
    Set METHOD_TERMS in kit_config.py to the names your method goes by.

    Deliberately a NUDGE, not a block. The rule is about the QUALITY of an explanation, which no
    regex can judge, and blocking on a keyword would only teach the assistant to sprinkle that
    keyword into option text to get past the gate. Fires only on decision-shaped questions
    (3+ options) so it stays quiet on ordinary ones.
    """
    try:
        try:
            from kit_config import METHOD_TERMS
        except Exception:
            METHOD_TERMS = ["lacivita", "andy"]
        if not METHOD_TERMS:
            return
        for q in (tool_input.get("questions") or []):
            if not isinstance(q, dict):
                continue
            opts = q.get("options") or []
            if len(opts) < 3:
                continue
            blob = " ".join(
                [str(q.get("question", "")), str(q.get("header", ""))]
                + [str(o.get(k, "")) for o in opts if isinstance(o, dict)
                   for k in ("label", "description", "preview")]
            ).lower()
            if not re.search(r"\b(build|skip|send|apply|target|pursue|drop|pick|reach)\b", blob):
                continue
            if any(t.lower() in blob for t in METHOD_TERMS):
                continue
            print("house rule: this reads as a decision and carries no read from the method you "
                  "adopted. Give its reasoning in ITS vocabulary, and make its suggestion option 1 "
                  "/ Recommended. Name any deliberate divergence in the same breath.")
            return
    except Exception:
        return  # advisory only: never let the nudge affect the call

if __name__ == "__main__":
    main()
