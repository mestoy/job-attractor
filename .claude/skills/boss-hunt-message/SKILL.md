---
name: boss-hunt-message
description: Draft a boss-hunt outreach email to a specific hiring decision-maker in Andrew LaCivita's structure and YOUR voice, with your honesty guardrails and a public-facts-only social deep-dive. Built WITH you beat by beat through pickers, never handed over as a finished draft; never send.
---

# Boss-Hunt Message skill (generic starter)

Produce one outreach draft to a **named boss**, blending LaCivita's structure with your voice (`documents/writing-style-guide.md`) and facts (`documents/PROFILE.md`).

## Format: EMAIL is primary (LaCivita); LinkedIn is the follow-up
The initial outreach is an **EMAIL with your résumé attached**, fuller than a short connect note (no em dashes):
> Subject: [simple, specific]
> Hi, [First]!
> [why you're reaching out + the hook, in your voice]
> [ONE boss-praise beat — a specific, verifiable public accomplishment, mirrored by a specific accomplishment of YOURS. Not two separate compliments.]
> [SEND-VALUE beat — name the org's core-promise number in plain words as the problem you'd want to work on (the co-constructed value-stream step below); show don't tell, no coined term.]
> Here's what I'd bring as I [one-line identity]. I:
> - [concrete proof 1 from your PROFILE; NO years-of-experience]
> - [concrete proof 2]
> - [concrete proof 3]
> My résumé highlights [the most relevant work].
> I'd welcome a short conversation. [warm one-line fallback]
> Thank you,
> [Your name] · [your site]

**LinkedIn = the follow-up only,** ~a week later if no email reply; never a cold connection request. One touch per medium.

## Boss-praise = ONE beat, genuinely specific on both sides
LaCivita's template uses a single "I was impressed with your [specifics]" slot (in your own words, not the literal "I was impressed" if that's not your voice). Praise ONE specific, verifiable accomplishment of the boss, and mirror it with a SPECIFIC accomplishment of yours from `PROFILE.md` (honest figures). Never two unrelated compliments; never vague ("your leadership").

## SEND VALUE = a co-constructed value-stream number (Issue #65)
Every boss-hunt note must **send value, not just praise.** Carry a research-grounded read of the org's value stream and name the single number that captures it — the org's **core promise to its customer, expressed as the customer's time or cost to value, in the org's own language** (NOT internal-ops, NOT scale/breadth). Framed as "the problem I'd want to work on."

This is a **repeatable, co-constructed step, not a from-memory redo.** Run it, don't reconstruct it:
1. **Fan research out** across the team/sessions (earnings, press, announcements, social — you have no internal data).
2. **Generate MULTIPLE candidate numbers,** each a different core-promise number.
3. **Panel-vet to ≥95** — a CEO/CTO/CPO-style panel scores each candidate before you ever see it.
4. **Pick via a picker:** `scripts/vsm_component.py present --company "<Org>" --candidates <json>` filters to the lens + panel survivors and prints the picker **with the panel default as option 1**; you pick. Candidates carry `{kind, unit, voice, panel:{ceo,cto,cpo}, default, plain}`; off-lens or sub-95 candidates are refused, never shown.
5. **Show don't tell:** phrase the picked number in **plain words — no coined metric term, never labeled "the value stream."** Asking the sharp number IS the demonstration. `scripts/vsm_component.py pick --option N --sentence "<plain words>"` gates it (exit 3 on a violation) before it lands in the note.

**Required for boss-hunt rungs; optional** for warm/reply/thank-you/other comms (`vsm_component.py --require-required <rung>`).

## For any wording you'll send: 3 options + a recommendation + "add your own"
Offer 3 distinct drafted options, name a recommended pick with the reasoning, and always include a free-response "add your own" slot. Draw them from your `writing-style-guide.md`. Avoid AI tells: em dashes, "I was impressed", "exact/actually/honestly", empty superlatives, and parroting the boss's own phrases.

## Review package — get EVERYTHING ready before any send (you inspect first)
Every outreach = **two artifacts, both made review-ready before anything leaves your machine:**
1. **The outreach email draft** (To / Subject / Body); when you say go, built by `scripts/mail-draft.sh` as a visible draft in your mail client with the résumé attached. That script is the path because it lints the body, runs the dedup check and writes the send log; a draft made any other way has passed none of those. See the `outreach-send-prep` skill.
2. **A company-tailored résumé**, built and **opened for your inspection before you attach it.** Pick a consistent naming convention and keep to it, e.g. **`<Your Name> - Resume - <Company>.pdf`**, and keep your build source (LaTeX/docx) separate from the attachable copy.

**Sequence:** draft email → build + name + open the tailored résumé → review both → edit/approve → *you* attach the résumé and send. The skill gets it ready; you hit send.

## Social deep-dive — SAFETY-GATED
- **Use only public information.** Surface the boss's publicly self-disclosed accomplishments and interests that align with who you are.
- **Draw attention to genuine similarities, framed positively, never negatively.**
- **Never infer or assert** a person's identity or private attribute; use a personal hook only if they've openly, publicly shared it. When unsure, omit.
- Pick one authentic hook; the boss-praise must rest on a real public accomplishment, the personal hook is a bonus.

## Honesty guardrails
Apply YOUR guardrails from `documents/PROFILE.md` (verified figures only; correct company names and scopes; no unverifiable claims; no em dashes).

## Output
Return **To**, **Subject**, **Body** (résumé attached), plus a 2–3 line "why this match." **Do not send. Do not auto-open email without your go.**

## ⛔ CO-CONSTRUCTION IS THE METHOD, not a finished draft (ruled 2026-08-10)

This skill's description used to say *"Output is a draft for you to review."* **That was wrong and it
is retired.** It contradicted `lacivita-line-by-line-outreach` in the same kit, and a partner's
picker asserted the losing doctrine in front of their user because the two shipped side by side.

**The message is built WITH you, in stages:** angle concepts with sample lines → you pick → phrasings
in your voice → you pick → assemble → you send. Every type, including follow-ups, replies and warm
intros. A batch of finished drafts handed over as text is the forbidden pattern.

⚖️ **Why this is the canonical half.** The method's whole claim is that the message sounds like YOU,
and a draft written for your approval regresses to the assistant's register no matter how good the
voice sample is. Picking the angle and the phrasing is what keeps it yours. It is slower on purpose.

⚠️ **Prefilled delivery is a DIFFERENT stage and does not contradict this.** Once the beats are
picked and assembled, the finished message ships as a prefilled draft in your mail client rather than
as text to copy. Co-construction is how it gets WRITTEN; prefilling is how it gets DELIVERED.
