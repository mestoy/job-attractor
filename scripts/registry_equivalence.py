#!/usr/bin/env python3
"""registry_equivalence.py — is `documents/employers.jsonl` fit to be the screening authority?

⛔ RUN THIS AFTER `seed_employers.py` AND BEFORE TRUSTING THE REGISTRY. It is the safety net that
makes the migration checkable rather than hopeful: it proves the registry is readable, non-empty,
and that every key it blocks traces back to a real NAME POSITION in the prose list. Until you seed a
registry, the whole pipeline keeps parsing prose and this script simply reports that there is
nothing to check.

⚖️ TWO STORES, SPLIT AUTHORITY, NEITHER ABSORBS THE OTHER:
  · `employers.jsonl` owns identity, status and the filter number.
  · `documents/state/company.jsonl` owns history and provenance.

Because the authority is split, DIVERGENCE BETWEEN THEM IS EXPECTED. It is reported and never
fatal; a check enforcing a rule nobody holds is how a red line gets trained out of a reader. What is
load-bearing is that the registry, once seeded, is the SOLE screening authority, so there is no
second opinion if it is unfit. The invariants below are about exactly that.

⛔ A COUNT THAT MATCHES IS NOT A PROOF, which is why `compare()` reports SET AGAINST SET and names
every difference in BOTH directions. Two sets of the same size can differ by a swap. Reporting the
size would be measuring a proxy instead of the thing, inside a check written to keep a store honest.
The divergence it prints is the reconcile worklist.

── 🔴 THE TRAP THIS EXISTS TO CATCH, found the hour it was written ─────────────────────────────
`state/company.jsonl` is an APPEND-ONLY EVENT LOG. On the install measured, 4,045 events over 1,972
companies. Reducing it with the obvious rule, LAST ROW WINS, returned 17 blocked companies. The
registry held 1,315.

That is not the store being empty. It is the reducer being wrong. A backfill run wrote
`payload.disposition = "blocked"` for 1,883 events; a later identity run wrote a SECOND event per
company carrying names and provenance and NO disposition at all. Row-level last-write-wins reads
that silence as a retraction.

⚖️ **A LATER EVENT THAT DOES NOT MENTION A FIELD HAS NOT RETRACTED IT.** The reducer is
last-write-wins PER FIELD, and with that rule the same log returned 1,287 blocked.

⛔ THE COST OF GETTING THIS WRONG IS THE WHOLE POINT OF THE GATE. Anyone folding that store with the
obvious reducer would have pointed the loader at a blocked set of 17, and roughly 1,300 declined
employers would have walked straight back into the ranked pool with nothing printed. That is silent
admission at the largest scale this pipeline can produce, and it would have looked like a successful
migration.

⚠️ IT ALSO CAUGHT THE AUTHOR. The first measurement taken here reported "state holds only 17 blocked
companies, the store cannot serve", a confident, wrong conclusion about the DATA that was really a
defect in five lines of throwaway reducer. It was caught by checking one company's event history
before reporting. Nothing about the first number looked suspicious.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)


def _import_sibling(modname):
    """Import a same-directory sibling module, immune to a STALE `sys.modules` entry.

    The same guard `screen_sweep._import_sibling` carries. Python caches an import by BARE NAME and
    never by path, so a copy of a module loaded from elsewhere can poison the shared name for every
    later importer in the process. A check that silently graded the WRONG registry would be worse
    than no check.
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


STATE = os.path.join(REPO, "documents", "state", "company.jsonl")
SRC = os.path.join(REPO, "documents", "blocked-employers-list.md")

# Values that mean "this event said nothing about that field", never "unset it". An explicit
# retraction, if the schema ever grows one, must be a VALUE and must not be spelled like silence.
EMPTY = (None, "", [], {})


def reduce_events(path=None, kind="company"):
    """key -> merged payload, LAST WRITE WINS PER FIELD, ordered by recorded_at.

    ⛔ PER FIELD, and the docstring at the top of this module is the receipt for why. Row-level
    last-write-wins turns a later event that merely omits `disposition` into a retraction of it, and
    an identity backfill produces thousands of such events.
    """
    path = path or STATE
    rows = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue          # a corrupt line is skipped, never fatal
                if r.get("kind") == kind and r.get("key"):
                    rows.append(r)
    except OSError:
        return {}
    # ⚠️ SORT BY recorded_at, NOT by file order. Append-only is not the same as chronological once
    # a backfill has run: a July `as_of` can be appended after an August one.
    rows.sort(key=lambda r: (r.get("recorded_at") or "", r.get("source_line") or 0))
    merged = {}
    for r in rows:
        cur = merged.setdefault(r["key"], {})
        for f, v in (r.get("payload") or {}).items():
            if v not in EMPTY:
                cur[f] = v
    return merged


def state_blocked(path=None):
    """The blocked set as `state/company.jsonl` would answer it."""
    return frozenset(k for k, p in reduce_events(path).items()
                     if p.get("disposition") == "blocked")


def registry_blocked():
    """The blocked set the ranker reads once a registry exists. The thing being graded."""
    try:
        employers = _import_sibling("employers")
        if employers.available():
            return frozenset(employers.blocked_keys())
    except Exception as e:                       # pragma: no cover - degraded path
        print(f"[!] registry unreadable ({e})", file=sys.stderr)
    return frozenset()


def compare(path=None):
    s, r = state_blocked(path), registry_blocked()
    return {"state": s, "registry": r, "agree": s & r,
            "only_state": sorted(s - r), "only_registry": sorted(r - s),
            "equivalent": s == r and bool(r)}


# ── THE SPLIT'S INVARIANTS ───────────────────────────────────────────────────────────────────────
#
# ⚖️ Neither store absorbs the other, so divergence between them is EXPECTED and allowed, and
# calling it a failure would be a check enforcing a rule nobody holds.
#
# ⛔ WHAT IS LOAD-BEARING is that a seeded registry is the SOLE screening authority, so the
# invariants are about the registry being fit to hold that job:
#
#   1. READABLE AND NON-EMPTY. An unreadable registry means every company reads as unblocked, which
#      is the worst direction this pipeline can fail in. Empty is not a pass.
#   2. EVERY BLOCKED KEY TRACES TO A NAME POSITION in the source list. A key that traces to nothing
#      is either parser debris or a fused alias, and both are how a real company goes quietly
#      unblocked.
#   3. STATE'S DISPOSITION IS NOT SCREENING AUTHORITY. The divergence is REPORTED so it stays
#      visible, and it never drives the exit code.
NAME_POSITION_MAX_UNTRACEABLE = 0


def untraceable_blocked():
    """Registry blocked keys that trace to NO name position in the source list.

    ⛔ NOT A COUNT OF JUNK, a count of keys whose ORIGIN cannot be shown. That is the property that
    matters: a fused `alphaalphawebservices` key traced to a name position too, and was still wrong,
    but a key that traces to NOTHING has no defensible reason to be blocking anybody.
    """
    try:
        raw = open(SRC, encoding="utf-8", errors="ignore").read().split("\n")
    except OSError as e:                         # pragma: no cover - degraded path
        print(f"[!] could not read the source list ({e})", file=sys.stderr)
        return []

    # ⛔ NO EXCEPTION IS CAUGHT BELOW THIS LINE, AND THAT IS THE POINT (2026-08-09).
    #
    # This whole body used to sit inside `except Exception: return []`. Returning an EMPTY list on
    # any failure means "zero untraceable keys", so `invariants()` PASSED UNCONDITIONALLY. Any bug
    # in the harvest, a `re.error`, an AttributeError from a typo, a syntax error in seed_employers,
    # silently converted the strongest claim this gate makes into a permanent green light, with one
    # stderr line as the only evidence.
    #
    # ⚖️ A SILENTLY GREEN GATE IS WORSE THAN A RED ONE. A red gate stops you; a green one certifies
    # a screening authority nobody checked. Only the file read above is a legitimate degradation
    # (no source list yet is a real state on a fresh install). Everything below is this kit's own
    # code, and this kit's code failing must be loud.
    se = _import_sibling("seed_employers")
    canon = _import_sibling("screen_sweep").canon
    namepos = set()
    for line in raw:
        t = line.strip()
        if not t.startswith(("-", "*", "|")):
            continue
        cells = [c.strip() for c in t.strip("|").split("|")] if t.startswith("|") else [t]
        # ⚠️ THE SAME bold_line FLAG THE SEEDER USES. Without it this reader would treat a bold
        # LABEL as a name position, so a label-derived key would trace to "a name position" and
        # the invariant would pass on a key the seeder no longer produces. A check measured
        # against a wider surface than the thing it checks is the proxy defect again.
        names = se._head_names(cells[0], bold_line=cells[0].startswith("**"))
        for nm in names:
            k = canon(nm)
            if k:
                namepos.add(k)
            for a in se.alias_parts(nm)[0]:
                ak = canon(a)
                if ak:
                    namepos.add(ak)
        # ── RENAME ALIASES, in EXACT lockstep with what the seeder can actually produce ───────
        # Single-name lines only, KEPT captures only. Parked captures and every capture on a
        # multi-entity line are excluded, because the seeder never aliases those either. A gate
        # that harvests MORE than the seeder produces would wave through keys the seeder cannot
        # justify. ⚖️ Accepted: namepos is a flat set of canon strings, not (key, line) pairs, so
        # it proves a string appeared as a name position SOMEWHERE. That is why the marker set is
        # kept as narrow as the evidence supports.
        if len(names) == 1:
            own = {canon(names[0])} | {canon(a) for a in se.alias_parts(names[0])[0]}
            for a in se.rename_aliases(line, own)[0]:
                ak = canon(a)
                if ak:
                    namepos.add(ak)
    return sorted(registry_blocked() - namepos)


def invariants(path=None):
    """(ok, findings). The split's rules, which are about the REGISTRY being fit to be authority."""
    r = registry_blocked()
    findings = []
    if not r:
        findings.append(("🔴", "the registry is unreadable or empty, so every company reads as "
                               "UNBLOCKED, the worst direction this can fail in"))
    untr = untraceable_blocked()
    if len(untr) > NAME_POSITION_MAX_UNTRACEABLE:
        findings.append(("🔴", f"{len(untr)} blocked key(s) trace to no name position in the source "
                               f"list: {', '.join(untr[:8])}"))
    return (not findings), findings


def main():
    employers = _import_sibling("employers")
    if not employers.available():
        # ⚪ NOT A FAILURE. No registry means the prose parser is still the authority, which is the
        # supported default. Grading a store that does not exist would train a red mark into noise.
        print("⚪ no employer registry yet, so the prose list is still the screening authority.")
        print("   Seed one with: python3 scripts/seed_employers.py --dry-run")
        return 0
    ok, findings = invariants()
    c = compare()
    print("── the split: employers.jsonl owns STATUS, state/company.jsonl owns HISTORY ──")
    print("")
    for mark, msg in findings:
        print(f"   {mark} {msg}")
    if ok:
        print(f"   ✅ registry readable, {len(c['registry']):,} blocked, "
              f"0 untraceable, fit to be the screening authority")
    print("")
    # ⚪ INFORMATIONAL FROM HERE DOWN. Under the split these two stores are ALLOWED to differ, so
    # this is a visibility report, not a verdict. It stays because the divergence is the reconcile
    # worklist, and a worklist nobody can see is a worklist nobody works.
    print("   ⚪ divergence from state/company.jsonl (expected under the split, not a failure)")
    print(f"        state blocked {len(c['state']):,} · registry blocked {len(c['registry']):,} · "
          f"agree {len(c['agree']):,}")
    print(f"        only in state {len(c['only_state']):,} · "
          f"only in registry {len(c['only_registry']):,}")
    if c["only_state"]:
        print(f"        state-only sample: {', '.join(c['only_state'][:6])}")
    print("")
    if not ok:
        print("   🔴 the SCREENING AUTHORITY is not fit for the job. Nothing else here matters.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
