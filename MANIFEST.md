# MANIFEST — job-application-assistant starter

What this package contains, where each piece is meant to go, and whether it **creates**, **merges into**, or **must not overwrite** something in your repo.

## Read this first (the guardrails you asked for)
- **Nothing here auto-installs. Nothing touches your repo until you copy it yourself.** This is a manifest to review against your working repo before anything moves.
- **I cannot see your machine or repo.** Destination paths below are *intended* locations relative to your repo root. **You must diff before copying** — do not trust a path blindly.
- **Never overwrite your personalized files.** Your filled-in `documents/PROFILE.md`, your profile files (`01-07`), your `main_*.tex`, your finished PDFs, your `job_search_tracker.csv`, and your Glassdoor/notes are yours. The starter's versions of those are **blank templates** — copying them over your real ones would be a downgrade. Where a name collides, the rule is **KEEP-YOURS**.
- **Fully sanitized and parameterized.** The docs, templates, skills, AND scripts carry no other person's name, contact details, PII, customers, or secrets. Every script reads its person-specific values (your name, email, site, phone, retired-claim list, screening filters) from **`scripts/kit_config.py`** (or matching environment variables) — nothing is baked in. Fill in `kit_config.py` once (or run `/setup`) and the whole toolchain is yours.
- If you already have a working pipeline, the **only genuinely new value** for you is the **multi-session layer** (rows marked ★). The rest you likely already have in better, personalized form.

## Action legend
- **CREATE** — new file; safe to add if you don't have it.
- **MERGE** — add only the parts you're missing; don't clobber your version.
- **KEEP-YOURS** — you already have a personalized version; do **not** overwrite. The starter copy is a blank template for reference only.
- **OPTIONAL** — nice to have; skip if not relevant.

## Files

| Package path | Intended destination | Action | Notes |
|---|---|---|---|
| ★ `WORKFLOW-RULES.md` | `<repo>/WORKFLOW-RULES.md` | **CREATE** | The operating system (filters, screening, outreach, résumé, interview, honesty, cadence). Fill the `[BRACKETS]`. This is the main thing you're missing. |
| ★ `deliverables/UBE_HANDOFF_MAIN.md` | `<repo>/deliverables/UBE_HANDOFF_MAIN.md` | **CREATE** | The multi-session single-source-of-truth. Fill the `[PLACEHOLDER]`s. This is the file your other session was complaining was missing. |
| ★ `ONBOARDING-GUIDE.md` §12–13 | (reference) | **MERGE** | New sections: multi-session sync + browser automation (opening LinkedIn/application tabs via Claude-in-Chrome). Copy those two sections into your own guide/notes if useful. |
| `.claude/commands/*.md` (11) | `<repo>/.claude/commands/` | **MERGE** | Add any command you don't have (`matrix-hunt`, `radar-outreach`, `apply`, `rank`, `interview`, `outcome`, `expand`, `setup`, `add-portal`, `add-template`, `reset`). If you already have a personalized one, keep yours. |
| `.claude/skills/job-application-assistant/SKILL.md` | `<repo>/.claude/skills/job-application-assistant/` | **MERGE** | Skill definition; keep yours if customized. |
| `.claude/skills/job-application-assistant/01-07*.md` | same | **KEEP-YOURS** | Blank profile templates. **Do NOT overwrite your filled-in profile.** |
| `.claude/skills/job-scraper/*` (3) | `<repo>/.claude/skills/job-scraper/` | **MERGE** | Scraper skill + browser sources + generic search queries. |
| `.claude/skills/upskill/SKILL.md` | same | **MERGE** | Skill-gap/learning-plan command. |
| `.agents/skills/*` (5 CLIs) | `<repo>/.agents/skills/` | **OPTIONAL** | Job-board search CLIs (bestpmjobs, builtin, hiring-cafe, linkedin, wttj). TypeScript; run `bun install` in each `cli/`. Skip if you don't scrape. |
| `templates/cv/plain-professional/template.tex` | `<repo>/templates/…` | **KEEP-YOURS / OPTIONAL** | A generic 1-page LaTeX résumé template. You already have working `main_*.tex` — keep them. |
| `CLAUDE.md` | `<repo>/CLAUDE.md` | **KEEP-YOURS** | Lean index that points at `documents/PROFILE.md` — you never fill it. If you have a filled-in `CLAUDE.md` from the old model, migrate its facts into `documents/PROFILE.md` (see `partner-docs/MIGRATION-2026-07.md`). |
| `README.md`, `ONBOARDING-GUIDE.md` (full) | (reference) | **OPTIONAL** | Read-only docs; no need to install. |
| `scripts/*.py`, `scripts/*.sh` (tripwires) | `<repo>/scripts/` | **MERGE** | Parameterized workflow-enforcement tripwires (identity via `kit_config.py`). `kit_config.py` (fill this first), `check_dup.py` (dedup across all stores), `verify_resume.py` (résumé QA incl. no-1st-person Summary), `check_outreach.py` (send-time AI-tell/format scrub), `check_screen_gate.py` (candidate is decision-ready before surfacing), `check_followups.py` (overdue follow-ups), `record_decision.py`/`record_chat_ruling.py` (the BUILD-ruling ledger writers), `consistency-check.sh` (one consolidated preflight; set `JOBSEARCH_MEMORY_DIR` or it skips the memory check). |
| `MANIFEST.md` | (this file) | — | — |

## Recommended install (given you already have a working repo)
1. `WORKFLOW-RULES.md` → repo root; fill the `[BRACKETS]` with your own filters/preferences.
2. `deliverables/UBE_HANDOFF_MAIN.md` → create `deliverables/`; fill the `[PLACEHOLDER]`s. Point every session at it first.
3. Copy `ONBOARDING-GUIDE.md` §12 (multi-session sync) + §13 (browser automation) into your notes; connect **Claude-in-Chrome** at claude.ai/chrome.
4. From `.claude/commands/` and `.claude/skills/`, add only the ones you don't already have.
5. Leave everything else (your profile, CLAUDE.md, main_*.tex, PDFs, tracker) exactly as-is.

## What this does NOT change vs. a working LaTeX repo
- It does not replace your LaTeX résumé pipeline (that's canonical; keep pdflatex/lualatex).
- It adds no DOCX toolchain and needs no `soffice`.
- It touches none of your personalized data. Your hunt stays yours.

---

## v2.x mechanisms (added 2026-07-19 — the enforcement layer, for selective sync)

The `scripts/` here are the parameterized enforcement layer; the genericized rulebook/checklist docs ship under **`partner-docs/`**. All identity flows through `kit_config.py` — there are no baked-in constants to swap. Fill `kit_config.py` (or run `/setup`) and copy `.claude/settings.example.json` → `.claude/settings.json` to wire the hooks.

| Package path | Intended destination | Action | Notes |
|---|---|---|---|
| `scripts/mail-draft.sh` | `<repo>/scripts/` | **MERGE / reference** | AppleScript Apple-Mail draft builder (visible, NEVER sends). Gates a boss-hunt send on `--company` (dedup at send, `--send-gate` mode), `--praise-source` (must carry a primary-source URL), `--praise-phrasing` (the Stage-2-approved text, must appear verbatim in the body), `--lacivita-check pass`, `check_outreach` body lint, and résumé-attachment naming. Normalizes body LF→CR so iOS Mail doesn't render the body quoted (v2.4). |
| `scripts/check_preview.py` | `<repo>/scripts/` (+ `PreToolUse` hook) | **MERGE / reference** | PreToolUse hook that lints an `AskUserQuestion`'s option label/description/**preview** text against the banned-word list BEFORE the question renders (the linter never sees previews otherwise). Fail-open so a hook bug can't block your questions. Wire it via `.claude/settings.example.json`. |
| `.claude/settings.example.json` | `<repo>/.claude/settings.json` | **MERGE** | Shows the `PreToolUse`→`check_preview.py` hook + the existing `Stop`→`consistency-check.sh` hook. Merge the hooks block; keep your own permissions. |
| `partner-docs/HARD-INVARIANTS.md` (seeded to `documents/` by install.sh) | `<repo>/documents/` | **CREATE / reference** | The re-read-at-every-gate card: SCREEN GATE + BUILD GATE + SEND GATE + RULE-EDIT GUARD + PUSH-ALWAYS. Genericized — your honesty guardrails and filters come from `kit_config.py`. |
| `documents/ENFORCEMENT-REGISTER.md` | `<repo>/documents/` | **CREATE** | Canonical map of rule → enforcement status (✅ enforced / ⚠️ partial / ❌ honor-system) → owning script. The "which rules actually have a tripwire" audit. |
| `documents/culture-screen-checklist.md` | `<repo>/documents/` | **CREATE / reference** | The DEEP culture screen (sub-ratings + 5 recent pos/5 neg verbatim + TREND read + entity-disambiguation). The headline rating is a false-positive risk. Includes the PE-owned default-deal-breaker gate. |
| `documents/boss-research-checklist.md` | `<repo>/documents/` | **CREATE** | Glassdoor-grade rigor on the boss praise beat: attribution-disambiguation + PRIMARY-source verification (drop secondhand-only metrics) + citation + recency + specificity. |
| `documents/email-body-checklist.md` | `<repo>/documents/` | **CREATE / reference** | Outreach-body format gate (greeting, para spacing, 2-blank-line signature + website, zero AI-tells). Show drafts in a fenced code block so spacing renders literally. |
| `documents/resume-build-checklist.md` | `<repo>/documents/` | **CREATE / reference** | Résumé QA gate + the deliverable-naming rule (attach `<Name> - Resume - <Company>.pdf`, never the internal `main_<co>.pdf`). |

**check_screen_gate.py / verify_resume.py / check_outreach.py updated** in this drop: industry-veto + verdict-not-mention gates + PE-ownership flag (screen gate); BANNED/RETIRED/not-an-engineer/Claude-Code scan + `% QA-EXEMPT` grandfathering for already-sent résumés (verify_resume). See `JOB-ATTRACTOR-CHANGELOG.md` v2.2–v2.8.

| `documents/green-board.md` (created empty by install.sh) | `<repo>/documents/` | **CREATE** | The 🟢 BUILD-READY board: the 6-gate bar (dedup · remote-confirmed · non-PE · deep-culture-clean · industry-cleared · boss+primary-sourced-accomplishment) and a running list toward your green goal. Ships empty; you fill it as you harvest true greens, multi-wave. |
