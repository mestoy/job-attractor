---
name: narrative-audit
description: Guided employer-context builder + career-collateral honesty audit. For each of your employers, research what the company officially published, then check your own résumé/profile/LinkedIn/interview-prep against it — surfacing honesty deltas, richer source-backed detail, and options — so your employment history is accurate AND compelling. Runs automatically for a new employer and re-runs at interview prep. Then triggers a collateral refresh.
---

# Narrative Audit skill (generic starter)

**Goal:** most candidates carry vague or unverified claims about past employers ("grew the network," "cut time 90%") that a sharp interviewer can poke holes in. This skill fixes that: it grounds every employer in **official/public sources**, separates *what the company did* from *what YOU did*, and turns weak/risky claims into specific, defensible ones — while surfacing figures that make you stronger. **Never fabricate. Prefer the defensible claim over the punchy one.**

Fill `documents/PROFILE.md` (via `/setup`) first — that's your identity, roles, and honesty guardrails.

## When it runs (walk the user through it)
- **On first setup / whenever a NEW employer is added:** run it automatically before that claim spreads into collateral. Don't wait to be asked.
- **At interview prep:** re-run for the employers that will come up — companies change (leadership moves, figures update, sites get acquired/archived). Stored narratives carry a research date; if stale, re-verify.
- **On demand:** the user asks to audit an employer or "all."

## The walkthrough (one employer at a time)
**Phase 1 — Research the employer (official/public only).**
1. Disambiguate same-name companies first; confirm the right company + era.
2. Search the company's OWN material + verifiable public sources about the work the user did: company site (+ web archive for defunct/acquired sites), leadership interviews/talks/podcasts, press releases, funding/acquisition coverage, case studies, filings, named-author blog posts/white papers.
3. Capture: leadership names/titles; the company's documented approach/philosophy (quote it); verifiable figures + their ATTRIBUTION; the **timeline** (what predated the user's tenure vs. happened during it).
4. **Separate the COMPANY's build from the USER's personal contribution** — this is the crux of honest attribution.
5. Note anything unverifiable explicitly.

**Phase 2 — Audit the user's collateral against the research.** Gather every place this employer appears (résumé[s], `documents/PROFILE.md`, LinkedIn export, portfolio/site, interview notes) and classify each claim:
- 🔴 **OVERSTATE / MISATTRIBUTE** — credits the user with more than their role/the record supports; a company figure claimed as theirs; an illustrative metric stated as real; **an outcome that happened after they left**. Honesty risk → fix.
- 🟡 **IMPRECISE / UNVERIFIED** — plausibly true but loosely worded or unsourced; tighten to the defensible version.
- 🟢 **ACCURATE** — well-supported; keep (note the source so they can cite it).
- 🔵 **STRENGTHEN** — a documented fact/quote/approach to ADD; **proactively suggest other figures/outcomes that strengthen the narrative**: (a) real numbers they can legitimately claim; (b) company proof-points cited as *attributed* backdrop; (c) stronger TRUE reframes that beat a weak/risky claim; (d) **prompt the user for figures they likely have but haven't captured** (adoption %, users, time/cost saved, throughput, revenue) — never invent; ask.

**Phase 3 — Present, decide, refresh, store.**
- Present deltas **one employer at a time, most-severe first**. For each: explain WHY, cite the source, give **options** (keep / tighten / reframe / add). The user decides each — never auto-rewrite their history.
- **Trigger a collateral refresh:** apply approved changes to the CANONICAL profile + any ACTIVE/live collateral. (LinkedIn = give the user the corrected text to paste; they own that edit.) **Do NOT retroactively re-edit résumés already SENT — only refresh a sent org's résumé if the user re-engages that org.**
- **Store the calibrated narrative** to `documents/employer-narratives/<employer>.md` (research + honest-attribution line + talking track + questions-to-ask) so interviews and future collateral reuse the calibrated version.

## Guardrails
- Honesty-first; company-approach vs. personal-contribution kept distinct; never fabricate; flag unverifiable items rather than asserting them; disambiguate same-name entities.
- Sources = official/public only (company site, leadership interviews, press, filings, verifiable case studies).
