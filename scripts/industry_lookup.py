#!/usr/bin/env python3
"""industry_lookup.py: classify a company from a maintained PUBLIC source (#24).

WHY. `veto_hits` reads industry words out of the company NAME, so it only stops a company that spelled
its industry into its own name. A kit user measured one sweep of 105 companies (kit issue #24): the few
whose names said "Bank", "Fintech" or "Defense" were caught, while a majority of financial firms
reached the banked pool against an operator whose FIRST hard filter was financial services.
The sourced segment cache (documents/state, written only by resolve_employers) already exists and is consulted first;
this module is a NEW FEEDER for it, so a company that never says its industry gets one from a source.

SOURCES, free, no key, nothing installed:
  1. Wikidata  P452 industry, P31 instance of, P856 official website. CC0.
     Policy: https://www.wikidata.org/wiki/Wikidata:Data_access  (descriptive User-Agent, about one
     request a second, which the default transport enforces).
  2. SEC EDGAR company_tickers.json plus the submissions API (`sic`, `sicDescription`).
     Policy: https://www.sec.gov/os/accessing-edgar-data  (a descriptive User-Agent with a contact
     point, at most ten requests a second). SEC answers 403 to a User-Agent with no contact point, so
     the person's setup email (JOBKIT_OWNER_EMAIL or kit_config.OWNER_EMAIL) goes in SEC's
     User-Agent only; with none set EDGAR is skipped (proxy 142) and Wikidata alone answers.

THE RULES THIS ENFORCES:
  M1  a `label` match (name equals a Wikidata label, no domain proof) may VETO but never settle the industry.
  M2  an industry code is not a customer check. This module says what a company IS, never who it
      SELLS to; the law enforcement and defense customer screens stay owed and `veto_hits` over the
      card text still fires whatever the code said.
  S1  superseded by proxy 142: the person's setup email rides in SEC's User-Agent only, never in a
      Wikidata request; with no email EDGAR is skipped.
  M3  a partial answer (a tried source failed) never resolves; only a veto is kept from it.
  Ambiguity never guesses (two same-label items and no domain returns None). A dead network returns
  None, never "resolved". Results cache in `documents/state/industry-lookup-cache.jsonl`
  (append-only, newest row wins, 90-day refresh).

THIS MODULE NEVER WRITES THE SEGMENT CACHE. `resolve_employers.py ingest` stays the only
validated writer; the sweep hands it the domain and EDGAR matches.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE))
CACHE = os.path.join(REPO, "documents", "state", "industry-lookup-cache.jsonl")
REFRESH_DAYS = 90
TIMEOUT = 8

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
EDGAR_TICKERS = "https://www.sec.gov/files/company_tickers.json"
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK%s.json"
EDGAR_BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=%s"
KIT_CONTACT_URL = "https://github.com/mestoy/job-attractor-kit"

# The family names the shipped map uses. The kit has no deal-breakers of its own (someone else may
# work in defense): a family vetoes when the person's OWN INDUSTRY_VETO words ask for it (see
# FAMILY_WORDS), a class they add in kit_config.INDUSTRY_USER_FILTERS vetoes too, and an industry
# label that trips their INDUSTRY_VETO words vetoes whatever the map says.
FAMILY_CLASSES = ("defense", "law-enforcement", "gambling", "crypto", "predatory-lending",
                  "dtc-rx-telehealth")

# P31 classes that mean "this item is a company". A family-name item (Q101352) or a stadium is not.
BUSINESS_CLASSES = {"Q4830453", "Q783794", "Q891723", "Q22687", "Q43229", "Q6881511", "Q167037",
                    "Q161726"}

_SUFFIX = re.compile(r"\b(inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|plc|"
                     r"sa|s\.a|nv|bv|ag|pty|pte|llp|lp)\b\.?", re.I)


def name_key(name):
    """Distinctive part of a name: parentheticals, legal suffix and punctuation dropped."""
    s = re.sub(r"\(.*?\)", " ", (name or "").lower())
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def _host(url):
    h = (urllib.parse.urlparse(url if "//" in url else "//" + url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


# ── transport ────────────────────────────────────────────────────────────────────────────────
def owner_email():
    """The person's setup email (proxy 142): JOBKIT_OWNER_EMAIL, else kit_config.OWNER_EMAIL, else
    "". It goes in SEC's User-Agent ONLY, because SEC refuses a User-Agent with no contact (403,
    measured 2026-10-04). Wikidata's User-Agent never carries it. With none set EDGAR is skipped."""
    e = (os.environ.get("JOBKIT_OWNER_EMAIL") or "").strip()
    if not e:
        try:
            import kit_config
            e = (getattr(kit_config, "OWNER_EMAIL", "") or "").strip()
        except Exception:
            e = ""
    # kit_config.example.py ships OWNER_EMAIL = "you@example.com": a placeholder, not a contact, so it
    # counts as "not set" (EDGAR skipped) rather than sending SEC a fake address.
    if e.lower().endswith("@example.com") or "@" not in e:
        return ""
    return e


def user_agent(email=""):
    """The kit's descriptive User-Agent, with `email` appended only when given (the SEC calls)."""
    ua = "Job Attractor kit (+%s)" % KIT_CONTACT_URL
    return ua + (" " + email if email else "")


_last = {"t": 0.0}


def default_transport(url, headers):
    """GET `url`, return parsed JSON. About one request a second, 8 s timeout. Raises on any error."""
    wait = 1.0 - (time.time() - _last["t"])
    if wait > 0:
        time.sleep(wait)
    _last["t"] = time.time()
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


_memo = {}


def reset_memo():
    _memo.clear()
    _analysis.clear()


# ── the map, data not code ───────────────────────────────────────────────────────────────────
def _cfg():
    try:
        import kit_config
        return {"wikidata": dict(getattr(kit_config, "INDUSTRY_CLASSES", {}).get("wikidata", {})),
                "sic": list(getattr(kit_config, "INDUSTRY_CLASSES", {}).get("sic", [])),
                "user_filters": list(getattr(kit_config, "INDUSTRY_USER_FILTERS", []) or [])}
    except Exception:
        return {"wikidata": {}, "sic": [], "user_filters": []}


HOLD = "hold"          # neither vetoes nor resolves: stays unknown, the send stays held
VETO_TERM = "veto-term"  # the looked-up industry LABEL tripped a kit_config.INDUSTRY_VETO word (M4)


# Proxy 166: a family vetoes when any of its words appears in the person's OWN INDUSTRY_VETO. There is
# no extra setup question: the deal-breakers they already wrote decide which classes stop a company.
# INDUSTRY_USER_FILTERS only ADDS a class (e.g. "financial-services"); it never removes a derived one.
# Proxy 171: the person's regexes are COMPILED and run against these sample phrases; a family is
# derived when any of their regexes matches any of its phrases. Matching the regex's own TEXT for a
# family word fails open on `defen[cs]e`, `sports? bett`, `gambl(e|ing)`, `pay ?day`, `polic(e|ing)`
# and over-derives on `defined`, `nftables`, `dodge`, `pharmaceutical`.
#
# Proxy 173: each phrase's only distinctive word is its family word, so a pattern for a filler word
# (agency, contractor, department, platform, online, industry...) derives nothing.
FAMILY_PHRASES = {
    "defense": ("defense", "defence", "military", "weapons", "weapon", "arms", "munitions", "warfighter",
                "dod"),
    "law-enforcement": ("law enforcement", "police", "policing", "surveillance"),
    "gambling": ("gambling", "betting", "sports betting", "casino", "sportsbook", "igaming", "lottery",
                 "poker"),
    "crypto": ("crypto", "cryptocurrency", "bitcoin", "blockchain", "web3", "defi", "nft"),
    "predatory-lending": ("payday loan", "payday lender", "subprime", "lease-to-own", "rent-to-own",
                          "buy now pay later", "merchant cash advance", "factor rate",
                          "earned wage access", "pawn shop", "title loan"),
    "dtc-rx-telehealth": ("telehealth prescribing", "ketamine", "pharmacy prescription",
                          "direct-to-consumer telehealth", "compounded semaglutide", "glp-1"),
}
_ALL_PHRASES = tuple(ph for phs in FAMILY_PHRASES.values() for ph in phs)
REGEX_BUDGET = 0.25     # seconds one veto regex may spend over every sample phrase


def _words(cfg):
    words = cfg.get("veto_words")
    if words is None:
        try:
            import kit_config
            words = list(getattr(kit_config, "INDUSTRY_VETO", []) or [])
        except Exception:
            words = []
    return words


class _Budget(Exception):
    pass


def _interruptible():
    import signal
    import threading
    return hasattr(signal, "setitimer") and threading.current_thread() is threading.main_thread()


def _timed(fn, seconds):
    """(finished, value): run fn() under a wall-clock budget. Python's regex engine checks for signals
    while it matches, so SIGALRM cuts a catastrophic match off, but ONLY on the main thread (Unix).
    Off the main thread the analysis runs in a child process instead (see _analyze)."""
    import signal

    def _handler(signum, frame):
        raise _Budget()
    old = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return True, fn()
    except _Budget:
        return False, None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def _analyze_uncached(words):
    """(families, bad, slow, usable): run each of the person's regexes, compiled, against the sample
    phrases under a time budget (proxy 184: no static shape classifier). A regex that does not compile
    (bad) or blows the derivation budget (slow) derives nothing and HOLDS the industry source (see
    unusable_patterns); doctor blocks on it. It is never dropped from real-text checks: see check_text."""
    fams, bad, slow, usable = set(), [], [], []
    for w in words:
        try:
            rx = re.compile(str(w), re.I)
        except re.error:
            bad.append(w)
            continue

        def run(rx=rx):
            return {fam for fam, phs in FAMILY_PHRASES.items() if any(rx.search(ph) for ph in phs)}
        done, hit = _timed(run, REGEX_BUDGET)
        if not done:
            slow.append(w)
            continue
        fams |= hit
        usable.append((w, rx))
    return fams, bad, slow, usable


def _analyze_in_child(words):
    """The same analysis in a child process with a hard timeout, for callers off the main thread
    (serve.py request threads), where SIGALRM cannot interrupt a match."""
    import subprocess
    try:
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "--analyze-patterns"],
                           input=json.dumps(list(words)), capture_output=True, text=True,
                           timeout=2 + 1.5 * len(words))
        d = json.loads(p.stdout)
        usable = [(w, re.compile(str(w), re.I)) for w in d["usable"]]
        return set(d["fams"]), list(d["bad"]), list(d["slow"]), usable
    except Exception:
        return set(), [], list(words), []     # could not prove any regex safe: all unusable, fail closed


_analysis = {}


def _analyze(cfg):
    key = tuple(str(w) for w in _words(cfg))
    if key not in _analysis:         # memoized per regex set: the sample run is not repeated per company
        _analysis[key] = (_analyze_uncached(list(key)) if _interruptible() or not key
                          else _analyze_in_child(key))
    return _analysis[key]


def bad_patterns(cfg=None):
    """The person's veto regexes that do not compile. They match nothing and derive nothing."""
    return list(_analyze(cfg or _cfg())[1])


def slow_patterns(cfg=None):
    """The person's veto regexes that blew the time budget or have a backtracking shape."""
    return list(_analyze(cfg or _cfg())[2])


def unusable_patterns(cfg=None):
    """Every veto regex that does not compile or blew the derivation budget. While ANY is present
    the industry source resolves nothing (it holds); doctor blocks."""
    a = _analyze(cfg or _cfg())
    return list(a[1]) + list(a[2])


CHECK_BUDGET = 1.5      # seconds ONE real-text check (all the person's veto regexes) may take


def _search_all(patterns, text, flags, cur=None):
    hits = set()
    for p in patterns:
        if cur is not None:
            cur[0] = p
        m = re.search(p, text, flags)
        if m:
            hits.add(m.group(0))
    return sorted(hits)


def check_text(patterns, text, budget=CHECK_BUDGET, flags=0):
    """(hits, held): run the person's veto regexes over `text` under ONE time-box per call (proxy 184).

    * a pattern that does not compile: held, naming it. Never dropped, never skipped.
    * the call takes longer than `budget`: held ("took too long to check"), so that card is neither
      resolved nor passed. Main thread: SIGALRM. Any other thread (serve.py request threads): a child
      process with a hard kill, because SIGALRM cannot interrupt a match there.
    * otherwise held is "" and hits are the matched terms."""
    good, bad = [], []
    for p in (str(p) for p in patterns):
        try:
            re.compile(p, flags)
            good.append(p)
        except re.error:
            bad.append(p)
    held = ("your veto pattern %r does not compile, so this card is held" % bad[0]) if bad else ""
    if not good:
        return [], held
    text = text or ""
    if _interruptible():
        cur = [good[0]]
        done, hits = _timed(lambda: _search_all(good, text, flags, cur), budget)
        if not done:
            return [], "your veto pattern %r took too long to check (over %.1f s), so this card is held" % (cur[0], budget)
    else:
        hits, took = _check_in_child(good, text, budget, flags)
        if took:
            return [], took
    # the patterns that DO compile still run, so a working veto still vetoes; the bad one holds the card
    return hits, held


def _check_in_child(patterns, text, budget, flags):
    """(hits, held reason) from a child process with a hard kill, for threads where SIGALRM cannot work."""
    import subprocess
    try:
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "--check-text"],
                           input=json.dumps({"patterns": patterns, "text": text, "flags": int(flags)}),
                           capture_output=True, text=True, timeout=budget + 1.5)
        return list(json.loads(p.stdout)["hits"]), ""
    except Exception:       # a timeout (the child is killed) or any failure to answer: hold, never pass
        return [], "your veto pattern took too long to check (over %.1f s), so this card is held" % budget


def derived_families(cfg=None):
    """The family classes the person's own INDUSTRY_VETO regexes ask to veto."""
    return set(_analyze(cfg or _cfg())[0])


def vetoes(cls, cfg=None):
    cfg = cfg or _cfg()
    return cls == VETO_TERM or cls in (cfg.get("user_filters") or []) or cls in derived_families(cfg)


def _veto_term(text, cfg):
    """True when `text` (an industry label) trips the kit's own veto words. A backstop for an industry
    code the map does not know: Wikidata spells it 'defence', and the map cannot list every code."""
    return bool(_label_check(text, cfg)[0])


def _label_check(text, cfg):
    """(hits, held) for one industry label against the person's veto regexes, one time-box per call."""
    return check_text(_words(cfg), (text or "").lower(), flags=re.I)


def tripping_label(labels, cfg):
    """The first industry label that trips the person's veto words, or None (142c: the veto message
    names it, so a person can see WHICH label stopped the company)."""
    for lab in labels or []:
        if _label_check(lab, cfg)[0]:
            return lab
    return None


def _pick(classes, text, cfg):
    """Strictest wins: a veto (mapped or by label), then HOLD, then the first resolving class."""
    for c in classes:
        if vetoes(c, cfg):
            return c
    hits, held = _label_check(text, cfg)
    if hits:
        return VETO_TERM
    if HOLD in classes or held:      # a label check that could not finish holds: never resolved or passed
        return HOLD
    for c in classes:
        if c != "off-segment":
            return c
    return "off-segment"


def _class_for_wikidata(qids, labels, cfg):
    """The strictest class across an item's industries; an unmapped industry is off-segment carrying
    its own label (which is still checked against the veto words)."""
    return _pick([cfg["wikidata"][q] for q in qids if q in cfg["wikidata"]], " ; ".join(labels or []), cfg)


def _class_for_sic(sic, cfg, label=""):
    try:
        n = int(sic)
    except (TypeError, ValueError):
        return _pick([], label, cfg)
    return _pick([c for lo, hi, c in cfg["sic"] if lo <= n <= hi], label, cfg)


def reclass(row, cfg=None):
    """The class of a stored row under the CURRENT map, worked out from its codes (S2), so fixing the
    map re-classifies rows cached or ingested earlier instead of trusting the class written then."""
    cfg = cfg or _cfg()
    code = str(row.get("code") or "")
    label = str(row.get("industry") or "")
    if code.startswith("wikidata:"):
        return _class_for_wikidata(row.get("industry_codes") or [], row.get("industry_labels") or [label], cfg)
    if code.startswith("sic:"):
        return _class_for_sic(code[4:], cfg, label)
    return row.get("class") or "off-segment"


# ── Wikidata ─────────────────────────────────────────────────────────────────────────────────
def _claim_ids(ent, prop):
    out = []
    for c in (ent.get("claims") or {}).get(prop, []):
        v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "id" in v:
            out.append(v["id"])
    return out


def _claim_strs(ent, prop):
    out = []
    for c in (ent.get("claims") or {}).get(prop, []):
        v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if isinstance(v, str):
            out.append(v)
    return out


def _label(ent):
    return ((ent.get("labels") or {}).get("en") or {}).get("value", "")


def _wikidata(name, domain, transport, headers, cfg):
    """(result|None, detail). Raises on a transport error; the caller reports 'unreachable'."""
    q = urllib.parse.urlencode({"action": "wbsearchentities", "search": re.sub(r"\(.*?\)", " ", name).strip() or name,
                                "language": "en", "type": "item", "limit": 7, "format": "json"})
    found = transport(WIKIDATA_API + "?" + q, headers).get("search", [])
    ids = [x["id"] for x in found if x.get("id")]
    if not ids:
        return None, "not in Wikidata"
    q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels",
                                "languages": "en", "format": "json"})
    ents = transport(WIKIDATA_API + "?" + q, headers).get("entities", {})
    biz = [(i, ents[i]) for i in ids if i in ents and BUSINESS_CLASSES & set(_claim_ids(ents[i], "P31"))]
    if not biz:
        return None, "no company item in Wikidata"
    chosen, how = None, None
    if domain:
        want = _host(domain)
        by_dom = [(i, e) for i, e in biz if want in {_host(u) for u in _claim_strs(e, "P856")}]
        if len(by_dom) == 1:
            chosen, how = by_dom[0], "domain"
        elif len(by_dom) > 1:
            return None, "ambiguous (%d items share the domain)" % len(by_dom)
    if not chosen:
        key = name_key(name)
        by_label = [(i, e) for i, e in biz if name_key(_label(e)) == key]
        if len(by_label) == 1:
            chosen, how = by_label[0], "label"
        elif len(by_label) > 1:
            return None, "ambiguous (%d items), add the domain" % len(by_label)
        else:
            return None, "no Wikidata item named %r" % name
    qid, ent = chosen
    inds = _claim_ids(ent, "P452")
    if not inds:
        return None, "Wikidata %s has no industry (P452)" % qid
    q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(inds[:6]), "props": "labels",
                                "languages": "en", "format": "json"})
    lab = transport(WIKIDATA_API + "?" + q, headers).get("entities", {})
    names = [_label(lab[i]) for i in inds[:6] if i in lab and _label(lab[i])]
    return {"industry": ", ".join(names[:3]) or inds[0], "code": "wikidata:" + qid,
            "source": "https://www.wikidata.org/wiki/" + qid, "matched_by": how,
            "class": _class_for_wikidata(inds, names, cfg), "industry_codes": inds[:6],
            "industry_labels": names}, ""      # EVERY label the veto check saw (142b), not just the 3 shown


# ── EDGAR ────────────────────────────────────────────────────────────────────────────────────
def _tickers(transport, headers):
    k = id(transport)
    if k not in _memo:
        _memo[k] = transport(EDGAR_TICKERS, headers)
    rows = _memo[k]
    return rows.values() if isinstance(rows, dict) else rows


def _edgar(name, transport, headers, cfg):
    key = name_key(name)
    if not key:
        return None, "empty name"
    ciks = {}
    for r in _tickers(transport, headers):
        if name_key(r.get("title", "")) == key:
            ciks[int(r["cik_str"])] = r
    if not ciks:
        return None, "not in EDGAR"
    if len(ciks) > 1:
        return None, "ambiguous (%d EDGAR filers)" % len(ciks)
    cik = "%010d" % next(iter(ciks))
    sub = transport(EDGAR_SUBMISSIONS % cik, headers)
    sic = str(sub.get("sic") or "")
    if not sic:
        return None, "EDGAR %s has no SIC" % cik
    return {"industry": sub.get("sicDescription") or ("SIC " + sic), "code": "sic:" + sic,
            "source": EDGAR_BROWSE % cik, "matched_by": "edgar",
            "class": _class_for_sic(sic, cfg, sub.get("sicDescription") or "")}, ""


# ── lookup ───────────────────────────────────────────────────────────────────────────────────
def lookup_ex(name, domain="", transport=None, cfg=None, today=None, email=None):
    """(result|None, detail). Never raises, never guesses.

    Wikidata first, EDGAR second, and EDGAR only when the person's setup email is set (proxy 142: it
    goes in SEC's User-Agent alone; with none, EDGAR is SKIPPED, not attempted and not counted as
    unreachable). A veto-family class from either source is reported even when the other source
    resolves (fail closed). Among non-veto results the order is domain, edgar, label.

    A PARTIAL answer (a source that was tried and failed) NEVER resolves: only a veto
    may be kept from it, because a veto fails closed and a resolve does not. Wikidata down plus an
    EDGAR SIC that reads as resolved must not become a 90-day 'resolved' for a weapons company.

    N2: an EDGAR name-equality match resolves (plan-sanctioned); company_tickers.json lists current
    ticker filers only, but a startup named like an older filer would resolve to that filer."""
    transport = transport or default_transport
    cfg = cfg or _cfg()
    email = owner_email() if email is None else email
    wd_headers = {"User-Agent": user_agent(), "Accept": "application/json"}
    sec_headers = {"User-Agent": user_agent(email), "Accept": "application/json"}
    results, details, unreachable = [], [], False
    steps = [(_wikidata, (name, domain), wd_headers)]
    if email:
        steps.append((_edgar, (name,), sec_headers))
    else:
        details.append("EDGAR skipped: no setup email")
    for fn, args, headers in steps:
        try:
            r, d = fn(*args, transport, headers, cfg)
        except Exception:
            unreachable = True
            details.append("source unreachable")
            continue
        if r:
            results.append(r)
        elif d:
            details.append(d)
    if unreachable:
        results = [r for r in results if vetoes(r["class"], cfg)]
    if not results:
        if unreachable:
            return None, "source unreachable"
        # an ambiguity in any source is the more useful thing to say
        amb = [d for d in details if d.startswith("ambiguous")]
        if amb:
            return None, amb[0]
        noind = [d for d in details if "no industry" in d]
        if noind:
            return None, noind[0]
        where = "Wikidata or EDGAR" if email else "Wikidata (EDGAR skipped: no setup email)"
        return None, "not in %s (checked %s)" % (where, (today or date.today()).isoformat())
    order = {"domain": 0, "edgar": 1, "label": 2}
    results.sort(key=lambda r: (0 if vetoes(r["class"], cfg) else 1, order[r["matched_by"]]))
    best = dict(results[0])
    best["checked"] = (today or date.today()).isoformat()
    return best, ("partial: a source was unreachable" if unreachable else "")


def lookup(name, domain="", transport=None, cfg=None, today=None):
    return lookup_ex(name, domain, transport, cfg, today)[0]


# ── the lookup cache (append-only, newest wins) ──────────────────────────────────────────────
def _read(path=None):
    path = path or CACHE
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("name"):
                    out[name_key(row["name"])] = row
    except OSError:
        pass
    return out


def cached(name, path=None):
    """The newest row for `name` of ANY age, or None. A stale veto still reads as a veto."""
    return _read(path).get(name_key(name))


def is_fresh(row, today=None):
    try:
        seen = datetime.strptime(str(row.get("checked"))[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return ((today or date.today()) - seen).days < REFRESH_DAYS


def row_answers(row, domain=""):
    """True when the cached `row` still answers this ask: it is fresh AND, when the caller now has a
    company domain the row was not asked with, a forced refresh for that one name (142b: the 'add the
    domain and re-run' path must not wait out the 90 days)."""
    if not is_fresh(row):
        return False
    return not domain or (row.get("domain_asked") or "") == domain


def _record(name, result, detail, path, today, domain=""):
    row = {"name": name, "status": "match" if result else "none", "domain_asked": domain or "",
           "detail": detail, "checked": (today or date.today()).isoformat()}
    if result:
        row.update(result)
        row["checked"] = (today or date.today()).isoformat()
    path = path or CACHE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def lookup_cached(name, domain="", transport=None, cfg=None, cache_path=None, today=None):
    """lookup() behind the cache: a fresh row costs no request. A source outage is not recorded, so
    a dead network never writes a 90-day 'not found'."""
    row = cached(name, cache_path)
    if row and row_answers(row, domain):
        if row.get("status") != "match":
            return None
        return dict(row, **{"class": reclass(row, cfg)})
    r, detail = lookup_ex(name, domain, transport, cfg, today)
    if r is None and detail == "source unreachable":
        return None
    # Everything else is a COMPLETE answer (absent, label-only, domain, edgar, or a veto kept from a
    # partial) and is recorded with the same 90-day refresh (M2): absent names stop being re-queried.
    _record(name, r, detail, cache_path, today, domain)
    return r


def gate_read(name, path=None, cfg=None):
    """What the screen gate needs from the cache, with no network: None, ('vetoed', detail),
    ('held', detail) or ('label-only', detail). Any age counts, so a stale veto still stops the
    company (fail closed). The class is worked out NOW from the stored codes (S2)."""
    row = cached(name, path)
    if not row or row.get("status") != "match":
        return None
    cfg = cfg or _cfg()
    cls = reclass(row, cfg)
    label = ("Wikidata: " if str(row.get("code", "")).startswith("wikidata:") else "EDGAR: ") + \
        str(row.get("industry") or "")
    if vetoes(cls, cfg):
        extra = " (label match only, add the domain to confirm; %s)" % row.get("source", "") \
            if row.get("matched_by") == "label" else " (%s)" % row.get("source", "")
        tag = cls
        if cls == VETO_TERM:
            hit = tripping_label(row.get("industry_labels") or [row.get("industry") or ""], cfg)
            tag = "%s: the industry label %r matched your INDUSTRY_VETO words" % (cls, hit)
        return "vetoed", "%s [%s]%s" % (label, tag, extra)
    if cls == HOLD:
        return "held", "held: %s reads defense-adjacent or sensitive, state the industry and the " \
            "customers (%s)" % (label, row.get("source", ""))
    bad = unusable_patterns(cfg)
    if bad:      # proxy 178: a veto regex that cannot be trusted means the source resolves NOTHING
        return "held", "held: your INDUSTRY_VETO pattern %r is unusable (does not compile, too slow, or " \
            "backtracks), so the industry source resolves nothing until it is fixed (run doctor)" % bad[0]
    if row.get("matched_by") == "label":
        return "label-only", "label match only (%s), add the domain to confirm" % \
            str(row.get("code", "")).replace("wikidata:", "Wikidata ")
    return None


def segments():
    """YOUR segment slugs (kit_config.SEGMENT_SLUGS). A mapped class that is one of them ingests as
    that segment; every other class ingests as off-segment with the industry label kept."""
    try:
        import kit_config
        return set(getattr(kit_config, "SEGMENT_SLUGS", []) or [])
    except Exception:
        return set()


def ingest_row(name, result, cfg=None):
    """The row resolve_employers.py ingest takes, or None when this result may not resolve (a
    label-only match, M1). The caller hands it to the validator; this module never writes it."""
    if not result or result.get("matched_by") not in ("domain", "edgar") or result.get("class") == HOLD:
        return None             # a HOLD class never resolves (S1)
    if vetoes(result.get("class", ""), cfg):
        return None             # defense in depth (142b): a vetoing class is never ingested as resolved
    if unusable_patterns(cfg):
        return None             # proxy 178: an unusable veto regex holds everything the source would resolve
    seg = result["class"] if result["class"] in segments() else "off-segment"
    return {"employer": name, "segment": seg, "industry": result["industry"],
            "source": result["source"], "confidence": "stated",
            "note": "industry_lookup %s %s class=%s" % (result["matched_by"], result.get("code"), result["class"])}


def main():
    if "--check-text" in sys.argv:            # the child-process path of check_text (stdin: JSON)
        d = json.loads(sys.stdin.read() or "{}")
        print(json.dumps({"hits": _search_all(d.get("patterns", []), d.get("text", ""), d.get("flags", 0))}))
        return
    if "--analyze-patterns" in sys.argv:      # the child-process path of _analyze (stdin: JSON list)
        fams, bad, slow, usable = _analyze_uncached(json.loads(sys.stdin.read() or "[]"))
        print(json.dumps({"fams": sorted(fams), "bad": bad, "slow": slow, "usable": [w for w, _ in usable]}))
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="company names to look up")
    ap.add_argument("--domain", default="")
    ap.add_argument("--worklist", action="store_true",
                    help="look up the pool's employers the segment cache lacks (dry run, nothing ingested)")
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    names = list(a.names)
    if a.worklist:
        sys.path.insert(0, HERE)
        import importlib
        cs = importlib.import_module("contact_signals")  # CLI-only; the lookup itself stays stdlib
        re_ = importlib.import_module("resolve_employers")
        have = cs.load_employer_cache()
        names += [e for e, _ in re_.pool_employers().most_common() if cs._employer_key(e) not in have]
        names = names[:a.limit]
    for n in names:
        r, d = lookup_ex(n, a.domain)
        print(json.dumps({"name": n, "result": r, "detail": d}, ensure_ascii=False))


if __name__ == "__main__":
    main()
