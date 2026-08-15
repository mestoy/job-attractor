# /verify-titles: Check a Ranked Person's Role Is Still Real

You are verifying that the people the ranker is about to offer still hold the roles it thinks they hold, and recording what you find with `scripts/record_role.py`.

⚖️ **A LinkedIn profile is READ by a human with a logged in browser. The assistant can navigate to it and cannot read it.** LinkedIn answers `HTTP 999` to every automated fetch. That is its documented refusal for non-browser clients, not rate limiting and not a bad URL, so no retry, no user agent and no alternate URL gets past it. The assistant runs the ranking, prepares the list, offers the alternate sources in Step 2b and writes the records. Reading a profile is the operator's half of the job.

## Why this exists, with the receipt

`Connections.csv` records a contact's company and title as they stood when the connection was MADE. `parse_network.py` copies that into `documents/warm-network.md`, and the ranker reads it as current. Nothing re-verifies it, ever.

**A contact ranked #1** on a title that had ended SIX YEARS earlier. The export had frozen it at the date they connected, the ranker offered them as a warm target on it, and a brief was written describing them in the present tense off a role they had long since left.

On 2026-08-10 the daily briefing reported **10 of 10** top-ranked people with never-verified titles, and `reconcile_contacts.py` counted **1,442 STALE-TITLE** rows. So this is the normal state, not an exception.

⛔ **Verify the people about to be WORKED, never the whole roster.** 1,442 profiles is not a task, it is a way to never send anything. The unit of work is the handful the picker is offering today.

## Step 0: Parse Input

`$ARGUMENTS` may contain:

- Nothing → verify the current top 3 from the people pool.
- `--name "Contact Name"` → verify that one person and stop. This is the path a build gate points at.
- `--n N` → verify the top N.

## Step 1: Get the Targets

Run `python3 scripts/rank_criteria.py --pool people --n <N>`. Take the names in order.

For each, read what the pipeline currently BELIEVES, so you can tell a confirmation from a correction: the row in `documents/warm-network.md` gives the frozen title, company and connection date.

## Step 1b: Prepare the Paste-Back Invocations

Reading is the human's half and recording is yours, so do not make them dictate values for you to retype. For EACH target, build the exact `record_role.py` line up front with the name already filled in and `--title`, `--company`, `--source` and `--source-type` left blank, and hand them the whole list at once. They read a profile, fill the blanks from what they see, and paste the line back. That turns their step into a paste instead of a dictation, and it is what lets the run hand off cleanly rather than stall waiting for them to read each value aloud.

```
python3 scripts/record_role.py --name "<Target Name>" --title "" --company "" \
  --source-type "" --source ""
```

If the role has ended, hand them the `--left` shape instead, so the paste stays a paste:

```
python3 scripts/record_role.py --name "<Target Name>" --left --source-type "" --source "" \
  --note "old role and its dates"
```

## Step 2: The LinkedIn Read, Which Needs a Human at the Browser

⛔ **Do NOT run WebFetch against linkedin.com.** It returns `HTTP 999` every time. A run that tries it, catches the failure and reports "could not open the profile" has spent tokens to rediscover a known refusal, and it makes an empty run look like a thorough one.

The sanctioned mechanism is the same split this kit uses everywhere on LinkedIn: **the assistant NAVIGATES to the page and stops, and the OPERATOR READS it.** The operator's logged in session is the only thing LinkedIn will answer, so getting them to the right profile is the assistant's useful contribution and the reading is theirs.

So, when the operator is at the browser:

1. Open the profile with the browser tools, one person at a time, and stop there.
2. Ask them for the experience section: their CURRENT title, their CURRENT company, and whether the role on file has ENDED.
3. Record what he reports with `--source-type linkedin-live`.

⚠️ Verify the page header names the intended person before you ask them to read it. Two similar names are two clicks apart.

**When the operator is not at the browser, skip to Step 2b.** Do not stall the run waiting for them, and do not quietly downgrade to a guess.

## Step 2b: The Sources a Machine Can Actually Read

Several people verified cleanly this week with no LinkedIn at all. On one install, 4 of 6 boss registry rows confirmed from these and 0 from LinkedIn. For current tenure they are stronger evidence than a frozen export snapshot, The company page is stronger than LinkedIn itself for current tenure, because it is the employer saying who works there today rather than the person saying it about themselves.

- **The company's own team, leadership, and about pages.** Fetchable, and the best of the three. Record with `--source-type company-page`. A company page is not a search snippet; it is the employer publishing its own roster.
- **A dated press release naming the person by title.** Fetchable. Record with `--source-type press-release`, and put the date in `--source`, because an undated release verifies nothing.
- **A conference bio, an ATS careers page signed by the hiring manager, or a bylined post on the company domain.** Same handling as a company page when the domain is the employer's own.

⚖️ **Still do not infer the title from the export, a search snippet, or a cached brief**, because those are the sources that froze it in the first place. The connection date tells you how old the claim is, and nothing more.

⛔ If no human browser session is available and no alternate source names the person, **record nothing for that person** and carry them into the UNVERIFIED bucket in Step 4. A guess recorded with a source is worse than a gap, because it looks verified forever.

## Step 3: Record Immediately, With a Source and a Source Type

⛔ **Write through `record_role.py`, NEVER into `warm-network.md`.** That file is regenerated from the export on every `parse_network.py` run, so a correction made there is erased the next time anyone parses.

Confirmed or corrected:

```
python3 scripts/record_role.py --name "<Contact Name>" --title "Associate Director, Technology" \
  --company "Vaco by Highspring" --source-type linkedin-live \
  --source "linkedin.com/in/..., experience section, read by the operator 2026-08-11"
```

Confirmed from a company page:

```
python3 scripts/record_role.py --name "<Contact Name>" --title "VP Product" \
  --company "Northwind Health" --source-type company-page \
  --source "https://northwind.example/leadership, retrieved 2026-08-11"
```

Role has ended:

```
python3 scripts/record_role.py --name "<Contact Name>" --left --source-type linkedin-live \
  --source "linkedin.com/in/..., experience section, read by the operator 2026-08-11" \
  --note "the stale role ran Jan 2019 to Feb 2020"
```

A source is mandatory. An unsourced verification is a memory, and a memory is what produced the defect.

`--source-type` takes one of `linkedin-live`, `company-page`, `press-release`, `secondhand`, `unverified`. That vocabulary is `boss_registry.VERIFIED`, imported by `record_role.py` rather than retyped, so the two stores can never drift. Anything else is refused with exit 4. Omitting the flag still works and records `unverified`, which is the honest label for "we know where you looked and not what kind of thing it was".

## Step 4: Report and Re-rank

Report per person in one line each, in one of FOUR buckets:

- **CONFIRMED**: the stored title and company held up. Name the source type.
- **CORRECTED**: give the old value and the new one, and the source type.
- **LEFT**: the stored role has ended.
- **UNVERIFIED**: no human browser session and no alternate source named them. Nothing was recorded and their row is still resting on the export.

⛔ **A run where everyone lands in UNVERIFIED must say so plainly, in a sentence, at the top of the report:** "Verified nobody. No browser session was available and no company page or press release named any of the N." That is the whole point of the fourth bucket. A command that reports "done" after recording nothing is indistinguishable from one that verified everybody, and this pipeline has already shipped a check that reported rather than measured. Never let the report imply coverage the run does not have.

Then note that the ranking may have moved, because a corrected employer changes the segment fit and a departed role should stop ranking the person at all. Re-run `python3 scripts/rank_criteria.py --pool people` and show the new order if it changed.

**Never** draft or send anything inside this command. Verification is verification; the picker decides what happens next.
