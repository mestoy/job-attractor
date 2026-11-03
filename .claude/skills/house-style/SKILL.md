---
name: house-style
description: >
  A house writing style built on APA's structural construct carried in your own informal voice,
  with zero AI slop. Load BEFORE writing or editing anything in your voice, and whenever you want a
  draft to be sharper, clearer, less AI-sounding, or audited for slop. Triggers on: writing, draft,
  edit, rewrite, prose, tone, voice, style, APA, slop, AI slop, AI tells, sounds like AI, is this
  AI, clean this up, tighten, dossier, summary, analysis, memo.
---

# House style: APA construct, your voice, no slop

Two rule sets, one contract. **APA supplies the construct** (how a piece is organized, attributed,
and made precise). **You supply the register** (informal, warm, contraction-friendly, plain). The
no-slop layer removes the patterns that make writing read as machine-generated.

The idea: keep the construct of APA while writing in your own informal voice, a deliberate blend
rather than picking one or the other wholesale.

## ⚖️ Precedence — when APA and your voice collide, YOUR VOICE WINS

| Collision | APA says | The ruling |
|---|---|---|
| Compound modifiers | hyphenate ("well-known firm") | **No hyphens** in your own compound terms — pick a consistent style and keep it |
| Contractions | avoid in formal writing | **Keep them.** They are the voice |
| Numbers under 10 | spell out | **Numerals** for money and metrics |
| Em dashes | permitted | **None, ever.** Commas, ellipses, or parentheses |
| Headings | plain title case | **Your own visual markers stay** — status badges, emoji depth markers, whatever signal you've deliberately adopted |

That last row is why "formatting slop" (banning emoji headings and decorative bold outright) is
**not** adopted wholesale here. Deliberate visual indicators you asked for are signal, not
decoration, and should not get stripped by a generic slop pass.

## Two jobs

**Edit (default).** You share a draft to fix. Make the *minimum effective edit*, then return the
edited draft plus a short **What changed** section. Do not tidy every paragraph to the same finish.

**Detect.** You ask whether something reads as AI, or ask for an audit without a rewrite. Name each
pattern, quote the line, give the fix in a few words. **Do not score the draft or guess whether AI
wrote it** — detectors guess, named patterns are evidence you can check yourself. Offer to edit
afterward.

## Workflow

1. Read the whole draft first.
2. Note the core point and 3-5 voice signals to preserve. Keep that note internal.
3. For a **detect** request, produce the findings report and stop.
4. For an **edit**, make the minimum effective changes.
5. Run any style checker your kit provides, if one exists.
6. Self-check against the eval checklist below. Fix anything that fails and re-check.
7. Return the full draft plus **What changed**.

## Where each mode applies

| Mode | Applies to | Notes |
|---|---|---|
| `prose` | dossiers, scorecards, research writeups, longer documents | this skill is authoritative |
| `chat` | replies in conversation | this skill is authoritative |
| `outreach` | emails, LinkedIn notes, DMs | keep this skill's mechanics, but defer to any outreach-specific linter your kit runs |
| `resume` | résumé and cover-letter copy | defer to any résumé-specific checklist your kit runs |

Short form degrades gracefully. An email has no heading hierarchy; what carries over is the
mechanics: serial comma, active voice, no anthropomorphism, no weasel attribution, precision. None
of those fight your email voice.

---

## The APA construct, carried in your voice

APA 7th supplies **structure, attribution, and precision**. It does not supply register. Take
APA's discipline and leave its formality behind.

### Structure

- **Heading hierarchy, no skipped levels.** H1 → H2 → H3 in order. A jump from H1 straight to H3 is
  a defect.
- **One idea per paragraph, topic sentence first.** If a paragraph needs two topic sentences, it is
  two paragraphs.
- **Parallel seriation.** Every item in a list takes the same grammatical shape. Do not mix
  fragments with full sentences, or noun phrases with verb phrases, inside one list.
- **Front-load the conclusion** when it helps the reader. Do not force every section into the same
  point-detail-background shape.

### Attribution

- **Author-date discipline for research claims.** A screening or research claim carries who said it
  and when: "reviews (2026) describe…", "per the source, checked 2026-07-24…". This is the
  mechanical form of the weasel-attribution ban below.
- **Longer research writeups carry a Sources section.** Every external claim traces to something
  the reader can open.
- **No source means no claim.** Ask, or say the gap out loud. Never invent one.

### Precision

- **Define abbreviations at first use**, except terms in your own lexicon that need no gloss.
- **Anthropomorphism ban.** Documents, data, roles, and companies do not think, want, believe,
  argue, or know. *People* do.
  > ❌ The posting wants someone who can ship.  ✅ The hiring manager wrote that they want someone who can ship.
  > ❌ The study concluded that…  ✅ The authors concluded that…

  APA permits "the results suggest" and "the data indicate," so those are fine. Flag only verbs a
  person alone can do.
- **Active voice, human subjects.** "The team shipped it Tuesday" beats "the decision emerged."
- **Serial comma.** "sponsors, drafts, and approvals," always the comma before *and*.
- **Verb tense.** Past for what happened ("they shipped"), present for what is true now ("the role
  is remote"), present perfect for a span still open ("they have applied to several roles").
- **Bias-free language.** Person-first or identity-first as the group itself prefers. Singular
  *they* when someone's pronouns are unstated. Be specific about age, race, and disability only
  when it is relevant, and never as a label.

### What does not carry into short form

An email or a LinkedIn note has no heading hierarchy, no reference list, and no abbreviation table.
What survives: serial comma, active voice, the anthropomorphism ban, no weasel attribution, and
precision. An outreach-specific linter, if your kit has one, remains the authority on outreach
shape and voice.

---

## The adopted no-slop patterns

Adapted from the public `petergyang/no-ai-slop` pattern list (MIT licensed), with one deliberate
exception: the rule banning emoji headings and decorative bold ("formatting slop") is dropped, so
that a deliberate personal visual system is not treated as a defect.

Column key: 🤖 = a linter can catch it automatically · 👤 = judgment, yours to catch.

### Patterns

**1. Binary contrasts.** 👤 "This is not X. It's Y." / "The question isn't X, it's Y." State Y
directly.
> ❌ The question isn't the model. It's the eval.
> ✅ The eval matters more than the model.

**2. Throat-clearing openers.** 🤖 "Here's the thing," "Let me be clear," "I'll be honest," "The
uncomfortable truth is." Cut them and state the point directly.

**3. Faux-insight setups.** 🤖 "What most people get wrong," "Here's what nobody tells you," "The
part everyone misses." They flatter the writer as the lone expert.
> ❌ The part everyone misses: distribution is the real moat.
> ✅ Distribution is the moat.

**4. Colon reveals.** 🤖 A noun phrase, a colon, a lowercase dramatic reveal.
> ❌ The detail that makes it work: a separate agent grades it.
> ✅ A separate agent does the grading, which is what makes it work.

Colons are fine for lists, labels, and quotes. Markdown labels ("**Status:** sent") are correct and
are not this pattern. Sentence case after a colon unless grammar, a proper noun, a title, or code
says otherwise.

**5. Superficial analysis.** 🤖 Trailing `-ing` clauses that pretend to explain significance:
highlighting, underscoring, reflecting, showcasing, demonstrating, cementing.
> ❌ The launch adds file search, highlighting the team's commitment to better workflows.
> ✅ The launch adds file search, so users can find old drafts without leaving the editor.

**6. Importance puffery.** 🤖 "Stands as a testament," "marks a pivotal moment," "plays a vital
role," "cannot be overstated." State the fact and let the reader judge.
> ❌ The launch marks a pivotal moment for the company.
> ✅ The launch is the company's first paid product.

**7. Weasel attribution.** 🤖 "Experts agree," "studies show," "widely regarded as." Name the
source or cut the claim. **If there is no source, ask, never invent one.**

**8. Fake-strong verbs.** 🤖 Prefer "is" and "has" when they are clearer.
> ❌ The app serves as a centralized hub for sponsor management.
> ✅ The app tracks sponsors, drafts, due dates, and approvals in one place.

**9. Synonym cycling.** 👤 If the clear word is right, repeat it. Do not rotate terms for style.
> ❌ The agent reviews the draft. The assistant scores the piece. The tool suggests fixes.
> ✅ The agent reviews the draft, scores it, and suggests fixes.

**10. Negative listing.** 🤖 "Not a X. Not a Y. A Z." Just say Z.

**11. Dramatic fragmentation.** 🤖 "That's it. That's the whole thing." / "X. And Y. And Z." Use
complete sentences. Flag 3+ consecutive sentences of four words or fewer.

**12. Robotic rhythm.** 🤖 Repeated sentence shapes, identical paragraph structures, stacked punchy
fragments. Vary the shape only when it helps the point.

**13. Rhetorical setups.** 🤖 "What if I told you," "Think about it:," "Plot twist:," and
self-answered "Question? Answer." pairs.

**14. Fake-profound kickers.** 👤 The final "deep" line that turns the point into an aphorism or a
mic drop. **Delete it. Do not rewrite it into a better metaphor and do not preserve the rhythm.**
End on the clearest concrete sentence already in the draft. If it needs closure, add a plain
takeaway or a next action.

**15. Summary-recap endings.** 🤖 "In conclusion," "Ultimately," "Overall," or a last paragraph that
restates the piece. The reader was just there.

**16. Formatting slop.** ⛔ **NOT adopted wholesale.** The source pattern list bans emoji headings
and decorative bold across the board. A deliberate personal visual system (status badges, a small
set of meaningful emoji markers) is required signal here, not noise. What does carry over as
judgment: do not use bullets where two sentences of prose read better, and do not put a header over
a two-sentence section.

**17. Em dashes.** 🤖 **None. Ever.** Commas, ellipses, or parentheses instead.

### Vocabulary

**Banned outright** 🤖: delve · foster · leverage · utilize · facilitate · empower · streamline ·
robust · cutting-edge · paradigm shift · game changer · tapestry · realm · beacon · multifaceted ·
meticulous · intricate · paramount · transformative · elevate · embark · supercharge ·
ever-evolving · myriad · plethora · vibrant · boasts · seamless · testament · passionate · proven
track record · furthermore · moreover

Plus a personal never-suggest list you might adopt: **actually · exactly · exact · genuinely ·
honestly · simply · really.**

**Proper-noun exception.** Several of those double as real company names (Empower, Beacon, Realm,
Elevate, Foster, Vibrant). A linter should flag only lowercase uses of those words, so naming a
company by name never trips the gate.

**Often-empty adverbs** 🤖: just · literally · truly · fundamentally · importantly · crucially ·
inherently · inevitably · notably · arguably · ultimately · very · quite. **Cut them when they add
nothing. Keep them when they carry emphasis, uncertainty, contrast, or your spoken rhythm.** "I
just left my last role" is cadence, not slop.

**Often-empty phrases** 🤖: it's worth noting · it's important to note · at the end of the day ·
when it comes to · at its core · in today's world · in the age of · in the world of · the reality
is · the truth is · in this article · let's dive in · needless to say.

Warn only, since they sometimes earn their place: in order to · with regard to · in terms of ·
going forward · to be honest.

### Editing principles

- **Preserve the real voice.** Notice the draft's vocabulary, cadence, bluntness, humor, and
  uncertainty first. Keep what is personal. Do not make every paragraph equally tidy.
- **Minimum effective edit.** Fix slop, errors, repetition, and unclear passages. Leave strong human
  sentences alone. A rough draft with a real voice should still sound like the same person.
- **Keep the meaning.** Never invent claims, examples, stats, or opinions. If it is unclear, ask.
- **Open it up, do not dumb it down.** Strip jargon, long sentences, abstract nouns, and tangled
  structure. Keep the substance and the precision.
- **Be concrete.** "The integration improved efficiency" → "The integration cut deploy time from 40
  minutes to 4." Names, numbers, dates, and mechanisms beat abstractions.
- **Protect the specific fact.** Do not smooth a useful detail into generic importance.
- **Make verbs do the work.** "Made a decision" → "decided." "Has the ability to" → "can."
- **Preserve useful edge.** Keep strong opinions, blunt language, humor, and honest admissions.
- **Default to the shortest, plainest construction** when a choice has to be made.

---

## Eval checklist

Run this against an edited draft **before returning it**. Answer each check pass or fail. If any
check fails, fix the draft and run the checks again. Do this yourself, no separate editor and
evaluator pass.

For a **detect** request, verify the response names each pattern with a quoted line and a short
fix, without rewriting, scoring, or claiming AI authorship.

**Precedence (the blend)**

1. Are the four overrides intact: no hyphenated compound terms, contractions kept, numerals for
   money and metrics, and zero em dashes?
2. Do any deliberate personal visual markers survive? (Rule 16 is not adopted. Stripping them is a
   failure, not a cleanup.)
3. Where APA and the voice collided, did the voice win?

**Editing principles**

4. Does the edit preserve the point without adding claims, examples, stats, quotes, or opinions?
5. Does it preserve distinctive vocabulary, cadence, bluntness, humor, uncertainty, and level of
   polish?
6. Does it leave strong human sentences alone instead of rewriting them for consistency?
7. Is the amount of cutting proportional to the actual slop, with no compression that strips
   character?
8. Does the draft lead with what the reader needs, while keeping personal setup that adds context
   or tension?
9. Do sentences earn their place, with concrete facts, protected details, and direct verbs?
10. Is it active voice with human subjects where possible?
11. Are genuinely tangled sentences fixed while clear spoken cadence and changes in pace remain?

**Vocabulary**

12. Are banned words, empty phrases, and inflated claims gone unless quoted as examples?
13. Were often-empty adverbs judged rather than deleted on sight, cut where they add nothing, kept
    where they carry emphasis, uncertainty, or spoken rhythm?

**Patterns**

14. Are binary contrasts, negative listing, rhetorical setups, and throat-clearing openers removed?
15. Are faux-insight setups, colon reveals, superficial `-ing` analysis, fake-strong verbs, synonym
    cycling, dramatic fragments, and robotic rhythm fixed?
16. Are importance puffery and weasel attribution replaced with plain facts and named sources, or
    flagged when no source exists?
17. Are fake-profound kicker lines **deleted** rather than rewritten into better metaphors?
18. Are summary-recap endings cut, so the piece ends on a concrete point, takeaway, or next action?
19. Are colons sentence case unless grammar, a proper noun, a title, or code requires otherwise?

**APA construct**

20. Does the heading hierarchy skip no levels?
21. Is every list parallel in grammatical shape?
22. Does every external or research claim name its source and date, with a Sources section if this
    is a longer writeup?
23. Are abbreviations defined at first use, except the ones already in your own lexicon?
24. Is the serial comma present in every three-item list?
25. Is anthropomorphism gone, no document, dataset, role, or company that thinks, wants, believes,
    argues, or knows?
26. Is verb tense consistent: past for what happened, present for what is true now?

**Final read**

27. Did any style checker your kit provides run, and is every hard finding resolved or deliberately
    exempted?
28. Does the draft avoid robotic symmetry, repeated sentence shapes, and stacked punchy fragments?
29. Would you recognize this as your own voice?
30. Would it sound natural read aloud to a sharp colleague?
31. Does the output include the full edited draft and a short **What changed** section?
