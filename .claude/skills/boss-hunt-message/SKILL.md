---
name: boss-hunt-message
description: Draft a boss-hunt outreach email to a specific hiring decision-maker in Andrew LaCivita's structure and YOUR voice, with your honesty guardrails and a public-facts-only social deep-dive. Output is a draft for you to review; never send.
---

# Boss-Hunt Message skill (generic starter)

Produce one outreach draft to a **named boss**, blending LaCivita's structure with your voice (`documents/writing-style-guide.md`) and facts (`documents/PROFILE.md`).

## Format: EMAIL is primary (LaCivita); LinkedIn is the follow-up
The initial outreach is an **EMAIL with your résumé attached**, fuller than a short connect note (no em dashes):
> Subject: [simple, specific]
> Hi, [First]!
> [why you're reaching out + the hook, in your voice]
> [ONE boss-praise beat — a specific, verifiable public accomplishment, mirrored by a specific accomplishment of YOURS. Not two separate compliments.]
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
