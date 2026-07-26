# Email-body checklist — INSPECT EVERY boss-hunt email BODY before displaying or firing

**Run this on every outreach body BEFORE showing a draft or calling `mail-draft.sh`.** The mechanical gate is **`python3 scripts/check_outreach.py <body.txt>`** — it must be 🟢. `mail-draft.sh` already calls it and blocks on FAIL. Report the result. Don't eyeball formatting.

## Format (mechanically checked by check_outreach.py)
- [ ] **Greeting line:** `Hi/Hey/TGIF, First!` on its OWN line, with a blank line before the body (`Hi, Astrid!\n\nYou brought…`, never `Hi, Astrid! You brought…`). check_outreach.py WARNs if the greeting is joined to the first beat or has no blank line after it.
- [ ] **One beat per paragraph:** ALL outreach (email AND LinkedIn/DM) breaks one beat per paragraph, blank line between beats (hook/praise · proof · identity · ask), never a single dense block. check_outreach.py WARNs on a dense-block body and on any single-newline-joined paragraph break.
- [ ] **Signature block:** the ask paragraph, then **TWO blank lines**, then your name, then your site URL on the line **directly under** it (no blank line between). Canonical shape (using your kit_config identity):
  ```
  You or a friend may need someone like me, so I'd love to be on your radar.


  Your Name
  https://www.yoursite.example
  ```
- [ ] **Website present:** your site URL (kit_config `OWNER_SITE_URL`) in the signature.
- [ ] **Display in a fenced code block:** when showing a draft, put the FULL body inside ``` fences so the TWO blank lines before your name render literally. Prose markdown collapses blank lines and makes the correct 2-blank spacing look like 1 — the spacing must be VISIBLE to you, not just correct in the file.
- [ ] **Zero AI tells:** no em dashes; no spaces around slashes; no banned/never-suggest words (add your own to the linter); `•` bullets only.
- [ ] **No retired figures:** nothing in kit_config `RETIRED` / `RETIRED_PATTERNS` (the linter fails any that reappear).
- [ ] **No repeated phrase:** the same multi-word content phrase must not recur across the body / consecutive sentences — a repetition AI tell. `check_outreach.py` WARNs on repeated 2-word content phrases; vary one.

## Content (human judgment — not scriptable)
- [ ] **3-goal structure:** hook (why-writing + genuine shared-passion) → boss-SPECIFIC praise of a real accomplishment → who-you-are/matched credential → enthusiasm + one low-friction ask.
- [ ] **Praise — RESEARCHED, SOURCED, specific boss praise (the #1 element).** The praise names a *specific thing THEY did*, from real research (`documents/boss-research-checklist.md` run first), with a source — NOT generic product/mission ("you built <Company> so…", "your mission", "work I care about" alone). `mail-draft.sh` blocks without `--praise-source`; `check_outreach.py` WARNs on generic "you built …" lines. ⚠️ **COLD RUNGS ONLY** — a warm or referred ask has no boss and no praise beat, so both the block and the WARN stand down when you pass `--rung warm|referred|event`.
- [ ] **Two-sided mirror.** Their specific accomplishment is mirrored by a specific accomplishment on your side (their thing ↔ your comparable thing), so the praise is earned kinship, not flattery.
- [ ] **Credential matched to THEIR problem**, not a generic history dump.
- [ ] **Ran the boss-hunt method checklist + reported the ✅/⚠️/❌ table** for this email (`--lacivita-check pass`).
- [ ] **Honesty guardrails:** every figure vetted against `PROFILE.md`, none in kit_config `RETIRED`; obey the role-authorship guardrails; praise is true to the boss's actual accomplishment.
- [ ] **Your voice:** written FROM `documents/writing-style-guide.md` (tight subject hook, warm, concrete), not a generic register.
- [ ] **Length:** short (~120–160 words); not a résumé dump.

## When displaying a draft
- [ ] Show the **full** body including the signature block and website — never a compressed/truncated preview that hides formatting. Preserve the real line breaks so you see exactly what will send.

**Ties:** `documents/HARD-INVARIANTS.md` SEND gate, `skills/boss-hunt-message.md`.
