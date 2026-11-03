# Partner Feedback Protocol — reporting defects in the SHIPPED kit

## WHEN to file
File a feedback entry when you hit something only the upstream maintainer can fix:

- a **shipped script errors** (a crash, a wrong exit code, an exception the kit's own gates did
  not expect),
- **two shipped rules contradict** each other (a checklist step and a gate disagree about what is
  required, a doc and the code it describes have drifted apart), or
- a **referenced file is missing** (a script or doc points at a path the kit never shipped).

This is NOT the place for your own data, your own preferences, or anything specific to your job
search. It is only for defects in the kit itself.

## The rule
**Append a structured entry. Do NOT silently patch the shipped script.** A local workaround is
allowed, but only AFTER the entry exists, and the workaround must be noted in the entry.

## The entry template (verbatim)
Append this block, exactly shaped, to `documents/partner-feedback.md`:

```
## FEEDBACK 2026-07-29 · check_ats-crashes-on-empty-board · status:unsent
- kind: script-error | rule-contradiction | missing-file | other
- surface: scripts/check_ats.py
- expected: <one line>
- observed: <verbatim error, paths scrubbed to ~/>
- repro: <the command run>
---
```

Only the header line (`## FEEDBACK ...`) is machine-edited, and only by `send_feedback.py`, which
rewrites it in place after a send.

## Scrub rule
No real names, and no absolute home-directory paths — anything that starts with your Mac user
folder should be written with `~/` instead (e.g. an expanded home path becomes `~/repo/...`). Scrub
before you write the entry, not after — the entry is the thing that eventually leaves this machine.

## After you've appended an entry
Tell the operator, and point them at:

```
python3 scripts/send_feedback.py
```

## Transport note
`documents/` is git-ignored by design. This file never travels via git — `send_feedback.py` is the
ONLY channel that can move it (via a `gh issue create`, or a mailto/copy-block fallback). Do NOT
"fix" this by tracking the file in git; that would break `git pull --ff-only` for every future kit
update.

No maintainer address ships in the kit. When `send_feedback.py` falls back to a copy-block (no `gh`
available), email that block to whoever sent you this kit — they are the maintainer who can fix it
upstream. A GitHub account holder can instead open an issue at the URL the script prints.
