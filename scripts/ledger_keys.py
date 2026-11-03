#!/usr/bin/env python3
"""ledger_keys.py -- the one place that reads, mints and lists the decision-ledger signing keys.

WHY THIS EXISTS (kit issue #149). The BUILD gate trusts a ruling only when its `mac` verifies against
your key. The old code made a key whenever none existed, overwrote an empty key file, and returned an
EMPTY mac when it could not write the key folder, all without a word. Run from a different HOME, a
script minted a new key and every earlier ruling stopped verifying, while the gate said only "no valid
BUILD ruling recorded". Nothing was wrong with the rulings. The key was wrong, and nothing said so.

THE RULES THIS MODULE HOLDS
  1. Reading a key never creates one. An empty or whitespace key file counts as MISSING.
  2. Minting is O_EXCL and returns what is on disk, not what it just generated.
  3. A key is minted only for a ledger that holds no signed row. A ledger with signed rows and no key is
     a problem to REPORT, never to paper over with a new key.
  4. Nothing here ever returns an empty signature quietly. Callers get a reason to say out loud.
  5. A signed row carries `kid`, a short id of its key, OUTSIDE the eight signed fields, so a mismatch
     can be diagnosed. Rows without `kid` verify exactly as before.
  6. A key you already own can be recognized again through the RING. The ring is a short list
     (ring.json, in the ring folder) of key FILES you name. Adding one is a deliberate act
     (`ledger_keys.py add`), a key never joins because it happens to sit on disk, and neither the ring
     folder nor a listed key file may live inside the project. Nothing is re-signed and nothing is
     copied: a row verifies only if some key in the ring made its signature. A key file in the ring
     folder that is NOT on the list is shown as a stray and verifies nothing.

Standard library only.  Usage:
    python3 scripts/ledger_keys.py list                       # which keys, and how many rows each accounts for
    python3 scripts/ledger_keys.py add <keyfile> [--label X]  # put a key you own into the ring
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone

MAC_FIELDS = ("ts", "session", "question", "header", "answer", "ruling", "company", "source")
HOOK_SOURCES = ("posttooluse-hook", "userpromptsubmit-hook")
RING_DIRNAME = ".jobsearch-ledger-keys"
RING_MANIFEST = "ring.json"
_INSTALL_KEY_NAME = re.compile(r"^[0-9a-f]{32}\.key$")   # record_decision.install_keyfile(): a signing key, not a stray


class LedgerKeyError(Exception):
    """A key problem the caller must say out loud."""


def key_id(key):
    return hashlib.sha256(key).hexdigest()[:8]


def _mac(row, key):
    payload = json.dumps({f: row.get(f, "") for f in MAC_FIELDS}, sort_keys=True,
                         ensure_ascii=False).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def load_key(path):
    """The key in `path`, or b"". READ ONLY: never creates or changes anything. An empty file, a
    file of only whitespace, or an unreadable one is MISSING."""
    try:
        with open(os.path.expanduser(path), "rb") as fh:
            return fh.read().strip()
    except OSError:
        return b""


def _read_rows(ledger):
    rows = []
    try:
        with open(ledger, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
    except OSError:
        pass
    return rows


def ledger_has_signed_rows(ledger):
    return any(str(r.get("mac", "")).strip() for r in _read_rows(ledger))


def ledger_signed_state(ledger):
    """("none" | "signed" | "unknown", reason). "none" only when the ledger is MISSING or was read in
    full and holds no signed row. Anything that stops a full read (permissions, a folder in its place,
    bytes that are not text) or a damaged line that mentions a mac is "unknown", and the hook treats
    unknown like signed: it must never mint next to rulings it could not see."""
    if not os.path.exists(ledger) and not os.path.islink(ledger):
        return "none", ""
    signed = False
    damaged = False
    try:
        with open(ledger, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    if '"mac"' in line:
                        damaged = True
                    continue
                if isinstance(r, dict) and str(r.get("mac", "")).strip():
                    signed = True
    except (OSError, UnicodeDecodeError) as e:
        return "unknown", "cannot read the ledger at %s (%s)" % (ledger, getattr(e, "strerror", None) or e.__class__.__name__)
    if signed:
        return "signed", ""
    if damaged:
        return "unknown", "cannot read every line of the ledger at %s (a damaged line mentions a mac)" % ledger
    return "none", ""


def mint_key(path):
    """Create a new key at `path` with O_EXCL (mode 0600) and return the key that is ON DISK.
    If a non-empty key already exists it is returned and left alone. Raises LedgerKeyError if the
    folder cannot be written. Callers decide WHETHER minting is allowed (see signing_key_for_hook)."""
    path = os.path.expanduser(path)
    existing = load_key(path)
    if existing:
        return existing
    d = os.path.dirname(path) or "."
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        fresh = os.urandom(32).hex().encode()
        if os.path.exists(path):
            # An EMPTY file holds nothing to lose. Replace it atomically, never with O_TRUNC.
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".key-", suffix=".tmp")
            with os.fdopen(fd, "wb") as fh:
                fh.write(fresh)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        else:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(fresh)
    except FileExistsError:
        pass                            # another process won the race: use ITS key
    except OSError as e:
        raise LedgerKeyError("could not create the ledger key in %s (%s)" % (d, e.strerror or e))
    got = load_key(path)
    if not got:
        raise LedgerKeyError("the ledger key at %s is still empty after creating it" % path)
    return got


def ring_folder(keyfile, honor_env=False):
    """The ring folder. By default ALWAYS the one beside the signing key. JOBKIT_LEDGER_KEYRING is
    honored only when the caller asks (honor_env=True, the ledger_keys.py command line), never by the
    BUILD gate, the doctor or a rewriter: whoever can set the environment could otherwise point the
    gate at a ring of their own making and authorize anything."""
    env = os.environ.get("JOBKIT_LEDGER_KEYRING") if honor_env else ""
    if env:
        return os.path.expanduser(env)
    return os.path.join(os.path.dirname(os.path.expanduser(keyfile)) or ".", RING_DIRNAME)


def _manifest(rd):
    try:
        with open(os.path.join(rd, RING_MANIFEST), "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        return [e for e in doc.get("keys", []) if isinstance(e, dict) and e.get("path")]
    except (OSError, ValueError):
        return []


def ring_keys(keyfile, ring=None):
    """[(kid, key, label)] for every key file NAMED in the ring list whose bytes still match the id
    it was added under. A key file in the ring folder that is not on the list is not here."""
    rd = ring or ring_folder(keyfile)
    out = []
    for e in _manifest(rd):
        k = load_key(e["path"])
        if k and key_id(k) == e.get("kid"):
            out.append((e["kid"], k, str(e.get("label", ""))))
    return out


def ring_strays(keyfile, ring=None):
    """[(file name, key id)] for *.key files in the ring folder that are NOT on the ring list.
    They verify nothing. Doctor shows them so a stray is visible as a stray."""
    rd = ring or ring_folder(keyfile)
    listed = {os.path.realpath(e["path"]) for e in _manifest(rd)}
    out = []
    try:
        names = sorted(os.listdir(rd))
    except OSError:
        return out
    for n in names:
        p = os.path.join(rd, n)
        if n.endswith(".key") and not _INSTALL_KEY_NAME.match(n) and os.path.realpath(p) not in listed:
            k = load_key(p)
            if k:
                out.append((n, key_id(k)))
    return out


def verifying_keys(keyfile, ring=None):
    """[(kid, key, source)] every key a row may verify under: the signing key first, then the ring."""
    keys = []
    k = load_key(keyfile)
    if k:
        keys.append((key_id(k), k, "signing key"))
    seen = {x[0] for x in keys}
    for kid, key, label in ring_keys(keyfile, ring):
        if kid not in seen:
            keys.append((kid, key, "ring" + (": " + label if label else "")))
            seen.add(kid)
    return keys


def verify_kid(row, keys):
    """The id of the key whose signature matches this row, or None."""
    m = str(row.get("mac", "") if isinstance(row, dict) else "")
    if not m:
        return None
    for kid, key, _src in keys:
        if hmac.compare_digest(_mac(row, key), m):
            return kid
    return None


def _inside(path, root):
    r, p = os.path.realpath(root), os.path.realpath(path)
    return p == r or p.startswith(r + os.sep)


def ring_add(src, keyfile, label="", ring_dir=None, project_root=None, honor_env=False, install=None):
    """Put a key you own into the ring: record its FILE and id in ring.json. Deliberate, reviewable,
    never automatic, and nothing is copied. Returns the key id. Refuses an empty key, and refuses a
    ring folder or key file inside the project (a key there could be committed or synced)."""
    rd = os.path.expanduser(ring_dir) if ring_dir else ring_folder(keyfile, honor_env=honor_env)
    src = os.path.abspath(os.path.expanduser(src))
    key = load_key(src)
    if not key:
        raise LedgerKeyError("the key file %s is empty or unreadable, so there is nothing to add" % src)
    if project_root:
        for what, path in (("ring folder", rd), ("key file", src)):
            if _inside(path, project_root):
                raise LedgerKeyError("the %s %s is inside the project folder %s. A key there can be "
                                     "committed or synced. Keep keys outside the project." % (what, path, project_root))
    kid = key_id(key)
    os.makedirs(rd, mode=0o700, exist_ok=True)
    entries = [e for e in _manifest(rd) if e.get("kid") != kid]
    entry = {"kid": kid, "path": src, "label": label, "added": datetime.now(timezone.utc).isoformat()}
    if install:
        entry["install"] = install      # the ring widens KEYS, never installs (signing merge, invariant 5)
    entries.append(entry)
    fd, tmp = tempfile.mkstemp(dir=rd, prefix=".ring-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"keys": entries}, fh, indent=1)
    os.replace(tmp, os.path.join(rd, RING_MANIFEST))
    return kid


def signing_key_for_hook(ledger, keyfile):
    """(key, kid, problem) for a hook about to write a row.

    key present   -> (key, kid, "")
    no key, ledger has NO signed row -> mint one (the first ever ruling) -> (key, kid, "")
    no key, ledger HAS signed rows   -> mint NOTHING -> (b"", "", loud reason)
    cannot write the key folder      -> (b"", "", loud reason)
    `problem` is a sentence the caller prints to stderr and records on the row."""
    key = load_key(keyfile)
    if key:
        return key, key_id(key), ""
    state, why = ledger_signed_state(ledger)
    if state == "unknown":
        return b"", "", ("%s, and this machine has no usable key at %s. Not creating a new key: if the ledger "
                         "holds signed rulings a new key would orphan every one of them. This row is recorded "
                         "UNSIGNED. Fix the ledger's permissions or restore it, then run again." % (why, keyfile))
    if state == "signed":
        return b"", "", ("the decision ledger already holds signed rulings, but this machine does not have "
                         "the key that signed them (no usable key at %s). Not creating a new key: it would "
                         "orphan every earlier ruling. This row is recorded UNSIGNED. Find the original key "
                         "and add it with:  python3 scripts/ledger_keys.py add <keyfile>" % keyfile)
    try:
        key = mint_key(keyfile)
        return key, key_id(key), ""
    except LedgerKeyError as e:
        return b"", "", ("%s. This row is recorded UNSIGNED, so it will not authorize anything." % e)


def rewrite_guard(ledger, keyfile):
    """For any script that rewrites existing ledger rows. Returns the signing key, or raises.
    Refuses when there is no key, and when the rows carry key ids and none is a key we hold."""
    key = load_key(keyfile)
    if not key:
        raise LedgerKeyError("no usable ledger key at %s. Refusing to rewrite a signed ledger: a new key "
                             "would orphan every existing ruling." % keyfile)
    held = {kid for kid, _k, _s in verifying_keys(keyfile)}
    carried = {str(r.get("kid")) for r in _read_rows(ledger) if r.get("kid")}
    if carried and not (carried & held):
        raise LedgerKeyError("the ledger's rows were signed by key id(s) %s, and this machine holds %s. "
                             "Refusing to rewrite them." % (", ".join(sorted(carried)),
                                                            ", ".join(sorted(held)) or "no key"))
    return key


def is_unsigned_record(row):
    """A ruling recorded with no usable key (proxy 70, 2026-10-03): no mac at all. It is a record of what the
    person said, never an authorization, and it is COUNTED NOWHERE: not as a hook row, not as unverified, not
    as a BUILD. (The BUG-486 lesson: unsigned captures once inflated a ledger and the app's rate.)"""
    return isinstance(row, dict) and not str(row.get("mac", "")).strip()


# ── BUG-778 (#380): A ROW MINTED FROM ANOTHER SESSION'S MESSAGE IS NOT THE OWNER'S DECISION ────────────────────────────────────────────────────
# BUG-775 stopped the typed-prompt hook from minting rows out of peer messages, but 109 BUILD rows (19 companies) and about 1,685 SKIP rows
# minted before the fix are in the ledger, MAC-valid, and every reader trusted them. The ledger is never edited; the READERS quarantine, through this
# one function. The marker list is record_chat_ruling.INJECTED, read from its SOURCE FILE next to this one (a literal tuple) and never copied, so a
# marker added there reaches every reader. Matching is the same rule as record_chat_ruling.is_injected: case-insensitive, anywhere in the text.
# Fails CLOSED: if the list cannot be read, a typed-path row (userpromptsubmit-hook) is treated as peer-minted and a picker-path row is not.
_MARKERS = None


def _load_marker_source():
    import ast
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "record_chat_ruling.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "INJECTED" for t in node.targets):
            vals = ast.literal_eval(node.value)
            if vals and all(isinstance(v, str) for v in vals):
                return tuple(v.lower() for v in vals)
    raise ValueError("record_chat_ruling.INJECTED not found")


def row_is_peer_minted(row):
    """True when the row's own text (answer, question, header) carries a peer-session or harness marker, so it authorizes nothing and shows no verdict."""
    global _MARKERS
    row = row if isinstance(row, dict) else {}
    try:
        if _MARKERS is None:
            _MARKERS = _load_marker_source()
    except Exception:
        return str(row.get("source") or "") == "userpromptsubmit-hook"
    text = " ".join(str(row.get(k) or "") for k in ("answer", "question", "header")).lower()
    return any(m in text for m in _MARKERS)


def ledger_report(ledger, keyfile):
    """Counts the doctor and the gate report: rows per key, rows no key verifies, BUILD rows. Unsigned records
    are reported only as `unsigned` and are in no other count."""
    keys = verifying_keys(keyfile)
    hook = [r for r in _read_rows(ledger) if r.get("source") in HOOK_SOURCES]
    unsigned = sum(1 for r in hook if is_unsigned_record(r))
    rows = [r for r in hook if not is_unsigned_record(r)]
    per = {kid: 0 for kid, _k, _s in keys}
    unverified = 0
    build_rows = build_ok = 0
    for r in rows:
        kid = verify_kid(r, keys)
        if kid:
            per[kid] += 1
        else:
            unverified += 1
        if r.get("ruling") == "BUILD":
            build_rows += 1
            build_ok += 1 if kid else 0
    return {"keys": [(kid, src) for kid, _k, src in keys], "per_key": per, "hook_rows": len(rows),
            "strays": ring_strays(keyfile), "unsigned": unsigned,
            "unverified": unverified, "build_hook_rows": build_rows, "build_verified": build_ok,
            "signing_key_present": bool(load_key(keyfile))}


def _cli():
    ap = argparse.ArgumentParser(description="Show or extend the decision-ledger key ring.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ledger", default=os.path.join("documents", "decision-ledger.jsonl"))
    common.add_argument("--signing-keyfile", default=os.environ.get("JOBKIT_LEDGER_KEYFILE", "~/.jobsearch-ledger-key"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", parents=[common], help="show the keys and how many rows each accounts for")
    ad = sub.add_parser("add", parents=[common], help="put a key you own into the ring")
    ad.add_argument("keyfile")
    ad.add_argument("--label", default="")
    a = ap.parse_args()
    if a.cmd == "add":
        project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        ring_dir, install = None, None
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import record_decision as _rd
            ring_dir, install = _rd._keydir(), _rd.install_id()
            project = _rd.INSTALL_ROOT       # the install this script lives in, never the session folder
        except Exception:
            pass
        try:
            kid = ring_add(a.keyfile, a.signing_keyfile, label=a.label, honor_env=ring_dir is None,
                           project_root=project, ring_dir=ring_dir, install=install)
        except LedgerKeyError as e:
            print("STOPPED: %s" % e)
            return 1
        print("Added key id %s to the ring list (%s)." % (kid, os.path.join(
            ring_dir or ring_folder(a.signing_keyfile, honor_env=True), RING_MANIFEST)))
        print("Nothing was re-signed or copied. Rows signed by this key now verify; rows signed by any other key still do not.")
        return 0
    rep = ledger_report(a.ledger, a.signing_keyfile)
    print("Signing key: %s" % ("present" if rep["signing_key_present"] else "MISSING (%s)" % a.signing_keyfile))
    for kid, src in rep["keys"]:
        print("  key %s  (%s)  accounts for %d hook rows" % (kid, src, rep["per_key"].get(kid, 0)))
    for name, kid in rep["strays"]:
        print("  STRAY key file %s (id %s) is in the ring folder but NOT on the ring list; it verifies nothing"
              % (name, kid))
    print("Hook rows: %d | verify under no key here: %d | BUILD rulings: %d, of which verify: %d"
          % (rep["hook_rows"], rep["unverified"], rep["build_hook_rows"], rep["build_verified"]))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
