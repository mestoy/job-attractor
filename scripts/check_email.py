#!/usr/bin/env python3
"""check_email.py — pre-send sanity check on an outreach address.

WHY: 3 of our 7 inbound events were BOUNCES, and the changelog already named the cause —
addresses are guessed (`firstname@domain`) and hedged via Bcc rather than verified. Andy's method
uses hunter.io + verifyemailaddress.org for ">90% probability" before sending. This is the
no-API-key, no-signup version of that gate: it cannot confirm a mailbox exists, but it catches the
failures that actually bite.

WHAT IT CHECKS (all local, stdlib + dig):
  1. syntax
  2. the domain RESOLVES and publishes MX records — a domain with no MX cannot receive mail at all,
     which is the single cheapest bounce to prevent
  3. role-account addresses (info@, support@) that are unlikely to reach a person
  4. free-mail domains, which for boss-hunting usually means a scraped personal address
     (WORKFLOW-RULES: "Never a scraped personal Gmail")

WHAT IT CANNOT DO: confirm the local part exists. SMTP RCPT probing is unreliable, rude to the
receiving server, and often blocked. For that, hunter.io is the documented upgrade — this gate is
the floor, not the ceiling. Honest about its own limits so nobody reads a PASS as "verified."

Usage:  scripts/check_email.py jane@example.com [more@addresses ...]
Exit:   0 = no blocking problem · 1 = a hard problem (no MX / bad syntax) · 2 = usage
"""
import re
import subprocess
import sys

SYNTAX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
ROLE = {"info", "support", "hello", "contact", "admin", "sales", "help", "team",
        "careers", "jobs", "hr", "noreply", "no-reply"}
FREEMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
            "aol.com", "proton.me", "protonmail.com", "me.com"}


def mx_records(domain):
    try:
        out = subprocess.run(["dig", "+short", "MX", domain], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        return [l for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def a_records(domain):
    try:
        out = subprocess.run(["dig", "+short", "A", domain], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        return [l for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def check(addr):
    fails, warns = [], []
    if not SYNTAX.match(addr):
        return [f"invalid syntax: {addr}"], []
    local, domain = addr.rsplit("@", 1)
    local_l, domain_l = local.lower(), domain.lower()

    mx = mx_records(domain_l)
    if not mx:
        if a_records(domain_l):
            warns.append(f"{domain_l} resolves but publishes NO MX — mail likely bounces")
        else:
            fails.append(f"{domain_l} does not resolve and has no MX — this address cannot receive mail")
    if local_l in ROLE:
        warns.append(f"'{local_l}@' is a role account, not a person — boss-hunt wants a human")
    if domain_l in FREEMAIL:
        warns.append(f"{domain_l} is free mail — never use a scraped personal address (WORKFLOW-RULES §4)")
    return fails, warns


def main():
    if len(sys.argv) < 2:
        print("usage: check_email.py <address> [address ...]")
        sys.exit(2)
    bad = False
    for addr in sys.argv[1:]:
        fails, warns = check(addr)
        if fails:
            bad = True
            print(f"🔴 {addr}")
            for f in fails:
                print(f"   ❌ {f}")
        elif warns:
            print(f"🟡 {addr}")
        else:
            print(f"🟢 {addr} — domain accepts mail (mailbox existence NOT verified)")
        for w in warns:
            print(f"   ⚠️  {w}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
