#!/usr/bin/env python3
"""new_contact_sweep.py — one durable, idempotent entrypoint that chains the network scripts.

WHY THIS EXISTS (Michael, 2026-08-15). Every building block for onboarding a new LinkedIn connection
already exists as an independent, idempotent CLI — parse_network (export → contact registry +
warm-network.md), level_contacts (messages → closeness + the levelling queue), contact_signals
(company → segment), resolve_employers (unknown company → segment via a resolver), mutual_groups (the
mutual-groups queue) — but nothing CHAINS them, so each new export drop was a manual multi-step ritual
and new connections silently aged unlevelled. This is the single entrypoint that runs the chain on
each export drop.

⛔ IT ORCHESTRATES; IT DOES NOT REIMPLEMENT. Every inference stays in the script that owns it. This
file only computes the delta, sequences the stages, writes the segment onto each new contact's record,
and reports. It never scrapes: the mutual-connections / Highlights read is auth-walled (Cloudflare +
login) and stays a QUEUED interactive step (mutual_groups --queue), exactly like bridge_sweep. "Done"
means the review queues are populated, never emptied.

STAGES (all idempotent; re-running on the same export writes nothing new):
  1. DETECT     newest export vs the cursor; nothing new → exit 0 with a clear line.
  2. DELTA      contacts in the export not already in the durable registry = the NEW connections.
  3. REGISTER   parse_network --write (registers contacts, regenerates warm-network.md).
  4. ENQUEUE    new contacts surface in level_contacts.pending() for the human review tool. NO
                inference — closeness is REVIEWED, not read off message count (a close tie can have
                zero messages). The sweep never runs infer and never default-files a tier.
  5. RESOLVE    unknown NEW employers → resolve_employers, so segment+company are known now
                (Michael's Q3(b); paid: a resolver agent reads sites/Lusha). Skippable, degrades.
  6. SEGMENT    write the inferred segment onto each NEW contact's registry record (Michael's Q1(b):
                queryable, not just reported), carrying the existing fields forward.
  7. REPORT     a dated report + the two review-queue sizes; the cursor is written LAST so a crash
                before completion re-runs cleanly.

DURABILITY: the cursor documents/state/new-contact-sweep.json ({last_swept_export, last_run_utc,
new_count}) is the one new store, written last. Every write stage is already idempotent (parse_network's
per-row signature, level_contacts._may_infer_over + _last_swept_export, resolve_employers' cache,
mutual_groups queue-by-absence). Older exports are refused (inherited from parse_network). Any stage
that errors still writes the report with what it got and leaves the cursor UNMOVED, so the next run retries.

⛔ THIS SCRIPT DOES NOT WIRE ITSELF LIVE. Invocation (launchd WatchPaths on the export folder, a
SessionStart surfacing line) is a separate, reviewed step. Running it by hand is always safe.

Usage:
    scripts/new_contact_sweep.py            # run the sweep
    scripts/new_contact_sweep.py --force    # re-run even if the export is unchanged
    scripts/new_contact_sweep.py --no-resolve   # skip the paid employer-resolution stage
    scripts/new_contact_sweep.py --json     # machine-readable summary to stdout
Exit: 0 ok / 0 nothing-new / 1 a stage failed (report still written, cursor unmoved)
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

CURSOR = os.path.join(REPO, "documents", "state", "new-contact-sweep.json")


# ── small helpers ───────────────────────────────────────────────────────────────────────────────

def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _load_cursor():
    try:
        with open(CURSOR, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_cursor(export_basename, new_count):
    """Written LAST. A crash before this leaves the cursor unmoved, so the next run re-does the sweep
    against the same export — which is safe, because every write stage is idempotent."""
    os.makedirs(os.path.dirname(CURSOR), exist_ok=True)
    tmp = CURSOR + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"last_swept_export": export_basename, "last_run_utc": _utcnow(),
                   "new_count": new_count}, fh, indent=2)
    os.replace(tmp, CURSOR)   # atomic; a half-written cursor never becomes the authority


def _run(cmd, label):
    """Subprocess a sibling CLI. Returns (ok, stdout). Never raises — a failed stage degrades the
    sweep to a report, it does not crash it."""
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, cmd[0])] + cmd[1:],
                           capture_output=True, text=True, cwd=REPO, timeout=600)
        if p.returncode != 0:
            return False, (p.stdout or "") + (p.stderr or "")
        return True, p.stdout or ""
    except Exception as exc:
        return False, f"{label} raised: {exc}"


def _export_date_iso(basename):
    """The export's own date (from its filename) for use as an `as_of`, else today. A segment fact is
    as-of the export that named the employer, not 'live today'."""
    try:
        import parse_network
        d = parse_network.export_date_from_name(basename)
        if d:
            return d.isoformat()
    except Exception:
        pass
    return datetime.date.today().isoformat()


# ── the stages ────────────────────────────────────────────────────────────────────────────────

def detect(force=False):
    """(export_path, export_basename, changed). `changed` is False when the newest export is the one
    the cursor already swept and --force was not given."""
    import parse_network
    path, _ = parse_network.find_export()
    if not path:
        return None, None, False
    basename = os.path.basename(str(path).split("::")[0])
    if not force and _load_cursor().get("last_swept_export") == basename:
        return path, basename, False
    return path, basename, True


def _contact_keys():
    """The normalized keys already in the durable contact registry, so we can name the NEW ones."""
    try:
        import state
        return set(state.keys("contact"))
    except Exception:
        return set()


def new_contacts(before_keys):
    """[(name, company, position, connected)] for export contacts whose key was NOT in the registry
    before this run — i.e. the genuinely new connections. Uses the SAME reader level_contacts uses.

    BUG-180 DUAL-KEY dedup: a contact registered under its HANDLE key (post-fix, the collision-free
    identity) would not match a squash-only key_for(name), so a squash-only check would re-classify
    every handle-keyed contact as NEW every run and re-process it. Read the export's own URL column and
    check whether EITHER candidate key (handle or squashed name) is already registered."""
    import level_contacts
    import state
    # name -> LinkedIn URL from the export, so the dedup can compute the handle key too.
    url_by_name = {}
    try:
        from parse_network import find_export, parse_rows
        _p, _text = find_export()
        for r in (parse_rows(_text) if _text else []):
            nm = f"{(r.get('First Name') or '').strip()} {(r.get('Last Name') or '').strip()}".strip()
            if nm:
                url_by_name[nm] = (r.get("URL") or "").strip()
    except Exception:
        pass
    out = []
    for name, company, position, connected in level_contacts.export_contacts():
        try:
            cand = state._candidate_keys("contact", name, url_by_name.get(name, ""))
        except Exception:
            cand = []
        if cand and not any(k in before_keys for k in cand):
            out.append((name, company, position, connected))
    return out


def write_segments(new_rows, as_of, source):
    """Q1(b): write the inferred segment onto each NEW contact's registry record, queryable via
    state.current('contact', name). Carries the existing payload FORWARD, because state.current
    returns the newest WHOLE record (field-merge lives only in from_source), so a segment-only write
    would shadow the title/company parse_network just registered.

    ⛔ `source` MUST parse to a valid state source family (live|authored|export|git); state.append
    rejects anything else with a StateError, and that rejection is SILENT here (caught per row), so a
    bad family writes NOTHING while the run still looks green. Pass `export:<export-basename>` — the
    same family parse_network registers contacts under (parse_network.py:436). With the SAME `as_of`
    (the export date) and the same family, the later-appended segment row wins the append-order
    tiebreak, so state.current returns it with the carried-forward fields. (Regression: the first cut
    passed 'new_contact_sweep:segment', an invalid family, so every write raised and the whole
    feature was a silent no-op — caught by the correctness panel, 2026-08-15.)

    Records BOTH the closed-vocabulary slug (contact_signals.segment_for, or the relevance verdict
    when no slug matched) and the matched detail, so a later query can tell 'payments' from a bare
    'off-segment'/'unknown'. Best-effort per row, but the caller surfaces `errors` into failures so a
    systemic breakage HOLDS the cursor instead of silently advancing."""
    import contact_signals
    import state
    counts = {"relevant": 0, "off": 0, "unknown": 0, "written": 0, "errors": 0}
    cache = contact_signals.load_employer_cache()   # the fresh cache (post-resolve)
    for name, company, position, _connected in new_rows:
        try:
            status, detail = contact_signals.segment_read(company or "", position or "", cache=cache)
            slug, matched = contact_signals.segment_for(company or "", position or "")
            counts[status] = counts.get(status, 0) + 1
            segment = slug or ("off-segment" if status == "off" else "unknown")
            existing = (state.current("contact", name) or {}).get("payload") or {}
            fields = {k: v for k, v in existing.items() if k not in ("name", "aliases")}
            fields["segment"] = segment
            fields["segment_detail"] = (matched or detail or "")[:200]
            fields["segment_status"] = status
            state.register("contact", name, as_of=as_of, as_of_source=source, **fields)
            counts["written"] += 1
        except Exception:
            counts["errors"] += 1
    return counts


def resolve_new_employers(new_rows, enabled):
    """Q3(b): resolve unknown NEW employers so segment is known this run. resolve_employers is NOT a
    pure function — resolution is done by a resolver AGENT reading sites/Lusha (worklist → agent →
    ingest). So this emits the worklist and, when enabled, subprocesses a headless `claude -p`
    resolver exactly as auto-sweep.sh does its findings stage, then ingests the validated result.

    ⚠️ DEGRADES, NEVER BLOCKS. An interactively-authenticated MCP server (Lusha) may be ABSENT in a
    headless/cron run; the resolver resolves what it can from the web and leaves the rest, which stay
    in the worklist for the next run. If `claude` is unavailable or --no-resolve is set, the unknown
    employers are simply left queued and the report says so. A missing segment falls back to the name
    read; it never guesses a band."""
    import contact_signals
    have = contact_signals.load_employer_cache()
    todo = sorted({(c or "").strip() for _n, c, _p, _d in new_rows
                   if (c or "").strip()
                   and contact_signals._employer_key(c) not in have})
    if not todo:
        return {"todo": 0, "resolved": 0, "skipped": "none-needed"}
    if not enabled:
        return {"todo": len(todo), "resolved": 0, "skipped": "--no-resolve", "employers": todo}

    # A headless resolver, scoped tight: read the worklist, resolve via Lusha/web, ingest the result.
    # Kept OUT of this file's own logic on purpose — a language model reading company sites is exactly
    # what resolve_employers' worklist/ingest contract is built around, and the ingest step validates
    # every row (closed-vocabulary segment, non-empty industry, cited source) before it lands.
    import shutil
    import tempfile
    if not shutil.which("claude"):
        return {"todo": len(todo), "resolved": 0, "skipped": "no-claude-cli", "employers": todo}
    outfile = os.path.join(tempfile.gettempdir(), "new-contact-sweep-resolved.json")
    prompt = (
        "Resolve each employer below to one of Michael's five target segments "
        "(payments, applied-ai, ai-enablement, regulated-workflow, govtech), 'off-segment', or "
        "'not-found'. Read the company's own site (and Lusha if available). For each, emit "
        "{employer, segment, industry, source} where source is a CITATION (a URL or named doc), "
        "never a bare assertion. Write a JSON object {\"employers\":[...]} to " + outfile + " and "
        "then run: python3 scripts/resolve_employers.py ingest " + outfile + "\n\nEmployers:\n"
        + "\n".join(f"- {e}" for e in todo))
    try:
        p = subprocess.run(
            ["claude", "-p", prompt,
             "--allowedTools", "WebFetch,WebSearch,Bash(python3 scripts/resolve_employers.py ingest*)",
             "--permission-mode", "acceptEdits"],
            capture_output=True, text=True, cwd=REPO, timeout=1800)
        # Count what actually landed in the cache rather than trusting the agent's word.
        after = contact_signals.load_employer_cache()
        resolved = sum(1 for e in todo if contact_signals._employer_key(e) in after)
        return {"todo": len(todo), "resolved": resolved,
                "left_queued": len(todo) - resolved,
                "resolver_rc": p.returncode}
    except Exception as exc:
        return {"todo": len(todo), "resolved": 0, "skipped": f"resolver-error: {exc}",
                "employers": todo}


def queue_sizes():
    """The two review queues the human works interactively — sizes only, never scraped here."""
    out = {}
    try:
        import level_contacts
        out["levelling"] = len(level_contacts.pending())
    except Exception:
        out["levelling"] = None
    try:
        import mutual_groups
        out["mutual_groups"] = len(mutual_groups._people_queue(10_000))
    except Exception:
        out["mutual_groups"] = None
    return out


def write_report(basename, new_rows, resolve_stats, seg_counts, queues):
    """A dated report, mirroring the discovery sweep's dated output. NOT the cursor — a report is a
    view, the cursor is the authority."""
    d = datetime.date.today().isoformat()
    path = os.path.join(REPO, "documents", f"new-contacts-{d}.md")
    lines = [f"# New-contact sweep — {d}", "",
             f"> Export: `{basename}` · {len(new_rows)} new connection(s) this sweep.", "",
             "## Closeness — QUEUED FOR HUMAN REVIEW (no inference; message count is not a proxy)",
             f"- {len(new_rows)} new contact(s) enqueued — set each tier by hand in "
             f"scripts/review_contacts.py",
             f"- levelling queue now: {queues.get('levelling')} awaiting review", "",
             "## Segment (written onto each contact record)",
             f"- relevant: {seg_counts.get('relevant', 0)} · off-segment: {seg_counts.get('off', 0)}"
             f" · unknown: {seg_counts.get('unknown', 0)} · written: {seg_counts.get('written', 0)}",
             f"- employer resolution: {json.dumps(resolve_stats)}", "",
             "## Review queues (interactive — nothing is scraped for you)",
             f"- closeness levelling: {queues.get('levelling')} awaiting (`level_contacts.py --batch`)",
             f"- mutual groups: {queues.get('mutual_groups')} awaiting "
             f"(`mutual_groups.py --queue` — open each profile logged in)", "",
             "## New connections", ""]
    for name, company, position, connected in new_rows[:200]:
        lines.append(f"- **{name}** · {position or '?'} @ {company or '?'} · connected {connected or '?'}")
    if len(new_rows) > 200:
        lines.append(f"- … and {len(new_rows) - 200} more (see the registry).")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


# ── the entrypoint ───────────────────────────────────────────────────────────────────────────────

def sweep(force=False, resolve=True):
    """Run the chain. Returns a summary dict. The cursor is written LAST and only on a full pass."""
    path, basename, changed = detect(force)
    if not path:
        return {"status": "no-export", "message": "no LinkedIn export found"}
    if not changed:
        return {"status": "nothing-new", "export": basename,
                "message": f"export {basename} already swept (use --force to re-run)"}

    before = _contact_keys()                     # snapshot BEFORE register, so 'new' is meaningful
    summary = {"status": "ok", "export": basename, "stages": {}, "failures": []}

    ok, out = _run(["parse_network.py", "--write"], "parse_network")
    summary["stages"]["register"] = "ok" if ok else "FAILED"
    if not ok:
        summary["failures"].append(f"parse_network: {out[:300]}")

    rows = new_contacts(before)
    summary["new_count"] = len(rows)

    # ⛔ NO CLOSENESS INFERENCE (ruling 2026-08-16,
    # [[closeness-is-reviewed-not-inferred-from-message-count]]). Message count is not a closeness
    # proxy — a close tie can have zero messages — so the sweep NEVER runs level_contacts.infer and
    # NEVER default-files a tier. New contacts are ENQUEUED for the human review tool
    # (scripts/review_contacts.py) by construction: once registered in stage 3, an un-levelled contact
    # automatically surfaces in level_contacts.pending(). "Enqueue" is therefore the absence of an
    # inference step, not an active write.
    summary["stages"]["closeness"] = "enqueued-for-review (no infer)"

    resolve_stats = resolve_new_employers(rows, enabled=resolve)
    summary["stages"]["resolve"] = resolve_stats

    seg_counts = write_segments(rows, as_of=_export_date_iso(basename),
                                source=f"export:{basename}")
    summary["stages"]["segment"] = seg_counts
    # ⛔ SURFACE a systemic segment failure so the cursor HOLDS and the next run retries. Segment is
    # the sweep's primary purpose (Q1(b)); a row that failed to write must not advance the cursor
    # past it and look green — the exact silent-no-op the invalid-family regression caused.
    if seg_counts.get("errors"):
        summary["failures"].append(
            f"segment write failed for {seg_counts['errors']} of {len(rows)} new contact(s)")

    queues = queue_sizes()
    summary["queues"] = queues

    try:
        summary["report"] = write_report(basename, rows, resolve_stats, seg_counts, queues)
    except Exception as exc:
        summary["failures"].append(f"report: {exc}")

    # ⛔ CURSOR LAST, and only when nothing hard-failed. A failed register/closeness stage leaves the
    # cursor unmoved so the next run retries the whole (idempotent) chain against the same export.
    if not summary["failures"]:
        _write_cursor(basename, len(rows))
        summary["cursor"] = "advanced"
    else:
        summary["cursor"] = "held (a stage failed; next run retries)"
        summary["status"] = "partial"
    return summary


def main():
    ap = argparse.ArgumentParser(description="chain the new-contact onboarding scripts, idempotently")
    ap.add_argument("--force", action="store_true", help="re-run even if the export is unchanged")
    ap.add_argument("--no-resolve", action="store_true", help="skip the paid employer-resolution stage")
    ap.add_argument("--json", action="store_true", help="machine-readable summary to stdout")
    a = ap.parse_args()
    summary = sweep(force=a.force, resolve=not a.no_resolve)
    if a.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"new-contact sweep: {summary.get('status')} · "
              f"{summary.get('new_count', 0)} new · export {summary.get('export', '?')}")
        for f in summary.get("failures", []):
            print(f"  🔴 {f}")
        if summary.get("report"):
            print(f"  report: {summary['report']}")
    return 1 if summary.get("status") == "partial" else 0


if __name__ == "__main__":
    sys.exit(main())
