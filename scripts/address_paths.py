#!/usr/bin/env python3
"""address_paths.py -- slice E: the three ways to reach a boss, from what the CLI's own address step already recorded.

His rule (hunter.io + verifyemailaddress, ABOVE 90, SEND gate): an address below the bar is never sent as if it were sure. Andy's two exceptions
(HARD-INVARIANTS, the bcc hedge): many formats are likely, or the name is common. So there are three paths, and one is the CLI's pick:
  verified    the CLI's address step accepted an address for this card (documents/state/address/results.json, status "accepted"): send to it
  variations  no verified address, but the company's mail domain is known from a below-bar find: To the likeliest form, Bcc the others (a GUESS, labeled)
  linkedin    no address good enough, or a common name: start on LinkedIn, nothing can bounce
This module READS the files scripts/address_fill.py writes. It never looks anything up, never calls a service and never invents a domain: with no known
domain there are no variations, and it says so. A bounced address (documents/bounced-addresses.txt, the same whole-line rule mail-draft.sh uses) is
never offered. Addresses leave this module only to the local app's own page (serve.py), never to the feed, the store or a model prompt.
"""
import json
import os
import re

ADDR_RE = re.compile(r"^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]{2,}$")
MAX_BCC = 2          # the CLI's hedge (WORKFLOW-RULES, channel and method): To first.last, Bcc first@ then flast@
# Consumer mailbox providers. A find at one of these is a person's own mailbox, never the company's mail domain, so it names no domain to guess from.
FREEMAIL_DOMAINS = frozenset("gmail.com googlemail.com yahoo.com ymail.com rocketmail.com outlook.com hotmail.com live.com msn.com icloud.com me.com mac.com "
                             "aol.com proton.me protonmail.com pm.me gmx.com gmx.net mail.com zoho.com yandex.com fastmail.com hey.com comcast.net "
                             "att.net verizon.net sbcglobal.net".split())
# Surnames so common that a pattern guess lands on the wrong person (Andy's second exception). A short, plain list, not a database.
COMMON_SURNAMES = frozenset("smith johnson williams brown jones garcia miller davis rodriguez martinez hernandez lopez gonzalez wilson anderson thomas taylor moore "
                            "jackson martin lee perez thompson white harris sanchez clark ramirez lewis robinson walker young allen king wright scott torres "
                            "nguyen hill flores green adams nelson baker hall rivera campbell mitchell carter roberts kim patel chen wang li zhang singh".split())
# Provider base names that are safe to match with any country suffix (yahoo.co.uk, outlook.fr). Short or common words (me, mac, pm, hey, mail) are left out:
# those match only as the listed full domain or a subdomain of it.
_FREEMAIL_BASES = frozenset(d.split(".")[0] for d in FREEMAIL_DOMAINS) - {"me", "mac", "pm", "hey", "mail", "att", "zoho", "proton"} | {"proton", "zoho"}
_TLD_WORDS = frozenset(("com", "net", "org", "co", "edu", "gov", "ne", "or"))


def is_freemail(domain):
    """True for a consumer mailbox provider: the listed domain, any subdomain of it, or its base name with a country suffix (yahoo.co.uk, gmx.de)."""
    d = str(domain or "").strip().lower().rstrip(".")
    if not d:
        return False
    if any(d == f or d.endswith("." + f) for f in FREEMAIL_DOMAINS):
        return True
    labels = d.split(".")
    for i, lab in enumerate(labels[:-1]):
        rest = labels[i + 1:]
        if lab in _FREEMAIL_BASES and all(len(x) <= 3 or x in _TLD_WORDS for x in rest):
            return True
    return False


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def load_bounced(repo):
    out = set()
    try:
        with open(os.path.join(repo, "documents", "bounced-addresses.txt"), encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                s = line.strip().lower()
                if s and not s.startswith("#"):
                    out.add(s)
    except OSError:
        pass
    return out


def _tokens(name):
    """(first, last) lowercase letters only, from a display name. A middle token is dropped; a trailing suffix is not guessed at."""
    parts = [re.sub(r"[^a-z]", "", p.lower()) for p in re.split(r"\s+", str(name or "").strip())]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[-1]


def forms(first, last):
    """The usual corporate local parts, likeliest first. Every one is a GUESS until something checks it."""
    return [("first.last", "%s.%s" % (first, last)), ("first", first), ("flast", first[0] + last),
            ("firstlast", first + last), ("f.last", "%s.%s" % (first[0], last)), ("firstl", first + last[0])]


def _form_of(local, first, last):
    for label, text in forms(first, last):
        if local == text:
            return label
    return None


def paths_for(repo, slug, boss_name):
    """The decision for one card: {"verified", "variations", "linkedin", "pick", "boss", "reason"}. Plain data, no markup."""
    results = _read_json(os.path.join(repo, "documents", "state", "address", "results.json")) or {}
    rec = ((results.get("records") or {}).get(slug)) if isinstance(results, dict) else None
    rec = rec if isinstance(rec, dict) else {}
    bounced = load_bounced(repo)
    out = {"slug": slug, "boss": str(boss_name or "").strip(), "verified": None, "variations": None, "linkedin": {"why": "No address is needed, and nothing can bounce."},
           "pick": "linkedin", "reason": "", "common_name": False, "checked_at": None}
    toks = _tokens(boss_name)
    out["common_name"] = bool(toks and toks[1] in COMMON_SURNAMES)
    addr = str(rec.get("to_email") or "").strip().lower()
    if rec.get("status") == "accepted" and ADDR_RE.match(addr) and addr not in bounced:
        out["verified"] = {"address": addr, "source": rec.get("source") or "", "confidence": rec.get("confidence"),
                           "confidence_source": rec.get("confidence_source") or "", "checked_at": rec.get("checked_at")}
        out["pick"] = "verified"
        out["reason"] = "An address cleared your bar."
        return out
    # No verified address. A below-bar find at this company names the mail domain (and maybe the form); that is the only place a domain comes from.
    domain, known_form = "", None
    for r in rec.get("rejected") or []:
        a = str((r or {}).get("address") or "").strip().lower()
        if ADDR_RE.match(a) and a not in bounced and not is_freemail(a.split("@", 1)[1]):
            domain = a.split("@", 1)[1]
            if toks:
                known_form = _form_of(a.split("@", 1)[0], *toks)
            break
    if domain and toks and not out["common_name"]:
        ordered = forms(*toks)
        if known_form:
            ordered = [f for f in ordered if f[0] == known_form] + [f for f in ordered if f[0] != known_form]
        cands = [("%s@%s" % (t, domain), label) for label, t in ordered]
        cands = [c for c in cands if c[0] not in bounced]
        if cands:
            out["variations"] = {"to": cands[0][0], "to_form": cands[0][1], "bcc": [c[0] for c in cands[1:1 + MAX_BCC]], "domain": domain,
                                 "to_seen": known_form is not None,
                                 "guess": True}
            out["pick"] = "variations"
            out["reason"] = "Several forms are likely and none is verified."
            return out
    out["reason"] = ("This is a common name, so a guessed address could reach the wrong person." if out["common_name"]
                     else "No address cleared the bar and no mail domain is on record.")
    return out
