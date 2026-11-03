"""person_name.py -- the ONE test of whether a string reads as a single person's name.

⛔ WHY IT LIVES HERE. `boss.verified` must mean two sources AND a real person. Before 2026-09-14 it
meant two sources only, so a boss line reading `NOT CONFIRMED` was shown as a VERIFIED boss (proxy
P8). The fix landed in the kit's `app/design/phases/build.py` and was loaded from there by path.
But partner-starter, the tree that ships, has no `app/design/phases/build.py`, and neither does the
published kit, so the fix never reached the people using it. They still had P8.

This module has one home in `scripts/`, which every tree with a feed builder also has, and it is
imported with a hard import: if it is missing, the builder fails loudly rather than calling every
boss unverified, or every placeholder verified, in silence.

⚠️ TWO COPIES EXIST UNTIL ONE MORE CHANGE LANDS. This text was taken from the kit's build.py at
commit 8dcb74b, byte for byte, below this note. build.py should import THIS module instead of
keeping its own; until it does, the two must stay identical, because two word lists is how a
placeholder passes one gate and fails the other.

Refusing a real name costs a "not matched yet" line; accepting a placeholder puts it at the top of
a message, so doubtful strings are refused.
"""
import re

_NAME_PARTICLES = frozenset(("de", "del", "della", "da", "di", "dos", "du", "la", "le",
                             "van", "von", "der", "den", "bin", "binti", "ibn", "al", "el",
                             "jr", "jr.", "sr", "sr.", "ii", "iii", "iv"))
# Lowercase words no one's name is made of, but placeholder and verdict strings are.
# Verdict tokens in capitals (PARK, PASS, LEFT) are refused by the all-capitals rule below,
# so real surnames like Park or Pass are not listed here.
_NOT_NAME_WORDS = frozenset((
    "not", "no", "none", "n/a", "na", "tbd", "tba", "unknown", "unnamed", "unconfirmed",
    "confirmed", "identified", "unidentified", "yet", "vacant", "fallback", "reverted",
    "pending", "owed", "verify", "verified", "unverified", "boss", "gate", "evidence",
    "pattern", "ruled", "decided", "unproven", "radar", "or", "and", "with", "ceo", "cto",
    "cpo", "coo", "vp", "svp", "evp", "chief", "officer", "founder", "product", "director",
    "manager", "team", "candidate", "role", "title", "source", "named", "hiring", "position"))
_LETTERS = re.compile(r"^[^\W\d_]+$")


def person_name(raw):
    """`raw`, stripped, when it reads as one person's name; else None.

    One to four words, letters only (hyphen and apostrophe inside a word, a trailing dot
    only on a single-letter initial), each word capitalised unless it is a name particle,
    no all-capitals word longer than three letters, and no placeholder or verdict word.
    Refusing a real name costs a "not matched yet" line; accepting a placeholder puts it
    at the top of a message, so doubtful strings are refused."""
    if not isinstance(raw, str):
        return None
    s = raw.strip().strip("*").strip()
    if not s or len(s) > 60 or re.search(r"[^\w\s.'\u2019-]|[\d_]", s):
        return None
    words = s.split()
    if not 1 <= len(words) <= 4:
        return None
    for i, word in enumerate(words):
        low = word.lower()
        if low.strip(".") in _NOT_NAME_WORDS:
            return None
        if i and low in _NAME_PARTICLES:
            continue
        if word.endswith("."):
            if len(word) == 2 and word[0].isupper():
                continue
            return None
        if not word[0].isupper() or (word.isupper() and len(word) > 3):
            return None
        if not all(part and _LETTERS.match(part) for part in re.split(r"['\u2019-]", word)):
            return None
    return s
