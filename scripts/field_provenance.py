#!/usr/bin/env python3
"""field_provenance.py — mechanism for a per-FIELD-NAME provenance block on a generated feed.

WHY THIS EXISTS (2026-09-12). A feed's `generated_at` dates the whole document; it dates no
field inside it. On 2026-09-11 the owner opened a card, saw ten evidence gates carrying no `why`,
and stopped rather than weigh a score he could not substantiate. A usability pass checked
afterward, found the field populated, and wrote him up as having missed evidence that was right
in front of him. **Both were right, about DIFFERENT BUILDS**: his build had `gates[].why` empty
on 1,010 of 1,010 rows; a later build populated it and regenerated twenty minutes after his
session ended. Nobody could tell which build anyone was looking at, because nothing recorded when
a FIELD began being populated — only when the FILE was generated.

THIS MODULE KNOWS NOTHING ABOUT ANY PARTICULAR FEED'S FIELDS. It is the mechanism: a registry
entry shape, a validator that every emitted field-path the caller declares is covered, and the
render of the `field_provenance` block itself. The caller (`build_app_feed.py`) supplies the
registry; this file never imports it and never hardcodes a field name.

THREE RULINGS THIS MECHANISM ENFORCES (the owner, 2026-09-12):
  1. One stamp per FIELD NAME at the schema level, never per-card. A registry keyed by a
     COLLAPSED path (`cards[].gates[].why`, list indices erased) does not grow with the card
     count — this is the whole reason the block stays small on a feed with hundreds of cards.
  2. Where a date cannot be established, the entry carries `code_since: null` WITH A STATED
     `basis` string explaining why. NEVER a backfilled estimate: a stamp silently defaulting to
     "today" or to some floor date reproduces the exact defect this file exists to fix, just
     one layer down. `mark_undeclared()` below is the one place that manufactures a null/basis
     pair, and it says exactly what it did.
  3. An absent provenance block, or a field missing from it, must read to the CALLING APP as
     "this build cannot say" — never as "nothing found" or "clean". That contract lives in
     `documents/app-feed-provenance-contract-2026-09-12.md` in the main repo, not as a comment
     here, so the app team can read it without opening this file.

WHAT AN ENTRY LOOKS LIKE, once rendered:
    "cards[].gates[].why": {
        "code_since": "2026-09-11T19:07:54Z",   # or null
        "basis": "gate_why() introduced at e13cd367, absent at dd42e11e (verified via git show)",
        "empty_means": "no evidence text could be re-derived for this gate's recorded state"
    }

Stdlib only. Read-only with respect to git: this module never shells out to git itself — bracket
dates are supplied by the caller, who did that work by hand and states the evidence in `basis`.
This is deliberate (module docstring, build_app_feed.py): deriving dates from git history inside
the feed generator was rejected twice on evidence — the feed's own tree entered git only on
2026-09-11 with 14 commits, 9 of them generic unattended backup snapshots from one day, so a
commit timestamp answers "when did this text enter a commit", not "when did an operator populate
this field", and the two were already shown to disagree by up to 20 minutes on the incident this
file exists to prevent.
"""
from __future__ import annotations

import re

REQUIRED_KEYS = ("code_since", "basis", "empty_means")

UNDECLARED_BASIS = "undeclared at build time"


class ProvenanceError(Exception):
    """Refusal. Raised by `require_complete()`; nothing about the caller's feed is touched."""


def collapse_path(path):
    """Strip a positional/index suffix down to the canonical '[]' collapse.

    Accepts either an already-collapsed path ('cards[].gates[].why') or one carrying real
    indices ('cards[3].gates[1].why') and returns the same collapsed form for both, so a
    registry lookup never has to know how many cards or gates exist.
    """
    return re.sub(r"\[\d+\]", "[]", path)


def collect_paths(obj, prefix=""):
    """Every LEAF field-path present in `obj`, list indices collapsed to '[]'.

    A dict descends by key. A list descends into each of its items under the SAME collapsed
    path (an empty list still contributes its own path, so a field that is empty on every card
    this run is not invisible to the registry check). A leaf (anything else, including an empty
    dict) contributes its own path.
    """
    paths = set()

    def walk(o, p):
        if isinstance(o, dict) and o:
            for k, v in o.items():
                walk(v, f"{p}.{k}" if p else k)
        elif isinstance(o, list):
            if not o:
                paths.add(p + "[]")
            for item in o:
                walk(item, p + "[]")
        else:
            paths.add(p)

    walk(obj, prefix)
    return paths


def validate_registry(registry):
    """[(path, problem), ...] for any entry missing a required key or carrying a bad shape.

    A `code_since` that is present must be a string (the caller's job to format as ISO-8601
    UTC, e.g. '2026-09-11T19:07:54Z' — full timestamp, never a bare date, because RULING 2
    exists precisely to stop a date-only stamp from hiding a same-day ordering mistake). A
    `basis` and `empty_means` must always be present and non-empty, even when `code_since` is
    null — RULING 2 requires the null to be EXPLAINED, not merely allowed.
    """
    problems = []
    for path, entry in registry.items():
        if not isinstance(entry, dict):
            problems.append((path, "registry entry is not a dict"))
            continue
        for key in REQUIRED_KEYS:
            if key not in entry:
                problems.append((path, f"missing required key '{key}'"))
        cs = entry.get("code_since")
        if cs is not None and not isinstance(cs, str):
            problems.append((path, "code_since must be a string timestamp or null"))
        for key in ("basis", "empty_means"):
            v = entry.get(key)
            if v is not None and not (isinstance(v, str) and v.strip()):
                problems.append((path, f"{key} must be a non-empty string"))
    return problems


def ancestors(path):
    """`path` itself, then each successively shorter CONTAINER prefix, by stripping one trailing
    '[]' or one trailing '.segment' at a time. Lets a registry entry at a container level (e.g.
    'cards[].boss') cover every leaf beneath it ('cards[].boss.confidence',
    'cards[].boss.verified') without a separate entry per leaf — how ~25 registry entries can
    account for every leaf path a real feed emits without one entry per scalar."""
    p = path
    yield p
    while True:
        if p.endswith("[]"):
            p = p[:-2]
            if not p:
                return
        elif "." in p:
            p = p.rsplit(".", 1)[0]
        else:
            return
        yield p


def covering_key(path, registry):
    """The registry key that covers `path` (itself or the nearest registered ancestor), or None."""
    for a in ancestors(path):
        if a in registry:
            return a
    return None


def require_complete(emitted_paths, registry, allow_undeclared=False):
    """Every path in `emitted_paths` (already collapsed, or raw — collapsed here) must be
    COVERED by a registry entry (itself or an ancestor container, see `ancestors()`), OR
    `allow_undeclared` must be set.

    Returns the set of leaf paths that were undeclared (empty if none, or if allow_undeclared
    masked them) so the caller can log what it let through. Raises ProvenanceError, nothing
    written by the caller, when undeclared paths exist and `allow_undeclared` is False — a seat
    is refused LOUDLY rather than shipping a feed the registry does not actually describe.
    """
    collapsed = {collapse_path(p) for p in emitted_paths}
    missing = sorted(p for p in collapsed if covering_key(p, registry) is None)
    if missing and not allow_undeclared:
        raise ProvenanceError(
            "REFUSING: %d emitted field path(s) are not covered by any field_provenance "
            "registry entry (checked the path itself and every container ancestor):\n%s\n"
            "Add a covering entry to the registry, or pass allow_undeclared=True to ship anyway "
            "with an undeclared marker recorded for those paths (basis '%s')."
            % (len(missing), "\n".join("  " + p for p in missing), UNDECLARED_BASIS))
    return set(missing)


def mark_undeclared(path):
    """The one, explicit place an undeclared path gets a provenance entry. Never invents a date."""
    return {"code_since": None, "basis": UNDECLARED_BASIS,
            "empty_means": "not documented; this field shipped before its provenance was written"}


def build_block(emitted_paths, registry, allow_undeclared=False):
    """The rendered `field_provenance` block: a COPY of every registry entry that covers at
    least one path actually emitted this run, plus one `mark_undeclared()` entry per leaf path
    that no registry entry covers (only reached when `allow_undeclared=True`; otherwise
    `require_complete` already raised).

    Deliberately NOT one entry per emitted leaf — the whole point of `ancestors()`-based coverage
    is that the block stays at registry scale (the owner's ruling: "roughly 25 entries... does not
    grow with the card count"), not leaf scale. A registry entry that covers nothing this run
    (a field the current build never produces) is left out, so the block always describes what
    shipped, not everything the registry has ever known about.

    Call this LAST, after the payload is otherwise complete, so `emitted_paths` reflects the
    real, final shape of the feed rather than an intermediate one.
    """
    probs = validate_registry(registry)
    if probs:
        raise ProvenanceError(
            "REFUSING: the registry itself is malformed:\n%s"
            % "\n".join("  %s: %s" % (p, why) for p, why in probs))
    undeclared = require_complete(emitted_paths, registry, allow_undeclared=allow_undeclared)
    collapsed = {collapse_path(p) for p in emitted_paths}
    used_keys = set()
    for p in collapsed:
        key = covering_key(p, registry)
        if key is not None:
            used_keys.add(key)
    block = {k: dict(registry[k]) for k in sorted(used_keys)}
    for p in sorted(undeclared):
        block[p] = mark_undeclared(p)
    return block, undeclared
