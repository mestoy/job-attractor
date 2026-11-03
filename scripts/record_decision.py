#!/usr/bin/env python3
"""record_decision.py — PostToolUse hook on AskUserQuestion.

Appends YOUR ACTUAL ANSWER to the decision ledger.

WHY THIS EXISTS:
Every other gate in this kit is satisfied by evidence the ASSISTANT supplies. A
`--lacivita-check pass` flag is the assistant typing a word. `--praise-phrasing` proves a
string is in the body, not that you chose it. So an assistant can satisfy every gate
without you having ruled on anything, and the first symptom is a drafted email for a
company you never approved.

This hook is written by the HARNESS from your real response, not by the assistant.
That makes it the one piece of non-forgeable evidence in the system, and it is what
`check_preview.py` consults to enforce the BUILD GATE.

Fail-open by design: a hook crash must never block legitimate work. A MISSING ledger
entry blocks (that's the gate); a BROKEN hook does not.
"""
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger_keys as _lk
import ledger_write as _lw
try:
    from kit_config import LEDGER_PATH, LEDGER_KEYFILE
except Exception:
    LEDGER_PATH = os.path.join("documents", "decision-ledger.jsonl")
    LEDGER_KEYFILE = "~/.jobsearch-ledger-key"

# ⛔ THE LEDGER BELONGS TO THE INSTALL THIS SCRIPT LIVES IN (kit #121, 2026-09-15).
# PATH DIVERGENCE, first round: this once defaulted to "." (cwd) while check_preview.py defaulted
# to the script's parent, so the WRITER and the READER used different files. Second round: both
# read CLAUDE_PROJECT_DIR FIRST. The harness sets that to whatever folder the Claude session was
# opened in, so mail-draft.sh run from a session rooted anywhere else read THAT folder's ledger:
# a partner's own signed ruling was refused, and another install's ledger could authorize this
# install's send. Hooks are wired as "$CLAUDE_PROJECT_DIR/scripts/<hook>.py", so for every hook
# the script's own install IS the project dir; resolving from the script location changes nothing
# on the hook path and fixes every other caller. JOBKIT_LEDGER_PATH (absolute) still relocates the
# file, which grants nothing: the key below is bound to the install, not to the ledger path.
INSTALL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = INSTALL_ROOT
LEDGER = os.path.join(_REPO, LEDGER_PATH)

# ⛔ ONE KEY PER INSTALL, OUTSIDE EVERY INSTALL. Key material lives outside the project so it is
# never committed, never synced to anyone else's copy of this kit, and never sitting next to the
# ledger it authenticates. It used to be ONE file per HOME (LEDGER_KEYFILE), so two installs on one
# machine shared it and a signed row copied from one install's ledger verified in the other. The
# key is now <account home>/.jobsearch-ledger-keys/<sha256(realpath of the install)>.key.
#
# SECURITY NOTES (kit #121, hardened after the non-author review of 2026-09-15). Each is tested in
# tests/test_partner_authorization.py.
#   * The key dir comes from the ACCOUNT's home (pwd), never from HOME or any other environment
#     variable (review L1): an env prefix on a Bash call must not choose the key a send is verified
#     with. The only override is the KEYDIR line below, which test sandboxes edit in their COPY.
#     If the system user list has no entry for this account there is NO key folder at all: signing
#     stops with a message and verification fails closed. HOME is never a fallback and no relative
#     "~" folder is ever created (second review N1).
#   * The key dir must be a real directory (not a symlink) owned by this account with no group or
#     other permission bits, and is created 0700 (L2). Otherwise nothing is signed or verified.
#   * The key is written to a random 0600 temp file and hard-linked into place, so it is never seen
#     half-written. An existing key that is empty, a symlink, not ours, or readable by others is
#     never overwritten: signing stops with a message and verification fails closed (L4).
#   * LEGACY_KEYFILE is the pre-#121 per-HOME key. Rows it signed stay verifiable through a SNAPSHOT
#     of the MACs of the rows in THIS install's ledger that verify under it, tagged with the install
#     key and pinned to the legacy key's fingerprint. It is taken AT MOST ONCE PER INSTALL, behind an
#     O_EXCL marker (<id>.migrated) that is never removed by the code (M2): a deleted or recreated key
#     fails the old tag and legacy rows are refused, it never re-takes the snapshot. The snapshot is
#     written through a random temp file (O_EXCL, no symlink follow) and renamed into place (L3).
#   * ⚠️ DOCUMENTED LIMIT (M1). Legacy rows carry no install binding, so a legacy-signed row copied into
#     this install's ledger BEFORE the snapshot is taken is indistinguishable from a genuine one and
#     is absorbed. No row count or timestamp taken at snapshot time can separate them, because the
#     copy already sits in the ledger at that moment. The window is shrunk, not closed: install.sh
#     (every install and every Update Kit run) calls `record_decision.py --migrate`, so the snapshot is
#     taken at update time rather than at the first gate run of a later session. That install-time
#     --migrate is also the closure for the second review's N2: before migration the legacy key PATH
#     is still environment-selectable (JOBKIT_LEDGER_KEYFILE), so a first gate run under a chosen env
#     could pin a chosen legacy key; an installed or updated folder has already pinned the real one.
#     An install run under sudo migrates root's key folder, not the owner's.
#   * --migrate also BACKFILLS a missing <id>.migrated marker for a key that has none (a crash between
#     publishing the key and creating the marker, or a key made by pre-44facf6 branch code), with no
#     snapshot, so deleting that key later cannot re-snapshot (second review N3). The backfill is
#     deliberately not done on gate runs: it could race a concurrent first run's own migration and
#     drop that run's legacy snapshot.
#   * Residual limits: anyone who can write to the key dir can also read the keys and sign directly;
#     deleting the key, snapshot AND marker together re-takes the snapshot (and voids every ruling
#     signed since, visibly); a moved install folder starts a new key and cannot re-snapshot.
#   * Symlinked script files (L5): check_preview passes its own unresolved install root, so the key is
#     chosen by the install the gate was invoked from; Python may still load this module's CODE from
#     the symlink target, which is the same code.
LEGACY_KEYFILE = os.path.expanduser(LEDGER_KEYFILE)
KEYDIR_NAME = ".jobsearch-ledger-keys"
KEYDIR = None
KEY_ERROR = ""

# Fields covered by the MAC. Order is fixed so the digest is reproducible.
MAC_FIELDS = ("ts", "session", "question", "header", "answer", "ruling", "company", "source")
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _account_home():
    """The account's home from the system user list, or None. Never HOME (reviews L1 and N1)."""
    try:
        import pwd
        home = pwd.getpwuid(os.geteuid()).pw_dir
    except Exception:
        return None
    return home if home and os.path.isabs(home) else None


def _keydir():
    if KEYDIR:
        return KEYDIR
    home = _account_home()
    return os.path.join(home, KEYDIR_NAME) if home else None


NO_HOME = ("this account has no home entry in the system user list, so no private key folder can be "
           "chosen (HOME is never used for this)")


def install_id(root=None) -> str:
    return hashlib.sha256(os.path.realpath(root or INSTALL_ROOT).encode("utf-8")).hexdigest()[:32]


def install_keyfile(root=None) -> str:
    d = _keydir()
    return os.path.join(d, install_id(root) + ".key") if d else ""


def _snapshot_file(root=None) -> str:
    d = _keydir()
    return os.path.join(d, install_id(root) + ".legacy.json") if d else ""


def _private(st) -> bool:
    return st.st_uid == os.geteuid() and not (st.st_mode & 0o077)


def _safe_keydir(create: bool):
    d = _keydir()
    if not d:
        return None, NO_HOME
    if create:
        try:
            os.makedirs(d, mode=0o700, exist_ok=True)
        except Exception as e:
            return None, f"could not create the key folder {d} ({e})"
    try:
        st = os.lstat(d)
    except FileNotFoundError:
        return None, f"the key folder {d} does not exist"
    except Exception as e:
        return None, f"could not inspect the key folder {d} ({e})"
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return None, f"the key folder {d} is a symlink or not a folder"
    if not _private(st):
        return None, f"the key folder {d} is not private to you (it must be yours, mode 0700)"
    return d, ""


def _read_install_key(path):
    try:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    except FileNotFoundError:
        return b"", "missing"
    except OSError as e:
        return b"", f"the key file {path} could not be opened safely ({e.strerror})"
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode) or not _private(st):
            return b"", f"the key file {path} is not a private file of yours (mode 0600)"
        k = fh.read().strip()
    return (k, "") if k else (b"", f"the key file {path} is empty")


def _read_legacy_key(path) -> bytes:
    if not path:
        return b""
    try:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
        with os.fdopen(fd, "rb") as fh:
            return fh.read().strip()
    except Exception:
        return b""


def _legacy_fp(key: bytes, legacy: bytes) -> str:
    return hmac.new(key, b"legacy-key-fingerprint\n" + legacy, hashlib.sha256).hexdigest() if legacy else ""


def _snapshot_tag(key: bytes, fp: str, macs) -> str:
    body = "legacy-snapshot-v2\n" + fp + "\n" + "\n".join(sorted(set(macs)))
    return hmac.new(key, body.encode("utf-8"), hashlib.sha256).hexdigest()


def _migrate_once(key: bytes, ledger: str, legacy_keyfile: str, root, d: str) -> None:
    """Take the legacy snapshot AT MOST ONCE for this install (review M2)."""
    marker = os.path.join(d, install_id(root) + ".migrated")
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
    except FileExistsError:
        return                      # already taken once; a recreated key never re-snapshots
    taken = datetime.now(timezone.utc).isoformat()
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(taken + "\n")
    legacy = _read_legacy_key(legacy_keyfile)
    macs = set()
    if legacy and os.path.exists(ledger):
        with open(ledger, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                m = str(row.get("mac", "")) if isinstance(row, dict) else ""
                if m and hmac.compare_digest(row_mac(row, legacy), m):
                    macs.add(m)
    fp = _legacy_fp(key, legacy)
    doc = {"v": 2, "install": os.path.realpath(root or INSTALL_ROOT), "taken": taken,
           "legacy_fp": fp, "macs": sorted(macs), "tag": _snapshot_tag(key, fp, macs)}
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".legacy-", suffix=".tmp")   # O_EXCL, 0600, random name
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        os.replace(tmp, _snapshot_file(root))                             # rename never follows a link
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def install_key(create=True, ledger=None, legacy_keyfile=None, root=None) -> bytes:
    """This install's HMAC key, or b"" with KEY_ERROR set. Never overwrites an existing key file."""
    global KEY_ERROR
    KEY_ERROR = ""
    d, why = _safe_keydir(create)
    if not d:
        KEY_ERROR = why
        return b""
    path = os.path.join(d, install_id(root) + ".key")
    k, why = _read_install_key(path)
    if k:
        return k
    if why != "missing" or not create:
        KEY_ERROR = "" if why == "missing" else why
        return b""
    k = os.urandom(32).hex().encode()
    try:
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".key-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(k)
                fh.flush()
                os.fsync(fh.fileno())
            os.link(tmp, path)          # atomic publish; FileExistsError when another process won
        finally:
            os.unlink(tmp)
    except FileExistsError:
        k, why = _read_install_key(path)
        KEY_ERROR = "" if k else why
        return k
    except Exception as e:
        KEY_ERROR = f"could not create the key in {d} ({e})"
        return b""
    try:
        _migrate_once(k, ledger or LEDGER,
                      LEGACY_KEYFILE if legacy_keyfile is None else legacy_keyfile, root, d)
    except Exception:
        pass                            # marker without snapshot: legacy rows refused, fails closed
    return k


def backfill_marker(root=None) -> bool:
    """Create <id>.migrated exclusively for an existing key that has none. Never snapshots (N3)."""
    d, _why = _safe_keydir(False)
    if not d:
        return False
    try:
        fd = os.open(os.path.join(d, install_id(root) + ".migrated"),
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
    except FileExistsError:
        return False
    except Exception:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("backfilled " + datetime.now(timezone.utc).isoformat() + "\n")
    return True


def key_status(root=None):
    """(status, reason, fix) for doctor.py: "ok", "missing" or "unsafe". Creates nothing, never
    reads key bytes into the result."""
    migrate = "python3 scripts/record_decision.py --migrate"
    d = _keydir()
    if not d:
        return "unsafe", NO_HOME, "run the kit as a user account that has a home folder"
    try:
        st = os.lstat(d)
    except FileNotFoundError:
        return "missing", "no signing key yet for this install", migrate
    except Exception as e:
        return "unsafe", f"the key folder {d} could not be inspected ({e})", f"check {d}, then {migrate}"
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return ("unsafe", f"the key folder {d} is a symlink or not a folder",
                f"replace {d} with a real folder of your own, then {migrate}")
    if st.st_uid != os.geteuid():
        return "unsafe", f"the key folder {d} is not owned by you", f"chown $(id -u) {d} && chmod 700 {d}"
    if st.st_mode & 0o077:
        return "unsafe", f"the key folder {d} is open to other users", f"chmod 700 {d}"
    path = os.path.join(d, install_id(root) + ".key")
    try:
        fst = os.lstat(path)
    except FileNotFoundError:
        return "missing", "no signing key yet for this install", migrate
    except Exception as e:
        return "unsafe", f"the key file {path} could not be inspected ({e})", f"check {path}, then {migrate}"
    regive = "; rulings recorded before then have to be given again"
    if stat.S_ISLNK(fst.st_mode) or not stat.S_ISREG(fst.st_mode):
        return "unsafe", f"the key file {path} is a symlink or not a file", f"remove {path}, then {migrate}{regive}"
    if fst.st_uid != os.geteuid():
        return "unsafe", f"the key file {path} is not owned by you", f"chown $(id -u) {path} && chmod 600 {path}"
    if fst.st_mode & 0o077:
        return "unsafe", f"the key file {path} is readable by other users", f"chmod 600 {path}"
    if fst.st_size == 0:
        return "unsafe", f"the key file {path} is empty", f"remove {path}, then {migrate}{regive}"
    if not os.path.lexists(os.path.join(d, install_id(root) + ".migrated")):
        return "missing", "the key has no one-time migration marker yet", migrate
    return "ok", "signing key ready for this install", ""


def _key() -> bytes:
    """The key every WRITER signs with: this install's own key, or b"" with KEY_ERROR set. A writer never creates one:
    a key is created only by `--migrate` (invariant 3 of the signing merge design), which checks the ledger first."""
    return install_key(create=False)


def key_error_message() -> str:
    return ("⛔ Ruling recorded UNSIGNED: this install's signing key is unusable ("
            + (KEY_ERROR or "no key has been created for this install yet") + "). The row is kept as a "
            "record, and it authorizes nothing: no gate will count it. Run: python3 scripts/doctor.py, "
            "then python3 scripts/record_decision.py --migrate. If the key file is empty or damaged, remove "
            "that one file; rulings recorded before then, including ones from before the kit #121 update, "
            "have to be given again too.")


def ledger_verifier(ledger=None, legacy_keyfile=None, root=None):
    """A `row -> bool` MAC check bound to THIS install, or None when no key can be had.

    True only for a row signed with this install's key, or a legacy-key row whose MAC is in this
    install's tagged snapshot, checked with the same legacy key the snapshot was taken with.
    """
    ledger = ledger or LEDGER
    lk = LEGACY_KEYFILE if legacy_keyfile is None else os.path.expanduser(legacy_keyfile)
    # A READ never mints: a gate that created a key here could orphan every earlier ruling (the 09-27 mint).
    key = install_key(create=False, ledger=ledger, legacy_keyfile=lk, root=root)
    if not key:
        return None
    allowed, legacy = frozenset(), b""
    try:
        fd = os.open(_snapshot_file(root), os.O_RDONLY | _NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        macs = [str(m) for m in doc.get("macs", [])]
        fp = str(doc.get("legacy_fp", ""))
        if fp and hmac.compare_digest(_snapshot_tag(key, fp, macs), str(doc.get("tag", ""))):
            cand = _read_legacy_key(lk)
            if cand and hmac.compare_digest(_legacy_fp(key, cand), fp):
                allowed, legacy = frozenset(macs), cand
    except Exception:
        pass

    ring = _same_install_ring(root)

    def ok(row) -> bool:
        m = str(row.get("mac", "")) if isinstance(row, dict) else ""
        if not m:
            return False
        if hmac.compare_digest(row_mac(row, key), m):
            return True
        if bool(legacy) and m in allowed and hmac.compare_digest(row_mac(row, legacy), m):
            return True
        # The ring is consulted LAST: it widens which keys count, never which install they count in.
        rk = ring.get(str(row.get("kid", "")))
        return bool(rk) and hmac.compare_digest(row_mac(row, rk), m)

    return ok


def legacy_status(ledger=None, legacy_keyfile=None, root=None):
    """(rows, present) for the doctor: how many ledger rows verify only THROUGH the legacy per-HOME key file
    (their MACs are in this install's tagged snapshot), and whether that file is here and is still the key the
    snapshot was taken with. (0, True) when there is nothing tagged. Read-only; never prints key material."""
    ledger = ledger or LEDGER
    lk = LEGACY_KEYFILE if legacy_keyfile is None else os.path.expanduser(legacy_keyfile)
    key = install_key(create=False, root=root)
    if not key:
        return 0, True
    try:
        fd = os.open(_snapshot_file(root), os.O_RDONLY | _NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        macs = [str(m) for m in doc.get("macs", [])]
        fp = str(doc.get("legacy_fp", ""))
        if not (fp and macs and hmac.compare_digest(_snapshot_tag(key, fp, macs), str(doc.get("tag", "")))):
            return 0, True
    except Exception:
        return 0, True
    tagged = set(macs)
    rows = 0
    try:
        with open(ledger, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and str(row.get("mac", "")) in tagged:
                    rows += 1
    except OSError:
        pass
    cand = _read_legacy_key(lk)
    present = bool(cand) and hmac.compare_digest(_legacy_fp(key, cand), fp)
    return rows, present


def ring_count(root=None) -> int:
    """How many extra verifying keys were added IN THIS INSTALL and still count (doctor's ring line)."""
    return len(_same_install_ring(root))


def _same_install_ring(root=None) -> dict:
    """{kid: key} for the ring entries that were added IN THIS INSTALL (signing merge, invariant 5). The list
    lives in the install's private key folder beside its key, never anywhere an environment variable can
    point. An entry counts only if it carries this install's id, its key file sits outside the project tree,
    and the file's bytes still match the id it was added under. Anything else verifies nothing."""
    d, _why = _safe_keydir(False)
    if not d:
        return {}
    try:
        fd = os.open(os.path.join(d, _lk.RING_MANIFEST), os.O_RDONLY | _NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            if not _private(os.fstat(fh.fileno())):
                return {}
            doc = json.load(fh)
        entries = [e for e in doc.get("keys", []) if isinstance(e, dict)]
    except Exception:
        return {}
    me = install_id(root)
    home = os.path.realpath(root or INSTALL_ROOT)
    out = {}
    for e in entries:
        path = e.get("path")
        if e.get("install") != me or not path:
            continue
        real = os.path.realpath(os.path.expanduser(str(path)))
        if real == home or real.startswith(home + os.sep):
            continue                    # a key kept inside the project could be committed or synced
        k = _read_legacy_key(real)
        if k and _lk.key_id(k) == e.get("kid"):
            out[str(e["kid"])] = k
    return out


def row_mac(row: dict, key: bytes) -> str:
    """Deterministic HMAC over the row's semantic fields (excludes 'mac' itself)."""
    if not key:
        return ""
    payload = json.dumps(
        {f: row.get(f, "") for f in MAC_FIELDS}, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

# BUILD is an EXACT-MATCH whitelist, never a regex over free text.
#
# REWRITTEN after a red-team found the regex version converted REFUSALS into AUTHORIZATIONS.
# The old rule was `SKIP and not BUILD -> SKIP; BUILD -> BUILD`, so any answer containing both
# words resolved to BUILD:
#     "don't build" -> BUILD          "do not build" -> BUILD
#     "Not yet, build next week" -> BUILD              "Go ahead and skip it" -> BUILD
#     "skip the email but build the resume" -> BUILD
# Each of those then got a VALID HMAC, so the ledger carried cryptographic proof of a decision
# the human never made — strictly worse than an unsigned forgery, because the audit trail
# corroborates it. Meanwhile genuine approvals ("yes", "Do it") classified as OTHER.
#
# Now: negation wins outright, and BUILD requires an exact match against a short literal set
# that the scorecard template emits as option labels. Paraphrase and free text NEVER classify
# as BUILD — they fall through to OTHER, which does not authorize anything.
# NARROWED, WITHOUT weakening the fail-closed property. Negation winning outright over the WHOLE
# answer fixed refusals-become-authorizations, but over-corrected: it also inverted real decisions
# whose VERDICT was affirmative and whose JUSTIFICATION merely contained a negative word, e.g.
#     "Keep it, X is not the mission"      -> recorded SKIP
#     "Build it, and negotiate Y later"    -> recorded SKIP
#     "Both in one pass"                   -> recorded SKIP  ("pass", the engineering sense)
# The affirmative opener was never consulted, because negation returned first.
#
# THE FIX: negation may only veto from the VERDICT CLAUSE (before the first comma). No comma means
# the whole answer is the verdict, so every red-teamed refusal ("don't build", "Not yet, build next
# week", "Go ahead and skip it", "skip the email but build the resume") behaves exactly as before.
# `pass` also lost its bare form; a bare "pass" answer is still caught verbatim by SKIP_EXACT.
NEGATION = re.compile(r"(?:\bdon'?t\b|\bdo not\b|\bnever\b|\bnot\b|\bno\b|\bskip\b|\bdrop\b|"
                      r"\bhold\b|\bpass on\b|\blater\b|\bnot now\b|\bnot yet\b)", re.I)

BUILD_EXACT = {
    "build", "build it", "build this", "build now",
    "yes build", "yes, build", "yes build it", "approve build", "approved build",
}
SKIP_EXACT = {"skip", "skip it", "drop", "drop it", "hold", "pass", "no", "not now"}

# The safety invariant the narrowing rests on, checked at import rather than in prose:
# if a BUILD label ever contained a negation token, moving the negation check could
# authorize something. It cannot, because it never can.
assert not any(NEGATION.search(_b) for _b in BUILD_EXACT), \
    "a BUILD_EXACT label contains a negation token — the clause-scoped check is unsafe"


def _norm(a: str) -> str:
    a = (a or "").strip().lower()
    # kit #166 bug 1: a "(Recommended)"/"(recommended)" suffix on a picker's default option is
    # display framing, not part of the ruling -- strip it before the exact-match lookups below so
    # "Build (Recommended)" still classifies as BUILD instead of falling through to OTHER.
    a = re.sub(r"\(\s*recommended\s*\)", " ", a)
    a = re.sub(r"[^a-z0-9,\s']", " ", a)
    return re.sub(r"\s+", " ", a).strip()


def _verdict_clause(a: str) -> str:
    """The part of the answer carrying the RULING, not the reasoning.

    A ruling routinely names what did NOT disqualify a thing ("Keep it, X is not the mission"), so a
    negation in a trailing clause is evidence ABOUT the verdict, not the verdict itself.
    """
    return a.split(",", 1)[0].strip() or a


# ── NON-AUTHORIZING VERDICT VOCABULARY (2026-09-12) ─────────────────────────────────────────
# BUILD is the only ruling anything downstream authorizes on, so unlike BUILD_EXACT/SKIP_EXACT
# these match on the LEADING word of the verdict clause rather than the whole string — the
# worst a false match can do is mislabel an audit row, never unlock a send. Mirrors
# rule_card.py's own GLYPHS vocabulary (BUILD, RADAR, PARK, DROP, SENT); DROP is left alone
# because it already lands on SKIP (via SKIP_EXACT / the NEGATION word list), not OTHER.
VERDICT_PREFIX = {"park": "PARK", "radar": "RADAR", "sent": "SENT"}


def classify(answer: str) -> str:
    """BUILD only on an EXACT affirmative ruling. Ambiguity and negation are never BUILD."""
    if not answer:
        return "UNKNOWN"
    a = _norm(answer)
    if a in SKIP_EXACT:
        return "SKIP"
    if a in BUILD_EXACT:
        return "BUILD"  # exact whole-string whitelist; provably contains no negation (see assert)
    clause = _verdict_clause(a)
    if NEGATION.search(clause):
        return "SKIP"  # a refusal, a conditional, or a deferral — never an authorization
    for word, verdict in VERDICT_PREFIX.items():
        if re.match(rf"^{word}\b", clause):
            return verdict
    return "OTHER"  # free text / paraphrase: recorded for audit, authorizes nothing


# ── BUILD BY AFFIRMATION-IN-CONTEXT ───────────────────────────────────────────────────────────
# classify() is an exact-match whitelist ON PURPOSE (a regex over a bare answer once turned refusals
# into authorizations). But that whitelist only knows the scorecard's option labels ("build", "yes,
# build"). A plain affirmation one step later — "yes, please proceed", picking an "Apple Mail draft"
# channel — is free text, so no BUILD row is written and both gates false-block work you plainly
# authorized. The fix reads the ANSWER together with the QUESTION as CONTEXT: a plain affirmation
# promotes to BUILD only when the QUESTION the assistant asked is itself a build/outreach step.
#   * NON-FORGEABLE: the RULING still comes from YOUR answer (harness-written); the assistant controls
#     only the CONTEXT. Any negation in the answer wins outright and the row is SKIP.
#   * NO OVER-MATCH: a bare "yes"/"ok" promotes only inside a build-context question. "Which company
#     next? -> yes" has no build context, so it stays OTHER and authorizes nothing.
BUILD_CONTEXT = re.compile(
    r"\b(?:build|draft|drafting|outreach|scorecard|boss[\s-]*match|praise\s*beat|"
    r"two[\s-]*stage|compose|apple\s*mail|mail\s*draft|gmail\s*draft|"
    r"send\s+(?:the\s+)?(?:email|note|outreach|draft|message)|"
    r"stage\s+(?:it|this|the\s+)?(?:email|outreach|draft|note)?)\b",
    re.I,
)
AFFIRM = re.compile(
    r"\b(?:yes|yep|yeah|yup|proceed|go\s+ahead|do\s+it|stage\s+it|build\s+it|"
    r"send\s+it|ship\s+it|approve|approved|draft\s+it|make\s+the\s+draft|"
    r"apple\s*mail|mail\s*draft|gmail\s*draft|please\s+proceed)\b",
    re.I,
)


# ── BUG-202 root cause 1 (2026-10-28): THE NAMED ALLOW-LIST OF BUILD ANSWER SHAPES, AND THE DEFERRAL VETO ───────────────────
# An earlier widening (reverted 22d8f868, forgery lens 10/100) used an OPEN object (`build <any word>`) kept safe by a veto list,
# and a refusal got through the list. This is the opposite design: a CLOSED, start-anchored, named set of shapes. Anything that
# does not match one of them stays OTHER, exactly as before, and OTHER authorizes nothing.
#
# ⛔ ADDING OR WIDENING A SHAPE MEANS TOUCHING tests/test_bug202_affirm_corpus.py: that test fails unless every name here has
# positives AND the negatives still pass, and the replay of the real ledger must show no BUILD lost.
#
# Each pattern runs on the RAW answer (capitalization is evidence: a company or person is capitalized), single line only, after
# the leading option number has been resolved to its label. The build-context question gate and the whole-string NEGATION
# veto in classify_answer still apply to every shape. `for_target` / `to_target` also require the named target to appear in
# the question or header the agent asked, so an answer cannot authorize something the question never named.
_TRAIL = (r"(?:\s+(?:now|specifically|only|please))*(?:\s*,\s*element\s+by\s+element)?"
          r"(?:\s*\((?:Recommended|Rec|Kuya\s+Andy['\u2019]s\s+pick|my\s+pick)\))?\s*$")
_TARGET = r"[A-Z0-9][\w&.'\u2019-]*(?:\s+[A-Z0-9][\w&.'\u2019-]*){0,3}?"
_ARTIFACT = (r"(?:email|note|draft|message|outreach|boss-hunt|approach|shortlist)")
AFFIRM_BUILD_SHAPES = {
    "bare": re.compile(r"^(?i:build)\s*(?:\((?i:radar)\)|\s(?i:both)|\s(?i:now))" + r"\s*$"),
    "for_target": re.compile(r"^(?i:build)\s+for\s+(?P<target>" + _TARGET + r")" + _TRAIL),
    "to_target": re.compile(r"^(?i:build)\s+to\s+(?P<target>" + _TARGET + r")" + _TRAIL),
    "artifact": re.compile(r"^(?i:build)\s+(?i:the|a|an|my)\s+(?:[A-Za-z][\w'\u2019-]*\s+){0,2}?(?i:" + _ARTIFACT + r")"
                           + _TRAIL),
}
# ── WHAT STOPS A BUILD FROM BEING PROMOTED, ACROSS THE WHOLE ANSWER (2b's forgery lens, 2026-10-28) ────────────────────────────────
# BUILD promotion is held to a stricter bar than SKIP, on purpose (the asymmetry documented in classify_answer): a wrong BUILD lets an
# unapproved message reach a person, a wrong OTHER costs one more pick. So every veto below reads the WHOLE answer, not just the verdict
# clause, and every veto only DEMOTES to OTHER (never SKIP, never BUILD). Nothing here can add an authorization.
_REFUSE_OR_DEFER = re.compile(
    r"\b(?:nothing|none|nobody|zero|tomorrow|tonight|today|after|before|once|when|until|till|eventually|someday|wait|waits|waiting|"
    r"hold\s+on|hang\s+on|pending|cancel|cancelled|canceled|stop|abort|scrap|scrapped|kill|nope|nah|rather\s+not|"
    r"won'?t|can'?t|cannot|shouldn'?t|wouldn'?t|isn'?t|instead|actually|hmm|maybe|perhaps|unsure|depends|if|eod|"
    r"this\s+(?:week|weekend|afternoon|evening|morning)|in\s+a\s+bit|next(?:\s+\w+)?|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\bsoon\b(?!\s+as\b)"
    r"|\b\d{1,2}[/-]\d{1,2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b")
_CONDITION = re.compile(r"\bonly\s+if\b|\bunless\b|\bprovided\b|\bas\s+long\s+as\b|\bsubject\s+to\b|\bconditional\b|\bcontingent\b|"
                        r"\bpending\b|\bassuming\b|\bdepending\b|\bgiven\s+that\b")
# A bulk or list answer authorizes an unnamed set; BUILD is per company. Words that are only bulk next to a build verb ("Keep both,
# build the draft" is not bulk; "build it for both" is) are matched within a few words after the verb.
_BULK_ANYWHERE = re.compile(r"\b(?:everyone|everybody|anyone|every|each|the\s+list|batch|the\s+rest)\b", re.I)
_BULK_AFTER_VERB = re.compile(
    r"\b(?:build|draft|stage|send|ship)\b[^,]{0,30}?\b(?:all|them|both|two|three|four|five|six|seven|eight|nine|ten)\b", re.I)
# BUILD names ONE recipient. After the target of a `for|to <Target>` phrase nothing may continue the recipient list or add free text:
# no "and", "&", "+", "plus", "cc", "also", "with", a comma, or a possessive ("Jane Roe's team"). The remainder after the target must be
# empty or the documented trailing set (now, ", element by element", one closed parenthetical). "for Acme Corp in Spanish" is OTHER.
_TARGET_PHRASE = re.compile(r"\b(?:for|to)\s+(?P<target>[A-Z0-9][\w&.'\u2019-]*(?:\s+[A-Z0-9][\w&.'\u2019-]*)*)"
                            r"(?=$|\s|,|'s\b|\u2019s\b|[&+(])")
_ALLOWED_PAREN = frozenset({"recommended", "rec", "kuya andy's pick", "kuya andy\u2019s pick", "kuya andy recommends", "my pick", "radar",
                            "andy's pick", "andy\u2019s pick"})
_SCORE_PAREN = re.compile(r"^\d{1,3}$")   # a panel score the picker label carries: "Yes, keep it as written (95)"
_AT_CLAUSE = re.compile(r"^\s+at\s+(?P<name>(?-i:[A-Z][\w&.'\u2019-]*(?:\s+[A-Z][\w&.'\u2019-]*){0,3}))")
_TRAIL_ONLY = re.compile(r"^(?:\s+(?:now|specifically|only|please))*(?:\s*,\s*element\s+by\s+element)?(?:\s*\([^)]*\))?\s*$", re.I)
_PAREN = re.compile(r"\(([^)]*)\)")
_known_cache = None


def _known_in(context) -> set:
    """Distinct known companies (lowercased, 4+ characters) that the question and header name; nested names count once."""
    global _known_cache
    if _known_cache is None:
        _known_cache = {k for k in _known_companies() if 4 <= len(k) <= 60}
    ctx = " ".join(str(c) for c in context if c).lower()
    hits = {k for k in _known_cache if k in ctx and re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", ctx)}
    return {h for h in hits if not any(h != o and h in o for o in hits)}


# Typographic characters that appear in ordinary answers. ANY other non-ASCII character (a zero-width or bidi mark that splits a
# negation, a Cyrillic look-alike, a fullwidth letter that NFKC would fold) means the answer never promotes.
_TYPO_OK = frozenset("\u2705\u2019\u2018\u201c\u201d\u2013\u2014\u00b7\u2026\u2022\u00e9\u00e8\u00fc\u00f6\u00e4\u00f1")


# `first` is ambiguous and keeps the doctrine settled in test_an_appended_instruction_modifies_the_build_it_does_not_withdraw_it:
# "#1 but please research him first" orders the work of a build that is already ruled ("build it" is unqualified), while "build the
# relationship first" defers the build itself. Trailing `first` vetoes only when the answer carries no unqualified build of its own.
_TRAILING_FIRST = re.compile(r"\bfirst\s*$")
_UNQUALIFIED_BUILD = re.compile(r"\bbuild\s+(?:it|this|that|now)\b|^\s*build\s*$")


def _promotion_vetoed(raw: str, a: str, context: tuple = ()) -> bool:
    """True when the answer must NOT be promoted to BUILD (it stays whatever it was, OTHER). Reads the raw answer, then its
    normalized form `a`. Every rule only DEMOTES.

    * a question ("Build the email?"): _norm strips the mark, so the RAW text is checked;
    * a non-ASCII character outside ordinary typography (an invisible character can split a negation so NEGATION misses it);
    * more than one line, or a semicolon: an injected second statement;
    * a refusal, cancellation, hedge, deferral, date or condition anywhere in the answer;
    * a bulk word ("everyone", "the list", or "all"/"both"/a count next to a build verb);
    * a parenthetical other than one closed label, once ("Build it (subject to legal review)", "(for Beta Inc)");
    * a second recipient, or free text, after the target of a for/to phrase ("to Jane and her CTO", "for Acme Corp in Spanish");
    """
    r = raw or ""
    if "?" in r or "\n" in r or "\r" in r or ";" in r:
        return True
    if any(ord(c) > 127 and c not in _TYPO_OK for c in r):
        return True
    # A curly apostrophe is typography, but _norm turns it into a space ("don\u2019t" -> "don t") and NEGATION then misses it.
    straight = _norm(r.replace("\u2019", "'").replace("\u2018", "'"))
    if _TRAILING_FIRST.search(straight) and not _UNQUALIFIED_BUILD.search(straight):
        return True
    if (NEGATION.search(straight) or _REFUSE_OR_DEFER.search(straight) or _REFUSE_OR_DEFER.search(a)
            or _REFUSE_OR_DEFER.search(r) or _CONDITION.search(straight) or _BULK_ANYWHERE.search(r)
            or _BULK_AFTER_VERB.search(r)):
        return True
    parens = _PAREN.findall(r)
    if len(parens) > 1 or any(p.strip().lower() not in _ALLOWED_PAREN and not _SCORE_PAREN.match(p.strip()) for p in parens):
        return True
    target = None
    m = _TARGET_PHRASE.search(r)
    if m:
        target = m.group("target")
        rest = r[m.end():]
        # "to <Person> at <Company>" is ONE recipient, but only when the `at` clause is exactly ONE company: a name the pipeline knows, or,
        # for a company it has not met yet, a run of at most two capitalized words. A longer run smuggles a second company ("at Altonly
        # Corp Beta Inc"), so the longest prefix that is a known company must be the WHOLE run.
        am = _AT_CLAUSE.match(rest)
        if am:
            toks = am.group("name").split()
            known = {k for k in _known_companies()}
            if known and any(" ".join(toks[:i]).lower() in known for i in range(1, len(toks) + 1)):
                if " ".join(toks).lower() not in known:
                    return True
            elif len(toks) > 2:
                return True
            rest = rest[am.end():]
        if re.match(r"^(?:'s\b|\u2019s\b)", rest) or not _TRAIL_ONLY.match(rest):
            return True
    return False


def _build_shape(raw: str, *context: str) -> str:
    """Name of the AFFIRM_BUILD_SHAPES entry that `raw` matches, or "". Single line, target named in the question."""
    r = (raw or "").strip()
    if not r or "\n" in r or "\r" in r:
        return ""
    ctx = " ".join(str(c) for c in context if c).lower()
    for name, pat in AFFIRM_BUILD_SHAPES.items():
        m = pat.match(r)
        if not m:
            continue
        target = m.groupdict().get("target")
        if target is not None and target.lower() not in ctx:
            continue
        # A bare "Build both"-style or artifact answer is attributed to whichever company extract_company picks from the question, so a
        # question that names two or more known companies cannot take it (2b D1). The exact labels ("Build it") are unchanged: they are
        # the scorecard's own template and are carried by real rows whose questions mention several companies in their descriptions.
        if target is None and len(_known_in(context)) >= 2:
            continue
        return name
    return ""


def _is_build_context(*texts: str) -> bool:
    """Does the assistant-authored question/header frame this as a build/outreach step?"""
    return any(bool(t) and bool(BUILD_CONTEXT.search(str(t))) for t in texts)


# ── AN OPTION NUMBER IS A RULING (reported by a partner install, kit issue #15) ───────────────
#
# ⛔ THE DEFECT. `classify_answer` reads the ANSWER TEXT and never the SELECTED OPTION LABEL. So
# answering a scorecard picker with "#1" records `ruling: OTHER` and authorizes nothing, even though
# option 1 is labeled "Build it" and that exact label classifies as BUILD. Measured here:
#     'Build it (Recommended)'           -> BUILD
#     '#1'                               -> OTHER
#     '#1 but please research him first' -> OTHER
#
# ⚖️ WHY THIS IS WORSE THAN A PARSE BUG: it inverts the gate's purpose. HARD-INVARIANTS carries an
# explicit counter-rule, "NEVER make you repeat a decision to satisfy a mechanism. If a gate
# blocks an instruction you already gave plainly, the GATE is wrong, fix the gate." Answering by
# number is a normal thing to do, and operators do it. The failure is SILENT at the moment of the ruling
# and only surfaces a step later, at a gate that then names the wrong cause.
#
# ⛔ IT RESOLVES, IT NEVER INVENTS. The number must LEAD the answer and must index a real option on
# that question; anything else is left exactly as typed. And the appended free text is KEPT and
# classified alongside the label, so the strict negation veto still applies: "#1 but skip it" must
# not become a BUILD. An instruction appended to a choice MODIFIES the build; it does not withdraw
# one, but only the veto gets to decide that.
_OPTION_REF = re.compile(r"^\s*(?:option\s*)?#?\s*([1-9])\s*(?=$|[\s.,;:)\]-])", re.I)


def resolve_option_answer(answer, question):
    """Answer text with a leading option reference replaced by that option's LABEL.

    Returns the answer unchanged when there is no leading reference, no options, or the index does
    not exist. Pure and total: never raises, never guesses beyond the options actually present.
    """
    a = str(answer or "")
    m = _OPTION_REF.match(a)
    if not m:
        return a
    opts = (question or {}).get("options") or []
    idx = int(m.group(1)) - 1
    if not (0 <= idx < len(opts)):
        return a
    opt = opts[idx]
    label = str((opt or {}).get("label") or "").strip() if isinstance(opt, dict) else str(opt)
    if not label:
        return a
    rest = a[m.end():].strip()
    return f"{label} {rest}".strip() if rest else label


def classify_answer(answer: str, *context: str) -> str:
    """Ruling for an answer, using the question/header as build CONTEXT. Exact rulings and negations
    are unchanged from classify(); only a free-text OTHER answer that AFFIRMS proceeding INSIDE a
    build-context question promotes to BUILD."""
    base = classify(answer)
    if base == "BUILD" and _promotion_vetoed(answer, _norm(answer), context):
        return "OTHER"   # even an exact label never authorizes when the raw answer is a question, multi-line or carries odd characters
    if base != "OTHER":
        return base
    a = _norm(answer)
    # ── THE ASYMMETRY, AND IT IS DELIBERATE ───────────────────────────────────────────────────
    # Authorizing and refusing do not get the same evidence bar: a wrong BUILD puts an unapproved
    # message in front of a real person, while a wrong SKIP only mislabels the audit trail.
    #   BUILD promotion keeps the STRICT whole-string veto: ANY negation ANYWHERE blocks it.
    #   SKIP is decided from the VERDICT CLAUSE only, so a justification cannot invert a decision.
    # The veto is evaluated BEFORE the SKIP branch so it can never be bypassed by reordering.
    if _is_build_context(*context) and not NEGATION.search(a) and not _promotion_vetoed(answer, a, context):
        if AFFIRM.search(a):
            # An answer that names an ARTIFACT ("build the email") is attributed to whichever company extract_company picks, so a question
            # that names two or more known companies cannot take it unless the answer names its own target (2b D1). The exact labels and
            # "build it" are unchanged: real scorecard questions mention several companies in their descriptions.
            if (re.search(r"\bbuild\s+(?:the\s+)?(?:email|outreach|note|message|draft)\b", a)
                    and not _TARGET_PHRASE.search(answer or "") and len(_known_in(context)) >= 2):
                return "OTHER"
            return "BUILD"
        if _build_shape(answer, *context):
            return "BUILD"
    if NEGATION.search(_verdict_clause(a)):
        return "SKIP"
    return "OTHER"


class _Ambiguous(str):
    """An empty company that means "two or more companies were named and nothing settled which", as opposed to "no company found".
    It equals "" and is falsy, so every existing caller treats it as no company; only main() tells the two apart, because the
    pending-scorecard fallback is for the second case and must not fill the first (BUG-774, 2b M1)."""


AMBIGUOUS = _Ambiguous("")


def extract_company(*texts: str) -> str:
    """Pull a company from a scorecard-style question, e.g. 'build ... for Acme?'.

    Best-effort only. The gate does NOT depend on parsing this correctly - it depends
    on a BUILD ruling existing at all. Company is recorded for the audit trail.

    Prepositions that usually precede a COMPANY (for/at/on) are tried before ones that often
    precede a PERSON (to/with), so "draft the note to Vic at Acme" resolves 'Acme', not 'Vic'.
    """
    # ── KNOWN NAME FIRST, LONGEST MATCH WINS ─────────────────────────────────────────────────
    # The proper-noun heuristic below TRUNCATES any company whose name carries a lowercase
    # connector, because it requires every following word to be capitalized:
    #     "Build or skip for Bayad with Bituin?"        -> "Bayad"     (stopped at "with")
    #     header "Bayad with Bituin"                    -> "Bituin"      (started at the last capital)
    #     "Build or skip for Welcome to the Jungle?" -> "Welcome"   (stopped at "to")
    # Both halves of that first pair were recorded live against a real ruling.
    #
    # ⚠️ THIS IS A SAFETY FIX, NOT A CONVENIENCE ONE. `check_preview` binds authorization to a NAMED
    # company, so a truncated name does not merely look untidy: it scopes a ruling to a company the
    # human did not rule on. "Welcome" is not "Welcome to the Jungle". A stray match against a real
    # company of that shorter name is cross-company authorization leakage.
    #
    # ⛔ IT TIGHTENS, IT NEVER WIDENS. A name the pipeline ALREADY KNOWS is authoritative over a
    # guess, and a LONGER name matches strictly fewer things than the prefix it replaces. Where no
    # known name is present, behavior is byte-for-byte what it was.
    #
    # ⚠️ THE RECOGNITION LIST IS POLLUTED, AND A LONGEST-MATCH SCAN EXPOSES IT. Names scraped from
    # markdown include entries that are not companies at all ("company", "remote", bare digits). The
    # OLD fallback never tripped on them by luck: its greedy multi-word windows meant a bare
    # "company" was never tested alone. A width-1 scan tests it, and a first draft of this scoped
    # "Which company should I screen next?" to a company literally named "company", which is the one
    # thing this edit may not do.
    #
    # The guard is POSITIONAL rather than a denylist, because a denylist rots as the list does: a
    # SINGLE-word known name only counts where a company actually sits, directly after a company
    # preposition or standing alone as the whole text. Multi-word known names need no guard; they
    # are too specific to collide.
    known = _known_companies()
    if known:
        # ── BUG-774: TWO OR MORE KNOWN COMPANIES IN ONE TEXT ARE AMBIGUOUS, NEVER A GUESS ───────────────────────────────
        # The scan used to keep the LONGEST name in the first text that had any, so a question naming two companies recorded the
        # longer one, and a BUILD ruling could be scoped to a company the question only mentioned. Now a text that names two or more
        # DISTINCT known companies (a name nested in a longer one counts once) does not decide: a later text (the header, then the
        # selected option's label) settles it only by naming exactly one of those companies. Nothing settles it -> "" (no company),
        # and check_preview then refuses to honor an unscoped ruling, which is the safe direction. Single-word names count only where
        # a company sits (after a company preposition, or standing alone), exactly as before, so words like "company" and "gate"
        # that pollute the list never make a text ambiguous.
        def _names_in(s):
            """Every distinct known company in `s`, using OVERLAPPING windows (the old non-overlapping scan let "or Beta" swallow
            "Beta Inc"). Used only to decide ambiguity; the single name that is returned still comes from the unchanged scan."""
            toks = [(m.start(), m.end()) for m in re.finditer(r"[A-Za-z][\w&.\-]*", s)]
            found = {}
            for i, (st, _en) in enumerate(toks):
                for w in range(1, 7):
                    if i + w > len(toks):
                        break
                    cand = s[st:toks[i + w - 1][1]].rstrip(".,!?;:")
                    if cand.lower() not in known:
                        continue
                    if w == 1:
                        before = s[:st].rstrip()
                        anchored = bool(re.search(r"\b(?:for|at|on|to|with)$", before, re.I))
                        if not (anchored or cand == s.strip().rstrip(".,!?;:")):
                            continue
                    found[cand.lower()] = cand
            # A single-word company that continues a LIST of companies ("for Acme or Beta", "Acme, Beta and Gamma") counts too: it is
            # chained to a name already found, so an ordinary word from the polluted list ("remote", "gate") never qualifies.
            for _ in range(3):
                grew = False
                for i, (st, en) in enumerate(toks):
                    cand = s[st:en].rstrip(".,!?;:")
                    if cand.lower() not in known or cand.lower() in found:
                        continue
                    before = s[:st].rstrip()
                    if any(re.search(re.escape(v) + r"\s*(?:,|/|&|\bor\b|\band\b|\bvs\.?)$", before, re.I) for v in found.values()):
                        found[cand.lower()] = cand
                        grew = True
                if not grew:
                    break
            return {k: v for k, v in found.items() if not any(k != o and k in o for o in found)}

        def _old_best(s):
            best = ""
            for width in range(6, 0, -1):
                pat = r"\b([A-Za-z][\w&.\-]*(?:\s+[\w&.\-]+){%d})" % (width - 1)
                for m in re.finditer(pat, s):
                    cand = m.group(1).strip().rstrip(".,!?;:")
                    if cand.lower() not in known or len(cand) <= len(best):
                        continue
                    if width == 1:
                        before = s[:m.start()].rstrip()
                        anchored = bool(re.search(r"\b(?:for|at|on|to|with)$", before, re.I))
                        if not (anchored or cand == s.strip().rstrip(".,!?;:")):
                            continue
                    best = cand
            return best

        ambiguous = None   # {lowercase name: spelling} from the first text that named 2+ companies
        for t in texts:
            s = str(t or "")
            if not s:
                continue
            names = _names_in(s)
            if ambiguous is None:
                if len(names) >= 2:
                    ambiguous = names
                    continue
                best = _old_best(s)
                if best:
                    return best
                continue
            hit = [v for k, v in names.items() if k in ambiguous]
            if len(hit) == 1:
                return hit[0]
        if ambiguous is not None:
            return AMBIGUOUS

    # LEADING SCORECARD HEADER (kit#99). "<COMPANY> SCORECARD · <role>" carries no preposition,
    # so neither pass above nor the fallback below could see it and the row recorded company:"".
    # A scorecard is built around a company by construction, so the leading run is trusted as-is.
    # Tried AFTER the known-name pass so a tracked name still beats a generic leading word.
    for t in texts:
        # A dot may sit INSIDE a name word ("Northwind.io", "Contoso.com") and never end one, and it
        # joins two parts only when the part after it starts with a lowercase letter or a digit. A
        # sentence end before SCORECARD ("Northwind Health. Your SCORECARD") has a space and cannot
        # join; "Northwind Health.Your SCORECARD" has none, and a capital after the dot is a new
        # sentence, not a domain: it recorded "Northwind Health.Your", which mail-draft's word-boundary
        # match then passed for --company "Northwind Health" (kit #99 again). Kit #151.
        # kit #166 bug 3: a header can carry the ruling keyword instead of the literal word
        # "SCORECARD" ("Zorbex Radar", "Quillmark Build", "Plinth Health Build") -- same
        # leading-run shape, so the trailing keyword this matches widens to cover them too.
        # The ruling-keyword alternatives are matched CASE-SENSITIVELY (Title Case only), same as
        # the literal "SCORECARD" they extend: "build"/"skip"/"drop" are ordinary English verbs
        # that show up lowercase mid-sentence ("Build or skip for Acme?"), and a case-insensitive
        # match there walked past several words of a real question to seize on one, misreading a
        # sentence as a header. A real header capitalizes its trailing ruling word.
        m = re.match(r"\s*([A-Z0-9][\w&\-]*(?:\.[a-z0-9][\w&\-]*)*"
                     r"(?:[ \t]+[\w&\-]+(?:\.[a-z0-9][\w&\-]*)*){0,3}?)"
                     r"[ \t]+(?:SCORECARD|Build|Radar|Drop|Park|Skip)\b", str(t or ""))
        if m:
            return m.group(1).strip()

    # kit #166 bug 4: a header that is NOTHING BUT a short proper-noun run ("Zorbex") names
    # the company by construction, the same way a SCORECARD/ruling-keyword header does, but has no
    # trailing keyword for the pass above to anchor on and is not yet in `_known_companies()`. An
    # empty-company row fails check_preview._build_rulings()'s authorization gate downstream, so
    # this is not cosmetic. Bounded to <=4 words and requires the WHOLE text to match, so a full
    # sentence ("Which company should I screen next?") never qualifies.
    for t in texts:
        s = str(t or "").strip()
        if s and re.fullmatch(r"[A-Z0-9][\w&\-]*(?:[ \t]+[A-Z][\w&\-]*){0,3}", s):
            return s

    # kit #166 bug 2: the preposition pass used to check `texts` in CALL ORDER (question text
    # first, header second), so a geographic or other proper noun sitting after a preposition
    # in the QUESTION body ("remote with Florida eligible") won outright even when the HEADER
    # separately named the real company. The header is more authoritative for company identity,
    # so it is checked first here (reversed, since the call site passes question-text-first).
    for prep in (r"for|at|on", r"to|with"):
        for t in reversed(texts):
            if not t:
                continue
            # CONNECTOR-TOLERANT PROPER-NOUN RUN. Same truncation as above, for a company the
            # pipeline has NOT met yet, so the known-name pass cannot help it. Only a closed set of
            # lowercase joiners is allowed, and each must still be followed by a capitalized token,
            # so "for the team" and "for a minute" still resolve to nothing.
            # SENTENCE BOUNDARY (kit#99). A name token may carry an INTERNAL dot ("Booking.com")
            # but never a trailing one, and words continue only across spaces, never a newline:
            # the old class `[\w&.\-]*` ate the period and the continuation only asked "is the
            # next word capitalized", so "at Brimwick Blue. Your ruling?" recorded "Brimwick Blue.
            # Your" on a live BUILD row and the gate was scoped to a company nobody ruled on.
            # The same rule as the SCORECARD header above (kit #151): a dot joins two parts only when
            # a lowercase letter or a digit follows it, so "at Northwind Health.Your ruling?" (no
            # space, a capital after the dot) cannot record "Northwind Health.Your" either.
            m = re.search(
                r"\b(?i:" + prep + r")\s+([A-Z][\w&\-]*(?:\.[a-z0-9][\w&\-]*)*"
                r"(?:(?:[ \t]+(?:of|the|with|and|for|to|at|by|on|in|de|la))*"
                r"[ \t]+[A-Z][\w&\-]*(?:\.[a-z0-9][\w&\-]*)*){0,3})", str(t))
            if m:
                cand = re.split(r"[.?!](?:\s|$)|\s·\s|\n", m.group(1), maxsplit=1)[0]
                return cand.strip().rstrip(".,!?;:")

    # LOWERCASE-BRAND FALLBACK. The pattern above is a proper-noun heuristic, and it silently
    # unscoped a real BUILD ruling for a company whose brand is spelled lowercase: "for <brand>"
    # matched nothing, the row recorded company:"", and the gate correctly refused to honor an
    # unscoped ruling, so a decision the human had plainly given blocked the next question.
    # Recognition-only, so ordinary words after a preposition still resolve to nothing.
    known = _known_companies()
    if known:
        for t in texts:
            for tok in re.findall(r"[A-Za-z][\w&.\-]*(?:\s+[\w&.\-]+){0,2}", str(t or "")):
                cand = tok.strip().rstrip(".,!?;:")
                if cand.lower() in known:
                    return cand
    return ""


def _known_companies() -> set:
    """Delegates to check_outreach.known_companies(), the single source for this list.

    Two copies of a recognition list drift, and a drifted list silently unscopes a BUILD ruling,
    which is the exact failure this path exists to prevent.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from check_outreach import known_companies
        return known_companies()
    except Exception as _e:
        # ⚠️ SILENT UNTIL 2026-09-12, same shape found (and fixed) in verify_resume.py,
        # check_style.py, check_pair.py and check_preview.py: an empty fallback with no
        # announcement. This function's own docstring already named the harm -- a drifted list
        # silently unscopes a BUILD ruling, the one record this agent cannot forge -- so an
        # empty set here means his signed authorization can attach to the wrong company or none,
        # with nothing to see. VISIBILITY ONLY: the return value is unchanged (still `set()`,
        # never invented), this is not the place to widen or narrow what gets returned.
        print(f"⚠️  record_decision: check_outreach.known_companies() did not import "
              f"({type(_e).__name__}: {_e}); company-anchor recognition for this ruling is "
              f"running with ZERO known companies", file=sys.stderr)
        return set()


def extract_person(texts, store):
    """The one contacts KEY (display name) a label/question names, or None.

    `texts` is tried IN ORDER, first hit wins; a text is skipped (not merged) if it resolves to
    zero or more-than-one contact. Longest normalized name wins within a single text. Returns
    None on no store, no match anywhere, or genuine ambiguity -- extraction never guesses.
    """
    if not store:
        return None
    try:
        import closeness
    except Exception as _e:
        print(f"⚠️  record_decision: closeness did not import ({type(_e).__name__}: {_e}); "
              f"a Hold/Lift ruling on a named contact cannot reach the closeness store this run",
              file=sys.stderr)
        return None
    for t in texts:
        s = str(t or "")
        if not s:
            continue
        best_key, best_len = None, 0
        ambiguous_at_best = False
        for width in range(4, 0, -1):
            # Zero-width lookahead so EVERY start position is tried, not just the ones a prior
            # non-overlapping match left unconsumed. Plain re.finditer would match "Hold Vale"
            # (both capitalized) first and then skip straight past "Vale Harbor" entirely,
            # because finditer never backtracks to a start position inside a completed match.
            pat = r"\b(?=([A-Z][\w'.\-]*(?:\s+[A-Z][\w'.\-]*){%d}))" % (width - 1)
            for m in re.finditer(pat, s):
                cand = closeness.normalize_name(m.group(1))
                if not cand or cand not in store:
                    continue
                if len(cand) > best_len:
                    best_key, best_len, ambiguous_at_best = cand, len(cand), False
                elif len(cand) == best_len and cand != best_key:
                    ambiguous_at_best = True  # two DIFFERENT names, same length, in this text
        if best_key and not ambiguous_at_best:
            return store[best_key].get("display_name") or best_key
        if best_key:
            return None  # this text named more than one contact -- never guess between them
    return None


# BUG-790: an option pick IS that option's ruling. Words typed after "#1" or after a clicked label are
# his reasons; they can narrow a BUILD to OTHER but never turn the pick into a SKIP or write a hold on
# a contact. A hold is written only when the chosen option is itself a hold, skip, pass or drop option
# (or the bare answer is a skip word, the typed BUG-233 case with no options).
_HOLD_WORD = re.compile(r"\b(?:skip|hold|pass|drop)\b", re.I)


def picked_option(answer, question):
    """(number, label, free_text) when the answer picked an option, else None.

    A pick is a leading option reference ("#1", "option 2") that exists, or an answer that equals an
    option label. Pure and total: never raises, never guesses beyond the options actually present.
    """
    a = str(answer or "")
    opts = (question or {}).get("options") or []
    labels = [str((o or {}).get("label") or "").strip() if isinstance(o, dict) else str(o).strip() for o in opts]
    m = _OPTION_REF.match(a)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(labels) and labels[idx]:
            return idx + 1, labels[idx], a[m.end():].strip()
        return None
    for idx, lab in enumerate(labels):
        if lab and a.strip().lower() == lab.lower():
            return idx + 1, lab, ""
    return None


def pick_ruling(ruling, picked, qtext, header):
    """The ruling once a pick is known. Only a SKIP is rewritten, and only to the label's own ruling.

    A SKIP that came from the words after the pick becomes the label's ruling (OTHER for an Andy's
    pick, SKIP for a "Skip <Name>" label). A label that would be BUILD becomes OTHER here: the free
    text carried the negation, so the pick narrows and never authorizes. OTHER and BUILD pass
    through untouched, so nothing authorizes that did not already.
    """
    if not picked or ruling != "SKIP":
        return ruling
    label_ruling = classify_answer(picked[1], qtext, header)
    return "OTHER" if label_ruling == "BUILD" else label_ruling


# BUG-794 N3: "his own words" = one short line. A pasted log is not, even when it names the contact.
_OWN_WORDS_MAX = 240


def _own_words(answer):
    a = str(answer or "").strip()
    return bool(a) and "\n" not in a and len(a) <= _OWN_WORDS_MAX


def _names_a_contact(texts):
    """True when the old extraction order would have resolved a contact (so a withheld hold is worth saying)."""
    try:
        import closeness as _closeness
        return bool(extract_person(texts, _closeness.load()))
    except Exception:
        return False


def apply_hold_or_lift(texts, action, *, reason, verb="HELD"):
    """Resolve ONE contact from `texts` (via extract_person) and pause or lift their row.

    `action` is "pause" or "lift". No-op (returns without writing) when no store, no name
    resolves, or (lift only) the row was never held by this mechanism -- closeness.lift() already
    enforces that boundary, this just avoids an unnecessary write when nothing changed.
    Returns the raw store keys it covered (every row for that person), so the caller can say when
    one decision touched more than one row. Raises on a genuine I/O failure so the caller's except block can print the loud stderr line;
    never itself prints or swallows.
    """
    import closeness as _closeness
    store = _closeness.load()
    name = extract_person(texts, store)
    if not name:
        return []
    key = _closeness.normalize_name(name)
    with _closeness.store_lock():
        with open(_closeness.STORE, encoding="utf-8") as _fh:
            raw = json.load(_fh)
        contacts = raw.get("contacts", {})
        changed = False
        covered = []
        for raw_key in contacts:
            if _closeness.normalize_name(raw_key) != key:
                continue
            covered.append(raw_key)
            before = contacts[raw_key]
            after = _closeness.pause(before, reason, verb=verb) if action == "pause" \
                else _closeness.lift(before, reason)
            if after != before:
                contacts[raw_key] = after
                changed = True
        # EVERY row for this person, not the first: load() merges credential-tail twins into one
        # contact whose hold is the union of theirs, so a lift on one twin alone would be a no-op.
        if changed:
            _closeness.atomic_write(raw, path=_closeness.STORE, indent=1)
    return covered


def _append_unsigned(rows, reason: str) -> None:
    """Append rows with NO mac field, NO kid and an `unsigned_reason`. Append-only, never an authorization."""
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    fd = os.open(LEDGER, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        for r in rows:
            out = {k: v for k, v in r.items() if k not in ("mac", "kid")}
            out["unsigned_reason"] = reason[:300]
            os.write(fd, (json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _migrate_refusal() -> str:
    """The reason `--migrate` must NOT create a key now, or "". It only matters when this install has no key yet:
    a new key beside rulings we cannot verify would orphan every one of them. An unreadable ledger, or a signed
    ledger whose legacy key is gone or verifies none of its rows, creates nothing and says what to restore."""
    if install_key(create=False):
        return ""
    state, why = _lk.ledger_signed_state(LEDGER)
    if state == "none":
        return ""
    if state == "unknown":
        return ("%s, and this install has no usable key. Not creating a new key: if the ledger holds signed "
                "rulings a new key would orphan every one of them. Fix the ledger's permissions or restore it, "
                "then run `python3 scripts/record_decision.py --migrate` again." % why)
    legacy = _read_legacy_key(LEGACY_KEYFILE)
    if legacy:
        try:
            with open(LEDGER, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    m = str(row.get("mac", "")) if isinstance(row, dict) else ""
                    if m and hmac.compare_digest(row_mac(row, legacy), m):
                        return ""
        except OSError:
            pass
    return ("the decision ledger already holds signed rulings, but the key that signed them is not here "
            "(looked at %s). Not creating a new key: it would orphan every earlier ruling. Restore that file "
            "from your backup, then run `python3 scripts/record_decision.py --migrate` again." % LEGACY_KEYFILE)


def main() -> None:
    # `--migrate`: create this install's key and take the one-time legacy snapshot now. install.sh runs
    # it on every install and Update Kit run, which shrinks the M1 window (see SECURITY NOTES).
    if len(sys.argv) > 1 and sys.argv[1] == "--migrate":
        refusal = _migrate_refusal()
        if refusal:
            print(refusal, file=sys.stderr)
            sys.exit(1)
        if not install_key(create=True):
            print(key_error_message(), file=sys.stderr)
            sys.exit(1)
        backfill_marker()           # N3: a key that predates its marker gets one, never a snapshot
        print("decision-ledger signing key ready for this install")
        sys.exit(0)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    try:
        tool_input = payload.get("tool_input") or {}
        tool_response = payload.get("tool_response") or {}

        questions = tool_input.get("questions") or []
        # The harness returns the user's selections keyed by question text.
        answers = tool_response.get("answers") or tool_input.get("answers") or {}
        if isinstance(answers, str):
            try:
                answers = json.loads(answers)
            except Exception:
                answers = {}
        if not isinstance(answers, dict):
            answers = {}

        rows = []
        ts = datetime.now(timezone.utc).isoformat()
        for q in questions:
            if not isinstance(q, dict):
                continue
            qtext = str(q.get("question", ""))
            header = str(q.get("header", ""))
            answer = str(answers.get(qtext, "") or "")
            # Resolve "#1" to the label the assistant authored, BEFORE classifying. The label comes
            # from a known vocabulary; the free-text answer is the operator writing in their own
            # words and will never enumerate.
            _for_class = resolve_option_answer(answer, q)
            _row_ruling = classify_answer(_for_class, qtext, header)
            # BUG-790: a pick is the option's ruling; the words after it never make it a SKIP.
            _picked = picked_option(answer, q)
            _row_ruling = pick_ruling(_row_ruling, _picked, qtext, header)
            rows.append(
                {
                    "ts": ts,
                    "session": payload.get("session_id", ""),
                    "question": qtext,
                    "header": header,
                    "answer": answer,
                    # A company named only in the SELECTED OPTION'S LABEL (e.g. "Build it for
                    # SomeCo") used to be invisible here, because this scanned the raw `answer`
                    # ("#1"), never the resolved label `_for_class` already carries. `_for_class`
                    # is never narrower than `answer` (resolve_option_answer returns it unchanged
                    # when there is no leading option reference to resolve), so this only adds
                    # text extract_company can match against, never removes any.
                    "ruling": _row_ruling,
                    "company": str(extract_company(qtext, header, _for_class)),
                    # two or more companies named and nothing settled which (BUG-774): distinct from "no company found"; outside the MAC fields
                    **({"company_ambiguous": True}
                       if isinstance(extract_company(qtext, header, _for_class), _Ambiguous) else {}),
                    "source": "posttooluse-hook",
                }
            )
            # A SKIP/Hold ruling on a picker option naming a contact pauses that row in
            # contact-closeness.json; a later BUILD or a "named advisor: <Name>" pick on an
            # already-picker-paused row lifts it.
            try:
                _opts = q.get("options") or []
                _opt1_label = str(_opts[0].get("label") or "") if _opts and isinstance(_opts[0], dict) else ""
                _texts = (_for_class, _opt1_label, qtext)  # extraction order per the approved plan
                _covered = []
                _hold_label = bool(re.match(r"^(hold|skip|pass|drop)\b" if _picked else r"^(hold|skip)\b",
                                            _for_class.strip(), re.I))
                _andy_label = bool(re.match(r"^kuya andy:", _for_class.strip(), re.I))
                if (_row_ruling == "SKIP" and not _picked) or _hold_label:
                    # BUG-794 N3: with options on the question and none picked, a hold needs the contact in his
                    # own words (one short line); a pasted log or "hold it for now" records the ruling only.
                    _typed = not _picked and bool(_opts)
                    _pause_texts = _texts if not _typed else ((answer,) if _own_words(answer) else ())
                    # BUG-794 N1: the note verb follows the label, not the ruling ("Hold X" is HELD).
                    _covered = apply_hold_or_lift(_pause_texts, "pause",
                                        verb=("HELD" if re.match(r"^hold\b", _for_class.strip(), re.I)
                                              or _row_ruling != "SKIP" else "SKIPPED"),
                                        reason=(_for_class or qtext).strip()[:200])
                    if _typed and not _covered and _names_a_contact(_texts):
                        print(f"record_decision: typed answer recorded as {_row_ruling}; it does not name the contact "
                              f"in his own words, so no hold was written. Confirm in a picker before any hold",
                              file=sys.stderr)
                elif _row_ruling == "BUILD" or _andy_label:
                    _covered = apply_hold_or_lift(_texts, "lift", reason=f"ruling {_row_ruling!r} on this contact")
                if _picked and _row_ruling != "SKIP" and not _hold_label:
                    _word = _HOLD_WORD.search(_picked[2])
                    if _word:
                        print(f'record_decision: option {_picked[0]} recorded; the words after it carry "{_word.group(0).lower()}", '
                              f"confirm with him in a picker before any hold", file=sys.stderr)
                if len(_covered) > 1:
                    print(f"record_decision: that covered {len(_covered)} rows for one person "
                          f"({', '.join(_covered)})", file=sys.stderr)
            except Exception as _hold_exc:
                # Fail-open per the module's own contract (a hook crash must never block real
                # work) -- but a swallowed hold write is invisible unless it says so.
                print(f"⚠️  record_decision: contact-closeness hold/lift FAILED for "
                      f"{qtext[:60]!r}: {_hold_exc!r}", file=sys.stderr)

        if rows:
            key = _key()
            if not key:
                # Proxy 70: no decision is lost silently. The row is RECORDED without a mac, kid or signature and
                # with the loud reason, so no verifier ever counts it. Exit 1 is a visible, NON-blocking hook error.
                _append_unsigned(rows, key_error_message())
                print(key_error_message(), file=sys.stderr)
                sys.exit(1)
            kid = _lk.key_id(key)
            for r in rows:
                _lw.append_signed_row(LEDGER, r, key, kid)
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
