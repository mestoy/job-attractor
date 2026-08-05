# /narrative-audit - Employer research and career-collateral honesty audit

**Goal:** ground your career narrative in official and public sources so every depiction of your employment history is honest, accurate, AND rich. For a given employer: research what the company itself published, audit your collateral against it, surface the gaps with explanations and options, then store a durable, honesty-calibrated employer narrative you can reuse in interviews and future collateral.

⛔ **Never fabricate. Prefer the defensible claim over the punchy one.** A punchy claim you cannot source is a claim that fails in the room where it matters.

Invoke: `/narrative-audit <employer>`, or `/narrative-audit all` to iterate one at a time.

## Run it automatically

- **A new employer enters your history → run this without being asked.** Audit before the claim propagates into collateral, because a wrong figure spreads faster than it gets corrected.
- **At interview prep → re-run for the relevant employers.** Companies change: leadership moves, figures update, sites get archived or acquired. Stored narratives carry a research date; if it is stale, re-verify.

---

## Phase 1 - Research the employer, official and public sources only

- ⚠️ **Disambiguate same-name entities FIRST.** Two companies routinely share a brand, and researching the wrong one produces a narrative that is confidently false. Confirm the right company AND the right era.
- Search the company's own material and verifiable public sources: the company site (plus the Wayback Machine for defunct or acquired sites), leadership interviews, talks, podcasts, press releases, funding and acquisition coverage, case studies, filings, and named-author blog posts.
- Extract and record:
  - **Leadership names and titles.** Who built or led the thing, and who authored the approach.
  - **The company's documented approach or philosophy.** Quote it rather than paraphrasing.
  - **Verifiable figures** and, just as important, their ATTRIBUTION.
  - **Timeline:** what predated your tenure against what happened during it. **This is the crux of honest attribution.**
- ⛔ **Separate the COMPANY's build from YOUR contribution.** A number the founders spent a decade building is backdrop you may cite, never an achievement you may claim.
- Note anything unverifiable explicitly. Do not launder a memory-sourced claim into a sourced one.

## Phase 2 - Audit your collateral against the research

Gather every place this employer appears: your résumé files, `documents/PROFILE.md`, your website or portfolio, your LinkedIn, and any interview prep notes. Compare each claim to the sourced facts and classify:

- 🔴 **OVERSTATE or MISATTRIBUTE.** Credits you with more than your role supports, claims a company figure as yours, or states an illustrative metric as real. **Honesty risk, fix it.**
- 🟡 **IMPRECISE or UNVERIFIED.** Plausibly true but loosely worded or unsourced. Tighten to the defensible version.
- 🟢 **ACCURATE.** Well supported. Keep it, and record the source so you can cite it.
- 🔵 **MISSED OPPORTUNITY.** A documented fact, quote, or approach you could ADD to make the narrative richer and more credible. Proactively suggest: real numbers you can legitimately claim; company proof points you can cite as attributed backdrop; stronger TRUE reframes that beat a weak claim; and **figures you likely have but never captured** (adoption, users, time or cost saved, throughput, revenue). ⛔ Never invent them. Ask.

## Phase 3 - Present, decide, apply, store

- Present findings **one employer at a time, most severe first.** For each: explain WHY, cite the source, and give OPTIONS (keep, tighten, reframe, add source-backed detail). **You decide each one.** Never auto-rewrite someone's history.
- Apply the decisions to the CANONICAL sources first (`documents/PROFILE.md`), then to any live collateral via `/collateral`.
- ⛔ **Do NOT retroactively sweep résumés you have already sent.** Sent is sent. Update a sent variant only if you re-engage that organization.
- **Store durably:** write the calibrated narrative to `documents/employer-narratives/<employer>.md` with the research, the honest attribution line, a talking track, and questions to ask. A finding that lives only in a chat log runs only when someone remembers it.

## Guardrails

- Honesty first. Company approach and personal contribution stay distinct. Never fabricate.
- Sources are official and public only. Flag anything unverifiable rather than asserting it.

## Voice

When writing any narrative or talking track in your name, generate FROM `documents/writing-samples.md` and `documents/writing-style-guide.md`. Zero AI tells, never a generic register. If the corpus is empty, run `/voice-setup` first.
