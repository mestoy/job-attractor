#!/usr/bin/env python3
"""apply_findings_from_stream.py — BUG-218 follow-up: dispatch findings from the TRUSTED
wrapper's own shell, never the unattended agent's.

WHY (#87, follow-up finding 2026-08-22 in auto-sweep.sh's own header comment). Pattern-scoped
`Bash(python3 scripts/record_finding.py:*)` allow-patterns do NOT restrict the tool in headless
`-p` mode — a probe command outside the stated pattern ran with zero denial. So an injected
instruction from fetched content had unrestricted Bash during the run, which could call `git
push` directly and bypass the entire downstream `backup_baseline.py` publish gate. The fix:
the agent gets NO Bash at all (`--disallowedTools "Bash"`, the one thing verified to actually
block a tool here); it reports findings as plain text in its own stream output instead, and
THIS script — run by the wrapper's own shell, with the wrapper's own trust — parses that
stream and calls `record_finding.py`/`reconcile_findings.py` itself.

CONTRACT. The agent is instructed (via its TASK prompt) to print each verdict as a fenced
block:
    ```finding
    {"run": "...", "lane": "...", "company": "...", "verdict": "SURVIVOR|DROP|UNVERIFIED",
     "filter": "...", "evidence": "...", "remote": "...", "ownership": "...",
     "pm_req": "...", "comp": "...", "note": "..."}
    ```
one per candidate, inside its own assistant text (never a tool call — it has none). This
script reads the `claude -p --output-format stream-json` log, extracts every well-formed
`finding` block from `type: assistant` events, and — ONLY under `--apply` — shells out to
`record_finding.py` for each one, using the exact same flags a human would type. A malformed
block is skipped and reported, never guessed at. This script is itself part of the trust
boundary: it does NOT execute anything the agent's text asks for beyond the fixed set of
`record_finding.py`/`reconcile_findings.py` flags below — an injected instruction cannot make
it run an arbitrary command, because it has no code path that takes one.

THE SAME RULE FOR FILES (BUG-218 re-enable plan). The unattended agent has no Write or Edit either, so anything it
produces for a file is printed as a fenced block and written HERE, by the wrapper's own shell, into a FIXED target
with size and shape limits:
    ```report         the morning report        -> --report-out documents/state/auto-sweep-YYYY-MM-DD.md
    ```queue-entry    a review-ready queue row  -> --queue-append documents/outreach-queue.md   (at most 8 per run)
    ```metrics-line   one summary line          -> --metrics-append documents/outreach-metrics.md
The targets are checked against the repo root and, for the report, against the dated file-name pattern, so a block that
names some other path cannot write there: the path comes from the wrapper's command line, never from the agent's text.

Usage:
    python3 scripts/apply_findings_from_stream.py STREAM.jsonl              # dry run, prints
    python3 scripts/apply_findings_from_stream.py STREAM.jsonl --apply      # actually records
    python3 scripts/apply_findings_from_stream.py STREAM.jsonl --apply --reconcile
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import untrusted  # noqa: E402

REPORT_SOURCE = "unattended auto-sweep agent (web-derived)"
QUEUE_PROVENANCE = "SOURCE: unattended prep agent, web-derived, verify before build"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)

FINDING_BLOCK_RE = re.compile(r"```finding\s*\n(.*?)\n```", re.S)
REQUIRED_KEYS = ("run", "lane", "company", "verdict")
OPTIONAL_KEYS = ("filter", "evidence", "remote", "ownership", "pm_req", "comp", "note")
VALID_VERDICTS = ("SURVIVOR", "DROP", "UNVERIFIED", "DEFERRED")


def extract_findings(stream_path):
    """(findings, malformed_count) — findings is a list of dicts pulled from every
    well-formed ```finding block in an assistant text event. Never raises on a bad line;
    a stream is untrusted content and this function's job is to read it, not trust it."""
    findings = []
    malformed = 0
    with open(stream_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") != "assistant":
                continue
            msg = ev.get("message") or {}
            for block in msg.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "text":
                    continue
                for m in FINDING_BLOCK_RE.finditer(block.get("text", "")):
                    try:
                        row = json.loads(m.group(1))
                    except ValueError:
                        malformed += 1
                        continue
                    if not isinstance(row, dict) or not all(k in row for k in REQUIRED_KEYS):
                        malformed += 1
                        continue
                    if row.get("verdict") not in VALID_VERDICTS:
                        malformed += 1
                        continue
                    findings.append(row)
    return findings, malformed


REPORT_NAME_RE = re.compile(r"^auto-sweep-\d{4}-\d{2}-\d{2}\.md$")
MAX_REPORT_BYTES = 100_000
MAX_QUEUE_ENTRIES = 8
MAX_QUEUE_ENTRY_CHARS = 20_000
MAX_METRICS_CHARS = 400
BAD_ENTRY_MARKUP = re.compile(r"(?i)<\s*(script|iframe|object|embed)\b|javascript:|```")


def extract_blocks(stream_path, tag):
    """[raw text] of every ```<tag> fenced block in an assistant text event, in stream order. Never raises on a bad line:
    the stream is untrusted content and this function reads it, it does not trust it."""
    rx = re.compile(r"```" + re.escape(tag) + r"[ \t]*\n(.*?)\n```", re.S)
    out = []
    with open(stream_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") != "assistant":
                continue
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    out += [m.group(1) for m in rx.finditer(block.get("text", ""))]
    return out


def _inside(path, *rel):
    """True when `path` resolves to REPO/<rel...> exactly (or, with a dir rel, anywhere beneath it)."""
    real = os.path.realpath(path)
    want = os.path.realpath(os.path.join(REPO, *rel))
    return real == want or real.startswith(want + os.sep)


def _atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def write_report(stream_path, out_path):
    """Write the LAST ```report block to the dated report file. (ok, message)."""
    if not (_inside(out_path, "documents", "state") and REPORT_NAME_RE.match(os.path.basename(out_path))
            and os.path.dirname(os.path.realpath(out_path)) == os.path.realpath(os.path.join(REPO, "documents", "state"))):
        return False, "refused: --report-out must be documents/state/auto-sweep-YYYY-MM-DD.md inside the repo"
    blocks = extract_blocks(stream_path, "report")
    if not blocks:
        return False, "no report block in the stream, so no report was written"
    text = blocks[-1].strip("\n") + "\n"
    if "\x00" in text:
        return False, "refused: the report block holds a NUL byte"
    if len(text.encode("utf-8")) > MAX_REPORT_BYTES:
        return False, f"refused: the report block is over {MAX_REPORT_BYTES} bytes"
    if not text.strip():
        return False, "refused: the report block is empty"
    # The agent read web pages, so its report is evidence to evaluate and never an instruction (HARD-INVARIANTS).
    _atomic_write(out_path, untrusted.wrap(text, REPORT_SOURCE, limit=MAX_REPORT_BYTES) + "\n")
    return True, f"wrote the report to {os.path.relpath(out_path, REPO)}"


def valid_queue_entry(text):
    """(ok, why). A queue entry is one `### ` heading section marked STATUS: NEW, no new `#`/`##` heading, no fence or script."""
    lines = [l for l in text.split("\n")]
    first = next((l for l in lines if l.strip()), "")
    if not first.startswith("### "):
        return False, "does not start with a ### heading"
    if len(text) > MAX_QUEUE_ENTRY_CHARS:
        return False, "too long"
    if any(re.match(r"#{1,2}\s", l) for l in lines):
        return False, "opens a # or ## heading"
    if "\x00" in text or BAD_ENTRY_MARKUP.search(text):
        return False, "carries a fence, script or NUL"
    if not any(l.strip() == "STATUS: NEW" for l in lines):
        return False, "has no STATUS: NEW line"
    for l in lines:
        m = re.match(r"\s*STATUS:\s*(\S+)", l)
        if m and m.group(1) != "NEW":
            return False, "names a status other than NEW"
    return True, ""


def append_queue(stream_path, queue_path):
    if not _inside(queue_path, "documents", "outreach-queue.md"):
        return False, "refused: --queue-append must be documents/outreach-queue.md inside the repo"
    blocks = extract_blocks(stream_path, "queue-entry")
    ok_blocks, refused = [], 0
    for b in blocks:
        good, _why = valid_queue_entry(b.strip("\n"))
        if good and len(ok_blocks) < MAX_QUEUE_ENTRIES:
            body = untrusted.defang(b.strip("\n"), limit=MAX_QUEUE_ENTRY_CHARS, keep_newlines=True)
            head, _, rest = body.partition("\n")
            ok_blocks.append(head + "\n" + QUEUE_PROVENANCE + ("\n" + rest if rest else ""))
        else:
            refused += 1
    if ok_blocks:
        with open(queue_path, "a", encoding="utf-8") as fh:
            for b in ok_blocks:
                fh.write("\n" + b + "\n")
    return True, f"appended {len(ok_blocks)} queue entr(y/ies); {refused} queue-entry block(s) refused"


def append_metrics(stream_path, metrics_path):
    if not _inside(metrics_path, "documents", "outreach-metrics.md"):
        return False, "refused: --metrics-append must be documents/outreach-metrics.md inside the repo"
    blocks = extract_blocks(stream_path, "metrics-line")
    if not blocks:
        return False, "no metrics-line block in the stream"
    raw = blocks[-1].strip("\n")
    if "\n" in raw or "\x00" in raw or not raw.strip() or len(raw) > MAX_METRICS_CHARS:
        return False, f"refused: the metrics line must be one non-empty line of at most {MAX_METRICS_CHARS} characters"
    line = untrusted.defang(raw, limit=MAX_METRICS_CHARS * 2)
    with open(metrics_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return True, "appended the metrics line"


def apply_finding(finding, record_finding_path):
    """Shells to record_finding.py with a fixed, known flag set — never anything the
    finding dict didn't put in one of REQUIRED_KEYS/OPTIONAL_KEYS. Returns the exit code."""
    cmd = [
        sys.executable, record_finding_path,
        "--run", str(finding["run"]),
        "--lane", str(finding["lane"]),
        "--company", str(finding["company"]),
        "--verdict", str(finding["verdict"]),
    ]
    for key in OPTIONAL_KEYS:
        val = finding.get(key)
        if val is not None and str(val).strip() != "":
            cmd += [f"--{key.replace('_', '-')}", str(val)]
    result = subprocess.run(cmd, cwd=REPO)
    return result.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stream", help="path to the claude -p --output-format stream-json log")
    ap.add_argument("--apply", action="store_true", help="actually call record_finding.py")
    ap.add_argument("--reconcile", action="store_true",
                     help="after applying, also run reconcile_findings.py")
    ap.add_argument("--report-out", default=None, help="write the last ```report block to this documents/state/auto-sweep-DATE.md")
    ap.add_argument("--queue-append", default=None, help="append valid ```queue-entry blocks to documents/outreach-queue.md")
    ap.add_argument("--metrics-append", default=None, help="append the last ```metrics-line block to documents/outreach-metrics.md")
    args = ap.parse_args()

    failures = 0
    for flag, fn, path in (("--report-out", write_report, args.report_out),
                           ("--queue-append", append_queue, args.queue_append),
                           ("--metrics-append", append_metrics, args.metrics_append)):
        if path:
            ok, msg = fn(args.stream, path)
            print(("✅ " if ok else "🔴 ") + f"{flag}: {msg}")
            failures += 0 if ok else 1
    if args.report_out or args.queue_append or args.metrics_append:
        if not args.apply and not (args.reconcile):
            return 1 if failures else 0

    findings, malformed = extract_findings(args.stream)
    print(f"found {len(findings)} well-formed finding(s), {malformed} malformed block(s) skipped")

    if not args.apply:
        for f in findings:
            print(f"  DRY-RUN would record: {f.get('verdict')} {f.get('company')!r} "
                  f"[{f.get('lane')}] run={f.get('run')}")
        return 0

    record_finding_path = os.path.join(HERE, "record_finding.py")
    for f in findings:
        rc = apply_finding(f, record_finding_path)
        if rc != 0:
            failures += 1
            print(f"⚠️  record_finding.py exited {rc} for {f.get('company')!r}", file=sys.stderr)

    if args.reconcile:
        reconcile_path = os.path.join(HERE, "reconcile_findings.py")
        rc = subprocess.run([sys.executable, reconcile_path], cwd=REPO).returncode
        if rc != 0:
            failures += 1
            print(f"⚠️  reconcile_findings.py exited {rc}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
