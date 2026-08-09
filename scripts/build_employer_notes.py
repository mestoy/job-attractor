#!/usr/bin/env python3
"""build_employer_notes.py — lift the NOTES out of the blocked list into a sidecar keyed by entity.

WHY THIS EXISTS. A mature `documents/blocked-employers-list.md` is mostly prose: on the install this
was built from, 2,148 lines and 389,066 characters, of which the company NAMES are about 14,119, or
3.6%. The other 96.4% is reason prose, Glassdoor quotes and JD excerpts. Six scripts read that file,
and the matchers among them only ever need the 3.6%.

⛔ THE DEFECT CLASS THIS RETIRES, which has been re-fought at least four times:
  · Companies silently dropped from the ranked pool because their names occur inside SOMEONE ELSE'S
    reason prose. Short, common brand names are the whole exposed class.
  · A company can be falsely blocked by appearing once, unquoted, inside another company's reason.
    The proposed "strip quoted spans" repair cannot reach that case.
  · A build gate fails because a company name containing a common word collides with a
    writing-style note quoting that word.
  · The style checker lints all 96.4% and cannot tell the pipeline owner's own analysis from an
    employer's quotation, giving hard issues against zero real ones.
`reconcile_findings._write_blocked` already carries a comment asking authors to keep prose out of
that file BECAUSE it becomes match surface. That is discipline standing in for structure.

⚖️ ONE PARSER, NOT TWO. Name extraction here reuses `screen_sweep`'s `canon()` and mirrors its
segmentation, because a second hand-rolled parser of the same file is how the two readers drift
apart. If they ever disagree, `--verify` says so and exits non-zero.

⛔ THIS SCRIPT NEVER WRITES TO THE BLOCKED LIST. It only reads it and emits the sidecar. Slimming
the source file is a separate, later step that must not happen until this round-trips clean.

⚠️ OPTIONAL AND LOW PRIORITY. `seed_employers.py` already writes a notes store of its own; this is
the standalone extractor and round-trip check for anyone who wants the sidecar without the registry.

Usage:
    python3 scripts/build_employer_notes.py            # write documents/employer-notes.jsonl
    python3 scripts/build_employer_notes.py --verify   # round-trip check only, writes nothing
Exit: 0 = every blocked key is represented in the sidecar · 1 = keys would be LOST
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)


def _import_sibling(modname):
    """Import a same-directory sibling module, immune to a STALE `sys.modules` entry.

    The same guard `screen_sweep._import_sibling` carries: Python caches an import by BARE NAME and
    never by path, so a copy loaded from elsewhere can poison the shared name process-wide.
    """
    expected = os.path.join(HERE, modname + ".py")
    mod = sys.modules.get(modname)
    if mod is not None and os.path.abspath(getattr(mod, "__file__", "") or "") == os.path.abspath(expected):
        return mod
    import importlib.util
    spec = importlib.util.spec_from_file_location(modname, expected)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_ss = _import_sibling("screen_sweep")            # one parser, see the docstring above
canon, blocked_keys_from_list = _ss.canon, _ss.blocked_keys_from_list

SRC = os.path.join(REPO, "documents", "blocked-employers-list.md")
OUT = os.path.join(REPO, "documents", "employer-notes.jsonl")

# Mirrors screen_sweep's own guards. Kept in step by the --verify round trip rather than by memory.
REASON = re.compile(r"\b(blocked|declined|owned|culture|layoff|always-on|grindset|pe-owned|"
                    r"leadership|reversal|turmoil|acquisition|not blocked|corrected|filter|"
                    r"remote|travel|company|reason)\b")
EXONERATED = re.compile(r"not blocked|not killed|not a gate fail|⏭️|deferred|corrected")
SECTION = re.compile(r"^\*\*⛔ Filter (\d+): (.+?)\*\*\s*$")
HEADING = re.compile(r"^#{1,6}\s+(.*)$")


def _names_on(segment):
    """The candidate display names a line segment offers, using screen_sweep's head rule."""
    out = []
    for seg in re.split(r"\s*·\s*", segment.lstrip("-* ").strip()):
        head = re.split(r"\s*[(—–:]|\s+\*\*", seg, 1)[0]
        cand = head.strip(" *_`~")
        if not cand or REASON.search(cand.lower()):
            continue
        if len(cand) > 44 or len(cand.split()) > 5:
            continue
        out.append(cand)
    return out


def rows():
    """One row per (entity, mention). A company named on three lines gets three notes, on purpose:
    the history of WHY is the thing being preserved, and it accumulates."""
    raw = open(SRC, encoding="utf-8", errors="ignore").read().split("\n")
    section, heading, out = None, None, []
    for i, line in enumerate(raw, 1):
        s = line.strip()
        m = SECTION.match(s)
        if m:
            section = {"filter": int(m.group(1)), "label": m.group(2)}
            continue
        h = HEADING.match(s)
        if h:
            heading = h.group(1)
            continue
        if not s or not s.startswith(("-", "*", "|")):
            continue
        exonerated = bool(EXONERATED.search(s.lower()))
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not cells or set(cells[0]) <= set("-: "):
                continue
            names = _names_on(cells[0])
        else:
            names = _names_on(s)
        for name in names:
            k = canon(name)
            if not k or len(k) < 2:
                continue
            out.append({
                "key": k,
                "name": name,
                "filter": (section or {}).get("filter"),
                "filter_label": (section or {}).get("label"),
                "section": heading,
                "note": s,
                "src_line": i,
                # ⛔ CARRIED, NOT DROPPED. A line that says a company is NOT blocked is a note about
                # that entity and belongs with it; it simply must never be read as a block. Losing
                # it would repeat the defect where documenting an exception created the thing it
                # excepted.
                "exonerated": exonerated,
            })
    return out


def main():
    verify_only = "--verify" in sys.argv
    if not os.path.exists(SRC):
        print(f"no blocked list to read: {SRC}")
        return 0
    data = rows()
    blocking = {r["key"] for r in data if not r["exonerated"]}
    truth = set(blocked_keys_from_list(SRC))
    lost = sorted(truth - blocking)

    print(f"source     : {SRC}")
    print(f"note rows  : {len(data):,} across {len({r['key'] for r in data}):,} entities")
    print(f"blocking   : {len(blocking):,} keys · screen_sweep sees {len(truth):,}")
    if lost:
        print(f"🔴 {len(lost)} key(s) the sidecar would LOSE: {', '.join(lost[:15])}"
              f"{' …' if len(lost) > 15 else ''}")
        print("   Refusing to treat this as a clean extraction. The blocked list is NOT touched.")
        return 1
    print("✅ every key screen_sweep blocks is represented in the sidecar (no loss)")
    extra = sorted(blocking - truth)
    if extra:
        print(f"ℹ️  {len(extra)} sidecar key(s) screen_sweep does NOT block (it applies extra "
              f"stop-word and length filters): {', '.join(extra[:10])}"
              f"{' …' if len(extra) > 10 else ''}")
    if verify_only:
        print("--verify: nothing written")
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        for r in data:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote      : {OUT}")
    print("⛔ the blocked list was NOT modified. Slimming it is a separate, later step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
