#!/usr/bin/env python3
"""reconcile_contacts.py — does the contact roster agree with the newest LinkedIn export?

WHY THIS EXISTS, measured rather than assumed (2026-08-10). The newest export held 1,447
connections. **35 of those people were absent from `documents/warm-network.md`**, which makes them
invisible to the daily 3-3-3, the warm-rung roster anchor and `check_dup`. **76 had no row in
`documents/contact-closeness.json`**, which fails their ask shape CLOSED so they cannot be contacted
at any rung. Two exports had never been ingested, so the version-controlled copy was two behind and
the raw input lived only in a Downloads folder.

`check_network_freshness.py` had been printing a correct warning all day and nothing acted on it,
because it compares max DATES. A max() cannot see a hole: 35 missing PEOPLE are invisible to a date
check that reports "current". Nothing anywhere compared COUNTS, and
`documents/contact-closeness.json` is referenced ZERO times in `consistency-check.sh` despite holding
1,433 stated relationships, which is the safety property the whole one-pool ruling rests on.

⚖️ THE DISCIPLINE IS COPIED FROM `reconcile_linkedin.py`, DELIBERATELY: it refuses to collapse
different disagreements into one number. Two earlier hand-rolled attempts at that file both got it
wrong the same way, by keying on one spelling. A single "N contacts out of sync" would be
unactionable, because MISSING-FROM-ROSTER is fixed by a re-parse, MISSING-CLOSENESS can only be
fixed by the human, and ORPHAN may not be a problem at all.

WHAT IT DOES

  Phase A (writes, only with --apply)  the SAFE LANES, orchestrated in their documented order.
                                      Adds no new write path: every one of these already writes
                                      .bak-first, merge-only, and refuses to regress to an older
                                      export. `parse_network` exits 3 and `ingest_export` exits 4
                                      rather than overwrite newer data with older.
  Phase B (read-only)                 the audit, classified into named kinds, never summed.
  Phase C                             a dated report plus a stamp under documents/state/.

⛔ WHAT IT NEVER WRITES: closeness levels, `outreach_status`, blocked status, or any field whose
`source` is `stated-by-<owner>`. Those are the OWNER'S rulings. Only they know who they know, and a
script that guessed would silently overwrite the one store no export can reconstruct.

Exit: 0 = clean · 1 = divergences found · 2 = a store or the export was unreadable · 3 = usage
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

STAMP = os.path.join(REPO, "documents", "state", "contact-reconcile.json")
# Where `ingest_export.py` puts its sanitized copies. Kept in sync with that script's DEST_DIR.
EXPORTS_DIR = os.path.join(REPO, "documents", "linkedin-exports")

# ── THE KINDS. Named, never summed. ──────────────────────────────────────────────────────────
# Each one has a DIFFERENT fixer, which is the whole reason they are separate:
#   MISSING-FROM-ROSTER  a re-parse fixes it, no human needed
#   MISSING-CLOSENESS    ONLY the human can fix it; a guess would corrupt the safety store
#   IDENTITY-SPLIT       a recorded alias fixes it (never a looser matcher)
#   STALE-TITLE          a human verification fixes it, one contact at a time
#   ROLE-ENDED           already known; the row is a reminder not to rank them
#   ORPHAN               may be no problem at all: a removed connection is a real event
#   EXPORT-LAG           NOT a gap. The export itself is old and only a download changes that.
KINDS = ("MISSING-FROM-ROSTER", "MISSING-CLOSENESS", "IDENTITY-SPLIT",
         "STALE-TITLE", "ROLE-ENDED", "ORPHAN", "EXPORT-LAG")

FIXER = {
    "MISSING-FROM-ROSTER": "python3 scripts/parse_network.py",
    "MISSING-CLOSENESS": "level them yourself; no script may guess a relationship",
    "IDENTITY-SPLIT": "state.register(kind, canonical, alias=variant) — record it, never loosen the matcher",
    "STALE-TITLE": "python3 scripts/record_role.py --name ... --source ...",
    "ROLE-ENDED": "already recorded; do not rank them",
    "ORPHAN": "expected when a connection is removed; no action unless it surprises you",
    "EXPORT-LAG": "download a fresh LinkedIn export (Settings, Data privacy, Get a copy of your data)",
}


def _run(args, label):
    """Run a lane, returning (ok, tail-of-output). Never raises."""
    try:
        p = subprocess.run([sys.executable] + args if args[0].endswith(".py") else args,
                           cwd=REPO, capture_output=True, text=True, timeout=600)
    except Exception as e:
        return False, f"{label}: {e.__class__.__name__}"
    out = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
    return p.returncode == 0, f"{label}: exit {p.returncode} · " + (out[-1] if out else "")


def _export_rows():
    from parse_network import find_export, parse_rows
    path, text = find_export()
    return (parse_rows(text) if text else []), path


def _name(row):
    return f"{(row.get('First Name') or '').strip()} {(row.get('Last Name') or '').strip()}".strip()


def _ws(s):
    """Collapse runs of whitespace. The roster blob separates names with DOUBLE spaces, so a name
    lands in it as `Firstname  Lastname` (double space) and a naive `name in text` test misses a person who is
    plainly there. Found on the first live run: 26 rows reported missing, and this was most of them.
    ⛔ A reconciler that over-reports is the failure this file exists to prevent, committed by the
    file itself."""
    return " ".join(str(s or "").split())


def _excluded_at_source(row):
    """True when `parse_network` excludes this person AT SOURCE, so their absence is by design.

    Some searches carry a hard rule: the LEADERSHIP tier at a named employer is out of scope while
    peers below it stay in. Counting those people as MISSING-FROM-ROSTER blames the roster for
    obeying a rule it was told to obey.

    🛑 CONFIG-DRIVEN, NEVER HARD-CODED. Upstream this function named one specific former employer.
    In the kit the employer list and the leadership titles both come from `kit_config`
    (EXCLUDED_EMPLOYERS, EXCLUDED_EMPLOYER_LEADERSHIP_TITLES), so it is a NO-OP until the operator
    configures one. Reuses the writer's own compiled patterns BY IMPORT so the two cannot drift.
    """
    try:
        from parse_network import EXCLUDED_EMPLOYER_RE, EXCLUDED_LEADERSHIP_RE
    except Exception:
        return False
    if EXCLUDED_EMPLOYER_RE is None or EXCLUDED_LEADERSHIP_RE is None:
        return False        # nothing configured, so nothing is excluded by design
    name = f"{row.get('First Name', '')} {row.get('Last Name', '')}"
    if not EXCLUDED_EMPLOYER_RE.search(row.get("Company") or ""):
        return False
    return bool(EXCLUDED_LEADERSHIP_RE.search(row.get("Position") or "")
                or EXCLUDED_LEADERSHIP_RE.search(name))


def _slug(row):
    return (row.get("URL") or "").strip().rstrip("/").rsplit("/", 1)[-1].lower()


def apply_safe_lanes(export_path):
    """Phase A. Orchestrates EXISTING scripts; adds no new write path.

    ⚖️ Order is the one `ingest_export.py` prints for itself. Each lane is allowed to fail without
    stopping the audit, because a partial reconcile plus an honest report beats an abort that
    leaves the operator with neither.
    """
    notes = []
    if export_path:
        raw = str(export_path).split("::", 1)[0]
        # ⚖️ SKIP THE INGEST WHEN THE RESOLVED EXPORT IS ALREADY THE INGESTED COPY. `find_export`
        # falls back to `documents/linkedin-exports/` once a download has been ingested, which is
        # the normal steady state, so this lane was handing `ingest_export` its own output. That is
        # now refused there (exit 5), but a refusal every morning is a red lane nobody reads.
        # Nothing to ingest is a lane that should not run, not a lane that should fail.
        if os.path.dirname(os.path.abspath(raw)) == os.path.abspath(EXPORTS_DIR):
            notes.append("ingest_export: skipped · already ingested, nothing new to copy in")
        else:
            notes.append(_run(["scripts/ingest_export.py", raw], "ingest_export")[1])
    for args, label in ((["scripts/parse_network.py"], "parse_network"),
                        (["scripts/parse_messages.py", "--write"], "parse_messages"),
                        (["scripts/sync_contacted.py", "--write"], "sync_contacted")):
        notes.append(_run(args, label)[1])
    return notes


def audit():
    """Phase B. Read-only. Returns {kind: [rows]} plus context. Raises only on an unreadable store."""
    rows, export_path = _export_rows()
    named = [r for r in rows if _name(r)]
    found = {k: [] for k in KINDS}

    roster = _ws(open(os.path.join(REPO, "documents", "warm-network.md"),
                      encoding="utf-8", errors="ignore").read())
    close = json.load(open(os.path.join(REPO, "documents", "contact-closeness.json"),
                           encoding="utf-8")).get("contacts") or {}

    roles = {}
    rp = os.path.join(REPO, "documents", "state", "contact-roles.jsonl")
    if os.path.exists(rp):
        for line in open(rp, encoding="utf-8"):
            if line.strip():
                try:
                    d = json.loads(line)
                    roles[str(d.get("name") or "")] = d
                except Exception:
                    continue

    for r in named:
        n = _name(r)
        if _ws(n) not in roster and not _excluded_at_source(r):
            found["MISSING-FROM-ROSTER"].append(n)
        if n not in close:
            found["MISSING-CLOSENESS"].append(n)
        role = roles.get(n)
        if role and str(role.get("still_there")).lower() in ("false", "no", "0"):
            found["ROLE-ENDED"].append(f"{n} (verified {role.get('verified_on', '?')})")
        elif not role:
            found["STALE-TITLE"].append(n)

    # IDENTITY-SPLIT: one slug, more than one name spelling, read from the durable store.
    by_slug = {}
    cp = os.path.join(REPO, "documents", "state", "contact.jsonl")
    if os.path.exists(cp):
        for line in open(cp, encoding="utf-8"):
            if not line.strip():
                continue
            try:
                p = json.loads(line).get("payload") or {}
            except Exception:
                continue
            if p.get("linkedin") and p.get("name"):
                by_slug.setdefault(p["linkedin"], set()).add(p["name"])
    # ⛔ A RECORDED ALIAS RESOLVES A SPLIT. Two spellings under one slug are only a PROBLEM while
    # nothing links them; once the collapse is recorded, every join already works and reporting it
    # would send the operator to fix something already fixed. Resolve both sides and compare keys.
    def _unresolved(names):
        try:
            import state as _st
            keys = {_st.resolve("contact", n) or n for n in names}
            return len(keys) > 1
        except Exception:
            return True          # cannot check: report it rather than go quiet
    found["IDENTITY-SPLIT"] = [f"{k.rsplit('/', 1)[-1]}: {sorted(v)}"
                               for k, v in by_slug.items()
                               if len(v) > 1 and _unresolved(v)]

    # ORPHAN: in the roster, absent from the export. A removed connection is a real event, so this
    # is reported and never "fixed".
    export_names = {_name(r) for r in named}
    for cname in close:
        if cname.startswith("_"):
            continue
        if cname not in export_names and _ws(cname) in roster:
            found["ORPHAN"].append(cname)

    try:
        import check_network_freshness as nf
        s = nf.scan()
        if (s.get("export_taken_days") or 0) > 14:
            found["EXPORT-LAG"].append(
                f"export taken {s['export_taken_days']}d ago ({s.get('export_taken')})")
    except Exception:
        pass

    return found, {"export": os.path.basename(str(export_path or "")), "export_rows": len(named),
                   "roster_chars": len(roster), "closeness_rows": len(close),
                   "slugs": len(by_slug)}


def write_report(found, ctx, lanes):
    path = os.path.join(REPO, "documents", f"contact-reconcile-{date.today().isoformat()}.md")
    L = [f"# Contact reconciliation — {date.today().isoformat()}", "",
         f"> Export: `{ctx['export']}` · {ctx['export_rows']} named connections · "
         f"{ctx['closeness_rows']} closeness rows · {ctx['slugs']} slugs on file.", ""]
    if lanes:
        L += ["## Safe lanes applied", ""] + [f"- {n}" for n in lanes] + [""]
    L += ["## Divergences, by kind", "",
          "⛔ These are NOT summed. Each kind has a different fixer, which is why they are separate.",
          ""]
    for k in KINDS:
        rowsk = found.get(k) or []
        L.append(f"### {k} — {len(rowsk)}")
        L.append(f"*Fix:* {FIXER[k]}")
        if rowsk:
            L += ["", "```"] + [f"  {x}" for x in rowsk[:40]]
            if len(rowsk) > 40:
                L.append(f"  … and {len(rowsk) - 40} more")
            L.append("```")
        L.append("")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="run the SAFE LANES first (ingest, parse, merge). Default is audit only.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    lanes = []
    try:
        _rows, export_path = _export_rows()
    except Exception as e:
        print(f"🔴 could not read the export ({e.__class__.__name__}). This is NOT 'nothing to do'.",
              file=sys.stderr)
        return 2
    if a.apply:
        lanes = apply_safe_lanes(export_path)

    try:
        found, ctx = audit()
    except Exception as e:
        print(f"🔴 a contact store was unreadable ({e.__class__.__name__}).", file=sys.stderr)
        return 2

    report = write_report(found, ctx, lanes)
    os.makedirs(os.path.dirname(STAMP), exist_ok=True)
    with open(STAMP, "w", encoding="utf-8") as fh:
        json.dump({"last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "counts": {k: len(found.get(k) or []) for k in KINDS},
                   "export": ctx["export"], "report": os.path.relpath(report, REPO)}, fh, indent=2)

    if a.json:
        print(json.dumps({"counts": {k: len(found.get(k) or []) for k in KINDS}, "context": ctx}))
    elif not a.quiet:
        print("=" * 74)
        print(f"  CONTACT RECONCILIATION — {ctx['export_rows']} connections in {ctx['export']}")
        print("=" * 74)
        for n in lanes:
            print(f"  ⚙️  {n}")
        for k in KINDS:
            c = len(found.get(k) or [])
            mark = "✅" if not c else ("⚪" if k in ("ORPHAN", "EXPORT-LAG") else "🔴")
            print(f"  {mark} {k:<22} {c}")
        print(f"\n  📄 {os.path.relpath(report, REPO)}")
        if not a.apply:
            print("     (audit only — pass --apply to run the safe lanes first)")

    # ⚖️ ORPHAN and EXPORT-LAG do not fail the run. A removed connection is a real event, and an old
    # export is a condition only a human download can clear; a check that stays red for something
    # nobody can fix from here is one nobody reads.
    hard = sum(len(found.get(k) or []) for k in KINDS if k not in ("ORPHAN", "EXPORT-LAG"))
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
