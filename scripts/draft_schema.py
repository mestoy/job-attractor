#!/usr/bin/env python3
"""draft_schema.py -- the app draft contract, schema 1 (app/design/draft_schema.md).

One file per card at documents/state/app-drafts/<slug>.json, written by
scripts/prepare_app_draft.py, carried into the feed card as card.draft. validate(doc) returns
a list of plain problems; an empty list means the draft is valid. Standard library only, and it
never changes the doc it reads.

    python3 scripts/draft_schema.py <draft.json> [...]   exit 0 valid, 1 invalid, 2 usage
"""
import datetime
import json
import re
import sys

SCHEMA_VERSION = 1
# Key order is part of the contract: the thesis comes before the subject and the beats.
TOP_KEYS = ("schema", "slug", "company", "prepared_at", "rung", "to_name", "to_title",
            "boss_verified", "thesis", "subject", "beats", "body", "checks", "resume")
SEATS = ("cpo", "cto", "ceo", "rise8")
SEAT_MAX = 25
PASS_FAIL = ("pass", "fail")
VERIFY = ("green", "red")
PRAISE_BEAT = "praise"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_URL = re.compile(r"^https?://\S+$")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_str(v, empty_ok=False):
    return isinstance(v, str) and (empty_ok or bool(v.strip()))


def _strings(node, path="draft"):
    """Every key and string value, with where it sits."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield path, str(k)
            yield from _strings(v, "%s.%s" % (path, k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _strings(v, "%s[%d]" % (path, i))
    elif isinstance(node, str):
        yield path, node


def _check_opt(opt, where, errs):
    if not isinstance(opt, dict):
        errs.append("%s is not an option object" % where)
        return
    for key in ("text", "scores", "total", "source_url"):
        if key not in opt:
            errs.append("%s is missing %s" % (where, key))
    if "text" in opt and not _is_str(opt["text"]):
        errs.append("%s.text must be non-empty text" % where)
    scores = opt.get("scores")
    seat_sum = 0
    if "scores" in opt:
        if not isinstance(scores, dict):
            errs.append("%s.scores must be an object" % where)
            scores = {}
        for seat in SEATS:
            if seat not in scores:
                errs.append("%s.scores is missing %s" % (where, seat))
                continue
            v = scores[seat]
            if not _is_int(v) or not 0 <= v <= SEAT_MAX:
                errs.append("%s.scores.%s must be a whole number from 0 to %d" % (where, seat, SEAT_MAX))
            else:
                seat_sum += v
    if "total" in opt:
        if not _is_int(opt["total"]):
            errs.append("%s.total must be a whole number" % where)
        elif isinstance(scores, dict) and all(_is_int(scores.get(s)) for s in SEATS) \
                and opt["total"] != seat_sum:
            errs.append("%s.total must equal the four seat scores added up" % where)
    url = opt.get("source_url")
    if url is not None and not (isinstance(url, str) and _URL.match(url)):
        errs.append("%s.source_url must be a web link or null" % where)


def _check_choice(block, where, errs, prompt=False, beat=False):
    if not isinstance(block, dict):
        errs.append("%s must be an object" % where)
        return
    need = (("prompt",) if prompt else ()) + (("name", "label") if beat else ()) \
        + ("options", "chosen") + (("freeform_allowed",) if beat else ())
    for key in need:
        if key not in block:
            errs.append("%s is missing %s" % (where, key))
    for key in (("prompt",) if prompt else ()) + (("name", "label") if beat else ()):
        if key in block and not _is_str(block[key]):
            errs.append("%s.%s must be non-empty text" % (where, key))
    if beat and "freeform_allowed" in block and not isinstance(block["freeform_allowed"], bool):
        errs.append("%s.freeform_allowed must be true or false" % where)
    opts = block.get("options")
    if "options" in block:
        if not isinstance(opts, list) or not opts:
            errs.append("%s.options must hold at least one option" % where)
            opts = []
        for i, opt in enumerate(opts):
            _check_opt(opt, "%s.options[%d]" % (where, i), errs)
    if "chosen" in block:
        c = block["chosen"]
        if not _is_int(c) or not (isinstance(opts, list) and 0 <= c < len(opts)):
            errs.append("%s.chosen must point at one of its options" % where)


def validate(doc):
    """Plain problems with `doc`, or [] when it is a valid schema-1 draft."""
    if not isinstance(doc, dict):
        return ["a draft must be a JSON object"]
    errs = []
    for key in TOP_KEYS:
        if key not in doc:
            errs.append("missing %s" % key)
    for key in doc:
        if key not in TOP_KEYS:
            errs.append("unknown key %s" % key)

    # No address anywhere: the address lives only in the page's private store.
    for where, s in _strings(doc):
        if "@" in s:
            errs.append("an @ appears in %s; no email address may be in a draft" % where)

    order = [k for k in doc if k in ("thesis", "subject", "beats")]
    if len(order) == 3 and order != ["thesis", "subject", "beats"]:
        errs.append("thesis must come before subject and beats")

    if "schema" in doc and (not _is_int(doc["schema"]) or doc["schema"] != SCHEMA_VERSION):
        errs.append("schema must be %d" % SCHEMA_VERSION)
    if "slug" in doc and not (isinstance(doc["slug"], str) and _SLUG.match(doc["slug"])):
        errs.append("slug must be lowercase letters, digits and hyphens")
    for key in ("company", "rung"):
        if key in doc and not _is_str(doc[key]):
            errs.append("%s must be non-empty text" % key)
    if "prepared_at" in doc:
        v = doc["prepared_at"]
        ok = isinstance(v, str) and bool(_UTC.match(v))
        if ok:
            try:
                datetime.datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                ok = False
        if not ok:
            errs.append("prepared_at must be an ISO-8601 UTC time ending in Z")
    for key in ("to_name", "to_title"):
        if key in doc and doc[key] is not None and not _is_str(doc[key]):
            errs.append("%s must be text or null" % key)
    if "boss_verified" in doc and not isinstance(doc["boss_verified"], bool):
        errs.append("boss_verified must be true or false")

    if "thesis" in doc:
        _check_choice(doc["thesis"], "thesis", errs, prompt=True)
    if "subject" in doc:
        _check_choice(doc["subject"], "subject", errs)
    has_praise = False
    if "beats" in doc:
        beats = doc["beats"]
        if not isinstance(beats, list) or not beats:
            errs.append("beats must hold at least one beat")
            beats = []
        for i, b in enumerate(beats):
            _check_choice(b, "beats[%d]" % i, errs, beat=True)
            if isinstance(b, dict) and b.get("name") == PRAISE_BEAT:
                has_praise = True
                for j, o in enumerate(b.get("options") or []):
                    if isinstance(o, dict) and not o.get("source_url"):
                        errs.append("beats[%d].options[%d] is praise with no source" % (i, j))
    if "body" in doc and not _is_str(doc["body"]):
        errs.append("body must be non-empty text")

    if "checks" in doc:
        ch = doc["checks"]
        if not isinstance(ch, dict):
            errs.append("checks must be an object")
        else:
            for key in ("outreach", "praise_sourced", "honesty", "notes"):
                if key not in ch:
                    errs.append("checks is missing %s" % key)
            for key in ("outreach", "honesty"):
                if key in ch and ch[key] not in PASS_FAIL:
                    errs.append("checks.%s must be pass or fail" % key)
            if "praise_sourced" in ch:
                if not isinstance(ch["praise_sourced"], bool):
                    errs.append("checks.praise_sourced must be true or false")
                elif isinstance(doc.get("beats"), list) and ch["praise_sourced"] != has_praise:
                    errs.append("checks.praise_sourced must be true exactly when there is a praise beat")
            if "notes" in ch and not (isinstance(ch["notes"], list)
                                      and all(isinstance(n, str) for n in ch["notes"])):
                errs.append("checks.notes must be a list of text")

    if "resume" in doc and doc["resume"] is not None:
        r = doc["resume"]
        if not isinstance(r, dict):
            errs.append("resume must be null or an object")
        else:
            for key in ("filename", "verify", "asset_url"):
                if key not in r:
                    errs.append("resume is missing %s" % key)
            if "filename" in r and not _is_str(r["filename"]):
                errs.append("resume.filename must be non-empty text")
            if "verify" in r and r["verify"] not in VERIFY:
                errs.append("resume.verify must be green or red")
            if "asset_url" in r and r["asset_url"] is not None and not _is_str(r["asset_url"]):
                errs.append("resume.asset_url must be text or null")
    return errs


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: draft_schema.py <draft.json> [...]")
        return 2
    bad = 0
    for path in argv:
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            print("%s: could not read it (%s)" % (path, exc))
            bad += 1
            continue
        errs = validate(doc)
        if errs:
            bad += 1
            print("%s: %d problem(s)" % (path, len(errs)))
            for e in errs:
                print("  - " + e)
        else:
            print("%s: valid" % path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
