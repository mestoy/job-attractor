# Template: nli-dense

- **Type:** CV
- **Engine:** pdflatex
- **Page limit:** **1 or 2 pages** (declared in the .tex as `% PAGE-LIMIT: 1-2`)
- **Fonts:** Helvetica (via `helvet`, no font files to bundle)
- **Class/packages:** `article` (10pt, letterpaper), `geometry`, `fontenc`, `helvet`, `titlesec`, `hyperref`. Optionally `ragged2e` and `needspace`, **both guarded with `\IfFileExists` and a plain-LaTeX fallback**, so the file compiles on a minimal TinyTeX that lacks them.

A **denser variant** of `plain-professional`. Same single-column, ATS-friendly text layer; the differences are vertical economy and page allowance.

⛔ **This format permits 1 OR 2 pages**, unlike `plain-professional`, which is a strict one-pager. The original template is a one-pager; the second page is for a history that needs the room, not a licence to pad.

## The section STRUCTURE, which is the substantive half

⭐ **Added 2026-08-10 (kit issue #19).** Until then this template shipped the LAYOUT and none of the
STRUCTURE: margins, `\parskip`, `\needspace` and a 2-page allowance, all real and all cosmetic. The
`\subblock` macro was defined in the file and never used. An operator following this template
believed they were using the format and were using the margins.

Each EXPERIENCE role splits into two sub-blocks:

| Sub-block | What goes in it | Length |
|---|---|---|
| **Achievements** | Outcomes with a number attached | Shorter. 1-2 bullets |
| **Responsibilities** | Scope, following ACTION + KEYWORDS + SCOPE + IMPACT | 2-3 bullets |

📊 **Why it earns the lines**, measured rather than asserted: restructuring identical content into
this shape took a page from **69.8% full to about 83%**, because sub-headings consume space
structurally instead of by padding. No content changed and no line was invented.

⛔ **Do not pad Achievements to fill the slot.** If a role has no achievement worth a number, that
is worth discovering while you are writing the résumé rather than in the interview. Leave it thin,
or fold the role into Responsibilities alone.

⚖️ **Two deliberate divergences from the source format**, kept on their own merits:
- The summary section is called **Summary**, not OBJECTIVE. `verify_resume.py` accepts
  `Summary`, `Objective` or `Profile`, so either spelling keeps both summary gates armed. It did
  not always: a heading the checker did not recognize used to disarm two checks silently, which is
  the other half of issue #19.
- **Core Skills sits near the top**, not as a TECHNICAL SKILLS list at the bottom.

## When to use it

Two cases:
1. Your one-pager **reads sparse or top-heavy**. This buys vertical room.
2. Your history **needs two pages**. `plain-professional` cannot give you that; this can.

If your history already fills one page comfortably, `plain-professional` breathes better.

⚖️ Neither is "better". They trade differently, and the trade is density against breathing room.

## What differs from plain-professional

| | nli-dense | plain-professional |
|---|---|---|
| top/bottom margins | **0.55in** | 0.6in |
| `\parskip` | **3pt plus 1pt** | 4pt plus 1pt |
| title line under your name | **yes** (`[YOUR_TARGET_TITLE]`) | no |
| page-break guard on role blocks | **yes** (`\needspace`) | no |
| experience heading | **"Experience"** | "Professional Experience" |
| pages allowed | **1 or 2** | 1 only |

## ⭐ The one thing not to change

`\parskip` is `3pt plus 1pt`, not a flat `3pt`. That `plus` is **stretchable glue**: LaTeX distributes leftover vertical space across every paragraph break, so a short history opens up on its own rather than stacking at the top with a gap at the bottom.

⛔ **Do not hand-tune margins per résumé to fix spacing.** It makes every build a one-off and you lose the ability to say "they all look the same," which is what makes the 1-page check meaningful. If a build looks wrong, the glue has nothing to stretch into, not the margins being wrong.

## ⚠️ Do not remove the package guards

```latex
\IfFileExists{ragged2e.sty}{...}{\raggedright}
\IfFileExists{needspace.sty}{\usepackage{needspace}}{\providecommand{\needspace}[1]{}}
```

Both are optional niceties: ragged-right without hyphenation, and roles that never orphan across a page break. **A template that fails to compile on the recipient's install is worse than one that renders slightly plainer.**

A third guard sits above `\begin{document}`:

```latex
\IfFileExists{underscore.sty}{\usepackage{underscore}}{\catcode`\_=12\relax}
```

⛔ **Do not remove it either, and here is what it cost.** The `[PLACEHOLDER]` tokens contain the `_` character, and a bare `_` is a math subscript in LaTeX. Without this line the UNFILLED skeleton fails with about 95 errors, which is the file `install.sh` tells a new user to compile as their smoke test. Two more skeleton-only bugs sat with it: `\\` followed by `[CERTIFICATION]` read the placeholder as its optional vertical-space argument, and `\item [BULLET_1]` read the placeholder as the item's LABEL, so bullets rendered with no marker. That last one raised no error at all. It was only visible in the PDF.

⚖️ **The earlier "verified, compiles to 1 page" note on this file was measured on a FILLED résumé.** The skeleton was never compiled, so nothing that was checked could have caught any of the three.

**Verified 2026-08-09 on the skeleton as shipped:** compiles with 0 errors to 1 page, with `ragged2e`, `needspace` and `underscore` present, and again with all three forced absent; text extraction shows the bullets carrying their markers.

## Compile

    cd cv && pdflatex -interaction=nonstopmode main_<company>.tex

Then run the résumé build checklist: 1 page, reverse-chronological, summary under 300 characters, and a text-extraction check that your email and phone come out as literal text.
