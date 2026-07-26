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
try:
    from kit_config import (VOICE_MARKERS, VOICE_MARKER_PATTERNS, RULES_DOC,
                            LEDGER_PATH, LEDGER_KEYFILE)
except Exception:
    VOICE_MARKERS = ["yoursite.example"]
    VOICE_MARKER_PATTERNS = [r"\b(hi|hey|tgif),\s+[A-Z][a-z]+!", r"\b(praise|phrasing|beat|angle|hook)\b"]
    RULES_DOC = "documents/WORKFLOW-RULES.md"
    LEDGER_PATH = os.path.join("documents", "decision-ledger.jsonl")
    LEDGER_KEYFILE = "~/.jobsearch-ledger-key"

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

LEDGER = os.path.join(
    os.environ.get("CLAUDE_PROJECT_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    LEDGER_PATH,
)

# Markers that a question is carrying DRAFTED OUTREACH VOICE (a praise beat / hook / phrasing
# option), as opposed to an ordinary planning or scorecard question. Add your own recurring
# tics to VOICE_MARKERS in kit_config.py — the more of your voice is listed, the more reliably
# this tells a drafted message apart from an ordinary question.
#
# Compiled with NO blanket flags, deliberately. The previous version applied `re.I` to any pattern
# whose text happened to contain the word "praise", which is a coin flip dressed as a rule: a
# blanket `re.I` on a pattern holding a `[A-Z]` anchor makes that anchor match LOWERCASE, so an
# anchor meant to pin a proper noun matches any word at all and the check stops discriminating.
# If you want part of a pattern case-insensitive, scope it INLINE in kit_config.py:
#     r"(?i:warm-rung:)\s*([A-Z][\w'\-]+)"      <- marker loose, NAME still case-sensitive
VOICE_PATTERNS = [re.compile(p) for p in VOICE_MARKER_PATTERNS]

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
    key = _ledger_key()
    if not key:
        # KEY-DOWNGRADE FIXED: the check used to be `if key and not _mac_ok(...)`, so an absent,
        # empty or unreadable key SKIPPED signature verification entirely instead of failing
        # closed. One `rm` of the key file restored full forgeability, silently. No key means no
        # verifiable evidence means no authorization. The honest path is unaffected:
        # record_decision.py creates the key (0600) the first time it records a ruling, so a key
        # can only be missing when no signed ruling has ever been written.
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
        if not _mac_ok(row, key):
            continue  # forged or tampered row
        co = (row.get("company") or "").strip().lower()
        if not co:
            # SKELETON-KEY FIXED: a BUILD row with no parseable company used to authorize EVERY
            # question, globally and permanently, because the caller fell back to "cannot scope,
            # allow". An unscoped ruling now authorizes NOTHING. A ruling must name what it
            # authorizes, or it is not a ruling.
            continue
        found.add(co)
    return found


def _ledger_key():
    try:
        kf = os.path.expanduser(LEDGER_KEYFILE)
        if os.path.exists(kf):
            with open(kf, "rb") as fh:
                return fh.read().strip()
    except Exception:
        pass
    return b""


def _mac_ok(row, key):
    import hashlib, hmac
    fields = ("ts", "session", "question", "header", "answer", "ruling", "company", "source")
    payload = json.dumps(
        {f: row.get(f, "") for f in fields}, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")
    want = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, str(row.get("mac", "")))


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
    # WORD-BOUNDARY match, not a bare substring. A substring test lets a short authorized name
    # authorize an unrelated longer one: BUILD("Ad") would open a question about "Adobe", and
    # a ruling for "Alpha" would open one about "Alphabet Systems".
    return any(re.search(r"(?<![a-z0-9])" + re.escape(co) + r"(?![a-z0-9])", blob)
               for co in rulings)

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

    # (a) A GREETING ADDRESSED TO A NAME. Greeting word, optional "there", optional comma, then a
    #     capitalized name of one or two words, then any punctuation or a line break.
    if re.search(r"(?:^|[\n\r>\"'“]|\s\s)"
                 r"(?:hi|hey|hello|dear|greetings|good morning|good afternoon|good evening"
                 r"|morning|afternoon|tgif)"
                 r"[ \t]*,?[ \t]*(?:there[ \t]*,?[ \t]*)?"
                 r"([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)?)"
                 r"[ \t]*[!,.:;\n\r-]",
                 blob, re.I | re.M):
        # Addressing YOU is not drafted outreach — that is the assistant talking to you.
        #
        # Two bugs to keep fixed here. (1) `re.I` must NOT apply to the name anchor: "hi" matches
        # inside "W-hi-ch", and a case-insensitive [A-Z] then captures "ch", so any question
        # containing "Which" fails the exemption and blocks. Keep the greeting keyword loose via an
        # inline group, but require a REAL capital for the name. (2) Collect EVERY addressed name,
        # not the first: "Hi, Dana! … Hi, You!" must block, and "Hi, You! … Hi, Dana!" must not pass.
        addressed = re.findall(
            r"(?i:hi|hey|hello|dear|morning|good morning)[ \t]*,?[ \t]*([A-Z][a-z]+)", blob)
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
    except Exception:
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

def _roster_names_blob():
    """Lowercased text containing ONLY contact NAMES from documents/warm-network.md.

    The warm/referral exemptions anchor on the named person being a real 1st-degree contact, so we
    match NAMES only — never the whole file, which also holds Title/Company columns and prose.
    Otherwise a cold draft labelled `WARM-RUNG: Product Manager` (a Title cell) would satisfy the
    anchor and bypass the BUILD gate. Names come from two NAME-only sources:
      (1) the 'Name' column of every markdown table (located by its header), and
      (2) the 'Full 1st-degree roster' section (parse_network.py joins 'First Last' with two spaces).
    Fails closed (returns '') on any error.
    """
    try:
        repo = os.environ.get("CLAUDE_PROJECT_DIR") or \
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def _is_warm_rung_to_known_contact(tool_input):
    """A WARM-rung message (LaCivita 5/6/7) to a real 1st-degree contact is BUILD-gate-EXEMPT.

    A warm rung has no scorecard, no boss, no company to screen and no praise beat, so there is
    nothing for a company-scoped BUILD ruling to attach to; mail-draft.sh's WARM profile gates it on
    --targets dedup instead. Non-forgeable anchor, BOTH must hold: (a) an explicit
    `WARM-RUNG: <Full Name>` marker in the question, AND (b) that person appearing in
    documents/warm-network.md (your own 1st-degree export). A cold boss is by definition not in it.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    m = re.search(r"(?i:warm[-\s]?rung:)\s*([A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){1,3})", blob)
    if not m:
        return False
    name = " ".join(m.group(1).split())
    return _name_in_roster(name, _roster_names_blob())


def _is_referred_via_known_introducer(tool_input):
    """A REFERRAL (LaCivita rung 8/9) is BUILD-gate-EXEMPT. The contact is 2nd-degree by definition,
    so the anchor is the INTRODUCER, not the stranger. Non-forgeable, BOTH must hold: (a) an explicit
    `REFERRED: <Contact> VIA <Introducer>` marker, AND (b) the INTRODUCER appearing in
    documents/warm-network.md. A cold boss-hunt cannot launder itself as a referral without naming a
    real 1st-degree contact as the source.
    """
    blob = " ".join(str(t) for _, t in _strings_from_questions(tool_input or {}))
    m = re.search(r"(?i:referred:)\s*[A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){0,3}\s+(?i:via)\s+"
                  r"([A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){0,3})", blob)
    if not m:
        return False
    introducer = " ".join(m.group(1).split())
    return _name_in_roster(introducer, _roster_names_blob())


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
        repo = os.environ.get("CLAUDE_PROJECT_DIR") or \
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def main():
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
        for field, text in _strings_from_questions(tool_input):
            for w in banned:
                if _hit(str(text), w):
                    hits.append((field, w))
            if "—" in str(text):
                hits.append((field, "em dash (use commas)"))
    except Exception:
        sys.exit(0)  # fail-open on any scan error
    if hits:
        lines = "; ".join(f"{f}: '{w}'" for f, w in hits[:12])
        print("⛔ AskUserQuestion BLOCKED by check_preview: banned AI-tell/format in the option text "
              f"the user will see. Fix and re-ask. Hits — {lines}. "
              "(Previews are in your voice; scrub them like an email body.)",
              file=sys.stderr)
        sys.exit(2)  # block the tool call; stderr is fed back to the model

    # BUILD GATE: drafted outreach voice requires a real, human-supplied BUILD ruling first.
    try:
        if (_carries_drafted_voice(tool_input)
                and not _has_build_ruling(tool_input)
                and not _is_followup_to_sent_company(tool_input)
                and not _is_warm_rung_to_known_contact(tool_input)
                and not _is_referred_via_known_introducer(tool_input)):
            print(
                "⛔ AskUserQuestion BLOCKED by check_preview: BUILD GATE not passed.\n"
                "This question shows drafted outreach text (a praise beat / hook / phrasing), "
                "but the decision ledger holds NO recorded BUILD ruling.\n"
                "Present the Boss Match Scorecard (badge · boss + lane · a 2-3 sentence org/product/"
                "why-this-boss narrative · the screen table · \'👉 YOUR CALL\') with all gaps CLOSED, and "
                "WAIT for an explicit build/skip ruling. The live-role verify (check_ats.py) must have run "
                "first — a 🟡 no-live-role verdict FORCES the radar register.\n"
                "A short go-ahead (\'build\', \'prep these\', \'go\') authorizes the ACTIVITY, not a "
                "specific company. A board row marked READY has NOT passed this gate.\n"
                f"Present the scorecard, let the human rule, then re-ask. See {RULES_DOC}.",
                file=sys.stderr,
            )
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
    means the choice is informed by the playbook rather than by whatever the assistant favoured.
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
