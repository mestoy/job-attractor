# Handoff — Main (single source of truth) — TEMPLATE

**Read this first.** This is the shared source of truth for a job search run across coordinated Claude sessions that all share one folder. If anything elsewhere conflicts with this file, this file wins.

> **This is a generic template. It contains no personal, customer, or secret data.** Replace every **[PLACEHOLDER]** with your own content before relying on it. Each session reads this file first.

## Shared conventions (keep all sessions in sync)
- Prefer **"main"** or **"primary"** over "master."
- The full operating rules live in **`WORKFLOW-RULES.md`** (filters, screening, outreach, résumé, interview, honesty guardrails). Read it alongside this file.
- Add shared wording preferences here as they come up.

## Division of labor
- **Content/strategy session** owns strategy and content: what the résumé says, which claims are honest, positioning, interview prep, screening decisions.
- **Build session (Claude Code in a terminal)** owns the programmatic build: the LaTeX résumé system (`main_<company>.tex` → PDF), scripts, and packaging.
- Résumés build in **LaTeX**: `pdflatex` for the 1-page plain-professional template (see `templates/cv/plain-professional/`); `lualatex` for any 2-page moderncv variants.

## Where things live
- `WORKFLOW-RULES.md` — the operating system (how the search runs).
- `documents/PROFILE.md` — your profile (the single source of truth); `CLAUDE.md` is a lean index that points at it.
- `.claude/skills/job-application-assistant/01-07*.md` — your profile files (run `/setup`).
- `.claude/commands/` — the slash-command workflows (`/matrix-hunt`, `/radar-outreach`, `/apply`, `/rank`, `/interview`, ...).
- `deliverables/` — shared outputs and handoffs (this folder).
- `main_<company>.tex` — your per-role résumé builds (you create these).
- `[your private folder]/` — raw source material and candid judgments. **Keep private; sanitize before sharing.**

## Honesty guardrails (do not violate) — FILL WITH YOUR OWN
- Verify every metric against a primary source; tenure-scope figures. If a source is gone, retire the number and describe the method + outcome instead.
- Scope claims precisely: what **you** did vs. the team/an engineer. Don't take sole credit for org-wide outcomes. Don't fabricate.
- [List your specific naming, figure, and scope corrections here.]

## Skills / claims verification — FILL WITH YOUR OWN
- **Claim (substantiated):** [what your source docs actually support].
- **Qualify (real but limited):** [true but narrower than it sounds].
- **Avoid:** [claims you cannot back].

## The multi-session workflow
- **One shared folder** is connected to every session; all sessions read/write it, so nothing is siloed.
- **This file is the single source of truth;** every session reads it first.
- **Start a session by pasting:** "You're my [content | build] session in our shared folder. Read `deliverables/UBE_HANDOFF_MAIN.md` first and follow its rules and guardrails. Then: <task>. Ask me before anything irreversible."

## Safety
- Never send, publish, email, push, or take an irreversible action without explicit human approval.
- Never commit or share secrets. Before any external hand-off, sanitize: API keys, tokens, service URLs/project refs, internal emails/personal names, customer or regulated (CUI) references.
- When unsure whether something is sensitive, redact it and flag it for review.

## Superseded (ignore these)
- [List any parallel/retired artifacts so sessions don't use the wrong one.]

*Generic template — no personal, customer, or secret data. Replace all [PLACEHOLDER] sections with your own.*
