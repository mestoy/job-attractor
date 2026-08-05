# /voice-setup - Build Your Voice Corpus

You are walking the user through filling in `documents/writing-samples.md`, the corpus every outreach draft is generated FROM. Your job is to make this take 15 minutes and feel like copy and paste, because that is what it is.

⛔ **DO NOT write any sample text yourself.** Every word in this file must be something the user has sent. A sample you compose teaches the pipeline to sound like you instead of like them, which is the one outcome this file exists to prevent.

---

## Why this matters, say it once and move on

Open with two sentences, not a lecture:

> Outreach drafting reads this file to write in your voice. With it empty you get a generic register, which is the thing that makes a message look automated.

Then start. Do not explain further unless asked.

---

## Step 0: check what is already there

Read `documents/writing-samples.md`. Count existing `## Sample` blocks.

- **0 samples** → full run, Step 1.
- **1 to 4 samples** → tell them which shapes they already have and which are missing, then resume at the first missing shape.
- **5 or more** → say so, offer to add one more shape or to stop. Do not re-collect what exists.

---

## Step 1: the five shapes, ONE AT A TIME

⛔ **Never present all five at once and never ask for more than one sample per turn.** A wall of requests gets abandoned; one request gets answered.

The five shapes, in this order. The order matters: the first is easiest to find and builds momentum.

| # | Shape | Where to tell them to look | What it teaches |
|---|---|---|---|
| 1 | A cold note to a stranger | sent mail, search for a name they do not recognize | their opener and self introduction |
| 2 | A favor asked of a friend | messages to someone close | their warm register, a different person entirely |
| 3 | A reply to someone who answered | any thread with back and forth | how they carry a conversation rather than start one |
| 4 | A thank-you | after an interview, a favor, an introduction | gratitude, which is easy to fake and easy to spot |
| 5 | Something public | a LinkedIn post or comment, their website, a bio | ⚠️ their PUBLIC voice, which is NOT their message voice |

For each shape, in its own turn:

1. **Ask with the picker**, using AskUserQuestion. Give them a way out, because a shape they cannot find should not stall the run. Options:
   - `Paste it` - they have one ready
   - `Help me find one` - you give two or three concrete search strings for their mail client, then re-ask
   - `Skip this shape` - record it as missing and move on
   - `Stop here` - save what exists and end cleanly

2. **When they paste**, do NOT edit it. Not the typos, not the run-on sentences, not the greeting. Say so out loud once, at the first sample: *"I am pasting this word for word as you sent it. The typos are data."*

3. **Ask ONE question about the situation**, because a sentence carries the relationship it was written into. Keep it to a single sentence answer:
   - *"Who was this to, and how well do you know them?"*

4. **Append immediately** to `documents/writing-samples.md` in this shape. Write after each sample rather than batching at the end, so an interrupted run keeps everything collected so far.

```
## Sample <n> - <shape> (<date if known>, <who it went to and how well they know them>)

Setup:
  <their one-line answer>

Verbatim (copy the VOICE, never the facts):
  │ <the message, word for word as pasted, every line prefixed with "  │ ">

Cadence lessons:
  <leave empty on the first pass>
```

---

## Step 2: read it back to them

After the last sample, do the one thing they cannot do for themselves. Read all the samples together and name **three to five concrete voice tells** you can see across them. Be specific and quote them:

- Greeting shape. `Hi, Name!` versus `Hi Name,` versus `Hey Name`, all real differences.
- Contractions, or their absence.
- Sentence length, and whether they run on or clip short.
- A tic that repeats: a phrase, an emoji, a sign-off, or a way of opening.
- How they close. An exclamation point and a full stop are different registers.

Write these into the `Cadence lessons:` line of the relevant sample.

⚠️ **Name what you SEE, never what you would recommend.** This is description, not coaching. If a habit looks like a mistake, it is still their voice and it stays.

---

## Step 3: prove it works

Run `python3 scripts/voice_samples.py cold-boss` and show them the output. They should see their own words come back. If the file is not found or no samples surface, fix that before finishing rather than reporting success.

Then tell them the one thing that makes the corpus compound:

> From here, whenever you rewrite a draft before sending, save both versions. The gap between the draft and what you sent is the richest signal about your voice, and it is invisible from the sent message alone.

---

## Notes

- **Nothing here is sent.** This command only writes a local file.
- Safe to re-run. It appends and never overwrites.
- If they have no sent mail at all, say plainly that outreach drafts will be generic until they do, and that the first few real sends become the corpus. Do not invent samples to fill the gap.
