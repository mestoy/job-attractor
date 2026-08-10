# WORKFLOW-RULES — your screening operating system (edit to fit you)

The pipeline screens every company against this, in order. Fill in your own rules.

## 0. Operating principles
- **Boss-hunt-first:** apply where a fitting role exists AND email the would-be boss in parallel; get on the radar of great companies for when a role opens.
- **Check `documents/blocked-employers-list.md` FIRST** (grep it) before surfacing/screening/emailing ANY company; never re-surface one you've passed. **Keep that file in the repo** so BOTH your Claude sessions can read it — a blocked list kept anywhere else is invisible to one of them.

## 1. Hard filters (auto-reject; not "your call")
- [Work arrangement, e.g., remote-only incl. your state; no required travel]
- **ALWAYS verify remote AND travel cadence from the primary JD before surfacing a match or showing a scorecard — never defer to prep.** Scan the JD for travel language ("willingness to travel", "travel ~X%", "once a month/quarter", mandatory onsites/offsites). A remote-*location* posting can still require substantial travel; if travel conflicts with your hard filter, it's an auto-reject. Verify from the company's own JD, not an aggregator tag or Glassdoor.
- **No open req is NOT a disqualifier — boss-hunting communicates value to the boss regardless of a job opening (LaCivita).** Live-JD verification catches hard-filter violations WHEN a role exists (travel, hybrid, comp, reporting line, lane); it does not require that one exist. No live role → reframe as a value-reach (radar): verify company-level remote/travel/industry/culture and reach out on value, with comp as a conversation-time question. "No live role" is a scorecard flag, never a drop. Only company-level reasons that hold regardless of any opening are drops: hard-filter fails (remote-absolute, firm no-travel e.g. mandatory offsites), deal-breaker industries, toxic/grindset/AI-mandate culture, layoffs/instability.
- [Deal-breaker industries]
- [Any values/political screen]
- Recurring layoffs / M&A absorption / C-suite-exit restructuring = strong pass.
- Always-on culture = pass.

## 2. Culture / leadership / news screen (before recommending or outreach)
- Pull recent positive AND negative reviews (Glassdoor, etc.); quote verbatim when flagging.
- Leadership stability + retention weigh heaviest.
- News layer (~12 mo): layoffs, PE cost-cutting, lawsuits, leadership exits.
- **Deeper-probe protocol (mandatory when a potentially disqualifying signal surfaces).** Any "low job security / attrition / people pushed out / backdated or subjective perf-management / exec churn / conduct" signal gets a dedicated deep probe BEFORE the match is presented as GO, never a one-line mention. Establish: verbatim + attributed quotes (date, rating, current/former + role); distinct reviewers vs. one amplified review; concentrated pattern vs. scattered gripes; whether it applies to YOUR role/org (a sales-comp-cliff story doesn't transfer to a product seat); confirmed layoffs/exits vs. rumor (discard generic SEO "severance/layoff" template pages); counter-evidence (funding runway, hiring, long-tenure positives). Output a one-line verdict, BLOCK-LEVEL PATTERN / REAL-BUT-NOT-DISQUALIFYING CAVEAT / MOSTLY NOISE, plus the sharpest interview question to test it. This reconciles "retention weighs heaviest" with "don't over-block on a few snippets."

## 3. Preferences (positive signals)
- [e.g., calm/stable/founder-run; mission fit; IC track]

## 8. Working with you (interaction)
- Present decisions **one at a time**, note position ("1 of N").
- **Gather all inputs and run the screens BEFORE asking you to decide.** When asking about a boss, open the sources (their LinkedIn, company site) so you see the evidence, explain how the draft maps to LaCivita's technique, and suggest how to make it more effective/memorable/friendly.
- **Recommend, don't survey.** Ask only genuine your-calls; act autonomously otherwise. Confirm anything irreversible or outward-facing.
- **Recency check before any decision ask.** Dossiers/scorecards go stale, roles get filled, comp bands shift, bosses move. Before presenting a scorecard or asking you to decide/prep/send on a specific live role, comp figure, or seated person, RE-VERIFY it against the primary source at decision time (the company's ATS/careers page for the exact posting; the person's current title). If the posting is gone, say so and re-anchor on what's actually live before you spend a decision.
- **Human-in-the-loop at every decision point.** Any choice that shapes what goes out, which boss, which accomplishment to praise, which phrasing, which role, send vs. drop, is yours. The assistant researches and narrows to a small set of options, then presents them for your pick; it never decides unilaterally and never fires an irreversible step (mailto/send) before you choose. Present via a multiple-choice prompt or the review console so you decide without scrolling.
- **Boss-praise is a two-stage pick:** first choose 1 of 3 researched, interest-aligned accomplishments; then choose 1 of 3 phrasings in your voice. Only then is the draft finalized.
- **Ready-to-send packages are the FIRST decision option.** Whenever one or more outreach packages are ready to send (person vetted + email pre-filled + résumé tailored), present SEND as the first choice/button, ahead of new scorecards, queuing, or any other action. Finishing a ready package outranks preparing a new one.

---

## 9. Cadence and targets

⚙️ **THE OPERATING CADENCE IS 3-3-3.** **3 companies, 3 people, 3 messages, every day, on a
never-ending loop.** Adopted from Andrew LaCivita's method.

⭐ **The daily unit of work is messages SENT, not companies eliminated.** That distinction is the
whole rule. A day spent screening thirty companies and sending nothing is a day the loop did not
run. If a day produces 3 real messages it was a good day.

⛔ **3 is a FLOOR, never a cap.** Hitting 3 does not end the day.

### Why a small number, when more feels better

This replaces three contradictory volume figures the reference workspace used to carry: a 3-4/day
pacing cap, ~10 outreach/day, and 50/day. They never reconciled, actual throughput ran about
15.9/day, and **the two highest-volume days were the days the method got skipped under pressure.**
Volume bent the method instead of the method bending volume.

⚖️ **Quality gates volume: fewer researched messages beat many generic ones.** A cold boss-hunt
message needs a sourced accomplishment and a live-verified role, and that research does not
compress. Three of those beat fifteen that skipped it.

### What you will see on screen

`scripts/pair_brief.py` computes this every session and prints a line like:

```
LADDER 2026-08-09 · sent 375 · replied 61 · rate 16.3% · 3-3-3 1/3
```

The trailing `1/3` is today's message count against the floor. `scripts/check_pair.py` enforces that
the line is present and recomputed rather than carried forward from an earlier message, because a
stale count is worse than none.

⚠️ **The count only sees what reaches `documents/send-log.jsonl`.** `mail-draft.sh` writes that log
itself; a LinkedIn message does not, so log it with `scripts/log_linkedin_send.py` or the day's count,
your reply rate and the burned-target guard all read low.

### Queue depth is a different axis

**Target queue depth = 50 approval-pending matches; run discovery continuously while below 50.**
That is an inventory goal for prepared, unsent matches. It is not a send target and it never gates
surfacing. Depth is how much is ready; 3-3-3 is how much goes out.

### Adjust it deliberately, not by drifting

The number is a method, not a law of nature. Raise or lower it on purpose, in this file, and say why.
⛔ What is not allowed is letting a busy day quietly redefine it, which is the failure the three
deleted figures above came from.

## Session refinements — 2026-07-18 (generic; mirrored from the reference workspace)

- **Close the "common gaps" BEFORE surfacing — present a DECISION, not a verify-list.** When a prospect has the recurring gaps (no confirmed live role, remote/travel unverified, comp unknown, boss/email unconfirmed), RESEARCH and RESOLVE them at the gate before the candidate sees a card. Verify a live role + comp + reporting via the company's **live ATS API** (Greenhouse `boards-api.greenhouse.io/v1/boards/<token>/jobs`, Ashby `api.ashbyhq.com/posting-api/job-board/<token>?includeCompensation=true`, Lever) — NOT stale aggregators/web-search. Verify remote + travel/offsite from the JD + careers page. Then present a one-word verdict (SEND / DROP / RADAR / PREP) with only the one genuine human-call left. Unreachable fact → mark UNVERIFIED, never a passed-off task.
- **Colored status-badge decision cards.** Lead every card with a colored-emoji badge = the recommendation: 🟢 SEND · 🔵 PREP · 🟡 RADAR · 🔴 DROP · ⚪ UNVERIFIED. Card shape: `### <badge> STATUS — Company` · a **Boss · Lane** line · **a 2-3 sentence narrative (the organization, the product, and why THIS boss — the product problem they'd own + values/lane fit)** · a compact check table (✅ pass / ❌ fail / ⚠️ caution / ❓ unverified over travel · live role · remote · comp · culture · email) · a `> 👉 YOUR CALL:` line + recommendation.
- **On a RADAR (no live role), research the hiring HISTORY to time the reach.** Find when the company last posted the target role / last hired for it, and tag: 🌱 GROWING (recent hires → reach now) · 🔄 BACKFILL-GAP (someone just left → reach now) · 😴 STATIC (no movement → long-game) · 🌾 GREENFIELD (never had one → pitch "your first hire"). Best source: the person-team tenure on LinkedIn (or a paid enrich — ask first); ATS APIs are current-only; free web search is usually too thin (say so, don't guess).
- **Pre-fire conformance check (before opening the mail client) — do it LINE BY LINE.** After a boss-hunt email is fully built and BEFORE opening the mail client, inspect EACH line and map it to the LaCivita element it serves (greeting · why-this-company hook · **boss-specific praise of a real accomplishment** · brief matched offer · enthusiasm + direct ask · sign-off; + résumé attached), and check each line against the candidate's writing style (their voice; zero AI tells — no filler adverbs, no AI clichés, no em dashes, no spaces around slashes; tight). Present a per-line table (Line · text · element · ✓). If a line doesn't map to an element or breaks a style rule, fix + re-inspect; fire only when every line passes both.

## Session refinements — 2026-07-20 (generic; mirrored from the reference workspace)

- **Front-load research in PARALLEL, present BATCHED decision-ready choices.** Deep-screen the candidate group and pre-research each survivor's boss (sourced accomplishment + praise angles) CONCURRENTLY and up front, so you decide across the batch in one pass rather than watching a sequential task queue. **EXCEPTION — a confirmed, send-ready match JUMPS the batch:** push that one straight through (phrasing pick → send); the rest keep cooking in parallel and arrive as their own batch.
- **ALWAYS `Read documents/writing-style-guide.md` FRESH before writing ANYTHING in your name** — not just email voice options, but APPLICATION free-response answers, narratives, interview answers, thank-yous, LinkedIn text, collateral. In a long session the sense of your voice drifts into a generic register; re-reading the real samples resets it.
- **Email/DM whitespace:** ALL outreach breaks ONE BEAT PER PARAGRAPH with a blank line between beats (hook/praise · proof · identity · ask), never a dense block; the GREETING sits on its OWN line with a blank line before the body. `check_outreach.py` WARNs on a joined greeting and on a dense-block body.
- **Open the apply page at the apply step.** When a work item includes SUBMITTING AN APPLICATION, `open` the actual ATS application page(s) in your browser as part of executing that step (the same authoritative ATS URL the liveness check returns), so you aren't left hunting the link.
