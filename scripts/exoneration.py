#!/usr/bin/env python3
"""exoneration.py — the ONE compiled pattern that says a blocked-list row has been cleared.

⛔ THIS MODULE HOLDS A PATTERN AND NOTHING ELSE, and the emptiness IS the design. No file reads,
no sibling imports, no work at import time. Its second consumer is the SEND GATE, which cannot
afford to inherit another module's side effects just to learn one regex.

⚖️ TWO CONSUMERS, TWO DIFFERENT JOBS, ONE VOCABULARY:

    seed_employers.EXONERATED   the registry reseed — CLEARS `is_blocked` on the entity
    check_dup._EXONERATED       the send gate — DEMOTES the matched blocked-list row 🔴 → 🟡

They used to be literal twins, copy-pasted, each carrying a comment asking the other to stay
identical. A comment is not a pin. The fix is not "import the script that does real work", it is
to hoist the LITERAL into a module that does nothing. Both now read the same object, and `is`
holds between them, which is what a parity test should assert.

🔴 WIDENING THIS VOCABULARY HAS UN-BLOCKED A REAL COMPANY, more than once, on the owner's own
pipeline. The short version: an alternative that reads a verdict out of a row's NARRATIVE prose
(rather than a marker the file actually writes) can clear an entity the row still blocks. A
"correction" runs in EITHER direction; a bare word like "corrected" carries no verdict at all. A
phrase used in one row's explanation can also appear, coincidentally, inside another row's
unrelated sentence, and a wide match clears that other row too even though it was never the
subject.

⚖️ THE RULE THOSE REGRESSIONS PAID FOR: an alternative must be a MARKER THIS FILE WRITES, never a
phrase its prose can happen to form.

⚠️ NOT THE ONLY EXONERATION PATTERN IN THE REPO, and the others are left alone ON PURPOSE.
`screen_sweep.blocked_keys_from_list` and `build_employer_notes` carry a LOOSER variant that still
accepts a bare `corrected`. Folding them in here would change which keys the blocked harvest emits,
which is a behavior ruling of its own — not something to smuggle in under a de-duplication.
"""
import re

EXONERATED = re.compile(r"not blocked|not killed|not a gate fail|⏭️|deferred|entry corrected")
