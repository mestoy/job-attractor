#!/usr/bin/env python3
"""screen_sweep.py — batch-screen a segment sweep down to real candidates.

Applies the MECHANICAL gates only, in the order that kills fastest and cheapest:

  1. dedup    — any prior record in the repo (sent / queued / archived / tracker) → drop
  2. blocked  — documents/blocked-employers-list.md → drop, with the recorded reason shown
  3. industry — the hard exclusions from kit_config.INDUSTRY_VETO (keyword regexes matched on
                company name + title), plus the name-based veto dict below → drop
  4. title    — formal people-management titles and non-PM roles → drop the ROLE, but keep the
                company as a BOSS-HUNT lead (an org hiring product with no IC seat is still a lead)
  5. comp     — a stated maximum below kit_config.COMP_FLOOR → drop; comp not stated → keep, flagged

What it deliberately does NOT do: remote verification beyond the aggregator's own field, PE
ownership, culture, boss identification. Those are judgement gates and stay human/agent work — a
filter cannot see whether a company's customers are police departments or whether leadership just
churned. A 🟢 here means "worth screening," never "worth sending."

Every person-specific value (the comp floor, the industry vetoes) comes from kit_config.py — fill
that in first. Paths are relative to the repo root and resolve against your own data files.

Usage: scripts/screen_sweep.py documents/sweep-YYYY-MM-DD.jsonl [--show-dropped] [--bank]
"""
import json, os, re, sys, collections

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from kit_config import COMP_FLOOR, INDUSTRY_VETO
except Exception:  # standalone fallback — 0 disables comp filtering, [] disables the keyword veto
    COMP_FLOOR, INDUSTRY_VETO = 0, []

# Company names that ARE the excluded industry (name alone is decisive). The keyword vetoes in
# kit_config.INDUSTRY_VETO look at the company NAME and the job TITLE, and a business can be a hard
# skip without either string saying so — a defense prime, a crypto exchange or an ALPR vendor sold
# to police rarely says "defense"/"crypto"/"police" in a job title. Add the company names you keep
# re-encountering; the classification, not the company, is what matters.
#
# ⚠️ EXAMPLE set — edit to YOUR deal-breakers, and keep it consistent with kit_config.INDUSTRY_VETO
# (if you do not veto gambling, drop the gambling names here). An empty dict is fine; the keyword
# screen above is the primary gate. These are public classifications, not editorial judgements.
INDUSTRY_NAME_VETO = {
    "coinbase": "crypto", "kraken": "crypto", "gemini": "crypto", "circle": "crypto",
    "consensys": "crypto",
    "lockheed martin": "defense", "raytheon": "defense", "northrop grumman": "defense",
    "general dynamics": "defense", "l3harris": "defense", "anduril": "defense",
    "palantir": "defense", "booz allen hamilton": "defense", "leidos": "defense",
    "saic": "defense", "caci": "defense", "peraton": "defense",
    "axon": "law enforcement", "flock safety": "law enforcement",
    "motorola solutions": "law enforcement",
    "draftkings": "gambling", "fanduel": "gambling",
}
# Formal people-management → the ROLE is a mismatch (IC track preferred), company still a lead.
MGMT_TITLE = r"\b(group product manager|director of product management|head of product management|" \
             r"vp,? product|vice president,? product|senior director|sr\.? director|manager,? product manag)"
# Not a product-management seat at all (the aggregator's matcher over-catches).
NON_PM = r"\b(engineer|scientist|analyst|architect|intern|marketing|sales|account executive|" \
         r"recruiter|designer|consultant|specialist|coordinator|operations manager)\b"


def load_prior():
    """Every company name with any prior record in the repo."""
    names = set()
    p = os.path.join(REPO, "documents/send-log.jsonl")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            try:
                c = json.loads(line).get("company", "")
            except Exception:
                continue
            if c:
                names.add(c.strip().lower())
    blobs = {}
    for f in ("documents/outreach-queue.md", "documents/outreach-queue-archive.md",
              "outreach_log.md", "prospect_queue.md", "job_search_tracker.csv",
              "documents/green-board.md"):
        fp = os.path.join(REPO, f)
        if os.path.exists(fp):
            blobs[f] = open(fp, encoding="utf-8", errors="ignore").read().lower()
    return names, blobs


def blocked_reason(company, blocked_txt):
    """Return the recorded block reason, or None. Anchored to a list-item start so a company
    whose name is a substring of prose does not read as blocked."""
    lc = re.escape(company.lower().strip())
    m = re.search(r"(?m)^[-*]\s*" + lc + r"\b[^\n]*", blocked_txt)
    return m.group(0)[:150] if m else None


def max_salary(s):
    if not s:
        return None
    nums = [int(n.replace(",", "").split(".")[0]) for n in re.findall(r"[\d,]+(?:\.\d+)?", s)]
    nums = [n for n in nums if n > 1000]
    return max(nums) if nums else None


def canon(name):
    """Normalize a company name so legal suffixes and variants collapse to one key.

    WHY: without this, "Acme, Inc." banks as a different company than "Acme" on the blocked
    list, and "Acme (Parent Co)", "Parent Co" and "Parent Co - Acme Division" bank as THREE
    rows — silently taking three of the ranker's top slots and shrinking the real set of
    distinct companies the user is asked to pick from. An exact-string blocked check is a
    blocked check a company escapes by adding ", Inc."

    ⬆️ HOISTED TO MODULE LEVEL so `reconcile_findings.py` can IMPORT it instead of forking it.
    It was a closure inside `bank()`, which meant the only way to reuse this normalization was
    to copy it, and a copied matcher drifts from its original the first time either side is
    fixed. One canonical core, several consumers; never fork the core.
    """
    n = name.lower()
    n = re.sub(r"\(.*?\)", " ", n)                       # drop parentheticals
    n = re.split(r"\s+(?:-|–|d/b/a|dba)\s+", n)[0]        # keep the head of "X - Y" / "X d/b/a Y"
    n = re.sub(r"\b(inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|plc|sa|nv|ag|"
               r"holdings|group|private|pvt|software and solutions india)\b", " ", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def blocked_keys_from_list(path=None):
    """Every blocked company as a canon() key, parsed from documents/blocked-employers-list.md.

    The blocked list uses BOTH shapes, and only reading one of them is how a block silently lapses:
      - ACME CORP (**CULTURE / LEADERSHIP + LAYOFFS**, blocked ...)   ← name is PLAIN
      - **Beta Systems** (beta.example, WebOps) — 🔴 2.9/5 ...         ← name is BOLD
    A first cut here read only `**bold**` spans and therefore harvested the REASON text out of the
    first shape, letting the plainly-named companies straight back into the pool. Parse the leading name of each
    bullet, and keep the bold span too for entries written the other way.

    ⬆️ HOISTED alongside canon(), same reason. Returns an empty set when the list is
    missing, so a fresh install banks rather than crashing.
    """
    path = path or os.path.join(REPO, "documents/blocked-employers-list.md")
    try:
        blocked_raw = open(path, encoding="utf-8", errors="ignore").read().lower()
    except Exception:
        return set()
    # ⬆️ WIDENED. The original read only a bullet's leading name plus its **bold** spans,
    # and the file writes blocked names in three more shapes that were all silently missed:
    #   - COMMA LIST as the head:      "- MeridianLink, Alkami, Zapier"
    #   - MIDDOT LIST, colon or not:   "- **Filter 2, defense:** Scale AI · C3.ai"
    #                                  "- Notable Health (13 of 16 SF) · OpenEvidence (8 SF)"
    #   - MARKDOWN TABLE ROW:          "| Rad AI | All 3 product seats SF-only | 1 |"
    # Splitting on · FIRST and then taking each segment's head is what generalizes across all of
    # them. Every candidate is still length-capped and reason-word filtered, because the cost of
    # over-harvesting is a company silently vanishing from the pool, which is the exact defect this
    # parser is being widened to fix (see rank_criteria._BlockedText).
    REASON = re.compile(r"\b(blocked|declined|owned|culture|layoff|always-on|grindset|pe-owned|"
                        r"leadership|reversal|turmoil|acquisition|not blocked|corrected|filter|"
                        r"remote|travel|company|reason)\b")

    def _add(cand, keys):
        cand = cand.strip(" *_`~")
        if not cand or REASON.search(cand):
            return
        if len(cand) > 44 or len(cand.split()) > 5:   # a name is short; a fragment is not
            return
        for part in cand.split("/") if "/" not in canon(cand) else [cand]:
            k = canon(part)
            if 3 < len(k) <= 40:
                keys.add(k)

    # ⛔ A LINE THAT SAYS A COMPANY IS *NOT* BLOCKED MUST NOT BLOCK IT. The file carries explicit
    # exoneration notes ("X, NOT blocked, an earlier call is CORRECTED"; a "⏭️ NOT blocked, recorded
    # so the next sweep does not re-walk them" section), and harvesting their bold names blocked the
    # very companies they clear. This is the
    # house's recurring defect: check_followups once armed a follow-up by reading the annotation that
    # DECLINED one, and check_screen_gate once passed a politics layer on the warning that politics
    # evidence was MISSING. Documenting an exception must never create the thing it excepts.
    EXONERATED = re.compile(r"not blocked|not killed|not a gate fail|⏭️|deferred|corrected")

    keys = set()
    for line in blocked_raw.splitlines():
        s = line.strip()
        if EXONERATED.search(s):
            continue
        if s.startswith("|"):
            # table row: the first cell is the company, by this file's own convention
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and not set(cells[0]) <= set("-: "):
                _add(cells[0], keys)
            continue
        if not s.startswith(("-", "*")):
            continue
        for seg in re.split(r"\s*·\s*", s.lstrip("-* ").strip()):
            head = re.split(r"\s*[(—–:]|\s+\*\*", seg, 1)[0]
            cands = [head] + re.findall(r"\*\*(.+?)\*\*", seg)
            if ":" in seg:                       # "…defense:** Scale AI" → keep the tail too
                cands.append(seg.split(":", 1)[1])
            cands += [p for c in list(cands) for p in re.split(r"\s*,\s*", c) if p.strip()]
            for cand in cands:
                _add(cand, keys)
    return keys


def bank(keep, boss_hunt, greenfield, src):
    """Write the survivors to documents/banked-candidates-<date>.md so the RANKER can read them.

    WHY. A screener that prints its survivors to stdout and stops has produced no artifact anything
    downstream reads — the ranker keeps re-ranking a stale pool while a fresh batch sits in a
    terminal buffer. `rank_criteria.banked_topup()` reads `documents/banked-candidates-*.md`, so the
    survivors must be written there or the whole screen is wasted. Screening without banking is not
    screening, it is printing. This matters because a low-quality outreach ask can burn a real
    relationship, so the ranker must see the best-screened pool, not last run's leftovers.

    Format is deliberately the dot-separated batch list `banked_topup` already parses; do not
    "improve" it into a table without changing that reader, which skips lines starting with `|`.
    """
    from datetime import date
    out = os.path.join(REPO, f"documents/banked-candidates-{date.today().isoformat()}.md")
    blocked_keys = blocked_keys_from_list()

    names, seen, dropped_blocked = [], set(), []
    for r in keep + boss_hunt + greenfield:
        co = (r.get("company") or "").strip()
        if not co:
            continue
        k = canon(co)
        if not k or k in seen:
            continue
        if k in blocked_keys:
            dropped_blocked.append(co)
            seen.add(k)
            continue
        seen.add(k)
        names.append(co)
    if dropped_blocked:
        print(f"\n   ⛔ {len(dropped_blocked)} name-variant(s) of BLOCKED companies caught by "
              f"normalization: {', '.join(dropped_blocked[:6])}")
    lines = [f"# Banked candidates — {date.today().isoformat()}", "",
             f"> Written by `screen_sweep.py --bank` from `{os.path.basename(src)}`.",
             "> Passed the MECHANICAL gates only (dedup, blocked-list, industry, title, comp floor).",
             "> **STILL OWED on every name here: remote verification, PE ownership, culture, boss.**",
             "> A name in this file means *worth screening*, never *worth sending*.", "",
             "## Passes", ""]
    for i in range(0, len(names), 6):
        lines.append(" · ".join(names[i:i + 6]) + " ·")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"\n🏦 banked {len(names)} companies → {os.path.relpath(out, REPO)}")
    print("   the ranker reads documents/banked-candidates-*.md; re-run rank_criteria.py to see them")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    path = sys.argv[1]
    show_dropped = "--show-dropped" in sys.argv
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

    prior_names, blobs = load_prior()
    blocked_path = os.path.join(REPO, "documents/blocked-employers-list.md")
    blocked_txt = (open(blocked_path, encoding="utf-8", errors="ignore").read().lower()
                   if os.path.exists(blocked_path) else "")

    by_company = collections.OrderedDict()
    for r in rows:
        c = (r.get("company") or "").strip()
        if c:
            by_company.setdefault(c, []).append(r)

    keep, boss_hunt, greenfield, dropped = [], [], [], []
    for company, posts in by_company.items():
        lc = company.lower()
        if lc in prior_names:
            dropped.append((company, "prior record: already contacted")); continue
        hit = next((f for f, txt in blobs.items() if lc in txt), None)
        if hit:
            dropped.append((company, f"prior record in {hit}")); continue
        br = blocked_reason(company, blocked_txt)
        if br:
            dropped.append((company, f"BLOCKED — {br}")); continue
        if lc in INDUSTRY_NAME_VETO:
            dropped.append((company, f"industry: {INDUSTRY_NAME_VETO[lc]}")); continue
        blob = (company + " " + " ".join(p.get("title", "") for p in posts)).lower()
        veto = None
        for pat in INDUSTRY_VETO:
            m = re.search(pat, blob)
            if m:
                veto = m.group(0); break
        if veto:
            dropped.append((company, f"industry: veto term \"{veto}\"")); continue

        ic, mgmt = [], []
        for p in posts:
            t = (p.get("title") or "")
            if re.search(NON_PM, t, re.I) and not re.search(r"product manager|product lead", t, re.I):
                continue
            (mgmt if re.search(MGMT_TITLE, t, re.I) else ic).append(p)
        if not ic and not mgmt:
            # NO product role posted is NOT a drop. A company hiring but with no product function is
            # a 0-to-1 "your first product hire" GREENFIELD target for a builder-PM who creates the
            # function. It already cleared the hard gates above (dedup/blocked/industry); the comp
            # floor can't apply (there is no product req to price), so keep it as a greenfield
            # boss-hunt lead — it owes founder/leader research + remote-verify like any radar target.
            gf = posts[0]
            greenfield.append({"company": company, "segment": gf.get("segment"),
                               "title": "(no product role posted — 🌾 greenfield / build the function)",
                               "salary": "n/a", "location": gf.get("location"),
                               "url": gf.get("applyUrl") or gf.get("url"), "n": len(posts)})
            continue

        pool = ic or mgmt
        best = max(pool, key=lambda p: (max_salary(p.get("salary")) or 0))
        top = max_salary(best.get("salary"))
        if COMP_FLOOR and top is not None and top < COMP_FLOOR:
            dropped.append((company, f"comp max ${top:,} < ${COMP_FLOOR:,} floor")); continue
        rec = {"company": company, "segment": posts[0].get("segment"), "title": best.get("title"),
               "salary": best.get("salary") or "not stated", "location": best.get("location"),
               "url": best.get("applyUrl") or best.get("url"), "n": len(posts)}
        (keep if ic else boss_hunt).append(rec)

    def show(rs, head):
        if not rs:
            return
        print(f"\n{head} ({len(rs)})")
        for r in sorted(rs, key=lambda r: (r["segment"] or "", r["company"])):
            seg = {"payments": "💰", "applied-ai": "🤖", "ai-enablement": "🧭", "regulated-workflow": "🏥", "govtech": "🏛️"}.get(r["segment"], "·")
            print(f"  {seg} {r['company'][:30]:32} {r['salary'][:22]:24} {r['title'][:42]:44} {(r['location'] or '')[:26]}")
            print(f"      {r['url']}")

    print(f"swept {len(rows)} postings · {len(by_company)} companies")
    show(keep, "🟢 CANDIDATES — IC product seat, mechanical gates passed (still owe: remote-verify, PE, culture, boss)")
    show(boss_hunt, "🟠 BOSS-HUNT LEADS — only people-management seats open, so the ROLE is a mismatch but the org is hiring product")
    show(greenfield, "🌾 GREENFIELD — hiring but NO product role posted; a 0-to-1 'your first product hire' target (no product org is NOT a drop)")
    if "--bank" in sys.argv:
        bank(keep, boss_hunt, greenfield, path)
    print(f"\n🔴 dropped {len(dropped)}")
    if show_dropped:
        for c, why in dropped:
            print(f"   {c[:34]:36} {why}")
    else:
        agg = collections.Counter(w.split(":")[0].split("—")[0].strip() for _, w in dropped)
        for w, n in agg.most_common():
            print(f"   {n:4}  {w}")


if __name__ == "__main__":
    main()
