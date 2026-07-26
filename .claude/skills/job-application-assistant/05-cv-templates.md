# CV Templates and Tailoring Guide

> Template. Defines the résumé format and how to tailor it per role. A clean one-page template ships in `templates/cv/plain-professional/` — register others with `/add-template`.

## Active template
- **Skeleton:** `templates/cv/plain-professional/template.tex`
- **Manifest:** `templates/cv/plain-professional/TEMPLATE.md` (read for style rules + pitfalls)
- **Engine:** `pdflatex` · **Page limit:** 1 page · single-column (ATS-safe)
- Output tailored copies as `cv/main_<company>.tex`.

*(If you prefer a 2-page format or a different look, register it with `/add-template` and update this file to point at it.)*

## Section order
1. Name + contact line (contact as literal text — see ATS note)
2. Summary / profile statement (tailored per role)
3. Core skills (a few labeled lines, reordered to the posting)
4. Professional experience (reverse-chronological; strongest, most relevant bullets first)
5. Education
6. (Optional) Publications / awards

## Tailoring rules
- **Summary** is the highest-leverage section — rewrite it to *this* role, not a generic blurb.
- **Bullets** reframe to the posting's language and priorities; lead with strong verbs; quantify honestly.
- **Keywords:** cover the posting's terms where truthful; leave genuine gaps visible; **never keyword-stuff**.
- **Metrics stay tenure-scoped and honest** — the résumé has to survive the interview.

## Page-fit + verification (never skip)
- Compile/render and **visually inspect** the PDF — never trust the source alone. Hit the page budget exactly; no orphaned section/entry titles.
- **ATS text layer:** extract the PDF text (e.g. `pdftotext -layout`) and confirm it's clean — no garbled characters, email and phone present as **literal text** (not icon-only), reading order matches the page.
