#!/usr/bin/env python3
"""check_story_honesty.py — flag drift between a CA²R story's Honesty line and its own beats.

WHY THIS EXISTS (kit#77). The stage-2 stock-stories skill has a BUILD flow with no REVISE flow:
nothing tells a session that after a beat edit, the story's own Honesty line and the library's
top-level Pairing rules summary need a re-read. Reported live: a beat moved from "checked by
hand" to "verified" and the Honesty line kept saying the old thing until a full-file re-read
caught it by luck. Separately, a story's Honesty line claimed a pairing relationship with another
story ("pairs with story 7's Context, never told back to back with it") that the file's own
top-level Pairing rules summary never recorded, so the part a person skims first said nothing.

TWO CHEAP HEURISTICS, NOT NLP, BOTH ADVISORY ONLY:
1. A quoted phrase in a story's Honesty line ("about 3", "checked by hand") that no longer
   appears anywhere in that story's own beats. A quoted phrase is the shape the Honesty line
   already uses for the exact defensible figures and claims it binds — if the words vanished
   from the beats, the Honesty line may be describing a state the beats no longer carry.
   DELIBERATELY CONSERVATIVE: a quoted figure can be reworded honestly (a number spelled out one
   way in the beat and another in the Honesty line, a paraphrase that keeps the same fact), so
   this FLAGS, it never blocks, and a false positive costs one line of output, not a refusal.
2. A story whose Honesty line names another story in a pairing-shaped phrase ("pairs with story
   N", "alternate to story N", "stands behind story N", "second chair to story N") with no
   matching entry in the library's own "## Pairing rules" section.

WHAT THIS DOES NOT DO. It does not verify a figure is TRUE — that is the candidate's own
verification at build time, per the skill. It does not touch the file. A finding is a prompt to
re-read, exactly the step the skill was missing, never a refusal to proceed.

Usage:  scripts/check_story_honesty.py FILE.md
Exit:   0 = clean (or file not found — see below) · 1 = findings printed (still advisory)
"""
import re
import sys

_STORY_HEADING = re.compile(r"^### (\d+)\.\s*(.+?)\s*$", re.M)
_BEAT_LABEL = re.compile(r"^\*\*([^*]+?)[.:]\*\*\s*(.*)$")
_QUOTED = re.compile(r'"([^"]{2,80})"')
_PAIRING_PHRASE = re.compile(
    r"\b(?:pairs? with|alternate (?:to|for)|stands behind|second chair (?:to|for)|"
    r"never told back to back with)\b[^.]*?\bstory\s+(\d+)\b", re.I)


def parse_stories(text):
    """[(number, title, {label: body}, honesty_text)], one entry per "### N. ..." section."""
    heads = list(_STORY_HEADING.finditer(text))
    stories = []
    for i, m in enumerate(heads):
        start = m.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[start:end]
        beats = {}
        for line in body.splitlines():
            bm = _BEAT_LABEL.match(line.strip())
            if bm:
                beats[bm.group(1).strip().lower()] = bm.group(2).strip()
        honesty = beats.get("honesty", "")
        stories.append((m.group(1), m.group(2), beats, honesty))
    return stories


def pairing_section_text(text):
    """The body of a top-level '## Pairing rules' section, or "" if the file has none — the gap
    kit#77 reported: the skill never named this section, so most libraries have none at all."""
    m = re.search(r"^## Pairing rules\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


_FORBIDDEN_PHRASE = re.compile(r'\bnever\s+"', re.I)


def check_drift(story_num, title, beats, honesty):
    """Quoted Honesty phrases absent from the story's own other beats.

    Case-insensitive: a phrase quoted mid-sentence in the Honesty line often starts a sentence
    in the beat it came from, and a capitalization mismatch alone is not drift.

    Skips a quote immediately preceded by "never" — that shape ('never "rolled out
    network-wide"') is the Honesty line naming a FORBIDDEN claim the candidate must not make, not
    a fact the beats are supposed to state. Flagging it would fire on every story that uses this
    idiom, which is common in this file's own convention.
    """
    other = " ".join(v for k, v in beats.items() if k != "honesty").lower()
    findings = []
    for m in _QUOTED.finditer(honesty):
        phrase = m.group(1)
        preceding = honesty[max(0, m.start() - 8):m.start()]
        if _FORBIDDEN_PHRASE.search(preceding + '"'):
            continue
        if phrase.lower() not in other:
            findings.append(
                f"story {story_num} ({title}): Honesty line quotes {phrase!r}, not found "
                f"anywhere in this story's own beats — re-read after the last edit?")
    return findings


def check_pairing(story_num, title, honesty, pairing_text):
    """A pairing claim in this story's Honesty line with no matching Pairing rules entry."""
    findings = []
    for other_num in _PAIRING_PHRASE.findall(honesty):
        pair_mentioned = (
            re.search(r"\bstory\s+" + re.escape(story_num) + r"\b", pairing_text, re.I)
            and re.search(r"\bstory\s+" + re.escape(other_num) + r"\b", pairing_text, re.I))
        if not pair_mentioned:
            findings.append(
                f"story {story_num} ({title}): Honesty line claims a pairing with story "
                f"{other_num}, but the library's Pairing rules summary does not name both — "
                f"add it there, or the part read first says nothing about it")
    return findings


def check_file(path):
    """(findings, stories_checked). findings is a flat list of advisory strings."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        return ([f"{path}: could not read ({e.__class__.__name__}) — nothing checked"], 0)
    stories = parse_stories(text)
    if not stories:
        return ([f"{path}: no '### N. Title' story sections found — nothing checked"], 0)
    pairing_text = pairing_section_text(text)
    findings = []
    for num, title, beats, honesty in stories:
        if not honesty:
            continue
        findings += check_drift(num, title, beats, honesty)
        findings += check_pairing(num, title, honesty, pairing_text)
    return (findings, len(stories))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: check_story_honesty.py FILE.md", file=sys.stderr)
        return 2
    findings, checked = check_file(argv[0])
    if checked == 0:
        print(f"⚪ {findings[0] if findings else 'nothing to check'}")
        return 0
    if not findings:
        print(f"✅ {checked} stor{'y' if checked == 1 else 'ies'} checked, no Honesty/Pairing "
              "drift found")
        return 0
    print(f"🟡 {len(findings)} advisory finding(s) across {checked} stor"
          f"{'y' if checked == 1 else 'ies'} (never blocks — re-read, then decide):")
    for f in findings:
        print(f"   {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
