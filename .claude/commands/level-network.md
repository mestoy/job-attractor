# /level-network - Level Your Network: the Closeness Interview

You are running the levelling interview that creates and fills `documents/contact-closeness.json`, the store the boss-hunt ladder runs on. Rungs 5/6/7 (warm asks) need a real relationship; rungs 1/2 need none; and a connection date cannot tell the two apart. Only the user can, and this interview asks them ONCE per contact and records the answer forever. `check_preview.py` refuses warm-shaped asks the store does not sanction, so until a contact is levelled here, the pipeline treats them as cold.

The engine is `scripts/level_contacts.py`. You orchestrate; it owns every write (immediate, `.bak` first). Never edit the JSON by hand.

Follow these steps **in order**. The user can stop at ANY point; every recorded answer is permanent and the next run resumes where this one stopped.

---

## Step 0: Parse Input

`$ARGUMENTS` may contain:

- Nothing → the full flow below.
- `--name "Contact Name"` → targeted mode: run `python3 scripts/level_contacts.py --name "Contact Name"`, show the user the output (their current state + the scale), ask ONE question ("How do you know Contact Name?" with the tier options), then record the answer with `--record "Contact Name=<tier>"`. Then stop. This is the 30-second path a blocked warm send points at.
- `--status` → run `python3 scripts/level_contacts.py --status`, report, stop.

## Step 1: Ingest the Newest Export

1. Look for a LinkedIn export using the kit's own resolution order (newest first, by filename date): `documents/linkedin-exports/Connections-*.csv`, then `~/Downloads`/`~/Desktop` (`*LinkedInDataExport*` folders, `Connections.csv`, `*LinkedIn*Export*.zip`).
2. If NONE exists anywhere: stop and tell the user how to get one: LinkedIn → Settings → Data privacy → **Get a copy of your data** → request the archive, then drop the `.zip` in Downloads and re-run `/level-network`. Do not improvise a contact list from anywhere else.
3. If the newest copy is NOT yet in `documents/linkedin-exports/`, ingest it: `python3 scripts/ingest_export.py "<path>"`. This strips every email address (a boolean `Has Email` survives, addresses never do) and REFUSES an export older than one already ingested, so respect the refusal, never `--force` it without the user saying so.
4. Then parse: `python3 scripts/parse_network.py` (builds/refreshes `documents/warm-network.md`).

## Step 2: The Machine Pass

Run `python3 scripts/level_contacts.py --infer`.

This levels what message evidence can level and no more: 6+ messages both ways → `know-well` (marked inferred, scores THIN until the user confirms, because volume is not intimacy) · 2-5 both ways → `never-spoke` flagged AMBIGUOUS (the re-ask queue) · one-way traffic → `never-spoke`. Stated answers are never touched; a two-way thread against a stated never-spoke gains a re-check marker instead.

## Step 3: Summary BEFORE Any Question

Run `python3 scripts/level_contacts.py --status` and present the shape of the work before asking anything, in one line, e.g.:

> N contacts · M with messages · K auto-levelled · J ambiguous · U unswept

Then ask whether to start a batch round now. If the user declines, stop here. The machine pass alone already improved the store.

## Step 4: Batch Rounds (~12 at a time, oldest connections first)

Repeat until the queue is empty or the user stops:

1. `python3 scripts/level_contacts.py --batch` → the next ~12 names (oldest connection date first, because old cohorts are where real relationships concentrate; re-ask entries show why they are back).
2. Ask ONE tick-who-you-know question (AskUserQuestion, multiSelect) listing the batch. **State the picker semantics verbatim in the batch preamble, every batch:**
   - "Tick anyone you KNOW. There is an explicit **'none of these'** option below."
     ⛔ Keep filler adverbs out of picker text. `check_preview` bans the AI-tell list (the one
     beginning `act`+`ually` and `ex`+`actly`) and refuses the call, so a protocol prescribing one
     cannot be followed. This line used to carry one and blocked the batch it describes (kit issue
     #9). ⚠️ Note the odd spelling above: `check_style` rejects those words in FILES too, so the
     rule about the word cannot be written with the word in it. That is the same contradiction one
     layer down, and splitting the token is the workaround, not a fix.
   - "**An EMPTY answer records `never-spoke` for this whole batch**, and it never means 'skipped'."
3. Record immediately, before the next question:
   - Unticked names and the "none of these"/empty case → `--record "Name=never-spoke"` for every unticked member of the batch.
   - Ticked names → a short SECOND pass, one question per name or grouped: "How do you know them?" with options **worked-together, know-not-close, personal-friend, classmate, shared-community, best-friend-lapsed**, plus "know them, ask me later" → `known-level-tbd` (the parking state). Record each with `--record "Name=<tier>"`.
4. After each round, show the shrinking count ("42 recorded, 388 to go") and offer: next batch, or stop for now. Stopping is always safe, because resumability is built in, and a recorded answer is never re-asked.

## Step 5: Close

Run `--status` one final time and report the coverage. Remind the user of the standing loop: a NEWER export later prompts only for the delta (new connections + new message evidence), and any blocked warm send names its own one-command fix (`--name`).

**Never** propose an outreach, draft a message, or pick targets inside this command, because levelling is levelling. The pipeline's other surfaces read the store from here on.
