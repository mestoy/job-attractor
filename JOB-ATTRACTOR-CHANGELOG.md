# Job Attractor Pipeline — Changelog (your copy)

A persistent, append-only record of how your pipeline evolves, so you (and anyone helping) can look back and understand why it works the way it does. **Newest at the bottom.** Add a dated entry every time you change the workflow, skills, or rules (what changed + why).

Start it with the feature set your kit ships with, then append your own changes:

## v1.0 — [install date] · Starter kit installed
- Two-session setup (content + build) on one shared folder; prep-only Job Attractor Pipeline, human-gated (never sends).
- Mandatory auto-screen before anything reaches you: blocked-list → hard filters (remote + any personal constraints, deal-breaker industries, layoffs, always-on) → culture/leadership/news → Glassdoor → fit.
- Screen from data first; a structured Match Scorecard, then a pause; the boss's LinkedIn and the company site open only after you confirm the match.
- For any wording you'll send: 3 options + a recommendation + a free-response "add your own", drawn from your writing-style guide; boss-praise is ONE specific beat mirrored by a specific accomplishment of yours.
- Review package before any send: email draft + a company-tailored résumé (`<Your Name> - Resume - <Company>.pdf`), opened for inspection.
- **Review Console** (`app/build_review_console.py` + `Open Review Console.command`): a standalone HTML you open outside the chat to click through prospects one at a time (Prep / Mark sent / Drop / Deeper probe / Full dossier). Re-run the build to refresh from your queue.
- Queue hygiene: the live queue holds ONLY items awaiting your approval; sent/dropped entries move to an archive. Target depth 20; the prep task runs continuously while below 20.
- Arm a follow-up only for a WARM contact, by email (forward the original); a cold non-reply gets a new target, not a second touch (warm-only follow-up rule).

## v1.1 — 2026-07 · Human-in-the-loop outreach + verification hardening
Capabilities added to the pipeline (generic; nothing personal baked in):
- **Verify the live JD BEFORE any scorecard/decision.** Open the actual posting and confirm remote + travel cadence + hybrid/relocation, comp band, seniority/years bar, reporting line, and role/lane from the JD text (an aggregator "remote" tag is not proof). A gated JD = mark those facts UNVERIFIED. Also run a recency check so a stale/closed posting never reaches you.
- **Verify remote AND travel cadence** from the JD, not just "remote" — a "remote" role with monthly on-site travel can still fail a no-travel constraint.
- **Deeper-probe protocol** for any potentially disqualifying signal (attrition, perf-management, exec churn, conduct, WLB) before a match is shown as GO: verbatim + attributed quotes, distinct voices vs. amplification, pattern vs. scatter, does-it-apply-to-your-org, news layer, counter-evidence → BLOCK / CAVEAT / NOISE verdict. Plus same-name-company disambiguation (make sure a scary review is about *this* company).
- **Two-stage boss-praise, human-in-the-loop.** Stage 1: research the boss and surface 3 interest-aligned accomplishments for you to choose the angle. Stage 2: 3 phrasings in your voice to choose/edit. The assistant never picks unilaterally.
- **Line-by-line outreach construction.** Build the email one beat at a time (greeting → hook → boss-praise → offer → ask → sign-off), 3 options per beat in your voice, you pick each. A single assembled draft is offered only when you want speed.
- **Human-in-the-loop at every decision point** (which boss, which praise, which phrasing, send vs. drop) — never an irreversible step (mailto/send) before you choose.
- **Résumé attach without desktop control:** use an attachment-capable mail connector (e.g. Outlook / Microsoft 365) to build the draft with the résumé attached, or self-attach the handed-over PDF. Never type into or click inside the compose window; you always send.
- **Résumé style:** left-aligned / ragged-right + no hyphenation (`ragged2e` + `\RaggedRightRightskip=0pt plus 2.5cm` + `\hyphenpenalty/\exhyphenpenalty=10000`, no `\emergencystretch`) so words wrap whole instead of breaking.
- **Commit everything after EVERY outreach** (send AND drop): log the exact copy + bounce status (or drop reason), a tracker row, move the queue entry to the archive, fold any voice edits into your style guide, and record any new rule.

## Rule — No open req is not a disqualifier (value-reach)
- Boss-hunting communicates value to the boss regardless of a job opening (LaCivita). Live-JD verification catches hard-filter violations WHEN a role exists (travel, hybrid, comp, reporting line, lane); it does not require that one exist.
- No live role → reframe as a value-reach (radar): verify company-level remote/travel/industry/culture and reach out on value, with comp as a conversation-time question. "No live role" is a scorecard flag, never a drop.
- Only company-level reasons that hold regardless of any opening are drops: hard-filter fails (remote-absolute, firm no-travel e.g. mandatory offsites), deal-breaker industries, toxic/grindset/AI-mandate culture, layoffs/instability.

## [your next entry] — [date] · [what changed]
- ...

## 2026-09-09 · Scorecard rendering (kit issue #88)
- New `scripts/render_scorecard.py`: turns a screened company's card markdown into an
  HTML fit scorecard, so the screening step produces an artifact rather than a prose
  file that has to be hand-published each time. `--backfill` catches up every existing
  card that has no HTML yet; `--reindex` rebuilds `documents/state/scorecards/INDEX.md`
  from what's on disk.
- New checked-in template at `templates/scorecard/scorecard-template.html`, one
  stylesheet for every rendered card.
- The card markdown is read against ~13 semantic slots matched by keyword, not exact
  header text, since header wording drifts session to session. A BUILD/RADAR card
  missing a slot warns; a DROP/PARK card stopping early after its first failing gate does
  not, since that's the expected shape of a company that was already screened out.
- New `SCORECARD_SURFACED_VERDICTS` in `kit_config.py` (default: empty, every verdict
  shown) lets you hide PARK/DROP rows from the index without deleting them.

## 2026-08-31 · The Power Story (kit issue #75)
- New `/power-story <company>`: from the operator's locked CA²R library, run the match test against the seat's job-to-be-done (same problem shape · same actor position · same constraint · a true continuation), present the picker with the top match as option 1, then co build the entry-point phrases, the 60 to 90 second telling, the continuation beat, the chapters, and the second-chair story into that interview's prep doc. Chosen from the rack, never drafted; the library stays the one canonical copy.
- `/interview` Step 3.0 calls it before the question list; stage 2 documents the rule, stage 3 routes the first legitimate question through the entry point, stage 5's card carries the Power Story line.
- Wording: `/interview` now says CA²R (Approach¹ names the steps, Approach² walks them) instead of CAAR, matching the stage 2 skill.

## v1.6.0 — 2026-09-10 · Scorecard rendering hardens, five bugs closed, Glassdoor no longer blocks a BUILD
Bundles kit issue #88 (logged separately above, 2026-09-09) with the fixes its first real
use surfaced, plus one screen-gate policy change from the same day.

- **Scorecard rendering (#88), recap.** `scripts/render_scorecard.py` turns a card's
  markdown into an HTML fit scorecard against ~13 semantic slots matched by keyword;
  `--backfill` catches up existing cards, `--reindex` rebuilds
  `documents/state/scorecards/INDEX.md` from what's on disk; `SCORECARD_SURFACED_VERDICTS`
  in `kit_config.py` hides PARK/DROP rows from the index without deleting them.
- **BUG-245 — a reindex read a card's ruled verdict from the wrong place.**
  `--reindex`'s `build_index()` used to scrape a rendered scorecard's numeric panel-score
  div as its "verdict," so re-running it could silently relabel a PARK/DROP card as
  whatever score it happened to carry. It now matches each HTML file to its source card
  and reads the card's own STATUS tag first, falling back to the HTML's bolded verdict
  word — never the score — and leaves every existing INDEX row untouched, only appending
  rows for HTML not yet listed.
- **BUG-246 — the blocked-list reader inherited a stale section heading instead of a
  company's own stated reason.** A single un-updated `**⛔ Filter N: ...**` heading could
  silently mislabel every entry under it (measured: 146 of 172 rows in one real span were
  mislabeled) — a remote-fail or values-fail company could read as "PE-owned" purely
  because of where it sat in the file. The reader now checks, in order: an explicit
  `filter N` the entry states about itself, then a keyword read of its own stated reason,
  then the section heading as a last resort. Added filter 12, "Values," for the
  human-life-pricing drop class, which had no code of its own before this.
- **BUG-247 — two follow-ups the same reader needed.** (1) A handful of blocked-list
  headings say "filter number not recognized" with an arbitrary digit instead of the
  existing 99 "other" sentinel, which could collide with a real filter number sharing
  that digit — now redirected to 99 regardless of what number the heading prints, so it
  self-heals against future occurrences too. (2) A culture-fail drop (recurring layoffs,
  toxic-leadership reviews) had no keyword coverage at all and was inheriting whatever
  reason the last heading happened to name — added, mapped to filter 0 ("not a hard
  filter, an operator's own ruling on fit"), checked last so it never overrides a more
  specific real reason.
- **BUG-248 — the scorecard renderer could silently load the wrong `kit_config.py`.**
  It resolved `kit_config` relative to its own script directory, never to the project
  whose docs it was actually rendering — invisible for every other script (always run in
  place) but live for this one, since rendering an install with no copy of this script
  means invoking it cross-directory. It now resolves against the project root first,
  the shipped example as fallback, and prints which config file it used on every run.
- **BUG-249 — gate and note-box text leaked raw `**bold**`/`[link]` markdown into the
  HTML instead of rendering it.** A card author's own emphasis or link markdown showed as
  literal asterisks and brackets on the rendered page. A minimal bold/italic/link
  conversion now runs on exactly the fields that carry free-form card prose — nothing
  else, no new dependency, no general markdown parser.
- **Screen-gate policy — Glassdoor unavailable no longer blocks a BUILD (HARD-INVARIANTS,
  2026-09-10).** Glassdoor is Cloudflare-walled and 403s every agent fetch, so previously
  an unread Glassdoor page could stall a screen indefinitely waiting on you. Now: when
  Glassdoor 403s or hasn't been read yet, the card's culture cell carries "Glassdoor
  unavailable, read owed," the owed read is listed once in the depth report, the gate
  runs on Indeed/Blind/news/leadership/remote-reality instead, and the BUILD proceeds.
  Your own read is still the better one when you're available, and an unreachable
  Glassdoor is never recorded as "culture clean" — it's no longer a hard stop, not a
  downgrade in what counts as clean.

## v1.6.1 — 2026-09-12 · The ranking model is written down, and the updater story is closed out
- **Ranking operating model (kit issue #73).** New page `partner-docs/RANKING-OPERATING-MODEL.md`
  (seeded into `documents/` by `install.sh`): what the company and people boards score, the
  category order and base weights, the six key people sort and where a tie lands (years known,
  then name), the three ways a tie surfaces today, what you can retune in `kit_config.py`, and
  the honest limit that the people score is near a constant for some categories (issue #12).
  It also records the gap still open: the pair brief's computed default reads row 1 without
  checking the tie band, and the proposed ranker side fix for it. No code changed in this entry.
- **`Update Kit.command` and the kit remote (kit issue #20, workspace BUG-013), closed out in
  docs.** The three code fixes have shipped: the updater and `scripts/kit_update.py` resolve the
  remote whose URL is the kit instead of assuming `origin`; `scripts/doctor.py` prints that
  remote's URL, probes that it can be fetched, and reports when your `HEAD` shares no history
  with it, pointing you at `documents/RECLONE-PROCEDURE.md`. What this entry adds is the README
  text: "Staying current" no longer tells you to run a bare `git pull`, which was the original
  defect, and it now points at the reclone procedure for an install with unrelated history.

## 2026-10-04 · The LinkedIn profile on the card, and a cleared row at the send gate
- A card whose boss has a LinkedIn profile now carries it (`boss.linkedin`), matched to the named boss only, never guessed, never fetched. A profile link you paste yourself wins over the one a source suggests.
- A LinkedIn send you record lands in your send log as the same row the CLI writes (channel, profile link, first-line subject).
- A blocked-list row marked 'not blocked' now reads a weak yellow at the send gate, matching the CLI.
