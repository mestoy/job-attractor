#!/usr/bin/env python3
"""check_customer_base.py — WHO does this company SELL TO? The cheapest disqualifying check there is.

WHY THIS EXISTS. Some deal-breakers are invisible to a keyword screen over a job title. Whether a
company sells to law enforcement, the military or another vetoed buyer is a fact about its CUSTOMER
BASE, which no regex over a company NAME or a job TITLE can see — a fraud-detection or cyber-risk
vendor rarely writes "police" in a product-manager posting. screen_sweep.py says as much in its own
comments, and its only defense is a hand-curated name list that grows AFTER a miss. This script
closes that loop by reading what the company says about its OWN customers on its OWN site.

Two illustrations of the class of miss this catches (invented names, real pattern — swap in
whatever you keep re-encountering):
  * a cyber-risk vendor whose /industries/government page states that "law enforcement" needs its
    visibility (call it SomeCo, someco.example/industries/government);
  * a voice-fraud vendor whose public-sector whitepaper names "law enforcement ... call centers"
    (call it Otherco) — and whose copy lives at a slug the fixed path list would never guess.
Both would clear a live-role check, a comp band and a boss-identification pass before anyone read a
page that took one fetch to load. This runs FIRST so the cheapest disqualifier stops running LAST.

⚠️ SCOPE, stated honestly. A miss here is a FALSE NEGATIVE, never a clearance. Absence of a
government page is weak evidence; plenty of vendors sell to police through resellers and say nothing
on their marketing site. **Exit 0 means "nothing found," not "cleared."** The full screen still runs.
What this buys is that the CHEAPEST disqualifier stops running LAST.

⚠️ CALIBRATION — do not make this blunter. Selling to "government" is NOT the veto; selling to
POLICING is. A contact-center vendor with a government page serving citizen services (DMV, benefits,
311-style lines) and zero police/dispatch/corrections terms is a legitimate PASS and a deliberate
negative-control fixture (a vendor whose site names no LE customers). Edit LE_TERMS / DEFENSE_TERMS below to match the exclusions in
YOUR rules doc — narrow them or widen them, but keep "government" and "policing" distinct.

Usage:
    scripts/check_customer_base.py "Acme"                 # guess the domain
    scripts/check_customer_base.py "Acme" acme.com        # explicit domain (preferred)
    scripts/check_customer_base.py "Acme" acme.com --json
Exit:
    0 = nothing found (NOT a clearance) · 1 = veto term found · 2 = usage / unreachable
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from untrusted import allowed_url, defang   # noqa: E402

# This script reads no repo files — it is purely a network probe — so it needs no repo-root path
# resolution, only its own directory on sys.path so it can import the shared config next to it.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# WHY import rather than re-declare the name list: a screening vocabulary must have ONE source.
# Duplicated copies of a veto list drift — in the origin repo two copies of a word-boundary rule
# fell out of sync, and the stale copy let a naive substring match authorize a real outreach draft
# in the gap. One source, imported. A screening list also ships POPULATED on purpose: an empty veto
# list does not "screen nothing loudly," it silently passes every known-bad name.
#
# VETO_EMPLOYERS is a list of company-NAME regexes for businesses whose INDUSTRY is a deal-breaker
# but whose NAME contains none of the banned keywords a body screen would catch. It is a CURATED
# floor, incomplete by construction, and it does not replace the per-company screen below.
try:
    from kit_config import VETO_EMPLOYERS
except Exception:  # standalone fallback — ⚠️ EXAMPLE public classifications; edit to YOUR employers
    VETO_EMPLOYERS = [
        r"\bcoinbase\b", r"\bkraken\b", r"\bbinance\b",                       # crypto exchanges
        r"\bpalantir\b", r"\banduril\b", r"\blockheed\b", r"\braytheon\b",    # defense primes
        r"\bnorthrop\b", r"\bgeneral dynamics\b", r"\bbooz allen\b", r"\bleidos\b",
        r"\baxon\b", r"\bflock safety\b", r"\bcellebrite\b",                  # law-enforcement vendors
        r"\bdraftkings\b", r"\bfanduel\b",                                    # gambling
    ]

# Pages a company uses to address public-sector buyers. Ordered cheapest-first by hit rate.
PATHS = [
    "/industries/government", "/government", "/public-sector", "/solutions/government",
    "/industries/public-sector", "/industries", "/customers", "/solutions",
]

# The POLICING veto. Deliberately narrower than "government" — see the calibration note above.
# Each entry is (regex, why) so a block record can quote its own reason.
LE_TERMS = [
    (r"\blaw[\s-]?enforcement\b", "law enforcement named as a customer"),
    (r"\bpolice\b|\bpolicing\b", "police named as a customer"),
    (r"\bsheriff\b", "sheriff's offices named as a customer"),
    (r"\bcorrections?\b(?!\s+(?:to|of|for)\b)", "corrections agencies named as a customer"),
    (r"\b911\b|\bdispatch\s+cent(?:er|re)", "emergency dispatch named as a customer"),
    (r"\bcjis\b", "CJIS compliance (criminal-justice information systems)"),
    (r"\bpublic\s+safety\b", "public safety named as a customer segment"),
]
DEFENSE_TERMS = [
    (r"\bdod\b|\bdepartment of defense\b", "Department of Defense named as a customer"),
    (r"\bwarfighter\b", "warfighter language"),
    (r"\bmilitary\b", "military named as a customer"),
    (r"\bdefense\s+(?:agencies|customers|contracts?|sector|mission)\b", "defense sector as a segment"),
]
# Government reseller/procurement vehicles. Not a veto ALONE (plenty of benign SaaS sells on GSA),
# but a strong amplifier when it appears next to a policing term, so it is reported, not fatal.
PROCUREMENT = [(r"\bcarahsoft\b", "Carahsoft"), (r"\bgsa\s+schedule\b", "GSA Schedule")]

UA = {"User-Agent": "Mozilla/5.0 (compatible; job-search-screen/1.0)"}


def fetch(url, timeout=12):
    if ASSET_URL.search(url):
        return ""
    # SSRF GUARD, NOT AN ALLOWLIST. Unlike check_ats, this tool's whole job is to read whatever
    # company is being screened, so a host allowlist would defeat it. What it does get is the other
    # half: no non-HTTP scheme, no embedded credentials, and no loopback/private/link-local
    # destination — 169.254.169.254 in particular, where a fetch of "a company site" becomes a read
    # of cloud instance metadata. See scripts/untrusted.py.
    ok, why = allowed_url(url, hosts=None, require_https=False)
    if not ok:
        return ""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return ""
            # Content-type guard as well as the extension guard: a URL with no extension can still
            # serve a PDF, and binary bytes regex into confident nonsense (the JPEG "DoD" match).
            ctype = (r.headers.get("Content-Type") or "").lower()
            if ctype and not any(t in ctype for t in ("text/html", "text/plain", "xml")):
                return ""
            raw = r.read(400_000)
        text = raw.decode("utf-8", errors="ignore")
        text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", text)
        return re.sub(r"<[^>]+>", " ", text)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return ""


def sentence_around(text, m):
    """Quote the matched sentence so a block record carries its own evidence.

    This is the sharpest untrusted-text path in the pipeline: a verbatim sentence, written by the
    company being screened, that gets printed and then copied into a durable ruling. defang() keeps
    it readable while stripping the leverage from an instruction-shaped one. See untrusted.py.
    """
    s = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
    e = text.find(".", m.end())
    e = e + 1 if e != -1 else m.end() + 120
    return defang(text[s:e], limit=300)


def candidate_domains(company, explicit=None):
    if explicit:
        return [explicit.replace("https://", "").replace("http://", "").strip("/")]
    slug = re.sub(r"[^a-z0-9]", "", company.lower())
    return [f"{slug}.com", f"{slug}.ai", f"{slug}.io"]


# URL slugs that mark a public-sector page wherever a CMS decided to put it.
SITEMAP_HINT = re.compile(
    r"government|public[-_]sector|public[-_]safety|law[-_]enforcement|federal|gov[-_]tech", re.I)

# Binary assets. ⚠️ Not hypothetical: an early sitemap-enabled run matched "DoD" inside the raw
# bytes of a scaled JPEG and reported it as "Department of Defense named as a customer". Regexing
# image data produces confident nonsense, and a screen that blocks on it is worse than no screen.
ASSET_URL = re.compile(r"\.(jpe?g|png|gif|svg|webp|pdf|zip|mp4|woff2?|css|js)(\?|$)"
                       r"|/wp-content/uploads/", re.I)

# Editorial pages. ⚠️ Also not hypothetical: the same run flagged a vendor's article on a 1990s
# espionage campaign, which mentions US "military and government agencies" as the VICTIMS of the
# attack, and read that as the vendor selling to the military. A company writing ABOUT defense is not
# a company selling TO defense. Marketing copy states who they sell to; editorial copy states what
# happened to somebody else. Only the former is evidence of a customer base.
EDITORIAL_URL = re.compile(r"/(article|articles|blog|news|press|press-release|glossary|podcast|"
                           r"webinar|event|events|author|category|tag)/", re.I)


def sitemap_urls(dom, cap=6):
    """Find public-sector pages via sitemap.xml instead of guessing paths.

    WHY (found in this script's own first test run): the fixed PATHS list caught one company (a
    cyber-risk vendor) on /industries/government and MISSED another (a voice-fraud vendor), whose
    law-enforcement copy lived at /research/whitepaper/public-sector-phone-channel-security/. A probe
    that clears a company you already KNOW sells to police is worse than no probe, because it
    launders a miss as a pass. You cannot enumerate every CMS layout; you can read the site's own
    index of itself. One extra fetch.
    """
    out = []
    for name in ("/sitemap.xml", "/sitemap_index.xml"):
        xml = fetch(f"https://{dom}{name}")
        if not xml:
            continue
        locs = re.findall(r"https?://[^\s<>\"']+", xml)
        # A sitemap INDEX points at more sitemaps. Follow them, skipping the ones that structurally
        # cannot hold marketing copy. ⚠️ An earlier `[:3]` cap here silently reproduced the exact
        # miss this function was written to fix: a company that publishes SIX sub-sitemaps kept its
        # law-enforcement whitepaper in the FOURTH (a resource sitemap), so the cap cleared a company
        # already known to sell to police. An arbitrary limit in a safety check is a false-negative
        # generator; bound it by relevance, not by an unexamined number.
        subs = [u for u in locs if u.endswith(".xml")
                and not re.search(r"(job|author|tag|category|glossary)[-_]sitemap", u, re.I)]
        for sub in subs[:8]:
            sub_xml = fetch(sub)
            if sub_xml:
                locs += re.findall(r"https?://[^\s<>\"']+", sub_xml)
        for u in locs:
            if u.endswith(".xml") or not SITEMAP_HINT.search(u):
                continue
            if ASSET_URL.search(u) or EDITORIAL_URL.search(u):
                continue  # see the two filters' own notes — both were real false-positive sources
            if u not in out:
                out.append(u)
            if len(out) >= cap:
                return out
        if out:
            return out
    return out


def probe(company, domain=None):
    findings, pages_read, base_used, seen_urls = [], 0, None, []
    for dom in candidate_domains(company, domain):
        # Fixed paths first (cheap, high hit rate), then whatever the site's own sitemap says is
        # public-sector — that second half is what catches a whitepaper the path list cannot guess.
        urls = [f"https://{dom}{p}" for p in PATHS] + sitemap_urls(dom)
        for url in urls:
            text = fetch(url)
            if not text or len(text) < 400:
                continue
            pages_read += 1
            seen_urls.append(url)
            base_used = base_used or dom
            low = text.lower()
            for group, label in ((LE_TERMS, "LAW-ENFORCEMENT"), (DEFENSE_TERMS, "DEFENSE")):
                for pat, why in group:
                    m = re.search(pat, low)
                    if m:
                        findings.append({"kind": label, "why": why, "url": url,
                                         "quote": sentence_around(text, m)})
            for pat, why in PROCUREMENT:
                if re.search(pat, low):
                    findings.append({"kind": "PROCUREMENT", "why": why, "url": url, "quote": ""})
        if pages_read:
            break  # a live domain was found; do not keep guessing others
    return findings, pages_read, base_used, seen_urls


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(2)
    company = args[0]
    domain = args[1] if len(args) > 1 else None

    named = [p for p in VETO_EMPLOYERS if re.search(p, company.lower())]
    findings, pages, base, probe_urls = probe(company, domain)
    hard = [f for f in findings if f["kind"] in ("LAW-ENFORCEMENT", "DEFENSE")]

    if as_json:
        print(json.dumps({"company": company, "domain": base, "pages_read": pages,
                          "curated_name_hit": bool(named), "findings": findings}, indent=2))
        sys.exit(1 if (hard or named) else 0)

    print(f"check_customer_base: {company}" + (f"  ({base})" if base else ""))
    if named:
        print("  🔴 CURATED VETO — this company is on kit_config.VETO_EMPLOYERS already.")
        sys.exit(1)
    if not pages:
        print("  ⚪ no public-sector page reachable (tried "
              f"{', '.join(candidate_domains(company, domain))}).")
        print("     NOT a clearance — absence of a page is weak evidence. Verify by hand if the")
        print("     company sells security, fraud detection, surveillance or govtech.")
        sys.exit(0)
    if not hard:
        # ⚠️ NEVER print a bare green when public-sector MARKETING URLs exist. The reason is the
        # voice-fraud example above: its sitemap carries a /research/whitepaper/public-sector-...
        # slug, the page fetches fine (10KB), and the phrase "law enforcement" is NOT in the HTML
        # because the whitepaper itself is a gated PDF. A body-only probe therefore CLEARS a company
        # whose own URL says it markets phone security to the public sector. The slug is evidence
        # even when the copy is behind a form — so surface it and make a human look, rather than
        # reporting a green that a later expensive screen will have to overturn.
        gov_urls = [f["url"] for f in findings if f["kind"] == "PROCUREMENT"]
        gov_urls += [u for u in probe_urls if SITEMAP_HINT.search(u)]
        gov_urls = sorted(set(gov_urls))
        if gov_urls:
            print(f"  🟡 REVIEW — no veto term in the page BODIES ({pages} read), but the company "
                  f"publishes public-sector marketing. Slugs are evidence; gated collateral is not "
                  f"readable by this probe. Check these by hand before clearing:")
            for u in gov_urls[:6]:
                print(f"     · {u}")
            for f in findings:
                if f["kind"] == "PROCUREMENT":
                    print(f"     · government reseller signal: {f['why']}")
            sys.exit(0)
        print(f"  🟢 nothing found across {pages} page(s). NOT a clearance — the full screen still runs.")
        sys.exit(0)
    print(f"  🔴 VETO — {len(hard)} hit(s) across {pages} page(s):")
    for f in hard:
        print(f"     [{f['kind']}] {f['why']}")
        print(f"       {f['url']}")
        if f["quote"]:
            print(f'       "{f["quote"]}"')
    for f in findings:
        if f["kind"] == "PROCUREMENT":
            print(f"     · amplifier: {f['why']} ({f['url']})")
    sys.exit(1)


if __name__ == "__main__":
    main()
