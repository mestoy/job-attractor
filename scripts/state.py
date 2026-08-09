#!/usr/bin/env python3
"""state.py — the one reader and writer for durable facts, with a recency guarantee.

WHY THIS EXISTS: the owner asked for a single durable source of truth — current data by default,
and when two sets disagree, the newer one.

That question got asked because the pipeline handed its owner STALE data three times in one session,
in three different data classes, and each time a different ad-hoc recency rule picked the OLDER set:

  • the session handoff  — `sorted()[-1]` ranked `...-25-b.md` below the bare `...-25.md`, because
    `-` is 0x2D and `.` is 0x2E. Alphabetical sort chose the older file.
  • a contact's title    — the live profile page said one thing; the roster and the export both said
    something a year out of date. The export won, because it was the only thing any reader opened.
  • an approved shortlist — a hand-picked trio vs the ranker's board-derived trio. Board membership
    won, and it was the weaker set.

Two more from the days before: the network parser ranked exports by FILE MTIME, so touching a 2025
export would have beaten a 2026 one; and a phantom follow-up was two parsers disagreeing about one
file, with the banner you read first showing the wrong answer.

THE PATTERN IS NOT "COMPANIES ARE MESSY". It is that the same fact lives in several places, no place
records WHEN it was true, and every reader invents its own recency rule. Those rules were
alphabetical sort, file mtime, and board membership. All three picked the older set. So the fix is
not a better sort in three files — it is one resolver that every reader shares, fed by records that
carry their own date.

THE THREE GUARANTEES
--------------------
  1. SINGLE HOME.  Each fact has one authoritative store. Markdown becomes a generated view.
  2. PROVENANCE.   Every record carries when it was true and where that came from.
  3. RECENCY.      One resolver. `current()` returns the newest. Disagreements are DETECTABLE and
                   reported rather than silently resolved.

Guarantee 3 is the one that needed a design decision. The tempting version of `current()` picks a
winner and says nothing. That is exactly what the three failures above did — each of them
confidently returned an answer. So when two live sources disagree about one key, `conflicts()`
surfaces it; `current()` still answers, because a pipeline that halts on every disagreement is a
pipeline that gets bypassed, but the disagreement is never silent.

WHY as_of_source EXISTS, AND WHY IT IS NOT DECORATION
-----------------------------------------------------
`backfill_as_of.py` backfills dates from `git blame`. A git-derived date is a good guess — most
commits in a repo like this are frequent "backup" commits, so they sit close to real edit times — but
it is still a guess about when a line was WRITTEN, not when the fact was TRUE. Without a provenance
tag a backfilled date would outrank a human's verified live observation from the day before on
`as_of` alone, and the backfill would quietly overwrite the most trustworthy data in the repo with
the least trustworthy. So precedence breaks ties by SOURCE, and `git:` sits at the bottom.

THE RECENCY RULE, IN ONE PLACE
------------------------------
  1. Highest `as_of` wins.
  2. Tie → `as_of_source` precedence: live > authored > export > git.
  3. Still tied → later append order (append-only files make this total and stable).
  4. A record with no `as_of` is REFUSED ON WRITE. If one appears from a legacy path it sorts last
     AND `conflicts()` reports it, so it can never masquerade as current.

Rule 4 is deliberately belt-and-braces. `append()` cannot write an undated row, so in principle the
sort-last branch is unreachable — but "in principle unreachable" is how a broken hook stayed broken
for days, and a store is a thing other scripts will eventually append to by hand.

CRASH-SAFETY COMES FROM THE WRITE SHAPE, not from a commit step: one `open(path, "a")` per call, one
line per record, matching `record_finding.py`. A half-written line is dropped by the reader rather
than poisoning the store.

Usage:  scripts/state.py current <kind> <key>
        scripts/state.py history <kind> <key>
        scripts/state.py conflicts [--kind K] [--json]
        scripts/state.py stale <kind> --days N [--json]
        scripts/state.py stats
Exit:   0 = clean · 1 = conflicts or stale rows found · 2 = store unreadable · 3 = usage
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
STATE_DIR = os.path.join(REPO, "documents", "state")


def _import_sibling(modname):
    """Import a same-directory sibling module, immune to a STALE `sys.modules` entry.

    BUG (2026-08-09): Python's import system caches modules by BARE NAME and never by path. A
    process that loads a COPY of a sibling from a different directory (a test sandbox, a fixture)
    leaves `sys.modules[modname]` pointing at that copy, and every later plain `import modname`
    anywhere in the SAME process silently reuses the wrong object, even after the copy's directory
    has been deleted. Found when a screening module loaded from a sandbox rebound the shared names
    process-wide and a blocked-list lookup started answering False for everything.

    ⚖️ A blocked list that goes quiet is the worst failure this pipeline has, because it reports
    success. So: never trust a cached module by name alone. Check its `__file__` sits in THIS
    directory and reload from the correct path when it does not, which self-heals `sys.modules`
    for every other bare importer in the process rather than only this call site.
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


# One store per data class. Adding a fifth is a one-line change here plus a key normalizer below,
# which is the whole point of building this class-agnostic on day one rather than shipping a
# company-shaped thing and generalizing it under deadline later.
KINDS = ("company", "contact", "ruling", "session", "boss")

# Tie-break precedence when two records claim the SAME as_of. Higher wins.
# `live` beats `authored` because a page you actually opened outranks something typed from memory;
# `export` beats `git` because an export at least dates its own contents.
SOURCE_PRECEDENCE = {"live": 3, "authored": 2, "export": 1, "git": 0}
_SOURCE_RE = re.compile(r"^(live|authored|export|git)(?::(.+))?$")

# Fields that are structural, not payload. Everything else a caller passes is payload.
_META_FIELDS = ("kind", "key", "as_of", "as_of_source", "source_file", "source_line", "run")


class StateError(Exception):
    """A write that would have broken a guarantee. Always fatal to the caller, never swallowed."""


# ── keys ─────────────────────────────────────────────────────────────────────────────────────

def _canon_company(name):
    """Company keys reuse `screen_sweep.canon()` BY IMPORT, never by copy.

    A copied matcher drifts from its original the first time either side is fixed, and this
    particular matcher is hard-won: it is what stops "Acme, Inc." dodging a blocked-list entry for
    "Acme", and what collapsed three spellings of one health insurer that were taking two slots in a
    top-10 you pick three companies from.
    """
    try:
        return _import_sibling("screen_sweep").canon(name)
    except Exception:
        # Degrade to the same shape rather than to nothing. A weaker key still groups exact
        # duplicates; returning the raw string would make every variant its own key.
        return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _canon_person(name):
    """People are NOT companies, and must not share a normalizer.

    `screen_sweep.canon()` strips `co`, `group`, `holdings` and friends as legal-suffix noise. Run a
    person named "<Something> Group" through it and you get "" — an empty key that every other
    unlucky name also collapses into. So: lowercase, reduce to alphanumerics, and strip the trailing
    credential salad a profile export puts in display names ("Jane Doe MD").
    """
    n = str(name).lower()
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"[,;]\s*(m\.?d|ph\.?d|mba|pmp|cpa|esq|jr|sr|ii|iii|iv)\b\.?", " ", n)
    n = re.sub(r"\s+(m\.?d|ph\.?d|mba|pmp|cpa|esq)\b\.?", " ", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def _canon_slug(name):
    """Rulings and session records key on a stable slug the caller chooses."""
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def _canon_boss(raw):
    """Boss records key on the LinkedIn slug when known, else `<company>/<person>`.

    The slug is the strong key: the one identifier that survives a title change, a rename and a job
    move. Reuse `sync_contacted._slug_from_to` BY IMPORT for it — that parser already handles every
    shape the field arrives in (bare handle, `linkedin:handle`, full URL, trailing slash, query
    string), and hand-rolling the same join is a known source of duplicate rows.

    With no slug, fall back to company plus person so two people with the same name at two companies
    stay two records.
    """
    raw = str(raw or "").strip()
    if "/" in raw and not raw.lower().startswith(("linkedin", "http", "www")):
        co, _, person = raw.partition("/")
        return f"{_canon_company(co)}/{_canon_person(person)}"
    sys.path.insert(0, HERE)
    try:
        from sync_contacted import _slug_from_to
        slug = (_slug_from_to(raw) or "").strip().lower()
    except Exception:
        slug = ""
    return slug or _canon_person(raw)


_KEYERS = {
    "company": _canon_company,
    "contact": _canon_person,
    "ruling": _canon_slug,
    "session": _canon_slug,
    "boss": _canon_boss,
}


def key_for(kind, raw):
    """Normalize a raw name into this kind's canonical key. The ONLY way callers should build keys."""
    if kind not in KINDS:
        raise StateError(f"unknown kind {kind!r} (known: {', '.join(KINDS)})")
    return _KEYERS[kind](raw)


# ── dates ────────────────────────────────────────────────────────────────────────────────────

def _as_iso_date(value):
    """Coerce a date, datetime or string to an ISO date string, or None if it is not one.

    Deliberately strict about what it ACCEPTS and lenient about what it is GIVEN: a caller passing a
    datetime should not have to remember to format it, but a caller passing "sometime last week" must
    get None so `append()` can refuse the row rather than store a date nobody can compare.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(0)).isoformat()
    except ValueError:
        return None


def _source_family(as_of_source):
    """`live:https://…` → `live`. Unknown or malformed → None, which `append()` treats as fatal."""
    m = _SOURCE_RE.match(str(as_of_source or "").strip())
    return m.group(1) if m else None


# ── session handoffs: one ordering, two consumers ────────────────────────────────────────────
#
# A same-date handoff suffix is NOT chronologically sortable as text, and both previous attempts got
# it wrong in different directions:
#
#   • `sorted()[-1]` ranked `session-state-2026-07-25-b.md` BELOW the bare `...-25.md`, because "-"
#     is 0x2D and "." is 0x2E. Every session that trusted the banner opened on stale state.
#   • Sorting the suffix as text puts "evening" before "pm", so an evening handoff reads as older
#     than the afternoon one it supersedes. Real logs carry exactly that pair.
#
# So the suffix gets an explicit ordinal for the words that name a time of day, and a letter series
# (`-b`, `-c`) ranks after all of them, because a lettered block is the second or third session of a
# day that already had a bare handoff. mtime stays as the LAST tiebreak only, never as the primary
# key: ranking on mtime is what let a touched 2025 export outrank a 2026 one in the network parser,
# and the same trap is available here.
_SUFFIX_ORDER = {"": 0, "am": 1, "morning": 1, "pm": 2, "afternoon": 2,
                 "evening": 3, "eve": 3, "night": 4, "late": 4}
_HANDOFF_RE = re.compile(r"session-state-(\d{4}-\d{2}-\d{2})(.*)\.md$")


def handoff_rank(path):
    """Sort key for one session-state file: (date, time-of-day ordinal, suffix, mtime)."""
    base = os.path.basename(path)
    m = _HANDOFF_RE.search(base)
    if not m:
        return ("", -1, "", 0.0)
    day, suffix = m.group(1), m.group(2).strip("-").lower()
    if suffix in _SUFFIX_ORDER:
        ordinal = _SUFFIX_ORDER[suffix]
    elif len(suffix) == 1 and suffix.isalpha():
        ordinal = 10 + (ord(suffix) - ord("a"))
    else:
        ordinal = 5                      # unknown wording: after the named times, before letters
    try:
        mt = os.path.getmtime(path)
    except OSError:
        mt = 0.0
    return (day, ordinal, suffix, mt)


def handoffs(repo=None):
    """Every session-state file, OLDEST FIRST. The single ordering rule for this class."""
    import glob
    repo = repo or REPO
    return sorted(glob.glob(os.path.join(repo, "documents", "session-state-*.md")),
                  key=handoff_rank)


def newest_handoff(repo=None):
    """The current handoff, or None. What the session banner reads."""
    h = handoffs(repo)
    return h[-1] if h else None


# ── the store ────────────────────────────────────────────────────────────────────────────────

def store_path(kind):
    if kind not in KINDS:
        raise StateError(f"unknown kind {kind!r} (known: {', '.join(KINDS)})")
    return os.path.join(STATE_DIR, f"{kind}.jsonl")


def _read_raw(kind):
    """Every record in append order, with its line number. Malformed lines are SKIPPED, not fatal.

    A store one bad line can take down is a store that takes the pipeline down with it. The
    skipped-line count is surfaced by `stats()` so silent decay is still visible.
    """
    path = store_path(kind)
    rows, bad = [], 0
    if not os.path.exists(path):
        return rows, bad
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                bad += 1
                continue
            if not isinstance(rec, dict):
                bad += 1
                continue
            rec["_seq"] = i
            rows.append(rec)
    return rows, bad


def _sort_key(rec):
    """THE recency rule. Every reader in the kit funnels through this one function.

    Undated rows sort last because `""` is lower than any ISO date, which satisfies guarantee 4
    without a special case in the comparator.
    """
    as_of = rec.get("as_of") or ""
    prec = SOURCE_PRECEDENCE.get(_source_family(rec.get("as_of_source")), -1)
    return (as_of, prec, rec.get("_seq", 0))


def history(kind, key, raw_key=False):
    """Every record for one key, NEWEST FIRST."""
    k = key if raw_key else key_for(kind, key)
    rows, _ = _read_raw(kind)
    return sorted([r for r in rows if r.get("key") == k], key=_sort_key, reverse=True)


def current(kind, key, raw_key=False):
    """The newest record for one key, or None. The function the whole design exists to provide."""
    h = history(kind, key, raw_key=raw_key)
    return h[0] if h else None


def keys(kind):
    rows, _ = _read_raw(kind)
    return sorted({r.get("key") for r in rows if r.get("key")})


def from_source(kind, needle):
    """Newest record per key whose `source_file` contains `needle`. THE board reader.

    WHY THIS EXISTS. Guarantee 1 in this module's docstring promises markdown becomes a GENERATED
    VIEW. Shipping the extraction without moving any reader onto it is a half migration: the store
    fills up, and every parser goes on hand-reading the markdown with position-based heuristics.

    WHAT THAT COSTS, measured rather than asserted. A mature board file carries many header shapes,
    and a positional reader assumes one or two. Reading by header NAME finds substantially more
    companies than the positional reader does, and every one of the extras is a company the ranker
    could not see. Separately, a `re.match(r"^[A-Z0-9]", name)` guard rejects a lowercase brand
    outright, losing more. There were ZERO ghosts in the other direction: the positional reader never
    invented a company, it only lost them. Silent loss is the failure mode this store was built
    against.

    Reading through here inherits the header-driven extraction in the pipe-table extractor and the
    ONE recency rule in `_sort_key`, so a new column cannot shift a reader's indices and a stale row
    cannot outrank a fresh one.

    ⚠️ It answers "what does the store hold", NOT "is the store current". Those are separate
    questions and conflating them is how a reader silently serves stale data. The consistency check
    is where currency is asserted; re-run the extractor when it reports the store behind.

    ⛔ RECENCY IS PER FIELD, NOT PER RECORD, and that distinction is load-bearing. One company can
    appear in several tables of the same file with DIFFERENT COLUMNS — a sparse index table next to
    the rich scored ones. Taking the newest whole record then hands back a row with no remote,
    culture or ownership cell, and the reader vetoes it as unverified.

    That is not hypothetical: on the first cut of this function two live targets vanished from the
    ranker exactly that way, one of them with a confirmed hiring manager and a posted band.
    Replacing a rich row with a newer sparse one is the same silent loss as the positional reader
    this replaces, wearing better clothes.

    So payloads are LAYERED oldest to newest: every field takes its newest non-empty value, and a
    newer row that simply lacks a column cannot erase it. The returned record carries the newest
    row's own metadata plus `_merged_from`, the count of records folded in, so a caller can tell a
    single-source row from a composite one.
    """
    rows, _ = _read_raw(kind)
    hit = [r for r in rows if needle in str(r.get("source_file") or "")]
    merged = {}
    for r in sorted(hit, key=_sort_key):          # ascending, so later writes overlay earlier ones
        k = r.get("key")
        if not k:
            continue
        prev = merged.get(k)
        payload = dict((prev or {}).get("payload") or {})
        for field_name, value in (r.get("payload") or {}).items():
            if value not in (None, ""):           # an ABSENT or empty cell never erases a known one
                payload[field_name] = value
        rec = dict(r)
        rec["payload"] = payload
        rec["_merged_from"] = ((prev or {}).get("_merged_from") or 0) + 1
        merged[k] = rec
    return [merged[k] for k in sorted(merged)]


def board_companies(needle="green-board"):
    """Canonical company keys on the board, newest record each. Convenience over `from_source`."""
    return [r["key"] for r in from_source("company", needle)]


def append(kind, key, as_of=None, as_of_source=None, source_file=None,
           source_line=None, run=None, **payload):
    """Append one record. Refuses anything that would break a guarantee.

    REFUSES, rather than defaulting, on a missing `as_of`. Defaulting to today would be the single
    most damaging convenience this file could offer: it would stamp every legacy row with today's
    date, which is precisely the "guess that outranks the truth" failure the precedence rule was
    built to prevent, and it would do it invisibly.
    """
    if kind not in KINDS:
        raise StateError(f"unknown kind {kind!r} (known: {', '.join(KINDS)})")

    iso = _as_iso_date(as_of)
    if not iso:
        raise StateError(
            f"refusing to write {kind}/{key!r} with no usable as_of (got {as_of!r}). "
            "Every record must say when it was true — that is guarantee 2."
        )

    family = _source_family(as_of_source)
    if not family:
        raise StateError(
            f"refusing to write {kind}/{key!r} with as_of_source={as_of_source!r}. "
            "Must be one of: authored · live:<url> · export:<name> · git:<sha>"
        )

    k = key_for(kind, key)
    if not k:
        raise StateError(f"refusing to write {kind} record with an empty key (raw {key!r})")

    rec = {
        "kind": kind,
        "key": k,
        "as_of": iso,
        "as_of_source": str(as_of_source).strip(),
        "source_file": source_file or "",
        "source_line": source_line if source_line is not None else "",
        "run": run or os.environ.get("JOBSEARCH_RUN", ""),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "payload": payload,
    }

    path = store_path(kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# ── disagreement detection ───────────────────────────────────────────────────────────────────

def _comparable(v):
    """Normalize a payload value for comparison. Whitespace and case are not disagreements."""
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v).strip().lower()
    return v


def _disagreements(a, b):
    """Fields where BOTH records carry a value and the values differ.

    Compares only the OVERLAP on purpose. Two sources describing different attributes of the same
    company are complementary, not contradictory — flagging those would bury the real conflicts in
    noise, and a report nobody reads is the failure mode every check in this kit is written against.
    """
    pa, pb = a.get("payload") or {}, b.get("payload") or {}
    out = []
    for field in sorted(set(pa) & set(pb)):
        va, vb = pa.get(field), pb.get(field)
        if va in (None, "") or vb in (None, ""):
            continue
        if _comparable(va) != _comparable(vb):
            out.append((field, va, vb))
    return out


def conflicts(kind=None):
    """Keys where two or more live sources disagree, RANKED BY AGE GAP (widest first).

    Ranked by age gap because the gap is the best available proxy for harm: a 90-day-old row
    contradicting today's observation is a fact that has been quietly wrong for 90 days, while two
    rows from the same afternoon are usually a race, not a rot.

    Also reports UNDATED rows as their own conflict class. They cannot be ordered against anything,
    so shipping them silently would reintroduce guarantee 4's hole through the back door.
    """
    kinds = [kind] if kind else list(KINDS)
    out = []
    for k in kinds:
        if k not in KINDS:
            raise StateError(f"unknown kind {k!r}")
        rows, _ = _read_raw(k)
        by_key = {}
        for r in rows:
            by_key.setdefault(r.get("key"), []).append(r)

        for key, recs in by_key.items():
            undated = [r for r in recs if not r.get("as_of")]
            if undated:
                out.append({
                    "kind": k, "key": key, "type": "undated", "age_gap_days": None,
                    "detail": f"{len(undated)} record(s) carry no as_of and cannot be ordered",
                    "sources": sorted({r.get("source_file", "") for r in undated}),
                })

            # Newest record PER SOURCE FILE. Comparing every pair would flag a store's own history
            # as a conflict with itself, which it is not: an append-only store is SUPPOSED to hold
            # superseded rows.
            newest_per_source = {}
            for r in sorted(recs, key=_sort_key):
                newest_per_source[r.get("source_file", "")] = r
            live = list(newest_per_source.values())
            if len(live) < 2:
                continue

            found = []
            for i in range(len(live)):
                for j in range(i + 1, len(live)):
                    for field, va, vb in _disagreements(live[i], live[j]):
                        found.append({
                            "field": field,
                            "a": {"value": va, "as_of": live[i].get("as_of"),
                                  "source": live[i].get("source_file", ""),
                                  "as_of_source": live[i].get("as_of_source", "")},
                            "b": {"value": vb, "as_of": live[j].get("as_of"),
                                  "source": live[j].get("source_file", ""),
                                  "as_of_source": live[j].get("as_of_source", "")},
                        })
            if not found:
                continue

            dates = [r.get("as_of") for r in live if r.get("as_of")]
            gap = None
            if len(dates) >= 2:
                gap = (date.fromisoformat(max(dates)) - date.fromisoformat(min(dates))).days
            winner = sorted(live, key=_sort_key)[-1]
            out.append({
                "kind": k, "key": key, "type": "disagreement", "age_gap_days": gap,
                "fields": sorted({f["field"] for f in found}),
                "detail": found,
                "resolves_to": {"as_of": winner.get("as_of"),
                                "as_of_source": winner.get("as_of_source", ""),
                                "source": winner.get("source_file", "")},
            })

    out.sort(key=lambda c: (-(c.get("age_gap_days") or 0), c["kind"], c["key"]))
    return out


VETO_SOURCE = "documents/blocked-employers-list.md"


def veto_conflicts():
    """Companies where the blocked list and a live board disagree about whether to pursue.

    THE RULING THIS ENCODES: *"generally the newer is valid, but please prompt me to select using a
    picker."* So the resolver keeps its ordinary newest-wins behaviour and this function exists to
    make the disagreement PRESENTABLE, one row per decision, rather than resolved in silence. The
    rule is deliberately not "blocked always wins": a newer record is usually the better one, and the
    exceptions are worth your eyes rather than a policy.

    ⛔ A CALLER MUST NOT ACT ON THE DEFAULT WITHOUT ASKING. Newest-wins is the right prior, not the
    decision, and the live conflicts that prompted this are the reason: every one resolved to
    "pursue" on the strength of queue cards that the queue's OWN banner calls unreliable, because the
    restock agent that wrote them ran with an incomplete dedup list. Most of those cards were
    re-treads. A rule that auto-applied the newer record there would have re-surfaced companies
    already ruled out.
    """
    out = []
    for c in conflicts("company"):
        if c.get("type") != "disagreement":
            continue
        sources = set()
        for d in c.get("detail", []):
            sources.add(d["a"].get("source", ""))
            sources.add(d["b"].get("source", ""))
        if VETO_SOURCE not in sources:
            continue
        blocked_side = next((d["a"] if d["a"].get("source") == VETO_SOURCE else d["b"])
                            for d in c["detail"])
        other_side = next((d["b"] if d["a"].get("source") == VETO_SOURCE else d["a"])
                          for d in c["detail"])
        rec = current("company", c["key"], raw_key=True) or {}
        # The display name lives on whichever record happened to carry one. A ruling appended by
        # `observe` sets a disposition, not a name, so the newest record is often nameless and a bare
        # canon key would be what a human is asked to decide on. Walk back through history for the
        # first real name rather than showing the key.
        display = (rec.get("payload") or {}).get("name")
        if not display:
            for h in history("company", c["key"], raw_key=True):
                n = (h.get("payload") or {}).get("name")
                if n:
                    display = n
                    break
        out.append({
            "key": c["key"],
            "name": display or c["key"],
            "age_gap_days": c.get("age_gap_days"),
            "blocked": {"value": blocked_side.get("value"), "as_of": blocked_side.get("as_of")},
            "other": {"value": other_side.get("value"), "as_of": other_side.get("as_of"),
                      "source": other_side.get("source", "")},
            "default_resolution": (rec.get("payload") or {}).get("disposition"),
            "default_as_of": rec.get("as_of"),
        })
    out.sort(key=lambda r: -(r["age_gap_days"] or 0))
    return out


def stale(kind, days, today=None):
    """CURRENT records older than N days, oldest first — the input to the age labels.

    Scopes to current records on purpose. An append-only store keeps superseded rows forever, and
    every one of them is by definition old; reporting those would make the staleness number grow with
    write volume instead of with actual staleness.
    """
    today = today or date.today()
    out = []
    for key in keys(kind):
        rec = current(kind, key, raw_key=True)
        if not rec or not rec.get("as_of"):
            continue
        age = (today - date.fromisoformat(rec["as_of"])).days
        if age >= days:
            out.append({"kind": kind, "key": key, "as_of": rec["as_of"], "age_days": age,
                        "as_of_source": rec.get("as_of_source", ""),
                        "source_file": rec.get("source_file", "")})
    out.sort(key=lambda r: -r["age_days"])
    return out


def stats(kind=None):
    """Row, key, undated and unreadable counts per store. Used by the CLI and the sweep step."""
    kinds = [kind] if kind else list(KINDS)
    out = {}
    for k in kinds:
        rows, bad = _read_raw(k)
        out[k] = {
            "rows": len(rows),
            "keys": len({r.get("key") for r in rows if r.get("key")}),
            "undated": sum(1 for r in rows if not r.get("as_of")),
            "unreadable_lines": bad,
            "by_source": _count_sources(rows),
            "path": os.path.relpath(store_path(k), REPO),
            "exists": os.path.exists(store_path(k)),
        }
    return out


def _count_sources(rows):
    counts = {}
    for r in rows:
        fam = _source_family(r.get("as_of_source")) or "invalid"
        counts[fam] = counts.get(fam, 0) + 1
    return dict(sorted(counts.items()))


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────

def _fmt_rec(rec):
    """Render one record for `state.py current|history`.

    ⛔ BUG-101 (reported by a partner install 2026-08-06, FIXED 2026-08-09). This line read
    `rec['source_line'] if rec.get('source_line') != '' else ''` and crashed with
    `KeyError: 'source_line'` on any record written WITHOUT that key, which is every row
    `boss_registry.py` used to write. The guard looks like it handles the missing case and does the
    opposite: `.get()` returns `None` when the key is absent, `None != ''` is True, so the truthy
    branch hard-indexes the key that is not there.

    ⚠️ IT WAS REPORTED AS ALREADY FIXED AND IT WAS NOT. The partner's patch notes marked it retired
    on the strength of an upstream fix that never landed, and the local patch was deleted on that
    basis. Reproduced in three trees on 2026-08-09. Do not retire a patch on a claim that a fix
    shipped; run the crashing path against the tree that is supposed to carry it.
    """
    p = rec.get("payload") or {}
    bits = " · ".join(f"{a}={b!r}" for a, b in list(p.items())[:6])
    line = rec.get("source_line")
    return (f"{rec.get('as_of')}  [{rec.get('as_of_source')}]  {rec.get('source_file') or '—'}"
            f"{':' + str(line) if line not in (None, '') else ''}\n      {bits}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip().split("Usage:")[-1].strip())
        return 3
    cmd = argv[0]
    as_json = "--json" in argv
    rest = [a for a in argv[1:] if not a.startswith("--")]

    def _opt_int(flag, default=None):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv):
                try:
                    return int(argv[i + 1])
                except ValueError:
                    pass
            print(f"usage: state.py {cmd} ... {flag} N", file=sys.stderr)
            sys.exit(3)
        return default

    try:
        if cmd in ("current", "history"):
            if len(rest) < 2:
                print(f"usage: state.py {cmd} <kind> <key>", file=sys.stderr)
                return 3
            kind, key = rest[0], " ".join(rest[1:])
            recs = history(kind, key)
            if cmd == "current":
                recs = recs[:1]
            if as_json:
                print(json.dumps(recs, ensure_ascii=False, indent=2))
                return 0 if recs else 1
            if not recs:
                print(f"⚪ no {kind} record for {key!r} (key: {key_for(kind, key)})")
                return 1
            print(f"{kind}/{key_for(kind, key)} — {len(recs)} record(s), newest first:")
            for r in recs:
                print(f"  • {_fmt_rec(r)}")
            return 0

        if cmd == "conflicts":
            kind = None
            if "--kind" in argv:
                i = argv.index("--kind")
                kind = argv[i + 1] if i + 1 < len(argv) else None
            cs = conflicts(kind)
            if as_json:
                print(json.dumps(cs, ensure_ascii=False, indent=2))
                return 1 if cs else 0
            if not cs:
                print("✅ no conflicts — every key resolves from a single agreeing set")
                return 0
            print(f"🟠 {len(cs)} conflict(s), widest age gap first:")
            for c in cs:
                gap = f"{c['age_gap_days']}d apart" if c.get("age_gap_days") is not None else "undated"
                print(f"  • {c['kind']}/{c['key']} ({gap}) — {c['type']}")
                if c["type"] == "undated":
                    print(f"      {c['detail']}")
                    continue
                for d in c["detail"][:3]:
                    print(f"      {d['field']}: {d['a']['value']!r} ({d['a']['as_of']}, "
                          f"{d['a']['as_of_source']}) vs {d['b']['value']!r} "
                          f"({d['b']['as_of']}, {d['b']['as_of_source']})")
                print(f"      resolves to: {c['resolves_to']['as_of']} "
                      f"[{c['resolves_to']['as_of_source']}]")
            return 1

        if cmd == "stale":
            if not rest:
                print("usage: state.py stale <kind> --days N", file=sys.stderr)
                return 3
            days = _opt_int("--days", 30)
            rows = stale(rest[0], days)
            if as_json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
                return 1 if rows else 0
            if not rows:
                print(f"✅ no {rest[0]} record is {days}+ days old")
                return 0
            print(f"🟠 {len(rows)} {rest[0]} record(s) {days}+ days old, oldest first:")
            for r in rows[:25]:
                print(f"  • {r['key']:<32} {r['as_of']}  ({r['age_days']}d)  "
                      f"[{r['as_of_source']}]")
            if len(rows) > 25:
                print(f"  … and {len(rows) - 25} more")
            return 1

        if cmd == "observe":
            # The write path for a fact seen on a live page. This is the ONLY way a `live:` record
            # enters a store, and it exists because the alternative is hand-patching a contact's
            # title into the roster — a file that regenerates from the export and would silently
            # revert the edit on the next parse.
            if len(rest) < 2:
                print("usage: state.py observe <kind> <key> --as-of DATE --source live:<url> "
                      "[--from FILE] [--set field=value ...]", file=sys.stderr)
                return 3
            kind, key = rest[0], rest[1]
            def _val(flag, default=None):
                if flag in argv:
                    i = argv.index(flag)
                    if i + 1 < len(argv):
                        return argv[i + 1]
                return default
            fields = {}
            for i, a in enumerate(argv):
                if a == "--set" and i + 1 < len(argv) and "=" in argv[i + 1]:
                    k, v = argv[i + 1].split("=", 1)
                    fields[k.strip()] = v.strip()
            rec = append(kind, key, as_of=_val("--as-of"), as_of_source=_val("--source"),
                         source_file=_val("--from", ""), run="observe", **fields)
            print(f"✅ recorded {kind}/{rec['key']} as of {rec['as_of']} [{rec['as_of_source']}]")
            for k, v in (rec["payload"] or {}).items():
                print(f"     {k}={v!r}")
            return 0

        if cmd == "veto-conflicts":
            vc = veto_conflicts()
            if as_json:
                print(json.dumps(vc, ensure_ascii=False, indent=2))
                return 1 if vc else 0
            if not vc:
                print("✅ no veto conflict — no blocked company is contradicted by a live board")
                return 0
            print(f"🟠 {len(vc)} veto conflict(s). Default is NEWEST-WINS, but the standing ruling "
                  f"is that each one gets a PICKER before anything acts on it:")
            for v in vc:
                print(f"  • {v['name']:<22} blocked {v['blocked']['as_of']} "
                      f"({v['blocked']['value']}) vs {os.path.basename(v['other']['source'])} "
                      f"{v['other']['as_of']} ({v['other']['value']}) "
                      f"→ default: {v['default_resolution']}")
            return 1

        if cmd == "stats":
            s = stats(rest[0] if rest else None)
            if as_json:
                print(json.dumps(s, ensure_ascii=False, indent=2))
                return 0
            for k, v in s.items():
                mark = "✅" if v["exists"] else "⚪"
                print(f"{mark} {k:<8} {v['rows']:>6} rows · {v['keys']:>5} keys · "
                      f"{v['undated']} undated · {v['unreadable_lines']} unreadable")
                if v["by_source"]:
                    print(f"   provenance: " +
                          " · ".join(f"{a}={b}" for a, b in v["by_source"].items()))
            return 0

    except StateError as e:
        print(f"🔴 {e}", file=sys.stderr)
        return 2

    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())


# Per-process caches for the identity layer. `resolve()` is called from inside ranking
# loops, and an uncached shape re-reads every row in the store per membership test.
_ALIAS_INDEX = {}
_KEY_SET = {}


def _known_keys(kind):
    """Cached set of every key present in one store. Same per-process caching bargain as the index.

    Cached because `resolve()` is called from inside ranking loops and the uncached shape re-read all
    2,065 company rows per membership test. `done_set()` alone tests ~150 companies against a pool of
    several hundred board rows, so an uncached read turns a ranker run into six figures of JSON
    parsing for an answer that cannot change mid-run.
    """
    if kind not in _KEY_SET:
        try:
            rows, _ = _read_raw(kind)
            _KEY_SET[kind] = {r.get("key") for r in rows if r.get("key")}
        except Exception:
            _KEY_SET[kind] = set()
    return _KEY_SET[kind]


def _alias_index(kind):
    """{normalized alias → canonical key} for one kind, built from rows' own `payload.aliases`.

    Cached per process because it is a full store scan (2,065 company rows) and `resolve()` is called
    inside ranking loops. The cache is a correctness tradeoff stated plainly: a long-lived process
    that appends an alias and then resolves it will not see the new alias. Every current caller is a
    one-shot script, and `register()` below busts the entry it writes into, so the exposure is a
    reader that also writes through some other path. Call `_alias_index.cache_clear` equivalent by
    deleting the kind from `_ALIAS_INDEX` if you ever need to force a rebuild.

    Tolerates rows with NO aliases, which today is all 2,065 of them. An index over an unbackfilled
    store is simply empty, and an empty index makes `resolve()` behave exactly like `key_for()`, which
    is the pre-existing behaviour. That is the required degradation: this must never be a new way for
    a read to fail.
    """
    if kind in _ALIAS_INDEX:
        return _ALIAS_INDEX[kind]
    index = {}
    try:
        rows, _ = _read_raw(kind)
        for r in sorted(rows, key=_sort_key):      # ascending, so a newer row's claim overlays older
            k = r.get("key")
            if not k:
                continue
            aliases = (r.get("payload") or {}).get("aliases")
            if isinstance(aliases, str):
                aliases = [a for a in re.split(r"\s*[|;]\s*", aliases) if a.strip()]
            if not isinstance(aliases, (list, tuple, set)):
                continue
            for alias in aliases:
                ak = key_for(kind, alias)
                if ak and ak != k:
                    index[ak] = k
    except Exception:
        index = {}                                  # a broken store degrades to key_for(), not to a raise
    _ALIAS_INDEX[kind] = index
    return index


def resolve(kind, raw):
    """The canonical key for a raw name, or None when the store has never heard of it.

    Returns None rather than the normalized key for an unknown name ON PURPOSE. `key_for()` always
    answers, which is right for WRITING (you need a key before the row exists) and wrong for
    COMPARING: two unknown companies both get a key, both keys are non-empty, and a caller that
    treats "key_for returned something" as "the store knows this" will happily compare two guesses.
    `resolve()` answering None is how a caller can tell the difference.
    """
    k = key_for(kind, raw)
    if not k:
        return None
    if k in _known_keys(kind):
        return k
    return _alias_index(kind).get(k)


def register(kind, name, alias=None, as_of=None, as_of_source=None, **fields):
    """Record an entity's literal name and merge an alias into its alias set. Wraps `append()`.

    THE MERGE IS THE POINT. Aliases UNION with whatever `current()` already holds, so registering the
    same company twice with two different spellings ends with both on file. An overwrite would make
    the store lose an alias every time a second source touched a company, which is the same silent
    loss the store was built to stop.

    Passes through `append()`'s refusals rather than working around them: no `as_of`, no row. The
    defaults here are for the LIVE case, a caller registering something it just saw, so the
    provenance is `live:register` (family `live`, top of SOURCE_PRECEDENCE per `_source_family`). A
    backfill must pass its own `as_of`/`as_of_source`, because stamping a git-derived fact as `live`
    today is exactly the "guess that outranks the truth" this module's docstring is about.
    """
    literal = str(name or "").strip()
    if not literal:
        raise StateError(f"refusing to register a {kind} with no name (got {name!r})")

    existing = current(kind, literal) or {}
    merged = list((existing.get("payload") or {}).get("aliases") or [])
    if isinstance(merged, str):
        merged = [a for a in re.split(r"\s*[|;]\s*", merged) if a.strip()]

    canonical = key_for(kind, literal)
    for candidate in (alias, literal):
        c = str(candidate or "").strip()
        if not c:
            continue
        if c not in merged:
            merged.append(c)

    payload = dict(fields)
    payload["name"] = (existing.get("payload") or {}).get("name") or literal
    payload["aliases"] = merged

    rec = append(kind, literal,
                 as_of=as_of or date.today().isoformat(),
                 as_of_source=as_of_source or "live:register",
                 **payload)

    # Bust the caches for this kind so a register-then-resolve in one process sees the new row. A
    # stale cache here would make `register()` look like it silently did nothing, which is the
    # hardest class of bug to notice from a call site.
    if kind in _KEY_SET:
        _KEY_SET[kind].add(canonical)
    idx = _ALIAS_INDEX.get(kind)
    if idx is not None:
        for a in merged:
            ak = key_for(kind, a)
            if ak and ak != canonical:
                idx[ak] = canonical
    return rec
