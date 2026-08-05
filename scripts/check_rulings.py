#!/usr/bin/env python3
"""check_rulings.py — your two veto lists must agree, and nothing checks that they do.

WHY THIS EXISTS
---------------
`documents/employer-criteria-matrix.md` states, in prose:

    "Hard vetoes here must match docs/HARD-INVARIANTS.md SCREEN GATE exactly."

In the pipeline this was ported from, they did not, and had not for some time. That is the root
cause in its purest form: **a contract asserted in prose with no checker.** The same shape produced
a Stop hook that stayed broken while its test passed, and a table layout that was an unwritten
agreement between a writer and a reader in different files. A claim of agreement, with nothing
reading both sides, is a claim that decays silently and confidently.

WHY THE DIVERGENCE IS NOT COSMETIC
----------------------------------
`employer-criteria-matrix.md` section A lists your hard vetoes under the heading
*"a NO on any one is a NO, at every rung, never waived"*.

`docs/HARD-INVARIANTS.md` carries a SHORTER list under *"Deal-breakers (never waived at any rung)"*.

Both claim to be the never-waived set. When they are different sets, the difference has teeth,
because the screen-depth table two lines above says a **warm 1st-degree** or **referred** target gets
*"Deal-breakers ONLY"*. So for every warm rung, which of these two lists is authoritative decides
whether the vetoes on the longer list get screened AT ALL. In the source pipeline the two rows that
fell through that gap were recurring layoffs — the owner's self-declared #1 factor — and always-on
culture, which had already killed a real candidate company.

This script does NOT pick a winner. Which list is authoritative is a policy decision about what your
pipeline screens, and it is yours. What this does is make the disagreement impossible to keep
ignoring, and then keep it that way.

STAYS HONEST WHEN YOUR DOCUMENTS CHANGE
---------------------------------------
A checker keyed on a fixed vocabulary rots the moment you add a veto. So a row found in either
document that this script cannot map is reported as UNMAPPED and is a finding in its own right,
rather than being silently skipped. That is the difference between a checker and a checker-shaped
thing — and on a kit that ships with generic categories against YOUR wording, UNMAPPED is the
expected first-run state, not a bug. Map them in KIT DEVIATION below.

FRESH INSTALL. With no matrix written yet there is nothing to compare, so this reports "not set up"
and exits 0. A vacuous pass that looked like agreement would be worse than no check.

Usage:  scripts/check_rulings.py [--quiet] [--json]
Exit:   0 = the two lists agree (or no matrix yet) · 1 = they diverge · 2 = a document is unreadable
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)

# KIT PATH NOTE: HARD-INVARIANTS ships under docs/; the criteria matrix is something YOU write, so
# it lives under documents/ with the rest of your working stores.
MATRIX = os.path.join(REPO, "documents", "employer-criteria-matrix.md")
INVARIANTS = os.path.join(REPO, "docs", "HARD-INVARIANTS.md")

# ⚠️ KIT DEVIATION — THIS IS THE TABLE YOU EDIT.
# The upstream pipeline hardcodes one person's 15 veto rows. Yours are your own, so the mapping ships
# GENERIC and is meant to be retuned. Each veto maps a pattern matching a row of YOUR matrix
# section A to the CATEGORY on the never-waived line that would carry it.
#
# ⚠️ THE TWO LISTS ARE AT DIFFERENT GRAIN, and getting that wrong is the failure mode. The
# never-waived line names CATEGORIES ("deal-breaker industries"); the matrix ITEMIZES ("no predatory
# lending"). Matching an itemized row against a category label directly finds nothing, and the
# checker then screams about vetoes that are perfectly well covered — the first cut of this reported
# 13 divergences where 3 were real. So each matrix row maps to the category that would carry it, and
# only a row with NO category is a genuine gap.
#
# These come from kit_config when you define them, each in its OWN try/except. Folding new names
# into an existing multi-name import would make the whole import fail on an older kit_config and
# silently fall back to placeholders, which is how a config change strands an existing install.
DEFAULT_CATEGORIES = {
    "work-arrangement":      r"work[- ]arrangement|remote",
    "deal-breaker-industry": r"deal[- ]breaker industr",
    "people-exclusion":      r"people[- ]level exclusion",
    "pe-owned":              r"pe[- ]owned",
    "political":             r"political",
}

DEFAULT_VETOES = [
    ("permanently-remote",  r"permanently remote|fully remote|remote[- ]only",  "work-arrangement"),
    ("no-travel",           r"no required travel|travel",                       "work-arrangement"),
    ("no-foreign-overlap",  r"time ?zone|overlap",                              "work-arrangement"),
    ("industry-veto",       r"defen[cs]e|military|law[- ]enforcement|gambling|"
                            r"crypto|predatory lending",                        "deal-breaker-industry"),
    ("not-pe-owned",        r"private equity|pe[- ]owned|majority[- ]owned",     "pe-owned"),
    ("political-alignment", r"right[- ]lean|political",                          "political"),
    ("people-exclusion",    r"former employer|leadership tier|people[- ]level",  "people-exclusion"),
]

try:
    from kit_config import VETO_CATEGORIES as CATEGORIES
except Exception:
    CATEGORIES = DEFAULT_CATEGORIES

try:
    from kit_config import VETO_ROW_MAP as VETOES
except Exception:
    VETOES = DEFAULT_VETOES

# Where a gap-row IS discussed in HARD-INVARIANTS, even though it is off the never-waived list.
# Reported separately, because "documented but not never-waived" and "absent entirely" are different
# problems with different fixes.
PROSE_PATTERNS = {
    "people-exclusion":   r"exclusion|leadership tier",
    "political-alignment": r"political",
}

# The short list on HARD-INVARIANTS.md that the screen-depth table sends warm rungs to.
_NEVER_WAIVED_LINE = re.compile(
    r"^\*\*Deal-breakers\*\*\s*\(never waived at any rung\)\s*:(.*)$", re.I | re.M)


def _read(path):
    try:
        return open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return None


def matrix_vetoes(text=None):
    """Rows of section A, as [(ordinal, label)].

    ⚠️ IMPORTS THE SEEDER'S EXTRACTOR RATHER THAN RE-IMPLEMENTING IT. Both existed for one run
    upstream and normalized labels differently: `backfill_as_of._clean_name` honours a head-anchored
    bold span, so `**Permanently remote**, US only` became "Permanently remote", while the local copy
    stripped only markdown characters and kept the whole cell. The store and the checker then
    disagreed about three vetoes that are identical in the file, and the drift report invented six
    findings out of nothing.

    Two spellings of one extraction is a forked-matcher defect that costs more every time it recurs.
    The store is the single source, so the code that FILLS it defines the shape, and every reader
    imports that.
    """
    sys.path.insert(0, HERE)
    try:
        from backfill_as_of import extract_vetoes
        return [(r["payload"]["ordinal"], r["payload"]["label"]) for r in extract_vetoes(MATRIX)]
    except Exception:
        # Degrade to a local parse so a broken import cannot silently report "no vetoes found",
        # which would read as agreement.
        body = text if text is not None else (_read(MATRIX) or "")
        m = re.search(r"^##\s*A\.\s*HARD VETOES.*?$(.*?)^##\s", body, re.S | re.M | re.I)
        out = []
        for line in (m.group(1) if m else "").splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0].isdigit():
                out.append((int(cells[0]), re.sub(r"[*`~]", "", cells[1]).strip()))
        return out


def invariants_never_waived(text):
    """The comma/middot separated short list of never-waived deal-breakers."""
    m = _NEVER_WAIVED_LINE.search(text)
    if not m:
        return []
    raw = re.sub(r"\(.*?\)", " ", m.group(1))
    return [re.sub(r"[*`~]", "", p).strip() for p in re.split(r"·|,", raw) if p.strip()]


def canonical_vetoes():
    """The SINGLE SOURCE: `documents/state/ruling.jsonl`, seeded from matrix section A.

    Before this, two documents were checked against EACH OTHER, which cannot detect the case that
    matters most: both drifting the same way at once. Checked against ONE store they cannot silently
    agree on something wrong, and the store is the thing a future generator renders both views from.

    Degrades to [] when the store is absent, so this file still runs on a fresh clone.
    """
    try:
        sys.path.insert(0, HERE)
        import state
        return [state.current("ruling", k, raw_key=True) for k in state.keys("ruling")]
    except Exception:
        return []


def scan():
    mt, it = _read(MATRIX), _read(INVARIANTS)
    if it is None:
        return {"error": "unreadable: docs/HARD-INVARIANTS.md"}
    # A matrix you have not written yet is a fresh install, not drift. Named, never silent: a check
    # that skips without saying so is indistinguishable from one that passed.
    if mt is None:
        return {"not_set_up": True, "agree": True, "matrix_rows": 0,
                "never_waived_entries": len(invariants_never_waived(it))}

    rows = matrix_vetoes(mt)
    never = invariants_never_waived(it)
    never_blob = " · ".join(never).lower()
    inv_blob = it.lower()

    canon = canonical_vetoes()
    result = {"matrix_rows": len(rows), "never_waived_entries": len(never),
              "canonical_vetoes": len(canon), "source_drift": [],
              "in_matrix_not_never_waived": [], "in_invariants_not_matrix": [],
              "unmapped_matrix_rows": [], "agree": False}

    # ── the matrix is a VIEW of the store now, so it must still match it ──────────────────────
    # Someone editing section A without re-seeding is the drift this catches. Without it, the
    # "single source" claim would be the same unchecked prose contract this file replaces.
    if canon:
        canon_labels = {(_c.get("payload") or {}).get("label", "").strip().lower()
                        for _c in canon if _c}
        matrix_labels = {l.strip().lower() for _n, l in rows}
        for missing in sorted(canon_labels - matrix_labels):
            result["source_drift"].append(
                {"item": missing, "why": "in the ruling store, no longer in matrix section A"})
        for added in sorted(matrix_labels - canon_labels):
            result["source_drift"].append(
                {"item": added, "why": "in matrix section A, not yet seeded into the ruling store "
                                       "(run: backfill_as_of.py --write --store employer-criteria)"})

    mapped = set()
    covered_categories = set()
    for slug, mpat, cat in VETOES:
        hit = next((r for r in rows if re.search(mpat, r[1], re.I)), None)
        if not hit:
            continue
        mapped.add(hit[0])
        cat_pat = CATEGORIES.get(cat) if cat else None
        if cat_pat and re.search(cat_pat, never_blob, re.I):
            covered_categories.add(cat)
            continue
        # No category on the never-waived list carries this row. Whether HARD-INVARIANTS discusses it
        # elsewhere changes the FIX, not the fact that a warm rung would not screen it.
        prose = PROSE_PATTERNS.get(slug)
        result["in_matrix_not_never_waived"].append(
            {"slug": slug, "matrix_row": hit[0], "label": hit[1],
             "category": cat,
             "described_in_screen_gate_prose": bool(prose and re.search(prose, inv_blob, re.I))})

    result["unmapped_matrix_rows"] = [{"row": n, "label": l} for n, l in rows if n not in mapped]
    result["never_waived_categories_matched"] = sorted(covered_categories)

    # And the other direction: a never-waived category no matrix row maps onto.
    for entry in never:
        cat = next((c for c, p in CATEGORIES.items() if re.search(p, entry, re.I)), None)
        if cat is None or cat not in covered_categories:
            result["in_invariants_not_matrix"].append(entry)

    result["agree"] = not (result["in_matrix_not_never_waived"]
                           or result["in_invariants_not_matrix"]
                           or result["unmapped_matrix_rows"]
                           or result["source_drift"])
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    quiet, as_json = "--quiet" in argv, "--json" in argv
    r = scan()
    if r.get("error"):
        print(f"🔴 {r['error']}", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["agree"] else 1
    if r.get("not_set_up"):
        # Say which case this took. A silent skip reads exactly like a pass.
        if not quiet:
            print("⚪ no documents/employer-criteria-matrix.md yet — nothing to compare against the "
                  f"{r['never_waived_entries']} never-waived entries. Write section A to enable this.")
        return 0
    if r["agree"]:
        if not quiet:
            print(f"✅ veto lists agree ({r['matrix_rows']} matrix rows, "
                  f"{r['never_waived_entries']} never-waived entries)")
        return 0

    print(f"🟠 the two veto lists DISAGREE — {os.path.basename(MATRIX)} claims they match exactly")
    print(f"   single source: {r['canonical_vetoes']} canonical veto(es) in the ruling store · "
          f"matrix section A: {r['matrix_rows']} · "
          f"HARD-INVARIANTS never-waived: {r['never_waived_entries']}")
    for d in r["source_drift"]:
        print(f"   🔴 SOURCE DRIFT: {d['item'][:52]}  ({d['why']})")
    for e in r["in_matrix_not_never_waived"]:
        where = ("described in SCREEN GATE prose but NOT in the never-waived list"
                 if e["described_in_screen_gate_prose"] else "absent from HARD-INVARIANTS entirely")
        print(f"   🔴 matrix #{e['matrix_row']:>2} {e['label'][:44]:<44} {where}")
    for e in r["in_invariants_not_matrix"]:
        print(f"   🔴 never-waived entry with no matrix row: {e}")
    for e in r["unmapped_matrix_rows"]:
        print(f"   ⚠️  matrix #{e['row']} {e['label'][:50]!r} is UNMAPPED — this checker does not "
              f"know it; add it to VETO_ROW_MAP")
    print("   ⛔ warm and referred rungs screen 'Deal-breakers ONLY', so the shorter list decides "
          "what a warm ask is screened against.")
    print("   Your call: widen the HARD-INVARIANTS list, or narrow the matrix's claim.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
