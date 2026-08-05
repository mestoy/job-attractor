# Job Attractor Kit, release notes

What the **maintainer** changed in the kit. Newest at the top. This file ships with every update and
is overwritten each time, so nothing you write here survives.

📓 Your own record is `documents/JOB-ATTRACTOR-CHANGELOG.md`. That one is yours, append-only, newest
at the bottom, and an update never touches it.

```
python3 scripts/release_notes.py          # what you have not read yet
python3 scripts/release_notes.py --all    # the whole history
python3 scripts/release_notes.py --seen   # mark it read
```

---

## v1.4 — 2026-08-04 · The people ranker stops rewarding companies nobody can identify

**Read this one if your top 10 has ever looked like a list of strangers at companies you could not
place.** That was a real defect, and this release fixes it.

### What was wrong

The people ranker scored contacts on title plus relationship, then applied a penalty when it could
not tell what the employer does. The penalty was a multiplier, and a multiplier cannot do the job:

- Applied to every unverified row equally, it scaled all of them and reordered none. Rows that were
  tied stayed tied.
- It landed **after** the learned category multiplier, so a founder at an unidentifiable company
  computed a HIGHER score than the same band would have scored un-multiplied. The penalty for being
  unidentifiable worked out to a promotion.

Net effect: the least knowable companies floated to the top, and the daily list was a connect-date
sort wearing a ranking's clothes.

### What changed

- **An evidence tier is now the primary sort key.** Four levels: resolved from a source, resolved at
  low confidence, not yet looked at, and searched-but-not-placeable. A tier floor is not tunable and
  cannot be out-multiplied by any weight the learner later finds. Points still order rows *within* a
  tier, so nothing else lost its meaning.
- **"Searched and could not place it" is now a thing you can record**, and it sorts BELOW "nobody has
  looked yet". A company no search can place is weak evidence of an org that hires your role; a
  company nobody has examined is no evidence either way. Treating them the same is what let obscurity
  win.
- **Resolution confidence is finally read.** A band sourced from a company's own about page now
  outranks one guessed from a headline. Both fields were being written already and used by nothing.
- **New in `kit_config.py`: `SEGMENT_INDUSTRY_PATTERNS` and `OFF_SEGMENT_PATTERNS`.** These say what
  a COMPANY does, which is a different question from `SEGMENTS` (which holds job titles you search
  for). ⚠️ Both ship EMPTY on purpose, and empty is the safe direction: nothing is demoted, every
  band is kept and flagged. Fill them in when you know your lanes.
- **New scripts:** `contact_signals.py` (segment and endorsement signals) and `resolve_employers.py`
  (`worklist` / `ingest` / `status`, to build a sourced employer cache).
- **The plateau warning actually fires now.** It compared scores exactly, so a continuous tenure
  bonus spreading nine identical rows across 50.2 / 50.1 / 49.8 read as distinct scores and the
  warning stayed silent on the day the tie was worst. It compares on whole points now.

### What you should do

Nothing is required. With the new config lists empty, the ranker behaves as before except that it
can no longer put an unidentifiable employer above a resolved one.

To get the full benefit, populate `SEGMENT_INDUSTRY_PATTERNS` and `OFF_SEGMENT_PATTERNS` in
`kit_config.py`, then run `python3 scripts/resolve_employers.py worklist` and hand the output to a
research agent.

### The transferable lesson

When a class of row must never outrank another, that is a **sort key**, not a score term. And test
the ordering a fix exists to produce, not the presence of the mechanism: this defect survived a
"fix" for five days because no test asserted that an unverified employer must sit below a resolved
one.

---

## v1.3 — 2026-08-03 · Your deal-breaker screen was silently disabled

🔴 **This was severe, and if you installed before 2026-08-03 it affected you.**

`kit_config.py` shipped as a tracked file, so the installer's seed never fired and a missing value
collapsed an import inside the screen. The `except` around it blanked **every** veto list to empty.
Defense, law enforcement, predatory lending, private-equity ownership, remote and politics all
passed everything, while the screen reported clean.

- Before: a company described as a defense contractor returned no veto hits.
- After: it returns the defense and weapons vetoes.

Also fixed in the same release: the ranker could not import at all (two modules were missing from
the ship list, causing 26 errors in the kit's own test suite), the 10-rung ladder never shipped
while the briefing told you to pick a rung, four other skills were missing, and `.gitignore` was
extended so a routine `git add` cannot trap the four files a partner actually edits.

**Standing fix, not a one-off:** the ship list is being inverted from "everything I remembered to
list" into an explicit DO-NOT-SHIP list, so the default becomes shipped rather than remembered.

---

## v1.2 — 2026-08-01 · Guardrail parity

The kit reached full parity with the maintainer's own guardrails: the send gate, the build gate,
the preview checks, the duplicate check, and the tripwire sweep all run the same code rather than a
simplified copy. Two copies of one rule drift, and the copy that drifts is the one nobody re-reads.
