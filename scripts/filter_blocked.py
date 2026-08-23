#!/usr/bin/env python3
"""filter_blocked.py — mechanical blocked-list gate for refill/survivor lists.

⛔ THE DEFECT THIS CLOSES. A discovery/refill path can hand an already-blocked company forward
as "fresh" if the blocked-list dedup is left to a human (or an agent) grepping the blocked-list
file by hand — that file grows long, so entries past the first screenful get missed. Several
already-blocked companies have been re-banked as clean this way in a single session, each
costing real research and build cycles before a manual re-audit caught it.

This runs the SAME exact canon-key blocked check `check_dup.blocked_key_hit()` uses —
collision-free, space-stripping-safe (e.g. "Acmeworks" == "Acme Works") — over a WHOLE
candidate list, deterministically, so filtering a refill/survivor list no longer depends on
someone remembering to grep the full file. It checks ONLY the blocked list, so a CLEAN verdict
here means "not blocked", never "not yet worked" — do not conflate the two.

Usage:
  filter_blocked.py "Company A" "Company B" ...        # names as args
  printf '%s\\n' "Company A" "Company B" | filter_blocked.py   # names on stdin, one per line
Output: one line per candidate, ⛔ BLOCKED (with the matching entry) / ✅ CLEAN / ⚠️ ERROR.
Exit:   0 = all clean · 1 = at least one blocked · 2 = usage / import failure

Intended use: pipe every discovery/refill candidate list through this BEFORE banking, and
drop the BLOCKED rows. Clean rows still owe the rest of the screening gate (remote, culture,
live-role, ownership) — this closes only the blocked-list hole, which is step 0 of the screen.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_dup import blocked_key_hit, _blocked_entry_lines


def classify(name: str):
    """Return (status, detail) for one candidate name. status ∈ {BLOCKED, CLEAN, ERROR}."""
    key = blocked_key_hit(name)
    if key == "__import_failed__":
        # FAIL LOUD: a broken blocked-list import must not read as "clean".
        return ("ERROR", "blocked-list check unavailable (screen_sweep import failed)")
    if key:
        lines = _blocked_entry_lines(key)
        detail = lines[0][1] if lines else f"(matched blocked key '{key}')"
        return ("BLOCKED", detail)
    return ("CLEAN", "")


def main():
    names = [a for a in sys.argv[1:] if a.strip()]
    if not names and not sys.stdin.isatty():
        names = [ln.strip() for ln in sys.stdin if ln.strip()]
    if not names:
        print('usage: filter_blocked.py "Company" [...]   (or names on stdin, one per line)',
              file=sys.stderr)
        return 2

    any_blocked = False
    any_error = False
    for n in names:
        status, detail = classify(n)
        if status == "BLOCKED":
            any_blocked = True
            print(f"⛔ BLOCKED  {n}  ->  {detail}")
        elif status == "ERROR":
            any_error = True
            print(f"⚠️  ERROR    {n}  ->  {detail}")
        else:
            print(f"✅ CLEAN    {n}")

    if any_error:
        return 2
    return 1 if any_blocked else 0


if __name__ == "__main__":
    sys.exit(main())
