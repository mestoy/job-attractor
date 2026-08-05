#!/usr/bin/env python3
"""schema.py — the column contract. One place that NAMES the shapes, so a rename fails loudly.

⛔ READ-ONLY. This module holds no data and writes nothing. It is a vocabulary.

WHY THIS EXISTS. This pipeline keeps durable facts in two forms: markdown tables a human reads and
edits, and jsonl stores a script appends to. The markdown side grows table shapes over time — a
board file can easily carry ten different headers, with several spellings for the same column — and
**18 parsers depend on those shapes**.

The failure mode is what makes this worth a module. A markdown column rename does not raise. The
reader returns an empty list and the caller renders nothing, so the pipeline reports success while
silently losing rows. Two incidents in this codebase's history, both real:

  1. A people-table writer gained a `Known since` column and its reader was never told. For **every
     row in a several-hundred-row people table** the reader put the date badge in `company` and
     mashed the real employer into `title`. The daily briefing rendered garbage for months and
     nobody read it as broken.
  2. Two different modules parsed the SAME blocked list incompatibly and returned different answers
     about who was blocked. This module makes that visible; it does not fix it, and reconciling two
     such parsers is its own job.

⚠️ THIS MODULE FREEZES, IT DOES NOT RESHAPE. No existing table is restructured by its arrival.
Reshaping every table would break every parser for no safety gain. The rule from here:

  · A NEW table uses the canonical names below.
  · Changing an EXISTING column needs a stated reason AND the matching parser change in the same
    commit. The reason goes in the commit message, not in a comment nobody diffs.
  · A parser that must be touched anyway gets moved onto `header_map()` while it is open.

THE TWO PATTERNS THIS CODEBASE PROVED BEFORE GENERALIZING THEM HERE:

  a. PARSE BY HEADER NAME, NOT BY POSITION. `backfill_as_of.extract_pipe_tables()` tracks the most
     recent header row, finds its column by name, and requires `len(cells) == width`. That is the
     shape `header_map()` generalizes. What it replaces is the heuristic family that makes a rename
     silent: counting pipes (`line.count("|") < 8`), indexing from the right (`cells[-2]`), and
     hardcoded column numbers.
  b. ONE HEADER CONSTANT, IMPORTED BY WRITER, READER AND TEST. `parse_network.PEOPLE_TABLE_HEADER`
     is the model, and its reader asserts against it at runtime, which makes it the only parser that
     refuses a section on column drift rather than mis-indexing through it. That assertion exists
     because of incident 1 above.

⚠️ ON IMPORT DIRECTION, stated plainly because it is a deliberate departure from the obvious design.
It is tempting to have writers, readers and tests all import their constants FROM here. Taken
literally that inverts the existing dependency arrows and creates cycles, because the writers own
these values today and this module is younger than all of them. So the direction stays as the rest
of the codebase does it: the WRITER stays the owner, and this module re-exports so a reader imports
one name instead of four. A copied constant drifts the moment a rung is added; a re-exported one
cannot.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

# RE-EXPORTED, NEVER COPIED. Each of these has exactly one owner and this is not it.
from log_linkedin_send import (  # noqa: E402,F401
    ARMS_FOLLOWUP, LEGACY_RUNG, NOT_DELIVERED, RUNGS,
)
from parse_network import PEOPLE_TABLE_HEADER, PEOPLE_TABLE_RULE  # noqa: E402,F401
from record_finding import VERDICTS  # noqa: E402,F401


# ─────────────────────────────────────────────────────────────────────────────
# ROW KINDS. The canonical key set per durable row, as the WRITER builds it.
# Keys marked optional are written only when a value is present, which is why a
# key-set census of the raw file shows more shapes than there are row kinds.
# ─────────────────────────────────────────────────────────────────────────────

# documents/state/*.jsonl — company, contact, ruling and session all share ONE shape.
# This is the cleanest store in the pipeline: a single key set across all four kinds, written by
# `backfill_as_of.py` alone. It is what a board migration should read from.
#
# ⚠️ Not every state file follows it. Stores with a bespoke shape (a boss registry, a weights
# snapshot, a segment cache) are their own contract and are deliberately absent from this tuple.
STATE_ROW = ("kind", "key", "payload", "as_of", "as_of_source",
             "source_file", "source_line", "recorded_at", "run")

# documents/findings/<run>.jsonl — written by record_finding.py only.
# ⚠️ `company` is REQUIRED and is the join key. The reconciler drops any row without it, SILENTLY.
# A discovery run whose rows were keyed `name` instead went unread for days while its sidecar still
# reported the run complete — the loss was invisible AND marked done. Never key a findings row
# anything but `company`.
FINDING_ROW = ("ts", "run", "lane", "company", "verdict")
FINDING_ROW_OPTIONAL = ("filter", "evidence", "remote", "ownership", "pm_req", "comp", "note")

# documents/send-log.jsonl — the widest key drift in the pipeline, because it has been appended to
# by several generations of writer.
# ⛔ The log is NEVER rewritten. It is the record of what happened and its shape is part of that
# record. Readers normalize instead (see `rung_ladder.backfill_source`). This tuple describes what a
# NEW row carries, not what every historical row carries.
SEND_ROW = ("ts", "date", "rung", "to", "company", "targets", "subject",
            "segment", "kind", "followup_due", "status", "replied", "sent_note")
SEND_ROW_OPTIONAL = ("referred_by", "channel", "backfill", "backfilled")

# `backfill` and `backfilled` are one concept with two provenances, and no row carries both. They
# hold DIFFERENT values (which import produced the row), so coalesce the KEY on read via
# `rung_ladder.backfill_source()` and keep the value. Do not add a third spelling.

ROW_KINDS = {
    "state": STATE_ROW,
    "finding": FINDING_ROW,
    "send": SEND_ROW,
}


# ─────────────────────────────────────────────────────────────────────────────
# MARKDOWN TABLE HEADERS. Canonical column NAMES for new tables.
# ─────────────────────────────────────────────────────────────────────────────

# The join key on every company-bearing table. The pipe-table extractor skips any table whose header
# does not name it, and COUNTS the skip rather than failing — so a table that forgets this column is
# invisible to the state store instead of erroring.
COMPANY_COL = "company"

# Canonical names for the columns that recur across board files. A mature board file carries many
# header shapes, with several names for the lane column and several for the verdict column. These
# are the names a NEW table uses. Nothing existing is renamed to match.
CANONICAL_COLS = {
    "company": ("company",),
    "lane": ("lane", "segment_lane", "segment", "tier", "category", "bucket"),
    "verdict": ("verdict", "status", "badge", "disposition", "call", "next_action", "read"),
    "remote": ("remote", "remote_own_board_evidence"),
    "culture": ("culture", "culture_sub_ratings",
                "culture_directional_5_5_owed_at_gate"),
    "non_pe": ("non_pe", "ownership", "funding"),
    "boss": ("boss_email", "boss_email_inferred", "boss_email_verify",
             "boss_email_verify_before_use", "boss_verify", "boss", "product_lead"),
    "praise": ("primary_praise_url", "praise"),
    "caveat": ("caveat", "fit_flags", "notes", "note", "verification_to_do",
               "why_it_s_a_target", "why_greenfield"),
}

# The alias sets above are DESCRIPTIVE: they record which spellings a reader will meet in the wild,
# canonical first, and they were harvested from live header shapes rather than invented. They are
# not permission to add another alias. A NEW table uses the canonical name.


def field(payload, canon, default=""):
    """First present value for a canonical column, reading a state-store payload dict.

    Alias order is priority order, so `boss_email` beats `boss_verify` when a row carries both.
    Returns `default` when the row has none of them, because a board row legitimately omits columns
    that its own table never had; a KeyError here would make a many-shaped file unreadable.
    """
    for alias in CANONICAL_COLS.get(canon, (canon,)):
        v = payload.get(alias)
        if v not in (None, ""):
            return v
    return default


def normalize_key(cell):
    """A header cell to a snake_case key. Mirrors the pipe-table extractor."""
    return re.sub(r"[^a-z0-9]+", "_", str(cell or "").lower()).strip("_")


def canonical_col(name):
    """Canonical column name for a header cell, or the normalized cell when it is unrecognized.

    An unknown column passes through under its own normalized name rather than being folded into a
    catch-all, on the same reasoning as rung normalization: swallowing an unrecognized key hides the
    drift the module exists to catch.
    """
    n = normalize_key(name)
    for canon, aliases in CANONICAL_COLS.items():
        if n in aliases:
            return canon
    return n


def split_row(line):
    """Cells of a markdown pipe row, or None when the line is not one.

    The separator row (`|---|---|`) returns None too, since it carries no data and every parser that
    treats it as a row produces one garbage entry per table.
    """
    raw = str(line or "").rstrip("\n")
    if not raw.startswith("|"):
        return None
    if re.match(r"^\|[\s:\-|]+\|?$", raw):
        return None
    return [c.strip() for c in raw.strip().strip("|").split("|")]


def header_map(line):
    """{canonical_column: index} for a header row, or None when the line is not a pipe row.

    This is pattern (a) from the docstring, generalized off the pipe-table extractor. A parser
    holding one of these reads `cells[hm["company"]]` and keeps working when a column is inserted to
    its left, which is the whole failure mode that silently corrupted an entire people table.

    ⚠️ Pair it with a width check. A row whose cell count differs from the header's is NOT a row of
    that table, and reading it by index is how a many-shaped file yields data that parses cleanly
    and means nothing.
    """
    cells = split_row(line)
    if cells is None:
        return None
    return {canonical_col(c): i for i, c in enumerate(cells) if c}


class HeaderDrift(AssertionError):
    """Raised when a table's header is not the one its reader was written against."""


def assert_header(found, expected, where):
    """Refuse a section whose header drifted, loudly. Pattern (b), generalized.

    The people-table reader does this against `PEOPLE_TABLE_HEADER` and is the only parser that
    fails rather than mis-indexes. The message names the file so the next person does not have to
    bisect every store to find which table moved.
    """
    if str(found or "").strip() != str(expected).strip():
        raise HeaderDrift(
            f"header drift in {where}\n"
            f"  expected: {expected}\n"
            f"  found:    {found!r}\n"
            f"  A reader indexing this table by position is now reading the wrong columns. Fix the\n"
            f"  table or update the constant AND its parser in the same commit (scripts/schema.py)."
        )
    return True


COMPANY_PAYLOAD = ("name", "aliases")
COMPANY_PAYLOAD_OPTIONAL = ("domain", "disposition", "note")

CONTACT_PAYLOAD = ("name", "aliases")
# `linkedin` is the slug, and it is the STRONG identifier: it survives a title change, a rename and a
# job move, which is why `state._canon_boss` already keys on it. See state.py:144.
CONTACT_PAYLOAD_OPTIONAL = ("linkedin", "title", "company", "connected_on", "pronouns")

PAYLOAD_KINDS = {
    "company": COMPANY_PAYLOAD,
    "contact": CONTACT_PAYLOAD,
}

PAYLOAD_KINDS_OPTIONAL = {
    "company": COMPANY_PAYLOAD_OPTIONAL,
    "contact": CONTACT_PAYLOAD_OPTIONAL,
}


def missing_keys(row, kind):
    """Required keys absent from a row, for the row kinds in ROW_KINDS. Empty tuple means clean."""
    required = ROW_KINDS.get(kind)
    if required is None:
        raise KeyError(f"unknown row kind {kind!r}; known: {', '.join(sorted(ROW_KINDS))}")
    return tuple(k for k in required if k not in row)


if __name__ == "__main__":
    print(__doc__.strip().splitlines()[0])
    print()
    for kind, keys in ROW_KINDS.items():
        print(f"{kind:9} {len(keys):2} required: {', '.join(keys)}")
    print()
    print(f"canonical columns: {', '.join(sorted(CANONICAL_COLS))}")
    print(f"rungs:             {', '.join(sorted(RUNGS))}")
    print(f"verdicts:          {', '.join(VERDICTS)}")
    print(f"not delivered:     {', '.join(sorted(NOT_DELIVERED))}")


def missing_payload_keys(payload, kind):
    """Required payload keys absent from a state row's payload, for the kinds in PAYLOAD_KINDS.

    A SIBLING of `missing_keys()` rather than an extension of it, deliberately. `missing_keys` is
    asked about an envelope and these two kinds live one level down, so folding "company" into the
    same lookup would make the answer depend on which level the caller happened to hand over, and a
    validator you can accidentally point at the wrong dict is worse than no validator.

    ⚠️ REPORTING ONLY, and this is the load-bearing part. Every one of the 2,065 company rows and
    1,525 contact rows in the store predates `aliases`, so acting on this return value as a refusal
    would reject the entire existing store. It answers "how far is this row from the contract", which
    is what the identity backfill needs to size its work. It never decides whether a row is readable.

    A key present but empty counts as MISSING, because an empty `aliases` teaches a reader nothing
    and a row that carries the key with no value would otherwise report as clean.
    """
    required = PAYLOAD_KINDS.get(kind)
    if required is None:
        raise KeyError(f"unknown payload kind {kind!r}; known: {', '.join(sorted(PAYLOAD_KINDS))}")
    p = payload or {}
    return tuple(k for k in required if p.get(k) in (None, "", [], {}))


if __name__ == "__main__":
    print(__doc__.strip().splitlines()[0])
    print()
    for kind, keys in ROW_KINDS.items():
        print(f"{kind:9} {len(keys):2} required: {', '.join(keys)}")
    print()
    for kind, keys in PAYLOAD_KINDS.items():
        opt = PAYLOAD_KINDS_OPTIONAL.get(kind, ())
        print(f"{kind:9} payload required: {', '.join(keys)} · optional: {', '.join(opt)}")
    print()
    print(f"canonical columns: {', '.join(sorted(CANONICAL_COLS))}")
    print(f"rungs:             {', '.join(sorted(RUNGS))}")
    print(f"verdicts:          {', '.join(VERDICTS)}")
    print(f"not delivered:     {', '.join(sorted(NOT_DELIVERED))}")
