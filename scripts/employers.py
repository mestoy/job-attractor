#!/usr/bin/env python3
"""employers.py — THE EMPLOYER ENTITY REGISTRY. One company, one row, one identity.

WHY THIS EXISTS. Without it, this pipeline has no employer ENTITY anywhere. Companies exist only as
prose inside `documents/blocked-employers-list.md`, and every consumer re-derives identity by
guessing at that text. On the install where this was first measured, parsing the prose returned
2,774 identities for 1,257 companies, including 328 keys built out of salary figures (`000145`,
`000customers`) and 713 lowercase sentence fragments (`acceptablewasnevertheissue`).

⛔ FOUR FIXES HAD ALREADY BEEN TRIED ON THE PARSER and each one tightened the guess rather than
removing the need to guess: length caps, reason-word filters, stop lists, and a proposed
strip-the-quoted-spans pass that was disproven because a real company name sits UNQUOTED inside
another company's reason. `reconcile_findings` carries a comment asking authors to keep prose out of
that file BECAUSE prose becomes match surface. That is discipline standing in for structure.

⚖️ THE STRUCTURE. Identity is DECLARED, never inferred:

    documents/employers.jsonl        this registry. status + identity. THE authority.
    documents/employer-notes.jsonl   append-only notes, keyed by entity
    documents/employer-review-queue.jsonl   candidates seen only in prose, parked, NOT blocking
    documents/blocked-employers-list.md     the prose list, read by humans

`is_blocked()` is an EXACT lookup of `canon(name)` against declared keys and aliases. No substring
test, no prose in the match surface. A company cannot be blocked by being mentioned in someone
else's reason, because reasons are no longer searched. The false-block class stops existing rather
than being defended against.

⛔ NOTHING IS EVER SILENTLY DROPPED. A candidate that cannot be resolved to an entity goes to the
review queue WITH its source line. A parked candidate does not block, and it is visible. The old
behavior had two silent outcomes (a junk key that hides a good company forever, or a dropped key
that quietly un-blocks one); this has none.

⚠️ OPTIONAL, AND OFF UNTIL YOU SEED IT. `available()` is False until `documents/employers.jsonl`
exists and holds rows, and every reader falls back to the prose parser while it is False. Nothing
about your install changes until you run `python3 scripts/seed_employers.py`.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)


def _import_sibling(modname):
    """Import a same-directory sibling module, immune to a STALE `sys.modules` entry.

    Same guard `screen_sweep._import_sibling` and `state._import_sibling` carry, and it is here for
    the same reason: Python caches an import by BARE NAME and never by path, so a copy of this file
    loaded from another directory can poison the shared name for every later importer in the
    process. A screening module resolving the wrong sibling can make a blocked-list lookup answer
    False for everything, and a blocked list that goes quiet reports success.
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


canon = _import_sibling("screen_sweep").canon  # one canon function, shared by every store

REGISTRY = os.path.join(REPO, "documents", "employers.jsonl")
NOTES = os.path.join(REPO, "documents", "employer-notes.jsonl")
QUEUE = os.path.join(REPO, "documents", "employer-review-queue.jsonl")

# Statuses an entity can hold. BLOCKING is the subset that suppresses a company from the pool.
BLOCKING = {"blocked"}
STATUSES = BLOCKING | {"cleared", "pending", "seen"}

_CACHE = {}


def _read(path):
    """Rows from a JSONL store, cached on (mtime_ns, ctime_ns, size).

    Same key shape as `screen_sweep.blocked_keys_from_list`, and for the same reason: these stores
    are appended to DURING a session, so a cache that ignored writes would answer a screening
    question with yesterday's answer. ctime is in the key because `cp -p` and `rsync -a` restore
    mtime after a same-length rewrite.
    """
    try:
        st = os.stat(path)
        stamp = (path, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
    except OSError:
        return ()
    hit = _CACHE.get(stamp)
    if hit is not None:
        return hit
    out = []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # ⛔ REPORTED, NEVER SKIPPED IN SILENCE. A malformed row in a screening store means
                # a company's status is unreadable, and treating that as "not blocked" is the
                # dangerous direction.
                print(f"[!] {os.path.basename(path)}:{line_no} is not valid JSON and was not read",
                      file=sys.stderr)
    out = tuple(out)
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[stamp] = out
    return out


# ── BUILD THE KEY INDEX ONCE PER FILE STATE ──────────────────────────────────────────────────
#
# 📊 `_read` already caches the ROWS, so the file was not being re-read. The alias fold was still
# rebuilt on every call: a profile of the session-start path counted 2,055 calls to this function
# for 1.5 seconds of pure re-indexing of rows it had already parsed.
#
# ⛔ KEYED ON THE IDENTITY OF `_read`'s CACHED TUPLE, not on a stat of its own and not on a bare
# lru_cache. `declare_blocked()` appends to the registry and then clears `_CACHE`, so the next
# `_read` returns a NEW tuple object, this `is` test misses, and the index rebuilds. That is the
# same read-after-write guarantee `declare_blocked()` documents, inherited rather than
# re-implemented, so there is no second invalidation rule that can drift from the first. Holding
# the tuple also pins it, so no later object can reuse its identity.
_REG_INDEX = None


def registry():
    """canon key -> entity row. Aliases resolve to the SAME row, so identity survives a rename."""
    global _REG_INDEX
    rows = _read(REGISTRY)
    if _REG_INDEX is not None and _REG_INDEX[0] is rows:
        return _REG_INDEX[1]
    by_key = {}
    for row in rows:
        k = row.get("key")
        if not k:
            continue
        by_key[k] = row
        for alias in row.get("aliases") or ():
            ak = canon(alias)
            # ⚠️ An alias never overwrites a declared entity. Two companies can legitimately share
            # a brand fragment (there are three unrelated companies called Boundless), and the row
            # that DECLARED the key outranks a row that merely lists it as an alias.
            if ak and ak not in by_key:
                by_key[ak] = row
    _REG_INDEX = (rows, by_key)
    return by_key


def blocked_keys():
    """Every canon key whose entity holds a blocking status. The screening authority."""
    return frozenset(k for k, row in registry().items() if row.get("status") in BLOCKING)


def is_blocked(name):
    """True when this company is DECLARED blocked. Exact identity, never a text search."""
    k = canon(name or "")
    if not k:
        return False
    row = registry().get(k)
    return bool(row and row.get("status") in BLOCKING)


def why(name):
    """The rows explaining a company's status: its registry entry plus every note attached."""
    k = canon(name or "")
    row = registry().get(k)
    if not row:
        return None
    notes = [n for n in _read(NOTES) if n.get("key") == (row.get("key") or k)]
    return {"entity": row, "notes": notes}


# ⛔ NEVER HAND-EDIT THE REGISTRY TO ADD AN ALIAS FOR AN UNMARKED RENAME. FIX THE PROSE.
# Reported from a partner install 2026-08-09, and it is doubly unsafe:
#   1. the registry is a DERIVED artifact, so a hand-added alias is ERASED by the next reseed, and
#   2. it has no name position in the source list, so `registry_equivalence.untraceable_blocked()`
#      reports it as a phantom block and step [28] goes RED.
# That is the gate working. A blocked key with no traceable origin has no defensible reason to be
# blocking anybody, and a hand alias for a rename the prose never announced is exactly that.
# ✅ THE FIX IS ALWAYS UPSTREAM: mark the rename in the blocked list itself, e.g.
# `- **NewName (now OldName)** ...` or `(formerly OldName)`, then reseed. The harvester derives the
# alias traceably and it survives every future reseed.

def declare_blocked(rows, path=None):
    """Append newly-blocked entities to the registry. Returns the number actually written.

    🔴 THE DEFECT THIS CLOSES, and it was LIVE and silent. `reconcile_findings.py` writes a DROP by
    APPENDING to `documents/blocked-employers-list.md`. Every reader of the blocked set comes
    through `screen_sweep.blocked_keys_from_list()`, which serves from THIS registry whenever it is
    available. So a company blocked mid-session did not become blocked: the prose row landed, the
    registry never heard about it, and the ranker went on offering the company until somebody
    re-ran `seed_employers.py`.
    📊 PROVEN by appending a test row to a live list and asking: `is_blocked()` answered **False**
    on a company that had just been written into the blocked file.

    ⚖️ WHY APPEND HERE RATHER THAN REBUILD. A full `seed_employers.py` pass takes seconds, which is
    too slow to hang off every reconcile, and the reconciler already knows exactly which company it
    just blocked.

    ⛔ THIS IS NOT A SECOND WRITER OF ONE FACT. `documents/blocked-employers-list.md` remains the
    source both writers derive from: the reconciler writes the prose row FIRST, this mirrors it into
    the registry, and the next full `seed_employers.py` re-derives the same entity from the same
    line. If the two ever disagree, the seeder's rebuild is the tiebreak, because it reads the
    source rather than remembering.

    ⚠️ IDEMPOTENT. A key already declared is skipped rather than duplicated, so re-running a
    reconcile cannot grow the file. `registry()` would survive a duplicate, but a store that grows
    on every retry is how a "harmless" append becomes a corruption.
    """
    path = path or REGISTRY
    try:
        existing = set(registry())
    except Exception:
        existing = set()
    out = []
    for r in rows:
        name = (r.get("company") or r.get("display") or "").strip()
        k = canon(name)
        if not k or k in existing:
            continue
        existing.add(k)
        out.append({"key": k, "display": name, "aliases": [], "status": "blocked",
                    "filter": r.get("filter"), "filter_label": r.get("filter_label"),
                    "ruled_on": r.get("ts", "")[:10] or None,
                    "source": r.get("source") or "reconcile:blocked-employers-list.md"})
    if not out:
        return 0
    with open(path, "a", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    # ⚠️ BELT AND BRACES, and labelled as such after a mutation proof deleted it and every test
    # stayed green. The read-after-write guarantee is carried by `_read`'s stat key
    # (path, mtime_ns, ctime_ns, size): an APPEND always changes size, so the cache misses without
    # help. This line would matter to a future writer that rewrites the file IN PLACE at the same
    # length, which is why it stays, but it is not what makes the declare visible today.
    _CACHE.clear()
    return len(out)


def available():
    """True when the registry exists and holds rows, so a caller can fall back while it is seeded.

    ⛔ THIS IS THE UPGRADE SWITCH. Every consumer asks this first and keeps its old prose-parsing
    behavior while it answers False, so an install with no registry file behaves exactly as it did
    before this module shipped.
    """
    return bool(_read(REGISTRY))


def main():
    if not available():
        print(f"registry not present or empty: {REGISTRY}")
        print("seed it with: python3 scripts/seed_employers.py")
        return 2
    reg = registry()
    blocked = blocked_keys()
    notes = _read(NOTES)
    queued = _read(QUEUE)
    print(f"entities   : {len({r['key'] for r in _read(REGISTRY)}):,} declared "
          f"({len(reg):,} lookup keys including aliases)")
    print(f"blocking   : {len(blocked):,}")
    print(f"notes      : {len(notes):,}")
    print(f"review q   : {len(queued):,}  (parked, NOT blocking, each with its source line)")
    if len(sys.argv) > 1 and sys.argv[1] not in ("--stats",):
        d = why(sys.argv[1])
        print()
        if not d:
            print(f"{sys.argv[1]!r}: no entity declared, so NOT blocked")
        else:
            e = d["entity"]
            print(f"{e['display']}  [{e['status']}]  filter={e.get('filter')}  "
                  f"ruled={e.get('ruled_on')}")
            for n in d["notes"][:10]:
                print(f"   · {n.get('kind','note')}: {(n.get('text') or '')[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
