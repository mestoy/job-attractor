# Job Application Assistant — Onboarding Guide

A Claude Code workspace that turns a job search into a repeatable pipeline: it **discovers** companies that fit *your* criteria, **screens** them hard before you spend any effort, **tailors** your résumé, and helps you reach the **hiring manager directly** instead of disappearing into an applicant-tracking black hole.

This is a starter kit. Everything personal has been stripped out — you fill in your own profile, and the assistant learns your preferences as you go.

---

## 1. The philosophy (why this works)

Three ideas drive the whole system:

1. **Discovery is driven by your criteria, not job boards.** Most job searches react to whatever postings exist. This one starts from a scorecard of what *you* actually want (remote, pay, culture, industry, autonomy) and goes looking for companies that match — posted role or not.
2. **Culture-first, always.** A great role at a company with toxic leadership, recent layoffs, or a broken remote promise is a trap. Every company is screened *before* you apply or reach out. A culture fail is dropped even if everything else is perfect.
3. **Go direct to the would-be boss.** Adapted from Andrew LaCivita's "boss hunting": instead of only submitting through the ATS, you find the person who would manage the role (the product/eng/design lead, not the CEO) and send a short, warm, personalized note. You pair it with the application, not instead of it.

---

## 2. Setup (do this first)

1. Copy this folder's contents into a working directory and open it in Claude Code.
2. Run **`/setup`** and answer the questions. This fills **`documents/PROFILE.md`** — your profile and the single source of truth the assistant loads on demand — and, from the same answers, the detailed skill files in `.claude/skills/job-application-assistant/` that `/apply`, `/rank`, and `/interview` read:
   - `01-candidate-profile.md` — who you are, work history, skills
   - `02-behavioral-profile.md` — how you work, strengths, growth areas
   - `03-writing-style.md` — your voice (used for cover letters and outreach)
   - `04-job-evaluation.md` — your deal-breakers, target sectors, calibrations
   - `05-cv-templates.md` — résumé structure and rules
   - `06-cover-letter-templates.md` — cover-letter structure (optional; many people skip cover letters now)
   - `07-interview-prep.md` — your prepared stories and talking points
3. You do **not** edit `CLAUDE.md` — it is a lean index that points at `documents/PROFILE.md` and never holds your data, so `git pull` updates stay conflict-free. `/setup` fills `documents/PROFILE.md` for you.
4. Build your **Employer Criteria Matrix** — a simple weighted scorecard of what you want (see §4). This is the engine of discovery.
5. (Optional) Install the job-search CLIs in `.agents/skills/` if you want automated board scraping — see their individual `SKILL.md` files.

Everything the assistant does should be checked against your real profile. It should never invent a skill, a metric, an employer, or a contact.

---

## 3. The pipeline

```
        ┌─────────────── DISCOVERY (two engines, run together) ───────────────┐
        │   matrix-hunt: companies from your criteria   +   scrape: job boards │
        └───────────────────────────────┬────────────────────────────────────┘
                                         ▼
                              AUTO-SCREEN (§5)  ← the gate
                                         ▼
                        ┌────── survivors only ──────┐
                        ▼                             ▼
                  APPLY (§6)                    OUTREACH (§7)
             tailor résumé + submit     →   direct note to the would-be boss
                        └──────────────┬──────────────┘
                                       ▼
                              INTERVIEW PREP (§8)
```

Discovery's two engines run **in parallel** — criteria-driven company hunting *and* job-board scraping — because each finds things the other misses.

---

## 4. Discovery, part 1: the Employer Criteria Matrix

Build a spreadsheet (or list) of everything that matters, each with a **weight** (how much you care, 1–10) and, per company, a **rating** (1–10). Score = weight × rating.

Split your criteria into two buckets — this distinction is the most important thing in the whole system:

- **Hard filters (a "no" = instant drop, no negotiation):** e.g. must be permanently remote, no required travel, and no deal-breaker industries. These are not scored; they gate. A company that fails one is out even if it's perfect on everything else.
- **Scoring factors (rank, don't gate):** pay band, equity, PTO, autonomy, a boss who develops people, interesting work, transparency, async culture, etc. A low score here lowers the ranking but doesn't disqualify.

Be honest about which is which. If "remote" is truly non-negotiable for you, it's a hard filter — and a company *drifting* toward hybrid (in-office pressure, "remote workers feel out of the loop") counts as a fail, not a maybe.

**`/matrix-hunt`** takes this matrix, generates a list of companies that plausibly score high (from your target lanes, "calm company" lists, mission-driven orgs, etc. — *not* job boards), scores them, and hands the survivors into screening. Tip: seed it with **bootstrapped / profitable / founder-stable / genuinely remote-first companies**, not hot VC-funded unicorns — the latter are often in post-growth correction (layoffs, RTO mandates, leadership churn) and rarely survive the screen.

## 4b. Discovery, part 2: scraping (optional)

**`/scrape`** (the `job-scraper` skill) runs installed job-board search CLIs, de-dupes against what you've already seen, and returns fresh postings. **`/rank`** then triages a batch of scraped jobs into a ranked shortlist against your profile. Keep batches small — find ~10, rank them, screen the winners, then find ~10 more, rather than scraping hundreds at once.

---

## 5. The auto-screen (the gate — never skip it)

Before you spend effort on any company — application *or* outreach — run it through these layers **in order**. Pass a layer → continue automatically to the next. Fail one → drop it and note why. Only survivors get surfaced.

1. **Blocked list + hard-filter industries.** Check your running "never again" list first (companies you've already declined, plus any deal-breaker industry). Cheapest veto — do it before anything else.
2. **Industry news (last ~12 months).** Layoffs (especially recurring/annual), private-equity cost-cutting, restructuring, lawsuits, regulatory/conduct issues, leadership departures. This layer kills a surprising number of otherwise-attractive companies.
3. **Culture (Glassdoor + verbatim quotes).** Overall rating, % recommend, recent trend. Pull the most recent positive *and* negative themes with 2–3 short real quotes each. Watch for review-gaming: "cult-like," "we were told to write good reviews," or an implausibly perfect score alongside angry recent reviews means the rating can't be trusted.
4. **Leadership stability + retention.** Founder/CEO stable? Recent turnover — and is it healthy (upgrade hires) or dysfunction (exodus, "mass departures," gaslighting)? High turnover + weak leadership is a hard block until both demonstrably improve.
5. **Location / remote reality.** Confirm the remote/hybrid policy against your hard filter — from the *company's own job listings*, not a third-party guess.

**Rule of thumb:** a strong culture can offset other gaps; a culture, leadership, remote, or industry fail cannot be offset by anything. When in doubt, drop it — there are always more companies.

Keep a **blocked-employers list** as you go: every company you decline, with a one-line reason. Check it first next time. (Keep this list private — it contains your candid judgments about named companies.)

---

## 6. Apply: tailoring the résumé

**`/apply`** runs a drafter→reviewer workflow: it tailors your résumé (and cover letter, if you use one) to a specific posting, then verifies it.

Good practice baked into the skill:
- **Tailor the summary and bullets** to the posting's actual requirements and keywords; don't ship a generic résumé.
- **Verify before delivering:** every claim must match your real profile (no invented metrics), the document must compile/render cleanly, fit its page budget, and — critically — the **PDF's text layer must extract cleanly** (ATS parsers read the text layer, not the pretty page). Check that your email and phone appear as literal text, not just icons.
- **Keep metrics honest and tenure-scoped.** Use the figure that was true *while you were there*, not a program total that grew after you left. An interviewer will ask.
- **Avoid AI "tells"** if that matters to you: no em-dashes as sentence connectors, no filler words, consistent tense.

The kit includes a clean one-page résumé template (`templates/cv/plain-professional/`). You can register your own with **`/add-template`**.

---

## 7. Outreach: reaching the would-be boss

This is what separates the system from "spray and pray." After you apply (or when a promising posting is dead), find the person who would manage the role and send a short, warm, personal note.

**Who to target:** the **product/eng/design lead** who owns hiring for the role (Head/Director/VP, or a would-be peer) — *not* the CEO. Reaching the founder/CEO makes you "the founder's pick" and steps on the hiring manager's toes. **Exception:** when the company is small/flat and the founder genuinely owns the product, the founder *is* the right target.

**Verify the person is current.** Before drafting, confirm on LinkedIn that they still hold that role at that company. People move on constantly; a note to someone who left six months ago is a wasted shot. (This check catches stale targets often — don't skip it.)

**Write it in your own voice, short.** A reliable shape is three tight beats:
1. A greeting + one *specific* reason this company appeals to you (something real about them), closed warmly.
2. One line on what you do and the value you bring — concrete, one credential.
3. A light close ("would love to be on your radar for a [role]").

Keep it human. No jargon dumps, no "here's my elevator pitch" framing, no walls of text. Run the draft through a quick three-lens check (how does this read to a CEO / an engineer / a product leader?) and fix what's off.

**Channel:** decide per person — LinkedIn note, email, or both. If email, treat it like a short cover letter (subject + body) delivered as a prefilled draft you review and send (see the `outreach-send-prep` skill), and flag any inferred address as inferred. On LinkedIn, a single connection request *with* the note is one clean touch — don't also send a separate follow-up message (it reads as pursuit). Note: LinkedIn may ask for the person's email to verify a connection when you share no mutual connections — have their likely work email ready (confirm the company's domain from public `support@`/`press@` addresses; never use a scraped personal address).

**Log every send** so you don't repeat yourself and can follow up: keep an outreach log (newest first) and a tracker row per company (contact name + title + verified profile).

---

## 8. Interview prep

**`/interview`** prepares you for a specific tracked application: likely questions, your best stories, and sharp questions to ask them.

A useful answer structure is **CAAR** — Context, Approach, Action, Result. The "Approach" beat (your thinking, why you chose what you did) is where you show judgment, and it lets you speak credibly about work a teammate executed. Prepare a small set of real, specific stories with honest metrics, and reuse them.

Your criteria matrix (§4) doubles as an interview tool: for each thing you care about, prepare a question that reveals whether they actually have it. ("Who on your team has been promoted, and what did you do to get them there?" reveals more than "do you support growth?")

---

## 9. How the assistant learns (memory)

As you work, the assistant should capture durable facts about *you* and *how you like to work* — corrections, confirmed preferences, your blocked-employers list, calibrations to your deal-breakers — so it doesn't re-ask or repeat mistakes. In Claude Code this lives in a memory directory with a one-line index. Treat it as private: it contains your preferences and candid company judgments.

Good things to save: "I won't negotiate on X." "This industry is a deal-breaker for me." "Company Y is a hard pass because Z." "Draft outreach in this voice." Bad things to save: anything already obvious from your profile or the code.

---

## 10. Command reference

| Command | What it does |
|---|---|
| `/setup` | Onboards your profile (run first) |
| `/matrix-hunt` | Discovers companies from your criteria matrix and screens them |
| `/scrape` | Runs job-board search CLIs for fresh postings |
| `/rank` | Triages a batch of scraped jobs into a ranked shortlist |
| `/apply` | Tailors + verifies a résumé (and cover letter) for a posting |
| `/radar-outreach` | Boss-hunt outreach for a specific named company (dead or live posting) |
| `/interview` | Interview prep for a tracked application |
| `/power-story` | Picks the one CA²R story that carries a specific interview, then scripts its entry points and telling |
| `/outcome` | Records the result of an application |
| `/upskill` | Compares tracked postings to your profile to find skill gaps + a learning plan |
| `/expand` | Builds out your profile from documents and your online presence |
| `/add-template` | Registers a custom résumé/cover-letter template |
| `/add-portal` | Generates a job-board search skill for your local market |
| `/reset` | Resets profile data |

---

## 11. A few hard-won rules

- **Screen before you spend effort.** Never write a résumé or an outreach note for a company you haven't screened.
- **Hard filters don't negotiate.** If remote (or anything) is truly non-negotiable, treat drift as a fail, not a "maybe worth it."
- **Verify people are current** before outreach.
- **Keep metrics honest and tenure-scoped.** The résumé has to survive the interview.
- **Target the hiring manager, not the CEO** (unless the founder owns the product).
- **Log everything.** Future-you needs the paper trail.
- **The assistant works only from what's true** — your materials, or what you tell it. It should never invent a figure, a profile URL, or a claim.

---

## 12. Multi-session sync (running more than one Claude session on the same search)

The whole point of this setup is that you can drive several Claude sessions from **one shared folder**, with no manual file-shuffling.

- **One shared folder** is connected to every session (Claude Code in a terminal, and/or a content/strategy session). They all read and write the same real folder, so nothing is siloed and each session sees the others' work.
- **`deliverables/UBE_HANDOFF_MAIN.md` is the single source of truth.** Every session reads it first; if anything conflicts, it wins. Fill in its `[PLACEHOLDER]` sections and your `WORKFLOW-RULES.md` before relying on them.
- **Two roles:**
  - *Content/strategy session* — drafts résumé content, verifies claims, makes screening decisions.
  - *Build session (Claude Code)* — typesets the LaTeX résumés, runs scripts, packages outputs.
- **Drive it by pasting a short prompt** to start work in any session:
  > "You're my [content | build] session in our shared folder. Read `deliverables/UBE_HANDOFF_MAIN.md` first and follow its rules and guardrails. Then: <task>. Ask me before anything irreversible."

That is the whole workflow: one shared folder, one source of truth, prompts to drive, and human approval on anything that leaves the machine.

## 13. Browser automation (opening LinkedIn + application tabs)

The outreach and apply steps get much smoother if the assistant can open the pages you need directly.

- **Connect the Claude-in-Chrome extension** at **claude.ai/chrome** (grant it site permissions). This lets a session open pages in your existing Chrome and read them.
- With it connected, the assistant will, at the right moments, **open the tabs you need to act** — the **application/careers page** *and* the **LinkedIn profile** of the person you're reaching — verify the target is current, and hand you the note (and their likely work email) ready to send.
- When it's done with a tab it opened, it verifies the tab is still open and **closes it** so your browser stays tidy (it waits until you've sent, for outreach tabs).
- If the extension disconnects mid-session, reconnect at claude.ai/chrome and the session can resume opening/closing tabs.

---

## Where the rules live
- **`WORKFLOW-RULES.md`** — the full operating system (hard filters, screening, outreach, résumé, interview, honesty, cadence). The assistant reads it as the durable source for *how* the search runs. Fill in its `[BRACKETS]` with your own filters and preferences.
- **`deliverables/UBE_HANDOFF_MAIN.md`** — the multi-session source of truth (above).
- **`documents/PROFILE.md`** — your profile: identity, experience, skills, deal-breakers, preferences. The single source of truth the assistant loads on demand. Fill it with `/setup`.
- **`CLAUDE.md`** — a lean index that points at `documents/PROFILE.md`; you never edit it.

Good luck. Fill in your profile, your `WORKFLOW-RULES.md`, and your matrix, then let the pipeline do the heavy lifting.
