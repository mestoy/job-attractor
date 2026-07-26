#!/usr/bin/env python3
"""ingest_export.py — copy a LinkedIn export into the repo, without its email addresses.

WHY. The raw export usually lives only in ~/Downloads, which is not backed up, so a machine loss
means re-requesting it from LinkedIn. Keeping it in `documents/linkedin-exports/` makes the raw
input as durable as everything derived from it.

⛔ THE COLUMN THAT MUST NOT BE COMMITTED. LinkedIn's `Connections.csv` carries an `Email Address`
column alongside every connection's name, employer and title. `parse_network.py` states the rule for
its own output ("email addresses are NEVER written to the shared output, only counted"), and copying
the raw CSV into the repo by hand walks straight around it. This script replaces the address with a
boolean `Has Email` column. Nothing downstream loses anything: parse_network only ever asks
`has_email = bool(...)`, and that flag is scored at ZERO points, because an address in the export
turns out not to mean a usable address.

It also names the file by the EXPORT date so `find_export()` ranks it correctly, and refuses to
replace a newer export with an older one.

Usage:
  scripts/ingest_export.py <path to Connections.csv | export dir | export .zip>
  scripts/ingest_export.py <path> --force     # allow ingesting an OLDER export

Exit: 0 = ingested · 2 = nothing usable found · 3 = usage · 4 = refused (older than what we have)
"""
import csv
import datetime
import glob
import io
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
DEST_DIR = os.path.join(REPO, "documents", "linkedin-exports")

OUT_COLS = ["First Name", "Last Name", "URL", "Has Email", "Company", "Position", "Connected On"]
_NAME_DATE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")


def _read_connections(path):
    """(text, label) for a Connections.csv reachable via a file, a dir or a .zip."""
    if os.path.isdir(path):
        cand = os.path.join(path, "Connections.csv")
        if os.path.exists(cand):
            return open(cand, encoding="utf-8-sig", errors="ignore").read(), path
        return None, path
    if path.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as zf:
                for n in zf.namelist():
                    if n.rsplit("/", 1)[-1] == "Connections.csv":
                        return zf.read(n).decode("utf-8-sig", "ignore"), path
        except (IsADirectoryError, zipfile.BadZipFile, OSError):
            return None, path
        return None, path
    if os.path.exists(path):
        return open(path, encoding="utf-8-sig", errors="ignore").read(), path
    return None, path


def _export_date(label, rows):
    """Date for the filename: the date in the source name if present, else today.

    Deliberately NOT the newest connection date. The two differ (an export taken on the 21st can
    hold nothing newer than the 19th), and `parse_network._recorded_source_date()` compares against
    the EXPORT date recorded in warm-network.md's header. Naming by connection date would make a
    freshly ingested copy look older than its own source and trip the regression guard.
    """
    m = _NAME_DATE.search(os.path.basename(label or ""))
    if m:
        mm, dd, yyyy = (int(x) for x in m.groups())
        try:
            return datetime.date(yyyy, mm, dd)
        except ValueError:
            pass
    try:
        return datetime.date.fromtimestamp(os.path.getmtime(label))
    except Exception:
        return datetime.date.today()


def existing_newest():
    """Newest export date already ingested, by filename."""
    best = None
    for p in glob.glob(os.path.join(DEST_DIR, "Connections-*.csv")):
        m = _NAME_DATE.search(os.path.basename(p))
        if not m:
            continue
        mm, dd, yyyy = (int(x) for x in m.groups())
        try:
            d = datetime.date(yyyy, mm, dd)
        except ValueError:
            continue
        if best is None or d > best:
            best = d
    return best


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv[1:]
    if not args:
        print(__doc__.split("Usage:")[1].strip())
        return 3

    text, label = _read_connections(args[0])
    if not text:
        print(f"❌ no Connections.csv found at {args[0]}")
        return 2

    lines = text.split("\n")
    try:
        hi = next(i for i, l in enumerate(lines) if l.startswith("First Name"))
    except StopIteration:
        # LinkedIn prepends a 3-line "Notes:" preamble; a naive reader treats it as the header and
        # returns zero rows. parse_network hit this live and now exits 2 rather than writing an
        # empty network. Same guard here.
        print("❌ no 'First Name' header row — is this really a Connections.csv?")
        return 2
    preamble = "\n".join(lines[:hi]).strip("\n")
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[hi:]))))
    if not rows:
        print("❌ parsed 0 rows — refusing to ingest an empty export")
        return 2

    when = _export_date(label, rows)
    have = existing_newest()
    if have and when < have and not force:
        print(f"⛔ REFUSING: {when} is older than the export already ingested ({have}).")
        print("   Ingesting it would make the pipeline look newer than it is. Use --force to override.")
        return 4

    n_email = 0
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=OUT_COLS)
    w.writeheader()
    for r in rows:
        has = bool((r.get("Email Address") or "").strip())
        n_email += has
        w.writerow({"First Name": r.get("First Name", ""), "Last Name": r.get("Last Name", ""),
                    "URL": r.get("URL", ""), "Has Email": "yes" if has else "",
                    "Company": r.get("Company", ""), "Position": r.get("Position", ""),
                    "Connected On": r.get("Connected On", "")})

    os.makedirs(DEST_DIR, exist_ok=True)
    dest = os.path.join(DEST_DIR, f"Connections-{when.strftime('%m-%d-%Y')}.csv")
    open(dest, "w", encoding="utf-8").write(
        (preamble + "\n\n" if preamble else "") + buf.getvalue())

    print(f"✅ ingested {len(rows)} connections → {os.path.relpath(dest, REPO)}")
    print(f"   🔒 {n_email} email address(es) stripped; committed as a Has Email boolean")
    print("   next: python3 scripts/parse_network.py   then   "
          "python3 scripts/check_network_freshness.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
