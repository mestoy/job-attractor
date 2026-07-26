# /radar-outreach - Radar & Dead-Posting Outreach

You are running a **radar outreach**: reaching an exceptional-fit company's product leader (or a would-be peer) with a low-pressure, forward-looking "I'd like to be on your radar for when you have an opening" message — whether or not there is a live posting.

Use this when a company is a strong **culture / leadership / domain** fit but has **no open role**, or a role that **just closed**, and a warm, human note to the right person beats waiting for a posting to appear. It complements `/apply` (for live postings) — it does not replace it.

`$ARGUMENTS` is an optional company name (and optionally a person). If empty, offer to surface a candidate first (Step 0).

Follow these steps **in order**. Do not skip the screen (Step 1) — never spend a warm introduction on a company that fails culture.

---

## Step 0: Parse Input / Surface a Candidate

- If `$ARGUMENTS` names a company, use it.
- If empty, propose a candidate: a **calm, sustainable, founder-stable, exceptional-culture** company in the candidate's target lanes (see `01-candidate-profile.md` and `04-job-evaluation.md`). Draw from recent `/scrape` shortlist entries in `job_scraper/seen_jobs.json`, prior research, or a quick targeted search. Confirm the pick with the candidate before proceeding.

## Step 1: Screen First (MANDATORY — fit → culture → news → leadership)

Do NOT reach out before this clears. A warm intro to a bad-culture company is worse than none.

1. **Fit** — domain/skill/experience match against `01-candidate-profile.md` + `04-job-evaluation.md`. Note honest gaps.
2. **Culture** — pull the 5 most recent positive AND 5 most recent negative Glassdoor reviews (recent, not just highest-rated); summarize recurring themes and WLB. Also check Blind/Comparably/Indeed where available.
3. **News / PR layer** — search recent news for layoffs, funding, lawsuits, regulatory/conduct issues, and leadership changes. Company-conduct red flags override a strong internal culture score.
4. **Leadership stability + trajectory** — is the founder still CEO? Any recent transition/turnover? **Distinguish upgrade-driven turnover (stronger org) from dysfunction-driven turnover (people fleeing instability, runway-layoffs, feedback suppression).** A recent transition landing as dysfunction is a strong pass signal even at a high aggregate rating.
5. **Deal-breakers** — apply the candidate's deal-breakers from `documents/PROFILE.md` (also `04-job-evaluation.md`).

Present the screen result. **If it fails, report why and stop** — do not do outreach. Only continue if the company clears.

## Step 2: Posting Status (informational)

Check the company's real ATS/careers board (authoritative source, not stale aggregators) for a matching live role.
- **No live role, or just closed** → radar outreach is the right play (continue).
- **A strong role IS live and the candidate is eligible** → say so: `/apply` is the better primary path. Radar outreach can still supplement it (apply, then connect).

## Step 3: Identify the Target — the PRODUCT LEAD, NOT the CEO

Reach the person who owns product hiring, not the founder. A CEO-blessed candidate can read as **the founder's pick** — the opposite of a clean entry into a flat, high-trust team, and it disrespects the pipeline and future teammates.

- Prefer, in order: **CPO → VP Product → Director/Head of Product** (the most senior product leader who owns PM hiring but is **not** the CEO). For a relationship-first, no-pitch curiosity note, a **peer PM** is also valid.
- Only fall back to the founder/CEO if **no** product leader is identifiable.
- **Only use a real, verifiable LinkedIn profile** (via WebSearch). Never fabricate a name. If the match is partial/uncertain, say so explicitly rather than presenting it as confirmed.

## Step 4: Draft the Radar Message (candidate's voice)

Draft in the candidate's own register — read `03-writing-style.md` and `02-behavioral-profile.md` (and any personal-voice notes) first.

- **Framing: forward-looking / "be on your radar for a future opening,"** decoupled from any specific posting. Do NOT frame it as "your posting closed before I could apply" (reads as *I missed out*). The strongest targets are companies with **no live opening** — you become who they remember when a role opens.
- **Voice:** plain, warm, concrete, first-person. Understated wit **baked into** plain statements, never announced ("here's my pitch," "funny thing" — cut these). No jargon dumps or parenthetical credential lists.
- **Content:** one plain line on what the candidate does (make it easy to say yes) + one genuine, specific reason *this* company draws them. **Verify any company-specific claim** before including it.
- **Deliver two lengths:** a **≤300-character** version (LinkedIn connection note) and a **fuller** version (LinkedIn message or email body).
- **Alternate register available:** a pure-curiosity opener with no pitch ("I really like what you're building — how does your product team actually work day to day?") for relationship-first outreach to a peer.

## Step 5: Decide the Channel Together (LinkedIn / email / both)

**Ask the candidate which channel** — do not assume.

- **LinkedIn** — ⛔ **NOT a first-contact channel.** Never send a cold connection request to a boss (RETIRED). LinkedIn is the FOLLOW-UP only: one **message** ~1 week later if no email reply, and only if the contact is verified 1st-degree.
- **Email** — draft the email through **`scripts/mail-draft.sh`** (the ONE email mechanism, per `documents/HARD-INVARIANTS.md` SEND GATE; pick the rung by relationship — `--rung cold-boss`/`cold-stranger` for a radar reach). It builds the Apple Mail draft (To + Bcc + Subject + Body + résumé) for review; it never sends. ⛔ Delivering the email as "copy-paste-ready plain text" is **RETIRED** — a hand-pasted email bypasses the lint, dedup, send-log, and follow-up-arming. Find/verify the recipient's address; if only inferable (e.g. `firstname@company.com`), **flag it as inferred** — never present a guessed address as confirmed.
- **Both** — ⛔ RETIRED. Do not pair a first-contact email with any LinkedIn connection request. Email first, then a LinkedIn **message** ~1 week later if no reply (one touch per medium).
- **No cover letters** — this framework does not send them; email is the outreach vehicle itself.

Present drafts as a starting point and expect the candidate to edit them into their own words before sending — that is the intended workflow.

## Step 6: Log It

After the candidate sends, append a row to `job_search_tracker.csv`:
- `status`: `contacted`
- `channel`: e.g. `LinkedIn radar outreach` or `Email radar outreach`
- `contact_person`: name + title + **verified** profile URL (note "product lead, not CEO")
- `fit_rating` + `notes`: the screen summary (culture/leadership/news) and a reminder to **watch the company's board for a role to (re)open**
- `cv_file`: none (no live posting to tailor against)

---

## Rules

1. **Screen before outreach.** Never reach out to a company that fails the culture/leadership/news screen.
2. **Target the product lead, not the CEO/founder** (pipeline + teammate respect).
3. **Only verifiable profiles/addresses.** Never fabricate a name; flag inferred emails as inferred.
4. **Radar/future framing,** decoupled from any posting — not "your posting closed."
5. **Voice and deal-breakers come from the candidate's profile files** (`documents/PROFILE.md`, `01`–`04`), so this skill works for any candidate who has run `/setup`.
6. **Decide the channel together;** deliver email as a prefilled draft you review and send (the `outreach-send-prep` skill); no cover letters.
