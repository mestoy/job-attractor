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
import sys, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from kit_config import (OWNER_NAME, OWNER_FIRST, OWNER_SITE, RETIRED,
                            RETIRED_PATTERNS, ROLE_IMPLY_PATTERNS)
except Exception:  # standalone fallback — placeholders, so the checks are visibly inert
    OWNER_NAME, OWNER_FIRST, OWNER_SITE = "Your Name", "You", "yoursite.example"
    RETIRED, RETIRED_PATTERNS, ROLE_IMPLY_PATTERNS = [], [], []

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
# Banned words that DOUBLE AS COMPANY NAMES. Every one of these is a plausible employer, and a
# boss-hunt names the company in nearly every sentence. For these, only a LOWERCASE occurrence
# counts as a defect.
NAME_PRONE = frozenset({
    "foster", "streamline", "realm", "beacon", "elevate", "embark", "supercharge",
    "vibrant", "empower", "paramount", "transformative", "facilitate", "utilize",
})


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

    if word in NAME_PRONE:
        return any(not _in_spans(m.start(), _spans) for m in
                   re.finditer(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", body))

    for m in re.finditer(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", body, re.I):
        if _in_spans(m.start(), _spans):
            continue                         # someone else's words, attributed — not an AI tell
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

def main():
    # --rung / --type are OPTIONAL and mail-draft.sh always passes them. They are parsed rather
    # than ignored on purpose: a flag a script silently swallows reads as wired while doing
    # nothing, which is the defect class this kit keeps paying for. Only the rung-dependent checks
    # below consult them; everything else (banned vocabulary, honesty figures, signature, spacing)
    # applies to every rung, because a warm note is still your writing going to a real person.
    argv = [a for a in sys.argv[1:]]
    rung, mtype = "", "outreach"
    for _f, _set in (("--rung", "rung"), ("--type", "type")):
        if _f in argv:
            _i = argv.index(_f)
            if _i + 1 < len(argv):
                _v = argv[_i + 1]
                if _set == "rung":
                    rung = _v
                else:
                    mtype = _v
                del argv[_i:_i + 2]
            else:
                del argv[_i]
    IS_WARM = rung in ("warm", "referred", "event", "off-ladder")
    if not argv:
        print("usage: check_outreach.py <body.txt> [--rung <rung>] [--type <type>]"); sys.exit(2)
    path = argv[0]
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
    # — banned words / AI tells —
    # banned_hit(), not a bare regex on `low`: lowercasing first destroys the capitalization that
    # tells a company name apart from a voice defect. See banned_hit's docstring.
    for w in BANNED:
        if banned_hit(body, w):
            fails.append(f"banned/AI-tell word: \"{w}\"")
    # — often-empty adverbs: WARN, never fail (see the SOFT comment above) —
    for w in SOFT:
        if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
            warns.append(f"often-empty adverb: \"{w}\" — cut it unless it carries emphasis, "
                         "uncertainty, or your spoken rhythm")
    # — retired / dishonest figures —
    for w in RETIRED:
        if w.lower() in low:
            fails.append(f"retired/incorrect figure: \"{w}\"")
    for pat, label in RETIRED_PATTERNS:
        if re.search(pat, low):
            fails.append(f"retired/incorrect claim: {label}")
    # ROLE-CLAIM honesty (kit_config.ROLE_IMPLY_PATTERNS). Word-level lists miss the real
    # failure, which is a whole phrasing that claims authorship of work someone else did —
    # "I built the payments API" reads as engineering authorship even when you owned the
    # requirements and the decision rather than the code. That phrasing goes out to a Head of
    # Product who will read it literally. Match the shape of the claim, not a keyword.
    for pat, label in ROLE_IMPLY_PATTERNS:
        if re.search(pat, low):
            fails.append(f"honesty guardrail: {label}")
    # Inflection hole: the (?![a-z]) boundary lets suffixed forms escape —
    # "seamlessly", "leveraged", "delved", "robustness", "showcased" all passed clean while
    # the base word is banned. Catch the common -ly/-ed/-ing/-ness forms of the worst offenders.
    for stem in ("seamless", "leverag", "delv", "robust", "showcas", "utiliz"):
        if re.search(r"(?<![a-z])" + stem + r"[a-z]*", low):
            m = re.search(r"(?<![a-z])(" + stem + r"[a-z]*)", low)
            fails.append(f"banned/AI-tell word: \"{m.group(1)}\"")
    # — structure (presence, not judgment) —
    if not re.search(r"^\s*(hi|hey|tgif|hello)[, ]+[A-Z][a-z]+!", body, re.M | re.I):
        warns.append("no 'Hi/Hey, First!' greeting line found")
    if OWNER_SITE.lower() not in low:
        fails.append(f"missing {OWNER_SITE} sign-off")
    # — signature block format: TWO blank lines before your name, then the website URL on the
    #   line DIRECTLY under it (no blank line between). —
    if not re.search(r"\n\n\n" + re.escape(OWNER_FIRST) + r"\b", body):
        fails.append(f"signature: need two blank lines before '{OWNER_FIRST}' (blank, blank, name)")
    if not re.search(r"\n" + re.escape(OWNER_FIRST) + r"\n(https?://)?(www\.)?" + re.escape(OWNER_SITE), body):
        fails.append(f"signature: website must sit on the line directly under '{OWNER_FIRST}' (no blank line between)")
    # — paragraph spacing: paragraphs separated by a blank line (no single-newline-joined blocks) —
    if re.search(r"[a-z0-9][.!?]\n(?=[A-Z])", body):
        warns.append("paragraph spacing: a paragraph break has no blank line (single newline mid-body)")
    # — GREETING ON ITS OWN LINE. It must sit alone on its line with a blank line before the body:
    #   "Hi, First!\n\nYou brought…", never "Hi, First! You brought…". Fires only when a greeting is
    #   present, so a no-greeting body keeps its single "greeting missing" warn. —
    _GREET = r"^[ \t]*(?:hi|hey|tgif|hello)[, ]+[A-Za-z'’-]+!"
    if re.search(_GREET + r"[ \t]*[^\s]", body, re.M | re.I) or \
       re.search(_GREET + r"[ \t]*\n(?!\n)", body, re.M | re.I):
        warns.append("greeting must sit on its own line with a blank line before the body "
                     "(Hi, First!\\n\\n…), not joined to the first beat")
    # — DENSE BLOCK. Break ONE BEAT PER PARAGRAPH (hook/praise · proof · identity · ask) with a blank
    #   line between beats, never one wall of text. Strip the signature, then flag a content region
    #   that is effectively one run-on paragraph. —
    _sig = re.search(r"\n\n\n" + re.escape(OWNER_FIRST) + r"\b", body)
    _content = body[:_sig.start()] if _sig else body
    _paras = [p for p in re.split(r"\n[ \t]*\n", _content) if p.strip()]
    _sentences = len(re.findall(r"[.!?](?:\s|$)", _content))
    if len(_paras) <= 2 and _sentences >= 3:
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
    # — sentence-level CADENCE (your hooks should stay SHORT; one vivid phrase carries the beat, not a
    #   nested clause or a comma-stacked run-on). This is the gap that lets a "clunky but clean" draft
    #   score 🟢: the word/format gates never measured per-sentence length or clause density. Short
    #   outreach hooks top out around ~28 words / ≤2 commas; the drafts you reject tend to run 32-33
    #   words — so >30 words, or 3+ commas in a longish sentence, WARNs. WARN, never FAIL: a legitimate
    #   "and X and Y" run-on and a tightened 24-word draft both stay clean. Reports the FIRST offender;
    #   re-lint after you tighten. Model each beat on a named sample (python3 scripts/voice_samples.py). —
    for _cs in re.split(r"(?<=[.!?])\s+", _content):
        _cs = _cs.strip()
        if not _cs:
            continue
        _csw = len(re.findall(r"\S+", _cs))
        if _csw > 30:
            warns.append(f"clunky sentence ({_csw} words) — your sentences run short; tighten it and "
                         f"let one vivid phrase carry the beat (writing-samples.md)")
            break
        if _cs.count(",") >= 3 and _csw >= 26:
            warns.append(f"comma-stacked hook ({_cs.count(',')} commas) — swap the nested clause for "
                         f"one tight phrase (writing-samples.md)")
            break
    # — generic-praise heuristic (Andy A2: praise must be a RESEARCHED SPECIFIC boss accomplishment,
    #   not product/mission-level). Flag a "you built/created <X>" sentence that has NO specific detail
    #   (no number and no second named/proper thing) — the generic shortcut. WARN (judgment-heavy);
    #   the hard gate is mail-draft.sh --praise-source. —
    # ⛔ COLD RUNGS ONLY. A warm or referred ask is a favor asked of someone you know: it has no
    # boss, no researched accomplishment and no praise beat, so "your praise may be generic" is
    # noise there. Nagging about a missing beat that the rung does not call for is how a check
    # teaches people to stop reading it.
    for _m in (() if IS_WARM else re.finditer(r"(?:^|[.!?]\s+)(you (?:built|created|made|led|shaped)\b[^.!?]*)", body, re.I)):
        _sent = _m.group(1)
        _stopcap = {"you","the","this","that","your","their","our","and","for","with","from","they","she","him","her"}
        _caps = [c for c in re.findall(r"\b[A-Z][a-zA-Z]{2,}", _sent) if c.lower() not in _stopcap]
        if not re.search(r"\d", _sent) and len(_caps) < 2:   # <2 named things + no number = generic
            warns.append("praise may be generic — a 'you built/led …' line with no specific "
                         "detail (no number, no second named thing). The method wants a RESEARCHED "
                         "specific accomplishment of theirs, mirrored by one of yours")
            break
    # — length (a boss-hunt note is short) —
    words = len(re.findall(r"\S+", body))
    if words > 200:
        warns.append(f"long body ({words} words) — boss-hunt notes run ~120-160")

    name = os.path.basename(path)
    if fails:
        print(f"🔴 check_outreach FAIL — {name}")
        for f in fails: print(f"   ❌ {f}")
        for w in warns: print(f"   ⚠️  {w}")
        print("   (praise genuineness + fit are human-judgment — not checked here)")
        sys.exit(1)
    print(f"🟢 check_outreach clean — {name}" + (f"  ({len(warns)} advisory)" if warns else ""))
    for w in warns: print(f"   ⚠️  {w}")
    if not RETIRED and not RETIRED_PATTERNS:
        print("   ⚠️  kit_config RETIRED lists are empty — the honesty-figure scrub checked nothing.")
    sys.exit(0)

if __name__ == "__main__":
    main()
