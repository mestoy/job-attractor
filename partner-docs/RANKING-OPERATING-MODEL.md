# Ranking operating model: what the ranker scores, how it orders, and where it is honest about not knowing

📊 Written 2026-09-12 (kit issue #73). The trigger was a board that showed the first row of a
six way tie as a #1 pick. Nothing in the output said the other five were indistinguishable.
This page explains how the two rankings in `scripts/rank_criteria.py` work, so you can read a
board without mistaking a tiebreak for a verdict.

## Two rankings, one file

`scripts/rank_criteria.py` produces two boards.

| Board | Command | Question it answers |
|---|---|---|
| Companies | `python3 scripts/rank_criteria.py` | which screened company to work next |
| People | `python3 scripts/rank_criteria.py --pool people` | who in your network can help first |

Both print a per row breakdown next to the score. Read the breakdown, because the score alone
hides how much of it is category and how much is the actual row.

## The objective

The people board ranks by expected value toward an offer, meaning who can best connect you to
your next opportunity. Replies are not the objective. A reply validates one factor (will they
engage) and nothing else. `scripts/rank_experiments.py` carries this in its header and it is the
bar every proposed signal is tested against.

## The company board

**Pool order.** The vetted green board first. When it holds fewer than N live rows, the ranker
tops up from the agent screened banked files, then from the raw discovery board (tagged as
needing a full screen). Sent, blocked, and already worked companies are excluded, because the
board is about who to work next.

**What it scores.** Only signals recorded on the row, mapped to your criteria matrix
(`docs/employer-criteria-matrix.md`). The weights live in `scripts/kit_config.py` under
`CRITERIA_WEIGHTS`:

| Criterion | Default weight | Source on the row |
|---|---|---|
| `wlb` | 10 | culture sub rating |
| `retention` | 10 | recommend or retention rating |
| `leadership_stability` | 10 | culture screen and its confidence tier |
| `calm_pace` | 8 | bootstrapped, mature, or calm pace signals |
| `boss_reachable` | 3 | a boss with an email on file (a readiness tiebreak) |
| `sourced_praise` | 2 | a sourced praise link (a readiness tiebreak) |

A criterion nobody wrote down is shown as "not scored," never counted as zero. Most of the
matrix (IC track, vacation, meeting load) is not recorded per row, so a company is never sunk
for a fact nobody captured. A WLB rating under `WLB_FLOOR` (default 3.0) removes the row
entirely, which is the one place a missing datum can do more than cost points.

**Order.** Culture confidence tier first (`🔬 verified`, `🟢 screened`, `🟡 soft`,
`💡 founder signal`, `⚪ unproven`), then criteria points inside the tier. A verified clean row
outranks an unproven one no matter the raw number. Among unscreened rows, which all arrive at
the same points by construction, open seats from the latest job sweep order the tie. That is a
tiebreak, never a fit signal; a company with nine openings is not a better match.

## The people board

**Categories and base weights.** Each contact is placed in a category from their title and
employer, with a base score from `PERSON_WEIGHTS` in `scripts/kit_config.py`:

| Category | Badge | Default base |
|---|---|---|
| product leader | 🎯 likely boss | 40 |
| founder or exec | 🏛 founder/CEO | equal to product leader |
| senior exec | 🏢 senior exec | 33 |
| product IC | 🤝 product peer | 25 |
| connector | 📇 connector | 15 |
| senior IC | 🧩 senior IC | see the file |
| other | · other | 5 |

The founder band scores equal to the product leader band on purpose. At a company with no
product function, the founder is the likely boss. Founders sort last inside a tie among
plausible bosses (the `founder_last` key below), which is an ordering, not a score gap.

**Bonuses.** `PERSON_EMAIL_BONUS` (default 5) when the contact is reachable now, and
`PERSON_REENTRY_BONUS` (default 8) when their company is already in your pipeline.

**Learned weights.** The per category multipliers are learned from your own send log and reply
outcomes. `--weights` shows the current row and `--recompute-weights` is the only writer of
`documents/state/person-weights.jsonl`. A signal needs at least 15 joined sends before it moves
a weight, and a lift is clamped to the range 0.5 to 2.0. Nothing is typed in and trusted.

**The warm path.** Knowing someone at the company before the send is a validated positive
signal. The closeness band (`worked-together`, `know-well`, `personal-friend` is strong; every
other stated tier is thin; never spoke or unstated is zero) leads the sort.

**The sort key, in order.** From `rank_people()` in `scripts/rank_criteria.py`:

1. closeness band, strong first
2. evidence tier (is the employer resolved and the title current)
3. points
4. founders last among equals
5. years known, longer first
6. name, alphabetical

Steps 5 and 6 are where a tie ends up. Two contacts equal on the first four keys are ordered by
how long you have been connected and then by their name. Neither fact says anything about who
can help you more.

**What the people board cannot see.** It is blind to company location, so the remote and
travel deal breakers apply only when a warm rung is built, not at ranking time. It also skips
any contact it cannot place in a category, and on a real install that is a large share of the
network (issue #12 counted it at 679 of 1441 on one network, and a partner's kit measured
99 rankable of 325 on another).

## How ties surface today

Three mechanisms are in place.

1. **Tie tripwires on both boards.** `print_tie_tripwires()` counts rows within a whole point of
   the top score and rows stating a byte identical reason string. More than `PLATEAU_WARN_AT`
   (5) rows within a point prints a plateau warning. When the union of the two groups is over
   `TIE_RATE_WARN_AT` (50%) of the shown rows, it prints that row 1 is a coin flip and names the
   tiebreak that decided the order.
2. **The contact card.** `scripts/contact_card.py` shows everyone within `TIE_BAND` (0.1) of the
   contact you are looking at, with the tiebreak named out loud. A card is owed before any
   co-creation picker names a person.
3. **The screening queue.** When the company board has nothing left to say, it prints what to
   measure next (a short culture peek is usually worth more points than any re-sort).

**The gap that remains.** The tripwires print to the terminal. The computed default in
`scripts/pair_brief.py` reads the sorted list and names row 1 as the default without checking
whether row 2 sits inside the tie band. When two contacts tie to the tenth on the first four
keys, the default flips between them as soon as either input moves, and the brief presents
whichever came first as the pick. That is the same defect the tripwires were built for, on the
one surface that skips them.

**Proposed change, not yet made.** In `rank_people()`, after the sort, mark every row that
matches row 1 on closeness band, evidence tier, and points rounded to `TIE_BAND` with a
`tied_with` list and a `tiebreak` string ("years known, then name"). Then `pair_brief.py` labels
the default "first of N tied, tiebreak years known" and offers the tied peers as equal options
instead of one pick. The check belongs in the ranker so both readers share one definition, the
same reason `reason_terms()` is shared between the tripwire and the card.

## What you can tune

All in `scripts/kit_config.py`, never in `rank_criteria.py`:

- `CRITERIA_WEIGHTS`, `WLB_FLOOR`, `WLB_RANGE`, `LEADERSHIP_CLEAN_TIER`,
  `LEADERSHIP_CAVEAT_FRACTION`, `LEADERSHIP_UNPROVEN_FRACTION`, `CONFIDENCE_MULTIPLIER`
- `PERSON_WEIGHTS`, `PERSON_EMAIL_BONUS`, `PERSON_REENTRY_BONUS`
- `EXCLUDED_EMPLOYERS` (leadership tier only at those employers; peers stay in scope)
- `NETWORK_SCORE_WEIGHTS` for the network company view in `scripts/rank_network_companies.py`

Retuning reorders who you are shown tomorrow, so treat a change as a ruling and note it in
`docs/JOB-ATTRACTOR-CHANGELOG.md`. The v2 people weights are proposed, not ratified, and the
output says so until you ratify them.

## Honest limits

- ⚠️ **The people score is close to a constant for some categories** (issue #12, BUG-181). On
  one measured run, nine of ten rows shared four distinct scores and byte identical reasons, and
  not one term was about the person. The score is category weight plus a distance bonus, so the
  tie is arithmetic, not an accident. The fix is better input (categorize more contacts, join
  more sends to contacts, and record closeness), not a cleverer sort.
- With no closeness store, every band is zero and the sort is unchanged from before that key
  existed. Fill `documents/state/closeness.jsonl` through `/level-network` to make the lead key
  do anything.
- The thread depth signal is leakage silenced and scores zero until it is validated on outcomes.
- A tiebreak that returns the same value for every row is a bug wearing the badge of a tie. The
  open seats tiebreak once did that when it matched the wrong sweep file, and it was
  caught only because the order never moved.

## The loop that refines it

- `scripts/rank_experiments.py` proposes a signal as a hypothesis, runs it against your
  outcomes, and ratifies it only on your say so. Append only, no rewrites.
- `scripts/log_impression.py` records what the board showed you, so a later run can measure
  which shown rows turned into sends and replies.
- `scripts/verdict_miner.py` reads your recorded rulings back into features.
- `scripts/bridge_sweep.py` runs on every new connection and profile visit, so the network
  input does not go stale between exports.

None of these change a weight on their own. They put a number in front of you and you rule.
