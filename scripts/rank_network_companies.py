#!/usr/bin/env python3
"""rank_network_companies.py — LaCivita steps 9-10, mechanized.

WHY. Andy LaCivita's target-list method says to look the OTHER way too: review your
CONTACTS' companies and add them to your company target list — "pick the company first, then
who-you-know." `parse_network.py` already computes that table (every company sourced from your
own 1st-degree network, ranked by how many people you know inside each), yet a pipeline built
from COLD discovery leaves it entirely unused. A warm path in beats a cold one, and the list is
already sitting in your own export.

This is the triage layer between that raw table and your target board. It does NOT screen a
company (that is the full SCREEN GATE, run per candidate when it is picked up). It removes what
can be removed mechanically and ranks what is left, so you review a decision list instead of
hundreds of rows:

  • deal-breaker INDUSTRY veto      — reuses kit_config.INDUSTRY_VETO, the canonical vocabulary,
                                      plus the name-based veto set below (a defense prime or a
                                      crypto exchange rarely says so in its company name)
  • blocked-employers list          — never re-surface a company you have already ruled out
  • already contacted               — a warm intro there is a re-touch, not a fresh lead
  • your own past employers          — kit_config.EXCLUDED_EMPLOYERS: where your network lives,
                                      not where you are going (ships EMPTY — fill in your own)
  • staffing/consulting/recruiting  — the contact is there, the job is not
  • too-generic entries             — "Stealth Startup" is not a company you can target

Score = people you know, weighted toward PRODUCT people (they can hire or refer into product)
and senior people (they can create a seat), because that is what a warm path is actually worth.
The weights are kit_config.NETWORK_SCORE_WEIGHTS so you can retune them without editing code.

Every person-specific value (the industry vetoes, your ex-employers, the score weights) comes
from kit_config.py — fill that in first. Paths are relative to the repo root and resolve against
your own data files (the network table is produced by `scripts/parse_network.py`).

Usage:
    scripts/rank_network_companies.py                # top 25
    scripts/rank_network_companies.py --n 60
    scripts/rank_network_companies.py --all          # every survivor, for a full pass
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# Deal-breaker INDUSTRY vocabulary — the canonical keyword regexes, shared with the screen gate.
try:
    from kit_config import INDUSTRY_VETO
except Exception:  # standalone fallback — a small generic set so the tool still runs
    INDUSTRY_VETO = [r"\bdefense\b", r"\bdod\b", r"\bwarfighter", r"\bmilitary\b",
                     r"law[- ]enforcement", r"\bpolice\b", r"\bcrypto\b", r"\bweb3\b",
                     r"\bgambling\b", r"\bcasino\b", r"sportsbook"]

# YOUR own past employers: this is where your network came from, not where you are going. Ships
# EMPTY — an empty list makes this filter a no-op until you add your ex-employers to kit_config.
# (NEW kit_config symbol; falls back to [] so a company is never wrongly dropped as "yours".)
try:
    from kit_config import EXCLUDED_EMPLOYERS
except Exception:
    EXCLUDED_EMPLOYERS = []

# How a warm path is scored. A product contact can hire or refer INTO product; a senior contact
# can create a seat; a body you merely know is worth least. Parameterized so you can retune the
# emphasis without touching this file. (NEW kit_config symbol; generic default below.)
try:
    from kit_config import NETWORK_SCORE_WEIGHTS
except Exception:
    NETWORK_SCORE_WEIGHTS = {"product": 3, "senior": 2, "person": 1}

# Company names that ARE the excluded industry, where the name alone is decisive. The keyword
# vetoes in INDUSTRY_VETO look at the company name, but a business can be a hard skip without the
# string saying so — a defense prime, a crypto exchange or an ALPR vendor sold to police rarely
# names its industry. Each KEY is matched as a word-boundary substring of the company name.
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
    "axon": "law enforcement", "flock safety": "law enforcement",
    "motorola solutions": "law enforcement",
    "draftkings": "gambling", "fanduel": "gambling",
}

# The contact is real, the target is not: agencies place people elsewhere, and "Stealth Startup"
# is an anonymity label rather than a company you can research, screen, or ask for an intro into.
# ⚠️ EXAMPLE — the specific staffing/recruiting firm names below are public agency classifications;
# edit the set to the ones you actually run into. The generic tokens (stealth, self-employed,
# freelance, staffing, recruit) do the primary work.
NOT_A_TARGET = re.compile(
    r"stealth|^self[- ]employed|^freelance|^independent|^consultant|^retired|^student|"
    r"robert half|^teksystems|^insight global|^apex systems|^kforce|^randstad|^adecco|"
    r"^aerotek|^cybercoders|staffing|recruit|talent solutions|^upwork|^fiverr|"
    r"^various|^n/?a$|^none$|^unemployed|^vaco\b|^robert walters|^hays\b|"
    r"^korn ferry|^heidrick|^page group", re.I)

# YOUR own past employers, compiled from kit_config.EXCLUDED_EMPLOYERS and anchored at the start of
# the company name (so "Acme" matches "Acme Corp" but not "Beacon Acme"). Empty list → matches
# nothing, and the filter is skipped.
EXCLUDED_EMPLOYERS_RE = (
    re.compile(r"^(" + "|".join(re.escape(e) for e in EXCLUDED_EMPLOYERS) + r")", re.I)
    if EXCLUDED_EMPLOYERS else None)


def _read(path):
    f = os.path.join(REPO, path)
    return open(f, encoding="utf-8", errors="ignore").read() if os.path.exists(f) else ""


def _blocked():
    """Company names on the canonical never-recommend list, INCLUDING '/'-separated aliases.

    WHY: the name class must include '/', or an entry written
    `- Acme / Acme Web Services (AWS) (REMOTE FAIL …)` matches nothing at all and the company
    stays in the rankings after being blocked. Every entry that uses an alias is affected — which
    is exactly the shape a well-written blocked entry takes. A blocked-list parser that silently
    drops entries is the worst possible failure here: the list reads correct to a human and does
    nothing."""
    out = set()
    for line in _read("documents/blocked-employers-list.md").splitlines():
        if not line.strip().startswith(("-", "*")):
            continue
        head = re.sub(r"^\s*[-*]\s*", "", line)
        head = re.split(r"\s*\((?=[A-Z0-9]{2,}|[a-z]+\.[a-z]{2,}|POLITICAL|REMOTE|PE-|INHERITED)", head)[0]
        head = re.split(r"\s+[—-]\s+", head)[0]
        for alias in re.split(r"\s*/\s*", head):
            alias = alias.strip().strip("*").strip()
            alias = re.sub(r"\s*\([^)]*\)", "", alias).strip()
            norm = re.sub(r"[^a-z0-9]", "", alias.lower())
            if 2 <= len(norm) <= 40:
                out.add(norm)
    return out


def _contacted():
    """Companies already reached, from the outreach log's block headers.

    WHY: a header must be mined for EVERY '·'-delimited segment and every parenthetical, not just
    the first segment. Real headers vary in shape. A header like
    `## 2026-07-18 · Email · Jane Doe (CPO, Acme) — APPLY + boss-hunt pairing` will, if only the
    first segment is read, capture **"Email"** as the company — so Acme comes back 🟢 NEW days
    after you applied there and emailed their CPO. A dedup that silently misses is worse than none:
    it spends a warm contact re-opening a door already open. Harvest EVERY segment and every
    parenthetical, and over-collect on purpose — a false "already contacted" costs one manual
    check, a false "new" costs a duplicate approach."""
    out = set()
    for line in _read("outreach_log.md").splitlines():
        if not line.startswith("## "):
            continue
        body = re.split(r"\s+[—-]\s+", line[3:])[0]        # drop the trailing status clause
        chunks = [c.strip() for c in body.split("·")]
        for ch in re.findall(r"\(([^)]*)\)", body):        # "(CPO, Acme)" -> "CPO", "Acme"
            chunks += [c.strip() for c in ch.split(",")]
        for ch in chunks:
            ch = re.sub(r"\b(email|linkedin|apply|applied|inbound|outbound|staffing)\b", "", ch, flags=re.I)
            ch = re.sub(r"\(.*?\)|\d{4}-\d{2}-\d{2}|https?://\S+", "", ch).strip()
            norm = re.sub(r"[^a-z0-9]", "", ch.lower())
            if len(norm) >= 3:
                out.add(norm)
    return out


def rows():
    """Parse the '🔄 Companies sourced FROM your network' table out of warm-network.md."""
    txt = _read("documents/warm-network.md")
    if "Companies sourced FROM your network" not in txt:
        return []
    section = txt.split("Companies sourced FROM your network", 1)[1]
    out = []
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip().strip("*") for c in line.split("|")]
        # | n | Company | People | Product | Senior | names |
        if len(cells) < 7 or not cells[1].strip().isdigit():
            continue
        try:
            people, product, senior = int(cells[3]), int(cells[4]), int(cells[5])
        except ValueError:
            continue
        out.append({"company": cells[2], "people": people, "product": product,
                    "senior": senior, "names": cells[6]})
    return out


def rank(n=25):
    blocked, contacted = _blocked(), _contacted()
    kept, dropped = [], {"industry": 0, "blocked": 0, "contacted": 0, "past": 0, "not-a-target": 0}
    w = NETWORK_SCORE_WEIGHTS
    for r in rows():
        co = r["company"]
        low = co.lower()
        # Strip a trailing parenthetical before normalising, so "Acme Web Services (AWS)" compares
        # equal to the blocked-list alias "Acme Web Services". Without this the ticker/abbreviation
        # in the network export defeats an otherwise correct block.
        norm = re.sub(r"[^a-z0-9]", "", re.sub(r"\s*\([^)]*\)", "", low))
        if any(re.search(v, low) for v in INDUSTRY_VETO):
            dropped["industry"] += 1; continue
        if any(re.search(r"\b" + re.escape(k) + r"\b", low) for k in INDUSTRY_NAME_VETO):
            dropped["industry"] += 1; continue
        if EXCLUDED_EMPLOYERS_RE and EXCLUDED_EMPLOYERS_RE.search(co):
            dropped["past"] += 1; continue
        if NOT_A_TARGET.search(co):
            dropped["not-a-target"] += 1; continue
        if norm in blocked:
            dropped["blocked"] += 1; continue
        if norm in contacted:
            dropped["contacted"] += 1; continue
        # A product contact can hire or refer INTO product; a senior contact can create a seat.
        # A body you merely know is worth least. Weights reflect what the warm path can DO.
        r["score"] = (r["product"] * w.get("product", 3)
                      + r["senior"] * w.get("senior", 2)
                      + r["people"] * w.get("person", 1))
        kept.append(r)
    kept.sort(key=lambda c: (-c["score"], c["company"].lower()))
    return kept[:n] if n else kept, dropped, len(rows())


def main():
    n = 25
    if "--all" in sys.argv:
        n = 0
    elif "--n" in sys.argv:
        i = sys.argv.index("--n")
        if i + 1 < len(sys.argv):
            try:
                n = int(sys.argv[i + 1])
            except ValueError:
                pass
    kept, dropped, total = rank(n)
    print("=" * 78)
    print("  COMPANIES SOURCED FROM YOUR NETWORK — LaCivita steps 9-10")
    print('  "Pick the company first, then who-you-know." A warm path in beats a cold one.')
    print("=" * 78)
    if not total:
        print("\n  ⚠️  no network-company table found — run scripts/parse_network.py --limit 999 first\n")
        sys.exit(0)
    print(f"  {total} companies in your network · dropped: " +
          ", ".join(f"{k}={v}" for k, v in dropped.items() if v))
    print(f"  showing {len(kept)}\n")
    for i, c in enumerate(kept, 1):
        who = c["names"][:52]
        print(f"  {i:3}. {c['company'][:34]:<34} score {c['score']:>3}  "
              f"({c['people']} known · {c['product']} product · {c['senior']} senior)")
        if who:
            print(f"       {who}")
    print("\n  These have had NO screen beyond deal-breaker industry, blocked-list and dedup.")
    print("  Per the tiered screen a warm rung needs deal-breakers only — screen each one WHEN")
    print("  you pick it up, not before. Live-role verify + culture come at the BUILD gate.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
