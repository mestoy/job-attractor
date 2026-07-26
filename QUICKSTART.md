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

## 3. Start

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
