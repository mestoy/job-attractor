#!/usr/bin/env python3
"""voice_samples.py — inspect YOUR writing BEFORE composing.

Read-only helper that mechanizes "read the right samples fresh before drafting."
Given a message TYPE, it surfaces the most relevant NAMED writing samples from
`documents/writing-samples.md` (verbatim text + their annotated cadence lessons),
plus a short block of UNIVERSAL cadence rules, so the composer models YOUR
actual voice instead of a generic AI register.

Usage:
    python3 scripts/voice_samples.py <type>
    python3 scripts/voice_samples.py            # list types + universal rules
    python3 scripts/voice_samples.py --help

Types: cold-boss · warm-rung · follow-up · reply · thank-you ·
       application-answer · narrative · linkedin

Fill `documents/writing-samples.md` with your own numbered samples (`## Sample 1`,
`## Sample 2`, …) and adjust TYPE_MAP below to point each situation at the sample
that best models it. NO writes. Standard library only. Degrades gracefully if the
source files are missing.
"""

import os
import re
import sys

REPO = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLES_PATH = os.path.join(REPO, "documents", "writing-samples.md")
STYLE_PATH = os.path.join(REPO, "documents", "writing-style-guide.md")

# Each message TYPE -> the ordered list of most-relevant sample numbers.
# Order matters: the first sample is the primary model for that situation.
# These defaults assume a corpus laid out like the starter guide; renumber to
# match your own `documents/writing-samples.md`.
TYPE_MAP = {
    "cold-boss": [4],            # cold/warm outreach hook shape (the 3-beat 👋🏽 note)
    "warm-rung": [6, 4, 7],      # warm-rung note — the richest warm-intro model leads
    "follow-up": [7],            # short warm bump; hold length, keep the register
    "reply": [7],                # replying to a warm contact — match brevity, ALWAYS ask them something back
    "thank-you": [7],            # short, warm, no vocabulary-mirroring
    "application-answer": [5],   # free-response — write TIGHTER, one vivid phrase carries it
    "narrative": [5, 1],         # long-form story voice — tight + one controlling image
    "linkedin": [1],             # About/profile register
}

# One-line situational note per type (printed in the type list + as a header).
TYPE_BLURB = {
    "cold-boss": "cold direct-to-boss note — the 3-beat 👋🏽 hook (researched hook → your credential proof → light ask)",
    "warm-rung": "warm-rung intro ask — land on THEM first, cut the throat-clearing, one absurd image carries the favor beat",
    "follow-up": "plain bump — float the note back up, no re-pitch, close on an explicit no-pressure line",
    "reply": "reply to a warm contact — match their brevity, ask a question BACK (a reply is a turn in a conversation, not a delivery), reach for SHARED HISTORY rather than commenting on their present, and state the shared circumstance instead of naming anyone's feelings. Never hand someone their own fear-words back, and do not mirror their slang: borrow your own warmth, do not copy theirs",
    "thank-you": "short warm thanks — friendly close takes a '!', keep it to a few sentences",
    "application-answer": "application free-response — write TIGHTER, two short paragraphs, end on a punchy declarative",
    "narrative": "long-form story voice — image-rich, outcomes-obsessed, one controlling image carries the frame",
    "linkedin": "LinkedIn About / profile register — short lines, concrete proof, a wry human close",
}

# UNIVERSAL cadence rules — always printed. Mirrors the sentence-cadence WARN in
# scripts/check_outreach.py and the "shortest/plainest wins" rule in the style guide.
UNIVERSAL = [
    "Short hooks. Keep outreach hooks to ~28 words max and lean on ONE idea, not a nested clause stack.",
    "The \"X, where Y\" hook shape: name the thing, then one tight relative clause that says why it matters "
    "(\"a warehouse-native CDP, where data teams own their pipeline instead of renting it\").",
    "One vivid phrase carries the beat. A single concrete image lands harder than an abstract qualifier — "
    "pull the image from YOUR own writing-samples.md, not a generic register.",
    "Shortest, plainest construction wins. If two options say the same thing, take the shorter one; "
    "cut throat-clearing, scene-setting, and \"proving I read you.\"",
    "Land on the other person before yourself. Go to their present first, then your news/ask — never open on the gap.",
    "NO comma-stacked run-on. A sentence over ~30 words, or 3+ commas in a longish sentence, reads clunky — "
    "tighten it and let one phrase do the lifting. (This mirrors the sentence-cadence WARN in scripts/check_outreach.py.)",
]

# ── light box-drawing helpers (terminal-friendly, no external deps) ─────────────
BAR = "─" * 78


def _hdr(text):
    return "\n" + BAR + "\n" + text + "\n" + BAR


def _note(msg):
    """Friendly degrade message to stderr-ish inline (kept on stdout for scannability)."""
    return "  (!) " + msg


# ── parsing ─────────────────────────────────────────────────────────────────────
def parse_samples(text):
    """Parse writing-samples.md generically by splitting on `^## Sample N` headers.

    Returns {num: {"num", "title", "verbatim", "context", "lessons"}}.
    Stays correct if samples are added: any level-2 header that is not a Sample is skipped.
    """
    samples = {}
    # Split on every level-2 header, KEEPING the header text (capturing group).
    # ⛔ LEVEL 2 OR 3. This matched `^##\s` only, so a corpus written with `### Sample 1` never
    # matched: after two hashes came a third rather than whitespace. The reader then reported the
    # corpus EMPTY against a file holding eight real sent emails. The corpus file's own "How to add
    # a sample" section never states a heading level, so nothing told the writer which to use.
    parts = re.split(r"(?m)^(#{2,3}\s+.*)$", text)
    # parts = [preamble, header1, body1, header2, body2, ...]
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        m = re.match(r"#{2,3}\s+Sample\s+(\d+)\s*[—–-]?\s*(.*)$", header)
        if not m:
            continue
        num = int(m.group(1))
        title = m.group(2).strip()
        samples[num] = _parse_block(num, title, body)
    return samples


def _parse_block(num, title, body):
    """Split one sample block into verbatim (blockquote), setup context, and cadence lessons."""
    lines = body.splitlines()

    # The lessons region begins at the first annotation header ("Voice tells" / "Lesson").
    lesson_start = None
    for idx, ln in enumerate(lines):
        flat = ln.strip().strip("*").strip().lower()
        if flat.startswith("voice tells") or flat.startswith("lesson:") or flat.startswith("lesson"):
            lesson_start = idx
            break

    if lesson_start is None:
        sample_lines, lesson_lines = lines, []
    else:
        sample_lines, lesson_lines = lines[:lesson_start], lines[lesson_start:]

    verbatim, context = [], []
    for ln in sample_lines:
        st = ln.strip()
        if st.startswith(">"):
            v = st[1:]
            if v.startswith(" "):
                v = v[1:]
            verbatim.append(v.rstrip())        # keep empty blockquote lines as paragraph breaks
        elif st:
            context.append(st)

    # Trim leading/trailing blank verbatim lines.
    while verbatim and not verbatim[0].strip():
        verbatim.pop(0)
    while verbatim and not verbatim[-1].strip():
        verbatim.pop()

    lessons = [ln.strip() for ln in lesson_lines if ln.strip()]
    return {"num": num, "title": title, "verbatim": verbatim, "context": context, "lessons": lessons}


def _clean_lesson(line):
    """Light markdown cleanup for a lesson line: strip bullet markers and bold."""
    s = line
    for lead in ("- ", "* ", "• "):
        if s.startswith(lead):
            s = s[len(lead):]
            break
    s = s.replace("**", "")
    return s.strip()


# ── rendering ─────────────────────────────────────────────────────────────────
def render_sample(s):
    out = [_hdr("Sample {num} — {title}".format(**s))]
    if s["context"]:
        out.append("Setup:")
        for c in s["context"]:
            out.append("  " + c)
        out.append("")
    if s["verbatim"]:
        out.append("Verbatim (copy the VOICE, never the facts):")
        for v in s["verbatim"]:
            out.append("  │ " + v if v.strip() else "  │")
    else:
        out.append(_note("no verbatim blockquote found in this sample"))
    if s["lessons"]:
        out.append("")
        out.append("Cadence lessons:")
        for ln in s["lessons"]:
            cleaned = _clean_lesson(ln)
            if not cleaned:
                continue
            # Annotation section headers ("Voice tells …:") get no bullet; teardown points do.
            low = cleaned.lower()
            if low.startswith("voice tells") or low.startswith("lesson:"):
                out.append("  " + cleaned)
            else:
                out.append("  • " + cleaned)
    return "\n".join(out)


def render_universal():
    out = [_hdr("UNIVERSAL cadence rules (always apply)")]
    for r in UNIVERSAL:
        out.append("  • " + r)
    out.append("")
    out.append("  Full rulebook + ban list: documents/writing-style-guide.md")
    out.append("  Raw voice corpus:         documents/writing-samples.md")
    return "\n".join(out)


def render_type_list():
    out = [_hdr("voice_samples.py — read the RIGHT samples before you compose")]
    out.append("Usage: python3 scripts/voice_samples.py <type>")
    out.append("")
    out.append("Message types:")
    width = max(len(t) for t in TYPE_MAP)
    for t in TYPE_MAP:
        nums = TYPE_MAP[t]
        stem = "Sample " if len(nums) == 1 else "Samples "
        label = stem + ", ".join(str(n) for n in nums)
        out.append("  {0:<{w}}  {1}".format(t, label, w=width))
        out.append("  {0:<{w}}  {1}".format("", TYPE_BLURB[t], w=width))
    return "\n".join(out)


# ── main ─────────────────────────────────────────────────────────────────────
def main(argv):
    args = [a for a in argv[1:] if a]
    want_list = (not args) or args[0] in ("--help", "-h", "help")

    if want_list:
        print(render_type_list())
        print()
        print(render_universal())
        return 0

    mtype = args[0].strip().lower()
    if mtype not in TYPE_MAP:
        print("Unknown type: {0!r}".format(mtype))
        print()
        print(render_type_list())
        return 2

    # Load + parse the corpus (degrade gracefully).
    if not os.path.exists(SAMPLES_PATH):
        print(_note("writing-samples.md not found at {0}".format(SAMPLES_PATH)))
        print(_note("cannot surface verbatim samples; showing universal rules only."))
        print()
        print(render_universal())
        return 1

    try:
        with open(SAMPLES_PATH, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(_note("could not read writing-samples.md: {0}".format(exc)))
        print()
        print(render_universal())
        return 1

    samples = parse_samples(text)

    print(_hdr("TYPE: {0}".format(mtype)))
    print(TYPE_BLURB[mtype])
    # ⚠️ AN EMPTY CORPUS MUST NOT BE TOLD TO READ SAMPLE 4 (fixed 2026-08-05). The shipped
    # writing-samples.md is a TEMPLATE, so on a first run this printed "Read these samples FRESH:
    # Sample 4" and pointed at something that has never existed. A tool that names a thing the user
    # does not have reads as broken rather than as empty, on their very first command.
    # ⚠️ ASK WHETHER THIS TYPE'S SAMPLES EXIST, not whether ANY do. The shipped template carries a
    # worked EXAMPLE block whose heading parses as a real sample, so `samples` is non-empty on a
    # first run while the sample this type needs is still absent. Checking the wrong set is how the
    # first-run message kept pointing at a sample nobody has.
    have = [n for n in TYPE_MAP[mtype] if n in samples]
    if not have:
        # ⛔ ABSENCE OF A MATCH IS NOT ABSENCE OF CONTENT, and saying the second when the first is
        # true sends the operator to redo work already done. This branch used to announce the
        # corpus EMPTY and prescribe fifteen minutes of filling, against a file that already held
        # eight verbatim sent emails the reader simply could not see.
        try:
            with open(SAMPLES_PATH, encoding="utf-8") as _fh:
                _lines = len(_fh.read().splitlines())
        except OSError:
            _lines = 0
        if samples:
            print(f"⚠️ No sample is mapped to '{mtype}' yet, though the corpus holds "
                  f"{len(samples)} sample(s). Everything below is the universal rules.")
        elif _lines > 5:
            print(f"⚠️ NO sample headers matched in a corpus of {_lines} lines. That is a PARSE "
                  f"result, not an empty file: check the sample headings are `## Sample N` or "
                  f"`### Sample N`. Everything below is the universal rules.")
        else:
            print("⚠️ Your corpus is empty, so there are no samples to read yet. Everything below "
                  "is the universal rules.")
            print("   Fill it in about 15 minutes with `/voice-setup`. Until you do, outreach "
                  "drafts come out in a generic register, which is the one thing that makes a "
                  "message look automated.")
    else:
        print("Read these samples FRESH before drafting: Sample " +
              ", ".join(str(n) for n in TYPE_MAP[mtype]) + ".")

    for n in TYPE_MAP[mtype]:
        if n in samples:
            print(render_sample(samples[n]))
        else:
            print(_hdr("Sample {0}".format(n)))
            print(_note("Sample {0} is mapped to '{1}' but was not found in writing-samples.md "
                        "(was it renumbered?)".format(n, mtype)))

    print(render_universal())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
