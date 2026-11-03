# /power-story - Choose and Script Your Power Story for a Specific Interview

You are helping the user pick ONE story from their CA²R library and shape it into the story that carries a specific interview. The method is Andrew LaCivita's, from his Panic-Free Interviewing material (the "your stories, not their questions" idea). His wording is not reproduced here; the user builds their own telling in their own voice, one beat at a time, through explicit choices.

`/interview` calls this as Step 3.0. It also runs standalone, any time an interview is scheduled and the library has at least two locked stories.

Follow these steps **in order**.

---

## The rule, stated once

- **The Power Story is the most ANALOGOUS full project to what THIS employer needs the user to do.** Not the most impressive story, not the biggest number. The one where the shape of the work matches the shape of the seat.
- **It comes out as early as possible, in the wake of the FIRST legitimate question.** A legitimate question is a real question about the work. "Tell me about yourself" and "walk me through your résumé" are not; those route to the stage 1 opener.
- **Every question has an entry point into it.** The move is: echo their words, insert the business problem, route in. "You asked about X. I had this challenge where X was the whole problem..." Behavioral questions land INSIDE the story: the mistake chapter, the leadership chapter, the persistence chapter are beats of the same project told from a different door.
- **Define one per target, as prep.** A different seat can have a different Power Story. The library does not change; the pick does.

---

## Step 0: Parse Input

`$ARGUMENTS` may contain a company name, e.g. `/power-story acme`.

- **With an argument:** match against `job_search_tracker.csv` (case-insensitive on company, then role). Several matches → list and ask. None → accept the posting and role details directly.
- **Without an argument:** list tracker rows in a live process (`interview`, `offer`, recently `applied`) and ask which one.

Then load, once:
- `documents/ca2r-story-library.md` (the stage 2 deliverable). If it does not exist, or has fewer than two LOCKED stories, stop and say so: the Power Story is chosen FROM the rack, so `lacivita-interview-02-stock-stories.md` runs first. Do not draft stories inside this command.
- The archived posting (`documents/applications/<company>_<role>/job_posting.md`, or the tracker's source URL, or ask the user to paste it).
- `.claude/skills/lacivita-interview-02-stock-stories.md` §The Power Story, for the shape.

---

## Step 1: Name the employer's job-to-be-done

From the posting and the stage 2 company research, write the seat's job-to-be-done in ONE sentence, in plain words: what this person must make happen in the first year, for whom, under what constraint. Examples of the shape (not content to reuse): "stand up a product function where none exists, for a 20-person company selling into regulated buyers" · "take an AI feature from demo to trusted default for sales reps who do not want it."

Show the sentence to the user and ask them to confirm or fix it before the match test. A wrong job-to-be-done picks the wrong story.

---

## Step 2: The match test

For every LOCKED story in the library, score the analogy on four questions, each 0-2:

1. **Same problem shape?** The story's problem and the seat's job-to-be-done are the same kind of problem (0-to-1 build, adoption and trust, scale and consolidation, turnaround, and so on).
2. **Same actor position?** The user held the kind of seat they are interviewing for (owner of the call, not a contributor to someone else's).
3. **Same constraint?** The story ran under the constraint the seat carries (regulated buyer, thin team, no budget, hostile users, speed).
4. **Continuation exists?** The story has a true "and the same pattern is running now" beat, or a clean bridge into the employer's world.

Total each story. Present the results as a table: story, slot, four scores, total, one line on the analogy. Then the picker.

---

## Step 3: The picker

Ask with AskUserQuestion, single select:

- **Option 1 is the top-scoring story, marked (Recommended)**, with the reasoning in the description: which of the four questions carried it, and what the entry-point phrase would sound like.
- Options 2 and 3 are the next two by score, each with its honest reason for being second.
- The user can pick any of them or name another story. Their pick is the Power Story; the score only orders the options.

Record the pick in the library under that story: `**⚡ Power Story (CompanyName, YYYY-MM-DD).** Chosen for <the analogy in one line>.` The library accumulates picks the way it accumulates bridges; it does not fork.

---

## Step 4: Build the telling, one beat at a time

The library section is canonical and already speakable. What this interview needs on top of it, and what gets built here:

1. **The entry-point phrase.** Three routes in, one per likely first question, each in the shape "echo their words → insert the business problem → route in." Draw the likely first questions from the stage 3 routing map. The user picks or supplies the words for each; never hand them three finished sentences to approve.
2. **The 60 to 90 second telling.** Context in one or two sentences, Approach¹ (the step names), Approach² (the walk), Result with its defensible figure. Read it aloud together; cut until it fits. This lives in the interview's prep doc, not in the library (stage 2 rule: one canonical copy).
3. **The continuation beat.** The sentence after the Result that carries the story into the present or into their world. If the user has a true "the same pattern runs today" line, it goes here; if not, the library's bridge for this company does.
4. **The chapters.** List which behavioral prompts land inside this story and which beat each one enters at (the mistake chapter, the people chapter, the persistence chapter). A prompt with no chapter here routes to a different rack story; say which.
5. **Second chair.** Name the one library story that stands behind the Power Story for the probes it invites (a trust probe, a scale probe). One, not three.

Every figure stays inside the library's Honesty line for that story. Nothing new enters a Result here.

---

## Step 5: Land it

- Write the telling, the entry-point phrases, the continuation beat, the chapters, and the second chair into `documents/applications/<company>_<role>/interview_prep_<stage>.md` under a heading `## ⚡ Power Story: <story name>`.
- Add one line to the stage 5 day-of card: the Power Story's name, its entry-point phrase in keywords, and the continuation beat in keywords.
- Ask the user to tell it aloud once, entry phrase to continuation beat, and time it. Under 90 seconds and they can also give the 30 second version: done. Otherwise cut and repeat.

---

## Important Rules

1. **Chosen from the rack, never drafted here.** No library, no Power Story. Build the rack first.
2. **The user's words.** Entry phrases and the telling are co built beat by beat; a finished script handed over for approval is the failure mode.
3. **Analogy beats impressiveness.** If the user reaches for their biggest number and it is not the analogous project, say so, show the scores, and let them decide.
4. **One canonical story copy.** The library holds the story; the prep doc holds this interview's telling and aim. Never restate the story in the prep doc.
5. **Honesty binds.** Every figure in the telling is already on the story's Honesty line. Nothing new enters a Result inside this command.
