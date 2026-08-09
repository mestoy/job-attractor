# Job Attractor Kit

A Claude Code workspace that runs your job search as a repeatable pipeline.

It discovers companies that fit *your* criteria, screens them hard before you spend effort,
verifies the actual hiring manager, drafts outreach in *your* voice, and tracks every outcome.
The outreach method is Andrew LaCivita's boss-hunt.

**It never sends, connects, or applies to anything itself. You always hit send.**

**Your data stays yours.** Everything you fill in lives in `documents/`, which is git-ignored.
It is never committed and never pushed. Only the generic tooling is shared.

---

## What you need first

- **[Claude Code](https://claude.com/claude-code)** — the kit runs inside it.
- **macOS or Linux.**
- Optional, for résumé building: `pdflatex` + `pdftotext`
  (`brew install --cask basictex && brew install poppler`, or `texlive-latex-recommended` +
  `poppler-utils` on Linux).
- Optional, for job-board search: [`bun`](https://bun.sh).

Not sure what you have? Run `python3 scripts/doctor.py` at any point. It changes nothing, and it
tells you exactly what is missing and the command to fix it.

## Getting started (about 20 minutes)

```
# If you were given access to the PRIVATE kit repo, clone that one:
git clone https://github.com/mestoy/job-attractor-kit job-search && cd job-search

# No access? The PUBLIC snapshot is read-only and cannot receive updates:
#   git clone https://github.com/mestoy/job-attractor job-search && cd job-search
bash install.sh .
```

Then open the folder in Claude Code and type:

```
/setup
```

`/setup` interviews you and writes everything: your profile, your identity, your deal-breakers, and
the enforcement hooks. **You never edit a config file by hand.**

That is the whole setup. Then:

```
/matrix-hunt            find and screen companies that fit you
/apply <job posting>    tailor your résumé and answers for a specific role
```

---

## How it works

Two halves, one folder:

- **The job-search assistant** — `/setup`, `/matrix-hunt`, `/apply`, `/rank`, `/interview`,
  `/outcome`, `/radar-outreach`, `/jd-fit`, `/expand`.
- **The boss-hunt pipeline** — screens a company, verifies the would-be boss, and drafts a
  LaCivita-style outreach email in your voice, queued for you to review and send.

The pipeline keeps a **review queue**. You read each draft, make it sound like you, and send it
yourself. Email first with your résumé attached; LinkedIn is the roughly one-week follow-up.

### The gates

Judgment is not the weak link in a job search. Volume is. These keep running after you stop being
careful, and each one exits non-zero and prints what to fix.

| Gate | What it stops |
|---|---|
| `check_dup.py` | Pitching a company you already contacted, or one you blocked |
| `check_ats.py` | Writing "I saw your opening" when there is no live role |
| `check_outreach.py` | Sending a draft with a retired claim or a filler word in it |
| `check_followups.py` | Losing a follow-up you armed and forgot |
| `verify_resume.py` | A résumé that runs to two pages or has no ATS text layer |
| `check_preview.py` | Being asked to approve outreach you were never shown a scorecard for |
| `check_screen_gate.py` | Deciding on a company while a screening layer still has no evidence |
| `doctor.py` | Discovering three weeks in that the hooks were never wired |

### Honesty is load-bearing

`RETIRED` and `RETIRED_PATTERNS` in `scripts/kit_config.py` ship **empty**, and `/setup` only fills
them if you name a claim you have corrected. They encode figures *you* got wrong once, so nobody
else's list helps you. Until you fill them, the scripts say so out loud rather than pretending to
check.

Screening filters are the opposite: `/setup` **interviews you** for your deal-breakers and writes
them. An empty screening list does not screen nothing loudly. It passes everything silently.

---

## Staying current

Double-click **`Update Kit.command`**, or run:

```
git pull && bash install.sh .
```

Your `documents/` folder — profile, blocked list, outreach log, résumés — is git-ignored, so it is
never touched and never pushed.

## Working with a partner

Two people can clone the same repo, pull the same tooling, and keep entirely separate private
`documents/`. One person pushes a tooling improvement, everyone else pulls it. To contribute back,
edit a file **outside** `documents/` and open a pull request.

## Optional: two sessions

On heavier days some people run **two Claude Code sessions** on the same folder, one for strategy
and one for building, each starting with *"Read `partner-docs/HANDOFF.md` first and follow it."*
That is a workflow preference, not a requirement. One session works fine.

---

## The one rule that matters most

Nothing goes out that you did not read and send yourself. Every gate in here exists to protect
that, not to replace it.
