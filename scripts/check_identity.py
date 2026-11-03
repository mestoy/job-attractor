#!/usr/bin/env python3
"""check_identity.py -- a GATE (unlike check_tokens.py, which only reports).

Fails when app/design/app2.py or app/design/phases/*.py drift from the token system in
tokens.css / tokens.json:

  1. a custom property (`--name:`) declared outside app/design/tokens.css, unless its
     name is on the short allowlist below (--phase-backbar-h, the motion vars, and the
     ELEVATION_FALLBACK names e1/e2/e3/raised-radius, which onboard.py substitutes as
     __E1__/__E2__/__E3__/__RAISED_RADIUS__ placeholders, not real properties)
  2. a `font-size` in px off the type scale (11, 13, 16, 19, 23, 28, 33, 40, 48)
  3. a `font-family` other than the token faces in tokens.json (display, body, mono,
     third) with their documented fallback stacks
  4. a hex color literal outside a var() fallback and outside an allowlisted custom
     property declaration (those are already caught by check 1)
  5. a `var(--x, fallback)` whose fallback differs from tokens.css's light value for
     --x (placeholder fallbacks like __E2__ are not literals and are skipped)

Plan: documents/plan-screen-continuity-and-navigation-2026-09-15.md section 5.
Baseline: scripts/identity_baseline.json holds today's violation COUNTS per
(file, rule) so the gate is green now and red only on NEW drift past that count.
Each slice that fixes a class of drift should lower its baseline entry (or delete it
once a file/rule reaches zero) -- the baseline never grows on its own.

Usage:  scripts/check_identity.py
Exit:   0 = no drift past baseline · 1 = new drift (printed, file:line)
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DESIGN_DIR = os.path.join(REPO, "app", "design")
PHASES_DIR = os.path.join(DESIGN_DIR, "phases")
TOKENS_CSS = os.path.join(DESIGN_DIR, "tokens.css")
TOKENS_JSON = os.path.join(DESIGN_DIR, "tokens.json")
BASELINE_PATH = os.path.join(HERE, "identity_baseline.json")

# Names allowed to be declared as custom properties OUTSIDE tokens.css. Section 5,
# verbatim: "(--phase-backbar-h, motion vars, ELEVATION_FALLBACK)". ELEVATION_FALLBACK
# itself is a Python dict (onboard.py), never a CSS custom property, so there is
# nothing named e1/e2/e3 to allowlist here in practice -- listed anyway so a future
# literal --e1/--e2/--e3/--raised-radius declaration does not need a new baseline row.
ALLOWLISTED_PROPERTY_NAMES = {
    "phase-backbar-h",
    "motion-dur",
    "motion-ease",
    "e1",
    "e2",
    "e3",
    "raised-radius",
}

FONT_SCALE_PX = {11, 13, 16, 19, 23, 28, 33, 40, 48}

# Fallback substitution placeholders onboard.py writes into var(--x, __NAME__) before
# tokens.json's elevation lands -- not literal values, never a fallback-diff violation.
PLACEHOLDER_FALLBACKS = {"__E1__", "__E2__", "__E3__", "__RAISED_RADIUS__"}

CUSTOM_PROP_DECL_RE = re.compile(r"--([A-Za-z][A-Za-z0-9-]*)\s*:")
FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+)px")
# Some font-family values are split across concatenated Python string literals
# (a `+`-joined multi-line JS-building block); this one is matched over the whole
# file text, lazily, up to the first plausible terminator, rather than per line.
FONT_FAMILY_RE = re.compile(r"font-family:\s*([^;}]+)")
FONT_FAMILY_MULTILINE_RE = re.compile(
    r"font-family:\s*((?:(?!;|\"\s*>)[\s\S]){1,300}?)(?:;|\"\s*>)")
VAR_FALLBACK_RE = re.compile(r"var\(\s*--([A-Za-z][A-Za-z0-9-]*)\s*,\s*([^)]+)\)")
HEX_RE = re.compile(r"(?<!&)#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})\b(?!:)")


def _load_token_faces():
    """Every allowed font-family value: each token face's declared stack, verbatim and
    with the quote characters normalized, plus the bare family name alone (some rules
    set only `font-family: "Nunito Sans"` without the fallback chain)."""
    with open(TOKENS_JSON, encoding="utf-8") as f:
        tokens = json.load(f)
    allowed = set()
    for spec in tokens["fonts"].values():
        if not isinstance(spec, dict) or "stack" not in spec:
            continue
        allowed.add(_normalize_family(spec["stack"]))
        allowed.add(_normalize_family(f'"{spec["family"]}"'))
    # IBM Plex Mono is the untouched mono face (tokens.json's own note) -- its stack
    # as shipped in tokens.css / _style.txt, quotes and all.
    allowed.add(_normalize_family('"IBM Plex Mono",ui-monospace,Menlo,monospace'))
    allowed.add(_normalize_family('"IBM Plex Mono",monospace'))
    allowed.add(_normalize_family('"IBM Plex Mono"'))
    return allowed


def _normalize_family(value):
    # A family value pulled from a JS-building string can carry two kinds of noise
    # a hand-written stack never has: escaped quotes (\' or \\') standing in for the
    # real quote around a family name, and Python string-concatenation glue (a bare
    # '+' and the plain, unescaped quotes that delimit adjacent literals) where the
    # source wraps the line. Escaped quotes are real content -- normalize them to a
    # plain double quote. Bare quotes and '+' are glue -- drop them outright.
    value = value.replace("\\\\'", "\x00").replace("\\'", "\x00")
    value = value.replace("'", "").replace("+", "")
    value = value.replace("\x00", '"')
    value = re.sub(r"\s+", "", value)
    value = value.strip('"').replace('""', '"')
    value = value.rstrip(",")
    return value.lower()


def _load_token_light_values():
    """--name -> light-theme literal value, parsed from tokens.css's first :root
    block (the unqualified block is the light/default theme)."""
    with open(TOKENS_CSS, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r":root\s*\{([^}]*)\}", text)
    if not m:
        return {}
    body = m.group(1)
    values = {}
    for decl in body.split(";"):
        decl = decl.strip()
        if not decl or ":" not in decl:
            continue
        name, _, value = decl.partition(":")
        name = name.strip()
        if name.startswith("--"):
            values[name[2:]] = value.strip()
    return values


def _target_files():
    files = [os.path.join(DESIGN_DIR, "app2.py")]
    if os.path.isdir(PHASES_DIR):
        for name in sorted(os.listdir(PHASES_DIR)):
            if name.endswith(".py"):
                files.append(os.path.join(PHASES_DIR, name))
    return [f for f in files if os.path.isfile(f)]


def _is_full_comment_line(line):
    return line.strip().startswith("#")


def _values_match(fallback, css_value):
    fallback = fallback.strip()
    css_value = css_value.strip()
    if fallback.upper() == css_value.upper():
        return True
    # px values: "24px" vs "24 px" style differences don't occur here, but normalize
    # whitespace defensively.
    return re.sub(r"\s+", "", fallback).upper() == re.sub(r"\s+", "", css_value).upper()


def scan(path, token_faces, token_light_values):
    """Returns a list of (rule, lineno, message) findings for one file."""
    findings = []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    for i, line in enumerate(lines, 1):
        if _is_full_comment_line(line):
            continue

        # 1. custom property declared outside tokens.css
        for m in CUSTOM_PROP_DECL_RE.finditer(line):
            name = m.group(1)
            if name.lower() in ALLOWLISTED_PROPERTY_NAMES:
                continue
            findings.append(("custom_property", i,
                              f"--{name}: declared outside tokens.css"))

        # 2. font-size off scale
        for m in FONT_SIZE_RE.finditer(line):
            px = int(m.group(1))
            if px not in FONT_SCALE_PX:
                findings.append(("font_size_scale", i,
                                  f"font-size:{px}px is off the scale "
                                  f"{sorted(FONT_SCALE_PX)}"))

        # 4. bare hex literal (not a property declaration, not a var() fallback)
        decl_spans = [m.span() for m in CUSTOM_PROP_DECL_RE.finditer(line)]
        var_spans = [m.span() for m in VAR_FALLBACK_RE.finditer(line)]
        for m in HEX_RE.finditer(line):
            start = m.start()
            in_decl = any(ds <= start < de + 40 for ds, de in decl_spans)
            in_var = any(vs <= start < ve for vs, ve in var_spans)
            if in_decl or in_var:
                continue
            findings.append(("hex_literal", i,
                              f"#{m.group(1)} is a bare hex literal"))

        # 5. var() fallback differing from tokens.css light value
        for m in VAR_FALLBACK_RE.finditer(line):
            name, fallback = m.group(1), m.group(2).strip()
            if fallback in PLACEHOLDER_FALLBACKS:
                continue
            if "var(" in fallback:
                continue  # nested var(), not a literal fallback
            if not (HEX_RE.match(fallback) or re.match(r"^-?\d+(\.\d+)?px$", fallback)
                    or re.match(r"^-?\d+ms$", fallback) or re.match(r"^\d+$", fallback)):
                continue  # not a literal we can compare (e.g. a calc() or keyword)
            css_value = token_light_values.get(name)
            if css_value is None:
                continue  # not a known token name, nothing to compare against
            if not _values_match(fallback, css_value):
                findings.append(("var_fallback", i,
                                  f"var(--{name}, {fallback}) fallback differs from "
                                  f"tokens.css light value {css_value}"))

    # 3. font-family other than token faces -- scanned over the whole file text
    # (not per line) because a value can be split across concatenated string
    # literals; the line number is recovered from the match offset.
    full_text = "".join(lines)
    for m in FONT_FAMILY_MULTILINE_RE.finditer(full_text):
        raw = m.group(1)
        if "__DISPLAY__" in raw or "__BODY__" in raw:
            continue  # onboard.py substitution placeholder, resolved at render
        lineno = full_text.count("\n", 0, m.start()) + 1
        if _is_full_comment_line(lines[lineno - 1]):
            continue
        normalized = _normalize_family(raw)
        if normalized not in token_faces:
            collapsed = re.sub(r"\s+", " ", raw.strip())
            findings.append(("font_family", lineno,
                              f"font-family: {collapsed} is not a token face"))

    findings.sort(key=lambda f: f[1])
    return findings


def _load_baseline():
    if not os.path.isfile(BASELINE_PATH):
        return {}
    with open(BASELINE_PATH, encoding="utf-8") as f:
        return json.load(f)


def main():
    token_faces = _load_token_faces()
    token_light_values = _load_token_light_values()
    baseline = _load_baseline()

    all_findings = {}  # rel_path -> list of (rule, lineno, message)
    counts = {}  # rel_path -> {rule: count}
    for path in _target_files():
        rel = os.path.relpath(path, REPO)
        findings = scan(path, token_faces, token_light_values)
        if findings:
            all_findings[rel] = findings
        file_counts = {}
        for rule, _lineno, _msg in findings:
            file_counts[rule] = file_counts.get(rule, 0) + 1
        if file_counts:
            counts[rel] = file_counts

    new_drift = []
    for rel, findings in all_findings.items():
        base_counts = baseline.get(rel, {})
        cur_counts = counts[rel]
        for rule, lineno, message in findings:
            base = base_counts.get(rule, 0)
            cur = cur_counts.get(rule, 0)
            # Only the count IN EXCESS of the baseline is new drift; print every
            # finding either way so the file:line is always visible for triage.
            over = cur > base
            tag = "NEW DRIFT" if over else "baselined"
            print(f"check_identity: {tag} {rel}:{lineno}: {message}")
        for rule, cur in cur_counts.items():
            base = base_counts.get(rule, 0)
            if cur > base:
                new_drift.append((rel, rule, base, cur))

    if new_drift:
        print("\ncheck_identity: FAIL -- new drift past the baseline:")
        for rel, rule, base, cur in new_drift:
            print(f"  {rel}: {rule} baseline={base} now={cur}")
        return 1

    print(f"check_identity: PASS -- {sum(len(v) for v in all_findings.values())} "
          f"finding(s), none past baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
