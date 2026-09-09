#!/usr/bin/env python3
"""kit_vendor_sync.py — bring the kit's files up to date WITHOUT ever asking git to relate your
history to the kit's.

WHY THIS EXISTS (BUG-040). `Update Kit.command` reaches the kit with `git pull --ff-only`, and when
that cannot fast-forward it historically fell to `git reset --hard "$upstream"`. On a clone whose
history is UNRELATED to the kit's — which is exactly what a partner has after the kit's history was
rebuilt, or after they committed their own fixes on top — the reset deletes the partner's own commits.
A circuit breaker in `Update Kit.command` now STOPS that path so nothing is destroyed, but stopping is
not the same as syncing: the partner is then stuck on an old kit with no way forward.

This is the replacement mechanism the circuit breaker was holding the door for. It NEVER runs
pull / merge / reset / rebase in the partner's repo, so the two histories never have to relate at all.
It fetches the kit read-only, then copies the kit's CURRENT version of each KIT-OWNED file into place
one file at a time. The only git verbs it runs in the partner's own repo are `tag`, `add`, `commit`
and `bundle` — none of which can delete a commit. Concretely, it guarantees:

  * Your private work is never touched. `documents/` and `scripts/kit_config.py` are git-ignored and
    are explicitly protected here too, belt and suspenders.
  * Your own edits to a kit file are never lost. Before the kit's version of a file lands, your copy
    is saved to `documents/.superseded/<timestamp>/` (the same place `Update Kit.command` and
    `install.sh` already use), so you can diff and reconcile. Undo saves your uncommitted edits too.
  * The whole sync is reversible. Before it changes anything it tags your exact pre-sync HEAD as
    `kit-sync-pre-<timestamp>` and writes a full `--all` bundle next to the backup. `Undo Kit
    Sync.command` restores that state.
  * It works no matter how your history relates to the kit's — behind, diverged with your own
    commits, or entirely unrelated — because it operates on FILES, not on history.
  * It ONLY ever adds or updates kit files; it never deletes one. If the kit dropped a file upstream,
    yours stays and is named in the report, so nothing you have vanishes silently.

The ancestry the old path got wrong is still computed here, but only to TELL you what your situation
is and to choose the wording, never to decide whether it is safe to overwrite your commits — that
answer is always "back it up first, then never destroy it".

Usage:
    kit_vendor_sync.py [--repo DIR] [--dry-run] [--undo] [--json]
Exit:
    0 = synced (or already current) · 1 = nothing done, a precondition failed · 2 = partial, see report
"""
import argparse
import datetime as _dt
import json
import os
import shutil
import tempfile
import subprocess
import sys

# Files that are the PARTNER's, never the kit's. They are git-ignored so they should never appear in
# the kit's tracked tree anyway; this list is the second guard, so a mistake upstream (a private path
# accidentally tracked) can still never let this script overwrite a partner's identity or documents.
PROTECTED_PREFIXES = (
    "documents/",
    "scripts/kit_config.py",
    ".superseded/",
)
PROTECTED_EXACT = frozenset({"scripts/kit_config.py"})

# Files the kit SEEDS once and the partner WRITES from then on. Kit-owned by the manifest, partner-
# written in practice: the changelog is the partner's own dated story of their pipeline. A sync
# adds it when absent and never replaces it once present (kit #80, third comment: a sync dropped 14
# dated lines of a partner's log).
PARTNER_ONCE_PRESENT = frozenset({"JOB-ATTRACTOR-CHANGELOG.md"})

# The subject prefix commit_sync() writes. A commit that does NOT start with it and touches a
# kit-owned file is the partner's own work on that file, which is what the local-edit guard and
# the clobber audit both look for.
KIT_SYNC_COMMIT_PREFIX = "Kit sync "

KIT_CANONICAL = os.environ.get("JOBKIT_CANONICAL", "mestoy/job-attractor-kit")

# Plain-language text for each precondition failure, keyed by a short error code so render() can turn
# a machine reason into a sentence a non-technical person can act on.
_ERROR_TEXT = {
    "not_a_clone": "This folder isn't a kit installed by the setup script, so there's nothing to "
                   "sync. Re-run the kit installer, then try again.",
    "no_remote":   "This kit copy has no link to the published kit, so it can't check for updates. "
                   "Send this message to the kit maintainer.",
    "offline":     "Couldn't reach the internet to check for kit updates. Nothing was changed — "
                   "please reconnect and try again.",
    "no_kit_ref":  "The published kit was reached, but its main branch couldn't be found. This copy "
                   "may be linked to the wrong place — send this message to the kit maintainer.",
    "commit_failed": "The kit's files were copied onto your computer, but saving them as a checkpoint "
                     "failed, so the update isn't finished. Your own work is untouched. Run \"Undo Kit "
                     "Sync\" to put the replaced files back.",
    "partial":     "Some kit files could not be written and were left exactly as they were. Anything "
                   "that did copy is saved and can be undone. Nothing of yours was destroyed.",
    "none_written": "None of the kit's files could be written, so nothing changed at all. Your own "
                    "work is untouched. This is usually a file-permission problem — send this message "
                    "to the kit maintainer.",
}


def _run(args, repo, text=True):
    return subprocess.run(args, cwd=repo, text=text,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _git(repo, *args):
    return _run(["git", *args], repo)


def _out(repo, *args):
    p = _git(repo, *args)
    return p.stdout.strip() if p.returncode == 0 else ""


def is_git_repo(repo):
    return _git(repo, "rev-parse", "--is-inside-work-tree").returncode == 0


# ─────────────────────────────────────────────────────────────────────────────────────────────────
#  KIT REMOTE DETECTION — same doctrine as Update Kit.command §2: never assume `origin`, prefer the
#  canonical owner+name, then a kit-named remote that is NOT the current tracking remote, then origin.
# ─────────────────────────────────────────────────────────────────────────────────────────────────
def find_kit_remote(repo):
    remotes = [r for r in _out(repo, "remote").splitlines() if r]
    if not remotes:
        return ""
    track = _out(repo, "rev-parse", "--abbrev-ref", "@{upstream}")
    track_remote = track.split("/", 1)[0] if "/" in track else ""
    kit_named = ""
    for r in remotes:
        url = _out(repo, "remote", "get-url", r)
        if KIT_CANONICAL in url:
            return r
        if "job-attractor-kit" in url:
            if not kit_named or (kit_named == track_remote and r != track_remote):
                kit_named = r
    if kit_named:
        return kit_named
    return "origin" if "origin" in remotes else remotes[0]


def kit_ref(repo, remote):
    track = _out(repo, "rev-parse", "--abbrev-ref", "@{upstream}")
    if track.startswith(remote + "/") and _git(repo, "rev-parse", "--verify", track).returncode == 0:
        return track
    for cand in (f"{remote}/main", f"{remote}/master"):
        if _git(repo, "rev-parse", "--verify", cand).returncode == 0:
            return cand
    head = _out(repo, "rev-parse", "--abbrev-ref", f"{remote}/HEAD")
    return head or f"{remote}/main"


# ─────────────────────────────────────────────────────────────────────────────────────────────────
#  ANCESTRY CORE — DIAGNOSTIC ONLY. The sync copies files regardless, backing up first.
#    up_to_date  HEAD == kit_ref.
#    behind      HEAD is an ancestor of kit_ref, carries nothing kit_ref lacks (a plain ff would work).
#    diverged    shares a merge-base but each has commits the other lacks (partner-with-own-fixes).
#    unrelated   no merge-base at all (the stranded clone after an upstream history rebuild).
#  local_only / upstream_only are exact `git rev-list --count` deltas.
# ─────────────────────────────────────────────────────────────────────────────────────────────────
def classify_ancestry(repo, head, ref):
    def count(rng):
        p = _git(repo, "rev-list", "--count", rng)
        try:
            return int(p.stdout.strip()) if p.returncode == 0 else 0
        except ValueError:
            return 0

    head_sha = _out(repo, "rev-parse", head)
    ref_sha = _out(repo, "rev-parse", ref)
    if not head_sha:
        state = "empty"                # no commits yet — a fresh seed, nothing of the partner's exists
        return {"state": state, "local_only": 0, "upstream_only": 0,
                "has_merge_base": False, "head": "", "ref": ref_sha}
    has_base = _git(repo, "merge-base", head, ref).returncode == 0
    local_only = count(f"{ref}..{head}")
    upstream_only = count(f"{head}..{ref}")
    if head_sha == ref_sha:
        state = "up_to_date"
    elif not has_base:
        state = "unrelated"
    elif local_only == 0:
        state = "behind"
    else:
        state = "diverged"
    return {"state": state, "local_only": local_only, "upstream_only": upstream_only,
            "has_merge_base": has_base, "head": head_sha, "ref": ref_sha}


# ─────────────────────────────────────────────────────────────────────────────────────────────────
#  KIT-OWNED FILE SET — every path tracked in the kit ref, minus protected private paths. `-z` keeps
#  non-ASCII / special-character paths intact (without it git quote-escapes them and they get skipped).
# ─────────────────────────────────────────────────────────────────────────────────────────────────
def _protected(path):
    if path in PROTECTED_EXACT:
        return True
    return any(path == p or path.startswith(p) for p in PROTECTED_PREFIXES)


def kit_owned_files(repo, ref):
    p = _git(repo, "ls-tree", "-r", "-z", "--name-only", ref)
    if p.returncode != 0:
        return []
    return [x for x in p.stdout.split("\0") if x and not _protected(x)]


def _entry_mode(repo, ref, path):
    """The 6-digit git mode for `path` at `ref` ('100644', '100755', '120000' symlink), or ''."""
    p = subprocess.run(["git", "ls-tree", "-z", ref, "--", path], cwd=repo,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0 or not p.stdout:
        return ""
    return p.stdout.split()[0] if p.stdout.split() else ""


def _kit_blob(repo, ref, path):
    p = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.stdout if p.returncode == 0 else None


def _read(path):
    try:
        if os.path.islink(path):
            return ("\0symlink\0" + os.readlink(path)).encode()   # compare links by target, not content
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _differs(repo, ref, rel, dest):
    """True if the partner's copy of `rel` differs from the kit's, accounting for symlinks."""
    mode = _entry_mode(repo, ref, rel)
    if mode == "120000":
        target = _kit_blob(repo, ref, rel)
        if target is None:
            return False
        want = ("\0symlink\0" + target.decode("utf-8", "replace")).encode()
        return _read(dest) != want
    return _read(dest) != _kit_blob(repo, ref, rel)


# ─────────────────────────────────────────────────────────────────────────────────────────────────
#  THE LOCAL-EDIT GUARD (kit #80, Matthew, 2026-09-05 and 2026-09-08).
#
#  The old plan was "every kit-owned file whose bytes differ from the NEW kit version gets replaced,
#  backed up, and committed". That is silent by construction: a partner's committed fix to a kit
#  script differs from the new kit version too, so it was replaced with the same one-line outcome
#  as a routine update. Five real fixes on one install were dead for a week, one of them a screening
#  gate; a sixth was reverted forty minutes after it was committed. The commit stayed in history, so
#  nothing ordinary could tell.
#
#  The information that separates "behind" from "edited" was always there: the LAST kit version of
#  the file. A partner copy that equals the last kit version is merely behind, and replacing it is
#  right. A partner copy that differs from BOTH the last kit version and the new one carries the
#  partner's own work, and the file is HELD: left exactly as it is, named in the report with the
#  commits that touched it, never replaced without being asked. `--merge` tries a three-way merge
#  first and holds only on conflict; `--replace-local` restores the old behaviour for named files.
#
#  Where does "the last kit version" come from? Two places, in order: the ref the previous sync
#  recorded in its manifest (works for the unrelated clone, which is the common partner shape), then
#  the merge-base with the kit (works for a real clone). A first-ever sync of an unrelated clone has
#  neither, so it behaves as before, backup and replace, and says so per file.
# ─────────────────────────────────────────────────────────────────────────────────────────────────
def last_synced_ref(repo):
    """The kit ref the most recent sync vendored, if its objects are still readable here."""
    man = latest_manifest(repo) or {}
    # The manifest's `ref` is a NAME (origin/main), which now points at the newest kit, not the
    # one that was vendored. The sha of that one is in the ancestry block the same sync wrote.
    sha = (man.get("ancestry") or {}).get("ref") or man.get("ref_sha") or ""
    if not sha:
        return ""
    ok = _out(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    return ok or ""


def _merge_base(repo, ref):
    p = _git(repo, "merge-base", "HEAD", ref)
    return p.stdout.strip() if p.returncode == 0 else ""


def baseline_blob(repo, rel, last_ref, base):
    """The last kit version of `rel` this partner received, or None when there is no way to know."""
    for r in (last_ref, base):
        if r:
            b = _kit_blob(repo, r, rel)
            if b is not None:
                return b
    return None


def local_commits_touching(repo, rel, limit=8):
    """The partner's OWN commits that touched `rel`: every commit in HEAD's history on that path
    whose subject is not a Kit sync. Newest first, `limit` at most."""
    p = _git(repo, "log", f"--max-count={limit * 4}", "--format=%h%x09%s", "--", rel)
    if p.returncode != 0:
        return []
    out = []
    for line in p.stdout.splitlines():
        sha, _, subject = line.partition("\t")
        if subject.startswith(KIT_SYNC_COMMIT_PREFIX):
            continue
        out.append({"sha": sha, "subject": subject})
        if len(out) >= limit:
            break
    return out


def three_way_merge(base, ours, theirs):
    """`git merge-file` on three blobs. Returns (merged_bytes, clean). Conflicts leave markers in the
    output and clean=False; the caller must NOT write that file."""
    d = tempfile.mkdtemp(prefix="kit-sync-merge-")
    try:
        paths = {}
        for name, data in (("base", base), ("ours", ours), ("theirs", theirs)):
            paths[name] = os.path.join(d, name)
            with open(paths[name], "wb") as fh:
                fh.write(data)
        p = subprocess.run(["git", "merge-file", "-p", "-L", "yours", "-L", "last kit", "-L", "new kit",
                            paths["ours"], paths["base"], paths["theirs"]],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.stdout, p.returncode == 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def classify_plan(repo, ref, files, last_ref, base, merge=False, replace_local=None):
    """Sort every kit-owned file that differs from the kit into what the sync will do with it.
    Returns (replace, content, notes): `replace` is the list vendor() may write, `content` holds
    merged bytes for files that merge cleanly, `notes` is one dict per file that is NOT simply
    replaced (held / merged / kept / no-baseline), for the report."""
    replace_local = set(replace_local or [])
    replace_all = "all" in replace_local
    replace, content, notes = [], {}, []
    for rel in files:
        dest = os.path.join(repo, rel)
        if not _differs(repo, ref, rel, dest):
            continue
        if not os.path.lexists(dest):
            replace.append(rel)                                   # a new kit file: always added
            continue
        if rel in PARTNER_ONCE_PRESENT:
            notes.append({"file": rel, "action": "kept", "why": "partner-written once present"})
            continue
        if _entry_mode(repo, ref, rel) == "120000" or os.path.islink(dest):
            replace.append(rel)                                   # symlinks carry no partner edits
            continue
        ours = _read(dest)
        theirs = _kit_blob(repo, ref, rel)
        baseline = baseline_blob(repo, rel, last_ref, base)
        if baseline is None:
            replace.append(rel)
            notes.append({"file": rel, "action": "replaced", "why": "no last kit version to compare "
                          "against (first sync); your copy is backed up"})
            continue
        if ours == baseline:
            replace.append(rel)                                   # merely behind: a clean update
            continue
        commits = local_commits_touching(repo, rel)
        if replace_all or rel in replace_local:
            replace.append(rel)
            notes.append({"file": rel, "action": "replaced", "why": "--replace-local",
                          "commits": commits})
            continue
        if merge and theirs is not None:
            merged, clean = three_way_merge(baseline, ours, theirs)
            if clean:
                replace.append(rel)
                content[rel] = merged
                notes.append({"file": rel, "action": "merged", "commits": commits,
                              "why": "your edit and the kit's update merged cleanly; read the result"})
                continue
            notes.append({"file": rel, "action": "held", "commits": commits,
                          "why": "your edit conflicts with the kit's update; left exactly as it was"})
            continue
        notes.append({"file": rel, "action": "held", "commits": commits,
                      "why": "your copy carries your own edit; left exactly as it was"})
    return replace, content, notes


def check_clobber(repo, ref):
    """Retrospective audit (kit #80, ask 2): for every kit-owned file, list the partner's own commits
    that touched it and test whether each commit's change is STILL in the working copy
    (`git show <c> -- <file> | git apply --check --reverse`). A change that no longer reverse-applies
    MAY have been replaced by a sync, or the kit may have upstreamed it in different wording, so
    the verdict is "go look", never "reverted"."""
    findings = []
    for rel in kit_owned_files(repo, ref):
        if not os.path.isfile(os.path.join(repo, rel)):
            continue
        for c in local_commits_touching(repo, rel, limit=20):
            show = _git(repo, "show", "--format=", c["sha"], "--", rel)
            if show.returncode != 0 or not show.stdout.strip():
                continue
            chk = subprocess.run(["git", "apply", "--check", "--reverse", "-"], cwd=repo,
                                 input=show.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True)
            findings.append({"file": rel, "sha": c["sha"], "subject": c["subject"],
                             "live": chk.returncode == 0})
    return {"ok": True, "repo": repo, "ref": ref, "findings": findings,
            "suspect": [f for f in findings if not f["live"]]}


def render_clobber(report):
    sus = report.get("suspect") or []
    n = len(report.get("findings") or [])
    lines = [f"▶  Clobber audit: {_n(n, 'local commit')} of yours touch kit-owned files."]
    if not sus:
        lines.append("✅  Every one of them is still present in the working copy.")
        return "\n".join(lines)
    lines.append(f"⚠  {_n(len(sus), 'change')} may no longer be live. Go look before re-applying any of "
                 "them: the kit may have shipped the same fix in different wording.")
    for f in sus:
        lines.append(f"   {f['file']}  ←  {f['sha']} {f['subject']}")
    lines.append("ℹ  Fixed a kit script? Send it up (an issue or a PR on the kit), or the next sync will "
                 "hold your copy and stop updating that file.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────────────────────────
#  THE SYNC.
# ─────────────────────────────────────────────────────────────────────────────────────────────────
def make_restore_point(repo, backup_dir, ts, dry_run):
    tag = f"kit-sync-pre-{ts}"
    bundle = os.path.join(backup_dir, "pre-sync.bundle")
    if dry_run:
        return tag, bundle
    os.makedirs(backup_dir, exist_ok=True)
    if not _out(repo, "rev-parse", "--verify", "HEAD"):
        return None, None
    _git(repo, "tag", "-f", tag, "HEAD")
    _git(repo, "bundle", "create", bundle, "--all")
    return tag, bundle


def _backup(repo, backup_dir, rel, data):
    """Back up raw bytes (used where we only hold content, e.g. the uncommitted-edit rescue)."""
    bpath = os.path.join(backup_dir, rel)
    os.makedirs(os.path.dirname(bpath), exist_ok=True)
    with open(bpath, "wb") as fh:
        fh.write(data)
    return os.path.relpath(bpath, repo)


def _backup_file(repo, backup_dir, rel, src):
    """Faithfully copy an existing file OR symlink at `src` into the backup, preserving link-ness."""
    bpath = os.path.join(backup_dir, rel)
    os.makedirs(os.path.dirname(bpath), exist_ok=True)
    if os.path.islink(src):
        os.symlink(os.readlink(src), bpath)
    else:
        shutil.copy2(src, bpath)
    return os.path.relpath(bpath, repo)


def _restore_file(repo, backup_rel, live_rel):
    """Faithfully restore a backed-up file/symlink to its live path (used by undo and by failure rollback)."""
    src, dest = os.path.join(repo, backup_rel), os.path.join(repo, live_rel)
    if os.path.dirname(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.lexists(dest):
        os.remove(dest)
    if os.path.islink(src):
        os.symlink(os.readlink(src), dest)
    else:
        shutil.copy2(src, dest)


def vendor(repo, ref, plan, backup_dir, dry_run, content=None):
    """Copy the kit's version of each planned file into place, backing up any existing copy first.
    Per-file errors are captured, not raised, and if a write fails after the old file was removed, the
    backup is rolled straight back so nothing of the partner's is ever left deleted. Returns
    (outcomes, failures)."""
    outcomes, failures = [], []
    content = content or {}     # rel -> bytes to write INSTEAD of the kit blob (a clean 3-way merge)
    for rel in plan:
        dest = os.path.join(repo, rel)
        mode = _entry_mode(repo, ref, rel)
        kit_bytes = content.get(rel) if rel in content else _kit_blob(repo, ref, rel)
        if kit_bytes is None:
            outcomes.append({"file": rel, "action": "skip", "why": "not in kit ref"})
            continue
        exists = os.path.lexists(dest)
        # A file that EXISTS but cannot be read must never be deleted without a backup. Leave it.
        if exists and not os.path.islink(dest) and _read(dest) is None:
            failures.append({"file": rel, "error": "existing file unreadable; left untouched", "backed_up": None})
            outcomes.append({"file": rel, "action": "failed", "error": "unreadable", "backed_up": None})
            continue
        action = "add" if not exists else ("merge" if rel in content else "update")
        if dry_run:
            outcomes.append({"file": rel, "action": action + " (dry-run)"})
            continue
        backed_up = None
        try:
            if exists:
                backed_up = _backup_file(repo, backup_dir, rel, dest)
                os.remove(dest)
            parent = os.path.dirname(dest)
            if parent:
                os.makedirs(parent, exist_ok=True)
            if mode == "120000":
                os.symlink(kit_bytes.decode("utf-8", "replace"), dest)
            else:
                with open(dest, "wb") as fh:
                    fh.write(kit_bytes)
                st = os.stat(dest).st_mode
                os.chmod(dest, (st | 0o111) if mode.endswith("755") else (st & ~0o111))
            outcomes.append({"file": rel, "action": action, "backed_up": backed_up})
        except OSError as e:
            # Write failed. If the partner's file had already been removed, roll the backup back in.
            if backed_up is not None and not os.path.lexists(dest):
                try:
                    _restore_file(repo, backed_up, rel)
                except OSError:
                    pass
            failures.append({"file": rel, "error": str(e), "backed_up": backed_up})
            outcomes.append({"file": rel, "action": "failed", "error": str(e), "backed_up": backed_up})
    return outcomes, failures


def commit_sync(repo, outcomes, ts):
    changed = [o["file"] for o in outcomes if o["action"] in ("add", "update", "merge")]
    if not changed:
        return "", ""
    for f in changed:
        _git(repo, "add", "--", f)
    msg = (f"Kit sync {ts}: vendored {len(changed)} file(s) per-file, no history relation.\n\n"
           "Applied by kit_vendor_sync.py (BUG-040). Prior state tagged kit-sync-pre-* and bundled;\n"
           "replaced files backed up under documents/.superseded/. Reversible via Undo Kit Sync.command.")
    # Pathspec-scoped commit: records ONLY the kit files we changed, never anything the partner had
    # already staged before this run.
    p = _git(repo, "commit", "-m", msg, "--", *changed)
    if p.returncode != 0:
        combined = (p.stdout + p.stderr).lower()
        if "nothing to commit" in combined or "no changes added" in combined:
            return "", ""   # the tree was already right; not an error
        # A real commit failure (a hook, signing): unstage what we staged so the partner's index is
        # not left holding the kit files, where their next commit would sweep them in.
        for f in changed:
            _git(repo, "reset", "-q", "--", f)
        return "", (p.stderr.strip() or "git commit failed")
    return _out(repo, "rev-parse", "HEAD"), ""


def write_manifest(backup_dir, data):
    os.makedirs(backup_dir, exist_ok=True)
    with open(os.path.join(backup_dir, "sync-manifest.json"), "w") as fh:
        json.dump(data, fh, indent=2)


def sync(repo, dry_run=False, merge=False, replace_local=None):
    report = {"ok": False, "repo": repo, "steps": [], "outcomes": [], "dry_run": dry_run}

    if not is_git_repo(repo):
        report["error"] = "not_a_clone"
        return report, 1
    remote = find_kit_remote(repo)
    if not remote:
        report["error"] = "no_remote"
        return report, 1
    report["remote"] = remote

    # FETCH FIRST, and only trust the ancestry AFTER a fetch that actually reached the kit. A clone
    # left an origin/* ref behind, so without this an offline run would happily compare against
    # stale clone-time content and report "you're already current" — the most dangerous false success.
    # Dry-run fetches too (it is read-only): a preview against stale refs would be the same false
    # success in disguise.
    fp = _git(repo, "fetch", remote, "--quiet")
    if fp.returncode != 0:
        report["error"] = "offline"
        report["error_detail"] = (fp.stderr or "").strip()[:200]
        return report, 1
    report["steps"].append(f"fetched {remote} (read-only)")

    ref = kit_ref(repo, remote)
    report["ref"] = ref
    if not _out(repo, "rev-parse", "--verify", ref):
        report["error"] = "no_kit_ref"
        return report, 1

    anc = classify_ancestry(repo, "HEAD", ref)
    report["ancestry"] = anc
    if anc["state"] == "up_to_date":
        report["ok"] = True
        report["steps"].append("already current")
        return report, 0

    files = kit_owned_files(repo, ref)
    last_ref = last_synced_ref(repo)
    base = _merge_base(repo, ref) if anc.get("has_merge_base") else ""
    report["baseline"] = {"last_synced_ref": last_ref, "merge_base": base}
    plan, content, notes = classify_plan(repo, ref, files, last_ref, base,
                                         merge=merge, replace_local=replace_local)
    report["held"] = [n for n in notes if n["action"] == "held"]
    report["merged_files"] = [n for n in notes if n["action"] == "merged"]
    report["kept"] = [n for n in notes if n["action"] == "kept"]
    report["notes"] = notes
    if not plan:
        report["ok"] = True
        if report["held"]:
            report["steps"].append(f"{len(report['held'])} file(s) held: they carry your own edits")
            return report, 2
        report["steps"].append("all kit-owned files already match; nothing to do")
        return report, 0

    ts = _dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    backup_dir = os.path.join(repo, "documents", ".superseded", ts)
    report["backup_dir"] = os.path.relpath(backup_dir, repo)

    tag, bundle = make_restore_point(repo, backup_dir, ts, dry_run)
    report["restore_tag"] = tag
    report["restore_bundle"] = os.path.relpath(bundle, repo) if bundle else None

    outcomes, failures = vendor(repo, ref, plan, backup_dir, dry_run, content=content)
    report["outcomes"] = outcomes
    report["failures"] = failures

    changed = [o for o in outcomes if o["action"] in ("add", "update", "merge")]
    if dry_run:
        report["ok"] = True
        report["steps"].append(f"dry-run: {len(plan)} file(s) would change")
        return report, 0
    if not changed:
        if failures:
            # Every planned file failed to write. Each was rolled back per-file, so the tree is intact,
            # but NOTHING copied — this is not "partial", it is a clean no-op-with-error. Exit 2.
            report["error"] = "none_written"
            report["ok"] = False
            report["steps"].append(f"no file could be written ({len(failures)} failed); nothing changed")
            return report, 2
        report["ok"] = True
        report["steps"].append("no kit-owned files differed")
        return report, 0

    commit, commit_err = commit_sync(repo, outcomes, ts)
    report["commit"] = commit

    # Always leave a manifest — even a partial or a commit that failed — so Undo can find its way back.
    write_manifest(backup_dir, {
        "ts": ts, "remote": remote, "ref": ref, "ref_sha": anc.get("ref", ""), "ancestry": anc,
        "restore_tag": tag, "restore_bundle": os.path.relpath(bundle, repo) if bundle else None,
        "commit": commit, "changed": [o["file"] for o in changed],
        "backed_up": [o.get("backed_up") for o in changed if o.get("backed_up")],
        "failures": failures,
    })

    if commit_err:
        report["error"] = "commit_failed"
        report["error_detail"] = commit_err
        return report, 2
    if failures:
        report["error"] = "partial"
        report["steps"].append(f"committed {len(changed)} file(s); {len(failures)} could not be written")
        report["ok"] = True
        return report, 2

    report["ok"] = True
    report["steps"].append(f"committed sync ({len(changed)} file(s))")
    if report.get("held"):
        report["error"] = "held"
        report["steps"].append(f"{len(report['held'])} file(s) held: they carry your own edits")
        return report, 2
    return report, 0


# ─────────────────────────────────────────────────────────────────────────────────────────────────
#  UNDO — return to the exact pre-sync state. Safe by construction: the restore tag sits at the
#  partner's OWN pre-sync HEAD, so every commit of theirs is inside it. Two things get extra care:
#   * If the partner committed MORE work since the sync, history is NOT rewound (that would lose it):
#     the replaced files are restored from the backup and history is left alone.
#   * If the working tree has UNCOMMITTED tracked edits, they are backed up before any reset, so the
#     reset can never silently drop them.
# ─────────────────────────────────────────────────────────────────────────────────────────────────
def latest_manifest(repo):
    root = os.path.join(repo, "documents", ".superseded")
    if not os.path.isdir(root):
        return None
    cands = []
    for name in sorted(os.listdir(root)):
        m = os.path.join(root, name, "sync-manifest.json")
        if os.path.isfile(m):
            cands.append(m)
    if not cands:
        return None
    try:
        with open(cands[-1]) as fh:
            data = json.load(fh)
        data["_manifest_path"] = cands[-1]
        data["_backup_dir"] = os.path.dirname(cands[-1])
        return data
    except (OSError, ValueError):
        return None


def _dirty_tracked(repo):
    """Paths with uncommitted changes to TRACKED files (ignored files never appear here)."""
    p = _git(repo, "status", "--porcelain", "--untracked-files=no", "-z")
    if p.returncode != 0 or not p.stdout:
        return []
    out = []
    for chunk in p.stdout.split("\0"):
        if len(chunk) > 3:
            out.append(chunk[3:])
    return out


def undo(repo, dry_run=False):
    report = {"ok": False, "repo": repo, "steps": [], "mode": None, "dry_run": dry_run}
    if not is_git_repo(repo):
        report["error"] = "not_a_clone"
        return report, 1
    man = latest_manifest(repo)
    if not man:
        report["error"] = "no_sync"
        return report, 1
    report["ts"] = man.get("ts")
    tag = man.get("restore_tag")
    sync_commit = man.get("commit")
    bundle = man.get("restore_bundle")
    head = _out(repo, "rev-parse", "HEAD")

    if tag and not _out(repo, "rev-parse", "--verify", tag):
        if bundle and os.path.isfile(os.path.join(repo, bundle)) and not dry_run:
            report["steps"].append("restore tag was gone; recovering it from the bundle")
            _git(repo, "fetch", os.path.join(repo, bundle), f"refs/tags/{tag}:refs/tags/{tag}")
    tag_sha = _out(repo, "rev-parse", tag) if tag else ""

    if tag_sha and sync_commit and head == sync_commit:
        # Clean full undo: rewinding to our own pre-sync tag can only drop the sync commit, never a
        # partner commit. But a reset --hard also discards uncommitted TRACKED edits — so back those
        # up first, so even mid-flight edits are recoverable.
        report["mode"] = "history"
        dirty = _dirty_tracked(repo)
        if dirty and not dry_run:
            bd = os.path.join(repo, "documents", ".superseded",
                              _dt.datetime.now().strftime("%Y-%m-%d-%H%M%S") + "-undo")
            saved = []
            for rel in dirty:
                data = _read(os.path.join(repo, rel))
                if data is not None:
                    saved.append(_backup(repo, bd, rel, data))
            report["saved_uncommitted"] = saved
            report["steps"].append(f"saved {len(saved)} uncommitted edit(s) before rewinding")
        if not dry_run:
            _git(repo, "reset", "--hard", tag)
        now = _out(repo, "rev-parse", "HEAD")
        report["restored_to"] = tag
        report["ok"] = dry_run or (now == tag_sha)
        return report, 0 if report["ok"] else 2

    # Partner committed since the sync (or the tag is unrecoverable): DO NOT touch history. Restore the
    # replaced files from the backup so their edits come back, and leave every commit in place.
    report["mode"] = "files-only"
    backup_dir = man.get("_backup_dir")
    prefix = (os.path.relpath(backup_dir, repo) + os.sep) if backup_dir else ""
    # ⚠️ `restored` must record only files ACTUALLY restored. An earlier version appended to it
    # unconditionally (outside the `if not dry_run:` guard), so a `--undo --dry-run` in this mode
    # reported files as restored that were never touched — `render_undo()` would have told a
    # dry-run user "Restored N file(s)... from the backup" when nothing happened. `would_restore`
    # is the dry-run's own, honestly-separate preview list.
    restored, would_restore = [], []
    for rel in man.get("backed_up", []) or []:
        live_rel = rel[len(prefix):] if prefix and rel.startswith(prefix) else None
        if not live_rel or not os.path.lexists(os.path.join(repo, rel)):
            continue
        if dry_run:
            would_restore.append(live_rel)
            continue
        try:
            _restore_file(repo, rel, live_rel)   # faithful: a backed-up symlink returns as a link
        except OSError:
            continue
        restored.append(live_rel)
    expected = [r for r in (man.get("backed_up") or []) if prefix and r.startswith(prefix)]
    report["restored_files"] = restored
    report["would_restore_files"] = would_restore
    report["expected_restores"] = len(expected)
    if dry_run:
        report["ok"] = True
        report["steps"].append(f"dry-run: would restore {len(would_restore)} replaced file(s) "
                                f"from backup; history untouched")
        return report, 0
    if expected and not restored:
        # We were meant to put files back and none came back: don't report success.
        report["ok"] = False
        report["steps"].append("could not restore any of the replaced files from backup")
        return report, 2
    report["ok"] = True
    report["steps"].append(f"history left intact; restored {len(restored)} replaced file(s) from backup")
    return report, 0


# ─────────────────────────────────────────────────────────────────────────────────────────────────
#  PLAIN-LANGUAGE REPORT.
# ─────────────────────────────────────────────────────────────────────────────────────────────────
def _n(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def render(report):
    # A hard precondition failure (offline / not a clone / commit-failed / total write failure): the
    # plain sentence is the whole message.
    if report.get("error") in _ERROR_TEXT and not report.get("ok"):
        return f"🛑 {_ERROR_TEXT[report['error']]}"
    if report.get("dry_run"):
        would = [o for o in report.get("outcomes", []) if o["action"].split()[0] in ("add", "update")]
        if not would:
            return "▶  Preview: your kit files already match. Nothing to update."
        u = sum(1 for o in would if o["action"].startswith("update"))
        a = sum(1 for o in would if o["action"].startswith("add"))
        return (f"▶  Preview (nothing changed yet): {_n(u, 'file')} would be updated, {a} added.\n"
                "   Run \"Sync Kit\" to apply. Your own files and commits would be preserved.")
    lines = ["▶  Syncing the kit (safe, per-file)…",
             f"   from: {report.get('remote','?')}"]
    anc = report.get("ancestry", {})
    state = anc.get("state", "")
    changed = [o for o in report.get("outcomes", []) if o["action"] in ("add", "update", "merge")]
    if (state == "up_to_date" or (not changed and report.get("ok"))) and not report.get("held"):
        if state in ("diverged", "unrelated"):
            lines.append("   Your own commits are untouched, and the kit's files already match — "
                         "nothing needed doing.")
        else:
            lines.append("   You were already on the latest kit. Nothing to do.")
        lines.append("✅  Done. Your own files, settings and commits were never touched.")
        return "\n".join(lines)
    if state == "unrelated":
        lines.append("   Your copy of the kit had drifted apart from the published one. Nothing of "
                     "yours was removed — the kit's files were simply copied in.")
    elif state == "diverged":
        lines.append("   You have your own commits the kit doesn't. They are untouched; the kit's "
                     "files were updated around them.")
    elif state == "behind":
        lines.append("   Your kit was behind. Updated it with no loss.")
    lo = anc.get("local_only", 0)
    if lo:
        lines.append(f"   {_n(lo, 'commit')} of yours " + ("was" if lo == 1 else "were") + " kept, every one.")
    added = [o for o in changed if o["action"] == "add"]
    updated = [o for o in changed if o["action"] == "update"]
    lines.append(f"   {_n(len(updated), 'file')} updated, {len(added)} added, one at a time.")
    if any(o.get("backed_up") for o in changed) and report.get("backup_dir"):
        lines.append(f"   Any file of yours that was replaced is saved under: {report['backup_dir']}")
    for o in report.get("merged_files") or []:
        lines.append(f"   ⚠  {o['file']}: your edit and the kit's update were MERGED; read the result.")
    for o in report.get("kept") or []:
        lines.append(f"   {o['file']}: yours, kept as is (the kit only seeds it).")
    held = report.get("held") or []
    for o in held:
        who = ", ".join(f"{c['sha']} {c['subject']}" for c in (o.get("commits") or [])[:3])
        lines.append(f"   ⛔ {o['file']} was NOT updated: it carries your own edit" +
                     (f" ({who})" if who else "") + ". Left exactly as it was.")
    if held:
        lines.append("   Fixed a kit script? Send it up (an issue or a PR on the kit) so the sync can "
                     "carry it. To take the kit's version anyway: Sync with --replace-local <file>, "
                     "or --merge to try a three-way merge.")
    failures = report.get("failures") or []
    if failures:
        lines.append(f"   ⚠  {_n(len(failures), 'file')} could not be written and " +
                     ("was" if len(failures) == 1 else "were") + " left exactly as before: " +
                     ", ".join(f["file"] for f in failures[:5]))
    if report.get("restore_tag"):
        lines.append("   This is reversible: run \"Undo Kit Sync\" to return to how things were.")
    if failures or held:
        lines.append("ℹ  Finished with some files skipped (above). Nothing of yours was destroyed.")
    else:
        lines.append("✅  Done. Your documents, your settings and your own commits were never touched.")
    return "\n".join(lines)


def render_undo(report):
    if report.get("error") == "no_sync":
        return "🛑 Nothing to undo — there's no previous Sync Kit to reverse."
    if report.get("error") == "not_a_clone":
        return f"🛑 {_ERROR_TEXT['not_a_clone']}"
    lines = ["▶  Undo kit sync"]
    dry_run = report.get("dry_run")
    if report.get("mode") == "history":
        if not report.get("ok"):
            lines.append("🛑  The undo did not fully complete. Nothing was destroyed, but your files "
                         "may not be back yet — send this to the kit maintainer.")
            return "\n".join(lines)
        if dry_run:
            lines.append("▶  Preview (nothing changed yet): would rewind to your pre-sync state. "
                         "The sync would be undone; every one of your own commits would stay intact.")
            lines.append("✅  Done. Nothing was changed — this was a preview.")
            return "\n".join(lines)
        if report.get("saved_uncommitted"):
            lines.append(f"   Saved {_n(len(report['saved_uncommitted']), 'unsaved edit')} first, then rewound.")
        lines.append("   Rewound to your pre-sync state. The sync is gone; all of your own commits "
                     "are intact.")
    else:
        if not report.get("ok"):
            lines.append("ℹ  No files could be put back from the backup. Nothing was destroyed either "
                         "way. If you expected files back, send this to the kit maintainer.")
            return "\n".join(lines)
        if dry_run:
            n = len(report.get("would_restore_files", []))
            lines.append("   No commit was moved; your history would be left exactly as it is.")
            lines.append(f"▶  Preview (nothing changed yet): would restore {_n(n, 'file')} the sync "
                         "had replaced, from the backup.")
            lines.append("✅  Done. Nothing was changed — this was a preview.")
            return "\n".join(lines)
        n = len(report.get("restored_files", []))
        lines.append("   No commit was moved, so your history is left exactly as it is.")
        lines.append(f"   Restored {_n(n, 'file')} the sync had replaced, from the backup.")
    lines.append("✅  Done. Nothing of yours was destroyed.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Vendored per-file kit sync (BUG-040).")
    ap.add_argument("--repo", default=".", help="the partner's kit clone (default: cwd)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, touch nothing")
    ap.add_argument("--undo", action="store_true", help="restore the pre-sync state of the last sync")
    ap.add_argument("--json", action="store_true", help="emit the raw report as JSON")
    ap.add_argument("--merge", action="store_true",
                    help="on a file you edited, try a three-way merge with the kit's update; hold on conflict")
    ap.add_argument("--replace-local", nargs="*", metavar="FILE",
                    help="take the kit's version of these files even though you edited them ('all' for every one)")
    ap.add_argument("--check-clobber", action="store_true",
                    help="audit only: which of your own commits to kit-owned files may no longer be live")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    if a.check_clobber:
        if not is_git_repo(repo):
            print(json.dumps({"ok": False, "error": "not_a_clone"}) if a.json else f"🛑 {_ERROR_TEXT['not_a_clone']}")
            return 1
        remote = find_kit_remote(repo)
        ref = kit_ref(repo, remote) if remote else ""
        report = check_clobber(repo, ref or "HEAD")
        print(json.dumps(report, indent=2) if a.json else render_clobber(report))
        return 0
    if a.undo:
        report, code = undo(repo, dry_run=a.dry_run)
        print(json.dumps(report, indent=2) if a.json else render_undo(report))
        return code
    report, code = sync(repo, dry_run=a.dry_run, merge=a.merge, replace_local=a.replace_local)
    print(json.dumps(report, indent=2) if a.json else render(report))
    return code


if __name__ == "__main__":
    sys.exit(main())
