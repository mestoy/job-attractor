#!/usr/bin/env python3
"""render_scorecard.py — kit #88: turn a company card markdown into an HTML scorecard.

WHY THIS EXISTS. Kit issue #88 found that a partner install produces no
scorecard HTML at all: the card markdown → HTML step only ever existed as a Claude
session hand-writing HTML into the Artifact tool from a card, never as checked-in code
(see documents/state/partner-card-step-evidence-*.md and c1's finding). This script is
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
import glob
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
TEMPLATE_PATH = os.path.join(REPO, "templates", "scorecard", "scorecard-template.html")


def _resolve_kit_config():
    """(module, path) for kit_config — REPO's own copy if it exists, else the shipped
    example next to this script. Returns (None, None) if neither imports cleanly.

    BUG-248: `sys.path.insert(0, HERE)` + a bare `import kit_config` always resolved
    against THIS SCRIPT's own directory, never against REPO — every other script in this
    codebase is always invoked in place, next to the kit_config.py that actually applies,
    so that was never a problem anywhere else. This script is the one asked to run
    cross-directory (rendering the private repo's docs, which carries no copy of this
    script itself, only means invoking partner-starter's or the kit's copy against it),
    and doing so silently loaded the WRONG kit_config with no error at all — confirmed
    live: `SCORECARD_SURFACED_VERDICTS` from BUG-245 never took effect on a cross-directory
    run. Loaded via `importlib.util.spec_from_file_location`, the same pattern
    `screen_sweep._import_sibling` uses elsewhere in this codebase, rather than
    `sys.path` + bare `import`, so this never depends on import order or a `sys.modules`
    entry an earlier, unrelated import may have already cached.
    """
    return _load_kit_config((os.path.join(REPO, "scripts"), HERE))


def _load_kit_config(candidate_dirs):
    """First importable kit_config.py among `candidate_dirs`, as (module, path)."""
    import importlib.util
    for candidate_dir in candidate_dirs:
        path = os.path.join(candidate_dir, "kit_config.py")
        if not os.path.exists(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location("kit_config", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod, path
        except Exception:
            continue
    return None, None


# BUG-248, reopened 2026-09-11: resolving once at import time was the other half of the bug.
# Module scope runs before any card path is known, so the config could only ever describe the
# SCRIPT's repo. It must follow the CARD: walk up from the card (or the directory being indexed)
# to the nearest repo root carrying scripts/kit_config.py. CLAUDE_PROJECT_DIR stays the
# deliberate escape hatch and still wins when set — an unset, undocumented env var that falls
# back silently to a wrong-but-plausible config is worse than no mechanism at all, because
# nothing errors and the operator has no reason to look.
_CONFIG_CACHE = {}


def _repo_root_for(path):
    """Nearest ancestor of `path` that carries scripts/kit_config.py, else None."""
    cur = os.path.abspath(path)
    if os.path.isfile(cur):
        cur = os.path.dirname(cur)
    while True:
        if os.path.exists(os.path.join(cur, "scripts", "kit_config.py")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


# kit#98 (a partner): WORKFLOW-RULES tells a person cards live in documents/state/scorecards/,
# and this script defaulted to a `scorecards` folder beside whatever it was given instead. He
# grepped scripts/ for that documented path, found no writer, and filed. He was right to: the
# writer existed and could not be found the way the rules said to look. The default now IS the
# documented path. `--out` still wins and still means what it meant.
DOCUMENTED_CARDS_DIR = os.path.join("documents", "state", "scorecards")


def announce_default(out_dir, used_out_flag):
    """Say where cards land when the DEFAULT put them there, so a moved default is never silent.

    kit#98: this default changed. An install whose cards have been landing beside the card file
    will start writing to documents/state/scorecards/, and a person must be able to tell why the
    next run went somewhere new rather than discover it later.
    """
    if used_out_flag:
        return
    print("cards: " + out_dir)
    print("       (the default moved to the documented path, kit#98; pass --out to choose another)")


def default_out_dir(hint_path):
    """documents/state/scorecards/ under the repo that owns `hint_path`, else beside it.

    Falls back to the old behavior only when no repo root can be found, so a card rendered
    outside any install still lands somewhere sensible rather than failing.
    """
    root = _repo_root_for(hint_path) or (os.environ.get("CLAUDE_PROJECT_DIR") or "")
    if root and os.path.isdir(root):
        return os.path.join(root, DOCUMENTED_CARDS_DIR)
    base = hint_path if os.path.isdir(hint_path) else os.path.dirname(os.path.abspath(hint_path))
    return os.path.join(base, "scorecards")


def kit_config_for(path=None):
    """(module, path) for the kit_config that governs `path`. Env override, then the card's own
    repo, then this script's repo, then the shipped example beside this script."""
    key = os.path.abspath(path) if path else ""
    if key in _CONFIG_CACHE:
        return _CONFIG_CACHE[key]
    candidates = []
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        candidates.append(os.path.join(os.environ["CLAUDE_PROJECT_DIR"], "scripts"))
    if path:
        root = _repo_root_for(path)
        if root:
            candidates.append(os.path.join(root, "scripts"))
    candidates += [os.path.join(REPO, "scripts"), HERE]
    result = _load_kit_config(candidates)
    _CONFIG_CACHE[key] = result
    return result


def surfaced_verdicts(path=None):
    """The INDEX filter for the repo that owns `path`. Empty list means surface everything."""
    mod, _p = kit_config_for(path)
    return list(getattr(mod, "SCORECARD_SURFACED_VERDICTS", []))


_KIT_CONFIG, _KIT_CONFIG_PATH = kit_config_for()
print(f"config: {_KIT_CONFIG_PATH or '(none found, empty defaults)'}")

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
        # kit #144: read only the first line/header, same as depth_report.py's card_stage().
        # A card without a verdict token there is undecided, even if a verdict word turns up
        # incidentally in the body prose.
        first_line = self.text.splitlines()[0] if self.text.strip() else ""
        m = VERDICT_RE.search(first_line)
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


# BUG-249: gate "why" text, note-box snippets, and table snippet/empty-note fields are the
# only `_esc()` callers that see free-form card-author prose (verified per call site: every
# other caller — company name, dates, verdict word, table cells, sources list, footer — is a
# short structured token that never legitimately carries markdown). A card author's
# `**bold**`/`*italic*`/`[text](url)` was passing through plain `_esc()` unconverted, so a
# real card's gate cell showed literal asterisks instead of bold text (confirmed live on the
# "Boss" and "Live PM req" gates of a real scorecard). `_esc_md()` escapes first — exactly
# like `_esc()`, so real HTML in the source text is neutralized the same way — then layers
# three markdown constructs on top of the ESCAPED string, safe because `**`, `[`, `]`, `(`,
# `)` all survive `html.escape` untouched, so the regexes still see the same delimiters.
# Bold is applied before italic (standard markdown order) so `**x**`'s outer `*`s are never
# mistaken for an italic span first. Deliberately only these three constructs — no images, no
# code spans, no nested emphasis — matching every markdown shape actually observed in this
# session's own card-reading passes; not a general markdown parser.
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)|_([^_]+)_")
# BUG-264: a backtick code span is literal text. Emphasis must not run into or across one.
_MD_CODE = re.compile(r"`([^`]+)`")


def _emphasis(s):
    """Bold before italic (standard markdown order), over plain text only."""
    s = _MD_BOLD.sub(r"<b>\1</b>", s)
    return _MD_ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", s)


def _esc_md(s):
    """Like `_esc()`, plus a minimal bold/italic/link conversion for card-author prose.

    BUG-258: emphasis must never run over the anchor markup this function itself generates.
    It used to, and `_MD_ITALIC`'s `_(...)_` arm then matched from one anchor's `target="_blank"`
    into the next one's, so a URL carrying an underscore had `<i>` injected into its own href --
    `.../Series_A_round` rendered as `.../Series<i>A</i>round`, a silently broken link (live on
    fake-compliance-2026-09-10). So each finished anchor is parked behind a NUL placeholder that
    carries no markdown delimiter, emphasis runs over what is left, and the anchors go back in
    last. Link TEXT still gets emphasis, applied before parking, so `[**x**](url)` is unchanged.
    """
    out = _esc(s)

    # BUG-264, the sibling of BUG-258. A code span is literal by definition, but `_MD_ITALIC`'s
    # `_(...)_` arm matched from the underscore in ONE span to the underscore in the NEXT, so
    # `check_dup.py ... check_dup.py` rendered as `check<i>dup.py ... check</i>dup.py` (live on
    # fakko-2026-09-10.html). Anchors were already parked for exactly this reason; spans were not.
    # Parked FIRST, so a span is protected from the link pass as well, and restored LAST.
    # The span is restored verbatim, backticks included: rendering it as <code> would change how
    # 92 published cards look, which is the owner's call and not a bug fix.
    spans = []

    def _park_code(m):
        spans.append(m.group(0))
        return f"\x01{len(spans) - 1}\x01"

    out = _MD_CODE.sub(_park_code, out)
    held = []

    def _park(m):
        held.append(
            f'<a href="{m.group(2)}" target="_blank" rel="noopener">{_emphasis(m.group(1))}</a>'
        )
        return f"\x00{len(held) - 1}\x00"

    out = _MD_LINK.sub(_park, out)
    out = _emphasis(out)
    for i, anchor in enumerate(held):
        out = out.replace(f"\x00{i}\x00", anchor)
    for i, span in enumerate(spans):
        out = out.replace(f"\x01{i}\x01", span)
    return out


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
    # BUG-250 backfill finding: a mean stated as an arithmetic expression — "Mean: (35+50+
    # 40)/3 = **41.7 -> PARK/PARTIAL**" (Malinaw Ventures, confirmed live) — makes the plain
    # "mean<10 chars>NUMBER" pattern below grab the first addend ("35") instead of the actual
    # result, since \D{0,10} cannot skip over the digits inside the expression. Tried first,
    # scoped to the line naming "mean" specifically (never the whole body, so an unrelated
    # "=" elsewhere in the card can't be mistaken for the mean): the number right after an
    # "=" sign on that line, the shape every "computed to" mean in this corpus actually uses.
    mean_line_m = re.search(r"^.*\bmean\b.*$", body, re.I | re.M)
    mean_eq_m = re.search(r"=\s*\*{0,2}(\d{2,3}(?:\.\d+)?)", mean_line_m.group(0)) if mean_line_m else None
    mean_m = mean_eq_m or re.search(r"mean\D{0,10}(\d{2,3}(?:\.\d+)?)", body, re.I)
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
    # BUG-250 backfill finding: a real card can name a seat and its score with MORE than 10
    # non-digit characters between them on the same bullet line — e.g. "CPO seat (no CPO
    # exists — reading as \"product-equivalent\" hiring lens)**: 35" — which both patterns
    # above miss (Malinaw Ventures, confirmed live). `_SEAT_PROSE_RULES` (below) already
    # anchors to the bullet LINE itself with no gap limit, so it's reused here as a third,
    # more permissive tier rather than widening `\D{0,10}` and risking it matching the WRONG
    # number on a longer, busier line.
    cpo2 = _SEAT_PROSE_RULES[0][1].search(body)
    cto2 = _SEAT_PROSE_RULES[1][1].search(body)
    ceo2 = _SEAT_PROSE_RULES[2][1].search(body)
    if cpo2 and cto2 and ceo2:
        seats = [int(cpo2.group(1)), int(cto2.group(1)), int(ceo2.group(1))]
        mean = float(mean_m.group(1)) if mean_m else sum(seats) / len(seats)
        return seats, mean
    return None


# The true gate-shaped slots (scorecard-parity-fix-53-2026-09-09.md): every hand-made card's
# "Gates first" section holds exactly these — thesis-fit, score history, current direction,
# sources etc. are NOT gates and get their own sections below, not dumped into this grid.
# BUG-250 (the owner's ruling, "Render plus owed boxes"): "dedup" moves from a note box into a
# gate tile — it's checked first on every card, the same shape as the other gates, and the
# approved template counts it among "Gates first."
GATE_SLOT_KEYS = (
    "dedup", "blocked_hardfilter", "news_layoffs", "culture", "leadership_retention",
    "remote_reality", "ownership", "boss", "live_req", "product_team",
)
# Slots with no fixed structural home in a hand-made card (Lead-with/Own-plainly, Recommended
# path) are curated analysis a human/agent writes directly — nothing in the 13-slot contract
# supplies that content, so this renderer does NOT fabricate it. These slots' own real text
# gets an honest .note box under its own real label instead of inventing "Lead with" framing.
NOTE_SLOT_KEYS = ("current_direction", "ask_register", "gate_owed", "public_errors")


# BUG-250 (the owner's ruling): a real pill reading per gate, not the constant "FOUND" every
# gate used to carry regardless of what it actually found. Checked in this order — most
# cautious reading wins when a gate body mentions more than one — so a gate that's mostly
# clean but flags a caveat still reads as the caveat, not a false PASS.
_GATE_PILL_RULES = (
    (re.compile(r"\bunproven\b|\bunverified\b|too thin\b", re.I), ("warn", "UNPROVEN")),
    (re.compile(r"\bowed\b|not yet (checked|verified|confirmed)|still owed", re.I), ("warn", "OWED")),
    (re.compile(r"\bradar\b", re.I), ("acc", "RADAR")),
    (re.compile(r"\bclean\b|\bconfirmed\b|\bcorroborated\b|already-seen", re.I), ("good", "PASS")),
)


def _gate_pill(body):
    for pat, result in _GATE_PILL_RULES:
        if pat.search(body):
            return result
    return ("acc", "FOUND")


def render_gate_card(label, header, body):
    snippet = " ".join(body.split())
    if len(snippet) > 400:
        # BUG-257: cut on a link boundary, never through one. The 397-char cut used to land
        # mid-URL, which strips the closing paren `_MD_LINK` needs, so the raw `[text](http...`
        # rendered literally -- 13 of 13 leaking gate bodies on 2026-09-10 ended in this ellipsis.
        # Dropping the whole link is the honest option: the alternative, converting before
        # truncating, would cut through generated <a> markup instead and leave a broken tag.
        cut = 397
        for m in _MD_LINK.finditer(snippet):
            if m.start() < cut < m.end():
                cut = m.start()
                break
        snippet = snippet[:cut].rstrip() + "..."
    css, text = _gate_pill(body)
    return (
        '    <div class="gate">'
        f'<span class="pill {css}">{text}</span>'
        f'<div class="name">{_esc(label)}</div>'
        f'<div class="why">{_esc_md(snippet)}</div>'
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


def _history_table_inner(body):
    """The `.histwrap` table markup for Score history, or an honest prose fallback — no
    `<section>`/`<h2>` wrapper, since BUG-250 folds this inside "Three seats" now."""
    rows = _parse_markdown_table(body)
    if not rows:
        snippet = " ".join(body.split())
        if not snippet:
            return ""
        return f'  <div class="note"><p>{_esc_md(snippet)}</p></div>\n'
    header, *data = rows
    thead = "".join(f"<th>{_esc(c)}</th>" for c in header)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in data
    )
    return f'  <div class="histwrap"><table><tr>{thead}</tr>{tbody}</table></div>\n'


def _sector_line_html():
    """No sector-sync data source exists yet (sector-line-sync-plan-53-2026-09-09.md is a
    plan, not shipped code) — render the template's own .pending state honestly rather than
    inventing n/median/Q1/Q3 numbers this renderer has no way to compute."""
    return ('  <div class="sectorline pending">Sector comparison not yet computed for this '
            "install (scripts/sector_sync.py is planned, not shipped).</div>\n")


def _existing_notes_boxes(card):
    """`.note` boxes for whatever of `NOTE_SLOT_KEYS` a card actually carries, under their own
    real label — never fabricating the template's four new label names, per BUG-250."""
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
        boxes.append(f'  <div class="note"><h3>{_esc(label)}</h3><p>{_esc_md(snippet)}</p></div>')
    return "\n".join(boxes)


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


_SEAT_PROSE_RULES = (
    ("cpo", re.compile(r"^[-*]\s.*\bCPO\b.*?(\d{2,3})\b(.*)$", re.I | re.M)),
    ("cto", re.compile(r"^[-*]\s.*\bCTO\b.*?(\d{2,3})\b(.*)$", re.I | re.M)),
    ("ceo", re.compile(r"^[-*]\s.*\bCEO\b.*?(\d{2,3})\b(.*)$", re.I | re.M)),
)


def _extract_seat_prose(body):
    """{"cpo"/"cto"/"ceo": trailing reasoning text on that seat's own bullet line}, per
    BUG-250 — a card's Panel slot already carries this (`- **CPO 82** — no product leader...`);
    `_extract_panel_scores` only ever pulled the number, discarding the sentence. Empty string
    per seat when no bullet-shaped line names it (e.g. the compact slash-triple Panel shape),
    never a crash."""
    prose = {}
    for seat_key, pat in _SEAT_PROSE_RULES:
        m = pat.search(body)
        prose[seat_key] = " ".join(m.group(2).strip(" -—–:*").split()) if m else ""
    return prose


def render_seats_section(card):
    """"Three seats on the thesis fit" (BUG-250 rename from "Panel") — the seat scores AND
    their own reasoning sentences, the score-history table, and the sector line, all folded
    into one section per the approved template shape, instead of four separate `<h2>`s."""
    slot_map = {key: (label, pat) for key, label, pat in REQUIRED_SLOTS + OPTIONAL_SLOTS}
    found = card.slot(slot_map["panel"][1])
    if not found:
        return ""
    _header, body = found
    parsed = _extract_panel_scores(body)
    if not parsed:
        return ""
    seats, mean = parsed
    prose = _extract_seat_prose(body)
    fill = max(0.0, min(100.0, mean))
    history_found = card.slot(slot_map["score_history"][1])
    history_inner = _history_table_inner(history_found[1] if history_found else "")
    return (
        '<section>\n'
        "  <h2>Three seats on the thesis fit</h2>\n"
        f'  <div class="track"><div class="fill" style="width:{fill}%"></div></div>\n'
        '  <div class="seats">\n'
        f'    <div class="seat"><b>CPO seat</b><span class="v">{seats[0]}</span>{_esc_md(prose["cpo"])}</div>\n'
        f'    <div class="seat"><b>CTO seat</b><span class="v">{seats[1]}</span>{_esc_md(prose["cto"])}</div>\n'
        f'    <div class="seat"><b>CEO seat</b><span class="v">{seats[2]}</span>{_esc_md(prose["ceo"])}</div>\n'
        "  </div>\n"
        f'  <p class="sub mono">Mean {mean:.1f}</p>\n'
        f'{history_inner}'
        f'{_sector_line_html()}'
        "</section>"
    )


def render_thesis_fit_section(card):
    """"Thesis fit against the record" (BUG-250) — the approved template's graded
    What-the-company-is / Read / Evidence TABLE has no corresponding slot anywhere in the
    13-slot card contract; a card's `## Fit read` is one free paragraph, not multiple named,
    graded rows. Per the owner's ruling ("Render plus owed boxes"): render the card's real Fit
    read paragraph when it has one, and mark the structured table itself as owed rather than
    fabricating rows or grades a human never wrote."""
    slot_map = {key: (label, pat) for key, label, pat in REQUIRED_SLOTS + OPTIONAL_SLOTS}
    found = card.slot(slot_map["fit_read"][1])
    body_html = ""
    if found:
        snippet = " ".join(found[1].split())
        if snippet:
            body_html = f'  <div class="note"><p>{_esc_md(snippet)}</p></div>\n'
    owed_text = (
        "A graded per-dimension table (What the company is / Read / Evidence) is not yet "
        "part of this card's contract"
        + (" — shown above is the card's plain Fit read." if body_html else
           ", and no Fit read is recorded on this card either.")
    )
    owed = f'  <div class="note"><span class="pill warn">OWED</span> <p>{_esc(owed_text)}</p></div>\n'
    return f'<section>\n  <h2>Thesis fit against the record</h2>\n{body_html}{owed}</section>'


def render_four_part_notes_section(card):
    """"Lead with / Own plainly" and "What would change the read / Owed before any note"
    (BUG-250) — four distinct labeled notes the 13-slot contract has no matching slots for.
    Per the owner's ruling: mark all four as owed, and still carry forward whatever a card's
    existing NOTE_SLOT_KEYS content says under its own real label, so nothing already written
    is silently dropped."""
    owed = (
        '  <div class="note"><span class="pill warn">OWED</span>\n'
        "    <h3>Lead with</h3><p>Not yet part of this card's contract.</p>\n"
        "    <h3>Own plainly</h3><p>Not yet part of this card's contract.</p>\n"
        "  </div>\n"
        '  <div class="note"><span class="pill warn">OWED</span>\n'
        "    <h3>What would change the read</h3><p>Not yet part of this card's contract.</p>\n"
        "    <h3>Owed before any note</h3><p>Not yet part of this card's contract.</p>\n"
        "  </div>\n"
    )
    existing = _existing_notes_boxes(card)
    body = owed + (existing + "\n" if existing else "")
    return f'<section class="cols">\n{body}</section>'


def render_recommended_path_section():
    """"Recommended path" (BUG-250) — an ordered next-step action list with no corresponding
    slot anywhere in the 13-slot contract on any card read this session. Always an owed box;
    there is no existing content this renderer could honestly show instead."""
    return (
        '<section class="path">\n  <h2>Recommended path</h2>\n'
        '  <p class="sub"><span class="pill warn">OWED</span> A structured next-step sequence '
        "is not yet part of this card's contract.</p>\n"
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

    out = template_text
    out = out.replace("{{COMPANY}}", _esc(card.company))
    out = out.replace("{{HEADLINE_SUFFIX}}", "")
    out = out.replace("{{READ_DATE}}", _esc(_read_date(card.basename)))
    first_line = card.text.splitlines()[0].lstrip("#").strip() if card.text.splitlines() else ""
    out = out.replace("{{SUMMARY}}", _esc(first_line))
    out = out.replace("{{VERDICT_BIG}}", _esc(card.verdict))
    out = out.replace("{{VERDICT_LABEL}}", _esc(f"Rendered from {card.basename}"))
    out = out.replace("{{SECTION_SEATS}}", render_seats_section(card))
    out = out.replace("{{SECTION_THESIS_FIT}}", render_thesis_fit_section(card))
    out = out.replace("{{SECTION_FOUR_NOTES}}", render_four_part_notes_section(card))
    out = out.replace("{{SECTION_RECOMMENDED_PATH}}", render_recommended_path_section())
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


# BUG-259: a card's verdict is hand-maintained AFTER the send — Batingaw Cyber's header says SENT
# while its HTML says BUILD, with the send recorded by hand on the .lbl line. The generator
# does not recognize a SENT header, so re-rendering one silently REVERTS that hand edit:
# fakespring-2026-09-06 went BUILD -> RADAR that way on 2026-09-10. Refuse and explain, rather
# than refuse silently, and do it in render_one so --backfill (where a bulk run would do this
# to many cards at once) is covered by the same guard as a single card.
_SENT_HEADER = re.compile(r"^#[^\n]*\bSTATUS:\s*(?:\u2705\s*)?SENT\b", re.I)


def is_sent_card(card_path):
    """The card's own header says it has been sent, so its verdict is no longer ours to write."""
    try:
        with open(card_path, encoding="utf-8") as fh:
            head = fh.readline()
    except OSError:
        return False
    return bool(_SENT_HEADER.search(head))


def render_one(card_path, out_dir, template_text, quiet=False):
    reason = is_not_a_card(card_path)
    if reason:
        if not quiet:
            print(f"SKIP {os.path.basename(card_path)}: {reason}")
        return None

    if is_sent_card(card_path):
        print(
            f"REFUSED {os.path.basename(card_path)}: this card reads STATUS: SENT, and a sent "
            "card's verdict is maintained by hand afterwards. Re-rendering would overwrite that "
            "hand edit with a generated verdict. Edit the HTML directly if it needs a change."
        )
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


_INDEX_ROW_RE = re.compile(r"\|[^\n|]*\|\s*([A-Za-z0-9_.\-]+\.html)\s*\|\s*$")


def _card_verdict_for_html(html_name, cards_dir):
    """The ruled verdict (BUILD/RADAR/PARK/DROP) for a rendered HTML file, read from its
    source card's own STATUS tag (BUG-245) — never the HTML's numeric score div, which is
    what a hand-authored pre-kit#88 scorecard puts in `<div class="big">` instead of a
    verdict word."""
    if cards_dir and os.path.isdir(cards_dir):
        slug = re.sub(r"-\d{4}-\d{2}-\d{2}\.html$", "", html_name)
        matches = sorted(glob.glob(os.path.join(cards_dir, f"{slug}-card-*.md")))
        if matches:
            card = ParsedCard(matches[-1])
            if card.verdict != "UNKNOWN":
                return card.verdict
    return None


def _html_lbl_verdict(text):
    m = re.search(r'<div class="lbl">.*?<b>(BUILD|RADAR|PARK|DROP)</b>', text, re.S)
    return m.group(1) if m else None


def build_index(out_dir, cards_dir=None):
    """Rebuild INDEX.md. Verdict source, in order: the matching card's own STATUS tag
    (ParsedCard.verdict), then a bolded BUILD/RADAR/PARK/DROP word inside the HTML's
    `<div class="lbl">` — never the `<div class="big">` div, which holds a numeric panel
    score on every hand-authored pre-kit#88 scorecard (BUG-245: this previously read
    Serbisyo Dash's ruled DROP as its panel score, "64").

    Existing INDEX.md rows (their artifact URL, ruled-status annotation, everything) are
    left byte-for-byte untouched — a reindex only APPENDS a row for an HTML file not
    already referenced by some row's page-file column. It never rewrites or corrects an
    existing row, so a stale row (like Serbisyo Dash's, pre-dating this fix) stays stale until
    someone edits it by hand.
    """
    if cards_dir is None:
        cards_dir = os.path.dirname(out_dir.rstrip(os.sep)) or "."

    surfaced = surfaced_verdicts(cards_dir)

    index_path = os.path.join(out_dir, "INDEX.md")
    existing_lines = []
    existing_page_files = set()
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as fh:
            existing_lines = fh.read().splitlines()
        for line in existing_lines:
            m = _INDEX_ROW_RE.search(line)
            if m:
                existing_page_files.add(m.group(1))

    new_rows = []
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".html") or name.startswith("TEMPLATE-"):
            continue
        if name in existing_page_files:
            continue
        path = os.path.join(out_dir, name)
        text = open(path, encoding="utf-8").read()
        m_company = re.search(r"<h1>([^<]*)</h1>", text)
        company = html.unescape(m_company.group(1)) if m_company else name

        verdict = _card_verdict_for_html(name, cards_dir) or _html_lbl_verdict(text) or "UNKNOWN"

        if surfaced and verdict not in surfaced:
            new_rows.append(f"| {company} — **{verdict}, not surfaced** | on file, not linked: `{name}` | {name} |")
        else:
            new_rows.append(f"| {company} | {verdict} | {name} |")

    if existing_lines:
        lines = list(existing_lines)
        while lines and lines[-1].strip() == "":
            lines.pop()
        lines.extend(new_rows)
    else:
        lines = [
            "# Scorecard index (generated by scripts/render_scorecard.py --reindex)",
            "",
            "| Company | Verdict | Page file |",
            "|---|---|---|",
        ]
        lines.extend(new_rows)

    index_text = "\n".join(lines) + "\n"
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(index_text)
    return index_path, len(existing_page_files) + len(new_rows)


_LEADING_ID_RE = re.compile(r"^\s*#(\d+)([A-Z]?)\b")


def validate_index(out_dir):
    """Read-only. Returns (problems, html_files_checked) for the INDEX.md/HTML contract in
    `out_dir` (kit#98). Never writes anything — `--reindex` above is the writer; this only
    reports.

    Covers two of the owner's three named checks (his 09-20 comment on #98), the two fully
    specified without guessing at a file format that is not documented anywhere in this kit:

    1. Coverage, BOTH directions. `--reindex` only ADDS a row for a page with none; it
       structurally cannot flag a row with no page, or two rows for one page (its own docstring
       says so: "a reindex only APPENDS... it never rewrites or corrects an existing row"). This
       checks both directions.
    2. Numbering collision. A leading `#<digits><optional single uppercase letter>` token at the
       start of a row's Company cell (his own description of the broken shape: "three parallel
       numbering namespaces... plain, B and C") is checked for an EXACT duplicate id across rows.
       Deliberately narrow: `#12` and `#12B` are left as different identifiers, not unified,
       since deciding whether they SHOULD be the same namespace is the open design question the
       issue itself raises, not a fact this check can assert on its own.

    NOT covered: a sprint-manifest cross-check (his third ask). No sprint-manifest file format is
    documented anywhere in this kit or referenced by any script — guessing at its shape here
    would be the same failure mode this validator exists to catch, a check that looks
    authoritative without actually knowing what it is checking.

    HIS HARD REQUIREMENT, stated as one: "it must prove it had something to look at, so an empty
    folder cannot pass as a clean one." A missing/empty directory returns a problem saying so with
    `checked == 0`; a populated, genuinely clean directory returns no problems with `checked > 0`
    — the two must never look the same.
    """
    if not os.path.isdir(out_dir):
        return ([f"{out_dir}: not a directory, nothing to check"], 0)
    html_files = sorted(n for n in os.listdir(out_dir)
                        if n.endswith(".html") and not n.startswith("TEMPLATE-"))

    index_path = os.path.join(out_dir, "INDEX.md")
    page_rows = {}   # page-file -> row count
    ids_seen = {}    # leading id token -> {page-files it appears on}
    if os.path.isfile(index_path):
        with open(index_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                m = _INDEX_ROW_RE.search(line)
                if not m:
                    continue
                page = m.group(1)
                page_rows[page] = page_rows.get(page, 0) + 1
                cells = [c.strip() for c in line.strip().split("|")]
                first_cell = cells[1] if len(cells) > 1 else ""
                id_m = _LEADING_ID_RE.match(first_cell)
                if id_m:
                    ids_seen.setdefault(id_m.group(0).strip(), set()).add(page)

    # HIS HARD REQUIREMENT. Checked BOTH ways, on purpose: no real HTML pages AND no real
    # INDEX.md rows means there is genuinely nothing here, not "a clean install". An INDEX.md
    # that names a page with no file on disk, or HTML pages sitting next to a missing/empty
    # INDEX.md, both have something to report below and must not take this exit.
    if not html_files and not page_rows:
        return ([f"{out_dir}: no HTML scorecards and no INDEX.md rows found, nothing to "
                 "check"], 0)

    problems = []
    for page in html_files:
        if page not in page_rows:
            problems.append(f"{page}: no INDEX.md row references it")
    for page, n in page_rows.items():
        if page not in html_files:
            problems.append(f"{page}: has an INDEX.md row but no page on disk")
        elif n > 1:
            problems.append(f"{page}: {n} rows reference this one page")
    for ident, pages in ids_seen.items():
        if len(pages) > 1:
            problems.append(f"{ident}: used by more than one row ({', '.join(sorted(pages))})")

    return (problems, len(html_files))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("card", nargs="?", help="path to a single *-card-*.md file")
    ap.add_argument("--backfill", metavar="DIR", help="render every *-card-*.md in DIR that has no HTML yet")
    ap.add_argument("--reindex", metavar="DIR", help="rebuild INDEX.md from the HTML already in DIR")
    ap.add_argument("--validate", metavar="DIR",
                    help="read-only: report INDEX.md/HTML coverage gaps and numbering collisions "
                         "in DIR, change nothing (kit#98)")
    ap.add_argument("--out", default=None,
                    help="output directory for rendered HTML "
                         "(default: documents/state/scorecards/ in this install)")
    args = ap.parse_args()

    if args.validate:
        problems, checked = validate_index(args.validate)
        if checked == 0:
            print(f"⚠️  {problems[0]}", file=sys.stderr)
            return 2
        if not problems:
            print(f"✅ {checked} scorecard(s) checked, INDEX.md consistent")
            return 0
        print(f"🔴 {len(problems)} problem(s) across {checked} scorecard(s):")
        for p in problems:
            print(f"   {p}")
        return 1

    if not os.path.exists(TEMPLATE_PATH):
        print(f"template not found: {TEMPLATE_PATH}", file=sys.stderr)
        return 2
    template_text = open(TEMPLATE_PATH, encoding="utf-8").read()

    if args.reindex:
        index_path, n = build_index(args.reindex)
        print(f"reindexed {n} card(s) -> {index_path}")
        return 0

    if args.backfill:
        out_dir = args.out or default_out_dir(args.backfill)
        announce_default(out_dir, bool(args.out))
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

    out_dir = args.out or default_out_dir(args.card)
    announce_default(out_dir, bool(args.out))
    result = render_one(args.card, out_dir, template_text)
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
