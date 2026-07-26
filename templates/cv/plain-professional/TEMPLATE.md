# Template: plain-professional

- **Type:** CV
- **Engine:** pdflatex
- **Page limit:** 1 page
- **Fonts:** Helvetica (via the standard `helvet` package - no font files to bundle, no external font install required)
- **Class/packages:** `article` (10pt, letterpaper), `geometry`, `fontenc`, `helvet`, `titlesec`, `hyperref`. No `enumitem` or `parskip` - both are unavailable in this TinyTeX install, so tight list/paragraph spacing is done with plain-LaTeX length settings instead (see template comments).

A clean, single-column, one-page résumé style designed to render an ATS-friendly text layer (plain black text, no sidebars or multi-column layout that would scramble extraction order). Edit the placeholder content in `template.tex` to your own details.

## Compile command

    cd cv && pdflatex -interaction=nonstopmode main_<company>.tex

## Style rules

- Plain black text throughout - no color accent scheme (this is the point: it matches the user's plain master résumés, unlike the moderncv/banking blue theme).
- Name: bold, left-aligned (not centered), ~20pt, followed directly by a single contact line separated with " $\cdot$ " and " $\mid$ " - no icons for phone/email/links.
- Section headers ("Summary", "Core Skills", "Professional Experience", "Education & Certifications"): bold, ~11pt, with a thin horizontal rule immediately underneath, tight spacing above/below.
- **Summary section is hard-capped at 300 characters** - this is a user-specified constraint distinct from the moderncv template's 5-7 line profile-statement guidance. Count characters before finalizing, not lines.
- Core Skills as 3 bold-labeled category lines (e.g. "AI & Product:", "Technical:", "Domain:"), each a comma-separated list, not a bulleted list.
- Each Professional Experience entry: company name (bold) and location/dates on one line via `\hfill`, title (italic) and a short domain tag (italic) on the line below via `\hfill`, then a tight bullet list.
- Bullets: plain LaTeX default bullet character, single-spaced, minimal gap between items (`\itemsep` 1pt).
- **Hard 1-page limit** - this template exists specifically because the user finds the moderncv 2-page format too long for their taste; do not let content spill to page 2. Use the same relevance-weighted cutting principle as `05-cv-templates.md`, just against a tighter budget.

## Known pitfalls

- `enumitem` and `parskip` are not installed in this environment's TinyTeX distribution. Do not add `\usepackage{enumitem}` or `\usepackage{parskip}` - use the plain-LaTeX length-setting equivalents already in the template (a redefined `itemize` environment, and manual `\parskip`/`\parindent` lengths).
- Escape literal `&` in skill-category labels or anywhere else in running text (e.g. "AI \& Product", not "AI & Product") - LaTeX treats a bare `&` as a table alignment character outside of `tabular`/`align` environments and will error.
- Because this is a strict 1-page format, content budget is much tighter than the moderncv template's 2-page budget. Expect to cut roughly in half: 1 profile-statement paragraph (300 chars), 3 skill lines, and 2-3 roles with 2-4 bullets each is close to the ceiling for one page at 10pt with 0.6-0.75in margins.
