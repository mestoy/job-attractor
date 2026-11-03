# /matrix-hunt - Matrix-Driven Company Discovery & Boss Hunting

You are running a **matrix hunt** (Andrew LaCivita's method): instead of reacting to job postings, you **proactively discover companies that score high on the candidate's Employer Criteria Matrix**, screen them, and go direct to the would-be boss with a warm outreach message — whether or not a role is posted.

This is the **front half** that `/apply` (live postings) and `/radar-outreach` (a specific named company) don't cover: it **generates the target list** from the candidate's own criteria, then hands the survivors into the outreach flow. Company discovery is driven by the **matrix**, not a job board.

`$ARGUMENTS` may contain a focus (a sector/lane), a company count (`--n 10`, default ~10 discovered / ~3-5 surfaced), or nothing (hunt broadly across the candidate's lanes).

Follow these steps **in order**. Never skip the culture screen (Step 4) — never spend a warm introduction on a company that fails culture.

---

## Step 1: Load the Matrix + Profile

Read once and hold in context:
- The candidate's **Employer Criteria Matrix** — a weighted scorecard of what they want (each criterion: weight × 1–10 rating). Extract the top-tier **walk-away must-haves** (the hard filters) and the tier weights. If the candidate hasn't built one yet, help them create it first (see the onboarding guide).
- `.claude/skills/job-application-assistant/01-candidate-profile.md` (lanes, history) and `04-job-evaluation.md` (deal-breakers, calibrations).

**The hard filters that gate discovery:** whatever the candidate has marked non-negotiable — typically **permanently remote**, **no required travel**, and all **deal-breaker industries**. These gate; a miss drops the company immediately. Comp and equity targets are usually **scoring factors, not hard filters** — check the candidate's matrix for which is which.

## Step 2: Discover Candidate Companies (from criteria, NOT job boards)

Generate a candidate set of ~10 (or `--n`) companies that plausibly score high on the matrix, using WebSearch + curated lists — **not** `/scrape`'s job-portal CLIs. Sources to draw on:
- The candidate's target lanes (from `01-candidate-profile.md` / `04-job-evaluation.md`).
- "Best remote-first companies," "calm company" / no-grindset lists, bootstrapped/profitable founder-led SaaS, B-corps / mission-driven orgs, and companies whose public posture matches the candidate's must-haves.
- **Seed with bootstrapped / profitable / founder-stable / genuinely remote-first companies rather than hot VC-funded unicorns** — the latter are often in post-growth correction (layoffs, RTO mandates, leadership churn) and rarely survive the screen.
- Companies already surfaced as strong culture in prior screens are fair game to (re)target even with no live role.

De-dupe against `job_search_tracker.csv` (already applied/contacted) and `job_scraper/seen_jobs.json`, and against any private "blocked/declined companies" list the candidate keeps. Skip anything already pursued or excluded.

## Step 3: Matrix-Score the Candidates

For each discovered company, score against the matrix rather than a single posting:
- **Hard filters first** — does it clear every walk-away must-have? A miss = drop it now.
- **Weighted criteria** — score the rest (comp band, PTO, autonomy, a boss who develops people, trust/output-not-presence, interesting work, transparency, etc.).
- Favor **quiet/stable/mature** and **mission-driven** companies if those are positives for the candidate.
- Produce a short ranked list with a matrix-fit read + a **product-leader angle**: 1–3 lines on the product/market/strategy problem the candidate would own, not just the fit scoring.

Present the ranked candidates and let the candidate pick which to pursue (default: the top ~3-5), OR proceed to screen the top few if they said "just go."

## Step 4: Culture-First Screen (MANDATORY — never skip)

For each company to pursue, run the full screen BEFORE any outreach — this is the gate. Run the layers in order; a fail at any layer drops the company:
1. **Blocked list + hard-filter industries** — check the candidate's "already declined" list and deal-breaker industries first (cheapest veto).
2. **Industry news (last ~12 mo)** — layoffs (esp. recurring/annual), PE cost-cutting, restructuring, lawsuits, regulatory/conduct issues, leadership exits.
3. **Culture** — Glassdoor overall (rating / %recommend / recent trend) + the most recent positive AND negative themes, **each backed by 2-3 short verbatim quotes** (with recency + reviewer role where visible). Watch for review-gaming ("cult-like," "told to write good reviews," an implausibly perfect score beside angry recent reviews).
4. **Leadership stability + retention** — founder/CEO stable? Recent turnover — healthy (upgrade hires) or dysfunction (exodus, high turnover, feedback suppression)? Weak leadership + high turnover is a block.
5. **Remote reality + location** — confirm the remote/hybrid policy against the hard filter, from the company's **own job listings**, not a third-party guess. Drift toward hybrid counts as a fail if remote is non-negotiable.

**If it fails, report why (with quotes) and drop it. Do NOT outreach a culture-fail.** Only survivors continue.

## Step 5: Identify the Would-Be Boss (the LIKELY BOSS, derived — not a title ladder)

For each survivor, find the person who would actually MANAGE this role, derived from how the company is built rather than read off a title ladder. **Real product org** → usually the seated product leader (CPO / VP / Head / Director of Product). **No product function** → the founder, CEO, or COO IS the likely boss, which is a first-class answer and not a fallback. A would-be **peer** is valid for a relationship-first note. Never HR, never a recruiter. ⚖️ **Founder ordering:** among several plausible bosses the founder or CEO is the LAST choice; if a founder is the only one you can find, target them without hesitation. **Verify the person currently holds that role** (people move on — a note to someone who left is wasted). **Only use a real, verifiable LinkedIn profile** (via WebSearch); never fabricate; flag partial matches.

## Step 6: Boss-Hunt Outreach (candidate's voice, channel decided together)

- Draft in the candidate's voice — read `03-writing-style.md` and `02-behavioral-profile.md` first (plain/warm/concrete; understated wit baked in, never announced; no announced-label openers; match whatever style rules the candidate has set, e.g. no em-dashes).
- **Framing:** forward-looking — "I'd like to be on your radar / I think you may be looking for someone like me," decoupled from any posting. Weave in the strongest matrix-aligned reason *this* company draws the candidate + one plain line on what they do. Verify any company-specific claim first.
- **Review the draft** through a quick multi-lens check (how does it read to a CEO / an engineer / a product leader?) and fix what's off.
- **Decide the channel together** (LinkedIn / email / both); deliver email as a prefilled draft you review and send (subject + body, via the `outreach-send-prep` skill); flag inferred addresses as inferred. On LinkedIn, a single connection request *with* the note is one clean touch — don't also send a separate message.
- **Log** each sent message to an outreach log (newest first) and add a `contacted` row to `job_search_tracker.csv` (contact person + title + verified profile; note "watch board for a role to open").

---

## Rules

1. **Matrix drives discovery.** Companies come from the candidate's criteria, not job boards.
2. **Culture-first, always.** Screen before outreach; a culture fail is dropped even at a perfect matrix score.
3. **Hard filters gate; scoring factors rank.** Check the matrix for which is which.
4. **Target the LIKELY BOSS**, whoever would actually manage the role, derived from how the company is built rather than a title ladder; verifiable, current profiles only.
5. **Quotes when flagging culture;** review every draft; decide channel together; no cover letters.
6. Complements `/apply` and `/radar-outreach` — this one **generates** the targets; hand survivors into the same outreach + logging flow.
