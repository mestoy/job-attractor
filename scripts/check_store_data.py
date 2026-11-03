#!/usr/bin/env python3
"""check_store_data.py <push-dir>: the gate on the DATA that goes into the app's store (BUG-709).

The HTML greps never read the store data, so a third party's address in `gates[].w`, or his own
identity glued to a voice sample, rode into the live page's store unseen. This reads the documents
the push would write (`feed-cards/*.json`, `feed-after/*.json`, `feed/meta.json`), flattens each to
`path = value` rows over dict KEYS and values, and runs `pii_gate.scan_items` on them, the same
matcher `kit_push_guard.py` uses, so an email, a phone and a LinkedIn slug stay ONE vocabulary. On top
it adds a literal tier for the owner's own identity, read from `pii_gate._resolve_owner()` plus the candidate
profile (`01-candidate-profile.md`), never typed here.

Allowed, and nothing else (plan rev 3 O1):
  * `meta.owner.*` and `meta.build_beats.owner.*` (the signature lint and sign-off row read them);
  * inside `meta.voice.*[].text`, a LINE that is, whole, his name or his site (as a URL too: a sign-off).
A third party's LinkedIn slug, and a street address in a card's research text (a company's office),
are provenance: WARN on cards and after rows, BLOCK under meta.

Exit 0 clean (writes `<push-dir>/.store-data-check.json`, a receipt `app_push_feed.py` checks),
3 on any blocking hit, 2 when it cannot run (a missing or unparseable file, no cards, an empty
identity vocabulary). A gate that could not look must never read as a pass.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "partner-starter", "scripts"))

RECEIPT = ".store-data-check.json"
_VOICE_TEXT = re.compile(r"^meta\.voice\.[^.\[\]]+\[\d+\]\.text$")
_OWNER_PATHS = ("meta.owner.", "meta.build_beats.owner.")
_PROFILE_FIELDS = (("name", r"Name"), ("phone", r"Phone"), ("email", r"Email"),
                   ("linkedin", r"LinkedIn"), ("site", r"Website"))


# a template value, matched WHOLE (BUG-737): [YOUR NAME], [CITY, STATE], "Your Name", "you@example.com", yoursite.*, yourdomain.*, example.*,
# the exact "Jane Doe" / "John Doe", 555-0100, "placeholder". A real "John Smith" or johnsmith@... is NOT a template value: a prefix match
# skipped it and the gate never searched the store data for a partner named John or Jane.
# .invalid is deliberately NOT a template domain: test fixtures use it for fake real owners (BUG-745 review)
_PLACEHOLDER = re.compile(r"^(?:\[[^\]]*\]|<?(?:your(?:\s.*)?|you@\S*|[^@\s<>]+@(?:[\w-]+\.)*(?:example\.(?:com|org|net)|[\w-]+\.(?:example|test))|(?:https?://)?(?:www\.)?(?:yoursite\S*|yourdomain\S*|example(?:\.\S*)?)|(?:jane|john)\s+doe|placeholder)>?|[+(]?(?:1[\W_]*)?5[\W_]*5[\W_]*5[\W_]*0[\W_]*1[\W_]*0[\W_]*0(?:[\W_]*1[\W_]*0[\W_]*0)?)$",
                             re.IGNORECASE)


class CannotRun(Exception):
    pass


def _files(push):
    """[(group, relpath, abspath)] of every document the gate reads."""
    out = []
    for group, sub in (("cards", "feed-cards"), ("after", "feed-after")):
        d = os.path.join(push, sub)
        if not os.path.isdir(d):
            if group == "cards":
                raise CannotRun("%s/ is missing" % sub)
            raise CannotRun("%s/ is missing (a cards-only directory is not a push tree)" % sub)
        for f in sorted(os.listdir(d)):
            if f.endswith(".json"):
                out.append((group, "%s/%s" % (sub, f), os.path.join(d, f)))
    if not any(g == "cards" for g, _r, _a in out):
        raise CannotRun("feed-cards/ holds no card")
    meta = os.path.join(push, "feed", "meta.json")
    if not os.path.isfile(meta):
        raise CannotRun("feed/meta.json is missing")
    out.append(("meta", "feed/meta.json", meta))
    return out


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        raise CannotRun("%s cannot be read (%s)" % (path, type(e).__name__))


def _canon(group, doc):
    if group == "meta" and isinstance(doc, dict) and isinstance(doc.get("source"), dict):
        doc = dict(doc, source={k: v for k, v in doc["source"].items() if k != "pushed_at"})
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def tree_digest(push):
    """sha256 over every scanned document; `source.pushed_at` is left out (every push restamps it)."""
    h = hashlib.sha256()
    for group, rel, path in _files(push):
        h.update(rel.encode("utf-8") + b"\0" + _canon(group, _load(path)).encode("utf-8") + b"\n")
    return h.hexdigest()


def _rows(prefix, node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            sub = "%s.%s" % (prefix, k)
            out.append((sub + "<key>", str(k)))
            _rows(sub, v, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _rows("%s[%d]" % (prefix, i), v, out)
    elif isinstance(node, str):
        out.append((prefix, node))


def identity(repo):
    """[(kind, literal)] for the owner's own identity: the resolved owner config plus the candidate profile."""
    import pii_gate
    old = pii_gate.REPO
    pii_gate.REPO = os.path.abspath(repo)
    try:
        owner = dict(pii_gate._resolve_owner())
    finally:
        pii_gate.REPO = old
    lits = [(k, v) for k, v in owner.items() if k in ("name", "email", "phone", "site") and v]
    prof = os.path.join(repo, ".claude", "skills", "job-application-assistant", "01-candidate-profile.md")
    try:
        text = open(prof, encoding="utf-8").read()
    except OSError:
        text = ""
    for kind, label in _PROFILE_FIELDS:
        m = re.search(r"^-\s*\*\*%s:\*\*\s*(.+?)\s*$" % label, text, re.M)
        if not m:
            continue
        v = m.group(1).strip()
        if _PLACEHOLDER.search(v):
            continue            # the shipped template, not filled in: it names nobody
        if kind == "linkedin":
            s = re.search(r"linkedin\.com/in/([A-Za-z0-9_-]{3,})", v)
            v = s.group(1) if s else ""
            kind = "linkedin slug"
        elif kind == "site":
            v = re.sub(r"^https?://", "", v).rstrip("/")
            v = v[:-5] if v.endswith("/work") else v
        if len(v) >= 4:
            lits.append((kind, v))
    seen, out = set(), []
    for k, v in lits:
        if (k, v.lower()) not in seen:
            seen.add((k, v.lower()))
            out.append((k, v))
    return out


def _literal_re(kind, lit):
    if kind == "phone":
        d = re.sub(r"\D", "", lit)[-10:]
        if len(d) < 10:
            return re.compile(re.escape(lit), re.I)
        return re.compile(r"(?<!\d)(?:\+?1\D{0,2})?\(?%s\)?\D{0,2}%s\D{0,2}%s(?!\d)" % (d[:3], d[3:6], d[6:]))
    return re.compile(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(lit), re.I)


def scan(push, repo):
    """-> (blocks, warns, n_docs); each hit is (group, path, hit, why)."""
    import pii_gate
    vocab = identity(repo)
    if not vocab:
        raise CannotRun("the identity vocabulary is empty (no profile, kit_config or card named him), so the "
                        "gate could not tell his data from anyone's")
    lits = [(k, v, _literal_re(k, v)) for k, v in vocab]
    own_text = {v.lower() for _k, v in vocab}
    files = _files(push)
    rows, group_of = [], {}
    for group, rel, path in files:
        doc = _load(path)
        root = "meta" if group == "meta" else rel[:-5]
        before = len(rows)
        _rows(root, doc, rows)
        for p, _b in rows[before:]:
            group_of[p] = group
    blocks, warns = [], []
    body = dict(rows)
    shapes, _w = pii_gate.scan_items(rows, (), (), (), owner=None)
    for p, hit, why in shapes:
        if hit.lower() in own_text or any(rx.fullmatch(hit) for _k, _v, rx in lits):
            continue          # his own literal: the literal tier below decides
        grp = group_of[p]
        if why == "LinkedIn profile slug" and grp != "meta":
            warns.append((grp, p, hit, "third-party LinkedIn slug (provenance)"))
        elif why == "street address" and grp != "meta":
            # a company's public office address in a research line is provenance, not a person's address
            warns.append((grp, p, hit, "street address in research text (provenance)"))
        else:
            blocks.append((grp, p, hit, why))
    for p, text in rows:
        grp = group_of[p]
        for kind, lit, rx in lits:
            for m in rx.finditer(text):
                if p.startswith(_OWNER_PATHS):
                    continue
                if _VOICE_TEXT.match(p) and kind in ("name", "site"):
                    a0 = text.rfind("\n", 0, m.start()) + 1
                    b0 = text.find("\n", m.end())
                    line = text[a0:(b0 if b0 >= 0 else len(text))]
                    # a bare name or site, or the site as a URL (a sign-off line): scheme, www. and a trailing / are not content
                    if re.sub(r"^(?:https?://)?(?:www\.)?|/$", "", line.strip(), flags=re.I).lower() == lit.lower():
                        continue
                blocks.append((grp, p, m.group(0), "his identity (%s)" % kind))
    return blocks, warns, len(files)


def _report(blocks, warns, n):
    def line(tag, items):
        by = {}
        for grp, p, hit, why in items:
            by.setdefault((grp, why), []).append((p, hit))
        for (grp, why), hs in sorted(by.items()):
            print("  %s %-5s %-34s %3d" % (tag, grp, why, len(hs)))
            for p, hit in hs[:6]:
                print("        %s" % p)
            if len(hs) > 6:
                print("        ... %d more" % (len(hs) - 6))
    print("STORE-DATA GATE: %d document(s) read, %d BLOCK hit(s), %d WARN hit(s)" % (n, len(blocks), len(warns)))
    line("BLOCK", blocks)
    line("WARN ", warns)
    tot = {}
    for grp, _p, _h, _w in blocks:
        tot[grp] = tot.get(grp, 0) + 1
    if blocks:
        print("  per file group: " + ", ".join("%s=%d" % kv for kv in sorted(tot.items())))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("push_dir")
    ap.add_argument("--repo", default=os.path.dirname(HERE))
    a = ap.parse_args(argv)
    push = os.path.abspath(a.push_dir)
    receipt = os.path.join(push, RECEIPT)
    try:
        if os.path.exists(receipt):
            os.unlink(receipt)       # a receipt only ever describes the run that wrote it
        blocks, warns, n = scan(push, a.repo)
        digest = tree_digest(push)
    except CannotRun as e:
        print("STORE-DATA GATE CANNOT RUN: %s. Nothing was checked, so this is NOT a pass." % e, file=sys.stderr)
        return 2
    _report(blocks, warns, n)
    # BUG-711 Slice 2: a boss called verified has a first-party source; the verdict rides in the same exit and receipt.
    import check_boss_sourced
    boss_rc = check_boss_sourced.main([push])
    if boss_rc != 0:
        print("STORE-DATA GATE: FAIL (exit 3). check_boss_sourced exited %d (BUG-711: a boss without a first-party source reads "
              "UNVERIFIED). Fix the builder, rebuild the feed, run again." % boss_rc)
        return 3
    if blocks:
        print("STORE-DATA GATE: FAIL (exit 3). Fix the builder, rebuild the feed, run again.")
        return 3
    print("STORE-DATA GATE: 0 hits (%d warn). The receipt is %s" % (len(warns), RECEIPT))
    with open(receipt, "w", encoding="utf-8") as fh:
        json.dump({"sha256": digest, "documents": n, "blocks": 0, "warns": len(warns), "boss_sourced": 0,
                   "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
