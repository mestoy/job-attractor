#!/usr/bin/env python3
"""scorecard_repalette.py — bring already-published scorecard pages onto the colorblind-safe palette.

WHY. Story S30 (2026-09-10): a kit user is colorblind, and the scorecard's good, warn and bad
states were green, amber and red, the pair colorblind readers confuse most. The template now
carries palette D (blue, orange, plum on pink) plus a glyph before every pill and chip. Pages
rendered before that keep their own inline <style>, so they would stay wrong forever. This
script rewrites ONLY the six state tokens in each theme block and adds the glyph rules; every
other byte of the page, including hand-written sections the renderer cannot reproduce, is
left as it is. Re-rendering would have lost those sections.

Idempotent: a page already on the new palette is reported and skipped.

Usage:
    python3 scripts/scorecard_repalette.py DIR            # dry run, lists what would change
    python3 scripts/scorecard_repalette.py DIR --apply
"""
import argparse
import glob
import os
import re
import sys

LIGHT_OLD = "--good:#2E7D5B; --good-soft:#DFF0E7; --warn:#A8701A; --warn-soft:#F6EBD3; --bad:#B23A3A; --bad-soft:#F5DEDE;"
LIGHT_NEW = "--good:#1F5FA8; --good-soft:#DCE8F7; --warn:#8A5400; --warn-soft:#F7E8CC; --bad:#3A0F26; --bad-soft:#F2CFE1;"
DARK_OLD = "--good:#7CC9A3; --good-soft:#1C3A2D; --warn:#E0B266; --warn-soft:#3D3019; --bad:#E08A8A; --bad-soft:#42201F;"
DARK_NEW = "--good:#8DB9F0; --good-soft:#1B2E4A; --warn:#F0B849; --warn-soft:#3E2E10; --bad:#FBD9EC; --bad-soft:#52153D;"
VIEWPORT = '<meta name="viewport" content="width=device-width,initial-scale=1">'
# S31: a raw URL in card prose is one unbreakable token. 25 of 92 cards carried one (worst 155
# chars), and with no wrap rule anywhere it drags the page body sideways at 400px -- the tables
# are already safe inside their own overflow-x boxes, so body copy was the last thing that could
# force a horizontal scroll. Anchored on the body rule the template and every rendered card share.
BODY_OLD = "font-size:15px;line-height:1.5}"
# S32: the light theme's caption color failed WCAG on BOTH surfaces it is used on --
# 3.66:1 on panel, 3.35:1 on paper, against a 4.5:1 floor for the 11-13px it renders at.
# #657181 is the lightest value that clears both (4.96 / 4.54). The DARK theme's own
# --ink-3 (#8290A2) already passes at 4.98/5.48 and is deliberately NOT touched, so this
# is a light-theme-only, single-token change.
INK3_OLD = "--ink-3:#7A8797;"
INK3_NEW = "--ink-3:#657181;"
BODY_NEW = "font-size:15px;line-height:1.5;overflow-wrap:anywhere;word-break:break-word}"
GLYPH_ANCHOR = ".pill.acc{background:var(--accent-soft);color:var(--accent)}"
GLYPH_CSS = GLYPH_ANCHOR + """
/* S30: state carries a glyph as well as a hue, so colorblind readers never depend on color alone */
.pill::before,.chip::before{display:inline-block;margin-right:5px;font-weight:700}
.pill.good::before{content:"\\2713"}
.pill.warn::before{content:"!"}
.pill.bad::before{content:"\\2715"}
.pill.acc::before{content:"\\25CB"}
.chip.strong::before{content:"\\2713"}
.chip.partial::before{content:"!"}"""
OLD_TOKENS = ("#2E7D5B", "#7CC9A3", "#A8701A", "#B23A3A")


def repalette(text):
    """Returns (new_text, changed, notes)."""
    notes = []
    out = text
    n_light = out.count(LIGHT_OLD)
    n_dark = out.count(DARK_OLD)
    out = out.replace(LIGHT_OLD, LIGHT_NEW).replace(DARK_OLD, DARK_NEW)
    if n_light:
        notes.append(f"light tokens x{n_light}")
    if n_dark:
        notes.append(f"dark tokens x{n_dark}")
    # His 2026-09-10 rule that every rendered surface is responsive. Without this a phone lays the
    # page out at 980px and crops it; a published Artifact hides the defect because the publish
    # wrapper supplies one, so it only bites when the file is opened off disk.
    if 'name="viewport"' not in out:
        if "<title>" in out:
            out = out.replace("<title>", VIEWPORT + "\n<title>", 1)
            notes.append("viewport added")
        else:
            notes.append("no <title> to anchor a viewport meta")
    if INK3_NEW not in out and INK3_OLD in out:
        out = out.replace(INK3_OLD, INK3_NEW, 1)
        notes.append("caption contrast fixed")
    if BODY_NEW not in out and BODY_OLD in out:
        out = out.replace(BODY_OLD, BODY_NEW, 1)
        notes.append("wrap added")
    if ".pill.good::before" not in out and GLYPH_ANCHOR in out:
        out = out.replace(GLYPH_ANCHOR, GLYPH_CSS, 1)
        notes.append("glyphs added")
    leftover = [t for t in OLD_TOKENS if t in out]
    if leftover:
        notes.append("old token still present: " + ", ".join(leftover))
    return out, out != text, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    changed = skipped = 0
    blocked = []
    for p in sorted(glob.glob(os.path.join(a.dir, "*.html"))):
        with open(p, encoding="utf-8") as f:
            text = f.read()
        new, did, notes = repalette(text)
        name = os.path.basename(p)
        if not did:
            skipped += 1
            if any("still present" in n for n in notes):
                print(f"UNCHANGED, needs a hand look: {name} ({'; '.join(notes)})")
            continue
        changed += 1
        print(f"{'patched' if a.apply else 'would patch'}: {name} ({'; '.join(notes)})")
        if a.apply:
            # One unwritable file must never abort the batch. fake-medical-2026-09-06.html is
            # mode 400 on this install, and an earlier version of this script died on it and left
            # every alphabetically-later page unprocessed.
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new)
            except OSError as exc:
                blocked.append((name, exc.strerror or str(exc)))
                changed -= 1
    print(f"{'patched' if a.apply else 'would patch'} {changed}, unchanged {skipped}")
    for name, why in blocked:
        print(f"BLOCKED, left as it was: {name} ({why})")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
