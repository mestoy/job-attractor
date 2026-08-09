#!/usr/bin/env python3
"""check_style.py — house-style linter: APA construct plus YOUR informal voice, no AI slop.

WHY THIS EXISTS
    The repo already gates VOICE, but only on two surfaces. check_outreach.py lints an email
    BODY. check_preview.py imports that same BANNED list to lint AskUserQuestion previews.
    Everything else written in your name — dossiers, scorecards, JD-fit analyses,
    session-state handoffs, and every chat reply — has never been linted at all.

    The owner's ruling (2026-07-24): "I prefer the construct of APA versus yours while using my
    informal voice. Let's try a blend." Plus: adopt petergyang/no-ai-slop, all 20 patterns
    MINUS rule 16 (formatting slop), because his status badges and 🔬/📊/💡 depth markers are
    deliberate signal, not decoration.

PRECEDENCE (the whole point of the blend)
    When APA and YOUR voice collide, YOUR VOICE WINS. Encoded here so it stops being
    re-litigated every session:
        compound modifiers  APA hyphenates      → his rule: no hyphens ("civic tech")
        contractions        APA avoids them     → his rule: keep them, they ARE the voice
        numbers under 10    APA spells them out → his rule: numerals for money and metrics
        em dashes           APA permits them    → his rule: none, ever (stricter than APA)

WHAT REGEX CAN AND CANNOT DO
    Honest split, because a linter that pretends to judge prose quality is worse than none:
      HARD FAIL  deterministic string/shape matches — em dashes, banned vocabulary, empty
                 phrases, throat-clearing, faux-insight setups, colon reveals, superficial
                 -ing analysis, importance puffery, weasel attribution, fake-strong verbs,
                 rhetorical setups, summary-recap endings.
      WARN       heuristics that carry false positives — binary contrasts, negative listing,
                 dramatic fragmentation, robotic rhythm, anthropomorphism, serial comma,
                 heading-level skips.
      SKILL ONLY not mechanizable at all — synonym cycling, fake-profound kickers,
                 preserve-the-voice, minimum-effective-edit. Those live in
                 .claude/skills/house-style/ and are judgment, not regex.

VOCABULARY SOURCE
    Imports BANNED / RETIRED / RETIRED_PATTERNS from check_outreach (the same import proven at
    check_preview.py:460). One canonical hard-block core, three consumers. This file ADDS a
    prose-only layer on top; it never forks the core.

Usage:
    scripts/check_style.py <file.md> [--mode prose|outreach|resume|chat]
    scripts/check_style.py --stdin [--mode chat]
    scripts/check_style.py <file.md> --hook     # advisory: exempt paths exit 0 silently
    scripts/check_style.py --hook-write         # PostToolUse(Write|Edit), reads payload on stdin
    scripts/check_style.py --hook-stop [--strict]   # Stop hook, lints the last assistant message

Exit: 0 = clean (or warns only, in --hook mode) · 1 = warns · 2 = hard fail / usage error
"""
import sys, os, re, fnmatch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import kit_config as cfg
except Exception:  # pragma: no cover - a missing config must not wedge a Write
    class cfg:  # noqa: N801 - stand-in namespace, not a real class
        OWNER_EMAIL = ""
        OWNER_PHONE = ""
try:
    from check_outreach import BANNED, SOFT, RETIRED, RETIRED_PATTERNS, banned_hit
except Exception:  # pragma: no cover - a broken import must not wedge a Write
    BANNED, SOFT, RETIRED, RETIRED_PATTERNS = [], [], [], []
    def banned_hit(body, word):
        return bool(re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", body, re.I))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── EXEMPT PATHS ─────────────────────────────────────────────────────────────────────────────
# A slop linter that fires on the documents which QUOTE slop as examples is a linter nobody
# leaves switched on. Every path here legitimately contains the patterns as specimens: the voice
# corpus, the style guide, the logs that store verbatim drafts, the skill references, and the
# memory store (which records rulings verbatim, including the words the ruling bans).
# The GUARDRAIL documents are exempt for the same reason, and the hook taught me this by firing on
# its own wiring commit: CLAUDE.md flagged "98%" and "adopted company-wide" as retired claims. Both
# appear there because CLAUDE.md is the file that BANS them. A rule index must be free to name what
# it forbids, and these files also predate the em-dash rule, which covers job-search materials
# (résumé, letters, outreach), not repo configuration.
EXEMPT_GLOBS = [
    "CLAUDE.md",
    "WORKFLOW-RULES.md",
    "documents/HARD-INVARIANTS.md",
    "documents/*checklist*.md",
    "documents/writing-style-guide.md",
    "documents/writing-samples.md",
    "documents/lacivita-*.md",
    "documents/session-state-*.md",
    "documents/interview-question-bank.md",
    # Culture screens are REQUIRED by HARD-INVARIANTS to carry "5 recent pos + 5 recent neg
    # VERBATIM" employee reviews. Employees write "genuinely", "actually", "really" and
    # "cutting-edge", and their sentences carry em dashes. A quote may not be edited to satisfy a
    # linter, and [[quote-exemption-needs-attribution]] already exempts ATTRIBUTED quotes, which
    # every quote in these files is. Added 2026-07-29 when the Luxury Presence screen tripped five
    # hard rules, all of them inside quoted review text. The surrounding prose is still held to the
    # house style by hand; this exemption buys the quotes, not the analysis.
    "documents/culture-screen-*.md",
    "documents/culture-screens-*.md",
    "outreach_log.md",
    "documents/correspondence-log.md",
    "documents/skills/*",
    # Instruction files, not deliverables. A skill or command that teaches the rules has to quote
    # the patterns it bans ("civic-tech", "The best part:"), and every one of them predates this
    # linter using em dashes as separators. The em-dash rule covers job-search materials, which
    # these are not.
    ".claude/skills/*",
    ".claude/commands/*",
    "_memory-backup/*",
    "partner-starter/*",
    "cover_letters/*",
    "tests/*",
    "scripts/*",
]


def is_exempt(path):
    """True when `path` is a file that legitimately quotes the patterns this linter bans."""
    if not path:
        return False
    try:
        rel = os.path.relpath(os.path.abspath(path), REPO)
    except ValueError:
        return False
    if rel.startswith(".."):
        return True  # outside the repo (scratchpad, plan files, memory dir) — not ours to lint
    rel = rel.replace(os.sep, "/")
    return any(fnmatch.fnmatch(rel, g) for g in EXEMPT_GLOBS)


# ── PROSE-ONLY VOCABULARY ────────────────────────────────────────────────────────────────────
# Deliberately NOT added to check_outreach.BANNED. These two carry repo-specific meanings that
# would false-block a legitimate sentence: "harness" is the Claude Code harness, "underscore" is
# a character. They are AI tells in prose, so they warn here and nowhere else.
PROSE_WARN_WORDS = ["harness", "underscore", "underscores", "underscoring"]

# Empty phrases (no-slop "Words to cut"). Hard: they always delay the point.
EMPTY_PHRASES = [
    "it's worth noting", "it is worth noting", "it's important to note",
    "it is important to note", "at the end of the day", "when it comes to",
    "at its core", "in today's world", "in the age of", "in the world of",
    "the reality is", "the truth is", "in this article", "let's dive in",
    "needless to say", "it goes without saying",
]
# Milder — real writing uses these. Warn, never block.
SOFT_PHRASES = ["in order to", "with regard to", "in terms of", "going forward", "to be honest"]

# ── NO-SLOP PATTERNS ─────────────────────────────────────────────────────────────────────────
# (label, regex, hard?) — 19 of the source skill's 20. Rule 16 (formatting slop) is DELIBERATELY
# ABSENT: your badges and depth markers are signal you asked for. See visual-indicators-required.
HARD_PATTERNS = [
    ("throat-clearing opener",
     r"(?:^|[.!?]\s+|\n)\s*(?:\*\*)?(here'?s the thing|here'?s what i mean|let me be clear|"
     r"let'?s be clear|i'?ll be honest|the uncomfortable truth is|here'?s the deal)"),

    ("faux-insight setup",
     r"(this is the part (?:most people|everyone) skips?|what (?:most people|everyone) gets? wrong|"
     r"(?:here'?s )?what nobody tells you|the part (?:everyone|most people) miss(?:es)?|"
     r"nobody talks about|what they don'?t tell you|most people (?:never|don'?t) realize)"),

    # Curated colon reveals. The GENERAL shape is a warn below, because markdown labels
    # ("**Status:** sent") are the same shape and are correct here.
    ("colon reveal",
     r"\b(?:the (?:best part|catch|kicker|twist|trick|secret|detail that makes it work)|"
     r"here'?s the kicker|plot twist|bottom line|the real (?:problem|question|issue|moat|story)):\s+[a-z]"),

    # A trailing -ing clause that pretends to explain significance. Cleanest signal on the list.
    ("superficial analysis (-ing clause)",
     r",\s+(highlighting|underscoring|reflecting|showcasing|demonstrating|signaling|"
     r"cementing|solidifying|emphasizing|illustrating|marking)\b"),

    ("importance puffery",
     r"((?:stands as|is) a testament|marks? a (?:pivotal|defining|watershed|turning) (?:moment|point)|"
     r"plays? a (?:vital|crucial|key|pivotal|critical) role|solidif(?:ies|ying) its position|"
     r"underscores (?:its|the) (?:significance|importance)|cements? its|speaks volumes|"
     r"cannot be overstated|a pivotal moment)"),

    ("weasel attribution",
     r"\b(experts (?:agree|say|note|believe)|industry reports suggest|studies show|"
     r"research shows|many (?:argue|believe|say)|widely (?:regarded|considered|seen) as|"
     r"it is (?:widely )?believed|critics argue|observers note|some would say)\b"),

    ("fake-strong verb",
     r"\b(serves? as (?:a|an|the)|acts? as (?:a|an|the)|functions? as (?:a|an|the)|"
     r"ha(?:s|ve) the ability to|made? a decision|provides? the ability)\b"),

    ("rhetorical setup",
     r"(what if i told you|think about it:|plot twist:|ask yourself:|sound familiar\?|"
     r"let that sink in|here'?s a question for you)"),

    # Recap ending. "ultimately" is a soft adverb anywhere; at a paragraph head it is THE tell.
    ("summary-recap ending",
     r"(?:^|\n)\s*(?:[*_>#\s]*)(in conclusion|ultimately|overall|to sum up|to summarize|"
     r"in summary|all in all)\b[,.]?\s"),

    ("dramatic fragmentation",
     r"\bthat'?s it\.\s+that'?s\b"),
]

WARN_PATTERNS = [
    ("binary contrast",
     r"\b(?:it'?s|this is|that'?s|the (?:question|problem|point|issue|answer))\s+(?:is\s+)?n(?:o|')t\b"
     r"[^.!?]{0,60}[.,;]\s*(?:it'?s|it is|but|rather)\b"),

    ("negative listing",
     r"\bnot an? [^.!?\n]{1,30}\.\s*not an? [^.!?\n]{1,30}\."),

    # APA anthropomorphism ban. Restricted to verbs only a person can do — APA permits
    # "the results suggest" and "the data indicate", so those are absent on purpose.
    ("anthropomorphism (APA)",
     r"\bthe (?:study|data|research|report|paper|analysis|table|figure|results?|role|posting|"
     r"jd|company|score|model|document|section)\s+"
     r"(?:argues?|believes?|thinks?|feels?|wants?|knows?|hopes?|decides?|claims?|worries|"
     r"concluded|assumes?)\b"),
]


# ── TEXT PREPARATION ─────────────────────────────────────────────────────────────────────────
# A fence opener must START A LINE (up to 3 spaces of indent, per CommonMark), and an unterminated
# one runs to end of file. Both halves of that sentence were bugs, and they pull in OPPOSITE
# directions, so neither can be fixed alone:
#
#   ANCHORING alone   — the old `​```.*?```` needed a closer, so a doc with an odd number of fences
#                       had its code linted as prose. Real: the tilde form was never matched at all.
#   EOF-TOLERANCE     — but `.*?(?:```|\Z)` WITHOUT anchoring is far worse than the bug it fixes.
#     alone             `documents/HARD-INVARIANTS.md:70` writes a bare (```) mid-sentence while
#                       explaining the fenced-draft rule, and `email-body-checklist.md` does the
#                       same. Measured: that reads as an unterminated opener and blanks 7,458 of
#                       28,153 non-space chars in HARD-INVARIANTS (26%) and 65% of the checklist.
#                       A style gate that silently stops reading a quarter of its own rulebook is a
#                       false NEGATIVE, which is the failure this linter cannot afford.
#
# Anchored + EOF-tolerant is byte identical to the old behaviour on 181 of 182 repo Markdown files.
# The one difference is an improvement: `.claude/commands/apply.md:141` opens with ```json, and the
# old regex left the bare word "json" behind to be linted as prose.
#
# The closer allows a trailing info string (```json closes an open block). Not strict CommonMark,
# but it makes an unterminated block end at the NEXT fence rather than eating the rest of the file,
# and blanking less is the safer error here.
FENCE_RE = re.compile(r"(?ms)^[ \t]{0,3}(?P<f>```|~~~).*?(?:^[ \t]{0,3}(?P=f)[^\n]*$|\Z)")


def strip_noise(text):
    """Remove regions that quote other people or hold code, replacing them with blanks.

    Blockquotes are where this file stores verbatim drafts and other people's words;
    linting them means telling a source it wrote badly. Fenced/inline code and link targets hold
    identifiers, not prose. Newlines are preserved so line-anchored patterns stay accurate.
    """
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))

    text = re.sub(r"^---\n.*?\n---\n", blank, text, count=1, flags=re.S)   # YAML frontmatter
    text = re.sub(FENCE_RE, blank, text)                                    # fenced code
    text = re.sub(r"`[^`\n]+`", blank, text)                                # inline code
    text = re.sub(r"^[ \t]*>.*$", blank, text, flags=re.M)                  # blockquotes
    text = re.sub(r"\]\([^)]*\)", blank, text)                              # markdown link targets
    # ⚠️ WIKI-LINK TARGETS ARE IDENTIFIERS TOO (2026-08-04). `[[some-memory-slug]]` names a FILE in
    # the memory store, and this repo cites them constantly. Linting one means telling a filename it
    # wrote badly: `[[build-picker-labels-must-match-build-exact]]` fired the banned-word rule on
    # "exact", and the only ways out were a WRONG path or dropping a correct citation. Both are worse
    # than the warning. Same reasoning as the markdown link targets on the line above, which this
    # function's own docstring already states.
    text = re.sub(r"\[\[[^\]\n]+\]\]", blank, text)                         # wiki-link targets
    text = re.sub(r"https?://\S+", blank, text)                             # bare URLs
    return text


LATEX_DROP_CMDS = (
    "documentclass|usepackage|input|include|includegraphics|hypersetup|geometry|pagestyle|"
    "fancyhead|fancyfoot|label|ref|pageref|cite|bibliography|bibliographystyle|"
    "newcommand|renewcommand|providecommand|newenvironment|renewenvironment|def|let|"
    "setlength|addtolength|definecolor|titleformat|titlespacing|vspace|hspace|rule|phantom|"
    "fontsize|selectfont|color|begin|end|hyphenchar|raisebox|makebox"
)
_LATEX_INNER = r"(?:\[[^\]]*\])*(?:\{[^{}]*\})+"


def strip_latex(text):
    """Reduce a .tex source to the words a reader sees, so the prose rules can run on it.

    The linter used to skip .tex entirely and exit 0, which read as a pass, so no résumé was
    ever style-checked. Widening the extension tuple alone is worse than the bug: an unstripped
    .tex lights up on \\textbf, \\hfill and package names, and an operator who learns to ignore
    a gate has no gate. So the markup comes off first.

    What goes: the preamble (everything before \\begin{document}), comment lines, the contact
    header line, URLs and \\href targets, command names and the braces of markup-only commands.
    What stays: the sentences and bullets a hiring manager reads.
    """
    # 1. preamble and back matter: only the document body is prose
    m = re.search(r"\\begin\{document\}", text)
    if m:
        text = text[m.end():]
    m = re.search(r"\\end\{document\}", text)
    if m:
        text = text[:m.start()]
    # 2. comments never render (a lone \% is an escaped percent sign, not a comment)
    text = re.sub(r"(?<!\\)%.*", "", text)
    # 3. \href{target}{label} keeps the label only
    text = re.sub(r"\\href\s*\{[^{}]*\}\s*\{([^{}]*)\}", r"\1", text)
    # 4. the contact/header line is identifiers, not prose
    _contact = "|".join(re.escape(s) for s in (
        cfg.OWNER_EMAIL, cfg.OWNER_PHONE, "linkedin.com/in/") if s)
    text = "\n".join(
        "" if (_contact and re.search(_contact, ln)) else ln
        for ln in text.split("\n"))
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\b[\w.-]+@[\w.-]+\.\w+\b", " ", text)
    # 5. markup-only commands go whole; everything else surrenders its braces and keeps the text
    for _ in range(6):
        new = re.sub(r"\\(?:" + LATEX_DROP_CMDS + r")\*?" + _LATEX_INNER, " ", text)
        new = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])*\{([^{}]*)\}", r" \1", new)
        if new == text:
            break
        text = new
    # 6. escaped characters render as themselves, so restore them before the bare-command sweep.
    # An escaped \$ is a DOLLAR SIGN and a bare $ is a math delimiter, and step 7 deletes the
    # delimiters. Park the real ones out of reach first, or a retired dollar figure survives
    # without its sign and the retired-figure rule never sees it.
    text = text.replace(r"\$", "\x00")
    text = re.sub(r"\\([%&#_{}])", r"\1", text)
    # 7. leftovers: bare commands (\hfill, \item, \\), math delimiters, orphan braces, lengths
    text = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"\\\\(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"\\[^a-zA-Z]", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"[ \t]*\$[ \t]*", " ", text)
    text = re.sub(r"(?<![A-Za-z0-9])-?\d+(?:\.\d+)?(?:pt|em|ex|in|cm|mm)\b", " ", text)
    text = text.replace("\x00", "$")
    text = re.sub(r"[ \t]+", " ", text)
    return text


def sentences(text):
    """Rough sentence split, good enough for the rhythm heuristics below."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# ── CHECKS ───────────────────────────────────────────────────────────────────────────────────
def check(text, mode="prose", is_markdown=True):
    """Return (fails, warns). `mode` selects which layers apply."""
    fails, warns = [], []
    body = strip_noise(text) if is_markdown else text
    low = body.lower()

    def hit(label, pat, bucket, flags=re.I):
        m = re.search(pat, low if flags & re.I else body, flags)
        if m:
            frag = " ".join(m.group(0).split())[:70]
            bucket.append(f'{label}: "{frag}"')

    # — precedence-table rules (his voice wins, and it is stricter than APA) —
    if "—" in body:
        fails.append('em dash present (his hard rule: commas, ellipses, or parentheses)')
    if re.search(r"\S\s+/\s+\S|\S\s+/\S|\S/\s+\S", body):
        fails.append("spaces around a slash (write applied-AI/platform, never ' / ')")

    # — shared hard-block vocabulary (the check_outreach core, proper-noun aware) —
    for w in BANNED:
        if banned_hit(body, w):
            fails.append(f'banned/AI-tell word: "{w}"')
    for w in SOFT:
        if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
            warns.append(f'often-empty adverb: "{w}" — cut it unless it earns the word')
    # Inflected forms escape the word-boundary check ("leveraged", "robustness", "fostering").
    # Lowercase-only on purpose: a Capitalized stem is almost always a name (Foster, Delve Inc).
    for stem in ("seamless", "leverag", "delv", "robust", "showcas", "utiliz", "foster"):
        m = re.search(r"(?<![A-Za-z])(" + stem + r"[a-z]*)", body)
        if m:
            fails.append(f'banned/AI-tell word: "{m.group(1)}"')

    # — honesty guardrails: OUTBOUND surfaces only —
    # These gate what SHIPS to an employer, not what the workspace writes about itself. Found by
    # smoke-testing the hook against documents/compass.md, which reads: "$7.6M is the
    # tenure-scoped figure, not $11.5M." That is the guardrail doing its job, and flagging it
    # would train the reader to ignore the linter. A prose doc has to be able to name the retired
    # figure in order to warn about it; an email does not.
    if mode in ("outreach", "resume"):
        for w in RETIRED:
            if w.lower() in low:
                fails.append(f'retired/incorrect figure: "{w}"')
        # re.I: `low` is already lowercased, so an uppercase literal in a RETIRED_PATTERNS entry would
        # be DEAD here while looking alive in your config. Ported from main 2026-08-07 after a panel
        # found a live pattern that fired on resumes and on nothing else.
        for pat, label in RETIRED_PATTERNS:
            if re.search(pat, low, re.I):
                fails.append(f"retired/incorrect claim: {label}")

    # — no-slop patterns —
    for label, pat in HARD_PATTERNS:
        hit(label, pat, fails)
    for label, pat in WARN_PATTERNS:
        hit(label, pat, warns)

    for p in EMPTY_PHRASES:
        if p in low:
            fails.append(f'empty phrase: "{p}"')
    for p in SOFT_PHRASES:
        if p in low:
            warns.append(f'often-empty phrase: "{p}" (keep only if it earns the words)')
    for w in PROSE_WARN_WORDS:
        if re.search(r"(?<![a-z])" + w + r"(?![a-z])", low):
            warns.append(f'AI-tell in prose: "{w}"')

    # — rhythm heuristics —
    sents = sentences(body)
    run = 0
    for s in sents:
        run = run + 1 if len(s.split()) <= 4 else 0
        if run >= 3:
            warns.append("dramatic fragmentation: 3+ consecutive sentences of 4 words or fewer")
            break
    openers, streak = [s.split()[0].lower() for s in sents if s.split()], 1
    for i in range(1, len(openers)):
        streak = streak + 1 if openers[i] == openers[i - 1] else 1
        if streak >= 3:
            warns.append(f'robotic rhythm: 3+ sentences in a row opening with "{openers[i]}"')
            break

    # — APA construct (advisory: these are the two mechanizable ones) —
    # Serial comma. Lowercase-initial items only, which keeps dates and names
    # ("In January, Dana and I…") from reading as a three-item list.
    # Skipped on résumés: a Core Skills line IS a comma list by design, so this heuristic fires on
    # every clean CV and teaches the reader to skim past the output.
    if mode != "resume" and re.search(r"\b[a-z][\w-]*,\s+[a-z][\w-]*(?:\s+[a-z][\w-]*){0,2}\s+and\s+[a-z]", body):
        warns.append("serial comma: a 3-item list may be missing the comma before 'and' (APA)")
    if is_markdown:
        levels = [len(m.group(1)) for m in re.finditer(r"^(#{1,6})\s", body, re.M)]
        for a, b in zip(levels, levels[1:]):
            if b > a + 1:
                warns.append(f"heading hierarchy: level {a} jumps to level {b} (APA: no skipped levels)")
                break
    # His compound-term ruling, which overrides APA hyphenation.
    # "insurance-claims" is an established compound noun: it needs no hyphen, and a de-hyphen
    # ruling propagates to every sibling term rather than stopping at the one that was caught.
    for bad, good in (("civic-tech", "civic tech"), ("builder-PMs", "builder PMs"),
                      ("insurance-claims", "insurance claims")):
        if re.search(r"(?<![a-z])" + bad + r"(?![a-z])", body, re.I):
            warns.append(f'hyphenated compound: "{bad}" → "{good}" (his rule beats APA here)')

    # dedupe, order-preserving
    return list(dict.fromkeys(fails)), list(dict.fromkeys(warns))


def _hook_write():
    """PostToolUse on Write|Edit: lint the Markdown that just landed.

    Advisory by design. The write already happened, so exit 2 does not block anything — it feeds
    stderr back as revision feedback. Fails OPEN on every error: a linter that can wedge a file
    write is worse than no linter.
    """
    import json
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    path = (payload.get("tool_input") or {}).get("file_path")
    if not path or is_exempt(path) or not str(path).lower().endswith((".md", ".markdown", ".tex")):
        sys.exit(0)
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except Exception:
        sys.exit(0)
    # A .tex used to fall through this gate, so the hook said nothing on every résumé build.
    if str(path).lower().endswith(".tex"):
        fails, warns = check(strip_latex(text), mode="resume", is_markdown=False)
    else:
        fails, warns = check(text, mode="prose", is_markdown=True)
    if not fails:
        sys.exit(0)
    rel = os.path.relpath(path, REPO) if path.startswith(REPO) else path
    print(f"⚠️  house-style: {len(fails)} hard issue(s) in {rel} — fix before this ships:",
          file=sys.stderr)
    for f in fails:
        print(f"   🔴 {f}", file=sys.stderr)
    for w in warns[:4]:
        print(f"   🟡 {w}", file=sys.stderr)
    print("   (rules: .claude/skills/house-style/ · if this file quotes slop on purpose, "
          "add it to EXEMPT_GLOBS in scripts/check_style.py)", file=sys.stderr)
    sys.exit(2)


def _hook_stop(strict=False):
    """Stop hook: lint the final assistant message of the turn.

    ADVISORY ONLY unless --strict. A Stop hook that exits 2 blocks the turn from ending and can
    loop, so v1 reports at exit 0 and lets you decide on --strict once the false-positive rate
    is known. Chat prose is the one surface with no other gate, which is why it is worth watching
    even without teeth.
    """
    import json
    try:
        payload = json.load(sys.stdin)
        tpath = payload.get("transcript_path")
        if not tpath or not os.path.exists(os.path.expanduser(tpath)):
            sys.exit(0)
        last = ""
        with open(os.path.expanduser(tpath), encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("type") != "assistant":
                    continue
                content = (ev.get("message") or {}).get("content") or []
                text = "".join(c.get("text", "") for c in content
                               if isinstance(c, dict) and c.get("type") == "text")
                if text.strip():
                    last = text
    except Exception:
        sys.exit(0)
    if not last:
        sys.exit(0)
    fails, _ = check(last, mode="chat", is_markdown=True)
    if not fails:
        sys.exit(0)
    out = sys.stderr if strict else sys.stdout
    print(f"🟡 house-style (chat): {len(fails)} slop finding(s) in the last reply — "
          + "; ".join(fails[:6]), file=out)
    sys.exit(2 if strict else 0)


def main():
    argv = sys.argv[1:]
    if "--hook-write" in argv:
        _hook_write()
    if "--hook-stop" in argv:
        _hook_stop(strict="--strict" in argv)

    mode, hook, use_stdin, path = "prose", False, False, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1].strip().lower(); i += 2; continue
        if a == "--hook":
            hook = True; i += 1; continue
        if a == "--stdin":
            use_stdin = True; i += 1; continue
        path = a; i += 1

    if mode not in ("prose", "outreach", "resume", "chat"):
        print(f"unknown --mode '{mode}'. One of: prose | outreach | resume | chat")
        sys.exit(2)

    if use_stdin:
        # Chat IS Markdown. The old `mode != "chat"` skipped strip_noise entirely on this path, so
        # the documented way to lint a chat reply by hand lit up on the CONTENTS of every code
        # block — and HARD-INVARIANTS *requires* drafts be shown inside fences, so every outreach
        # review tripped it. The Stop hook that lints the same text already passes is_markdown=True
        # (see _hook_stop); the two chat paths disagreed, and the hook was the correct one.
        text, label, is_md = sys.stdin.read(), "(stdin)", True
    else:
        if not path:
            print(__doc__.split("Usage:")[1].split("Exit:")[0].strip())
            sys.exit(2)
        if hook and is_exempt(path):
            sys.exit(0)   # exempt file, advisory run: say nothing
        if not os.path.exists(path):
            print(f"file not found: {path}")
            sys.exit(0 if hook else 2)
        if not path.lower().endswith((".md", ".txt", ".markdown", ".tex")):
            sys.exit(0)   # not prose — nothing to say about it
        raw = open(path, encoding="utf-8", errors="ignore").read()
        if path.lower().endswith(".tex"):
            # A .tex used to exit 0 silently here. It is a résumé, so it gets the résumé mode
            # (honesty guardrails on) and the markup comes off before the rules run.
            text, label, is_md = strip_latex(raw), path, False
            if mode == "prose":
                mode = "resume"
        else:
            text, label, is_md = raw, path, True

    fails, warns = check(text, mode=mode, is_markdown=is_md)

    if hook:
        # PostToolUse advisory. The write already landed; exit 2 feeds stderr back as revision
        # feedback rather than blocking anything. Silence on a clean file keeps the transcript quiet.
        if fails:
            print(f"⚠️  house-style: {len(fails)} hard issue(s) in {label} — fix before this ships:",
                  file=sys.stderr)
            for f in fails:
                print(f"   🔴 {f}", file=sys.stderr)
            for w in warns[:4]:
                print(f"   🟡 {w}", file=sys.stderr)
            print("   (rules: .claude/skills/house-style/ · exempt this path in check_style.py "
                  "if it quotes slop on purpose)", file=sys.stderr)
            sys.exit(2)
        sys.exit(0)

    print(f"── house-style: {label} (mode={mode}) ──")
    for f in fails:
        print(f"   🔴 {f}")
    for w in warns:
        print(f"   🟡 {w}")
    if not fails and not warns:
        print("   ✅ clean")
    print(f"\n{len(fails)} hard · {len(warns)} advisory")
    sys.exit(2 if fails else (1 if warns else 0))


if __name__ == "__main__":
    main()
