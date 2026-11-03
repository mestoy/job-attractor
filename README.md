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

- **[Claude Code](https://claude.com/claude-code)**, the kit runs inside it.
- **macOS or Linux**, with **python3 3.9 or newer** and **git**. A Mac has neither until the
  Xcode Command Line Tools are installed once: `xcode-select --install`. The installer checks
  both and stops with a plain message if either is missing.
- Optional, for résumé building: `pdflatex` + `pdftotext`
  (`brew install --cask basictex && brew install poppler`, or `texlive-latex-recommended` +
  `poppler-utils` on Linux).
- Optional, for job-board search: [`bun`](https://bun.sh).

Not sure what you have? Run `python3 scripts/doctor.py` at any point. It changes nothing, and it
tells you what is missing and the command to fix it.

## Getting started (about 20 minutes)

```
git clone https://github.com/mestoy/job-attractor job-search && cd job-search
bash install.sh .
```

Then open the folder in Claude Code and type:

```
/setup
```

`/setup` interviews you and writes everything: your profile, your identity, your deal-breakers,
and the enforcement hooks. **You never edit a config file by hand.** Then:

```
/matrix-hunt            find and screen companies that fit you
/apply <job posting>    tailor your résumé and answers for a specific role
```

---

## How it works

Two halves, one folder:

- **The job-search assistant**: `/setup`, `/matrix-hunt`, `/apply`, `/rank`, `/interview`,
  `/power-story`, `/outcome`, `/radar-outreach`, `/jd-fit`, `/expand`.
- **The boss-hunt pipeline**: screens a company, verifies the would-be boss, and drafts a
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
| `doctor.py` | Discovering three weeks in that a gate was never wired, or that your config fell behind the code that reads it |

### Scorecards

`scripts/render_scorecard.py` turns a screened company's card markdown
(`documents/state/<slug>-card-<date>.md`) into an HTML fit scorecard, so the screening
step produces an artifact you can open, not a prose file.

```
python3 scripts/render_scorecard.py documents/state/<slug>-card-<date>.md
python3 scripts/render_scorecard.py --backfill documents/state       # render every card with no HTML yet
python3 scripts/render_scorecard.py --reindex documents/state/scorecards
```

A card's markdown headers vary in wording session to session, but every card is read
against the same ~13 semantic slots (blocked/hard-filter gate, news & layoffs, culture,
leadership & retention, remote reality, ownership, boss, live req, current direction, fit
read, panel, score history, sources), matched by keyword, not by header wording. A
BUILD/RADAR card missing one of those warns; a DROP/PARK card stopping early after its
first failing gate does not, since that is expected. The template lives at
`templates/scorecard/scorecard-template.html`; `--reindex` rebuilds
`documents/state/scorecards/INDEX.md` from whatever HTML is on disk. `kit_config.py`'s
`SCORECARD_SURFACED_VERDICTS` (default: empty, everything linked) lets you hide PARK/DROP
rows from the index without deleting them, if you only want BUILD/RADAR surfaced.

### Rankings

The reference workspace this kit is drawn from wires several of the scripts above into Claude
Code hooks (`.claude/settings.json`), so they run automatically instead of by hand. The kit ships
the scripts but does **not** wire the hooks (each one below assumes person-specific state, a
heavier always-on cost, or a design call the kit deliberately leaves to you):

### The gates are wired for you on the first install

`install.sh` copies the shipped hook example to `.claude/settings.json`, so **every gate
below is on from your first session and there is nothing to type**. Check it any time with
`python3 scripts/doctor.py`, which names how many are wired and whether yours has fallen behind
the shipped example.

| Hook event | What runs | What it is for |
|---|---|---|
| `SessionStart` (startup/resume/compact) | `session_start.py` | Opens the session with your unfinished work, your ladder and today's count |
| `PreToolUse` (AskUserQuestion) | `check_preview.py`, `check_pair.py` | You are never asked to approve outreach you were not shown a scorecard for, and a question always comes with the next-step pair |
| `PreToolUse` (Write/Edit/MultiEdit) and (Bash) | `check_ledger_guard.py`, `check_ledger_guard_bash.py` | Your decision ledger is not rewritten behind your back, by either route |
| `PostToolUse` (AskUserQuestion) | `record_decision.py`, `log_impression.py` | Each choice you make is recorded, so the ranking learns from you instead of asking again |
| `PostToolUse` (Write/Edit) | `check_style.py --hook-write` | A retired claim or a filler word is caught as it is written |
| `UserPromptSubmit` | `record_chat_ruling.py` | A ruling you state in chat is kept, so it does not have to be repeated |
| `Stop` | `consistency-check.sh`, `check_pair.py --hook-stop`, `check_style.py --hook-stop`, `kit_update.py --stop` | The end of every turn checks the work, owes you a next step, and tells you when the kit has an update |

**Turning one off** is editing `.claude/settings.json` and removing its block. That file is yours;
the installer creates it once and afterwards only refreshes it while it still matches a version
this repo has shipped, which is how it can tell it is untouched. Once you edit it, it is kept and
you are told there is a newer example rather than having your copy replaced.

> ⛔ **This section used to say the opposite, and it was worth writing down why.** It said the kit
> "does not wire the hooks" and listed a reason for each one to stay off. That had been true, and
> then the installer was changed to wire them, but the example shipped at the repo root while
> `install.sh` and `doctor.py` read `.claude/` only, so an install from a tree that keeps the
> example at its root wired nothing and the paragraph stayed accidentally accurate. Both
> locations are read now. Three tests covered the wiring and were green the whole
> time, because each one copied the example into `.claude/` in its own sandbox first.

### Honesty is load-bearing

`RETIRED` and `RETIRED_PATTERNS` in `scripts/kit_config.py` ship **empty**, and `/setup` only fills
them if you name a claim you have corrected. They encode figures *you* got wrong once, so nobody
else's list helps you. Until you fill them, the scripts say so out loud rather than pretending to
check.

Screening filters are the opposite: `/setup` **interviews you** for your deal-breakers and writes
them. An empty screening list does not screen nothing loudly. It passes everything silently.

---

## Staying current

This is a snapshot. To pick up a newer one, reclone; `git pull` will not fast-forward across a
republish. Your `documents/` folder (profile, blocked list, outreach log, résumés) is git-ignored,
so copy it from the old clone into the new one and nothing you saved is lost.

## Working with a partner

Each person gets their own clone and their own install: run "Getting started" above on your own
machine, in your own folder, even if a teammate already has the kit running. That gives you your
own `documents/`, so your answers, your decisions, and your sends never land in the same place as
anyone else's. Sharing one clone means your answers save over theirs, or theirs over yours, with no
warning either way.

What is shared across every install is the tooling itself. What stays yours alone is everything
in `documents/` and your `scripts/kit_config.py`.

## Optional: two sessions

On heavier days some people run **two Claude Code sessions** on the same folder, one for strategy
and one for building, each starting with *"Read `documents/HANDOFF.md` first and follow it."*
That is a workflow preference, not a requirement. One session works fine.

---

## How we work

For a new module, a schema change, or anything touching auth, money, migrations or deletion, read
`documents/HOW-WE-WORK.md` first. It is the maintainer's own operating model, in the maintainer's words: what to look up before asking,
what to write down before building, and when to stop and say so. A small change with one obvious form does not need it.

---

## The one rule that matters most

Nothing goes out that you did not read and send yourself. Every gate in here exists to protect
that, not to replace it.
