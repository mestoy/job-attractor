#!/usr/bin/env python3
"""migrate_activity_stores.py — plan the one-time move of the Rise8 activity answers into the app.

WHY THIS EXISTS. His words, 2026-09-15: "in the app, I followed the link to the Rise8 Brand
Assumptions activity and it took me outside the app. Everything should reside in the app, except
items like emails to future bosses. This is critical." The activities now open inside the app and
save under the SAME names the old published pages used, so the answers he already gave have to
move across once. After that there is one place he answers and one place his assistant reads.

⛔ THIS FILE NEVER TOUCHES A LIVE STORE. It reads two exports from disk and writes a PLAN: the
list of saves, each pinned to the version the app already holds, plus everything it refuses to
touch and why. The /app command applies that plan. Nothing here reaches the network, and nothing
here changes either export. That separation is deliberate: the documents it plans over are his
real answers, so the step that actually writes them is a person's decision, not a script's.

WHAT IT PLANS, per document

  the app has nothing        → save it across, unpinned (there is nothing to overwrite)
  the app has the same       → nothing; it already moved on an earlier run
  the app has something OLDER→ save it across, pinned to the version the app holds, so the save
                               does nothing at all if that answer changed in the meantime
  the app has something NEWER→ refuse. A newer answer in the app is his most recent word, and a
                               migration must never talk over it
  the app differs, age unknown→ refuse. With no version there is no safe pin

It is safe to plan twice. A second run over the same two exports plans nothing, and a marker
records what moved so the /app step can tell a finished move from one never made.

THE EXPORTS IT READS. Both are the on-disk shape the /app export step writes: one file per
document, in a folder named for the store it came from.

    <export>/brand_assumptions/current.json
    <export>/brand_assumptions/submission-1757800000000.json
    <export>/brand_hypotheses/current.json
    <export>/user_research_plan/current.json
    <export>/brand_studio_a2/current.json

Pass --old-export more than once when the same activity page was published more than once (his
read-every-copy rule): every copy is read, and for any one document the newest answer wins.

Versions, used as the pin, are read from `_versions.json` at the top of the export
({"brand_assumptions/current": 7}) or from a `__version` key inside a document. A version is
bookkeeping, never part of the answer, so it is stripped before anything is saved.

Run:  python3 scripts/migrate_activity_stores.py --old-export DIR [--old-export DIR ...]
                                                 --app-export DIR [--repo DIR] [--out PATH]
"""
import argparse
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = os.path.dirname(HERE)

# The four stores the old activity pages wrote. Each name is the one an activity description in
# app/design/activities already declares, so the app and this file never carry two spellings of
# one store (a test holds these against those descriptions).
ACTIVITY_COLLECTIONS = ("brand_assumptions", "brand_hypotheses", "user_research_plan",
                        "brand_studio_a2")

# The marker the move leaves behind, so a later run can tell "already done" from "never ran".
MARKER_COLLECTION = "migrations"
MARKER_DOC = "activities-2026-09"

# Keys that are bookkeeping about a document rather than part of what he answered.
BOOKKEEPING = ("__version", "__name__", "version")

# Where a document says when it was last answered. The activity view writes updatedAt on every
# change and submittedAt on Done, so the newest of these is how old an answer is.
STAMP_KEYS = ("submittedAt", "updatedAt", "savedAt", "at")

PLAN_REL = os.path.join("documents", "state", "activity-migration-plan.json")


class MigrationInputError(Exception):
    """The exports it was pointed at are not there. Never confused with "nothing to move"."""


def _titles():
    """{store name: the activity's own title}, read from the activity descriptions the app
    ships, so a person reads "Brand Assumptions" and never a stored name."""
    out = {}
    folder = os.path.join(REPO_DEFAULT, "app", "design", "activities")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                spec = json.load(fh)
        except (ValueError, OSError):
            continue
        if isinstance(spec, dict) and spec.get("collection") and spec.get("title"):
            out[spec["collection"]] = spec["title"]
    return out


def _title_for(name, titles=None):
    titles = _titles() if titles is None else titles
    return titles.get(name) or name.replace("_", " ").replace("-", " ").strip().title()


def _load_store(path):
    """{store: {document name: document or a read failure}} from one export folder.

    A document that cannot be read is carried as a failure rather than dropped: a move that
    silently skips an unreadable answer is the same defect as calling a refused read empty.
    """
    store = {}
    if not path or not os.path.isdir(path):
        return store
    for name in sorted(os.listdir(path)):
        folder = os.path.join(path, name)
        if not os.path.isdir(folder):
            continue
        for fname in sorted(os.listdir(folder)):
            if not fname.endswith(".json"):
                continue
            doc_id = os.path.splitext(fname)[0]
            try:
                with open(os.path.join(folder, fname), encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (ValueError, OSError):
                store.setdefault(name, {})[doc_id] = _Unreadable()
                continue
            if isinstance(doc, dict):
                store.setdefault(name, {})[doc_id] = doc
    return store


class _Unreadable(object):
    """A document on disk we could not read. Never treated as an empty answer."""


def _load_versions(path):
    out = {}
    if not path or not os.path.isdir(path):
        return out
    try:
        with open(os.path.join(path, "_versions.json"), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (ValueError, OSError):
        return out
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, int):
                out[str(key)] = value
    return out


def _answer(doc):
    """What he actually answered: the document without its bookkeeping keys."""
    return {k: v for k, v in doc.items() if k not in BOOKKEEPING}


def _stamp(doc):
    """The newest time this document carries, or "" when it carries none."""
    best = ""
    for key in STAMP_KEYS:
        value = doc.get(key)
        if isinstance(value, str) and value > best:
            best = value
    return best


def _version_of(doc, key, versions):
    if key in versions:
        return versions[key]
    for name in ("__version", "version"):
        value = doc.get(name)
        if isinstance(value, int):
            return value
    return None


def _merge_copies(paths):
    """Every old copy read into one {store: {document: doc}}, newest answer winning.

    His read-every-copy rule: an activity page published twice holds the same documents on
    both copies, and the newer answer is the real one.
    """
    merged = {}
    for path in paths:
        for name, docs in _load_store(path).items():
            for doc_id, doc in docs.items():
                have = merged.get(name, {}).get(doc_id)
                if have is None:
                    merged.setdefault(name, {})[doc_id] = doc
                    continue
                if isinstance(doc, _Unreadable):
                    continue
                if isinstance(have, _Unreadable) or _stamp(doc) > _stamp(have):
                    merged[name][doc_id] = doc
    return merged


def _now():
    return (datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"))


def plan(old_export, app_export, at=None):
    """The batch of saves the move needs, plus what it refuses and what already moved.

    `old_export` is one export folder or a list of them (one per published copy). Returns a
    plain dict; nothing is written and no store is contacted.
    """
    paths = [old_export] if isinstance(old_export, str) else list(old_export or [])
    if not paths:
        raise MigrationInputError("I was not told where your activity answers were saved.")
    for path in paths:
        if not os.path.isdir(path):
            raise MigrationInputError(
                "I could not find your saved activity answers at %s." % path)

    old = _merge_copies(paths)
    app = _load_store(app_export)
    versions = _load_versions(app_export)
    titles = _titles()

    writes, refusals, skipped, moved = [], [], [], []

    for name in ACTIVITY_COLLECTIONS:
        title = _title_for(name, titles)
        here = old.get(name) or {}
        for doc_id in sorted(here):
            doc = here[doc_id]
            key = "%s/%s" % (name, doc_id)
            if isinstance(doc, _Unreadable):
                refusals.append({"collection": name, "doc_id": doc_id, "title": title,
                                 "reason": "We could not read this %s answer. It stays "
                                           "where it is." % title})
                continue
            theirs = app.get(name, {}).get(doc_id)
            if isinstance(theirs, _Unreadable):
                refusals.append({"collection": name, "doc_id": doc_id, "title": title,
                                 "reason": "We could not read what your app has for %s. "
                                           "Nothing is touched." % title})
                continue
            body = _answer(doc)
            if theirs is None:
                writes.append({"op": "set", "collection": name, "doc_id": doc_id, "data": body})
                moved.append(key)
                continue
            mine = _answer(theirs)
            if mine == body:
                skipped.append({"collection": name, "doc_id": doc_id, "title": title,
                                "reason": "Your app already has this %s answer." % title})
                continue
            if _stamp(theirs) > _stamp(doc):
                refusals.append({"collection": name, "doc_id": doc_id, "title": title,
                                 "reason": "Your %s answer in the app is newer. It stays "
                                           "as it is." % title})
                continue
            pin = _version_of(theirs, key, versions)
            if pin is None:
                refusals.append({"collection": name, "doc_id": doc_id, "title": title,
                                 "reason": "Your app has a different %s answer. We cannot "
                                           "tell which version it is on. Nothing is "
                                           "changed." % title})
                continue
            writes.append({"op": "set", "collection": name, "doc_id": doc_id, "data": body,
                           "if_version": pin})
            moved.append(key)

    if writes:
        writes.append({"op": "set", "collection": MARKER_COLLECTION, "doc_id": MARKER_DOC,
                       "data": {"moved": sorted(moved), "at": at or _now(),
                                "refused": sorted(r["collection"] + "/" + r["doc_id"]
                                                  for r in refusals)}})

    return {"planned_at": at or _now(), "writes": writes, "refusals": refusals,
            "skipped": skipped, "summary": _summary(writes, refusals, skipped, titles)}


def _summary(writes, refusals, skipped, titles):
    """What a person reads: what moves, what stays, and what happens next."""
    lines = []
    by_store = {}
    for write in writes:
        if write["collection"] == MARKER_COLLECTION:
            continue
        by_store.setdefault(write["collection"], 0)
        by_store[write["collection"]] += 1
    for name in ACTIVITY_COLLECTIONS:
        title = _title_for(name, titles)
        moving = by_store.get(name, 0)
        staying = [r for r in refusals if r["collection"] == name]
        already = [s for s in skipped if s["collection"] == name]
        if moving:
            lines.append("%s: %s into your app."
                         % (title, "1 answer moves" if moving == 1
                            else "%d answers move" % moving))
        elif already and not staying:
            lines.append("%s: already in your app, nothing to move." % title)
        for row in staying:
            lines.append("%s: %s" % (title, row["reason"]))
    if not lines:
        lines.append("There is nothing to move. Your app already has every activity answer.")
    if writes:
        lines.append("Nothing has changed yet. Your assistant moves these answers the next "
                     "time you run /app. After that you answer inside the app.")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Plan the one-time move of your activity answers into the app.")
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--old-export", action="append", default=None,
                    help="an export of an old activity page's saved answers; pass it once "
                         "per published copy")
    ap.add_argument("--app-export", default=None,
                    help="an export of what the app itself has saved")
    ap.add_argument("--out", default=None, help="where to write the plan")
    a = ap.parse_args(argv)

    try:
        made = plan(a.old_export or [], a.app_export)
    except MigrationInputError as err:
        print(str(err))
        print("Run /app first. It saves your answers where I can read them.")
        return 1

    for line in made["summary"]:
        print(line)

    out = a.out or os.path.join(a.repo, PLAN_REL)
    directory = os.path.dirname(out) or "."
    os.makedirs(directory, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(made, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
