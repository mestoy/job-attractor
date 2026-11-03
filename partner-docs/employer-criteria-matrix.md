# Your employer criteria matrix

> ⚠️ **This file is a TEMPLATE and it degrades SILENTLY.** Fill in the top few rows.
>
> ↻ **CORRECTED 2026-08-07 (BUG-047).** This note used to say `rank_criteria.py` reads this file and
> that leaving it empty means ranking runs with no personal weighting. **Neither is true.**
> `rank_criteria.py` only PRINTS this path in a header; nothing in it opens the file. Ranking weight
> lives in `scripts/kit_config.py` under `CRITERIA_WEIGHTS`, and that is where to change it.
>
> **What this file DOES serve**, and why an empty one still costs you: it is your durable reasoning
> about employers, and it is read by `check_rulings.py` (which reconciles it against your veto list)
> and `backfill_as_of.py` (which extracts your rulings). `doctor.py` reports it under `[6] your
> inputs` when it is still the shipped template.
>
> ⚖️ The old wording was worse than a plain error: you would fill this in, see the check turn green,
> and get a ranking that came out byte for byte unchanged.

## The two kinds of criteria, and mixing them is the common mistake

**Hard filters** are pass or fail. One failure drops the company, whatever else is true. They never
get a weight, because a weighted deal-breaker is not a deal-breaker.

**Scoring factors** rank the survivors. They carry a weight from 1 to 10 for how much you care, and
each company gets a rating from 1 to 10 for how well it does.

## A. HARD VETOES — a NO on any one is a NO, at every rung, never waived

Write yours. These rows are examples of the SHAPE, not recommendations, and are pre-filled to match
`docs/HARD-INVARIANTS.md`'s "Deal-breakers (never waived at any rung)" line category for category
(`scripts/check_rulings.py` checks that the two stay in agreement) — replace the wording, keep at
least one row per category you still hold, and delete a row for a category you don't filter on.

| # | Veto | Test |
|---|---|---|
| 1 | Permanently remote, no relocation, no commute | Would this role ever ask you into an office? |
| 2 | No required travel | Does the job post or the recruiter mention travel at all? |
| 3 | No fixed non-US time zone overlap | What hours would a standup or on-call actually fall in? |
| 4 | Deal-breaker industries: defense/military mission, law enforcement or policing customers, gambling, crypto, predatory lending | Who does this company sell to, and who uses what it builds? |
| 5 | Any people-level exclusion you maintain (a named former employer, an excluded leadership tier) | Would this role report into, or alongside, the person or tier you excluded? |
| 6 | PE-owned, if that is a filter for you | Who owns the company, and since when? |
| 7 | Political alignment, if that is a filter for you | Has the company or its leadership taken a public position you've ruled out? |

## Scoring factors

| Criterion | Weight 1-10 | Why it matters to you |
|---|---|---|
| | | |
| | | |
| | | |

⚖️ **Start with three rows, not twenty.** A matrix with three criteria you mean beats one with
fifteen you guessed at, and you will learn the real ones from the companies you reject.

## How to fill it

Do not start from a list of virtues. Start from the last few jobs, roles, or teams you turned down or
left, and ask what the actual reason was. Those reasons are your criteria, and they are already
tested. The ones you invent in the abstract usually turn out to be things you thought you should
want.

Then, for each criterion, write the question that would reveal it in an interview. A criterion you
cannot test is a preference, and it belongs lower down.
