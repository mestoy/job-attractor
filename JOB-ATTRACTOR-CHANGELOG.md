# Job Attractor Pipeline — Changelog (your copy)

A persistent, append-only record of how your pipeline evolves, so you (and anyone helping) can look back and understand why it works the way it does. **Newest at the bottom.** Add a dated entry every time you change the workflow, skills, or rules (what changed + why).

Start it with the feature set your kit ships with, then append your own changes:

## v1.0 — [install date] · Starter kit installed
- Two-session setup (content + build) on one shared folder; prep-only Job Attractor Pipeline, human-gated (never sends).
- Mandatory auto-screen before anything reaches you: blocked-list → hard filters (remote + any personal constraints, deal-breaker industries, layoffs, always-on) → culture/leadership/news → Glassdoor → fit.
- Screen from data first; a structured Match Scorecard, then a pause; the boss's LinkedIn and the company site open only after you confirm the match.
- For any wording you'll send: 3 options + a recommendation + a free-response "add your own", drawn from your writing-style guide; boss-praise is ONE specific beat mirrored by a specific accomplishment of yours.
- Review package before any send: email draft + a company-tailored résumé (`<Your Name> - Resume - <Company>.pdf`), opened for inspection.
- **Review Console** (`app/build_review_console.py` + `Open Review Console.command`): a standalone HTML you open outside the chat to click through prospects one at a time (Prep / Mark sent / Drop / Deeper probe / Full dossier). Re-run the build to refresh from your queue.
- Queue hygiene: the live queue holds ONLY items awaiting your approval; sent/dropped entries move to an archive. Target depth 20; the prep task runs continuously while below 20.
- Arm a follow-up only for a WARM contact, by email (forward the original); a cold non-reply gets a new target, not a second touch (warm-only follow-up rule).

## v1.1 — 2026-07 · Human-in-the-loop outreach + verification hardening
Capabilities added to the pipeline (generic; nothing personal baked in):
- **Verify the live JD BEFORE any scorecard/decision.** Open the actual posting and confirm remote + travel cadence + hybrid/relocation, comp band, seniority/years bar, reporting line, and role/lane from the JD text (an aggregator "remote" tag is not proof). A gated JD = mark those facts UNVERIFIED. Also run a recency check so a stale/closed posting never reaches you.
- **Verify remote AND travel cadence** from the JD, not just "remote" — a "remote" role with monthly on-site travel can still fail a no-travel constraint.
- **Deeper-probe protocol** for any potentially disqualifying signal (attrition, perf-management, exec churn, conduct, WLB) before a match is shown as GO: verbatim + attributed quotes, distinct voices vs. amplification, pattern vs. scatter, does-it-apply-to-your-org, news layer, counter-evidence → BLOCK / CAVEAT / NOISE verdict. Plus same-name-company disambiguation (make sure a scary review is about *this* company).
- **Two-stage boss-praise, human-in-the-loop.** Stage 1: research the boss and surface 3 interest-aligned accomplishments for you to choose the angle. Stage 2: 3 phrasings in your voice to choose/edit. The assistant never picks unilaterally.
- **Line-by-line outreach construction.** Build the email one beat at a time (greeting → hook → boss-praise → offer → ask → sign-off), 3 options per beat in your voice, you pick each. A single assembled draft is offered only when you want speed.
- **Human-in-the-loop at every decision point** (which boss, which praise, which phrasing, send vs. drop) — never an irreversible step (mailto/send) before you choose.
- **Résumé attach without desktop control:** use an attachment-capable mail connector (e.g. Outlook / Microsoft 365) to build the draft with the résumé attached, or self-attach the handed-over PDF. Never type into or click inside the compose window; you always send.
- **Résumé style:** left-aligned / ragged-right + no hyphenation (`ragged2e` + `\RaggedRightRightskip=0pt plus 2.5cm` + `\hyphenpenalty/\exhyphenpenalty=10000`, no `\emergencystretch`) so words wrap whole instead of breaking.
- **Commit everything after EVERY outreach** (send AND drop): log the exact copy + bounce status (or drop reason), a tracker row, move the queue entry to the archive, fold any voice edits into your style guide, and record any new rule.

## Rule — No open req is not a disqualifier (value-reach)
- Boss-hunting communicates value to the boss regardless of a job opening (LaCivita). Live-JD verification catches hard-filter violations WHEN a role exists (travel, hybrid, comp, reporting line, lane); it does not require that one exist.
- No live role → reframe as a value-reach (radar): verify company-level remote/travel/industry/culture and reach out on value, with comp as a conversation-time question. "No live role" is a scorecard flag, never a drop.
- Only company-level reasons that hold regardless of any opening are drops: hard-filter fails (remote-absolute, firm no-travel e.g. mandatory offsites), deal-breaker industries, toxic/grindset/AI-mandate culture, layoffs/instability.

## [your next entry] — [date] · [what changed]
- ...

## 2026-08-31 · The Power Story (kit issue #75)
- New `/power-story <company>`: from the operator's locked CA²R library, run the match test against the seat's job-to-be-done (same problem shape · same actor position · same constraint · a true continuation), present the picker with the top match as option 1, then co build the entry-point phrases, the 60 to 90 second telling, the continuation beat, the chapters, and the second-chair story into that interview's prep doc. Chosen from the rack, never drafted; the library stays the one canonical copy.
- `/interview` Step 3.0 calls it before the question list; stage 2 documents the rule, stage 3 routes the first legitimate question through the entry point, stage 5's card carries the Power Story line.
- Wording: `/interview` now says CA²R (Approach¹ names the steps, Approach² walks them) instead of CAAR, matching the stage 2 skill.
