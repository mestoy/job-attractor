# Kit Migration — July 2026 (read this before/after the maintainer's force-push)

**Who this is for:** you (the kit user) **and your Claude Code assistant.** Your assistant can read this file and walk you through every step.

## What happened and why
An audit found the previously distributed kit had two problems: (1) it shipped some of the maintainer's **personal data** (a personal operating-rules doc, a contact list, identity baked into scripts), and (2) it was **not functional for a second user** — the résumé and outreach gates rejected anyone who wasn't the maintainer, the rulebook docs were missing, and the "BUILD" gate could never be satisfied.

The kit has been **rebuilt clean and parameterized** (your identity now comes from `scripts/kit_config.py`, nothing is baked in), and the repository **history was rewritten** to purge the personal data from all past commits. That rewrite requires a **force-push**, which is why your local copy needs a one-time update.

## The single most important fact: YOU DO NOT LOSE YOUR DATA
Your personal working files live in the **`documents/` folder, which is git-ignored** — it exists only on your machine and was never part of the repository. The history rewrite and force-push touch only repo-tracked files, so **they cannot affect your `documents/`.** The data being removed is the maintainer's, not yours.

## Before you do anything (30-second safety net)
Make a dated backup of your private folder, just in case:
```
cp -R documents ~/job-kit-documents-backup-$(date +%F)
```
That's it — that folder holds everything that is uniquely yours (`PROFILE.md`, outreach logs, résumés, blocked list).

## The safe update — NO deletion needed
Once the maintainer confirms the force-push is done, in your kit folder:
```
git fetch origin
git status                       # confirm you have no un-pushed local commits to tracked files
git reset --hard origin/main     # move onto the new history; your git-ignored documents/ is untouched
git clean -fdn                   # DRY RUN: shows untracked files that a clean WOULD remove — review it
                                 # (do NOT run `git clean -fd` unless you've read the list; documents/ is
                                 #  ignored so -fd won't touch it, but review before removing anything)
bash install.sh                  # non-destructive: seeds any NEW template files, never overwrites yours
```

## Then make it yours (identity)
The scripts read your identity from `scripts/kit_config.py` (or environment variables). Either edit that file, or export:
```
export JOBKIT_OWNER_NAME="Your Name"
export JOBKIT_OWNER_EMAIL="you@example.com"
export JOBKIT_OWNER_SITE="yoursite.example"
export JOBKIT_OWNER_PHONE="555-0100"     # the fragment that appears in your résumé PDF text
```
Or just open the folder in Claude Code and run **`/setup`** — it interviews you and fills `documents/PROFILE.md`.

## Wire the enforcement hooks (new — this is what un-blocks the workflow)
Copy the example settings into place so the gates fire:
```
cp .claude/settings.example.json .claude/settings.json
```
This wires the pre-send lint, the BUILD-ledger writer (`record_decision.py` — now shipped, so the BUILD gate is satisfiable), and the session briefing.

## Verify it works for YOU (2 minutes)
- `python3 scripts/verify_resume.py <your résumé>.pdf` → should PASS on YOUR site/email now (not the maintainer's).
- Draft a test outreach body with your own name + site → `python3 scripts/check_outreach.py <body>.txt` → should pass with your signature.
- Your assistant should read `partner-docs/HARD-INVARIANTS.md` and the checklists (now present) — those are the gate cards.

## Fallback (only if the reset looks wrong)
Back up `documents/` (above), delete the kit folder, `git clone` fresh, copy your `documents/` back in, run `install.sh`, set identity. Same end state.

## Questions your assistant can answer from the repo
- "What changed?" → this file + `README.md` + `partner-docs/`.
- "Is my data safe?" → yes; `documents/` is git-ignored and local-only.
- "What do the gates do?" → `partner-docs/HARD-INVARIANTS.md` and the checklist docs.
