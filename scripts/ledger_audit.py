#!/usr/bin/env python3
"""ledger_audit.py -- READ ONLY. Was a signed ledger row edited after it was written, which field, and was it
re-signed?

WHY (kit issue #149). `company` is one of the eight signed fields (ledger_keys.MAC_FIELDS). A partner's own session
edited that field across a ledger and re-signed every row. Leave the old signature and every touched row stops
verifying. Re-sign and the ledger asserts an authorization for content nobody approved. Nothing said which had
happened, and it took days to tell. Git already holds the earlier versions of the ledger, so this reads them.

    python3 scripts/ledger_audit.py --against-git [--repo DIR] [--ledger REL] [--keyfile PATH] [--limit N] [--json]

WHAT IT REPORTS, per row, as counts by class (never a verdict):
    OK                  the row is exactly as the first commit that held it, or a later append
    EDITED_AFTER_WRITE  a signed field changed and the mac did not, so the row no longer verifies
    RESIGNED            the mac changed too. `verifies_now` says whether the new mac verifies under your key:
                        a True here is the dangerous case, because the ledger now vouches for changed content
    UNWITNESSED         in no commit yet (a new uncommitted row), so git can say nothing about it
    REMOVED             a committed row that is no longer in the file

OK IS NOT SOUND. A row that was written as captured text, and never touched, reads OK: correctly, and uselessly for
the question "was this a decision at all". The audit answers "altered after it was written", nothing else.

THE LIMITS, stated once. It protects only a ledger in a repo with a remote (the output says when there is none), and
a history rewrite defeats it, loudly. Granularity is the backup cadence. This catches an accident or a clumsy edit. A determined actor with the same HOME can also
rewrite the history it reads. A row written and edited between two commits is invisible, so every answer is
"as of the first commit that held the row", never "as written". Rows are matched one to one by content, never by
(ts, session): 821 real rows share that pair.

NOTHING HERE EVER SIGNS OR REPAIRS. It opens the ledger, the key and git read only, and a test scans this file for
any write. A guard that repairs by re-signing manufactures the authorization it exists to protect.
"""
import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys

MAC_FIELDS = ("ts", "session", "question", "header", "answer", "ruling", "company", "source")
CLASSES = ("OK", "EDITED_AFTER_WRITE", "RESIGNED", "UNWITNESSED", "REMOVED")
BAD = ("EDITED_AFTER_WRITE", "RESIGNED", "REMOVED")
def _default_keyfile():
    """Where the signing key is, without inventing a place: the JOBKIT_LEDGER_KEYFILE variable, else the kit's own
    kit_config.LEDGER_KEYFILE when this runs inside a kit, else the first of the two known homes that exists. The
    kit keeps its key at ~/.jobsearch-ledger-key and that path must never move (a moved key orphans every ruling)."""
    env = os.environ.get("JOBKIT_LEDGER_KEYFILE")
    if env:
        return os.path.expanduser(env)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import kit_config
        cfg = getattr(kit_config, "LEDGER_KEYFILE", "")
        if cfg:
            return os.path.expanduser(cfg)
    except Exception:
        pass
    for cand in ("~/.claude/.jobsearch-ledger-key", "~/.jobsearch-ledger-key"):
        if os.path.exists(os.path.expanduser(cand)):
            return os.path.expanduser(cand)
    return os.path.expanduser("~/.jobsearch-ledger-key")


DEFAULT_KEYFILE = _default_keyfile()
DEFAULT_LEDGER = os.path.join("documents", "decision-ledger.jsonl")


def load_key(path):
    """The key bytes, or None when it cannot be read. Never creates anything."""
    try:
        with open(os.path.expanduser(path), "rb") as fh:
            data = fh.read().strip()
    except OSError:
        return None
    return data or None


def _mac_of(row, key):
    payload = json.dumps({f: row.get(f, "") for f in MAC_FIELDS}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _canon(row):
    """Identity of a row: the eight signed fields and the mac. `kid` and anything else is outside the signature."""
    return tuple([str(row.get(f, "")) for f in MAC_FIELDS] + [str(row.get("mac", ""))])


def _parse(line):
    line = line.strip()
    if not line:
        return None, False
    try:
        row = json.loads(line)
    except ValueError:
        return None, True
    return (row, False) if isinstance(row, dict) else (None, True)


def _git(repo, *args):
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, errors="replace")
    return done.returncode, done.stdout


def _changed_fields(old, new):
    return [f for f in MAC_FIELDS if str(old.get(f, "")) != str(new.get(f, ""))]


def _pair(removed, added):
    """One to one: each removed row with the added row that shares its ts and matches most fields. Returns
    (pairs, unpaired_removed, unpaired_added). Identical rows on both sides cancel first (a moved line)."""
    rem = list(removed)
    add = list(added)
    for r in list(rem):
        for a in add:
            if _canon(a) == _canon(r):
                rem.remove(r)
                add.remove(a)
                break
    pairs = []
    for r in list(rem):
        best, best_score = None, -1
        for a in add:
            if str(a.get("ts", "")) != str(r.get("ts", "")):
                continue
            score = sum(1 for f in MAC_FIELDS if str(a.get(f, "")) == str(r.get(f, "")))
            if score > best_score:
                best, best_score = a, score
        if best is not None:
            pairs.append((r, best))
            rem.remove(r)
            add.remove(best)
    return pairs, rem, add


def _history(repo, rel):
    """[(commit, removed_rows, added_rows)] oldest first, from the diff of each commit that touched the ledger."""
    code, out = _git(repo, "log", "--reverse", "--format=COMMIT:%H", "-p", "-U0", "--no-color", "--", rel)
    if code != 0:
        return []
    commits, cur = [], None
    for line in out.split("\n"):
        if line.startswith("COMMIT:"):
            cur = [line[7:], [], []]
            commits.append(cur)
        elif cur is not None and line.startswith("+{"):
            row, _bad = _parse(line[1:])
            if row is not None:
                cur[2].append(row)
        elif cur is not None and line.startswith("-{"):
            row, _bad = _parse(line[1:])
            if row is not None:
                cur[1].append(row)
    return [(c, r, a) for c, r, a in commits]


def _rows_of(text):
    rows, damaged = [], 0
    for line in text.split("\n"):
        row, bad = _parse(line)
        if bad:
            damaged += 1
        elif row is not None:
            rows.append(row)
    return rows, damaged


def audit_against_git(repo, rel=DEFAULT_LEDGER, key=None):
    """The report: {"counts": {class: n}, "findings": [...], "damaged_lines": n, "commits_read": n}."""
    path = os.path.join(repo, rel)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            current, damaged = _rows_of(fh.read())
    except OSError:
        current, damaged = [], 0

    origin = {}    # canon -> first commit that held the row
    edited = {}    # canon of the row as it stands -> {"root": earliest row, "commit": c}
    rows_by_canon = {}
    removed_events = []
    history = _history(repo, rel)
    for commit, removed, added in history:
        pairs, rem_left, add_left = _pair(removed, added)
        for r, a in pairs:
            root = edited.get(_canon(r), {}).get("root", r)
            edited[_canon(a)] = {"root": root, "commit": commit}
            origin.setdefault(_canon(a), commit)
        for a in add_left:
            origin.setdefault(_canon(a), commit)
        for r in rem_left:
            removed_events.append((commit, r))

    # The working tree against HEAD is one more step, so an uncommitted edit is seen too.
    code, head_text = _git(repo, "show", "HEAD:" + rel.replace(os.sep, "/"))
    if code == 0:
        head_rows, _ = _rows_of(head_text)
        head_c = {}
        for r in head_rows:
            head_c[_canon(r)] = head_c.get(_canon(r), 0) + 1
        cur_c = {}
        for r in current:
            cur_c[_canon(r)] = cur_c.get(_canon(r), 0) + 1
        removed = []
        for r in head_rows:
            if cur_c.get(_canon(r), 0) < head_c[_canon(r)]:
                head_c[_canon(r)] -= 1
                removed.append(r)
        added = []
        for r in current:
            if head_c.get(_canon(r), 0) < cur_c[_canon(r)]:
                cur_c[_canon(r)] -= 1
                added.append(r)
        pairs, rem_left, add_left = _pair(removed, added)
        for r, a in pairs:
            root = edited.get(_canon(r), {}).get("root", r)
            edited[_canon(a)] = {"root": root, "commit": "WORKTREE"}
            origin.setdefault(_canon(a), "WORKTREE")
        for r in rem_left:
            removed_events.append(("WORKTREE", r))
    for r in current:
        rows_by_canon[_canon(r)] = r

    counts = {c: 0 for c in CLASSES}
    findings = []
    for row in current:
        c = _canon(row)
        ev = edited.get(c)
        if ev is not None:
            root = ev["root"]
            fields = _changed_fields(root, row)
            klass = "RESIGNED" if str(root.get("mac", "")) != str(row.get("mac", "")) else "EDITED_AFTER_WRITE"
            counts[klass] += 1
            verifies = None
            if key:
                verifies = bool(row.get("mac")) and hmac.compare_digest(str(row.get("mac", "")), _mac_of(row, key))
            findings.append({"class": klass, "ts": row.get("ts", ""), "fields": fields, "commit": ev["commit"],
                             "verifies_now": verifies, "company_now": row.get("company", ""),
                             "company_before": root.get("company", "")})
        elif c in origin and origin[c] != "WORKTREE":
            counts["OK"] += 1
        else:
            counts["UNWITNESSED"] += 1
    present = {_canon(r) for r in current}
    for commit, r in removed_events:
        if _canon(r) in present:
            continue
        counts["REMOVED"] += 1
        findings.append({"class": "REMOVED", "ts": r.get("ts", ""), "fields": [], "commit": commit,
                         "verifies_now": None, "company_now": "", "company_before": r.get("company", "")})
    return {"counts": counts, "findings": findings, "damaged_lines": damaged, "commits_read": len(history)}


def protection_line(repo, rel=DEFAULT_LEDGER):
    """(protected, one plain line). The audit reads git history, so the ledger is covered only when it is inside a git
    repository, is tracked by it, and the repository has a remote a local rewrite cannot reach. A doctor prints this
    line so nobody assumes cover they do not have."""
    code, out = _git(repo, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out.strip() != "true":
        return False, ("NOT PROTECTED: %s is not under version control, so there is no history to audit and nothing "
                       "can show a later edit." % repo)
    code, out = _git(repo, "ls-files", "--error-unmatch", rel.replace(os.sep, "/"))
    if code != 0:
        return False, ("NOT PROTECTED: %s is not tracked by git (it may be ignored), so its history is not kept."
                       % rel)
    code, out = _git(repo, "remote")
    names = [x for x in out.split() if x] if code == 0 else []
    if not names:
        return False, ("PARTLY PROTECTED: %s is tracked, but the repository has no remote, so a local rewrite of git "
                       "would erase the evidence." % rel)
    return True, "protected: %s is tracked and the repository has a remote (%s)." % (rel, ", ".join(names))


def _remote_line(repo):
    code, out = _git(repo, "remote")
    names = [x for x in out.split() if x] if code == 0 else []
    if names:
        return "remote: %s (history a later rewrite would have to force-push to hide)" % ", ".join(names)
    return ("remote: NONE. Without a remote this history protects nothing: a local rewrite of git would erase "
            "the evidence this audit reads.")


def _print(report, limit, repo=None):
    print("READ THIS FIRST: OK means the row is unchanged since the first commit that held it. It does NOT mean the "
          "row was a real decision, or that the ledger is sound. A row written as captured text reads OK.")
    if repo:
        print(_remote_line(repo))
    print("ledger rows by class (as of the first commit that held each row, never 'as written'):")
    for c in CLASSES:
        print("  %-19s %d" % (c, report["counts"][c]))
    print("  damaged lines       %d" % report["damaged_lines"])
    print("commits read: %d" % report["commits_read"])
    shown = report["findings"][:limit]
    for f in shown:
        print("- %s ts=%s fields=%s commit=%s verifies_now=%s before=%r now=%r" % (
            f["class"], f["ts"], ",".join(f["fields"]) or "(none: mac only)", str(f["commit"])[:10],
            f["verifies_now"], f["company_before"], f["company_now"]))
    if len(report["findings"]) > len(shown):
        print("... and %d more (raise --limit, or use --json)" % (len(report["findings"]) - len(shown)))
    if report["findings"] and any(f["class"] == "RESIGNED" and f["verifies_now"] for f in report["findings"]):
        print("NOTE: a RESIGNED row that verifies now vouches for content that changed after it was written.")
    print("This is evidence by class. It does not say the rest of the ledger is sound: it cannot see a row written "
          "and edited between two commits.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only audit of the decision ledger against git history.")
    ap.add_argument("--against-git", action="store_true", help="compare the ledger with its committed versions")
    ap.add_argument("--repo", default=os.getcwd())
    ap.add_argument("--ledger", default=DEFAULT_LEDGER, help="path of the ledger relative to --repo")
    ap.add_argument("--keyfile", default=DEFAULT_KEYFILE)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--protection", action="store_true",
                    help="print one line saying whether this ledger has any history-based protection, and exit 1 if not")
    args = ap.parse_args(argv)
    if args.protection:
        ok, line = protection_line(args.repo, args.ledger)
        print(line)
        return 0 if ok else 1
    if not args.against_git:
        ap.error("nothing to do: pass --against-git or --protection")
    key = load_key(args.keyfile)
    report = audit_against_git(args.repo, args.ledger, key=key)
    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        if key is None:
            print("key not readable at %s, so signatures were not tested (verifies_now is None)." % args.keyfile)
        _print(report, args.limit, args.repo)
    return 1 if any(report["counts"][c] for c in BAD) else 0


if __name__ == "__main__":
    sys.exit(main())
