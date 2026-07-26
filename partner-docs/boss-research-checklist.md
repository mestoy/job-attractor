# Boss-accomplishment research checklist — the DEEP probe, run for EVERY boss before the praise beat

> **A secondhand claim about a boss is a FALSE-POSITIVE risk, exactly like a Glassdoor headline rating.** The #1 boss-hunt element is a *specific, sourced* boss accomplishment mirrored by a *specific, verified* accomplishment on your side. A generic or unverified praise beat fails the method. Apply the **same deep rigor here that `documents/culture-screen-checklist.md` applies to Glassdoor**: don't trust the first claim you find — verify it to a primary source, confirm it's THIS boss's, and cite it. This is a **reported gate** (agent/research-driven); `scripts/mail-draft.sh` mechanically blocks a send without a cited `--praise-source` (and requires a primary-source URL inside it), and `scripts/check_outreach.py` flags a generic praise beat.

## Run per boss (before writing ANY praise line)

1. **Attribution-disambiguation (FIRST — the analog of entity-disambiguation).** Confirm the accomplishment is actually **this person's**, at **this company**, in **this role**. The recurring failure modes:
   - **Co-founder / team mis-attribution** — someone who *co-founded the company that built* a thing did not necessarily *create* the thing; never write "you created X" when they shipped/led/scaled X. Use the true verb.
   - **Predecessor / wrong-title** — confirm the current title from a primary source before "as CEO you…".
   - **Namesake / wrong person** — same-name collisions. Verify the LinkedIn/company-page identity matches.
   - Get the **verb right**: created vs co-founded vs led vs scaled vs shipped vs acquired-into. An overclaimed verb is a credibility landmine in a cold email to the person who lived it.

2. **PRIMARY SOURCE, not an aggregator (the analog of "probe the actual reviews, not the headline").** A claim is not usable until it's confirmed on a **primary source**: the boss's own talk/post/podcast, the **company's** blog/docs/press release, a **named** case study, an SEC/press filing, a conference page. Third-party summaries (contact-database blurbs, SEO "success story" blogs, Medium recaps) are **leads, not proof** — they carry the same inflation risk as a Glassdoor headline.
   - If the metric appears **only** in a secondhand source and the primary source doesn't state it → **do not use the metric**. Fall back to the qualitative accomplishment the primary source *does* support, or find a different accomplishment.

3. **Cite it VERBATIM with the source URL (the analog of the 5-pos/5-neg verbatim quotes).** Record the accomplishment as a one-line citation: `<specific accomplishment> — <primary-source URL>`. That string is what goes into `mail-draft.sh --praise-source`. No citation = not researched.

4. **Recency / tense scope (the analog of the review-recency + trend read).** Is the accomplishment **current and at THIS company**, or old / at a **prior** employer? Scope the tense precisely — praising a 10-year-old win at a different company reads as stale homework. Prefer a recent, at-this-company accomplishment; if you use an older/prior-company one, frame the tense honestly.

5. **Specificity gate (the analog of "a headline number is not a screen").** The accomplishment must be a **named artifact or a real, sourced figure**, not a category. "You built great products / care about customers / scaled the team" = generic = FAILS (matches `check_outreach.py`'s generic-praise heuristic). "You shipped <named feature/product>" or "you <verb> <sourced metric>" = passes.

6. **The MIRROR must be verified too (honesty guardrails apply to your side).** The specific accomplishment on your side that you pair against it must be a **true, precisely-scoped** fact from your own history (drawn from `PROFILE.md`), with no figure or claim in kit_config `RETIRED` / `RETIRED_PATTERNS`, obeying the role-authorship guardrails (kit_config `EMPLOYERS` / `SELF_BUILT` / `ROLE_IMPLY`) and never implying a background you don't have. The mirror is a *kinship* claim — it has to be as true as the boss's side.

## Gates (any → the praise beat is NOT ready)
- **Unverified metric** (secondhand-only, primary source silent or contradicting) → drop the metric; don't ship it.
- **Mis-attributed accomplishment** (co-founder's / predecessor's / namesake's) → fix the attribution or pick another.
- **Generic praise** (no named artifact, no sourced figure) → fails the method; go deeper.
- **Stale/wrong-company** without honest tense-framing → re-scope or replace.
- **No primary-source citation string** → cannot pass `mail-draft.sh` (`--praise-source` is a hard precondition).

## Output
For the boss, produce: the **attribution-confirmed, primary-source-cited** accomplishment (one-line citation with URL) + the **verified mirror on your side** + a one-line note on tense/recency. Then draft the ONE praise beat in your voice per `skills/boss-hunt-message.md` (paraphrase in your own words, don't parrot). Ties: `documents/culture-screen-checklist.md`, `documents/HARD-INVARIANTS.md` SEND GATE, `documents/WORKFLOW-RULES.md`.
