# /collateral - Content-to-Collateral Pipeline

Generate any job-search collateral from **one canonical content base**, so facts never drift between artifacts. `$ARGUMENTS` names what to produce and for whom, for example "resume for <company/role>", "cover letter for <company>", "interview prep for <company>", "outreach note to <person> at <company>", "linkedin about-blurb", or "add <new verified fact> to the base".

**The point of this command:** ONE verified content base feeds every artifact (résumé, cover letter, interview prep, outreach, LinkedIn), so the same figure means the same thing everywhere, honesty guardrails are applied automatically, and stories are never re-derived from scratch. This is the shared spine under `/apply`, `/jd-fit`, and `/interview`.

⚠️ **The interviewer read your résumé.** Cross-artifact drift is not a tidiness problem, it is the moment your credibility is checked.

## Step 1 - Load the canonical content base

Read (skip anything already in context):

- `documents/PROFILE.md` - your facts, roles, credentials, and surfaced history.
- `documents/writing-samples.md` - the voice corpus. Every artifact in your name is written FROM it, never from a generic register. If it is empty, run `/voice-setup` first.
- `documents/writing-style-guide.md` - the rules your drafts are linted against.
- Any story library or portfolio notes you keep in `documents/`.

## Step 2 - Apply the FACT-CURRENCY and HONESTY filter

⛔ **Run this BEFORE generating, never after.** These are the claims that drift, and the filter is the whole reason a shared base beats copying between documents.

Build and maintain your own list in `documents/PROFILE.md` under a clearly marked honesty section. A guardrail is any claim where the precise wording matters. Common shapes:

- **A retired number.** A figure you once used and can no longer source. Name the retired version so it cannot come back.
- **A scoped number.** A total that is only true for a date range, a region, or your tenure. Carry the scope with the number, always.
- **Served versus used.** How many people a system SERVES is not how many USED it. Pick the defensible word and keep it.
- **Ownership splits.** What you owned against what your team owned against what the org shipped. Write the split down once so every artifact tells it the same way.
- **Naming.** The legal entity, the product name, and the brand are often three different strings. Pick the correct one per context and record which.
- **Credentials.** Expired is not current. Coursework is not a conferred degree. Never present either as the other.
- **Tense and framing.** A thing you designed is not a thing that was adopted. Verify the verb before reusing any metric.

## Step 3 - Generate the requested collateral, tailored to the target

Route by artifact type, drawing ONLY from the content base:

- **Résumé** → one page, plain professional LaTeX. For a live application run it through `/apply`, which builds, verifies, and ATS checks it. Confirm the role is live first.
- **Cover letter** → when the application form has NO free-response fields, build a letter matching the résumé style and append it after the résumé as one combined PDF. When the form HAS free-response fields, answer those and skip the letter.
- **Interview prep** → your story library plus the ask-and-close questions from `/interview`. Quote your own reflections for failure, lesson, and leadership answers rather than inventing new ones.
- **Outreach note** → the three beat format, your voice from the corpus, one accomplishment matched to the target's need.
- **LinkedIn and personal brand** → your voice, precise and defensible claims only.

## Step 4 - Cross-consistency check

Nothing generated may contradict another live artifact. Same figures, same framing, same ownership splits everywhere. Flag any drift you find rather than silently picking one version.

## Rules

- **Single source of truth is the content base.** When a NEW verified fact surfaces, **update the base first**, then let every downstream artifact inherit it. Never patch one artifact in isolation, because the next artifact will not know.
- The honesty guardrails in Step 2 are non-negotiable and apply to every artifact automatically.
- Open the job description in the browser for role-specific work, and open the compiled résumé PDF to inspect it before it goes anywhere. A LaTeX file that looks right is not a PDF that looks right.
