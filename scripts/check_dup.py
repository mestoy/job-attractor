#!/usr/bin/env python3
"""check_dup.py — has this boss-hunt candidate already been screened/actioned?

FIRST screening step (WORKFLOW-RULES §0). Normalizes the company (and optional boss)
name, checks it against ALL durable stores, and returns a clear verdict so the pipeline
skips or surfaces accordingly — instead of re-screening or re-pitching a company/boss
we've already sent, dropped, blocked, or queued.

Usage:
    scripts/check_dup.py [--send-gate] "<company>" ["<boss>"]

Verdict: NEW  (safe to proceed)  |  ALREADY-SEEN (with where + inferred status)

Scoped deliberately: exact-normalized + a small alias map (no heavy fuzzy matching,
which would cause false "duplicate" hits and make us miss real new companies).
"""
import sys, os, re, csv, glob, json, io

# ⛔ THE ROOT IS THE INSTALL THIS SCRIPT LIVES IN, never the session's folder (kit #156, the same rule as the signing fix 9c7a273). This read
# CLAUDE_PROJECT_DIR first, so a session rooted elsewhere searched THAT folder's stores: the install's blocked list and send log were invisible
# (14 of a partner's Builds could not send) and another folder's stores could scope a send here. The ONLY redirect is the explicit
# JOBSEARCH_DATA_ROOT (a test harness or a second project sets it on purpose, and no Claude session ever does); a suite can also assign `REPO = tmp`.
INSTALL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.abspath(os.environ.get("JOBSEARCH_DATA_ROOT") or INSTALL_ROOT)

_REPO_AT_IMPORT = REPO


def _repo():
    """The project root (BUG-156, kit #37; kit #156). A patched module constant wins (suites assign `REPO = tmp`), then the explicit
    JOBSEARCH_DATA_ROOT if it is set NOW (a harness that sets it after import), else the root bound at import: the INSTALL this script lives in.
    CLAUDE_PROJECT_DIR is never consulted, because a session rooted elsewhere sets it to a folder that is not this install (kit #156)."""
    if REPO != _REPO_AT_IMPORT:
        return REPO
    env = os.environ.get("JOBSEARCH_DATA_ROOT")
    return os.path.abspath(env) if env else REPO


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from kit_config import COMPANY_ALIASES
except Exception:
    COMPANY_ALIASES = []

# store file -> the status a hit there implies.
# Add any store YOU keep. A durable store missing from this dict is a dedup blind spot:
# rows in it come back "🟢 NEW" and get re-screened or, worse, re-pitched.
STORES = {
    "documents/blocked-employers-list.md": "BLOCKED / declined",
    # A "banked, build-ready" board is the classic missed store: vetted-but-unbuilt rows look
    # brand new to any check that only searches what was already SENT, so they get rediscovered
    # and re-screened from scratch.
    "documents/green-board.md":            "BANKED on the GREEN BOARD (already vetted — do not re-screen)",
    "outreach_log.md":                     "SENT (or drop logged)",
    "job_search_tracker.csv":              "CONTACTED / applied / skipped",
    "documents/outreach-queue.md":         "IN QUEUE (awaiting your review)",
    "documents/outreach-queue-archive.md": "SENT or DROPPED (archived)",
    "documents/discovery-board.md":        "on the discovery board",
    "prospect_queue.md":                   "IN PROSPECT QUEUE (awaiting review)",
    "documents/correspondence-log.md":     "PRIOR CORRESPONDENCE (message sent/received)",
    "documents/outreach-decision-log.md":  "in the outreach DECISION LOG (prior build/pick)",
    # prior-work narrative docs: a company you assessed and dropped often survives ONLY as prose
    # in a notes file, which is exactly where dedup forgets to look. Hits here are usually
    # 🟡 POSSIBLE prose — verify the record before acting.
    "documents/outreach-metrics.md":       "ASSESSED in a prior discovery/metrics run (may be a DROP)",
    "documents/boss-hunt-learning-log.md": "SCREENED in the boss-hunt learning log (prior assessment)",
    # built-but-unsent drafts + prior application material: durable, and invisible to dedup
    # unless the directory is globbed → re-pitch risk.
    "documents/ready-to-send/**/*":        "BUILT but UNSENT draft (ready-to-send)",
    "documents/applications/**/*":         "in APPLICATIONS (prior application material)",
    # DEDUP HOLE CLOSED. A findings run that discovery WRITES was never a store dedup READS, so
    # a company screened yesterday came back NEW today and agents re-walked it from scratch.
    # Soft-tier, never send-gate: a screened company is re-screenable, it is not re-DISCOVERABLE.
    "documents/findings/*.jsonl":          "SCREENED in a prior agent discovery run",
}

# ⛔ THE RECORD-KIND DISTINCTION (kit issue #8 / BUG-134). `documents/banked-candidates-*.md`
# USED to sit in STORES above and produce the exact same ALREADY-SEEN verdict as a blocked list
# or a sent log. That is backwards: the banked files say, verbatim, in their own header, "A name
# in this file means worth screening, never worth sending." A row there has passed the
# MECHANICAL gates only and is EXPLICITLY queued for the screen this tool gates — so a hit here
# is not evidence the work was done, it is the reason the work is next. Measured against the
# SCREEN GATE's own instruction ("proceed only on NEW; ALREADY-SEEN/POSSIBLE = STOP"): on one
# install, 800 of 814 banked rows returned ALREADY-SEEN, so the gate refused nearly the entire
# queue it was pointed at, and every session had to override it by routine — a gate overridden
# by routine is not a gate.
#
# ⚖️ THIS DOES NOT WEAKEN REAL DEDUP. A company that is BOTH banked AND genuinely already-seen
# (blocked, on the green board, in outreach_log, in the send log, …) still reads ALREADY-SEEN
# off that OTHER store — this dict is consulted separately, in `main()`, and only ever SOFTENS
# a verdict that would otherwise have been NEW anyway. A row banked and nothing else now reads
# NEW-TO-SCREEN instead of a bare NEW, carrying the queue context; it was never going to block.
QUEUED_STORES = {
    "documents/banked-candidates-*.md": "BANKED by a prior sweep (hard gates passed, culture still owed)",
}

# Rebrands / trading names — one set per real-world entity, so dedup doesn't treat one
# company as two. Add yours to COMPANY_ALIASES in kit_config.py.
ALIASES = list(COMPANY_ALIASES)

LEGAL = r"\b(inc|llc|ltd|corp|co|gmbh|plc|pbc|labs|technologies|systems|data|the)\b"
TLD = r"\.(com|dev|io|ai|co|org|net|app|tech|xyz|so|sh|dev)\b"

def norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(TLD, "", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(LEGAL, " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def norm_lite(s: str) -> str:
    """Like norm() but KEEPS legal/common tokens (inc, data, systems, co...).

    FALSE-NEW BUG, SECOND HALF. variants() was taught to fall back to the raw name for an
    all-legal-token company, but _strong() still normalized the LINE with norm(), which strips
    those same tokens, so the needle 'data systems inc' could not match
    '- Data Systems Inc (blocked...)', which norm()s to ' blocked '. The gate still reported
    🟢 NEW. A false NEW is the worst direction: it PASSES the send gate.
    """
    s = s.lower().strip()
    s = re.sub(TLD, "", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _boundary_norm(s: str, keep_legal: bool = False) -> str:
    """Like norm(), but "(" and ")" become a hard separator a multi-word needle can't cross,
    instead of a plain space.

    `keep_legal`: when the needle being boundary-checked was matched via norm_lite() (which
    KEEPS legal/common tokens like "co", "plc", "gmbh" -- see norm_lite()'s own docstring), this
    must keep those same tokens too, or the rescue and the boundary check disagree about what the
    needle even is. Without this, an all-legal-token needle like "plc gmbh co" survives
    norm_lite()'s rescue but then fails the boundary re-check, because a hardcoded
    strip-legal-tokens boundary_norm() strips the needle's own tokens out from under it,
    reintroducing the exact false-🟢 norm_lite() exists to close. Callers pass `keep_legal=True`
    only when the hit came from norm_lite(); a hit from norm() still strips legal tokens here
    exactly as before, since that needle never had them to begin with.

    THE BOUNDARY BUG: norm() strips ALL punctuation to spaces, so two unrelated words either
    side of a parenthetical seam can become falsely adjacent -- e.g. blocked-list text
    "...token 'Foo')** (bar-enablement..." collapses under norm() to "...token foo bar
    enablement...", which matches the needle "foo bar" even though "foo" closes one aside about
    a company called Foo and "bar" opens an unrelated segment tag. Scoped to multi-word-needle
    matching only (see _strong) -- single-word needles can't span a boundary by definition, and
    norm()/norm_lite() themselves are untouched everywhere else.

    Deliberately NOT scoped on "." too: abbreviated names ("A.B. Example", "U.S. Example") need "."
    to stay a plain space, or a missed match there is a false NEW (the worst direction).

    Also deliberately NOT boundarying every lone "(" or ")": a SINGLE parenthetical that expands
    the same entity's own name ("ABC (Alpha Beta Corp)") has no cross-entity seam and must
    keep matching. The actual dangerous shape is a CLOSE paren immediately followed by an OPEN
    paren -- two adjacent-but-separate parenthetical asides. Only that "),... (" seam becomes a
    hard separator; a lone paren is left as a plain space, same as norm().
    """
    s = s.lower().strip()
    s = re.sub(TLD, "", s)
    s = re.sub(r"\)\s*\**\s*\(", " \x00 ", s)
    s = re.sub(r"[^a-z0-9\x00 ]", " ", s)
    if not keep_legal:
        s = re.sub(LEGAL, " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_hit(window: str, nd: str) -> bool:
    """Does needle `nd` hit `window` under norm() or norm_lite(), surviving the boundary
    re-check?

    The boundary re-check must agree with WHICH normalization produced the hit. A needle that
    hit via norm() never had legal tokens (norm() stripped them out of the needle too), so it is
    re-checked against a boundary_norm() that also strips them. A needle that hit ONLY via
    norm_lite() (an all-legal-token name like "plc gmbh co") KEPT its legal tokens, so it must be
    re-checked against a boundary_norm() that also keeps them, or the rescue and the boundary
    check are arguing about two different needles and the rescue always loses.
    """
    hit_norm = nd in norm(window)
    hit_lite = nd in norm_lite(window)
    if not (hit_norm or hit_lite):
        return False
    if " " not in nd:
        return True
    # a multi-word needle that only matched by crossing a "(...)(...)" clause boundary is not a
    # real record match -- see _boundary_norm(). Check the boundary re-normalization that matches
    # whichever plain normalization actually produced the hit; either surviving is enough.
    if hit_norm and nd in _boundary_norm(window):
        return True
    if hit_lite and nd in _boundary_norm(window, keep_legal=True):
        return True
    return False


# Ordinary industry vocabulary that must NEVER become a bare single-token dedup needle. Every one
# of these appears in dozens of real company names, so as a needle it matches everything and the
# 🔴 it produces is noise that looks like evidence. The full-name needle still catches real records.
GENERIC_TOKENS = {
    "health", "healthcare", "financial", "finance", "global", "credit", "insurance", "capital",
    "partners", "group", "systems", "solutions", "technology", "technologies", "digital", "data",
    "labs", "software", "services", "network", "networks", "platform", "medical", "clinical",
    "security", "payments", "banking", "analytics", "intelligence", "consulting", "ventures",
    "holdings", "national", "american", "united", "general", "advanced", "innovation", "innovations",
    "management", "resources", "enterprise", "enterprises", "international", "associates", "company",
    "corporation", "industries", "products", "science", "sciences", "research", "energy", "insight",
    "insights", "commerce", "market", "markets", "media", "mobile", "cloud", "online", "direct",
}


def variants(name: str):
    n = norm(name)
    if not n:
        # FALSE-NEW BUG FIXED 2026-07-19 (pipeline audit): a name made ENTIRELY of LEGAL
        # tokens ("Data Systems Inc") normalized to "" → empty needle set → the search loop
        # never ran → reported "🟢 NEW, safe to proceed" with full confidence. That is the
        # worst failure direction: a false NEW passes the gate. Fall back to the raw name.
        n = re.sub(r"[^a-z0-9 ]", " ", name.lower())
        n = re.sub(r"\s+", " ", n).strip()
    out = {n}
    # add the single most distinctive token (>=4 chars) to catch "ExampleData" inside prose
    #
    # FALSE-🔴 BUG FIXED. The fallback above rescues an all-legal-token name, but this block then
    # handed the search a BARE GENERIC TOKEN as a needle:
    #     variants("Data Systems Inc") -> {"data systems inc", "data"}
    #     variants("The Labs Data Co") -> {"the labs data co", "labs"}
    # and "data"/"labs" match any company with those words in its name. A false 🔴 silently kills
    # a real candidate before it is ever screened, which is the same harm class _capitalized_hit
    # was written to prevent, arriving through a different door.
    #
    # Two guards, DELIBERATELY REDUNDANT (defense in depth on a gate whose failure silently kills
    # a real candidate). First: if norm() emptied the name, every token in it is a legal/generic
    # word by definition, so there IS no distinctive token, do not invent one. Second: never emit
    # a bare token that norm() itself would strip. The full-name needle still matches a genuine
    # record, so nothing real is lost.
    # THIRD GUARD: the two guards above are necessary and still not sufficient. A short generic
    # word can also be merely-not-a-legal-suffix and merely 4+ chars long, so it slips past both:
    #     "Blue River Co"   -> "blue"      matched an unrelated "Blue ___" company
    #     "QZT Global"      -> "global"    matched every "___ Global" company
    #     "Zed Health"      -> "health"    matched every health company on the boards
    #     "QT Financial"    -> "financial" matched an unrelated "___ Financial" company
    # `norm(cand)` passes all of these, because they are ordinary industry nouns, not legal
    # suffixes. A false 🔴 is the dangerous direction — it reads exactly like a completed screen
    # and silently kills a real candidate before anyone looks at it.
    #
    # The needle's ONLY job is to catch a concatenated brand name buried in prose ("ExampleData").
    # That needs a genuinely distinctive token: take the FIRST token (an English company name puts
    # the brand first — "Acme Labs", "Otherco Inc"), require >= 6 chars, and reject ordinary
    # industry vocabulary. The FULL-NAME needle is unaffected and still matches genuine records.
    _fellback = not norm(name)
    toks = [t for t in n.split() if len(t) >= 4]
    if toks and not _fellback:
        cand = toks[0]
        if len(cand) >= 6 and cand not in GENERIC_TOKENS and norm(cand):
            out.add(cand)
    # aliases
    for grp in ALIASES:
        if n in grp or any(t in grp for t in n.split()):
            out |= {norm(a) for a in grp}
    return {v for v in out if v}

def _capitalized_hit(line, nd):
    """Does `nd` appear in the ORIGINAL line as a proper noun (capitalized)?

    FALSE-POSITIVE CLASS FIXED. Matching was done on a lowercased line, so a company name that
    is also an ordinary English word matched its lowercase usage:
        "Verifiable"  matched  "[verifiable accomplishments]"   (a TEMPLATE placeholder)
        "Zqramp"      matched  "the zqramp that reaches..."
        "Vector"      matched  "open-source vector-DB / RAG"
    Each produced a hard 🔴 ALREADY-SEEN, which silently kills a real candidate before it is ever
    screened. Company names are proper nouns; their genuine records are capitalized. So require
    at least one capitalized occurrence before calling a hit STRONG.

    DIGIT-LEADING NAMES: an earlier version tested `match[0].isupper()`, and `"1".isupper()` is
    False, so a name like `1Example` could NEVER be strong, degraded 🔴 to 🟡, and mail-draft.sh
    (which blocks only on exit 1) let a BLOCKED employer through to a send with the warning
    suppressed. Test ANY character instead of the first one.
    """
    for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(nd) + r"(?![a-z0-9])", line, re.I):
        g = m.group()
        if g != g.lower():          # any uppercase char anywhere -> proper-noun usage
            return True
    return False


def _is_template(line):
    """Template/placeholder lines are not records, `[fill me in]` style brackets.

    MUST NOT match `[[wiki-links]]`. A first cut used a bare `\\[[a-z][^\\]]{3,}\\]`, which matched
    the inner bracket of every `[[memory-link]]`, and a blocked-employers list whose entries end
    in those links was silently downgraded ENTIRELY from 🔴 hard-block to 🟡. That disabled the
    single most important gate in the pipeline while looking like a false-positive fix.
    Lesson for any test set: verify with companies that appear in ONE store only. A name present
    in several stores stays 🔴 from elsewhere and masks a per-store regression.

    A STORE RECORD IS NEVER A TEMPLATE. Blocked-list entries carry bracketed prose of their own
    (`- Acme (... [over-promoted product leaders, ...])`), and were being downgraded. A line
    shaped like a record (bullet + capitalized name + `(` or an em dash) is a record, whatever
    brackets it also holds.
    """
    if re.match(r"\s*[-*]\s+[A-Z0-9][\w&.\-' ]{1,40}\s*[\(—]", line):
        return False
    return bool(re.search(r"(?<!\[)\[[a-z][^\]\[]{3,}\](?!\])", line))


def _strong(path, line, nd):
    """A STRONG match = the name is an actual entry/record, not incidental prose.
    Avoids false positives when a company name is also a common word (a company called
    'Notion' or 'Zqramp' colliding with ordinary uses of those words in your notes)."""
    if _is_template(line):
        return False
    # A JD's own text is not a record of contacting anyone. A saved posting under
    # documents/applications/*/job_posting.md is full of generic tech vocabulary, and
    # "- Vector databases/embeddings/RAG" hard-blocked a company called Vector. The application
    # FOLDER name still matches and a genuine contact is recorded in the tracker and outreach log,
    # so nothing real is lost by demoting these to prose.
    low_path = path.lower()
    if "job_posting" in low_path or low_path.endswith(("/jd.md", "_jd.md")):
        return False
    # Multi-word names are distinctive enough; single-token names need the proper-noun check.
    if " " not in nd and not _capitalized_hit(line, nd):
        return False
    ls = line.lstrip()
    if path.endswith(".csv"):
        # company is the 2nd CSV field: date,company,...
        fields = line.split(",")
        return len(fields) > 1 and (nd in norm(fields[1]) or nd in norm_lite(fields[1]))
    # markdown: an entry header (## …), a list bullet (- …), or the name near line start
    # Check BOTH normalizations, see norm_lite() for why norm() alone misses legal-token names.
    if ls.startswith(("## ", "### ", "- ", "* ", "> ")):
        window = ls[:120]
        return _norm_hit(window, nd)
    window = line[:60]
    return _norm_hit(window, nd)

def loose_tokens(name: str):
    """The needles `variants()` EXTRACTED from a longer name, rather than the name itself.

    🔴 WHY THIS EXISTS. `variants("Some Totally Different Co")` emits both the full name and the
    bare token `totally`. That one word then matches any prose in a grepped store that happens to
    contain it, and the send is blocked 🔴 ALREADY-SEEN for a company nobody ever contacted. The
    capitalization guard does not help: a word opening a sentence or a quoted phrase is capitalized
    like a brand.

    ⚖️ THE ONE-WORD NEEDLE IS A WEAK SIGNAL BY CONSTRUCTION, and the comment that introduced it says
    so: its only job is to catch a concatenated brand name buried in prose. Catching a brand in
    prose is a reason to LOOK, never proof of contact. The FULL-NAME needle carries strong detection
    and is untouched, so this narrows false BLOCKS without weakening real dedup.

    ⚠️ A SINGLE-WORD COMPANY IS NOT AFFECTED, because its token IS its name and `t != n` excludes
    it. Only a token pulled out of a LONGER name is demoted, which is the case that cannot tell a
    brand from an English word.
    """
    n = norm(name) or norm_lite(name)
    toks = [t for t in n.split() if len(t) >= 4]
    return {t for t in toks[:1] if t and t != n}


# `## <date> · <Company> · <Person> ...` — outreach_log.md's own entry-header shape, the field
# order this reader already cites in the warm-ask-naming comment below ("a real prior contact
# always names the company in the block HEADER"). Scoped narrowly to THIS ONE STORE on purpose —
# see the header comment on `is_warm_ask_naming` for why a general header rule is not safe
# everywhere.
_OUTREACH_HEADER = re.compile(r"^##\s*[\d.\-/]+\s*·\s*([^·]+?)\s*·")

# kit#174. `documents/applications/**/*` and `documents/ready-to-send/**/*` are dir-glob STORES
# (STORES, above) — they glob whatever real files sit in those folders, which for applications is
# CVs and other saved material: PDFs, and macOS's `.DS_Store`. Neither is text, and kit#159's
# strict UTF-8 decode in `search_file()` raised UnicodeDecodeError on both, crashing check_dup for
# EVERY company (any install with a saved PDF under documents/applications reproduces it) and, via
# mail-draft.sh's send gate, refusing every send with exit 4.
#
# Classified by EXTENSION first (fast, no read): a known binary type or `.DS_Store` is always
# skipped; a known TEXT type always proceeds to the strict decode in `search_file()` (a corrupt
# `.md` etc. must still fail closed — that is kit#159's whole point, not a bug to route around).
# An extension in neither list is classified by CONTENT: a NUL byte in the first 8KB is the cheap,
# reliable "this is not text" signal (real text files essentially never contain one; binary
# formats commonly do early). OSError while peeking is NOT swallowed here — it is left for
# `search_file()`'s own strict open to raise, so an unreadable file still refuses loudly.
_BINARY_STORE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".docx", ".xlsx", ".pptx", ".zip"}
_TEXT_STORE_EXTS = {".md", ".txt", ".log", ".jsonl", ".json", ".csv", ".tex", ".yml"}


def _is_binary_store_file(full_path: str) -> bool:
    """True when a dir-glob store file should be skipped as non-text (kit#174)."""
    if os.path.basename(full_path) == ".DS_Store":
        return True
    ext = os.path.splitext(full_path)[1].lower()
    if ext in _BINARY_STORE_EXTS:
        return True
    if ext in _TEXT_STORE_EXTS:
        return False
    try:
        with open(full_path, "rb") as fb:
            chunk = fb.read(8192)
    except OSError:
        return False  # let search_file()'s own strict open raise this loudly instead
    return b"\x00" in chunk


def search_file(path: str, needles: set, loose: set = ()):
    full = os.path.join(_repo(), path)
    if not os.path.exists(full):
        return []
    strong, weak = [], []
    # kit issue #8 / BUG-175. The most recent `## <date> · <Company> · <Person>` header seen so
    # far this file, tracked while scanning forward — this is what lets a quoted-body line be
    # judged against the entry it actually belongs to, instead of a fixed vocabulary of past
    # templates' wording. File-scoped (reset per `search_file` call) and ONLY consulted for
    # `outreach_log.md` — see `is_warm_ask_naming` below.
    _header_company_norm = None
    # kit#159 (a): errors="ignore" used to silently drop undecodable bytes, so a mid-sync or
    # corrupted store still read as some lines with the bad bytes gone, no error, possibly zero
    # matches -- 3f wrote raw undecodable bytes into correspondence-log.md and got a clean 🟢 NEW.
    # Strict decode first: a bad-encoding file refuses the same way a permission-denied one does
    # (both are "exists but cannot be trusted"), rather than silently reading a partial file.
    try:
        with open(full, "rb") as fb:
            _text = fb.read().decode("utf-8")
    except OSError as e:
        raise OSError(f"{full}: {e.__class__.__name__}: {e}") from e
    except UnicodeDecodeError as e:
        raise UnicodeDecodeError(e.encoding, e.object, e.start, e.end, f"{full}: {e.reason}") from e
    with io.StringIO(_text) as f:
        for i, line in enumerate(f, 1):
            if path == "outreach_log.md":
                _hm = _OUTREACH_HEADER.match(line)
                if _hm:
                    _header_company_norm = norm(_hm.group(1)) or norm_lite(_hm.group(1))
            # Check BOTH normalizations here too. norm() strips legal/common tokens (inc, data,
            # systems, co...), so an all-legal-token needle like "data systems inc" could never
            # survive this PRE-FILTER, it never even reached _strong(), and the company came back
            # 🟢 NEW even though it sat in the blocked list. Fixing _strong() alone leaves the bug
            # alive one layer up; the candidate filter has to be as permissive as the matcher.
            #
            # A STAGED draft entry is an IN-FLIGHT CONSTRUCTION record, not a "contacted" one -
            # the same category SEND_GATE_STORES carves out. mail-draft.sh writes a
            # `STAGED (draft created, awaiting … send)` block the moment a draft is staged, and
            # nothing has been sent yet. So a match on such a line is at most a 🟡 POSSIBLE signal,
            # never a 🔴 do-not-send, which would block re-staging and, worse, block the actual
            # first send. A real SENT block carries no STAGED marker and still matches strong.
            _low_line = line.lower()
            is_staged = ("staged" in _low_line
                         and ("draft" in _low_line or "not yet sent" in _low_line
                              or line.lstrip().startswith("<!--")))
            # A WARM-ASK NAMING IS NOT CONTACT. A connector-ask template names a few TARGET
            # companies to a warm contact ("Rather than send you a long list, I picked three: …").
            # The company is the SUBJECT of the ask, not the recipient — nobody there has been
            # contacted. Those lines live in outreach_log.md, a send-gate store, so every named
            # company was being 🔴 do-not-send'd for a COLD outreach it had never received.
            #
            # Safe because a REAL prior contact always names the company in the block HEADER
            # ("## <date> · SomeCo · <boss>"), which still matches strong. A warm ask's header
            # names the CONTACT instead, so the company appears only in the `Targets named:`
            # metadata and inside the quoted body — both demoted to 🟡 WEAK here.
            #
            # ⛔ GENERALIZED (kit issue #8 / BUG-175). This used to fire ONLY when the quoted line
            # contained one of two LITERAL phrases lifted from one connector-ask template. A reply
            # delivering the same names in ANY other wording missed both phrases and scored a
            # strong hit. The mechanism the comment above already claims is now what actually
            # runs: `_header_company_norm` is the most recent `## date · Company · Person` header
            # seen scanning forward, so ANY quoted line is demoted when the enclosing entry's own
            # header names a DIFFERENT company — whatever words the quote happens to use.
            #   ⚖️ SCOPED TO outreach_log.md ONLY, on purpose. A system-wide version of this rule
            #   was proposed and REJECTED by review: applied to blocked-employers-list.md (no
            #   `## ` headers at all) it would have silently disabled the entire blocked list;
            #   applied to job_search_tracker.csv (no headers, no markdown) it defeats the CSV
            #   company-column match entirely. Neither file can ever set `_header_company_norm`
            #   non-None (computed only when `path == "outreach_log.md"`), so this generalization
            #   structurally cannot reach them. `job_search_tracker.csv` was never vulnerable to
            #   this bug in the first place: `_strong()` matches its dedicated company COLUMN,
            #   never free-text notes.
            is_warm_ask_naming = (
                "targets named" in _low_line
                or (line.lstrip().startswith(">")
                    and _header_company_norm is not None
                    and _header_company_norm not in needles)
            )
            low = " " + norm(line) + " "
            low_lite = " " + norm_lite(line) + " "
            # ⛔ EVERY MATCHING NEEDLE IS WEIGHED, AND THE STRONGEST VERDICT WINS. This loop used
            # to `break` on the FIRST needle that matched, which was harmless while all needles were
            # equal. It stopped being harmless the moment one could be DEMOTED: a correspondence
            # header naming the company matches BOTH the full name and the extracted token, and
            # whichever the set yielded first decided the line. A weak needle shadowing a strong one
            # turns a real prior contact into a 🟡, the wrongly-ALLOWS direction and the costlier.
            _hit = False
            _strong_hit = False
            # ⚠️ SORTED, so the outcome does not depend on set-iteration order. It should not
            # matter (the loop keeps going until a STRONG hit is found), and that is the point: a
            # regression reintroducing an early `break` would then pass or fail by hash order, and
            # a test that flips with the hash seed proves nothing. Deterministic order also makes
            # the reported line stable between runs.
            for nd in sorted(needles):
                # WORD-BOUNDARY match only (padded low handles start/end) — no loose substring,
                # which would match a short name inside a common word (e.g. "vent" in "prevent").
                if (" " + nd + " ") in low or (" " + nd + " ") in low_lite:
                    _hit = True
                    # ⛔ AN EXTRACTED TOKEN NEVER BLOCKS A SEND. Third demotion here, same reasoning
                    # as the other two: the match is real, what it PROVES is weaker than "already
                    # contacted", and a false 🔴 blocks a first send that was never made.
                    if nd not in loose and _strong(path, line, nd):
                        _strong_hit = True
                        break
            # AN EXONERATED / RE-ADDED BLOCKED-LIST ROW IS NOT A DO-NOT-SEND (ported from AJS, Q29 M2).
            # A company re-added after audit keeps its blocked-list row with an exoneration marker
            # ("not blocked", "entry corrected", ...) and the registry clears is_blocked via the same
            # pattern. Demote such a row to a weak 🟡 (already seen, not a block), scoped to the blocked
            # list and reusing exoneration.EXONERATED so the two never diverge. Fails closed: if the import
            # broke (_EXONERATED is None) nothing is demoted, so the row still blocks.
            _exonerated = (path == "documents/blocked-employers-list.md"
                           and _EXONERATED is not None and bool(_EXONERATED.search(_low_line)))
            if _hit:
                is_strong = ((not is_staged) and (not is_warm_ask_naming)
                             and (not _exonerated) and _strong_hit)
                (strong if is_strong else weak).append((i, line.strip()[:160]))
    return strong, weak

# SEND-GATE stores: only the ones that mean "already BLOCKED or CONTACTED" — a true do-not-send.
# The other stores (decision-log, queues, discovery-board, prospect-queue, metrics) are
# CONSTRUCTION/DISCOVERY records — the company you are actively building is EXPECTED to appear
# there, because you log the pick before you send. If those stores gated the send, every build
# would block itself the moment it was written down.
SEND_GATE_STORES = {
    "documents/blocked-employers-list.md",
    "outreach_log.md",
    "job_search_tracker.csv",
    "documents/correspondence-log.md",
}

def blocked_key_hit(company: str):
    """EXACT canon-key match against the parsed blocked list. Returns the key, or None.

    ⛔ THE DEFECT THIS CLOSES. Aggregators emit space-stripped brand names, and norm() PRESERVES
    spaces (`[^a-z0-9 ]`). So the needle and the record never met:

        "Some Co Networks" -> norm 'some co networks'   (the blocked-list record)
        "Somesconetworks"  -> norm 'somesconetworks'    (what a sweep row actually says)

    check_dup returned 🟢 NEW for the space-stripped form while returning 🔴 for the spaced form of
    the same company. Dedup is step 0 of every screen, which makes this the one gate whose failure
    admits a vetoed company to the whole pipeline.

    ⚖️ WHY EQUALITY AND NOT A LOOSER SUBSTRING TEST. The obvious fix — strip spaces from both sides
    and keep the existing `in` test — is unsafe, because space-stripped text has no word
    boundaries: a real blocked short name can be a substring of an unrelated ordinary word.
    canon() keys are compared for EQUALITY, so they are collision-free at any length.

    This REUSES screen_sweep.canon + blocked_keys_from_list rather than forking them — one
    canonical core, several consumers; never fork the core. The fuzzy needle machinery above is
    deliberately left untouched; this is an ADDITIONAL precise check, not a replacement.

    kit#92 (narrow half, PROXY P7 2026-09-22): a company blocked only under an abbreviation or
    acronym (no expansion anywhere the parser reads) used to read clean under any other spelling,
    because this check never consulted ALIASES (kit_config.COMPANY_ALIASES) at all — only the
    fuzzy, non-blocking dedup path below did. Fixed by unioning each ALIASES group's canon()
    keys into the blocked set at the SAME exact-equality standard as the check above: this can
    only ADD a refusal, never remove one, which is the only safe direction to widen a hard gate.
    Deliberately NOT done here: fuzzy/substring matching, or automatically treating a
    parenthetical expansion in blocked-list prose as an alias — both stay with kit_config's own
    curated ALIASES list; the owner is separately ruling on whether to widen further.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from screen_sweep import canon, blocked_keys_from_list
    except Exception:
        # FAIL CLOSED-ISH: a broken import must not silently downgrade the blocked check to
        # "no hit". Returning the sentinel makes the failure visible in the verdict instead.
        return "__import_failed__"
    k = canon(company)
    if not k:
        return None
    blocked = blocked_keys_from_list()
    if k in blocked:
        return k
    for group in ALIASES:
        keys = {canon(m) for m in group}
        hit = keys & blocked
        # Return the BLOCKED key itself (what `_blocked_entry_lines` and every other caller
        # expects), never `k` (the queried company's own canon) — they can legitimately differ,
        # that difference is the whole point of an alias.
        if k in keys and hit:
            return sorted(hit)[0]
    return None


def _blocked_entry_lines(key):
    """The blocked-list line(s) whose leading name canon()s to `key`, for the verdict printout.

    Best-effort only: the verdict above does not depend on finding the line, so a miss here just
    means you read the file yourself rather than getting a quoted excerpt.
    """
    try:
        from screen_sweep import canon
        path = os.path.join(_repo(), "documents/blocked-employers-list.md")
        out = []
        with open(path, encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, 1):
                ls = line.lstrip()
                if not ls.startswith(("- ", "* ")):
                    continue
                head = re.split(r"[(:—–·|]", ls[2:].replace("**", ""))[0]
                if canon(head) == key:
                    out.append((i, ls.rstrip()[:150]))
        return out
    except Exception:
        return []


try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _ADDED_HERE = _HERE not in sys.path
    if _ADDED_HERE:
        sys.path.insert(0, _HERE)
    try:
        from exoneration import EXONERATED as _EXONERATED
    finally:
        if _ADDED_HERE and _HERE in sys.path:
            sys.path.remove(_HERE)
except Exception:
    # Fail CLOSED: None means "no row is skipped", so a 'not blocked' line still reads as a block.
    _EXONERATED = None


# ── Q29b: THE BARE TOKEN'S CLAIM ON THE BLOCKED LIST (2026-10-04, plan rev 2, Review 125) ────────
#
# A candidate's FIRST word is the one distinctive token an aggregator spelling shares with a longer
# blocked name. What it may CLAIM depends on what it equals:
#   * it EQUALS a blocked entry's whole canon key (`quorble` for the entry `Quorble`, `plinth` for
#     `Plinth`): the blocked company IS that word, so a candidate that opens with it stays 🔴 and says
#     it may be a different company with the same name (verify). Review 125 measured 1,311 live
#     one-word blocks reachable ONLY this way (`Sprockwin Technologies`), so this MUST NOT soften.
#   * it is only PART of a longer blocked name (`gladwyn` inside `Gladwyn River Fake`): a collision
#     to verify, 🟡, never a block on that word alone. On --send-gate it still HOLDS the send.
# A candidate the registry already declares CLEARED has been verified, so it raises neither.
BARE_NOTE = "may be a different company with the same name; verify before you proceed"
_HEADS_CACHE = {}


def _blocked_heads():
    """[(line_no, line_excerpt, canon_key, words)] for every live (non-exonerated) bullet head of
    the blocked list. Cached on the file's stat, so a 2,000-name measurement reads it once."""
    path = os.path.join(_repo(), BLOCKED_LIST_PATH)
    try:
        st = os.stat(path)
    except OSError:
        return []
    stamp = (path, st.st_mtime_ns, st.st_size)
    hit = _HEADS_CACHE.get(stamp)
    if hit is not None:
        return hit
    out = []
    try:
        from screen_sweep import canon
        with open(path, encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, 1):
                ls = line.lstrip()
                if not ls.startswith(("- ", "* ")):
                    continue
                if _EXONERATED is not None and _EXONERATED.search(ls.lower()):
                    continue
                head = re.split(r"[(:\u2014\u2013\u00b7|]", ls[2:].replace("**", ""))[0]
                words = re.sub(r"[^a-z0-9 ]", " ", head.lower()).split()
                if words:
                    out.append((i, ls.rstrip()[:150], canon(head), words))
    except Exception:
        return []
    _HEADS_CACHE.clear()
    _HEADS_CACHE[stamp] = out
    return out


def _bare_token(company: str):
    """The candidate's first distinctive word, or None (too short, or ordinary industry vocabulary)."""
    n = norm(company) or norm_lite(company)
    toks = n.split()
    if not toks:
        return None
    t = toks[0]
    if len(t) < 4 or t in GENERIC_TOKENS or not norm(t):
        return None
    return t


def blocked_token_hits(company: str):
    """{"token", "whole": [(ln, txt)], "part": [(ln, txt)]} for the candidate's bare token against
    the blocked list. Empty lists when there is no token, or when the registry declares the
    candidate cleared (that declaration is the recorded verification)."""
    out = {"token": None, "whole": [], "part": []}
    t = _bare_token(company)
    if not t:
        return out
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from screen_sweep import canon, blocked_keys_from_list
        import employers
        keys = blocked_keys_from_list()
        row = employers.registry().get(canon(company))
        if row is not None and row.get("status") == "cleared":
            return out
    except Exception:
        return out
    out["token"] = t
    heads = _blocked_heads()
    if canon(t) in keys:
        lines = [(ln, txt) for ln, txt, k, _w in heads if k == canon(t)]
        if not lines:
            reg = employers.registry().get(canon(t)) or {}
            lines = [(0, f"(registry alias key {canon(t)!r} of {reg.get('display', '?')!r})")]
        out["whole"] = lines
    else:
        out["part"] = [(ln, txt) for ln, txt, k, w in heads if w and w[0] == t and k != canon(t)]
    return out


def blocked_list_verdict(company: str):
    """"red", "yellow" or None from the blocked list's two precise checks (canon key, bare token).
    The fuzzy needle scan is not part of it. The measurement test drives this in-process."""
    if blocked_key_hit(company):
        return "red"
    h = blocked_token_hits(company)
    if h["whole"]:
        return "red"
    if h["part"]:
        return "yellow"
    return None


SENDLOG = "documents/send-log.jsonl"
# Statuses that mean the message REACHED the person. Everything else in the send log (staged,
# drafted, bounced, blocked, failed) means it did not, and must stay 🟡 — a bounce in particular
# is the case where a RETRY is correct, so promoting it to 🔴 would block the very send it should
# enable.
SENDLOG_DELIVERED = {"sent", "delivered", "replied", "submitted"}


def _open_sendlog(path, errors="ignore"):
    """The send log as a reader should see it: the file plus any spooled change not yet folded in (sendlog_lock.open_lines). Readers take no lock.
    A copy of scripts/ without sendlog_lock.py reads the file as it always did."""
    try:
        import sendlog_lock
    except ImportError:
        import importlib.util
        try:
            _spec = importlib.util.spec_from_file_location("sendlog_lock", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sendlog_lock.py"))
            sendlog_lock = importlib.util.module_from_spec(_spec)
            sys.modules["sendlog_lock"] = sendlog_lock
            _spec.loader.exec_module(sendlog_lock)
        except (OSError, ImportError):
            sys.modules.pop("sendlog_lock", None)
            return open(path, encoding="utf-8", errors=errors)
    return sendlog_lock.open_lines(path, errors)


def sendlog_hits(needles: set):
    """Precise, JSON-aware search of the authoritative send log. Returns (strong, weak) line lists.

    ⛔ WHY THIS EXISTS. documents/send-log.jsonl is the store the rung ladder is computed from, and
    if it is not in STORES, the dedup gate cannot see what has actually been sent — only the prose
    logs, which can disagree: a build tool may still say STAGED (which search_file deliberately
    demotes to 🟡) after the send log already says "status": "sent". Net effect: a contact who
    received a message yesterday can come back as a 🟡 prose mention today.

    Parsed as JSON rather than swept with the fuzzy line matcher on purpose: the generic matcher
    cannot tell a delivered row from a bounced one, and those two need opposite verdicts.
    """
    full = os.path.join(_repo(), SENDLOG)
    strong, weak = [], []
    # ⛔ isfile, NOT exists, and this is a real defect rather than a style preference.
    # `os.path.exists` is TRUE for a DIRECTORY, so a send log that is anything other than a readable
    # file reaches `open()` and raises IsADirectoryError. check_dup then dies, and `mail-draft.sh`
    # reads ANY non-zero exit as "🔴 blocked-list or strong duplicate" — so an unreadable send log
    # silently becomes **"you already contacted this company" on EVERY send**, with a message
    # pointing at the wrong cause.
    #
    # ⚖️ FAILS OPEN, LOUDLY, and that is the deliberate half. The send log is ONE dedup signal among
    # several; the blocked list and the prose stores are read independently and still run. Failing
    # CLOSED here would keep the defect alive as an I/O problem masquerading as a duplicate verdict,
    # which is worse than a missing signal because it is a WRONG one. The warning goes to stderr so
    # you learn the log is unreadable rather than believing the company was contacted.
    if not os.path.isfile(full):
        if os.path.exists(full):
            print(f"⚠️  send log at {SENDLOG} is not a readable file (found a directory or special "
                  "file). Skipping the send-log signal; the blocked list and prose stores still ran.",
                  file=sys.stderr)
        return strong, weak
    try:
        f = _open_sendlog(full)
    except OSError as e:
        print(f"⚠️  send log at {SENDLOG} could not be read ({e.__class__.__name__}). Skipping the "
              "send-log signal; the blocked list and prose stores still ran.", file=sys.stderr)
        return strong, weak
    with f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            hay = " ".join(str(row.get(k, "")) for k in ("company", "to", "boss", "person", "subject"))
            low = " " + norm(hay) + " "
            low_lite = " " + norm_lite(hay) + " "
            if not any((" " + nd + " ") in low or (" " + nd + " ") in low_lite for nd in needles):
                continue
            status = str(row.get("status", "")).strip().lower()
            excerpt = (f"{row.get('date','?')} · {row.get('company','?')} · to {row.get('to','?')} "
                       f"· rung {row.get('rung','?')} · status {status or '?'}")
            (strong if status in SENDLOG_DELIVERED else weak).append((i, excerpt[:160]))
    return strong, weak


def _group_hits(flat):
    """Rebuild the {store: (status, [(line, text), ...])} shape `dump()` expects, from the flat
    hit list `prior_contact()` returns — first-seen order preserved, so printed output is
    unaffected by going through the flat representation."""
    grouped = {}
    for h in flat:
        store = h["store"]
        if store in grouped and grouped[store][0] != h["status"]:
            store = "%s (%s)" % (store, h["status"])   # one store, two kinds of hit (kit #229: a research row beside another weak hit)
        if store not in grouped:
            grouped[store] = (h["status"], [])
        grouped[store][1].append((h["line"], h["text"]))
    return grouped


# A WEAK hit is by definition NOT a recorded send: search_file() rates a STAGED draft, a warm-ask
# naming and a loose token as weak on purpose (see is_staged above). It must therefore never
# borrow its store's fixed label, which for outreach_log.md reads "SENT (or drop logged)". That
# label told a person they had already written to someone they never wrote to. The staged
# handling above decides strong versus weak and was right; this is the step AFTER it, where the
# finding was thrown away. Used by prior_contact() and by main()'s _scan(), the two places a weak
# hit is given a status. Next step, not done here: read the entry's own Status line and print
# that word.
WEAK_STORE_STATUS = ("named there, NOT a recorded send (a staged draft, or a loose match). "
                     "Open the line to see which")

# THE NEXT STEP the comment above flags: the entry's own status word (STAGED, SENT, RETIRED,
# MOVED ON, ...), read straight off the matched line rather than left for the reader to go open
# (kit #147). outreach_log.md writes its status in caps, either in the entry's own header ("...
# — STAGED (draft)") or its "**Status:**" line, and search_file() already captures whichever line
# matched (truncated to 160 chars) as the hit's `text` — so no extra file read is needed here.
# Scoped to outreach_log.md ONLY: it is the one SEND_GATE_STORES file whose fixed per-store label
# actually disagrees with individual entries (a SENT row and a STAGED row share one file). The
# other stores' fixed labels (blocked list, tracker, correspondence log, ...) do not carry this
# per-entry ambiguity, and running a bare ALL-CAPS scan over their prose would just as easily catch
# an unrelated acronym (LLC, SBIR, USA) and print it as if it were a status.
#
# ⛔ ANCHORED, NOT LEFTMOST (kit #147 follow-up, 29, 2026-09-22). A first pass here took the
# leftmost ALL-CAPS run anywhere in the line, which reads a company whose own name is a caps-heavy
# acronym ("... @ ABC Systems — STAGED (draft)") as status "ABC" — the company sits to the LEFT of
# the real status word in outreach_log.md's own header shape. The status word is never free-
# floating: it is always the text right after the header's trailing em-dash, or right after the
# entry's own "**Status:**" label. Anchoring to one of those two spots, and taking the LAST such
# match (the header's trailing "— STATUS" clause, not an earlier "— Name, Title @ Company" one
# that happens to open with a single capital), reads the same header correctly whatever the
# company's own capitalization looks like.
_STATUS_ANCHOR = re.compile(r"(?:—|\*\*Status:\*\*)\s*([A-Z]{3,}(?:\s[A-Z]{2,})?)\b")


def _status_word_from_text(txt: str):
    """The entry's own ALL-CAPS status word anchored after a trailing em-dash or a "**Status:**"
    label in `txt`, or None when there isn't one."""
    match = None
    for match in _STATUS_ANCHOR.finditer(txt or ""):
        pass
    return match.group(1).strip() if match else None


# ── THE TRACKER'S STATUS COLUMN (kit #229, plan-kit229-send-gate-tracker-status-2026-11-02.md) ───────────────────────────────────────────────────
# A tracker row blocks a first send only when its status says a contact happened. These five words, matched as the whole FIRST TOKEN of the
# lowercased status, mark a RESEARCH row (a note about a company, no one was contacted). Everything else, including an empty or unknown status, stays a
# contact and blocks: the list can only ever open the gate for these words, never for a misspelling. Adding a word means adding a red test.
TRACKER_PATH = "job_search_tracker.csv"
TRACKER_RESEARCH_STATUSES = (
    "build",      # a Build decision row: "build"
    "discover",   # a discovery row: "discover→<company>"
    "scorecard",  # a scorecard row: "scorecard(<card>)"
    "banked",     # the kit's screen-and-bank vocabulary: a company banked for later
    "research",   # the kit's screen-and-bank vocabulary: a research note
)
# NOT in the list on purpose: "radar" (RADAR is a sent outreach register here), "screen" and "screened" ("screening call", "screened by HR" are contacts).
# A research-status row stays a CONTACT when any column except date, company and the link and file columns carries one of these STEMS (case insensitive,
# at the start of a word): a hand-written send hides in the notes column in a hundred spellings, so the list is open on the blocking side and over-blocking
# fails closed. The link and file columns (source, cv_file, cover_letter_file) are skipped because a URL such as linkedin.com/jobs is not a contact.
# A non-empty `channel` is also a contact (it records HOW a contact went) unless it starts with n/a, none or "(screen only)".
TRACKER_CONTACT_STEMS = (
    ("e-?mail", r"\be-?mail"), ("sen[dt]", r"\bsen[dt]"), ("wrote/writ", r"\bwr(?:ote|it(?:e|es|ing|ten))\b"), ("ping", r"\bping"),
    ("dm", r"\bdm(?:'?d|ed|s)?(?!\w)"), ("messag", r"\bmessag"), ("inmail", r"\bin-?mail"), ("linkedin", r"\blinked-?in"),
    ("call", r"\bcall"), ("spoke/speak", r"\bsp(?:oke|eak|oken)"), ("met/meet", r"\bmet\b|\bmeet"), ("interview", r"\binterview"),
    ("follow", r"\bfollow"), ("outreach", r"\boutreach"), ("reach out", r"\breach(?:ed|es|ing)?\s+out"), ("contact", r"\bcontact"),
    ("repl", r"\brepl(?:y|ied|ies|ying)"), ("apply/applied", r"\bappl(?:y|ied|ies|ication)"), ("intro", r"\bintro"), ("connect", r"\bconnect"),
)
TRACKER_NO_CHANNEL = ("n/a", "none", "(screen only)")
_TRACKER_SKIP_COLUMNS = ("date", "company", "source", "cv_file", "cover_letter_file")
_STATUS_SPLIT = re.compile(r"[\s\u2192(:]+")


def _tracker_cells(header_line, line):
    """(lowercased header names, row cells) when the line is one well formed row of this tracker, else (None, None): no header, no `status`
    column, or a row whose width is not the header's width (a shifted column is never trusted). csv.reader, never split(",")."""
    try:
        header = [h.strip().lower() for h in next(csv.reader([header_line]))]
        row = next(csv.reader([line]))
    except (StopIteration, csv.Error):
        return None, None
    if "status" not in header or len(row) != len(header):
        return None, None
    return header, row


def tracker_row_status(header_line, line):
    """The row's status field, lowercased and stripped, found by header name. None when the row cannot be read (and None is a contact)."""
    header, row = _tracker_cells(header_line, line)
    return None if header is None else row[header.index("status")].strip().lower()


def tracker_row_kind(header_line, line):
    """("research", word) when the row's status is one of the research words and no column carries a contact stem or a channel, else ("contact", why).
    `why` names the column and the stem when a research-status row is kept as a contact."""
    header, row = _tracker_cells(header_line, line)
    if header is None:
        return "contact", ""
    status = row[header.index("status")].strip().lower()
    first = _STATUS_SPLIT.split(status, 1)[0] if status else ""
    if first not in TRACKER_RESEARCH_STATUSES:
        return "contact", ""
    for name, cell in zip(header, row):
        text = cell.strip().lower()
        if name == "channel" and text and not text.startswith(TRACKER_NO_CHANNEL):
            return "contact", "channel: %s" % text        # a channel records how a contact went
        if name in _TRACKER_SKIP_COLUMNS:
            continue
        if name == "status":
            text = status[len(first):]       # the rest of the status field: "build sent 10-02" is a contact
        for stem, pattern in TRACKER_CONTACT_STEMS:
            if re.search(pattern, text):
                return "contact", "%s: %s" % (name, stem)
    return "research", first


def _split_tracker_research(full_path, strong):
    """(strong hits that stay contacts, research hits as (line, text, word), a note naming why a research-status row stayed a contact or "")."""
    try:
        with open(full_path, encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()
    except OSError:
        return strong, [], ""
    kept, research, note = [], [], ""
    for ln, txt in strong:
        raw = lines[ln - 1] if 0 < ln <= len(lines) else ""
        kind, detail = tracker_row_kind(lines[0], raw) if lines else ("contact", "")
        if kind == "research":
            research.append((ln, txt, detail))
        else:
            kept.append((ln, txt))
            note = note or (("status is a research word, but %s" % detail) if detail else "")
    return kept, research, note


def prior_contact(company: str, person: str = "") -> dict:
    """Card-build-time dedup: has THIS company (and optionally person) already been contacted?

    This is exactly the SEND-GATE signal set (`--send-gate`'s scoped stores plus the authoritative
    send log) pulled out of `main()` so it can run BEFORE a card is built, not only at the final
    send gate. See documents/state/dedup-card-build-bug-draft-02-2026-09-09.md for why: a full
    build (beat 1/2, offer list, ask, close, subject, all scored and staged) got blocked at
    mail-draft.sh AFTER the expensive work was already done, with no earlier gate to catch it.

    Deliberately narrower than the plain (non-send-gate) verdict `main()` computes: it does not
    scan the construction/discovery stores (decision-log, queues, discovery-board, metrics) or the
    QUEUED_STORES banked board — those mean "being worked", not "already contacted", and are not
    this function's question.

    Returns {"strong": [...], "weak": [...], "verdict": "red"|"yellow"|"clean"}. Each hit is
    {"store": path, "status": status, "line": line_no, "text": excerpt}. "red" = a strong hit
    exists (an actual record/delivery, not incidental prose) — same-person delivered sends belong
    here. "yellow" = weak hits only (prose mention, or a send-log row that did not deliver —
    staged/bounced/failed). "clean" = neither.
    """
    needles = variants(company)
    loose = loose_tokens(company)
    if person:
        needles |= {norm(person)}
        toks = [t for t in norm(person).split() if len(t) >= 4]
        if toks:
            needles.add(toks[-1])  # last name

    stores = {p: s for p, s in STORES.items() if p in SEND_GATE_STORES}
    strong_found, weak_found = {}, {}
    research_hits = []
    for path, status in stores.items():
        res = search_file(path, needles, loose)
        if not res:
            continue
        strong, weak = res
        if path == TRACKER_PATH and strong:
            # kit #229: a tracker hit whose status is a research word is a note, not a contact
            strong, research, note = _split_tracker_research(os.path.join(_repo(), path), strong)
            research_hits += [{"store": path, "status": "research row (%s), not a contact" % w, "line": ln, "text": txt} for ln, txt, w in research]
            if note:
                status = "%s (%s)" % (status, note)
        if strong:
            strong_found[path] = (status, strong)
        elif weak:
            weak_found[path] = (WEAK_STORE_STATUS, weak)

    sl_strong, sl_weak = sendlog_hits(needles)
    if sl_strong:
        strong_found[SENDLOG] = ("DELIVERED per the send log (already contacted)", sl_strong)
    elif sl_weak:
        weak_found[SENDLOG] = ("in the send log, NOT delivered (staged/bounced/failed)", sl_weak)

    def _flatten(found):
        out = []
        for store, (status, hits) in found.items():
            for ln, txt in hits:
                st = status
                if store == "outreach_log.md" and status == WEAK_STORE_STATUS:
                    word = _status_word_from_text(txt)
                    if word:
                        st = (f"named there as {word} (a staged draft, or a loose match), "
                              "NOT a recorded send")
                out.append({"store": store, "status": st, "line": ln, "text": txt})
        return out

    strong_list = _flatten(strong_found)
    weak_list = _flatten(weak_found) + research_hits
    verdict = "red" if strong_list else ("yellow" if weak_list else "clean")
    return {"strong": strong_list, "weak": weak_list, "verdict": verdict}


def _domain_map_from_registry():
    """{blocked-employers-list.md line number: domain}, for employers.jsonl rows that carry one.

    A registry row's `source`/`status_source` already names the exact blocked-list line it came
    from ("seed:blocked-employers-list.md:N" or "blocked-employers-list.md:N") -- reused here
    rather than re-parsing the markdown a second time, so the domain a line is credited with is
    always the domain the seeder itself recorded for that row.
    """
    path = os.path.join(_repo(), "documents", "employers.jsonl")
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                dom = row.get("domain")
                if not dom:
                    continue
                for field in ("source", "status_source"):
                    src = row.get(field) or ""
                    m = re.search(r"blocked-employers-list\.md:(\d+)", src)
                    if m:
                        out[int(m.group(1))] = dom
    except FileNotFoundError:
        pass
    return out


BLOCKED_LIST_PATH = "documents/blocked-employers-list.md"


def apply_domain_collision(strong_found, candidate_domain, dom_map=None):
    """Downgrade a blocked-employers-list.md STRONG hit to a distinct "name collision, domains
    differ" signal, instead of a real re-contact block, when the candidate's own domain and the
    matched line's registry domain are BOTH present and differ.

    Returns (possibly-updated strong_found, collision hits or None). Additive, not replacing:
    - either side has no domain on file -> unchanged (rows that predate this field keep
      today's name-only behavior exactly).
    - domains match -> unchanged, the hit stands as a real strong match.
    - domains both present and differ -> that hit is pulled OUT of strong_found (so it can't
      trigger the hard block below) and returned separately so the caller can print a distinct
      "NAME COLLISION, verify entity" verdict instead.
    """
    if not candidate_domain:
        return strong_found, None
    if BLOCKED_LIST_PATH not in strong_found:
        return strong_found, None
    if dom_map is None:
        dom_map = _domain_map_from_registry()
    status, hits = strong_found[BLOCKED_LIST_PATH]
    remaining, collided = [], []
    for ln, txt in hits:
        row_domain = dom_map.get(ln)
        if row_domain and row_domain != candidate_domain:
            collided.append((ln, txt, row_domain))
        else:
            remaining.append((ln, txt))
    if not collided:
        return strong_found, None
    updated = dict(strong_found)
    if remaining:
        updated[BLOCKED_LIST_PATH] = (status, remaining)
    else:
        del updated[BLOCKED_LIST_PATH]
    return updated, collided


def main():
    args = [a for a in sys.argv[1:] if a != "--send-gate"]
    send_gate = "--send-gate" in sys.argv[1:]
    # Kit #156: a JOBSEARCH_DATA_ROOT that points anywhere but this install would make the send gate read another folder's stores and call a
    # contacted company NEW. It is for a test harness (JOBSEARCH_TEST=1), so outside a test the send gate refuses instead of guessing.
    _redirect = os.environ.get("JOBSEARCH_DATA_ROOT")
    if send_gate and _redirect and os.environ.get("JOBSEARCH_TEST") != "1" \
            and os.path.realpath(_redirect) != os.path.realpath(INSTALL_ROOT):
        print(f"check_dup: REFUSED. JOBSEARCH_DATA_ROOT is set to {_redirect}, but this send gate belongs to {INSTALL_ROOT} and would read "
              f"the wrong stores. Unset JOBSEARCH_DATA_ROOT and run it again.", file=sys.stderr)
        sys.exit(2)
    # optional candidate domain, for the domain-collision downgrade (apply_domain_collision).
    candidate_domain = None
    if "--domain" in args:
        _di = args.index("--domain")
        candidate_domain = args[_di + 1] if _di + 1 < len(args) else None
        args = args[:_di] + args[_di + 2:]
    if len(args) < 1:
        print("usage: check_dup.py [--send-gate] [--domain <domain>] \"<company>\" [\"<boss>\"]"); sys.exit(2)
    company = args[0]
    boss = args[1] if len(args) > 1 else ""
    needles = variants(company)
    loose = loose_tokens(company)      # extracted tokens may WARN, never BLOCK
    if boss:
        needles |= {norm(boss)}
        toks = [t for t in norm(boss).split() if len(t) >= 4]
        if toks: needles.add(toks[-1])  # last name

    stores = {p: s for p, s in STORES.items() if p in SEND_GATE_STORES} if send_gate else STORES
    print(f"check_dup: company={company!r} boss={boss!r}" + ("  [send-gate: blocked/contacted stores only]" if send_gate else ""))
    print(f"  normalized needles: {sorted(needles)}")

    def _scan(store_dict):
        found_strong, found_weak = {}, {}
        for pattern, status in store_dict.items():
            # a pattern with '*' expands to matching files (dir-based stores); else it's one file
            if "*" in pattern:
                # kit#174: skip non-text files here, in the dir-glob branch ONLY, so
                # search_file()'s strict decode (kit#159) never sees a PDF/.DS_Store/etc. A
                # single named-file store below is never globbed, so it is never binary-checked —
                # it is a durable text store by construction and keeps the strict fail-closed
                # decode unconditionally.
                paths = sorted(os.path.relpath(p, _repo())
                               for p in glob.glob(os.path.join(_repo(), pattern), recursive=True)
                               if os.path.isfile(p) and not _is_binary_store_file(p))
            else:
                paths = [pattern]
            for path in paths:
                res = search_file(path, needles, loose)
                if not res:
                    continue
                strong, weak = res
                if strong:
                    found_strong[path] = (status, strong)
                elif weak:
                    found_weak[path] = (WEAK_STORE_STATUS, weak)
        return found_strong, found_weak

    if send_gate:
        # ⛔ THE SEND-GATE PATH, factored out to `prior_contact()` so card-build-time callers
        # (boss_registry.py cmd_add, filter_blocked.py) can ask the same question BEFORE a card is
        # built, not only here at the final gate. Reused verbatim, not reimplemented, so the two
        # never drift: this rebuilds the exact same strong_found/weak_found this branch always
        # produced (SEND_GATE_STORES scan + sendlog_hits merge, no QUEUED_STORES), just from
        # prior_contact()'s flat return shape.
        #
        # kit#159, round 2 (3f's catch, score 72/FAIL): search_file()'s open() has no guard of its
        # own, so a SEND_GATE_STORES file that EXISTS but can't be read (permission denied, a
        # directory in its place) raised an uncaught PermissionError here, well before the
        # blocked_key_hit() try/except below ever ran. Uncaught, Python exits 1, and mail-draft.sh
        # reads exit 1 as "BLOCKED — blocked-list or strong duplicate": a true statement about the
        # exit code and a false one about the reason. A top-level catch here covers every reader
        # on this path (present or future) rather than threading a guard through each one by hand.
        try:
            pc = prior_contact(company, boss)
        except (OSError, UnicodeDecodeError) as e:
            # kit#159 (a): a bad encoding is caught here too now, not just permission/missing --
            # search_file() and blocked_keys_from_list() both decode strict and raise instead of
            # silently dropping undecodable bytes via the old errors="ignore".
            print(f"\n  ⛔ CANNOT VERIFY — a send-gate store could not be read ({e.__class__.__name__}: {e}).")
            print("      Refusing rather than proceeding on a partial store. Fix the file and re-run.")
            sys.exit(5)
        strong_found, weak_found = _group_hits(pc["strong"]), _group_hits(pc["weak"])
        queued_strong, queued_weak = {}, {}
    else:
        strong_found, weak_found = _scan(stores)
        # ⛔ QUEUED (banked) hits are scanned SEPARATELY and never feed strong_found/weak_found —
        # see QUEUED_STORES above. `--send-gate` never searched the banked store before this fix
        # either (it was never in SEND_GATE_STORES), so that scope is preserved exactly.
        queued_strong, queued_weak = _scan(QUEUED_STORES)
    queued_found = queued_strong or queued_weak

    # downgrade a blocked-employers-list.md STRONG hit to a distinct "name collision, domains
    # differ" signal, instead of a real re-contact block, when the candidate's own domain and
    # the matched line's registry domain are BOTH present and differ. No-op when --domain
    # wasn't given, or when either side has no domain on file -- see
    # apply_domain_collision's own docstring. Applies to both gate paths.
    strong_found, collision_hits = apply_domain_collision(strong_found, candidate_domain)

    # Q29b: the bare token against the blocked list (see blocked_token_hits). A whole-key hit joins
    # strong_found (so it prints and exits as a 🔴 ALREADY-SEEN, through the SAME BUG-244 domain
    # downgrade); a part-of-a-longer-name hit is held for the 🟡 NAME COLLISION verdict below.
    _tok = {"token": None, "whole": [], "part": []}
    if blocked_key_hit(company) is None:
        _tok = blocked_token_hits(company)
    whole_hits, part_hits = [], list(_tok["part"])
    if _tok["whole"]:
        _wf, _wcol = apply_domain_collision({BLOCKED_LIST_PATH: ("BLOCKED / declined", list(_tok["whole"]))}, candidate_domain)
        if BLOCKED_LIST_PATH in _wf:
            whole_hits = _wf[BLOCKED_LIST_PATH][1]
            if BLOCKED_LIST_PATH not in strong_found:
                strong_found = dict(strong_found)
                strong_found[BLOCKED_LIST_PATH] = ("BLOCKED / declined", whole_hits)
        if _wcol:
            collision_hits = (collision_hits or []) + _wcol

    if not send_gate:
        # The authoritative record of what actually went out (see sendlog_hits). Merged into the
        # same verdict buckets so it prints through the normal dump().
        sl_strong, sl_weak = sendlog_hits(needles)
        if sl_strong:
            strong_found[SENDLOG] = ("DELIVERED per the send log (already contacted)", sl_strong)
        elif sl_weak:
            weak_found[SENDLOG] = ("in the send log, NOT delivered (staged/bounced/failed)", sl_weak)

    def dump(found):
        for path, (status, hits) in found.items():
            print(f"   • {path}  [{status}]")
            for ln, txt in hits[:3]:
                print(f"       L{ln}: {txt}")
            if len(hits) > 3:
                print(f"       … +{len(hits)-3} more line(s)")

    # ⛔ PRECISE BLOCKED-LIST CHECK, independent of the fuzzy needles above. Runs BEFORE the
    # needle verdicts so a blocked company reports as blocked even when a space-stripped form
    # would defeat norm(). See blocked_key_hit() for the defect and why this is an equality
    # test rather than a looser substring match.
    try:
        bk = blocked_key_hit(company)
    except Exception as e:
        # kit#159: the blocked list EXISTS but could not be read (screen_sweep.BlockedListUnreadable,
        # or anything else unexpected) must refuse loudly, never proceed as if it read empty. This is
        # the opposite direction from sendlog_hits()'s own deliberate fail-open: the send log is one
        # signal among several, but the blocked list is the one gate nothing else backstops.
        print(f"\n  ⛔ CANNOT VERIFY — the blocked list could not be read ({e.__class__.__name__}: {e}).")
        print("      Refusing rather than proceeding on a partial store. Fix the file and re-run.")
        sys.exit(5)
    if bk == "__import_failed__":
        print("\n  ⚠️  blocked-list key check UNAVAILABLE (screen_sweep import failed).")
        print("      Treat a 🟢 below as UNVERIFIED against the blocked list and check it by hand.")
    elif bk:
        print(f"\n  VERDICT: 🔴 BLOCKED — '{company}' canon-matches a blocked-list entry (key: {bk}).")
        print("  Do NOT screen, surface, or pitch. Read the entry before doing anything else:")
        for ln, txt in _blocked_entry_lines(bk)[:3]:
            print(f"       documents/blocked-employers-list.md L{ln}: {txt}")
        sys.exit(1)

    # ⛔ A LOUDER VERDICT MUST NEVER HIDE A QUIETER ONE. This used to dump(strong_found) and exit,
    # so weak_found printed ONLY when there were no strong hits at all — which meant a real prior
    # record could sit in weak_found (e.g. a surname collision produced the strong hit, while the
    # actual match was a weaker one) and never print. The 🔴 read as if the gate had worked even
    # though it showed the wrong evidence. The verdict still exits 1 on strong hits; weak hits now
    # print underneath instead of being swallowed.
    #
    # ── PREFIX-COLLISION WARNING ───────────────────────────────────────────────────────────────
    # variants() emits the full normalized name PLUS its most distinctive token, so a two-word
    # company hands the search its own first word as a needle. That is right for finding a brand
    # name buried in prose, and wrong when the first word IS ITSELF A DIFFERENT REAL COMPANY (two
    # companies sharing a first word can produce a hard 🔴 on the wrong one's block).
    #
    # The gate is NOT weakened here on purpose. A send gate that leaks is worse than one that
    # over-warns, and this file already carries fixed FALSE-🔴 bugs whose lesson was the opposite
    # direction. So: keep the verdict, ADD the fact that the full name never appeared.
    _full = norm(company)
    if _full and strong_found:
        _hit_lines = [txt for _status, hits in strong_found.values() for _ln, txt in hits]
        _full_seen = any(_full in norm(ln) for ln in _hit_lines)
        if not _full_seen:
            _tokens = sorted(nd for nd in needles if nd != _full and nd and _full.startswith(nd))
            if _tokens:
                print(f"\n  ⚠️  PREFIX COLLISION LIKELY — the full name {company!r} appears in NONE of")
                print(f"      the matched lines. The match came from the shorter needle(s) {_tokens},")
                print(f"      which may be a DIFFERENT company that merely shares a first word.")
                print(f"      Read the lines below before treating this as a block on your target.")

    # ⛔ A QUEUED (banked) HIT ALWAYS PRINTS, same principle as the weak-under-strong dump above:
    # a louder verdict must never fully hide a quieter fact. This prints it unconditionally as
    # supplementary context, so it is visible whichever verdict actually decides the exit code.
    def dump_queued_if_any():
        if queued_found:
            print("\n  ALSO — 🟢 also queued for screening (this does not weaken the verdict")
            print("  above; it is context, not a second vote):")
            dump(queued_strong or queued_weak)

    if strong_found:
        print("\n  VERDICT: 🔴 ALREADY-SEEN — do NOT re-screen/re-pitch without checking these:")
        dump(strong_found)
        if weak_found:
            print("\n  ALSO — 🟡 weaker mentions, printed because a 🔴 must not mask them.")
            print("  A 🔴 can come from a name COLLISION, so read these before concluding the")
            print("  🔴 above is about your actual target:")
            dump(weak_found)
        if whole_hits:
            print(f"\n  ⚠️  The word '{_tok['token']}' EQUALS a blocked entry's whole name: this {BARE_NOTE}.")
            print("      To record an exception, declare the candidate itself on the blocked list with a 'not blocked' note.")
        dump_queued_if_any()
        sys.exit(1)
    if part_hits:
        # Q29b: the candidate shares one word with a LONGER blocked name. A collision to verify, not a
        # block on that word. A blocked-list hit HOLDS the send gate (Review 125 S1); only BUG-244's
        # domain-mismatch collision below stays non-blocking.
        print(f"\n  VERDICT: 🟡 NAME COLLISION, verify entity — shares the word '{_tok['token']}' with a blocked entry:")
        for ln, txt in part_hits[:3]:
            print(f"   • {BLOCKED_LIST_PATH}  L{ln}: {txt}")
        if len(part_hits) > 3:
            print(f"       … +{len(part_hits)-3} more line(s)")
        print("      It may be a different company that shares a word; verify the entity.")
        if weak_found:
            print("\n  ALSO — 🟡 weaker mentions:")
            dump(weak_found)
        dump_queued_if_any()
        if send_gate:
            print("\n  --send-gate: this collision BLOCKS the send until you verify the entity. If it is a different")
            print("  company, declare it on the blocked list with a 'not blocked' note, then run the gate again.")
            sys.exit(1)
        sys.exit(3)
    if weak_found:
        print("\n  VERDICT: 🟡 POSSIBLE — prose mention only (no core-store entry/company-column match).")
        print("  Either a common-word collision OR a PRIOR assessment/example in a narrative doc —")
        print("  VERIFY the prior record before proceeding (it may be a DROP or just an example):")
        dump(weak_found)
        dump_queued_if_any()
        sys.exit(3)
    if collision_hits:
        # the candidate's own --domain and a matched blocked row's registry domain are both on
        # file and differ -- this is a name collision, not a re-contact block.
        print("\n  VERDICT: 🟡 NAME COLLISION, verify entity — domains differ, not treated as a block:")
        for ln, txt, row_domain in collision_hits[:3]:
            print(f"   • {BLOCKED_LIST_PATH}  L{ln}: {txt}")
            print(f"       candidate domain: {candidate_domain!r}  vs.  blocked-row domain: {row_domain!r}")
        if len(collision_hits) > 3:
            print(f"       … +{len(collision_hits)-3} more line(s)")
        dump_queued_if_any()
        sys.exit(3)
    if queued_found:
        # ⛔ kit issue #8 / BUG-134. The banked files say it themselves: "A name in this file
        # means worth screening, never worth sending." Being queued for the screen this gate
        # exists to run is not evidence the screen already happened — it is the OPPOSITE fact.
        # Exits 0 (safe to proceed), same as a bare NEW, because that is exactly what this row
        # is: nothing has actually screened it yet.
        print("\n  VERDICT: 🟢 NEW-TO-SCREEN — queued but not yet screened. Safe to proceed:")
        dump(queued_strong or queued_weak)
        sys.exit(0)
    print("\n  VERDICT: 🟢 NEW — no prior record. Safe to proceed with screening.")
    sys.exit(0)

if __name__ == "__main__":
    main()
