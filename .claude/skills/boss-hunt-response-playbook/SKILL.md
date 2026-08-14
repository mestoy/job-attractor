---
name: boss-hunt-response-playbook
description: What to do after a boss-hunt email goes out — LaCivita's 8 reply scenarios (interest, referral, no-opening, brush-off, silence) with drafted responses in your voice, plus the follow-up cadence and logging steps. Load when a boss replies or the silence window closes.
---

# Skill: Boss-Hunt Response Playbook (handling replies)

**When:** a boss replies to an outreach email (or the ~7–10 day silence window closes). This is the standing asset for *what to do next* — LaCivita's 8-scenario reply playbook (Boss-Hunting Bible), in the candidate's voice.

**How it works:** Ube drafts the reply in their voice; **the candidate sends** (human-gated, same as outreach — never auto-send). Templates are starting points; they edits into their own words. Honesty guardrails + zero AI tells + no em dashes + `firstname@`/www rules all still apply. **Log every reply + outcome** to `outreach_log.md` + `job_search_tracker.csv` (status: replied / referred / interviewing / passed) and run `/outcome` when a result lands.

**One touch per medium, then move on (90/1/9):** reaching a NEW boss beats chasing a non-responder. Don't over-invest in any single thread.

---

## ⓪ CLASSIFY FIRST, and put the classification in a picker

Added 2026-08-11. The eight scenarios below were seed concepts with **no step that maps a real
reply onto one of them**, so in practice a reply got answered from instinct and the playbook went
unread. Classification is the missing hinge.

**The assistant PROPOSES a section with its evidence; the OWNER RULES through the picker** (every
selection is a picker). Options carry a one-line rationale each, Andy's read as option 1.

| Signal in their message | Section | Then |
|---|---|---|
| Scheduling language, "let's talk", "send times" | **§1** | advance stage to `conversation` |
| Names a COLLEAGUE to talk to | **§2** | new note to that person, rung `referred` |
| Names a RECRUITER, HR or TA | **§3** | see the ambiguity rule below |
| Points at a careers page or ATS | **§4** | see the APPLYING boundary below |
| "No thank you", no time horizon | **§5** | gratitude + ONE network ask, stage `closed` |
| Asks how you got their address | **§6** | the honest provenance answer |
| Hostile | **§7** | default NO REPLY, stage `closed` |
| Silence at 7 to 10 days | **§8** | one touch on the OTHER medium, if unspent |

### ⚠️ The three cases that get mis-sorted

**A recruiter who wrote FIRST is not §3.** §3 is *our boss reply referred us to a recruiter*. An
unsolicited recruiter is an inbound of its own and runs the inbound-recruiter method (always reply,
the goal is the phone, relationship questions before any submission). The gate treats them
differently too: §3 rides `FOLLOWUP:` because a SENT record exists; an unsolicited recruiter rides
`INBOUND:` because there is none. Getting this wrong picks the wrong exemption and the gate blocks
for a reason that reads like a bug.

**A DATED DEFERRAL IS NOT A REJECTION.** *"I don't have anything at the moment but probably will
closer to October"* is an invitation with a date on it, not §5. Classifying it as a no discards a
recruiter who named the month to come back in. Log it with an explicit `FOLLOWUP-DUE` date, close
the present turn warmly, and let the date do the work. 📊 Live instance the day this was written:
upstream, 2026-08-04, a recruiter named October and nothing held the date.

**"Not right now" from the BOSS is §5; "not right now" from a RECRUITER is usually a deferral.** A
boss is telling you about their team. A recruiter is telling you about this week's requisition list,
and theirs changes.

### The stage each section advances to

§1 → `conversation` · §3 screen against a named seat → `screen` · §5 and §7 → `closed` with a note ·
§4 stays `replied` until the boss-carried application moves. ⛔ `conversation` is never `interview`;
an intro call and a coffee chat are conversations. That distinction has its own receipt: on
2026-07-24 the pipeline reported "3 interviews this week" and the owner corrected it to three
conversations and no interviews.

---

## The 8 scenarios

### 1. 🟢 "Great, let's talk!" (positive interest)
**Goal:** convert to a conversation fast, remove scheduling friction, don't over-sell. **Then prep** (run `/interview`: CAAR stories, LaCivita Confirm/Assure/Close, salary reference).
> Hey [First]! This makes my day, thank you. I'd love to talk. I'm open [Day A] or [Day B], or send a time that works and I'll make it happen. Looking forward!

### 2. ↪️ Refers you to someone else (a colleague / hiring manager)
**Goal:** honor the referral, keep momentum, use the boss's name as a warm intro.
> Thanks, [First], I appreciate you pointing me to [Name]. Would you rather I reach out to them directly, or would you forward my note? Either way works, and I'm grateful.

When you then reach [Name], open with the referral: *"[Boss First] suggested I connect with you about product at [Company]…"* + one matched proof + résumé.

### 3. ↪️ Refers you to a recruiter
Same as #2, directed to the recruiter. Reaching the recruiter:
> Hi [Recruiter]! [Boss First] suggested I connect with you about product at [Company]. Quick on me: builder PM, [one matched proof from your profile]. Résumé attached. Would love to find a time.

### 4. 🗂️ "Apply through our careers page / ATS"
**Goal:** comply, but preserve the warm signal. **Upload via the ATS first**, then close the loop by email so the boss ties your application to the conversation.
> Hey [First]! Done, I applied through your site for [role]. Wanted to close the loop since you pointed me there. Happy to share anything else that helps. Thank you!

⛔ **THE AUTHORIZATION BOUNDARY, and it is a two-gate section.** Co-constructing the reply above is
a REPLY and rides `FOLLOWUP: <Company>`. **The ATS submission is an APPLICATION** and needs
`APPLYING: <Company>` with its own screen and its own ruling. The exemption docs already say
`INBOUND:` authorizes replying and never applying; the same is true here.
⚠️ **And the ORDER is an honesty rule, not a preference.** The message says *"Done, I applied."*
Drafting it before the application exists puts a false sentence in the owner's outbox. So: **APPLYING ruling
→ submit → then the close-the-loop reply.** Never co-construct this reply first.

⭐ **THE RECRUITER-SIDE MESSAGE IS THE ACTUAL CONVERSION PLAY, and it was missing here.** Andy's §4
does not stop at closing the loop with the boss. The point of an ATS referral is that it gives you a
BOSS'S NAME to put in front of the recruiter, which no cold application has. His script, seed
concept, to the recruiter:
> I'm reaching out because I connected with [boss] and [he/she] asked me to put my resume into your
> ATS for [position]. Assuming you have several candidates for this role, I wanted to send you this
> personal message with my resume and cover letter to see whether you feel I'd be a great fit for
> [boss]'s team or other positions within your organization. I did load all the respective
> information into your ATS if you need additional insight on me.

📊 **Why this matters more than it looks.** Measured 2026-08-11: every application in the record that
went in COLD produced a rejection or nothing. 23 applications, 3 form rejections, **0 advances on
their own.** Andy's method never applies cold, the boss's name is in the first line. This section is
the only place the pipeline manufactures that name.

🧾 **Record it so the two kinds stay countable.** Advance the send with
`--stage-note "ats-via-boss:<Boss Name>"`. That is note vocabulary, not a schema change, so the log
is never rewritten and stages stay monotonic. `--funnel` can then compare boss-carried applications
against cold ones, which today are 0 for all.

### 5. 🙏 "No thanks / not a fit right now"
**Goal:** don't burn the bridge; pivot to a low-cost networking ask (Andy). Stay gracious.
> Totally understand, [First], and thank you for the reply. If it's alright, is there anyone in your network I should meet who's building in this space? Either way, I'll be cheering [Company] on.

### 6. 🤔 "How did you get my email?"
**Goal:** honest, transparent, disarming. (Be truthful about how we actually found it — inferred from the company's common format — not a canned line.)
> Fair question, [First]! No trickery, I inferred it from your company's common email format since I couldn't find a listed address. I reached out directly because I'd genuinely love to be on your radar, not to spam you. Happy to move to LinkedIn if you'd prefer.

### 7. 😐 Rude / hostile reply
**Goal:** don't engage or escalate; protect their energy. Usually **no reply, just move on + log**. If a reply feels right, keep it light and gracious, then drop it:
> No worries at all, [First], I'll get out of your inbox. Wishing you and [Company] the best.

### 8. 🔁 No response after ~7–10 days
**Goal:** ONE value-add follow-up, then move on. Per our rule, the follow-up is a **LinkedIn message (never a cold connect)**; an email "bump" is the alternative. Keep it as short as possible.
> Hey [First]! Bumping my note from last week in case it got buried. Still would love to be on your radar as a builder PM. No pressure either way, thanks!

(Email-bump variant: *"Hey [First]! Floating this back up, no worries if the timing's off. Would still love to connect. Thanks!"*)

---

## Cross-cutting
- **Human-gated:** Ube drafts the reply in their voice; the candidate reviews + sends. Never auto-send. For a positive reply (#1), also fire the interview prep.
- **Log everything:** update `outreach_log.md` + `job_search_tracker.csv` with the reply + new status; move to `/outcome` when a result lands.
- **New metrics to track** (feed the changelog scoreboard): reply rate, positive-reply rate, referral rate. Alert the candidate on notable trends.
- **Voice + honesty:** their voice, zero AI tells, no em dashes, no spaces around slashes, `firstname@`/www rules; only vetted facts from your own profile (no invented figures).
- **Attribution precision when they ask "how did you do X":** a positive/referral reply often names a specific achievement and asks the candidate to expand on it (e.g. "tell me more about how you built the network"). Before drafting, split what the *company/team* built from what the *candidate personally owned*, and write the reply so the candidate's lane is theirs and the larger build is honestly credited to whoever did it. Overclaiming the company's work as the candidate's is the easiest honesty slip to make in a warm reply, and the precise version reads as *more* credible to a domain-expert reader, not less. Numbers/scale are fine as context; never as the candidate's personal build if they weren't.
