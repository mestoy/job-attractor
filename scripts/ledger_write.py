#!/usr/bin/env python3
"""ledger_write.py -- the ONE way our own code appends to or rewrites the decision ledger, and both refuse what caused
the harm in kit issue #149.

A kit script, run under another HOME, minted a key and re-signed rows it had rewritten. Leave the signature and the
rows stop verifying. Re-sign and the ledger asserts an authorization for content nobody approved. Against our OWN
tools prevention is complete, because every one of them is ours, so:

  append_signed_row   computes the mac itself, over the row it is appending, and REFUSES a row that arrives with a
                      mac (nobody hands it one). It only ever appends: earlier bytes are never touched.
  guarded_rewrite     for any bulk rewriter. REFUSES to change any of a signed row's eight signed fields or its mac,
                      REFUSES to drop a signed row, and REFUSES any output row carrying a mac the input did not
                      already hold. It can never sign. It writes a temp file and replaces the ledger only after the
                      whole result has been checked, so a refusal leaves the file byte for byte as it was.

THE LIMIT. This does not stop `python3 -c "open(...).write(...)"` or any code that does not call it. It stops our own
code, which is where the harm came from. Finding what a stranger's code did afterwards is ledger_audit.py's job.
Rows with no mac may be edited: there is no signature to violate. Fields outside the signature (kid, via, notes) may
change: they cannot change what a row asserts.
`kid` is a diagnostic label, not an input to verification: ledger_keys.verify_kid ignores a row's own kid and tries every
held key, so allowing it to change cannot make a row verify that did not.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger_keys as _lk  # noqa: E402

MAC_FIELDS = _lk.MAC_FIELDS


class WriteOnceError(Exception):
    """A write that would alter, drop or newly sign a signed row. The ledger is left as it was."""


def _sig(row):
    return tuple([str(row.get(f, "")) for f in MAC_FIELDS] + [str(row.get("mac", ""))])


def append_signed_row(ledger, row, key, kid, problem=""):
    """Append ONE row. The mac is computed here, over this row. Returns the row as written."""
    if str(row.get("mac", "")).strip():
        raise WriteOnceError("this row arrived with a mac. A mac is computed here, over the row being appended, "
                             "and is never passed in.")
    out = dict(row)
    if key:
        out["mac"] = _lk._mac(out, key)
        out["kid"] = kid
    else:
        out["mac"] = ""
        out["kid"] = ""
        out["key_state"] = "unsigned: " + str(problem)[:160]
    os.makedirs(os.path.dirname(os.path.abspath(ledger)), exist_ok=True)
    line = (json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(ledger, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)
    return out


def _read_all(ledger):
    """(rows, damaged). Blank lines are skipped. Any other line that is not a JSON object is damaged."""
    rows, damaged = [], 0
    try:
        with open(ledger, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    damaged += 1
                    continue
                if isinstance(r, dict):
                    rows.append(r)
                else:
                    damaged += 1
    except OSError:
        pass
    return rows, damaged


def guarded_rewrite(ledger, keyfile, transform):
    """Apply `transform(rows) -> rows` to the ledger, write-once for every signed row. Raises LedgerKeyError when
    there is no usable key, WriteOnceError on any violation; either way the file is untouched."""
    _lk.rewrite_guard(ledger, keyfile)
    before, damaged = _read_all(ledger)
    if damaged:
        raise WriteOnceError("the ledger has %d line(s) I cannot read as rows. Rewriting would drop them, so I "
                             "will not." % damaged)
    held = {}
    for r in before:
        if str(r.get("mac", "")).strip():
            held[_sig(r)] = held.get(_sig(r), 0) + 1
    after = transform([json.loads(json.dumps(r)) for r in before])
    for r in after:
        if not str(r.get("mac", "")).strip():
            continue
        s = _sig(r)
        if held.get(s, 0) > 0:
            held[s] -= 1
            continue
        changed = [f for f in MAC_FIELDS if not any(str(o.get(f, "")) == str(r.get(f, "")) for o in before)]
        raise WriteOnceError("an output row carries a mac the input did not hold (signed fields that differ from any "
                             "existing row: %s). A rewrite can never sign or re-sign." % (", ".join(changed) or "mac"))
    dropped = sum(held.values())
    if dropped:
        names = []
        for s, n in held.items():
            if n:
                match = [r for r in before if _sig(r) == s]
                for f in MAC_FIELDS:
                    if match and not any(str(x.get(f, "")) == str(match[0].get(f, "")) for x in after):
                        names.append(f)
        raise WriteOnceError("%d signed row(s) would be altered or dropped%s. Signed rows are write-once." % (
            dropped, (" (a signed field no longer matches: %s)" % ", ".join(sorted(set(names)))) if names else ""))
    directory = os.path.dirname(os.path.abspath(ledger))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ledger-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for r in after:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, ledger)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return after
