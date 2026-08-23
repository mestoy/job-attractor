---
name: fill-queue
description: >
  Refill your boss-hunt decision queue with fresh, screened prospects. Reads the balancer
  to find under-target segments, runs discovery, screens each candidate against your hard
  filters and blocked list, dedups against the send log, and banks survivors until the
  queue hits depth. Triggers on: /fill-queue, fill queue, refill the board, top up the
  queue, keep queues full, research queue.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, WebFetch, WebSearch, AskUserQuestion
---

# Fill-Queue skill

---

> 🔒 **This is a RESEARCH-AND-BANK loop, not a send loop.** It never contacts anyone. It
> stops when the queue is at target depth or discovery goes dry. The SCREEN gate still
> applies to every candidate — run it and report ✅/❌ per the checklist below. If you are
> running this with other agents in parallel, keep ONE writer: whoever holds the write lock
> banks survivors into the queue file; the rest research and return findings rather than
> writing shared state directly.

Keep your decision queue full so you always have vetted vectors to pick from when you sit
down to work outreach. This is the command that tops it up on demand.

## Targets (the fill goal)

- Refill to a target depth of **approval-pending, screened-clean rows** — pick a number that
  keeps you a session or two ahead of your own outreach pace (this skill's upstream install
  used 30-50; tune to your cadence).
- Fill is **balanced, not opportunistic**: bias new rows toward the rungs and segments the
  balancer flags as under-target, so the queue mix pulls your actual send mix toward the
  target you set in `kit_config.py`'s `TARGET_RUNG_MIX` / `TARGET_SEGMENT_MIX`. See
  `balancer.py` in this kit's scripts.

## The loop

Run these steps and report ✅/❌ back to yourself (or whoever you're building the queue for)
at the end.

### 1. Read the shortfall

- Run `python3 scripts/pair_brief.py` (or `python3 scripts/balancer.py` directly) and read
  its output: which segments and rungs are below target, and by how much. Those gaps set the
  discovery priority order.
- Measure current queue depth: count the not-yet-decided rows in your queue file(s).
  Compute the deficit against your target depth. If already at or above target, report
  "queue full" and stop.

### 2. Discover

- Research the highest-deficit segment first: search company sites, job boards, and press
  for candidates in that lane. If you have other idle research agents available to fan work
  out to, hand each one a single under-target segment and have it report findings back
  rather than write the queue directly — keep one writer.
- Ask for, per candidate: company + one-line what-they-do + URL, a verifiable REMOTE posture
  (unverifiable remote = drop, say so explicitly), a LIVE role in your target seat with its
  JD URL, a hard-filter result, and a rough read on funding/ownership/size/stability.

### 3. Screen every candidate (the SCREEN gate — do not skip)

Re-read your `docs/HARD-INVARIANTS.md` (or wherever you keep your gate doc) before running
this step, since your own filters may have changed since you last ran it.

**STEP 0, mechanical, never by hand:** run the kit's blocked-list check over the WHOLE
candidate list before doing anything else with it. If your kit ships a batch checker (a
`filter_blocked.py`-style script), pipe the full candidate list through it in one pass; if
it does not, loop `python3 scripts/check_dup.py "<Company>"` over every candidate name
individually and drop every 🔴 BLOCKED result before continuing. **Do not hand-grep your
blocked-list doc.** A blocked-list file grows past what a human eye reliably scans in one
pass, and a candidate already on it is exactly the one you cannot afford to re-research as
if it were fresh.

Then, for each surviving candidate:

- **Remote posture** verifiable FROM THE ACTUAL COMPANY'S OWN CAREERS/ATS BOARD, else drop.
  A discovery "live role" tag from an aggregator is not proof — cached and stale listings
  are common. Confirm the role is live on the company's real board (a JS-rendered board
  needs a browser, not a plain fetch).
- **Hard filters**: whatever your `kit_config.py` `INDUSTRY_VETO` / `REMOTE_DISQUAL` /
  `PE_FLAG` lists say, applied consistently — see `check_screen_gate.py`.
- **Culture at the THREAD level, not the headline.** Read actual reviews for an
  always-on / nights-and-weekends / recurring-layoffs thread. A strong star average can
  hide exactly this — read the newest and most critical reviews, not just the aggregate.
- **Dedup**: skip anyone already in your send log or already a queue row.
- **Entity check**: verify you have the right company before trusting its funding or
  ownership data — name collisions between similarly-named companies are common.
- An unknown industry marks the row and does not silently pass through as clean.

### 4. Bank survivors

- Append each survivor to the queue as a clean row: company · what-they-do · URL · remote
  evidence · live-role JD URL · segment tag · rung intent · screen result + date · source.
  Tag the segment so the balancer can measure it.
- If a candidate turns out blocked/declined during this pass, record that ruling into your
  durable blocked-list doc the SAME pass you find it — a ruling that lives only in this
  session's output is a ruling that gets re-discovered and re-researched later.

### 5. Loop until full or dry

- Recompute the deficit. If still short and discovery is still producing fresh survivors, go
  back to step 2 for the next under-target segment. Stop when the queue hits its target
  depth, or when a full pass over the under-target segments yields no new survivors — then
  report the shortfall honestly rather than banking filler to hit a number.

## Report

Close with a compact summary: starting depth → ending depth, rows added per segment,
anything newly blocked, and which segments came up dry. This skill only banks — it does not
auto-advance into outreach.
