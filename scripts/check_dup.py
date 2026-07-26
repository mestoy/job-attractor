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
import sys, os, re, csv, glob

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    # DEDUP HOLES CLOSED. Two stores that discovery WRITES were never stores that dedup READS,
    # so a company screened yesterday came back NEW today and agents re-walked it from scratch.
    # Same blind-spot class as a banked-but-unsent row. Both are soft-tier, never send-gate: a
    # banked company is re-screenable, it is not re-DISCOVERABLE.
    "documents/banked-candidates-*.md":    "BANKED by a prior sweep (hard gates passed, culture still owed)",
    "documents/findings/*.jsonl":          "SCREENED in a prior agent discovery run",
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
    # add the single most distinctive token (>=4 chars) to catch "TigerData" inside prose
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
    _fellback = not norm(name)
    toks = [t for t in n.split() if len(t) >= 4]
    if toks and not _fellback:
        cand = toks[0]
        if norm(cand):          # a token norm() keeps is truly distinctive
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
        "Ramp"        matched  "the on-ramp that reaches..."
        "Vector"      matched  "open-source vector-DB / RAG"
    Each produced a hard 🔴 ALREADY-SEEN, which silently kills a real candidate before it is ever
    screened. Company names are proper nouns; their genuine records are capitalized. So require
    at least one capitalized occurrence before calling a hit STRONG.

    DIGIT-LEADING NAMES: an earlier version tested `match[0].isupper()`, and `"1".isupper()` is
    False, so a name like `1Password` could NEVER be strong, degraded 🔴 to 🟡, and mail-draft.sh
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
    'Notion' or 'Ramp' colliding with ordinary uses of those words in your notes)."""
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
        return nd in norm(ls[:120]) or nd in norm_lite(ls[:120])
    return nd in norm(line[:60]) or nd in norm_lite(line[:60])

def search_file(path: str, needles: set):
    full = os.path.join(REPO, path)
    if not os.path.exists(full):
        return []
    strong, weak = [], []
    with open(full, encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f, 1):
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
            low = " " + norm(line) + " "
            low_lite = " " + norm_lite(line) + " "
            for nd in needles:
                # WORD-BOUNDARY match only (padded low handles start/end) — no loose substring,
                # which would match a short name inside a common word (e.g. "ably" in "reliably").
                if (" " + nd + " ") in low or (" " + nd + " ") in low_lite:
                    is_strong = (not is_staged) and _strong(path, line, nd)
                    (strong if is_strong else weak).append((i, line.strip()[:160]))
                    break
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

def main():
    args = [a for a in sys.argv[1:] if a != "--send-gate"]
    send_gate = "--send-gate" in sys.argv[1:]
    if len(args) < 1:
        print("usage: check_dup.py [--send-gate] \"<company>\" [\"<boss>\"]"); sys.exit(2)
    company = args[0]
    boss = args[1] if len(args) > 1 else ""
    needles = variants(company)
    if boss:
        needles |= {norm(boss)}
        toks = [t for t in norm(boss).split() if len(t) >= 4]
        if toks: needles.add(toks[-1])  # last name

    stores = {p: s for p, s in STORES.items() if p in SEND_GATE_STORES} if send_gate else STORES
    print(f"check_dup: company={company!r} boss={boss!r}" + ("  [send-gate: blocked/contacted stores only]" if send_gate else ""))
    print(f"  normalized needles: {sorted(needles)}")
    strong_found, weak_found = {}, {}
    for pattern, status in stores.items():
        # a pattern with '*' expands to matching files (dir-based stores); else it's one file
        if "*" in pattern:
            paths = sorted(os.path.relpath(p, REPO)
                           for p in glob.glob(os.path.join(REPO, pattern), recursive=True)
                           if os.path.isfile(p))
        else:
            paths = [pattern]
        for path in paths:
            res = search_file(path, needles)
            if not res:
                continue
            strong, weak = res
            if strong:
                strong_found[path] = (status, strong)
            elif weak:
                weak_found[path] = (status, weak)

    def dump(found):
        for path, (status, hits) in found.items():
            print(f"   • {path}  [{status}]")
            for ln, txt in hits[:3]:
                print(f"       L{ln}: {txt}")
            if len(hits) > 3:
                print(f"       … +{len(hits)-3} more line(s)")

    if strong_found:
        print("\n  VERDICT: 🔴 ALREADY-SEEN — do NOT re-screen/re-pitch without checking these:")
        dump(strong_found)
        sys.exit(1)
    if weak_found:
        print("\n  VERDICT: 🟡 POSSIBLE — prose mention only (no core-store entry/company-column match).")
        print("  Either a common-word collision OR a PRIOR assessment/example in a narrative doc —")
        print("  VERIFY the prior record before proceeding (it may be a DROP or just an example):")
        dump(weak_found)
        sys.exit(3)
    print("\n  VERDICT: 🟢 NEW — no prior record. Safe to proceed with screening.")
    sys.exit(0)

if __name__ == "__main__":
    main()
