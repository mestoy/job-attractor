#!/usr/bin/env python3
"""render_scorecard.py — kit #88: turn a company card markdown into an HTML scorecard.

WHY THIS EXISTS. Kit issue #88 found that a partner install (Matthew's) produces no
scorecard HTML at all: the card markdown → HTML step only ever existed as a Claude
session hand-writing HTML into the Artifact tool from a card, never as checked-in code
(see documents/state/matthew-card-step-evidence-*.md and c1's finding). This script is
the mechanical version of that step, so it runs on any install.

THE CARD CONTRACT, per documents/state/scorecard-contract-survey-53-2026-09-09.md
(67 real cards, 43 existing HTMLs walked by hand): a card's `## ` section headers are
NOT stable text — dates, seat names and qualifiers get folded into the heading itself
("Panel", "Panel (calibration addendum applied)", "Panel (0-100, calibration addendum
applied verbatim)" are the same slot). What IS stable is a set of ~13 semantic slots,
matched by keyword against the header line, never by exact string. REQUIRED_SLOTS below
are present in a clear majority of real cards; OPTIONAL_SLOTS are legitimately absent on
many cards and are rendered only when present.

VERDICT-AWARE VALIDATION. A DROP/PARK card stops after the first failing gate by design
(confirmed by the survey's thin-card cluster — sample companies alpha/beta/gamma and
friends, 1-2 of 13 required slots, on purpose, not damage). Missing required slots are
only reported as a problem when the card's own verdict reads BUILD or RADAR.

CSS. The <style> block in templates/scorecard/scorecard-template.html is the version
named canonical by the plan (documents/state/scorecard-template-plan-53-2026-09-09-v2.md):
copied from the file the reference install already treats as its template. The survey
found 7 drifted style variants across already-published cards; this script does not
attempt to reconcile them, only new renders use the canonical CSS.

Usage:
    python3 scripts/render_scorecard.py CARD.md [--out DIR]
    python3 scripts/render_scorecard.py --backfill DIR [--out DIR]
    python3 scripts/render_scorecard.py --reindex DIR
"""
import argparse
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
TEMPLATE_PATH = os.path.join(REPO, "templates", "scorecard", "scorecard-template.html")

sys.path.insert(0, HERE)
try:
    import kit_config  # type: ignore
    SURFACED_VERDICTS = list(getattr(kit_config, "SCORECARD_SURFACED_VERDICTS", []))
except Exception:
    SURFACED_VERDICTS = []

# Filenames that are not real company cards — skip outright, never render, never warn.
NOT_A_CARD_PATTERNS = [
    re.compile(r"dedup-card-build-bug-draft", re.I),
    re.compile(r"panel-calibration-card", re.I),
    re.compile(r"-call-card-", re.I),
]

# (slot key, human label, keyword regex matched against a section's header line)
REQUIRED_SLOTS = [
    ("blocked_hardfilter", "Blocked list / hard filters", re.compile(r"blocked list|hard filter", re.I)),
    ("news_layoffs", "Industry news & layoffs", re.compile(r"news.{0,15}layoffs|layoffs.{0,15}12", re.I)),
    ("culture", "Culture", re.compile(r"culture", re.I)),
    ("leadership_retention", "Leadership & retention", re.compile(r"leadership.{0,10}retention|retention", re.I)),
    ("remote_reality", "Remote reality", re.compile(r"remote reality|remote.{0,10}(pass|fail)", re.I)),
    ("ownership", "Ownership", re.compile(r"ownership", re.I)),
    ("boss", "Boss", re.compile(r"\bboss\b", re.I)),
    ("live_req", "Live PM req", re.compile(r"live.{0,5}(pm )?req", re.I)),
    ("current_direction", "Current Direction", re.compile(r"current direction", re.I)),
    ("fit_read", "Fit read", re.compile(r"fit read", re.I)),
    ("panel", "Panel", re.compile(r"\bpanel\b", re.I)),
    ("score_history", "Score history", re.compile(r"score history", re.I)),
    ("sources", "Sources", re.compile(r"^sources", re.I)),
]
OPTIONAL_SLOTS = [
    ("product_team", "Product team", re.compile(r"product team", re.I)),
    ("dedup", "Dedup check", re.compile(r"dedup", re.I)),
    ("gate_owed", "Gate still owed", re.compile(r"gate.{0,5}(still )?owed", re.I)),
    ("public_errors", "Public errors", re.compile(r"public errors", re.I)),
    ("ask_register", "Ask register", re.compile(r"ask.register", re.I)),
]

VERDICT_RE = re.compile(r"\b(BUILD|RADAR|PARK|DROP)\b")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)

# A "resolution card" (kit #88 dry run finding, 2026-09-09) is a distinct document genre
# that shares the *-card-*.md filename convention but not the 13-slot fit-card contract at
# all: no Panel, no Score history, no Sources section. Flagging every missing slot on one
# of these reads as 12 broken gates when it's really "not this kind of card" — so it gets
# its own one-line INFO instead of the WARN stack.
RESOLUTION_TITLE_RE = re.compile(r"resolution card", re.I)
_GENRE_CORE_KEYS = ("panel", "score_history", "sources")


class ParsedCard:
    def __init__(self, path):
        self.path = path
        self.basename = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            self.text = fh.read()
        self.sections = self._split_sections()
        self.verdict = self._find_verdict()
        self.company = self._find_company()

    def _split_sections(self):
        heads = list(SECTION_RE.finditer(self.text))
        out = []
        for i, m in enumerate(heads):
            start = m.end()
            end = heads[i + 1].start() if i + 1 < len(heads) else len(self.text)
            out.append((m.group(1), self.text[start:end].strip()))
        return out

    def _find_verdict(self):
        m = VERDICT_RE.search(self.text)
        return m.group(1).upper() if m else "UNKNOWN"

    def _find_company(self):
        first_line = self.text.splitlines()[0] if self.text.splitlines() else ""
        first_line = first_line.lstrip("#").strip()
        if "·" in first_line:
            return first_line.split("·")[0].strip()
        if first_line:
            return first_line
        slug = re.sub(r"-card-\d{4}-\d{2}-\d{2}\.md$", "", self.basename)
        return slug.replace("-", " ").title()

    def slot(self, keyword_re):
        for header, body in self.sections:
            if keyword_re.search(header):
                return header, body
        return None

    def required_present(self):
        return {key: self.slot(pat) is not None for key, _label, pat in REQUIRED_SLOTS}

    def missing_required(self):
        return [label for key, label, pat in REQUIRED_SLOTS if self.slot(pat) is None]

    def is_resolution_genre(self):
        first_line = self.text.splitlines()[0] if self.text.splitlines() else ""
        if not RESOLUTION_TITLE_RE.search(first_line):
            return False
        slot_map = {key: pat for key, _label, pat in REQUIRED_SLOTS}
        return all(self.slot(slot_map[k]) is None for k in _GENRE_CORE_KEYS)


def is_not_a_card(path):
    base = os.path.basename(path)
    for pat in NOT_A_CARD_PATTERNS:
        if pat.search(base):
            return f"filename matches non-card pattern {pat.pattern!r}"
    size = os.path.getsize(path)
    card = ParsedCard(path)
    hits = sum(1 for _k, _l, pat in REQUIRED_SLOTS if card.slot(pat))
    if hits == 0 and size < 5000:
        return f"0/{len(REQUIRED_SLOTS)} required slots matched and file is under 5KB ({size}B)"
    return None


def _esc(s):
    return html.escape(s, quote=True)


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "company"


def _extract_sources(body):
    rows = []
    for line in body.splitlines():
        m = re.search(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", line)
        if m:
            rows.append((m.group(1), m.group(2)))
    return rows


def _extract_panel_scores(body):
    """(seats, mean) from a card's Panel section body, or None.

    Two real shapes exist in the wild (scorecard-parity-fix-53-2026-09-09.md): a
    slash-triple ("82/75/78", tried first since it's cheap and common) and a bulleted
    per-seat list ("- CPO 82 ... - CTO 75 ... - CEO 78 ..."), which most real cards
    actually use and which the slash-triple regex never matched — a silent regression
    that dropped the whole Panel/seats section from the render with no warning.
    """
    mean_m = re.search(r"mean\D{0,10}(\d{2,3}(?:\.\d+)?)", body, re.I)
    m = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})\s*/\s*(\d{2,3})", body)
    if m:
        seats = [int(x) for x in m.groups()]
        mean = float(mean_m.group(1)) if mean_m else sum(seats) / len(seats)
        return seats, mean
    cpo_m = re.search(r"\bcpo\D{0,10}?(\d{2,3})\b", body, re.I)
    cto_m = re.search(r"\bcto\D{0,10}?(\d{2,3})\b", body, re.I)
    ceo_m = re.search(r"\bceo\D{0,10}?(\d{2,3})\b", body, re.I)
    if cpo_m and cto_m and ceo_m:
        seats = [int(cpo_m.group(1)), int(cto_m.group(1)), int(ceo_m.group(1))]
        mean = float(mean_m.group(1)) if mean_m else sum(seats) / len(seats)
        return seats, mean
    return None


# The true gate-shaped slots (scorecard-parity-fix-53-2026-09-09.md): every hand-made card's
# "Gates first" section holds exactly these — thesis-fit, score history, current direction,
# sources etc. are NOT gates and get their own sections below, not dumped into this grid.
GATE_SLOT_KEYS = (
    "blocked_hardfilter", "news_layoffs", "culture", "leadership_retention",
    "remote_reality", "ownership", "boss", "live_req", "product_team",
)
# Slots with no fixed structural home in a hand-made card (Lead-with/Own-plainly, Recommended
# path) are curated analysis a human/agent writes directly — nothing in the 13-slot contract
# supplies that content, so this renderer does NOT fabricate it. These slots' own real text
# gets an honest .note box under its own real label instead of inventing "Lead with" framing.
NOTE_SLOT_KEYS = ("current_direction", "ask_register", "dedup", "gate_owed", "public_errors")


def render_gate_card(label, header, body):
    snippet = " ".join(body.split())
    if len(snippet) > 400:
        snippet = snippet[:397].rstrip() + "..."
    return (
        '    <div class="gate">'
        '<span class="pill acc">FOUND</span>'
        f'<div class="name">{_esc(label)}</div>'
        f'<div class="why">{_esc(snippet)}</div>'
        "</div>"
    )


def _parse_markdown_table(body):
    """[[cell, ...], ...] (header row first) from the FIRST markdown pipe-table found in
    body, or None if no table is present. Tolerant of leading/trailing pipes."""
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if rows:
                break  # table ended
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue  # the |---|---| separator row
        rows.append(cells)
    return rows or None


def render_table_section(title, body, empty_note):
    rows = _parse_markdown_table(body)
    if not rows:
        # No parseable table — show the real prose rather than inventing a table around it.
        snippet = " ".join(body.split())
        return (f'<section>\n  <h2>{_esc(title)}</h2>\n'
                f'  <div class="note"><p>{_esc(snippet) if snippet else _esc(empty_note)}</p></div>\n'
                "</section>")
    header, *data = rows
    thead = "".join(f"<th>{_esc(c)}</th>" for c in header)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in data
    )
    return (
        f'<section>\n  <h2>{_esc(title)}</h2>\n'
        f'  <div class="histwrap"><table><tr>{thead}</tr>{tbody}</table></div>\n'
        "</section>"
    )


def render_sector_section():
    """No sector-sync data source exists yet (sector-line-sync-plan-53-2026-09-09.md is a
    plan, not shipped code) — render the template's own .pending state honestly rather than
    inventing n/median/Q1/Q3 numbers this renderer has no way to compute."""
    return ('<section>\n  <h2>Sector</h2>\n'
            '  <div class="sectorline pending">Sector comparison not yet computed for this '
            "install (scripts/sector_sync.py is planned, not shipped).</div>\n"
            "</section>")


def render_notes_section(card):
    boxes = []
    for key, label, pat in REQUIRED_SLOTS + OPTIONAL_SLOTS:
        if key not in NOTE_SLOT_KEYS:
            continue
        found = card.slot(pat)
        if not found:
            continue
        _header, body = found
        snippet = " ".join(body.split())
        if not snippet:
            continue
        boxes.append(f'  <div class="note"><h3>{_esc(label)}</h3><p>{_esc(snippet)}</p></div>')
    if not boxes:
        return ""
    return '<section class="cols">\n' + "\n".join(boxes) + "\n</section>"


SOURCE_TAG_RULES = (
    # (regex over URL or surrounding text, tag) — first match wins, "company" is the default.
    (re.compile(r"greenhouse\.io|ashbyhq\.com|lever\.co|/careers|/jobs", re.I), "req"),
    (re.compile(r"linkedin\.com", re.I), "boss"),
    (re.compile(r"prnewswire|businesswire|techcrunch|globenewswire|\bpress\b", re.I), "press"),
    (re.compile(r"crunchbase|sec\.gov", re.I), "market"),
)


def _source_tag(text, url):
    haystack = f"{text} {url}"
    for pat, tag in SOURCE_TAG_RULES:
        if pat.search(haystack):
            return tag
    return "company"


def render_panel_section(card):
    for key, _label, pat in [("panel", "Panel", REQUIRED_SLOTS[10][2])]:
        found = card.slot(pat)
    if not found:
        return ""
    _header, body = found
    parsed = _extract_panel_scores(body)
    if not parsed:
        return ""
    seats, mean = parsed
    fill = max(0.0, min(100.0, mean))
    return (
        '<section>\n'
        "  <h2>Panel</h2>\n"
        f'  <div class="track"><div class="fill" style="width:{fill}%"></div></div>\n'
        '  <div class="seats">\n'
        f'    <div class="seat"><b>CPO seat</b><span class="v">{seats[0]}</span></div>\n'
        f'    <div class="seat"><b>CTO seat</b><span class="v">{seats[1]}</span></div>\n'
        f'    <div class="seat"><b>CEO seat</b><span class="v">{seats[2]}</span></div>\n'
        "  </div>\n"
        f'  <p class="sub mono">Mean {mean:.1f}</p>\n'
        "</section>"
    )


def render_card_html(card, template_text):
    slot_map = {key: (label, pat) for key, label, pat in REQUIRED_SLOTS + OPTIONAL_SLOTS}

    gate_cards = []
    for key in GATE_SLOT_KEYS:
        label, pat = slot_map[key]
        found = card.slot(pat)
        if found:
            header, body = found
            gate_cards.append(render_gate_card(label, header, body))

    sources_header_body = card.slot(REQUIRED_SLOTS[-1][2])
    sources_rows = []
    if sources_header_body:
        for text, url in _extract_sources(sources_header_body[1]):
            tag = _source_tag(text, url)
            sources_rows.append(
                f'    <li><span class="tag">{_esc(tag)}</span>'
                f'<a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(text)}</a></li>'
            )
    if not sources_rows:
        sources_rows = ["    <li>No sourced links parsed from the Sources section.</li>"]

    history_found = card.slot(slot_map["score_history"][1])
    history_section = render_table_section(
        "Score history", history_found[1] if history_found else "", "No score history recorded."
    )
    fit_found = card.slot(slot_map["fit_read"][1])
    fit_section = render_table_section(
        "Fit read", fit_found[1] if fit_found else "", "No fit read recorded."
    )

    out = template_text
    out = out.replace("{{COMPANY}}", _esc(card.company))
    out = out.replace("{{HEADLINE_SUFFIX}}", "")
    out = out.replace("{{READ_DATE}}", _esc(_read_date(card.basename)))
    first_line = card.text.splitlines()[0].lstrip("#").strip() if card.text.splitlines() else ""
    out = out.replace("{{SUMMARY}}", _esc(first_line))
    out = out.replace("{{VERDICT_BIG}}", _esc(card.verdict))
    out = out.replace("{{VERDICT_LABEL}}", _esc(f"Rendered from {card.basename}"))
    out = out.replace("{{SECTION_PANEL}}", render_panel_section(card))
    out = out.replace("{{SECTION_SECTOR}}", render_sector_section())
    out = out.replace("{{SECTION_HISTORY}}", history_section)
    out = out.replace("{{SECTION_FIT}}", fit_section)
    out = out.replace("{{SECTION_NOTES}}", render_notes_section(card))
    out = out.replace("{{SECTION_GATES}}", "\n".join(gate_cards) if gate_cards else "    <div class=\"gate\"><div class=\"name\">No sections matched</div></div>")
    out = out.replace("{{SOURCES_ROWS}}", "\n".join(sources_rows))
    out = out.replace(
        "{{FOOTER}}",
        _esc(f"Card file: {card.basename}. Verdict: {card.verdict}. "
             f"Rendered by scripts/render_scorecard.py."),
    )
    return out


def _read_date(basename):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", basename)
    return m.group(1) if m else ""


def render_one(card_path, out_dir, template_text, quiet=False):
    reason = is_not_a_card(card_path)
    if reason:
        if not quiet:
            print(f"SKIP {os.path.basename(card_path)}: {reason}")
        return None

    card = ParsedCard(card_path)

    if card.verdict == "UNKNOWN":
        print(f"INFO {os.path.basename(card_path)}: no verdict token (BUILD/RADAR/PARK/DROP) found")

    if card.is_resolution_genre():
        print(f"INFO {os.path.basename(card_path)}: resolution card, not a fit card")
    else:
        missing = card.missing_required()
        if missing and card.verdict in ("BUILD", "RADAR"):
            print(
                f"WARN {os.path.basename(card_path)} [{card.verdict}] missing required slot(s): "
                + ", ".join(missing)
            )
        elif missing and not quiet:
            print(
                f"INFO {os.path.basename(card_path)} [{card.verdict}] stopped early, "
                f"missing {len(missing)}/{len(REQUIRED_SLOTS)} required slot(s) (expected for DROP/PARK)"
            )

    html_out = render_card_html(card, template_text)
    os.makedirs(out_dir, exist_ok=True)
    date = _read_date(card.basename) or "undated"
    out_path = os.path.join(out_dir, f"{_slug(card.company)}-{date}.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_out)
    if not quiet:
        print(f"OK   {os.path.basename(card_path)} -> {out_path} [{card.verdict}]")
    return out_path


def build_index(out_dir):
    entries = []
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".html") or name.startswith("TEMPLATE-"):
            continue
        path = os.path.join(out_dir, name)
        text = open(path, encoding="utf-8").read()
        m_company = re.search(r"<h1>([^<]*)</h1>", text)
        m_verdict = re.search(r'<div class="big">([^<]*)</div>', text)
        company = html.unescape(m_company.group(1)) if m_company else name
        verdict = html.unescape(m_verdict.group(1)) if m_verdict else "UNKNOWN"
        entries.append((company, verdict, name))

    lines = ["# Scorecard index (generated by scripts/render_scorecard.py --reindex)", ""]
    lines.append("| Company | Verdict | Page file |")
    lines.append("|---|---|---|")
    for company, verdict, name in entries:
        if SURFACED_VERDICTS and verdict not in SURFACED_VERDICTS:
            lines.append(f"| {company} — **not surfaced** | on file, not linked: `{name}` | {name} |")
        else:
            lines.append(f"| {company} | {verdict} | {name} |")
    index_text = "\n".join(lines) + "\n"

    index_path = os.path.join(out_dir, "INDEX.md")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(index_text)
    return index_path, len(entries)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("card", nargs="?", help="path to a single *-card-*.md file")
    ap.add_argument("--backfill", metavar="DIR", help="render every *-card-*.md in DIR that has no HTML yet")
    ap.add_argument("--reindex", metavar="DIR", help="rebuild INDEX.md from the HTML already in DIR")
    ap.add_argument("--out", default=None, help="output directory for rendered HTML")
    args = ap.parse_args()

    if not os.path.exists(TEMPLATE_PATH):
        print(f"template not found: {TEMPLATE_PATH}", file=sys.stderr)
        return 2
    template_text = open(TEMPLATE_PATH, encoding="utf-8").read()

    if args.reindex:
        index_path, n = build_index(args.reindex)
        print(f"reindexed {n} card(s) -> {index_path}")
        return 0

    if args.backfill:
        out_dir = args.out or os.path.join(args.backfill, "scorecards")
        existing = set()
        if os.path.isdir(out_dir):
            for name in os.listdir(out_dir):
                existing.add(re.sub(r"-\d{4}-\d{2}-\d{2}\.html$", "", name))
        rendered = 0
        for name in sorted(os.listdir(args.backfill)):
            if not re.search(r"-card-.*\d{4}-\d{2}-\d{2}\.md$", name):
                continue
            card_path = os.path.join(args.backfill, name)
            slug_guess = _slug(ParsedCard(card_path).company) if not is_not_a_card(card_path) else None
            if slug_guess and slug_guess in existing:
                continue
            if render_one(card_path, out_dir, template_text):
                rendered += 1
        print(f"backfill rendered {rendered} new card(s) into {out_dir}")
        return 0

    if not args.card:
        ap.print_usage()
        return 2

    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.card)), "scorecards")
    result = render_one(args.card, out_dir, template_text)
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
