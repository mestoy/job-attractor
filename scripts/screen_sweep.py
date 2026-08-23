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

REPO = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.abspath(__file__))


def _import_sibling(modname):
    """Import a same-directory sibling module, immune to a STALE `sys.modules` entry.

    ⛔ THIS FILE IS THE ONE THAT CAUSED THE BUG IT NOW GUARDS AGAINST (2026-08-09). Its own
    `sys.path.insert(0, HERE)` at module scope is harmless when it runs from its install, and
    poisonous when a COPY of it is loaded from somewhere else: `HERE` then points at the copy's
    directory, and its bare `import kit_config` caches that copy under the SHARED name. Python's
    import system caches by bare name and never by path, so every later plain `import kit_config`
    in the same process silently reuses the wrong object, even after the copy's directory is gone.

    ⚖️ The consequence is worth stating plainly, because it is the reason this is defended rather
    than documented: a screening module resolving the wrong config can make a blocked-list lookup
    answer False for everything, and a blocked list that goes quiet reports success. So: check a
    cached module's `__file__` sits in THIS directory, and reload from the correct path when it
    does not, which self-heals `sys.modules` for every other bare importer in the process.
    """
    expected = os.path.join(HERE, modname + ".py")
    mod = sys.modules.get(modname)
    if mod is not None and os.path.abspath(getattr(mod, "__file__", "") or "") == os.path.abspath(expected):
        return mod
    import importlib.util
    spec = importlib.util.spec_from_file_location(modname, expected)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    _kc = _import_sibling("kit_config")
    COMP_FLOOR, INDUSTRY_VETO = _kc.COMP_FLOOR, _kc.INDUSTRY_VETO
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
# ⚠️ RETAINED AS THE FALLBACK ONLY. See SEAT_TITLE below for why this is no longer the primary path.
NON_PM = r"\b(engineer|scientist|analyst|architect|intern|marketing|sales|account executive|" \
         r"recruiter|designer|consultant|specialist|coordinator|operations manager)\b"

# ── SEAT_TITLE — BUG-105 (reported from a partner install, ruled 2026-08-09) ──────────────────
# NON_PM is a NEGATIVE exclude list and it encodes an assumption: that you are hunting PRODUCT
# seats. It names analyst, architect, consultant, specialist and coordinator as "not a product
# seat". If those are YOUR target seats, this screener was throwing your real matches away before
# any other gate ran, and throwing them away SILENTLY, because the filter had no counter. Measured
# on a real install: 5 of 9 target titles dropped, two whole segments returning nothing while the
# sweep reported success.
#
# ⚖️ SET `SEAT_TITLE` IN kit_config.py TO DECLARE YOUR OWN SEATS. When it is set, this screener
# keeps a posting whose title matches it (or MGMT_TITLE) and drops the rest WITH A REPORTED COUNT.
# When it is empty, the older NON_PM behavior runs unchanged, so an install that has not declared
# its seats is never handed a stricter filter it did not ask for.
#
# ⚠️ THE DIRECTION OF FAILURE FLIPS with that setting, which is the whole reason the count prints.
# A negative list KEEPS a title phrasing nobody anticipated. A positive list DROPS it. For a
# discovery sweep the silent drop is worse, because the match never reaches your board and nothing
# tells you. A high "not a target seat" count means widen SEAT_TITLE, not that the market is quiet.
#
# Per-name guard, never a tuple import: a tuple import of one absent name raises for the WHOLE
# tuple, the mechanism that blanked every résumé guardrail in BUG-100.
try:
    SEAT_TITLE = getattr(_import_sibling("kit_config"), "SEAT_TITLE", "")
    SEAT_TITLE = SEAT_TITLE if isinstance(SEAT_TITLE, str) and SEAT_TITLE.strip() else ""
except Exception:
    SEAT_TITLE = ""


def classify_title(p, t, ic, mgmt):
    """Sort one POSTING into ic/mgmt, or return a drop reason string.

    Returning the reason rather than printing it is the point: the caller counts drops, which is the
    half of BUG-105 that kept it invisible.
    """
    if SEAT_TITLE:
        if re.search(MGMT_TITLE, t, re.I):
            mgmt.append(p)
            return None
        if re.search(SEAT_TITLE, t, re.I):
            ic.append(p)
            return None
        return "not a target seat"
    if re.search(NON_PM, t, re.I) and not re.search(r"product manager|product lead", t, re.I):
        return "non-PM title"
    (mgmt if re.search(MGMT_TITLE, t, re.I) else ic).append(p)
    return None


_NOT_A_COMPANY = re.compile(
    r"(candidate experience|company overview|^opportunities with\b|^careers?\b|"
    r"^job openings?\b|^open (roles|positions)\b|^learn more\b|^click here\b|"
    r"^apply (now|here)\b|^view all\b|^see all\b|^search jobs?\b)", re.I)


def is_company_shaped(company):
    """False when the `company` field is scraped page text rather than an employer name."""
    c = (company or "").strip()
    if len(c) < 2 or not re.search(r"[A-Za-z]", c):
        return False
    return not _NOT_A_COMPANY.search(c)


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
    # DURABLE STORE, ADDED TO `names` ONLY.
    #
    # ⛔ THE BLOB BELOW STAYS A FULL-TEXT READ, AND THAT IS DELIBERATE. It would be natural to move
    # every board reader onto the state store; doing it here would be a regression. `blobs` is
    # searched with `lc in txt`: the question it answers is "has this company been mentioned
    # ANYWHERE in this file", prose and reasons included, not "is it a row in a table". Swapping a
    # whole-file text search for the store's company keys would make dedup NARROWER, and a narrower
    # dedup re-surfaces a company that was already screened and ruled on. Widen `names`, leave the
    # text search alone.
    try:
        import state as _state
        for _rec in _state.from_source("company", "green-board"):
            _n = ((_rec.get("payload") or {}).get("name") or "").strip()
            if _n:
                names.add(_n.lower())
    except Exception:
        pass
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


# Three-letter canon keys that are common English function words, not companies. Without this the
# widened parser (comma/colon tail-harvest) would turn a reason-phrase word into a blocked key and
# wrongly hide any company whose name canonizes to it. Kept deliberately small: only pure noise words,
# never a plausible short brand (QZT, VBN, KRP, DWL, MFG stay in the pool of real 3-letter names).
STOP3 = {"all", "and", "not", "new", "the", "for", "was", "are", "its", "our", "out", "you",
         "has", "per", "pre", "non", "two", "via", "ice", "who", "why", "how", "inc", "llc",
         "ltd", "usa", "www", "com", "org"}


# ── PARSE ONCE PER FILE STATE ─────────────────────────────────────────────────────────────────
#
# 📊 Every reader of the blocked set comes through here, once per candidate, and each call re-read
# and re-parsed the whole list. On the maintainer's tree a profile put 54 of 61 seconds inside this
# one function: 664 calls in a single briefing, 232 million function calls and 22.8 million regex
# substitutions, to answer 664 questions about a file that never changed between them.
#
# ⛔ KEYED ON (path, mtime, size), NOT a bare lru_cache. The blocked list IS written inside a
# session when a screening run records a drop, and a cache blind to that would answer "not blocked"
# for a company blocked moments earlier. That turns a speedup into a screening defect, which is the
# one direction this file is not allowed to fail in.
#
# ⚖️ mtime+size rather than a content hash: hashing the file on every call would re-read the very
# bytes this exists to stop re-reading. A same-second write that preserves byte length is the known
# blind spot, and it is narrow enough to accept for a file only ever appended to.
_BLOCKED_KEYS_CACHE = {}


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
    # ── THE REGISTRY IS THE AUTHORITY WHEN IT EXISTS, AND ONLY THEN ──────────────────────────
    #
    # ⚖️ Every reader of the blocked set comes through this function: `check_dup.blocked_key_hit`,
    # `rank_criteria._BlockedText.__contains__`, `reconcile_findings`, and this module itself. So
    # this is the one place that has to change for all of them to stop guessing.
    #
    # 📊 WHAT CHANGES ONCE YOU SEED ONE. Parsing prose derives identity by guessing at text, and on
    # the install where it was measured that guessing returned 2,774 identities for 1,257 companies:
    # 328 keys built out of salary figures and 713 lowercase sentence fragments. Worse than the
    # noise, a company whose NAME appears inside a DIFFERENT company's blocked REASON reads as
    # blocked itself, so a good target vanishes from the pool with nothing printed. The registry
    # declares identity instead, and an EXACT lookup of `canon(name)` against declared keys and
    # aliases takes reasons out of the match surface entirely.
    #
    # ⛔ NOBODY GETS A BEHAVIOR CHANGE UNTIL THEY SEED A REGISTRY. `employers.available()` is False
    # with no `documents/employers.jsonl`, and this function then does exactly what it did before.
    #
    # ⛔ AN EXPLICIT `path` STILL PARSES THAT FILE. Tests and fixtures pass a path on purpose, and
    # silently redirecting them to the live registry would make a fixture measure production state.
    # Only the live, no-argument call is served from the registry.
    if path is None:
        try:
            _employers = _import_sibling("employers")
            if _employers.available():
                return _employers.blocked_keys()
        except Exception as e:                       # pragma: no cover - degraded path
            # Loud, and it falls back to the OLD behavior rather than to an empty set. An empty
            # blocked set silently passes every company, which is the direction that costs most.
            print(f"[!] employer registry unreadable ({e}); falling back to parsing the prose list",
                  file=sys.stderr)
    path = path or os.path.join(REPO, "documents/blocked-employers-list.md")
    # ⛔ realpath, because the raw path STRING is not a file identity. Two different strings can
    # name the same file, and caching under both would parse it twice for no gain.
    path = os.path.realpath(path)
    try:
        _st = os.stat(path)
        _stamp = (path, _st.st_mtime_ns, _st.st_ctime_ns, _st.st_size)
    except OSError:
        _stamp = None                      # missing file: fall through to the empty-set path below
    if _stamp is not None and _stamp in _BLOCKED_KEYS_CACHE:
        return _BLOCKED_KEYS_CACHE[_stamp]
    try:
        blocked_raw = open(path, encoding="utf-8", errors="ignore").read().lower()
    except Exception:
        return set()
    # ⬆️ WIDENED. The original read only a bullet's leading name plus its **bold** spans,
    # and the file writes blocked names in three more shapes that were all silently missed:
    #   - COMMA LIST as the head:      "- SomeCo, Otherco, Thirdco"
    #   - MIDDOT LIST, colon or not:   "- **Filter 2, defense:** Scale AI · C3.ai"
    #                                  "- SomeCo (13 of 16 SF) · Otherco (8 SF)"
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
            # ⬇️ FLOOR is len>=3, not >3. A `3 < len(k)` floor silently drops every three-letter
            # company from the blocked set, so a blocked three-letter name keeps surfacing in the
            # ranker's banked_topup even though it was blocked. Longer names are never affected,
            # which is why the bug hides. Three-letter names are a real class (QZT, VBN, 7x7, DWL,
            # MFG, KRP). STOP3 guards the handful of common function words that the comma/colon
            # tail-harvest would otherwise turn into keys that wrongly hide a real company (a false
            # BLOCK hides a good target, the costlier error).
            if 2 < len(k) <= 40 and k not in STOP3:
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
    if _stamp is not None:
        if len(_BLOCKED_KEYS_CACHE) > 8:
            _BLOCKED_KEYS_CACHE.clear()
        _BLOCKED_KEYS_CACHE[_stamp] = keys
    return keys


_ATS_TOKEN_RE = [
    re.compile(r"greenhouse\.io/(?:embed/job_app\?for=)?([A-Za-z0-9_.-]+)/jobs?/", re.I),
    re.compile(r"job-boards\.greenhouse\.io/([A-Za-z0-9_.-]+)/", re.I),
    re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)", re.I),
    re.compile(r"hiring\.cafe/jobs/(?:ashby|greenhouse|lever)-([A-Za-z0-9_.-]+?)-[0-9a-f]{8}", re.I),
    re.compile(r"jobs\.lever\.co/([A-Za-z0-9_.-]+)", re.I),
]


def _register_banked_identity(company, row):
    """Record the banked company in the state store, with its ATS token as an alias.

    ⚖️ WHY AT BANK TIME. A recorded alias is what lets `state.resolve()` collapse two spellings of
    one employer, and this is the one moment BOTH spellings are in hand: the display name the sweep
    captured and the ATS token sitting in the posting URL.

    📊 THE LEAK IT CLOSES. In the tree this shipped from, six already-contacted companies were
    sitting in the screening queue under variant spellings, and every one was a VARIANT rather than
    an exact miss: a domain-suffixed name against a bare one, a full legal name against a short one,
    a brand against an entity name. Exact-key matches: zero. One of them had already received a
    cold-boss email with a resume attached, three weeks before the board offered it back as fresh.

    ⚠️ WHAT THIS DOES NOT DO, stated so nobody reads more into it. It links the display name to the
    ATS token. It cannot invent the link to a spelling a HUMAN typed into a send log months earlier,
    because that string appears nowhere on the posting. Those still need a recorded ruling. This
    stops the NEXT generation of leaks; it does not retro-fix a spelling nobody wrote down.

    ⛔ FAILS OPEN, always. Identity bookkeeping must never take a sweep down: a store problem costs
    an alias, while a raise here costs the whole screening run.
    """
    try:
        # ⚠️ `date` is imported inside bank(), not at module scope, so this needs its own import.
        # Without it the NameError would be swallowed by the fail-open below and this function
        # would never register anything while looking like it worked. A fail-open that ALWAYS
        # fails is worse than no feature, because it reports success by staying quiet.
        from datetime import date as _date
        import state as _state
        url = ""
        for field in ("url", "link", "href", "posting_url"):
            if row.get(field):
                url = str(row[field])
                break
        token = ""
        for rx in _ATS_TOKEN_RE:
            m = rx.search(url)
            if m:
                token = m.group(1)
                break
        # Only register the token when it is a DIFFERENT spelling. A token equal to the canon of
        # the display name adds nothing and would grow the payload on every sweep.
        alias = token if (token and canon(token) and canon(token) != canon(company)) else None
        _state.register("company", company, alias=alias,
                        as_of=_date.today().isoformat(),
                        as_of_source="live:screen_sweep-bank")
    except Exception:
        pass


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
        _register_banked_identity(co, r)
    if dropped_blocked:
        print(f"\n   ⛔ {len(dropped_blocked)} name-variant(s) of BLOCKED companies caught by "
              f"normalization: {', '.join(dropped_blocked[:6])}")
    # ── BUG-098 (fixed 2026-08-09): THIS FILE HAS TWO WRITERS AND THIS ONE USED TO TRUNCATE. ──
    # `reconcile_findings._write_banked()` opens the SAME path in APPEND mode to promote SURVIVOR
    # rows. This function opened it `"w"`. So a sweep running after a reconcile on the same day
    # destroyed every survivor the reconcile had promoted, while the reconcile's `.reconciled`
    # sidecar still certified the run as consumed. The sidecar answered "was this run reconciled"
    # when the question that matters is "are its survivors still in the pool".
    #
    # ⚖️ THE FIX IS MERGE, NOT COORDINATION. Both writers have a legitimate claim on the day's file,
    # and a rule that says "run the reconcile last" is a rule a human has to remember, which is what
    # already failed. Nothing overwrites now, so the hazard is gone structurally, not by ordering.
    #
    # ⛔ FOREIGN CONTENT IS PRESERVED VERBATIM and this writer's block is delimited, so a re-run
    # replaces exactly its own output. Do NOT merge the two name lists into one: the writers grant
    # DIFFERENT things (this one, mechanical gates only; the reconcile, a screened SURVIVOR verdict)
    # and each block's prose is the provenance of the names under it.
    #
    # The markers are `>` lines on purpose: `rank_criteria.banked_topup()` skips lines starting with
    # `#`, `>`, `|` or `-`, so they are invisible to the reader without touching it. A bare HTML
    # comment line would NOT be skipped and would be split on '·' into a junk company name.
    BEGIN, END = "> <!-- screen_sweep:begin -->", "> <!-- screen_sweep:end -->"
    foreign, existing_keys = [], set()
    if os.path.exists(out):
        inside = False
        for line in open(out, encoding="utf-8", errors="ignore").read().splitlines():
            if line.strip() == BEGIN:
                inside = True
                continue
            if line.strip() == END:
                inside = False
                continue
            if inside:
                continue
            foreign.append(line)
            # Same parse rule as banked_topup(), so "already present" means present TO THE READER.
            if line.strip() and not line.lstrip().startswith(("#", ">", "|", "-")):
                for chunk in line.split("·"):
                    k = canon(chunk.strip().strip("*~ ").strip())
                    if k:
                        existing_keys.add(k)
        while foreign and not foreign[-1].strip():
            foreign.pop()

    fresh = [n for n in names if canon(n) not in existing_keys]
    block = [BEGIN,
             f"> Written by `screen_sweep.py --bank` from `{os.path.basename(src)}`.",
             "> Passed the MECHANICAL gates only (dedup, blocked-list, industry, title, comp floor).",
             "> **STILL OWED on every name here: remote verification, PE ownership, culture, boss.**",
             "> A name in this file means *worth screening*, never *worth sending*.", "",
             f"## Passes (mechanical sweep, {date.today().isoformat()})", ""]
    for i in range(0, len(fresh), 6):
        block.append(" · ".join(fresh[i:i + 6]) + " ·")
    block += ["", END]

    if foreign:
        lines = foreign + [""] + block
    else:
        lines = [f"# Banked candidates — {date.today().isoformat()}", ""] + block
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    carried = len(names) - len(fresh)
    print(f"\n🏦 banked {len(fresh)} companies → {os.path.relpath(out, REPO)}")
    if carried:
        print(f"   {carried} already in today's file (another writer banked them); not duplicated")
    if foreign:
        print(f"   {len(foreign)} line(s) from the other writer preserved (BUG-098: this used to truncate)")
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
    # BUG-105: the title filter had no counter, so a taxonomy that was wrong for its user
    # looked like a quiet market. Counted here and reported at the end of the run.
    seat_drops = {}
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
            why = classify_title(p, t, ic, mgmt)
            if why:
                seat_drops[why] = seat_drops.get(why, 0) + 1
                continue
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
    # ── BUG-105: SAY OUT LOUD WHAT THE TITLE FILTER THREW AWAY. ──────────────────────────────
    # This filter dropped 5 of 9 of a real user's target titles for weeks and reported success,
    # because it counted nothing. A seat taxonomy that is wrong for its user is indistinguishable
    # from a quiet market unless the run says which one it is.
    if seat_drops:
        mode = "SEAT_TITLE (your declared seats)" if SEAT_TITLE else "NON_PM (no seats declared)"
        total = sum(seat_drops.values())
        print(f"   🪑 {total} posting(s) dropped on TITLE, filter = {mode}")
        for why, n in sorted(seat_drops.items(), key=lambda kv: -kv[1]):
            print(f"      {n:4}  {why}")
        if SEAT_TITLE:
            print("      if that number looks high, widen SEAT_TITLE in scripts/kit_config.py "
                  "before concluding the market went quiet")
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
