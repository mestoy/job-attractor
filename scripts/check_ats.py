#!/usr/bin/env python3
"""check_ats.py — is there a LIVE PM role? (Greenhouse / Ashby / Lever, authoritative)

Gap-close step for "verify a live role via the ATS API, not a stale aggregator"
(WORKFLOW-RULES §4). Probes all three major ATS boards for a company, reports live
Product-Manager roles with location / remote / comp, so a RADAR vs live-application
call is made from the source of truth.

Usage:
    scripts/check_ats.py "<company>"          # derive candidate tokens
    scripts/check_ats.py --token <exacttoken> # force a known board token

Notes: Greenhouse tokens are case-sensitive (tries given + Capitalized). Ashby comp is
structured; Greenhouse comp is regex-scraped from the JD when present. stdlib only.
"""
import sys, os, json, re, html, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from untrusted import ATS_HOSTS, allowed_url, defang   # noqa: E402

def get_json(url, timeout=12):
    # EGRESS ALLOWLIST. This fetcher's destinations are known in advance (the three ATS APIs), so
    # anything else is refused rather than fetched and then judged. The tokens fed to it are derived
    # from company names, i.e. from data, so "the URL is always one of ours" was an assumption
    # rather than a guarantee. See scripts/untrusted.py.
    ok, why = allowed_url(url, hosts=ATS_HOSTS)
    if not ok:
        print(f"  ⛔ refused fetch: {why}", file=sys.stderr)
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None

def is_pm(title: str) -> bool:
    """True if the title is a product-management seat.

    FIXED 2026-07-19 (pipeline audit). Two bugs made real PM seats invisible, each one
    silently downgrading a company to '🟡 no live PM role → RADAR':
      1. The blacklist ran FIRST, so any PM role SCOPED to another domain was discarded —
         "Product Manager, Platform Engineering" and "Technical PM, Design Systems" both
         returned False on 'engineer'/'design'.
      2. Only the "of" phrasing matched, so "Director, Product Management", "VP of Product",
         "VP, Product", "Chief Product Officer", "Product Owner" and "Senior Manager, Product"
         all returned False.
    Fix: test for a PM title FIRST, and only then apply the blacklist to non-PM titles.
    """
    t = " ".join(title.lower().split())

    # 0) "Product <other-discipline>" is a DIFFERENT job, not a PM seat scoped to a domain.
    # Regression caught 2026-07-19: moving the blacklist after the affirmative tests made it
    # dead code, so "Director of Product Marketing", "VP of Product Design" and
    # "Lead Product Designer" all returned True — inflating live-role verdicts and pushing a
    # RADAR company into false LIVE framing. The distinction that matters:
    #   "Product MARKETING/DESIGN/…"          -> product modifies another discipline  -> NOT PM
    # NOTE: 'ops|operations' does NOT belong in this reject list. It wrongly hides
    # "Director of Product Operations" / "Product Operations Manager", and product-ops /
    # enablement is a real PM lane — rejecting it recreates the same false-RADAR failure this
    # function exists to prevent. Analytics/content/quality/data-science are the real
    # false positives. If product-ops is NOT a lane you want, add it back here.
    #   "Product Manager, Platform Engineering" -> a PM whose SCOPE is a domain        -> still PM
    # So reject a product-<discipline> title only when no explicit PM token is present.
    #
    # OTHER-DISCIPLINE SEATS. The leadership pattern below matches any "<word> Manager, Product
    # <word>", so non-PM seats returned True: "Engineering Manager, Product Platform", "Design
    # Manager, Product", "Marketing Manager, Product Launches", "Data Manager, Product Insights"
    # and "Lead Product Recruiter", the blacklist at the bottom was unreachable for all of them.
    # The direction of harm is INVERTED from the bug this function was last fixed for: FALSE-LIVE,
    # i.e. it reports an open PM seat at a company that has an engineering one.
    DISCIPLINE = (r"engineering|engineer|design|designer|marketing|sales|support|research|"
                  r"analytics|content|quality|data science|recruiting|recruiter|finance|legal")

    has_pm_token = bool(
        re.search(r"\bproduct (?:line )?(manager|management|owner)\b", t)
        or re.search(r"\b(chief product officer|cpo)\b", t)
    )
    # a) "Product <other-discipline>", product modifies another discipline, not a PM seat.
    #    (ops/enablement deliberately absent; see the note above.)
    if not has_pm_token and re.search(r"\bproduct (?:" + DISCIPLINE + r")\b", t):
        return False
    # b) "<other-discipline> Manager/Director/Lead, Product X", the SEAT belongs to that
    #    discipline; "Product X" is only the scope it covers.
    if not has_pm_token and re.search(
            r"\b(?:" + DISCIPLINE + r"|data)\s+(manager|director|lead|head|architect)\b", t):
        return False

    # 1) Affirmative PM-title tests run FIRST (a scoped PM role is still a PM role).
    if has_pm_token:
        return True
    # Leadership-of-product phrasings, both "of" and comma forms. Up to two MODIFIERS may sit
    # between the leadership token and "product": "Director of Platform Product" and "Senior
    # Director, Digital Product" are real PM seats that the modifier-free pattern missed.
    MOD = (r"(?:platform|digital|technical|core|global|enterprise|growth|consumer|commercial|"
           r"senior|group|staff|principal|line|new|corporate)\s+")
    if re.search(r"\b(head|director|vp|vice president|svp|senior manager|manager|lead)\b"
                 r"[ ,]*(of[ ,]*)?(?:" + MOD + r"){0,2}product\b", t):
        return True
    if "product" in t and re.search(r"\b(staff|principal|group|lead)\b", t):
        return True
    # Bare "PM" abbreviation ("Principal PM", "Senior PM, Payments") — common in real postings.
    if re.search(r"\bpm\b", t):
        return True
    # Product operations / enablement counts regardless of word order: "Product Operations
    # Manager" puts the noun after, which no leadership-phrasing pattern catches.
    if re.search(r"\bproduct (operations|ops|enablement)\b", t):
        return True

    # (A trailing "discard other functions" blacklist used to sit here. Both of its branches
    # returned False, so it changed nothing while reading like a working check. The real
    # discipline rejection is step (a)/(b) at the top, where it is reachable.)
    return False

def comp_from_text(txt: str):
    txt = html.unescape(re.sub("<[^>]+>", " ", txt or ""))
    m = re.search(r"\$[\d,]{3,}k?\s*(?:-|–|—|to)\s*\$?[\d,]{3,}k?", txt, re.I)
    return m.group().strip() if m else ""

# Board tokens that are NOT derivable from the company name. Add a row the moment a lookup
# resolves the WRONG company or misses a real board, because that is the only way this file learns.
#
# The generated suffixes below (data/hq/app/ai/inc) are guesses that happen to be cheap. They do not
# cover the common real case, which is name + industry word: a company called "Acme" may post on
# 'acmehealth' while the bare token 'acme' belongs to an unrelated company that happens to share the
# name. Seeded EMPTY on purpose: your aliases are yours to add.
#
#   ALIAS_TOKENS = {"acme": ["acmehealth"]}      # normalized company name -> extra tokens to probe
#
# ⚠️ This map is what makes the ambiguity check downstream able to fire at all. Without the second
# token, only ONE board resolves, nothing looks ambiguous, and you get a single confident WRONG
# answer, which is the worst outcome available here.
ALIAS_TOKENS = {}


def tokens_from(name: str):
    base = name.lower().strip()
    nospace = re.sub(r"[^a-z0-9]", "", base)
    hyphen = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    first = re.sub(r"[^a-z0-9]", "", base.split()[0]) if base.split() else nospace
    cands = [nospace, hyphen, first, nospace + "data", nospace + "hq",
             nospace + "app", nospace + "ai", nospace + "inc"]
    cands += ALIAS_TOKENS.get(nospace, [])
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c); out.append(c)
    return out


def board_identity(ats, token, _cache={}):
    """One line saying WHO a board belongs to, so a wrong-entity match is visible on sight.

    Every "About <company>" blurb differs even when the company NAME does not, which is what makes
    this the cheapest possible disambiguator. Best-effort: identity is a convenience for a human
    reading the ambiguity warning, so any failure returns a shrug rather than raising.
    """
    key = (ats, token)
    if key in _cache:
        return _cache[key]
    out = "(could not read the board's About text)"
    try:
        if ats == "Greenhouse":
            d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
            blob = " ".join((j.get("content") or "") for j in (d or {}).get("jobs", [])[:3])
            # UNESCAPE FIRST, then strip tags. Greenhouse returns `content` HTML-escaped, so
            # stripping before unescaping turns &lt;p&gt; back into a live <p> and leaves tag
            # debris in the one line a human reads to tell two companies apart.
            txt = re.sub(r"<[^>]+>", " ", html.unescape(blob))
            txt = re.sub(r"\s+", " ", txt).strip()
            m = re.search(r"\bAbout\s+[A-Z][\w.&' -]{1,40}?\s+((?:is|was|builds?|makes?)\b.{50,300})",
                          txt)
            out = (m.group(1) if m else txt[:280]).strip()
    except Exception:
        pass
    return _cache.setdefault(key, defang(out, limit=320))

def probe_greenhouse(token):
    for tk in dict.fromkeys([token, token.capitalize(), token.upper()]):
        d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{tk}/jobs?content=true")
        if isinstance(d, dict) and "jobs" in d:
            roles = []
            for j in d["jobs"]:
                if is_pm(j.get("title", "")):
                    roles.append({"title": j.get("title", ""),
                                  "loc": (j.get("location") or {}).get("name", ""),
                                  "comp": comp_from_text(j.get("content", "")),
                                  "url": j.get("absolute_url", "")})
            return ("Greenhouse", tk, len(d["jobs"]), roles)
    return None

def ashby_location(j):
    """Render an Ashby posting's location, trusting `workplaceType` over `isRemote`.

    ⚠️ ASHBY SETS `isRemote: true` ON HYBRID ROLES. Verified live 2026-07-25 against
    `someco-pay`, where the Technical Product Owner returns `isRemote: true` alongside
    `workplaceType: "Hybrid"` and `location: "Atlanta HQ"`. The old code appended " | remote"
    on `isRemote` alone, so an on-site Atlanta req printed as remote, and remote-absolute is
    The single hardest filter for a remote-only search. `workplaceType` is the authoritative field; `isRemote`
    appears to mean "not tied to one desk", not "work from anywhere".

    Hybrid and On-site are labeled LOUDLY rather than left bare, because a silent omission
    reads as "no location constraint found" to whoever scans the output.
    """
    loc = str(j.get("location", ""))
    wt = str(j.get("workplaceType", "") or "").strip()
    if wt.lower() == "remote":
        return loc + " | remote"
    if wt:
        # ⚠️ Never put the literal token "remote" in this branch. `assess_postings` substring-matches
        # the rendered location, so the phrase "isRemote=True" inside a HYBRID warning scored the req
        # as a remote seat, which is the very bug this function exists to kill. Caught 2026-07-25.
        return f"{loc} | ⚠️ {wt.upper()} per Ashby workplaceType (board flag not authoritative)"
    # No workplaceType at all: fall back, but never assert a remote seat off the board flag alone.
    return loc + (" | ⚠️ workplaceType absent, VERIFY" if j.get("isRemote") else "")


def probe_ashby(token):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true")
    if isinstance(d, dict) and "jobs" in d:
        roles = []
        for j in d["jobs"]:
            if is_pm(j.get("title", "")):
                c = j.get("compensation") or {}
                roles.append({"title": j.get("title", ""),
                              "loc": ashby_location(j),
                              "comp": c.get("compensationTierSummary", ""),
                              "url": j.get("jobUrl", "")})
        return ("Ashby", token, len(d["jobs"]), roles)
    return None

def probe_lever(token):
    d = get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    if isinstance(d, list):
        roles = []
        for j in d:
            if is_pm(j.get("text", "")):
                sr = j.get("salaryRange") or {}
                comp = f"{sr.get('min','')}-{sr.get('max','')} {sr.get('currency','')}".strip() if sr else ""
                roles.append({"title": j.get("text", ""),
                              "loc": (j.get("categories") or {}).get("location", ""),
                              "comp": comp, "url": j.get("hostedUrl", "")})
        return ("Lever", token, len(d), roles)
    return None

def main():
    if len(sys.argv) < 2:
        print('usage: check_ats.py "<company>"  |  --token <exacttoken>'); sys.exit(2)
    if sys.argv[1] == "--token" and len(sys.argv) > 2:
        toks = [sys.argv[2]]
    else:
        toks = tokens_from(sys.argv[1])
    print(f"check_ats: trying tokens {toks}\n")

    # ⛔ PROBE EVERY TOKEN. This loop used to break on the first token that resolved ANY board, and
    # "resolves a board" is not "is the right company". Found live 2026-07-26, where two unrelated
    # real companies shared a name:
    #
    #   the bare token   →  2 roles, a company in a completely different industry (and one whose
    #                       customer base would have been a hard-filter fail on its own)
    #   the real token   → 57 roles, the company actually being screened
    #
    # The bare token sorts first, so the probe stopped there and reported "no Product-Manager role →
    # 🟡 RADAR" for a company with SIX live remote product roles. That false fact then propagated
    # into the notes and downranked the company. A wrong-entity match is worse than NO match,
    # because it answers.
    #
    # Corroborating on the company NAME does not save you, because both companies really do carry
    # that name. When a name is ambiguous it cannot be resolved from the name alone, so the honest
    # move is to REFUSE a single verdict and make the human disambiguate with --token. Print each
    # board's own "About" line: that one snippet makes a wrong entity obvious at a glance.
    boards = []
    for tk in toks:
        for probe in (probe_greenhouse, probe_ashby, probe_lever):
            res = probe(tk)
            if res:
                boards.append(res)

    if len(boards) > 1:
        print(f"  🔴 AMBIGUOUS: {len(boards)} different ATS boards match this name. NOT verifying.")
        print("     These are probably DIFFERENT COMPANIES that share a name. Identify the right")
        print("     one below, then re-run with the exact token:\n")
        for ats, tk, total, roles in boards:
            print(f"     ▸ {ats} board '{tk}' — {total} open roles, {len(roles)} product role(s)")
            print(f"        who this is: {board_identity(ats, tk)}")
            print(f"        → python3 scripts/check_ats.py --token {tk}")
        print("\n  VERDICT: 🔴 UNRESOLVED — live-role status is UNVERIFIED until a token is chosen.")
        print("     ⛔ Do NOT build off either board. Picking the wrong one is how a company with")
        print("        six open PM seats gets recorded as having zero.")
        sys.exit(2)

    if not boards:
        print("  ❌ No ATS board found for these tokens (custom/other ATS, or wrong token).")
        print("     → treat live-role as UNVERIFIED; check the company careers page manually.")
        sys.exit(2)

    any_pm = False
    for ats, tk, total, roles in boards:
        print(f"  ✅ {ats} board '{tk}' — {total} open roles total")
        if roles:
            any_pm = True
            for r in roles:
                # Title, location and comp band are strings the EMPLOYER wrote, printed verbatim
                # into an agent's context. defang() leaves them readable but strips the leverage
                # from an instruction-shaped one. See scripts/untrusted.py.
                line = f"     ▸ {defang(r['title'], limit=200)} | {defang(r['loc'], limit=120)}"
                if r["comp"]:
                    line += f" | {defang(r['comp'], limit=120)}"
                print(line)
                if r["url"]:
                    print(f"        {r['url']}")
        else:
            print("     (no Product-Manager role on this board)")
    print()
    if any_pm:
        print("  VERDICT: 🔵 LIVE PM ROLE(S) — potential application + paired boss-hunt.")
        sys.exit(0)
    else:
        print("  VERDICT: 🟡 NO live PM role → RADAR (verify remote/travel/culture at company level; tag hiring-history timing).")
        # Exit 1 = "no live role" so a CALLER can branch on it (closes register gap G8's exit half).
        # This is NOT a drop: no-live-role is a valid RADAR reach. It exists so the build path is
        # forced into the RADAR register instead of silently writing live-role framing
        # ("I applied", "let's talk about your opening") for a job that does not exist.
        sys.exit(1)

if __name__ == "__main__":
    main()
