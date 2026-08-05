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
import sys, os, re, csv, glob, json

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
    # THIRD GUARD: the two guards above are necessary and still not sufficient. A short generic
    # word can also be merely-not-a-legal-suffix and merely 4+ chars long, so it slips past both:
    #     "Blue River Co"   -> "blue"      matched an unrelated "Blue ___" company
    #     "WAI Global"      -> "global"    matched every "___ Global" company
    #     "Nym Health"      -> "health"    matched every health company on the boards
    #     "GM Financial"    -> "financial" matched an unrelated "___ Financial" company
    # `norm(cand)` passes all of these, because they are ordinary industry nouns, not legal
    # suffixes. A false 🔴 is the dangerous direction — it reads exactly like a completed screen
    # and silently kills a real candidate before anyone looks at it.
    #
    # The needle's ONLY job is to catch a concatenated brand name buried in prose ("TigerData").
    # That needs a genuinely distinctive token: take the FIRST token (an English company name puts
    # the brand first — "Acme Labs", "Ocrolus Inc"), require >= 6 chars, and reject ordinary
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
            is_warm_ask_naming = (
                "targets named" in _low_line
                or (line.lstrip().startswith(">")
                    and ("picked three" in _low_line
                         or "relationship at one of them" in _low_line))
            )
            low = " " + norm(line) + " "
            low_lite = " " + norm_lite(line) + " "
            for nd in needles:
                # WORD-BOUNDARY match only (padded low handles start/end) — no loose substring,
                # which would match a short name inside a common word (e.g. "ably" in "reliably").
                if (" " + nd + " ") in low or (" " + nd + " ") in low_lite:
                    is_strong = (not is_staged) and (not is_warm_ask_naming) and _strong(path, line, nd)
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
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from screen_sweep import canon, blocked_keys_from_list
    except Exception:
        # FAIL CLOSED-ISH: a broken import must not silently downgrade the blocked check to
        # "no hit". Returning the sentinel makes the failure visible in the verdict instead.
        return "__import_failed__"
    k = canon(company)
    return k if k and k in blocked_keys_from_list() else None


def _blocked_entry_lines(key):
    """The blocked-list line(s) whose leading name canon()s to `key`, for the verdict printout.

    Best-effort only: the verdict above does not depend on finding the line, so a miss here just
    means you read the file yourself rather than getting a quoted excerpt.
    """
    try:
        from screen_sweep import canon
        path = os.path.join(REPO, "documents/blocked-employers-list.md")
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


SENDLOG = "documents/send-log.jsonl"
# Statuses that mean the message REACHED the person. Everything else in the send log (staged,
# drafted, bounced, blocked, failed) means it did not, and must stay 🟡 — a bounce in particular
# is the case where a RETRY is correct, so promoting it to 🔴 would block the very send it should
# enable.
SENDLOG_DELIVERED = {"sent", "delivered", "replied", "submitted"}


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
    full = os.path.join(REPO, SENDLOG)
    strong, weak = [], []
    if not os.path.exists(full):
        return strong, weak
    with open(full, encoding="utf-8", errors="ignore") as f:
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

    # The authoritative record of what actually went out (see sendlog_hits). Merged into the
    # same verdict buckets so it prints through the normal dump(), and included under
    # --send-gate because "already delivered to this person" is precisely a do-not-send fact.
    sl_strong, sl_weak = sendlog_hits(needles)
    if sl_strong:
        strong_found[SENDLOG] = ("DELIVERED per the send log (already contacted)", sl_strong)
    elif sl_weak:
        weak_found[SENDLOG] = ("in the send log, NOT delivered (staged/bounced/failed)", sl_weak)

    # ⛔ PRECISE BLOCKED-LIST CHECK, independent of the fuzzy needles above. Runs BEFORE the
    # needle verdicts so a blocked company reports as blocked even when a space-stripped form
    # would defeat norm(). See blocked_key_hit() for the defect and why this is an equality
    # test rather than a looser substring match.
    bk = blocked_key_hit(company)
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

    if strong_found:
        print("\n  VERDICT: 🔴 ALREADY-SEEN — do NOT re-screen/re-pitch without checking these:")
        dump(strong_found)
        if weak_found:
            print("\n  ALSO — 🟡 weaker mentions, printed because a 🔴 must not mask them.")
            print("  A 🔴 can come from a name COLLISION, so read these before concluding the")
            print("  🔴 above is about your actual target:")
            dump(weak_found)
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
