#!/usr/bin/env python3
"""check_outreach.py — send-time conformance tripwire for a boss-hunt email body.

Mechanizes the deterministic slice of the pre-fire conformance check (the voice/format pass
plus the honesty-figure scrub) that slips in practice — a banned filler word leaks into a real
email under volume, every time, unless something mechanical catches it. It does NOT judge
praise genuineness or fit; that stays human. Called by mail-draft.sh on --body-file; a FAIL
should stop the send until fixed.

Your site, your signature name and your retired figures come from kit_config.py — fill that
in first. The retired-figure lists ship EMPTY, so until you populate them this checks format
and vocabulary only.

Usage:  scripts/check_outreach.py <body.txt>
Exit:   0 = clean · 1 = FAIL (issues printed) · 2 = usage/no file
"""
import sys, os, re, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from kit_config import (OWNER_NAME, OWNER_FIRST, OWNER_SITE, RETIRED,
                            RETIRED_PATTERNS, ROLE_IMPLY_PATTERNS, OUTCOME_VERBS)
except Exception:  # standalone fallback — placeholders, so the checks are visibly inert
    OWNER_NAME, OWNER_FIRST, OWNER_SITE = "Your Name", "You", "yoursite.example"
    RETIRED, RETIRED_PATTERNS, ROLE_IMPLY_PATTERNS = [], [], []
    OUTCOME_VERBS = ["taken", "led", "built", "run", "drove", "driven", "shipped"]

# kit issue #64: the outcome-verb branch used to be hard-coded to product-management verbs
# (taken/drove/driven/led/shipped/built), scoped in the SCRIPT rather than in kit_config, so a
# business-analyst or process-improvement claim describing the same class of result in different
# words ("migrated", "consolidated", "automated", ...) missed the gate. Built once here and reused
# by both ingredients 1 and 5 below, so the two branches cannot drift out of sync with each other.
_OUTCOME_VERB_RE = r"(?:" + "|".join(re.escape(v) for v in OUTCOME_VERBS) + r")"

BANNED = [  # AI tells + filler words (writing-style-guide.md "Zero AI tells")
    "actually", "honestly", "genuinely", "simply", "really", "exactly", "exact",
    "leverage", "delve", "seamless", "robust", "passionate", "proven track record",
    "tapestry", "testament", "in today's fast-paced", "that's the beauty of",
    # ── no-slop vocabulary (adapted from petergyang/no-ai-slop, MIT). Hard-block tier: none of
    # these has a legitimate use in a warm, plain outreach register.
    "foster", "utilize", "facilitate", "streamline", "cutting-edge", "paradigm shift",
    "game changer", "realm", "beacon", "multifaceted", "meticulous", "intricate",
    "paramount", "transformative", "elevate", "embark", "supercharge", "ever-evolving",
    "myriad", "plethora", "vibrant", "boasts", "empower", "furthermore", "moreover",
]
# SOFT = warn, never block. These adverbs are CONTEXT-DEPENDENT: cut them when they add nothing,
# keep them when they carry emphasis, uncertainty, contrast, or your natural spoken rhythm.
# BANNED is hard-fail only, so putting them there would block true sentences — "I just left my
# last role" is cadence, not slop. A warn leaves the judgment with the human.
SOFT = [
    "just", "literally", "truly", "fundamentally", "importantly", "crucially",
    "inherently", "inevitably", "notably", "arguably", "ultimately", "very", "quite",
]

# Ask-shaped vocabulary for a rung 1-2 LinkedIn invitation note. A connection request may ask to
# connect and share networks, nothing more; any role pitch is a hard fail. check_preview reuses this
# list for its rung 1-2 zero-ask exemption, so it lives here as one source of truth for both gates.
_INVITATION_ASK = [
    (re.compile(r"on your radar", re.I), '"on your radar" is a rung 3-4 ask'),
    (re.compile(r"\bPM like me\b|looking for a (?:PM|product manager)", re.I),
     'pitching yourself for a role'),
    (re.compile(r"\bbe considered\b|when (?:you have|a spot|you build out)", re.I),
     'asking to be queued for an opening'),
    (re.compile(r"\b(?:just )?applied for|I'?m applying|let'?s talk\b", re.I),
     'an application or meeting ask'),
    (re.compile(r"work directly for you", re.I), 'the hire-me ask'),
]
# Banned words that DOUBLE AS COMPANY NAMES. Every one of these is a plausible employer, and a
# boss-hunt names the company in nearly every sentence. For these, only a LOWERCASE occurrence
# counts as a defect.
NAME_PRONE = frozenset({
    "foster", "streamline", "realm", "beacon", "elevate", "embark", "supercharge",
    "vibrant", "empower", "paramount", "transformative", "facilitate", "utilize",
})


# ── SANCTIONED PRAISE CONSTRUCTION ───────────────────────────────────────────────────────────
# The LaCivita appreciation ingredient is "I was impressed with your [X]", which a plain-spoken
# house style bans as consultant-speak. The reference ruling: follow the METHOD as the baseline so
# it can be evaluated and iterated, but carry the praise beat in "I really like ..." instead.
# "really" is a BANNED filler adverb everywhere else and STAYS banned — this carve-out whitelists
# it ONLY inside that exact construction, so the appreciation beat is sanctioned while stray
# filler ("this really works", "really glad") still fails. A narrow phrase span, never a blanket
# unban. Edit the list if your own praise beat uses a different construction.
SANCTIONED_ADVERB_PHRASES = [
    re.compile(r"\bI\s+really\s+like\b", re.I),
]


def sanctioned_phrase_spans(body):
    """[(start, end)] byte spans where a BANNED word sits inside a sanctioned praise construction.

    Only the whitelisted phrases in SANCTIONED_ADVERB_PHRASES qualify. A banned-word match whose
    position falls inside one of these spans is appreciation, not filler, and is not a hit.
    """
    return [(m.start(), m.end()) for pat in SANCTIONED_ADVERB_PHRASES
            for m in pat.finditer(body)]


def known_companies() -> set:
    """Lowercased company names the pipeline already tracks.

    WHY THIS EXISTS. Several gates identify a company by scanning for a Capitalized token, and a
    lowercase brand defeats every one of them silently. In the reference pipeline one lowercase
    company broke three mechanisms in a single session, the worst being the decision recorder,
    which wrote an empty company and so left a real BUILD ruling UNSCOPED. An unscoped ruling
    authorizes nothing, so a decision the human had plainly given went on to block the next
    question. Lowercase brands are common, so this will recur.

    A RECOGNITION list, never a pattern: a lowercase token counts only when the pipeline already
    knows that company, so "for the team" still resolves to nothing. Fails to an empty set, which
    restores the old Capitalized-only behaviour rather than breaking a gate.
    """
    out = set()
    repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    try:
        import csv
        with open(os.path.join(repo, "job_search_tracker.csv"), encoding="utf-8",
                  errors="ignore") as fh:
            for row in csv.DictReader(fh):
                co = (row.get("company") or "").strip()
                if len(co) > 2:
                    out.add(co.lower())
    except Exception:
        pass
    try:
        with open(os.path.join(repo, "documents", "green-board.md"), encoding="utf-8",
                  errors="ignore") as fh:
            for m in re.finditer(r"^\|\s*\*{0,2}([^|*]{3,40}?)\*{0,2}\s*\|", fh.read(), re.M):
                out.add(m.group(1).strip().lower())
    except Exception:
        pass
    # DURABLE STORE, ADDED ALONGSIDE. The regex above reads the FIRST cell of every board row, so on
    # a numbered table it collects row numbers and on a sparse table it collects whatever leads. The
    # store is header-driven, so it names the company column correctly across every table shape.
    #
    # ⚠️ ADDED, NOT SUBSTITUTED, and deliberately. This set widens a GATE: a name in it is a name the
    # gate recognizes. Swapping the loose regex for the precise store would make the gate NARROWER,
    # and a narrower gate here fails open. Union keeps every name either source knows.
    try:
        import state as _state
        for _rec in _state.from_source("company", "green-board"):
            _name = (_rec.get("payload") or {}).get("name")
            if _name and len(_name) > 2:
                out.add(_name.strip().lower())
    except Exception:
        pass
    # RADAR-REGISTER COMPANIES. The two sources above only carry companies that reached the
    # TRACKER or the GREEN BOARD, and neither is where a boss hunt STARTS. In the reference
    # pipeline a company was screened, boss-verified and BUILD-ruled by the human, yet the
    # decision recorder still wrote an empty company, because the name existed nowhere in this
    # set. The gate then correctly refused to honour an unscoped row, so a decision the human had
    # plainly given blocked the send. Same defect class as the lowercase-brand case above, one
    # layer earlier in the funnel: that name was lowercase, this one was simply NEW.
    #
    # These stay a RECOGNITION list, not a pattern. The criterion is "a store that carries a
    # company in a dedicated column", and both of these do. They are pipeline-written records of
    # real, screened companies, so nothing a scorecard never touched can enter this way.
    for rel, field in (("documents/state/boss.jsonl", "company"),
                       ("documents/state/employer-segments.jsonl", "employer")):
        try:
            with open(os.path.join(repo, rel), encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    co = (json.loads(line).get(field) or "").strip()
                    if len(co) > 2:
                        out.add(co.lower())
        except Exception:
            pass
    return out


# ── QUOTE EXEMPTION ─────────────────────────────────────────────────────────────────────────
# A banned word inside SOMEONE ELSE'S quoted words is not an AI tell in your voice, it is
# reporting. This fired live: a scorecard preview quoting a CEO verbatim was BLOCKED on a banned
# word, and the only ways to satisfy the gate were to paraphrase her or to silently edit a real
# person's words. Both are worse than the thing the gate was protecting against.
#
# ⚠️ THE DESIGN TRAP, and why quote marks alone are NOT enough. Two-stage pickers put YOUR OWN
# candidate lines in quotes (`Sample line: "..."`). Those are the highest-value text on the screen
# and the whole reason the preview gate exists. Exempting every quoted span would switch the gate
# off precisely where it earns its keep. So the exemption requires an ATTRIBUTION CUE near the
# quote, and a markdown blockquote counts on its own because that is how inbound verbatim is kept.
#
# Second belt: on body-length text, if quoted spans cover most of it, no exemption is granted.
# A draft body is not 80% quotation; something wrapped that heavily is either a pasted artifact
# or an attempt to launder a banned word through quote marks.
ATTRIBUTION_CUES = (
    r"said", r"says", r"saying", r"wrote", r"writes", r"written", r"tells", r"told",
    r"verbatim", r"quotes?", r"quoted", r"quoting", r"according to", r"per\b",
    r"in (?:her|his|their) own words", r"(?:her|his|their) (?:own )?words",
    r"HERS", r"HIS", r"THEIRS", r"asked", r"replied", r"answered", r"put it",
)
_CUE_RE = re.compile("|".join(ATTRIBUTION_CUES), re.I)
_QUOTE_COVERAGE_CAP = 0.80
_CAP_MIN_LEN = 200          # below this, text is a preview line, not a draft body


def attributed_quote_spans(body):
    """Char ranges of quoted text attributable to someone other than the sender."""
    spans = []
    for m in re.finditer(r"(?m)^[ \t]*>.*$", body):
        spans.append((m.start(), m.end()))
    for m in re.finditer(r'"[^"\n]{1,400}"|“[^”\n]{1,400}”', body):
        if _CUE_RE.search(body[max(0, m.start() - 90):m.start()]):
            spans.append((m.start(), m.end()))
    if not spans:
        return []
    covered = sum(e - s for s, e in spans)
    if len(body) >= _CAP_MIN_LEN and covered / len(body) > _QUOTE_COVERAGE_CAP:
        return []
    return spans


def _in_spans(pos, spans):
    return any(s <= pos < e for s, e in spans)


def exempted_banned(body):
    """[(word, snippet)] for banned words found but sitting inside an attributed quote.

    Surfaced as an advisory so an exemption is never silent. A gate that quietly stops checking
    is worse than one that argues.
    """
    spans = attributed_quote_spans(body)
    out = []
    if not spans:
        return out
    for w in BANNED:
        for m in re.finditer(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", body, re.I):
            if _in_spans(m.start(), spans):
                out.append((w, body[max(0, m.start() - 30):m.end() + 30].replace("\n", " ").strip()))
                break
    return out


def banned_hit(body, word):
    """True when `word` appears in `body` as VOCABULARY, not as part of a proper noun.

    WHY THIS IS NOT A PLAIN REGEX
        Adding the no-slop word list brought in a dozen words that are also company names. A
        real send once opened on the recipient's own employer, named by its short form at a
        sentence start, and a lowercase regex hard-failed it. The gate would have fired hardest
        on exactly the messages it exists to protect, because a boss-hunt names the company in
        nearly every sentence.

    TWO TIERS
        NAME_PRONE words count ONLY when lowercase. Capitalization at a sentence start proves
        nothing, so nothing short of knowing the company name distinguishes a name from a verb.
        The deliberate trade is a false NEGATIVE on a sentence-initial verb use against never
        blocking a true send. You review every message; the gate catches what you would
        not notice, it does not argue with you about a recipient's name.

        Every other word keeps a case-insensitive match, guarded only against a Capitalized
        proper-noun PHRASE (a banned word paired with another Capitalized token). At a sentence
        start the capital is uninformative, so the safe reading there is "it is vocabulary": none
        of those words is a plausible employer name, and a missed AI tell ships while a false
        positive only asks you to look.
    """
    _spans = attributed_quote_spans(body)
    _sanc = sanctioned_phrase_spans(body)    # the appreciation beat — praise, not filler

    if word in NAME_PRONE:
        return any(not _in_spans(m.start(), _spans) for m in
                   re.finditer(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", body))

    for m in re.finditer(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", body, re.I):
        if _in_spans(m.start(), _spans):
            continue                         # someone else's words, attributed — not an AI tell
        if _in_spans(m.start(), _sanc):
            continue                         # sanctioned praise construction — not filler
        if not body[m.start():m.end()][:1].isupper():
            return True                      # lowercase use — plain vocabulary
        before, after = body[max(0, m.start() - 40):m.start()], body[m.end():m.end() + 40]
        if not before.strip() or re.search(r"[.!?:>•\-]\s*$|\n\s*$", before):
            return True                      # sentence start — the capital means nothing
        prev_tok = re.search(r"([A-Za-z][\w'’-]*)\W*$", before)
        next_tok = re.search(r"^\W*([A-Za-z][\w'’-]*)", after)

        # "I" is a capital that says nothing about its neighbour. Without this exclusion,
        # "Actually, I disagree" reads as a proper-noun phrase and a banned word escapes.
        def _is_name_tok(t):
            return bool(t) and t.group(1) != "I" and t.group(1)[:1].isupper()

        if not (_is_name_tok(prev_tok) or _is_name_tok(next_tok)):
            return True                      # Capitalized but standing alone — not a name
    return False
# RETIRED (literal strings) and RETIRED_PATTERNS (variant-tolerant regexes) both come from
# kit_config.py and ship EMPTY — they encode YOUR corrected figures, and someone else's are
# worthless to you. Populate both.
#
# Why a literal list is not enough: retire "2 million people use X" and the variant
# "2 million people CAN use X" still sails through — and that variant is usually sitting in
# your own writing-samples file, which is the corpus every future draft is written FROM. A
# literal-only list leaves the sample corpus as an active re-contamination channel. Write the
# pattern, not the string.


# ── PORTED METHOD LAYER (2026-08-05): the O-A-K ingredient check, the message-type
# vocabulary, and the invitation-note gate. Previously the kit shipped a lighter linter;
# these are METHOD rather than one person's register, so they belong in every copy.
# ── ANDY'S 7 MESSAGE INGREDIENTS + THE O-A-K TEST (added 2026-07-20) ────────────────────────
# Source: Job Search Boot Camp, "Searching" digest p.12-13 (your licensed Milewalk PDF).
# Coverage-map finding: these had ZERO repo presence — not a script, not a checklist, not a line
# of prose — despite being Andy's core message-quality gate. Every other message rule we enforce
# (voice, honesty, praise-source) sits DOWNSTREAM of them.
#
#   1 Who you are · 2 Why you chose them · 3 What you want/why reaching out ·
#   4 You did your research · 5 What you can offer them · 6 You're grateful · 7 The next step
#
# His annotation on the slide: "#2 + #4 is what shows a O-A-K message" — O-A-K = ONE-OF-A-KIND:
#   "Does this message look like it's the only one in existence?
#    Does it look like it could ONLY be sent to this person?"
#
# MECHANIZING O-A-K. The honest proxy for "could ONLY be sent to this person" is: strip out
# your own boilerplate vocabulary and see whether any specific anchor remains. A body whose
# only proper nouns are your own credentials (Rise8 / OnPay / CalPEST / Claude Code) is a template
# with a mail-merged first name — exactly the message Andy says NOT to send. Requires >= 2
# distinct THEIR-side proper nouns; a greeting name alone is one, and one is not enough.
#
# CALIBRATION. These are FAILs, so they were calibrated against your ACTUAL sent corpus in
# outreach_log.md, not against an idea of a good message.
#
# ⚠️ INGREDIENT 6 ("you're grateful") — RULING REVERSED 2026-07-24. This block used to read that
# gratitude was "ABSENT from your strongest sends" and treat its absence as a deliberate divergence
# from Andy. That was an INFERENCE FROM THE ARCHIVE, not a ruling: the sent corpus lacked a
# thank-you beat because nobody had put one in, and the calibration then wrote that absence down as
# your voice. you corrected it on a warm-reply note: **"No, we need to have the grateful
# part."** He wants all SEVEN of Andy's ingredients.
#
# It stays a WARN rather than a FAIL, because a warm in-thread reply legitimately drops it, but the
# WARN now means "you are missing one of the seven", not "this is fine, it is your voice". The wider
# lesson: calibrating a gate against the archive encodes whatever the archive happens to contain,
# including its gaps. An absence is only a preference once the human says so.
#
# RUNG-AWARE. Andy's ask shrinks as relationship distance shrinks, so the required ingredients
# differ. A warm 1st-degree intro request has no praise beat and no credential dump by design;
# holding it to the cold-boss shape would flag correct messages.
# ⛔ YOUR OWN BOILERPLATE VOCABULARY, and it must come from kit_config, not from here.
# These are the proper nouns that appear in EVERY message you send (your name, your employers,
# your products, your stack), so they prove NOTHING about who a given message is for. The O-A-K
# test below subtracts them before asking "could this only have been sent to this person?"
# ⚠️ Ships EMPTY on purpose. Someone else's boilerplate is worthless to you, and a populated
# default would quietly weaken the one test that catches a mail-merged opener.
try:
    from kit_config import OWNER_BOILERPLATE as _OWNER_BOILERPLATE
except Exception:
    _OWNER_BOILERPLATE = []
MINE = set(x.lower() for x in _OWNER_BOILERPLATE) | {
    # Grammatical filler only. Nothing here identifies a person.
    "the", "and", "for", "with", "you", "your", "i", "my", "we", "our", "at", "to", "of", "in",
    "on", "a", "an", "is", "are", "was", "were", "it", "that", "this",
}


# Common words that legitimately START a sentence and are not proper nouns. Needed because the
# first calibration run threw away every sentence-initial capital, which silently DELETED the
# company name from bodies like the Xano send ("Xano giving builders a real backend…") and then
# failed it for having no specifics. A positional rule cannot tell "Xano" from "Getting"; a
# vocabulary rule can.
SENTENCE_STARTERS = {
    "the","a","an","it","its","this","that","these","those","there","here","you","your","yours",
    "we","our","i","my","he","she","they","their","what","who","whom","whose","when","where",
    "why","how","if","and","but","or","so","because","after","before","while","since","as",
    "getting","letting","turning","building","making","taking","running","owning","having",
    "being","doing","giving","seeing","looking","working","shipping","writing","reading",
    "most","many","some","every","each","both","all","no","not","now","then","just","even",
    "one","two","three","first","last","next","one-of-a-kind","nothing","everything","someone",
    "let","let's","would","could","should","will","can","may","might","must","do","does","did",
    "is","are","was","were","been","be","am","for","from","with","without","about","into","on",
    "at","by","to","of","in","out","up","down","over","under","again","still","also","too",
}


# ── MESSAGE TYPES (--type) ───────────────────────────────────────────────────────────────────
# "outreach" is a FIRST CONTACT (cold boss-hunt or warm intro ask). Everything else is IN-THREAD:
# a message to someone already in the process, where the thread itself carries the context that a
# first contact has to build from nothing. Rules about the SHAPE of a first contact (the greeting,
# the signature block, the praise beat, the 7 ingredients, the O-A-K anchor) are gated on this;
# voice and honesty rules are not, and run on every type.
#
# The aliases are not cosmetic. mail-draft.sh maps `--rung thank-you` to `--type thankyou` and
# `--rung follow-up` to `--type followup` (no hyphen), so an in-thread set spelled only with
# hyphens silently classified every mail-draft thank-you and follow-up as a first contact.
#
# "peer" is its own third bucket, neither cold-boss-outreach nor in-thread: a first contact, in
# the shape sense (greeting/signature/dense-block rules apply), that is not an ask for a job and
# so does not owe the cold-boss 7-ingredient/O-A-K block. See the PEER_TYPES comment below.
KNOWN_TYPES = {"outreach", "reply", "follow-up", "thank-you", "bump", "reunion", "invitation", "peer"}


TYPE_ALIASES = {
    "thankyou": "thank-you", "thank_you": "thank-you", "thanks": "thank-you",
    "followup": "follow-up", "follow_up": "follow-up", "bump-email": "bump",
    "intro": "outreach", "cold": "outreach", "": "outreach",
}


IN_THREAD_TYPES = {"reply", "follow-up", "thank-you", "bump"}


# NO-ASK types (added 2026-07-24). A REUNION is a first contact that carries NO ask: a close
# friend gone quiet gets a note with nothing requested, and the outreach comes later as a separate
# message ([[reunion-before-outreach-close-friends]], ruled 2026-07-22 and mechanized here).
#
# Why it needed its own name rather than reusing a type: every existing non-outreach type is
# IN-THREAD, and a reunion is not. Labelling one `reply` to reach the right gate profile would be
# lying to the linter to get a weaker check, which is the exact failure this file already guards
# against (an unrecognized --type used to silently SKIP the O-A-K gate on a cold boss-hunt).
#
# It shares the in-thread PROFILE because the reasons line up: no 7-ingredient/O-A-K check (there
# is no ask to be one-of-a-kind about), and no signature block (a portfolio URL in a note to a
# friend is the transactional tell the reunion rule exists to prevent). Everything else still
# runs: AI-tells, em dashes, spaced slashes, retired figures, engineer-implication. A note to a
# friend has to be just as honest and just as clean as a cold email.
NO_ASK_TYPES = {"reunion", "invitation"}


# ── THE PEER / COMMON-INTEREST NOTE ─────────────────────────────────────────────────────────────
# A rung 1-2 note to someone you are ALREADY connected to — celebrate their public work, one light
# give, one question. It owes a genuine reason for reaching out and staying human; it does NOT owe
# the cold-boss ask (who you are / why you chose them / what you want / one-of-a-kind anchor).
# That block is built for a "work directly for you" pitch, so running it on a peer note is a
# category error, not a quality check.
#
# ⛔ NOT the same shape as "invitation". Invitation is a LinkedIn CONNECTION REQUEST to a
# stranger — 300-char cap, no signature possible, ask = acceptance. Peer is a normal-length
# note/email to an EXISTING 1st-degree connection — full body, a real signature, no character cap.
# Deliberately in NEITHER NO_ASK_TYPES nor IN_THREAD_TYPES, so the greeting/signature/dense-block
# checks a first-contact-length note still owes keep running.
#
# WHAT STAYS ON: banned-word/AI-tells, em dash, spaced slash, retired figures, role-implication,
# greeting line, signature block (rung-aware), dense-block, generic-praise, length. Only the
# 7-ingredient/O-A-K composite is structurally exempt below — mtype != "outreach" already routes
# it to WARN-only, same as every other non-outreach type.
PEER_TYPES = {"peer"}


# WARM LANE (added 2026-07-26 for the rung-aware signature below). These are the rungs where the
# recipient already knows who he is and how to reach him, so the portfolio URL is optional.
# ⚠️ This list ALSO lives in scripts/check_followups.py, which uses it to decide whether a send
# arms a follow-up at all. Two copies of one rule drift, and the copy nobody re-reads is the one
# that drifts, so tests/test_style.py pins them equal. Change both or change neither.
WARM_RUNGS = ("warm", "referred", "event", "off-ladder")
# ── THE RUNG VOCABULARY, and the flag mixup it exists to refuse (kit issue #21, 2026-08-11) ───────
# `--type` was hardened against unrecognized values on 2026-07-21. `--rung`, parsed eleven lines
# away, never was: an unrecognized rung was not an error, it was silently "not warm", so the body got
# the COLD signature profile while mtype stayed "outreach" and the full 7-ingredient + O-A-K block
# ran. The operator got a confident, detailed, WRONG failure.
#
# The reporter staged a no-ask reunion note, ran `--rung reunion`, and was told it was missing an
# ask, a "what you can offer them" beat and a portfolio sign-off. The obvious repair is to ADD AN ASK
# TO A NO-ASK NOTE, so the gate would have talked him into breaking the rule the gate enforces.
#
# ⛔ THE SET IS log_linkedin_send.RUNGS MINUS `reunion`, AND THAT ONE OMISSION IS THE WHOLE FIX.
# A reunion is a message TYPE in this script, never a rung: it reaches the no-ask profile through
# NO_ASK_TYPES. The logger legitimately records a send AT rung reunion, so the two vocabularies
# diverge here by exactly one word, deliberately, and the parity test below pins the difference so
# the divergence stays a decision rather than drift.
#
# ⚠️ A FIRST DESIGN KEYED ON "was --type also given" AND IT WAS WRONG. It would have refused
# `--rung reply` with no `--type`, which is a legitimate shape the suite already exercises
# (test_10_ingredient_failure_names_the_type_flag lints an in-thread body bare on purpose, to prove
# the failure NAMES the flag that fixes it). Caught by running the suite, not by reading it.
#
# ⚠️ Typed here rather than imported from log_linkedin_send: check_outreach is imported by
# check_style.py, check_preview.py, verify_resume.py and record_decision.py, and widening their
# import graph to fix a flag is a bigger change than the fix. Drift is covered by a parity test
# instead, the shape test_07d already uses for WARM_RUNGS.
KNOWN_RUNGS = frozenset({
    "cold-boss", "cold-stranger", "warm", "referred", "event", "off-ladder",
    "reply", "thank-you", "follow-up", "application",
})
RUNG_ALIASES = {"followup": "follow-up", "thankyou": "thank-you"}


def _validate_rung(raw):
    """Normalize a --rung value, or refuse with exit 2. Returns the normalized rung.

    ⚖️ Mirrors the --type validation below it: strip/lower, alias at the boundary, membership test,
    one line to stdout, exit 2. The two siblings now fail the same way.

    ⛔ FALL-THROUGH, stated because a gate written for one rung has bound the wrong rungs three times
    in this repo: an ABSENT --rung stays legal and unchanged (partner-starter/tests/test_gates.py
    shells out with no flags at all, and several checklists tell the operator to run it bare). Every
    one of the ten known rungs passes untouched, with or without a --type. The only value this
    refuses is one that is not a rung.
    """
    rung = (raw or "").strip().lower()
    if not rung:
        return ""
    rung = RUNG_ALIASES.get(rung, rung)
    if rung not in KNOWN_RUNGS:
        msg = f"unknown --rung '{rung}'. One of: " + " | ".join(sorted(KNOWN_RUNGS))
        # Name the likely repair. `reunion`, `invitation`, `bump` and `outreach` are all real
        # vocabulary in this script, just for the OTHER flag, which is what makes the mixup ordinary
        # rather than exotic.
        as_type = TYPE_ALIASES.get(rung, rung)
        if as_type in KNOWN_TYPES:
            msg += (f"\n   '{rung}' is a message TYPE here, not a rung. Did you mean "
                    f"--type {as_type}?")
        print(msg)
        sys.exit(2)
    return rung


# ── THE INVITATION NOTE (added 2026-07-27, ruled off the July numbers) ─────────────
# A LinkedIn connection request carrying a note. It shares the NO-ASK profile because the only
# thing the format can deliver is ACCEPTANCE: there is no reply box, no signature, no room for
# seven ingredients in 300 characters.
#
# WHAT THE DATA SAID. 45 went out in July carrying a rung 3-4 pitch ("Would love to be on your
# radar for a product role", "I heard you may be looking for a PM like me"). 7 were accepted
# (15.6%) and 2 of those ever wrote back (4.4% of all sent), which is indistinguishable from cold
# boss messaging at 4.8%. Scored as an ASK it looks like a failure. Scored as what it is, it
# converted 7 strangers into permanent 1st-degree connections, and 1st-degree is the pool the
# warm rungs draw from, which reply at 17.1%. **The channel is a roster builder, not a boss hunt.**
#
# THE RULING (you, 2026-07-27): keep the channel, strip the pitch, ask only to connect, and
# score it on acceptance rather than replies. That is Andy's template 1-2 verbatim ("at a minimum,
# I'd love to connect online and share networks").
#
# ⛔ WHAT THIS DOES NOT RELAX. Andy's warning stands and is not ours to soften: "DO NOT send a
# LinkedIn connection request to any bosses before you've made contact with them via these other
# techniques. And, DO NOT send them a connection request unless you have their permission."
# A clean rung 1-2 note to a non-boss is sanctioned. A connection request to the boss is not,
# whatever the note says, and that check lives at the SEND GATE where the target is known.
_INVITATION_MAX = 300  # LinkedIn's hard cap; over this it TRUNCATES silently, mid-sentence.


INGREDIENTS = [
    # (number, label, regex, hard-fail-for-cold, hard-fail-for-warm)
    (1, "who you are",
     r"\b(i'?m|i am)\s+(a|an)\b|\bbuilder\s+pm\b|\bproduct\s+manager\b|\bi'?ve\s+(spent|been)\b"
     r"|\bi\s+(have\s+)?" + _OUTCOME_VERB_RE + r"\b|\bi\s+ship\b",
     False, False),
    (2, "why you chose them",
     r"\b(is|are)\s+(a\s+)?(problem|work|company|question|the\s+kind|something|exactly)\b"
     r"|\bi\s+can'?t\s+stop\b|\bso\s+i'?m\s+saying\b|\bdrew\s+me\b|\bcaught\s+my\b"
     r"|\bwhy\s+i'?m\s+(writing|reaching)\b|\bwork\s+i\s+care\s+about\b"
     r"|\bi\s+(care|love|admire|follow)\b|\bbecause\b|\byour\s+work\b|\byour\s+\w+\s+is\b",
     False, False),
    # DIRECT-QUESTION CLAUSE added 2026-07-21. Ingredients 3 and 7 both LED with "on your radar",
    # and 3 is a HARD fail — so passing this linter effectively required that one phrase. Meanwhile
    # `documents/compass.md` diagnoses regulated-workflow (17 sends, 0 replies) with rule 3, "Ask a
    # question… the regulated ones asked nothing answerable," and the payments send that DID convert
    # asked about a named seat. The two mechanisms contradicted each other: the linter mandated the
    # shape the compass blames for the zero. A question addressed to the recipient is a STRONGER
    # statement of what you want and what happens next than a passive radar register, so it has to
    # count. Scoped to interrogatives that address THEM (contain "you"/"your"), so a rhetorical
    # question in the hook does not satisfy the ask on its own.
    (3, "what you want / why you're reaching out",
     r"\bon\s+your\s+radar\b|\bi'?d\s+love\s+to\b|\bwould\s+love\s+to\b|\bjust\s+a\s+hello\b"
     r"|\bsaying\s+(hello|hi)\b|\bi'?m\s+saying\b|\bi'?m\s+(reaching\s+out|writing)\b|\bopportunity\s+to\b"
     r"|\bintroduction\b|\bintroduce\b|\bconnect\b|\binterested\s+in\b|\bany\s+chance\b"
     r"|[^.?!]*\byour?\b[^.?!]*\?",
     True, True),
    (4, "you did your research (specific, THEIR side)", None, False, False),  # computed below
    (5, "what you can offer them",
     r"\$[\d,]+|\b\d+%|\b\d+x\b|\b0-to-1\b|\bzero\s+to\s+one\b|\b\d+\s*(million|billion|m\b|b\b|k\b)"
     r"|\bbuilder\s+pm\s+like\s+me\b|\bi\s+(have\s+)?" + _OUTCOME_VERB_RE + r"\b"
     # His give-back idiom is offering to SHARE what he knows — "trade/swap/compare notes",
     # "happy/glad to share/help" (proven across two real sends). Andy's ingredient 5
     # is "what you can offer them"; an offer of hard-won expertise is one, and the detector missed
     # it because it only recognized a demonstrated-metric offer. Added 2026-07-29.
     + r"|\b(swap|trade|compare)\s+notes\b|\b(happy|glad)\s+to\s+(swap|trade|share|compare|help)\b"
     # 🤝 OFFERING PEOPLE IS AN OFFER, and for a recruiter it is the BEST one. Added 2026-08-04 on
     # a note to a staffing director with 15 years placing technologists.
     # The note offered "if I run into a strong engineer or PM who's looking, I'll send them your
     # way", which is Andy's ingredient 5 in its purest form: candidates are a recruiter's currency,
     # and it costs you nothing. The detector failed the note anyway because it only knew about
     # metrics and about sharing expertise. Same defect shape as the 2026-07-29 addition above, one
     # idiom later.
     r"|\bsend\s+(them|him|her|folks|people|anyone|someone)\s+your\s+way\b"
     r"|\b(point|refer|introduce)\s+(them|him|her|folks|people|anyone|someone)\s+(to\s+you|your\s+way)\b"
     # ⏱️ OUTCOME VERBS BEYOND THE BUILD LIST. "I cut secure pipeline release time from months to
     # minutes" is a demonstrated result with no digit in it, so the numeric branch missed it and the
     # verb branch (taken/drove/led/shipped/built) did not carry "cut" or "reduced". A months-to-
     # minutes claim is the strongest offer in that whole note.
     r"|\bi\s+(cut|reduced|shrank|took)\b[^.?!]*\bfrom\b[^.?!]*\bto\b",
     True, False),
    (6, "you're grateful", r"\bthank(s| you)\b|\bgrateful\b|\bappreciate\b", False, False),
    (7, "what the next step would be",
     r"\bon\s+your\s+radar\b|\btalk\b|\bconversation\b|\bchat\b|\bnext\s+step\b|\bfind\s+a\s+time\b"
     r"|\bhear\s+back\b|\bforward\s+my\b|\bfollow\s+up\b|\bmake\s+an?\s+intro"
     r"|[^.?!]*\byour?\b[^.?!]*\?",  # a question TO them is the next step: their answer
     False, False),
]


def _their_anchors(body):
    """The O-A-K substrate: specifics that belong to THEM, not to your boilerplate.

    Two kinds count, because both are things a template cannot carry:
      • proper nouns that are not your own vocabulary (their name, their product), and
      • a figure inside a clause about them ("You've moved $1B+ for schools…").
    The figure half was added after calibration: the Cheddar Up send never names the company,
    carries its whole specificity in "$1B+ for schools, teams, and nonprofits", and was being
    failed as a template. It is the opposite of a template.
    """
    toks = set()
    for m in re.finditer(r"\b([A-Z][a-zA-Z0-9]{1,})\b", body):
        t = m.group(1)
        if t.lower() in MINE or t.lower() in SENTENCE_STARTERS or len(t) < 2:
            continue
        toks.add(t)
    for m in re.finditer(r"\b([A-Z][a-z]+[A-Z][a-zA-Z0-9]*|[A-Z]{2,})\b", body):
        if m.group(1).lower() not in MINE:
            toks.add(m.group(1))
    # LOWERCASE-BRAND ANCHORS. Naming the company IS a their-side specific, and a lowercase brand
    # is still the company's name. Without this, a message naming brightwheel twice was failed as a
    # mail-merge template because the scanner only collects Capitalized tokens. Recognition-only:
    # see known_companies().
    try:
        for co in known_companies():
            if len(co) > 3 and re.search(r"(?<![a-z])" + re.escape(co) + r"(?![a-z])", body, re.I):
                toks.add(co)
    except Exception:
        pass
    anchors = set(toks)
    # a them-anchored figure is a one-of-a-kind specific too
    for sent in re.split(r"(?<=[.!?])\s+", body):
        if re.search(r"\byou(r|'ve|'re)?\b", sent, re.I):
            for f in re.findall(r"\$[\d,.]+\s*(?:[BbMmKk]\+?|billion|million|thousand)?\+?|\b\d+[%x]\b", sent):
                anchors.add(f.strip())
    return anchors


def check_ingredients(body, rung):
    """Andy's 7 ingredients + the O-A-K test. Returns (fails, warns).

    HARD gates are deliberately narrow. Andy's own annotation is that ingredients #2 and #4 are
    what MAKE a message one-of-a-kind, so the O-A-K test is already their composite — and the
    composite is far more robust to detect than either part. Calibration proved the point: the
    per-ingredient vocabulary detectors for #2 and #4 produced a 17.6% false-fail rate against
    your real sent corpus (a strong send expresses "why I chose you" as admiration,
    which no keyword list anticipates), while the fixed O-A-K composite produces none. So #2 and
    #4 WARN, and the composite FAILs. Hard-failing an individually brittle detector is how you
    get a gate that people learn to --force past, which is worse than no gate.
    """
    fails, warns = [], []
    warm = rung in ("warm", "referred", "event")
    low = body.lower()

    anchors = _their_anchors(body)
    did_research = False
    for sent in re.split(r"(?<=[.!?])\s+", body):
        if re.search(r"\byou(r|'ve|'re)?\b|\b" + r"\b|\b".join(
                sorted((re.escape(a) for a in anchors if a[:1].isalpha()), key=len, reverse=True)[:6] or ["￿"]) + r"\b", sent, re.I):
            if re.search(r"\d", sent) or _their_anchors(sent):
                did_research = True
                break

    for num, label, pat, hard_cold, hard_warm in INGREDIENTS:
        present = did_research if num == 4 else bool(re.search(pat, low, re.I))
        if present:
            continue
        hard = hard_warm if warm else hard_cold
        msg = f"ingredient {num} missing — {label}"
        (fails if hard else warns).append(msg)

    # ── the O-A-K test (the #2 + #4 composite, and the real gate) ──
    # RUNG-AWARE (FIX D, 2026-07-24): "could ONLY be sent to this person" is a COLD-BOSS bar — a
    # cold stranger who gets a generic note is the failure Andy warns about. A WARM note goes to a
    # known 1st-degree contact by definition, so a thin rung-5/6 reconnect (one anchor) is
    # legitimate, not a mail-merge. Mirror the ingredient loop's hard_warm split: FAIL cold, WARN warm.
    if len(anchors) < 2:
        (warns if warm else fails).append(
            "O-A-K FAIL — nothing in this body could ONLY be sent to this person. "
            f"Their-side specifics found: {sorted(anchors) or 'none'}. Andy: \"Does this message "
            "look like it's the only one in existence? Does it look like it could ONLY be sent to "
            "this person?\" A mail-merged first name is not an answer."
        )
    elif len(anchors) < 3:
        warns.append(f"O-A-K thin — {sorted(anchors)} is all that is theirs; add one more specific")
    return fails, warns

def main():
    if len(sys.argv) < 2:
        print("usage: check_outreach.py <body.txt> [--rung <rung>] [--type <message type>]")
        sys.exit(2)
    rung = ""
    if "--rung" in sys.argv:
        _i = sys.argv.index("--rung")
        if _i + 1 < len(sys.argv):
            rung = sys.argv[_i + 1]
        sys.argv = sys.argv[:_i] + sys.argv[_i + 2:]
        rung = _validate_rung(rung)
    # MESSAGE-TYPE awareness (added 2026-07-20). The 7-ingredient + O-A-K check is intrinsically
    # about a COLD/WARM INTRO ("why you chose them", "what you can offer", a one-of-a-kind anchor).
    # A thank-you / reply / follow-up-bump has none of those by nature, so running the ingredient
    # check on one FALSE-FAILS it (hit live on Blake's Astra thank-you). --type gates ONLY the
    # ingredient block; every other check (AI-tells, em-dash, spaced-slash, retired figures,
    # engineer-implication, signature, sign-off) still runs — a thank-you must be just as honest and
    # just as clean as an outreach email.
    mtype = "outreach"
    if "--type" in sys.argv:
        _j = sys.argv.index("--type")
        if _j + 1 < len(sys.argv):
            mtype = sys.argv[_j + 1]
        sys.argv = sys.argv[:_j] + sys.argv[_j + 2:]
    # NORMALIZE + VALIDATE (2026-07-21). Two defects sat one line apart here.
    #   1. mail-draft.sh spells two of these types without a hyphen (thankyou, followup), so the
    #      in-thread exemptions never fired on a thank-you or a follow-up sent through the one
    #      mechanism that sends everything. Both hard-failed on a missing signature block, which is
    #      the beat an in-thread message is supposed to drop. Aliasing at the boundary is cheaper
    #      than trusting two files to agree on a string forever.
    #   2. An unrecognized --type fell through as "not outreach" and SKIPPED the 7-ingredient/O-A-K
    #      gate. A typo bought a WEAKER check on a cold boss-hunt, which is the wrong direction for
    #      a gate to fail, so an unknown type is a usage error now and mail-draft blocks on it.
    mtype = mtype.strip().lower()
    mtype = TYPE_ALIASES.get(mtype, mtype)
    if mtype not in KNOWN_TYPES:
        print(f"unknown --type '{mtype}'. One of: " + " | ".join(sorted(KNOWN_TYPES)))
        sys.exit(2)
    # IN-THREAD = the recipient already knows who he is and how to reach him, and the thread
    # carries the context. Gates the first-contact SHAPE rules only; see each use below.
    # Gates the FIRST-CONTACT-ASK shape rules (7 ingredients, O-A-K, signature block). True for a
    # live thread, and also for a no-ask reunion, which is a first contact that requests nothing.
    _IN_THREAD = mtype in IN_THREAD_TYPES or mtype in NO_ASK_TYPES
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"body file not found: {path}"); sys.exit(2)
    body = open(path, encoding="utf-8", errors="ignore").read()
    low = body.lower()
    fails, warns = [], []

    # — format (deterministic) —
    if "—" in body or "---" in body:
        fails.append("em dash present (use commas)")
    if re.search(r"\S\s+/\s+\S|\S\s+/\S|\S/\s+\S", body):
        fails.append("spaces around a slash (write fintech/payments)")
    if re.search(r"^\s*-\s+\S", body, re.M):
        fails.append("'-' bullet(s) — use '•' for Apple Mail")
    # — banned words / AI tells (word-boundary) —
    # banned_hit(), not a bare regex on `low`: lowercasing first destroys the capitalization that
    # tells a company name apart from a voice defect. See banned_hit's docstring (Empower Project).
    for w in BANNED:
        if banned_hit(body, w):
            fails.append(f"banned/AI-tell word: \"{w}\"")
    # — often-empty adverbs: WARN, never fail (see the SOFT comment at the top of this file) —
    for w in SOFT:
        if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
            warns.append(f"often-empty adverb: \"{w}\" — cut it unless it carries emphasis, "
                         "uncertainty, or his spoken rhythm")
    # — retired / dishonest figures —
    for w in RETIRED:
        if w.lower() in low:
            fails.append(f"retired/incorrect figure: \"{w}\"")
    # re.I: `low` is already lowercased, so an uppercase literal in a RETIRED_PATTERNS entry would
    # be DEAD here while looking alive in your config. Ported from main 2026-08-07 after a panel
    # found a live pattern that fired on resumes and on nothing else.
    for pat, label in RETIRED_PATTERNS:
        if re.search(pat, low, re.I):
            fails.append(f"retired/incorrect claim: {label}")
    # ENGINEER-IMPLICATION (added 2026-07-19). This file had NO engineer patterns at all —
    # only verify_resume.py did, and its patterns ("as an engineer", "engineer-turned-pm")
    # would not have caught the phrasing that actually shipped: "I built OnPay's $35B+ B2B
    # payments API" went to a Head of Product (Flexpa) and a co-founder/CPO (Zus Health) on
    # 2026-07-14. you owned the REQUIREMENTS and the API-first decision; an engineer built
    # the API. The repo's own vetted phrasing is "DROVE OnPayConnect's ... API-first".
    # REWRITTEN 2026-07-19 after a red-team showed the first version was backwards. It keyed on
    # verb-noun PROXIMITY ("I built" within 40 chars of api|platform|...), which:
    #   • blocked 8/8 TRUE statements — "I built Ensemble with Claude Code", "I built a RAG
    #     pipeline for the Air Force" — i.e. the builder-PM/Claude Code differentiator CLAUDE.md
    #     tells him to lead with; and
    #   • passed 5/5 evasions of the ACTUAL dishonest claim ("We built OnPay's API",
    #     "I've built…", "I developed…").
    # The real tell is not the verb, it is the OBJECT: claiming an EMPLOYER'S engineering artifact.
    # "I built Ensemble" is true (he built it with Claude Code). "I built OnPay's payments API" is
    # not (he owned requirements; an engineer built it). So match possession, and stay narrow —
    # a precise check that catches the known-bad pattern beats a broad one that cries wolf.
    ENGINEER_CLAIMS = (
        (r"\b(i|we)(?:'ve| have)?\s+(built|coded|engineered|architected|developed|wrote|implemented)\b"
         r"[^.]{0,40}?\b(onpay|onpayconnect|rise8)\b[^.]{0,25}\b(api|platform|pipeline|backend|infrastructure|system)\b",
         'claims authorship of an EMPLOYER\'s engineering artifact — you owned requirements and the '
         'API-first decision; an engineer built it. Use the vetted phrasing: "drove OnPayConnect\'s '
         '$35B+ payments platform API-first"'),
        # Possessive object = someone else's artifact. Exclude the things he genuinely DID build
        # himself with Claude Code (Ensemble / the PM OS), or this flags a true statement.
        (r"\b(i|we)(?:'ve| have)?\s+(built|coded|engineered|architected|developed|implemented)\b"
         r"[^.]{0,30}?\b(?!ensemble|pm[- ]os|my own)[a-z]+'s\s+[^.]{0,20}\b(api|platform|backend|infrastructure)\b",
         'claims authorship of someone ELSE\'s engineering artifact (possessive object) — scope the '
         'claim to what you personally owned'),
        (r"\bas an engineer\b|engineer[- ]turned[- ]pm|came up as an engineer|\bmy engineering background\b",
         "implies an engineering background — you was NEVER an engineer"),
    )
    for pat, label in ENGINEER_CLAIMS:
        if re.search(pat, low):
            fails.append(f"honesty guardrail: {label}")
    # Inflection hole (2026-07-19 audit): the (?![a-z]) boundary let suffixed forms escape —
    # "seamlessly", "leveraged", "delved", "robustness", "showcased" all passed clean while
    # the base word is banned. Catch the common -ly/-ed/-ing/-ness forms of the worst offenders.
    for stem in ("seamless", "leverag", "delv", "robust", "showcas", "utiliz"):
        if re.search(r"(?<![a-z])" + stem + r"[a-z]*", low):
            m = re.search(r"(?<![a-z])(" + stem + r"[a-z]*)", low)
            fails.append(f"banned/AI-tell word: \"{m.group(1)}\"")
    # — structure (presence, not judgment) —
    # GREETING PRESENCE IS FIRST-CONTACT ONLY (2026-07-21). Opening a cold email with no greeting
    # is a real defect; opening a REPLY with no greeting is how people write in a live thread.
    # you does both. His reply to Brian de Haaff opened "TGIF, Brian!", his reply to Mark
    # Bishop opened "Good eye. FIS was a contract stint…", and the second one is correct, so a
    # warn that fires on it is telling him his own good writing is wrong. Note this suppresses only
    # the PRESENCE warn; the own-line format warn below still applies whenever a greeting IS there,
    # because a joined greeting reads the same in any message.
    if not _IN_THREAD and not re.search(r"^\s*(hi|hey|tgif|hello)[, ]+[A-Z][a-z]+!", body, re.M | re.I):
        warns.append("no 'Hi/Hey, First!' greeting line found")
    # IN-THREAD REPLIES DO NOT GET A SIGNATURE. Signing a reply inside a live thread reads as
    # impersonal, and unassisted writing proves the point: a real in-thread DM reply runs to two
    # warm sentences with no name and no URL. The signature earns its place on FIRST contact,
    # where the recipient may not know who you are or how to find you. Three messages deep it
    # reads like closing a business letter. This check was built for email and was over-applied to
    # DM replies, where it hard-failed a real reply until this block was added.
    # (_IN_THREAD is computed in main() above, at the point --type is normalized.)
    # — signature block format: TWO blank lines before your name, then the website URL on the
    #   line DIRECTLY under it (no blank line between). The sign-off token is any of YOUR real
    #   names — the full name, a diminutive, or the surname alone — and you pick the register per
    #   message (a warm post-chat thank-you often gets the diminutive, a cold-boss email the full
    #   name, a note to somebody who has called you by your surname for twenty years the surname).
    #
    # ⛔ THE SIGNATURE IS RUNG-AWARE. It used to demand the full block on every first contact,
    # which hard-failed REAL warm practice. Measured against a live corpus: warm notes that were
    # sent, welcomed, and replied to end on a bare first name with no URL. A gate that fails copy
    # somebody already sent is wrong about the copy, not the other way round — the same principle
    # the live-corpus regression tests enforce on the word list.
    #
    # The distinction is the RUNG, not the channel. A cold boss does not know who you are or how to
    # find you, so the full block earns its place. A warm 1st-degree contact already knows both,
    # and a portfolio URL under a note to a friend reads like a pitch. So: warm lane accepts EITHER
    # shape, cold lane still requires the full block. This LOOSENS nothing for cold outreach.
    # ⚠️ Derived from the configured identity, never hardcoded. The main pipeline can name one
    # person; a kit cannot, and a hardcoded name here silently fails every signature check
    # for everyone else while reporting a formatting error they cannot fix.
    # ⛔ THE FULL NAME MUST BE AN ALTERNATIVE, AND IT MUST COME FIRST (fixed 2026-08-09).
    # This built the alternation from NAME TOKENS ONLY, so a two-word OWNER_NAME produced
    # `(?:First|Last)` and the joined full name was never an option. A cold-boss email signed
    # with the FULL name then FAILED the signature gate while a single-token sign-off passed, which
    # is the opposite of what the comment above this line says cold outreach should use. Reported
    # from a partner install, which is the only place it could show: an owner whose sign-off is one
    # token never meets it.
    # ⚠️ ORDER IS LOAD-BEARING. Python's alternation is first-match with backtracking, so a shorter
    # token listed first can match and then fail the following `\n`. Putting the longest form first
    # makes the pattern correct without depending on backtracking to rescue it.
    _parts = [p for p in re.split(r"\s+", OWNER_NAME.strip()) if p]
    _NAME = "(?:" + "|".join(re.escape(x) for x in dict.fromkeys(
        [OWNER_NAME.strip()] + _parts + [OWNER_FIRST])) + ")" if _parts else r"(?:\w+)"
    _WARM_LANE = (rung or "").strip().lower() in WARM_RUNGS
    if not _IN_THREAD:
        _full_block = bool(re.search(r"\n\n\n" + _NAME + r"\n(https?://)?(www\.)?" + re.escape(OWNER_SITE),
                                     body))
        # Warm shape, measured from REAL sends rather than assumed. One warm note ends
        # `…\n\n<diminutive>\nhttps://www.<your site>\n` — ONE blank line, name, URL directly
        # under. Another ends on a bare surname with no URL at all. So the warm lane varies on
        # BOTH axes (one-or-two blank lines, URL present or not) and the only invariant is: a
        # sign-off name alone on its line, optionally followed by the URL line, nothing after it.
        # ⚠️ An earlier read of this said warm notes carry no URL. That was wrong, taken from a
        # truncated blockquote in the narrative log rather than from the bytes. Measure the file.
        _warm_sig = bool(re.search(
            r"\n\n+" + _NAME + r"[ \t]*(?:\n(?:https?://)?(?:www\.)?" + re.escape(OWNER_SITE) + r"[ \t]*)?\s*\Z",
            body))
        if _WARM_LANE:
            # A sign-off is still REQUIRED. Only the URL and the second blank line are optional.
            if not (_full_block or _warm_sig):
                fails.append("signature: a warm-lane first contact still needs a sign-off — either "
                             "a bare your sign-off name after a blank line, or the full block "
                             f"(two blank lines, name, {OWNER_SITE} directly under it)")
        else:
            if OWNER_SITE not in low:
                fails.append(f"missing {OWNER_SITE} sign-off")
            if not re.search(r"\n\n\n" + _NAME + r"\b", body):
                fails.append("signature: need two blank lines before your name (blank, blank, name)")
            if not _full_block:
                fails.append("signature: website must sit on the line directly under your name (no blank line between)")
    elif re.search(r"\n" + _NAME + r"\n(https?://)?(www\.)?" + re.escape(OWNER_SITE), body):
        # Present on a reply is not an error he must fix, but it is worth seeing: it is the beat
        # that makes a live thread read as correspondence rather than conversation.
        warns.append("signature present on an in-thread reply — usually reads formal; his own "
                     "in-thread replies carry no name/URL")
    # — paragraph spacing: paragraphs separated by a blank line (no single-newline-joined blocks) —
    if re.search(r"[a-z0-9][.!?]\n(?=[A-Z])", body):
        warns.append("paragraph spacing: a paragraph break has no blank line (single newline mid-body)")
    # — GREETING ON ITS OWN LINE (you 2026-07-20, memory→durable migration). The greeting must
    #   sit alone on its line with a blank line before the body: "Hi, Astrid!\n\nYou brought…", never
    #   "Hi, Astrid! You brought…". Fires ONLY when a greeting is present, so a no-greeting body keeps
    #   its single "greeting missing" warn rather than double-penalizing. —
    # EMAIL/FIRST-CONTACT ONLY (you 2026-07-29). He joins the greeting to the first beat on
    # every LinkedIn short message — "Hi, Riché! I really like…", three in a row (Jason, Malte,
    # Riché). The own-line rule was written for email bodies (the dense-block concern); an in-thread
    # or short DM joins the greeting by his consistent practice, so suppress the warn there. The
    # rule still holds for a cold-boss email.
    _GREET = r"^[ \t]*(?:hi|hey|tgif|hello)[, ]+[A-Za-z'’-]+!"
    if not _IN_THREAD and (re.search(_GREET + r"[ \t]*[^\s]", body, re.M | re.I) or
                           re.search(_GREET + r"[ \t]*\n(?!\n)", body, re.M | re.I)):
        warns.append("greeting must sit on its own line with a blank line before the body "
                     "(Hi, First!\\n\\n…), not joined to the first beat")
    # — DENSE BLOCK (you 2026-07-20, memory→durable migration). Outreach (email AND LinkedIn/DM)
    #   breaks ONE BEAT PER PARAGRAPH with a blank line between beats (hook/praise · proof · identity ·
    #   ask), never a single wall of text — he DELETED staged drafts that were one dense paragraph.
    #   Strip the signature, then flag a content region that is effectively one run-on paragraph. —
    # ⚠️ THE OWNER'S FIRST NAME COMES FROM kit_config, never from a literal (genericized
    # 2026-08-09). This read `(?:you|Mike)`, the kit author's own name baked into a partner
    # kit, so for anybody else the signature never matched, the whole sign-off counted as
    # BODY, and the wall-of-text rule was measured against text that is not the message.
    # This file already imports OWNER_FIRST and already uses it this way further up.
    _sig = re.search(r"\n\n\n(?:you|" + re.escape(str(OWNER_FIRST)) + r")\b", body)
    _content = body[:_sig.start()] if _sig else body
    _paras = [p for p in re.split(r"\n[ \t]*\n", _content) if p.strip()]
    _sentences = len(re.findall(r"[.!?](?:\s|$)", _content))
    # The wall-of-text rule stays universal (he reformatted a WorqFlow LinkedIn REPLY himself to
    # show the pattern), but the trigger was calibrated on outreach, which carries four beats by
    # design. A short in-thread reply carries one, so the shape it is being told to adopt does not
    # exist: his own two-sentence reply to Brian de Haaff tripped this. Floor the in-thread case at
    # a body long enough to HAVE separable beats; a long in-thread message mashed into one
    # paragraph is still a wall of text and still warns. (2026-07-21)
    _cwords = len(re.findall(r"\S+", _content))
    if len(_paras) <= 2 and _sentences >= 3 and (_cwords >= 60 or not _IN_THREAD):
        warns.append("dense block — the body reads as one paragraph; break it one beat per paragraph "
                     "(hook/praise · proof · identity · ask) with a blank line between beats")
    # — repeated multi-word content phrase (an AI tell: same phrase in nearby sentences, e.g. "builder PM" twice) —
    _w = re.findall(r"[a-z0-9']+", low)
    _stop = {"and","the","for","with","that","your","you","this","have","from","into","are","was",
             "but","not","can","will","who","how","its","our","out","off","the"}
    from collections import Counter
    _grams = [" ".join(_w[i:i+2]) for i in range(len(_w) - 1)]
    _dupes = sorted({g for g, c in Counter(_grams).items()
                     if c > 1 and any(len(x) >= 4 and x not in _stop for x in g.split())})
    if _dupes:
        warns.append("repeated phrase(s) across the body (AI tell — vary it): " + ", ".join(_dupes[:6]))
    # — sentence-level CADENCE (his hooks are SHORT; one vivid phrase carries the beat, not a nested
    #   clause or a comma-stacked run-on). This is the gap that let a "clunky but clean" draft score
    #   🟢: the word/format gates never measured per-sentence length or clause density. Calibrated on
    #   his real corpus — his outreach hooks top out ~28 words / ≤2 commas (writing-samples.md Sample
    #   4b), and the clunky drafts he rejected ran 32-33 words — so >30 words, or 3+ commas in a
    #   longish sentence, WARNs. WARN, never FAIL: his legitimate "and X and Y" run-on (Sample 5) and
    #   the tightened draft (24 words) both stay clean. Reports the FIRST offender; re-lint after you
    #   tighten. —
    for _cs in re.split(r"(?<=[.!?])\s+", _content):
        _cs = _cs.strip()
        if not _cs:
            continue
        _csw = len(re.findall(r"\S+", _cs))
        if _csw > 30:
            warns.append(f"clunky sentence ({_csw} words) — his run short; tighten it and let one "
                         f"vivid phrase carry the beat (writing-samples.md Sample 4/5/6)")
            break
        if _cs.count(",") >= 3 and _csw >= 26:
            warns.append(f"comma-stacked hook ({_cs.count(',')} commas) — swap the nested clause for "
                         f"one tight phrase (writing-samples.md Sample 4)")
            break
    # — generic-praise heuristic (Andy A2: praise must be a RESEARCHED SPECIFIC boss accomplishment,
    #   not product/mission-level). Flag a "you built/created <X>" sentence that has NO specific detail
    #   (no number and no second named/proper thing) — the generic shortcut. WARN (judgment-heavy);
    #   the hard gate is mail-draft.sh --praise-source.
    #   FIRST-CONTACT ONLY (2026-07-21). A2 governs the PRAISE BEAT of a cold boss-hunt: the thing
    #   that earns a stranger's attention in the first ten seconds. A live thread has no praise beat
    #   to research, and the mechanism this points at (mail-draft --praise-source) is not supplied on
    #   a post-contact send at all, so the advice has nowhere to land. "You led that rollout" in a
    #   reply to a hiring manager is conversation, not a failed A2. —
    if not _IN_THREAD:
        for _m in re.finditer(r"(?:^|[.!?]\s+)(you (?:built|created|made|led|shaped)\b[^.!?]*)", body, re.I):
            _sent = _m.group(1)
            _stopcap = {"you","the","this","that","your","their","our","and","for","with","from","they","she","him","her"}
            _caps = [c for c in re.findall(r"\b[A-Z][a-zA-Z]{2,}", _sent) if c.lower() not in _stopcap]
            if not re.search(r"\d", _sent) and len(_caps) < 2:   # <2 named things + no number = generic
                warns.append("praise may be generic — a 'you built/led …' line with no specific detail (no number, no second named thing). Andy A2 wants a RESEARCHED specific boss accomplishment + a you mirror")
                break
    # — length (a boss-hunt note is short) —
    words = len(re.findall(r"\S+", body))
    if words > 200:
        warns.append(f"long body ({words} words) — boss-hunt notes run ~120-160")

    # An exemption must never be silent. If a banned word was let through because it sat inside
    # someone else's attributed words, SAY SO — the linter cannot verify that an attribution is
    # truthful, so that judgment stays with the human reading this line.
    for _w, _snip in exempted_banned(body):
        warns.append(f'banned word "{_w}" ALLOWED inside an attributed quote: …{_snip[:70]}… '
                     f"(verify the attribution is real; the linter cannot)")

    # — Andy's 7 ingredients + the O-A-K test (OUTREACH only; a thank-you/reply/follow-up has no
    #   "why you chose them" or one-of-a-kind anchor by nature, so this would false-fail it) —
    if mtype == "outreach":
        _if, _iw = check_ingredients(body, rung)
        if _if:
            # A manual invocation carries no --type (documents/email-body-checklist.md says to run
            # `check_outreach.py <body.txt>` bare), so an in-thread reply linted by hand collects
            # first-contact ingredient fails it can never satisfy. Point at the flag instead of
            # leaving the reader to argue with a gate that is measuring the wrong genre.
            _if.append("↑ if this is an in-thread reply/thank-you/follow-up, re-run with "
                       "--type reply|follow-up|thank-you|bump. The ingredient/O-A-K block is a "
                       "FIRST-CONTACT check and does not apply here.")
        fails.extend(_if); warns.extend(_iw)
    elif mtype in PEER_TYPES:
        warns.append("message type 'peer': rung 1-2 common-interest note — the cold-boss "
                     "7-ingredient/O-A-K block does not apply (not a work-for-you ask); AI-tells, "
                     "honesty, greeting, and signature checks still applied")
    else:
        warns.append(f"message type '{mtype}': ingredient/O-A-K check skipped (not an intro); "
                     "AI-tells, honesty, and signature checks still applied")

    # — The invitation note is rung 1-2 and its ask is ACCEPTANCE. A role pitch in it asks for
    #   something the format cannot deliver, and July's 45 sends are the evidence (see the
    #   _INVITATION_ASK block above for the funnel). Hard fail, because a connection request
    #   cannot be unsent and the ruling exists to stop the pitch version recurring. —
    if mtype == "invitation":
        _body_len = len(body.strip())
        if _body_len > _INVITATION_MAX:
            fails.append(
                f"invitation note is {_body_len} chars, over LinkedIn's {_INVITATION_MAX} cap. "
                "LinkedIn truncates silently, mid-sentence, and the send still counts.")
        for _pat, _why in _INVITATION_ASK:
            _m = _pat.search(body)
            if _m:
                fails.append(
                    f'invitation note carries a rung 3-4 ask ({_why}): "{_m.group(0)}". '
                    "An invitation can only deliver ACCEPTANCE, so the ask is rung 1-2: connect "
                    "and share networks, nothing more. Ruled 2026-07-27 off 45 July sends that "
                    "carried the pitch and converted 7. Work the ones who accept at the warm rungs, "
                    "where the reply rate is 17.1%.")

    name = os.path.basename(path)
    if fails:
        print(f"🔴 check_outreach FAIL — {name}")
        for f in fails: print(f"   ❌ {f}")
        for w in warns: print(f"   ⚠️  {w}")
        print("   (praise genuineness + fit are human-judgment — not checked here)")
        sys.exit(1)
    print(f"🟢 check_outreach clean — {name}" + (f"  ({len(warns)} advisory)" if warns else ""))
    for w in warns: print(f"   ⚠️  {w}")
    sys.exit(0)

if __name__ == "__main__":
    main()
