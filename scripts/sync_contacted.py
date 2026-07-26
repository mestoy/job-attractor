#!/usr/bin/env python3
"""sync_contacted.py — reconcile "who was actually contacted" between the two stores.

THE BUG this fixes (two parts):
  1. documents/contact-closeness.json holds a `contacts` dict. Each MAY carry a `sent`
     field. When a person has NOT been contacted, `sent` is JSON null → Python None →
     str(None) == "None", a TRUTHY non-empty string. Any dedup filter that does
     `if str(v.get('sent','')).strip()` therefore treats EVERYONE as contacted.
     Filters that only regex the literal word "rung" MISS off-ladder/reconnect sends
     (whose sent reads e.g. "2026-07-22 off-ladder reconnect").
  2. documents/send-log.jsonl is the GROUND TRUTH of who was actually contacted, but
     people contacted via the send-log often still have `sent: null` in the closeness
     file — the two stores are never reconciled. So already-contacted people keep
     resurfacing in candidate rankings.

This script builds a robust contacted-status for every contact by combining:
  - the existing `sent` field, honored ONLY when it is a real string carrying a real
    signal ("rung" / "off-ladder" / "reconnect" / "warm" / a 20YY- date stamp) — never
    the literal "None"/null; and
  - a whole-word / token-boundary match against the send-log, handling the messy shapes
    the `to` field comes in (linkedin slugs, descriptive strings, plain "First Last",
    emails), while avoiding substring false-positives (e.g. a contact named "Ana Kirk" must
    NOT match send-log text for an unrelated "Kirkland Bayer").

Both stores are your own data files; the script hardcodes no names and reads only whatever
is present. Paths are relative to the repo root.

Usage:
    scripts/sync_contacted.py            # dry run — report only, writes nothing
    scripts/sync_contacted.py --write    # reconcile: fill null `sent` for send-log hits

Safety: run WITHOUT --write first, eyeball the report, then --write ONCE. A backup of
contact-closeness.json is written to contact-closeness.json.bak before any write.
"""
import sys, os, re, json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOSENESS = os.path.join(REPO, "documents", "contact-closeness.json")
SENDLOG = os.path.join(REPO, "documents", "send-log.jsonl")
BACKUP = CLOSENESS + ".bak"

# --------------------------------------------------------------------------------------
# Name cleaning
# --------------------------------------------------------------------------------------

# Credential / suffix tokens to strip from the TAIL of a contact name before matching.
# A contact key like "Jo Marcell, MBA, CFE" must reduce to first=jo, last=marcell
# — using the last whitespace token as the surname would wrongly pick "CFE".
# Tokens are compared after stripping punctuation and dots and upper-casing, so "LL.M"
# and "OTR/L" and "PBC-CP" normalize to LLM / OTRL / PBCCP.
CREDENTIALS = {
    "MBA", "CFE", "PMP", "ESQ", "JD", "LLM", "PHD", "MPH", "CHES", "CST", "OTD",
    "OTRL", "CISSP", "CCSP", "CMS", "PBCCP", "CTP", "CPA", "MD", "RN", "MS", "MA",
    "MSN", "DNP", "MPA", "MSW", "LCSW", "PE", "CFA", "CISA", "CISM", "SPHR", "PHR",
    "SHRM", "CSM", "CSPO", "MFA", "EDD", "DPT", "DDS", "DO", "BSN", "FNP", "NP",
    # trailing generational suffixes — harmless to strip for matching purposes
    "JR", "SR", "II", "III", "IV",
}


def _norm_token(tok):
    """Uppercase, keep only letters/digits — 'LL.M' -> 'LLM', 'OTR/L' -> 'OTRL'."""
    return re.sub(r"[^A-Za-z0-9]", "", tok).upper()


def name_tokens(name):
    """Return the lowercase [first, ..., last] name tokens with credentials stripped.

    Splits comma groups first ("Jo Marcell, MBA, CFE" -> core "Jo Marcell"),
    then drops any trailing credential tokens from the core.
    """
    core = name.split(",")[0].strip()
    toks = [t for t in core.split() if t]
    # drop trailing credential tokens (e.g. a name written "Jane Doe PhD" without comma)
    while toks and _norm_token(toks[-1]) in CREDENTIALS:
        toks.pop()
    # keep only alphabetic tokens for name matching (drops stray "Jr."/punctuation)
    toks = [re.sub(r"[^a-z]", "", t.lower()) for t in toks]
    toks = [t for t in toks if t]
    return toks


def first_last(name):
    """(first, last) lowercase, or (None, None) if we can't form a two-signal name."""
    toks = name_tokens(name)
    if len(toks) < 2:
        return (None, None)
    return (toks[0], toks[-1])


# --------------------------------------------------------------------------------------
# send-log indexing
# --------------------------------------------------------------------------------------

def _slug_from_to(to):
    """Extract the linkedin slug from a `to` value, else None.

    Handles 'linkedin:janemdoe', 'linkedin.com/in/johnsmith',
    'linkedin.com/in/jane-doe', trailing '/'.
    """
    t = to.strip()
    if t.lower().startswith("linkedin:"):
        return t.split(":", 1)[1].strip().strip("/")
    m = re.search(r"/in/([^/?#]+)", t)
    if m:
        return m.group(1).strip().strip("/")
    return None


def _alpha_tokens(text):
    """Lowercase alphabetic word tokens (len>=2), whole-word boundaries."""
    return [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 2]


def index_sendlog(rows):
    """Turn send-log rows into a list of parsed match-entries.

    Each entry: {kind, tokens(set), compressed(str), date, rung, raw}
      - kind 'slug': name tokens from the slug; compressed = name tokens joined (no digits)
      - kind 'text': whole-word tokens from a descriptive `to`
      - kind 'email': whole-word tokens from the local part before '@'
    Rows with an empty `to` carry no person identity and are skipped.
    """
    idx = []
    for r in rows:
        to = (r.get("to") or "").strip()
        if not to:
            continue
        date = r.get("date", "")
        rung = r.get("rung", "")
        slug = _slug_from_to(to)
        if slug is not None:
            # split slug into tokens; keep only alphabetic ones for name matching
            # (drops trailing hash ids like 'a614b051', '812268118', '3014bb28')
            raw = re.split(r"[^A-Za-z0-9]+", slug)
            name_toks = [t.lower() for t in raw if t.isalpha()]
            idx.append({
                "kind": "slug",
                "tokens": set(name_toks),
                "compressed": "".join(name_toks),
                "date": date, "rung": rung, "raw": to,
            })
        elif "@" in to and " " not in to:
            local = to.split("@", 1)[0]
            toks = _alpha_tokens(local.replace(".", " ").replace("_", " "))
            idx.append({
                "kind": "email",
                "tokens": set(toks),
                "compressed": "".join(toks),
                "date": date, "rung": rung, "raw": to,
            })
        else:
            toks = _alpha_tokens(to)
            idx.append({
                "kind": "text",
                "tokens": set(toks),
                "compressed": "",
                "date": date, "rung": rung, "raw": to,
            })
    return idx


# --------------------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------------------

def match_sendlog(name, sendlog_index):
    """Return the first send-log entry that matches this contact name, else None.

    Rules (all require BOTH a first-name and last-name signal, never a lone substring):
      - text/email: contact's first AND last token both appear as whole tokens.
      - slug: (a) first AND last both in the slug's name tokens, OR
              (b) the slug's compressed name string startswith(first) AND endswith(last)
                  — catches single-token slugs with a middle initial, e.g.
                  'janemdoe' -> Jane Doe, 'johnsmith' -> John Smith, OR
              (c) compressed slug == compressed contact (exact).
    """
    first, last = first_last(name)
    if not first or not last or len(first) < 2 or len(last) < 2:
        return None
    compressed_contact = first + last
    for e in sendlog_index:
        toks = e["tokens"]
        if e["kind"] in ("text", "email"):
            if first in toks and last in toks:
                return e
        else:  # slug
            if first in toks and last in toks:
                return e
            comp = e["compressed"]
            if comp and comp.startswith(first) and comp.endswith(last):
                return e
            if comp and comp == compressed_contact:
                return e
    return None


# Real signals that an existing `sent` string means "actually contacted".
_SENT_SIGNALS = ("rung", "off-ladder", "reconnect", "warm")
# A real date stamp, e.g. "2026-07-22" — any 20YY- prefix (year-agnostic, not hardcoded).
_DATE_STAMP = re.compile(r"\b20\d\d-\d")


def existing_sent_is_real(sent):
    """True only when `sent` is a real string carrying a contact signal.

    Never true for None, "", or the literal string "None"/"null".
    """
    if not isinstance(sent, str):
        return False
    s = sent.strip()
    if not s or s.lower() in ("none", "null"):
        return False
    low = s.lower()
    if _DATE_STAMP.search(s):  # a real date stamp
        return True
    return any(sig in low for sig in _SENT_SIGNALS)


def is_contacted(name, contact_record, sendlog_index):
    """Reusable predicate other scripts can import.

    Returns True if this contact was actually contacted — either their existing `sent`
    field is a real signal, or the send-log ground truth matches them. Robust against the
    str(None)=="None" truthiness trap and against substring false positives.
    """
    if existing_sent_is_real((contact_record or {}).get("sent")):
        return True
    return match_sendlog(name, sendlog_index) is not None


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def load():
    if not os.path.exists(CLOSENESS):
        return {}, []
    with open(CLOSENESS, encoding="utf-8") as f:
        data = json.load(f)  # dict preserves insertion order (py3.7+)
    rows = []
    if os.path.exists(SENDLOG):
        with open(SENDLOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return data, rows


def run(write=False):
    data, rows = load()
    contacts = data.get("contacts", {})
    idx = index_sendlog(rows)

    total = len(contacts)
    contacted = 0
    sync_gap = []          # newly reconciled from send-log that had sent: null/missing
    for name, rec in contacts.items():
        if not isinstance(rec, dict):
            continue
        via_existing = existing_sent_is_real(rec.get("sent"))
        m = None if via_existing else match_sendlog(name, idx)
        if via_existing or m is not None:
            contacted += 1
        if not via_existing and m is not None:
            sync_gap.append((name, m))

    # ---- report -------------------------------------------------------------------
    print("=" * 72)
    print("sync_contacted.py — contact-closeness.json <-> send-log.jsonl")
    print("=" * 72)
    if not contacts:
        print("no contacts found in documents/contact-closeness.json (nothing to reconcile).")
        print("=" * 72)
        return sync_gap
    print(f"send-log rows            : {len(rows)}  ({len(idx)} with an identifiable `to`)")
    print(f"total contacts           : {total}")
    print(f"contacted (either store) : {contacted}")
    print(f"SYNC GAP (send-log hit, sent was null/missing) : {len(sync_gap)}")
    print("-" * 72)
    if sync_gap:
        for name, m in sorted(sync_gap, key=lambda x: x[0].lower()):
            print(f"  + {name:<34} <- {m['raw']}  [{m['date']} {m['rung']}]")
    else:
        print("  (none — the two stores are already reconciled)")
    print("-" * 72)

    # ---- write --------------------------------------------------------------------
    if write:
        if sync_gap:
            # back up first
            with open(CLOSENESS, encoding="utf-8") as f:
                original = f.read()
            with open(BACKUP, "w", encoding="utf-8") as f:
                f.write(original)
            print(f"backup written: {BACKUP}")
            for name, m in sync_gap:
                rec = contacts[name]
                rung = (m["rung"] or "").strip()
                date = (m["date"] or "").strip()
                val = " ".join(p for p in [date, rung] if p) + " [synced-from-send-log]"
                rec["sent"] = val.strip()
            # Match the source file's unicode-escaping convention so the diff shows ONLY
            # the reconciled `sent` fields, not 1000+ lines of emoji re-encoding churn.
            # If the source ships fully ASCII-escaped (\uXXXX), writing literal UTF-8 would
            # rewrite nearly every line and bury the real change. So: keep literal unicode
            # only if the source already had it.
            source_has_literal_unicode = any(ord(ch) > 127 for ch in original)
            with open(CLOSENESS, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2,
                          ensure_ascii=not source_has_literal_unicode)
                f.write("\n")
            print(f"WROTE {len(sync_gap)} reconciled `sent` values to contact-closeness.json")
            print(f"(ensure_ascii={not source_has_literal_unicode}, matching source convention)")
        else:
            print("--write: nothing to reconcile (0 sync-gap names). File untouched.")
    print("=" * 72)

    return sync_gap


def main():
    write = "--write" in sys.argv[1:]
    run(write=write)
    sys.exit(0)


if __name__ == "__main__":
    main()
