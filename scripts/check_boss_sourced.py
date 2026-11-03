#!/usr/bin/env python3
"""BUG-711 Slice 2 gate: a boss the card calls verified has a first-party source in the registry.

    python3 scripts/check_boss_sourced.py <push-dir>     (read-only; reads <push-dir>/feed-cards/*.json)

BUG-714 Slice A: it reads the PUSHED shape (card["panel"][].w, app2.py:1952). Exit 1 when any card has
  - boss.verified true without a first-party boss.record_verified (linkedin-live, company-page, press-release), or
  - an UNVERIFIED boss (verified is not true AND (record_verified not first-party OR boss.why[0] starts "UNVERIFIED:"))
    with "confirmed"/"named" in boss.title or boss.why, or in a panel seat that also names his surname, or a seat that
    names a registry-demoted boss, or a "scored on a boss" seat that is not the fixed sentence for its own seat and score.
  A seat naming a source-unverified (not demoted) boss is a WARN here (a problem in Slice B). "not confirmed" and
  "cannot confirm" are the honest words and pass.
Exit 2 when there are no cards or a card is in the pre-push shape (panel_seats, no panel). Exit 0 otherwise."""
import glob
import json
import os
import re
import sys

FIRST_PARTY = ("linkedin-live", "company-page", "press-release")
CLAIM_RE = re.compile(r"(?<!not )(?<!n't )\b(confirmed|named)\b", re.I)
# Gate-local copies, pinned to build_app_feed by tests/test_check_boss_sourced.py (the gate imports nothing from the builder).
UNVERIFIED_SEAT = "%s %s: scored on a boss the registry cannot confirm; re-panel owed once the team-page read lands."
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd", "md"}


def name_tokens(raw):
    toks = re.findall(r"[a-z]+", str(raw or "").lower())
    return [t for t in toks if t not in _NAME_SUFFIXES]


def surname_rx(name):
    """The surname as a whole word; a hyphenated surname matches whole, and a hyphen never joins a plain one ("white-label").
    An apostrophe is optional in the match ("O'Brien"), and a credential or tagline after a comma or a dash that has a space on at least one side
    ("Erin Fakerson- Empowering Leaders", "Erin Fakerson - ...", "Erin Fakerson -...") is dropped, the same rule as check_dup._display_person (BUG-737).
    A hyphen inside a name ("Smith-Jones") has no space beside it and stays."""
    head = re.split(r",|\s*-\s+|\s+-\s*", str(name or ""))[0]
    words = [w for w in head.split() if name_tokens(w)]
    if not words:
        return None
    last = words[-1].replace("\u2019", "'")
    parts = [t for t in (re.sub(r"[^a-z']", "", p.lower()) for p in last.split("-")) if t.replace("'", "") and t not in _NAME_SUFFIXES]
    if not parts:
        return None
    pat = "-".join("['\u2019]?".join(re.escape(x) for x in t.split("'")) for t in parts)
    return re.compile(r"(?<![\w-])%s(?![\w-])" % pat, re.I)


def _why0(boss):
    why = boss.get("why")
    first = why[0] if isinstance(why, list) and why else why
    return str(first or "")


def is_demoted(boss):
    return _why0(boss).startswith("UNVERIFIED:")


def is_unverified(boss):
    return boss.get("verified") is not True and (boss.get("record_verified") not in FIRST_PARTY or is_demoted(boss))


def _stand_in_seat_problems(card, boss):
    """BUG-711 Slice 3b: on a stand-in card the demoted person is others[0]; a seat naming that surname must carry the fixed sentence.
    A missing or malformed others[0] means no demoted person."""
    if boss.get("confidence") != "stand-in":
        return []
    others = boss.get("others")
    first = others[0] if isinstance(others, list) and others else None
    rx = surname_rx(first.get("name")) if isinstance(first, dict) and isinstance(first.get("name"), str) else None
    if not rx:
        return []
    out = []
    for i, seat in enumerate(card.get("panel") or []):
        seat = seat if isinstance(seat, dict) else {}
        w = seat.get("w") if isinstance(seat.get("w"), str) else ""
        if w != UNVERIFIED_SEAT % (seat.get("n"), seat.get("s")) and rx.search(w):
            out.append("panel[%d].w names the demoted person on a stand-in card" % i)
    return out


def check_card(card):
    """-> (problems, warns)."""
    boss = card.get("boss") if isinstance(card, dict) else None
    if not isinstance(boss, dict):
        return [], []
    probs, warns = [], []
    if boss.get("verified") is True:
        if boss.get("record_verified") not in FIRST_PARTY:
            probs.append("boss.verified is true but record_verified is %r (no first-party source)"
                         % boss.get("record_verified"))
        probs.extend(_stand_in_seat_problems(card, boss))
        return probs, warns
    if not is_unverified(boss):
        return probs, warns          # waiting for promotion (a first-party word, verified false): not this gate's business
    texts = [("boss.title", str(boss.get("title") or ""))]
    why = boss.get("why")
    for w in (why if isinstance(why, list) else [why]):
        texts.append(("boss.why", str(w or "")))
    for where, text in texts:
        m = CLAIM_RE.search(text)
        if m:
            probs.append("%s says %r on an unverified boss" % (where, m.group(1)))
    rx = surname_rx(boss.get("name"))
    for i, seat in enumerate(card.get("panel") or []):
        seat = seat if isinstance(seat, dict) else {}
        w = seat.get("w") if isinstance(seat.get("w"), str) else ""
        n, sc = seat.get("n"), seat.get("s")
        if w == UNVERIFIED_SEAT % (n, sc):
            continue
        if ": scored on a boss" in w:
            probs.append("panel[%d].w is not the fixed sentence for %s %s" % (i, n, sc))
            continue
        if not (rx and rx.search(w)):
            continue
        m = CLAIM_RE.search(w)
        if m:
            probs.append("panel[%d].w claims %r about the unverified boss" % (i, m.group(1)))
        elif is_demoted(boss):
            probs.append("panel[%d].w names the registry-demoted boss" % i)
        else:
            warns.append("panel[%d].w names a boss the registry cannot confirm" % i)
    return probs, warns


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: check_boss_sourced.py <push-dir>", file=sys.stderr)
        return 2
    files = sorted(glob.glob(os.path.join(argv[0], "feed-cards", "*.json")))
    if not files:
        print("BOSS-SOURCED GATE CANNOT RUN: no feed-cards/*.json under %s. Nothing was checked, so this is NOT a pass." % argv[0],
              file=sys.stderr)
        return 2
    bad = nwarn = 0
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                card = json.load(fh)
        except (OSError, ValueError) as e:
            print("BOSS-SOURCED GATE CANNOT RUN: %s cannot be read (%s)" % (f, type(e).__name__), file=sys.stderr)
            return 2
        if isinstance(card, dict) and "panel_seats" in card and "panel" not in card:
            print("BOSS-SOURCED GATE CANNOT RUN: pre-push shape: panel_seats found, panel missing; run the gate on the push tree (%s)"
                  % os.path.basename(f), file=sys.stderr)
            return 2
        probs, warns = check_card(card)
        for p in probs:
            bad += 1
            print("  %s: %s" % (os.path.basename(f), p))
        for w in warns:
            nwarn += 1
            print("  WARN %s: %s" % (os.path.basename(f), w))
    print("BOSS-SOURCED GATE: %d card(s) read, %d problem(s), %d warn(s)" % (len(files), bad, nwarn))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
