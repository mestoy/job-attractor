# Quickstart — 3 steps

## 1. Get it

```
git clone https://github.com/mestoy/job-attractor job-search && cd job-search
bash install.sh .
```

The installer never overwrites files you already have, so it is safe to re-run.

## 2. Set it up

Open the folder in **Claude Code** and type:

```
/setup
```

It interviews you and writes all of it: your profile, your identity, your deal-breakers, and the
enforcement hooks. **You never open a config file.**

⚠️ **Run `/setup` all the way to the end.** The last step wires the enforcement hooks, and every
gate in this pipeline is one of them. Stopping early leaves you with no gates at all and nothing
on screen says so. If you are unsure, run `python3 scripts/doctor.py`: it names any hook that is
missing.

## 3. Two things with a lead time, do them TODAY

Both of these unlock large parts of the pipeline and both take longer than you expect, so start
them before you need them.

**Request your LinkedIn data export.** LinkedIn → Settings → Data privacy → Get a copy of your
data. **It can take a day to arrive.** Until it does, the warm rungs of the ladder stay locked and
you can only work cold contacts, which convert several times worse. When the .zip lands in
Downloads, run `/level-network`.

**Fill in `documents/writing-samples.md`.** It ships empty and it is a 15 minute copy and paste
from your own sent mail. Outreach drafting reads it to write in YOUR voice; with it empty you get a
generic register, which is the one thing that makes a message look automated. The file explains what
to collect.

## 4. Start

```
/matrix-hunt            find and screen companies that fit you
/apply <job posting>    tailor your résumé and answers for a specific role
```

The pipeline keeps a **review queue** of drafted outreach. Read each one, make it sound like you,
and send it yourself — email first with your résumé attached, LinkedIn as the roughly one-week
follow-up.

---

## Something not working?

```
python3 scripts/doctor.py
```

It changes nothing. It reports what is unconfigured or missing and the exact command to fix it —
identity still on placeholders, hooks not wired, profile half-filled, `pdflatex` absent.

## Staying current

Double-click **`Update Kit.command`** any time, or run `git pull && bash install.sh .`.
Your `documents/` folder is git-ignored and is never touched or pushed.

---

**Nothing is ever sent, connected, or applied without you doing it.**
Full detail: `README.md`, then `ONBOARDING-GUIDE.md`.
