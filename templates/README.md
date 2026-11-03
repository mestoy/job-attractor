# Custom Templates

This folder holds user-registered LaTeX templates, managed by the `/add-template` command. The framework works out of the box with its bundled `plain-professional` template (pdflatex, 1 page); a conditional cover letter reuses that same template and is appended to the résumé — this folder only gets content when you register your own.

## What ships

| Template | Pages | Use it when |
|---|---|---|
| `cv/plain-professional` | 1 (strict) | The default. Single column, ATS friendly, breathing room. |
| `cv/nli-dense` | 1 or 2 | Your one pager reads sparse or top heavy, or your history genuinely needs a second page. |

Both are pdflatex + Helvetica, so there are no font files to install. Read the `TEMPLATE.md` inside a
template folder before you edit its `.tex`: it names the pitfalls that cost a rebuild.

**To switch to `nli-dense`:** point the "Active template" block in
`.claude/skills/job-application-assistant/05-cv-templates.md` at
`templates/cv/nli-dense/template.tex` and its manifest. That block is what `/apply` reads, so nothing
else needs changing. `verify_resume.py` picks up the 2 page allowance on its own, from the
`% PAGE-LIMIT: 1-2` line in the template.

## Layout

```
templates/
├── cv/
│   └── <template-name>/
│       ├── template.tex     # Profile-agnostic skeleton ([PLACEHOLDER] tokens)
│       ├── TEMPLATE.md      # Manifest: engine, fonts, page limit, style rules, pitfalls
│       ├── *.cls / *.sty    # Custom class/style files (if the template needs them)
│       └── fonts/           # Bundled font files (if not using system fonts)
└── cover_letters/
    └── <template-name>/
        └── (same layout)
```

## How it works

- `/add-template` interviews you for the template's instructions (compile engine, fonts, style rules, page limit), stores the files here, and runs a mandatory test compile before registering anything.
- Activating a template adds a managed block to `05-cv-templates.md` or `06-cover-letter-templates.md`, which is what `/apply` reads when drafting — no other wiring needed.
- `/add-template --list` shows registered templates; `/add-template --use <name>` switches; `/add-template --use default` reverts to the stock templates.

Templates are stored with `[PLACEHOLDER]` tokens instead of personal data, so they are safe to commit and share.
