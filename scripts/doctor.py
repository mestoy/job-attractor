#!/usr/bin/env python3
"""doctor.py — is this kit ready to use? Read-only health check.

Run it any time: after install, after an update, or when something behaves oddly.
It changes nothing. It tells you what is missing and the exact command to fix it.

WHY THIS EXISTS
    The setup steps that get skipped are the ones with no feedback. A kit whose identity is still
    "Your Name" does not announce itself — it just produces outreach signed by nobody and a résumé
    gate that rejects your own file for reasons that look like bugs. Same with an unwired hooks
    file: the enforcement layer is simply absent and nothing says so.

    So this reports the state of the things that fail QUIETLY, and prints the fix next to each one.

Usage:  python3 scripts/doctor.py
Exit:   0 = ready (warnings are fine) · 1 = something blocking is unconfigured
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL, WARN = [], []


def line(mark, label, detail=""):
    print(f"  {mark} {label}" + (f"\n      {detail}" if detail else ""))


def blocking(label, fix):
    FAIL.append(label)
    line("🔴", label, f"fix: {fix}")


def advisory(label, fix):
    WARN.append(label)
    line("⚠️ ", label, f"fix: {fix}")


def ok(label, detail=""):
    line("✅", label, detail)


def _read(*parts):
    p = os.path.join(ROOT, *parts)
    try:
        with open(p, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception:
        return None


print("── job-attractor doctor ──\n")

# ── 1. identity ──────────────────────────────────────────────────────────────────────────
# The single highest-value check. Every gate reads identity from kit_config, so placeholders
# here make the résumé and outreach linters reject your own correct work.
print("[1] your identity (scripts/kit_config.py)")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
try:
    import kit_config as KC
    placeholders = {
        "OWNER_NAME": "Your Name",
        "OWNER_SITE": "yoursite.example",
        "OWNER_EMAIL": "you@example.com",
        "OWNER_PHONE": "555-0100",
    }
    unset = [k for k, v in placeholders.items() if str(getattr(KC, k, "")).strip() == v]
    if unset:
        blocking(f"{len(unset)} identity field(s) still placeholder: {', '.join(unset)}",
                 "run `/setup` in Claude Code (it writes these for you), "
                 "or edit scripts/kit_config.py")
    else:
        ok(f"identity set — {getattr(KC, 'OWNER_NAME', '?')} · {getattr(KC, 'OWNER_SITE', '?')}")

    # Screening filters: populated is REQUIRED. An empty list does not screen nothing loudly,
    # it passes everything silently — which is the failure you never notice.
    veto = list(getattr(KC, "INDUSTRY_VETO", []) or [])
    if not veto:
        blocking("INDUSTRY_VETO is empty — every company passes the industry screen silently",
                 "run `/setup`, or add your deal-breaker industries to scripts/kit_config.py")
    else:
        ok(f"industry veto list: {len(veto)} pattern(s)")

    # Honesty lists SHIP EMPTY on purpose. Empty is correct until you have a corrected claim.
    retired = list(getattr(KC, "RETIRED", []) or [])
    if retired:
        ok(f"retired-claim list: {len(retired)} entr(y/ies) — the send gate will catch these")
    else:
        line("ℹ️ ", "retired-claim list empty (correct by default)",
             "these are figures YOU have corrected on your own resume. Nobody else's list helps "
             "you. Add yours when you have one; until then the gate says so rather than pretending.")
except Exception as e:
    blocking(f"could not load scripts/kit_config.py ({type(e).__name__}: {e})",
             "re-run `bash install.sh .` from the kit folder")

# ── 2. profile ───────────────────────────────────────────────────────────────────────────
print("\n[2] your profile (documents/PROFILE.md)")
prof = _read("documents", "PROFILE.md")
if prof is None:
    blocking("documents/PROFILE.md not found",
             "run `bash install.sh .` to seed it, then `/setup` in Claude Code")
else:
    slots = prof.count("[")
    if slots > 5:
        advisory(f"PROFILE.md still has ~{slots} unfilled [...] slots",
                 "run `/setup` in Claude Code — it interviews you and fills them")
    else:
        ok("profile filled in")

# ── 3. enforcement hooks ─────────────────────────────────────────────────────────────────
# Without settings.json the hooks never fire. Nothing errors; the gates are simply not there.
print("\n[3] enforcement hooks (.claude/settings.json)")
if os.path.exists(os.path.join(ROOT, ".claude", "settings.json")):
    try:
        cfg = json.loads(_read(".claude", "settings.json") or "{}")
        n = sum(len(v) for v in (cfg.get("hooks") or {}).values())
        ok(f"hooks wired ({n} hook group(s))")
    except Exception:
        advisory("settings.json present but not valid JSON",
                 "cp .claude/settings.example.json .claude/settings.json")
elif os.path.exists(os.path.join(ROOT, ".claude", "settings.example.json")):
    blocking("hooks NOT wired — the gates will not fire at all",
             "cp .claude/settings.example.json .claude/settings.json")
else:
    advisory("no settings.example.json found", "re-run `bash install.sh .`")

# ── 4. optional tools ────────────────────────────────────────────────────────────────────
# None of these block the core pipeline. Named individually so a missing one reads as
# "this feature is off" rather than "the kit is broken".
print("\n[4] optional tools")
for exe, what, fix in [
    ("pdflatex", "resume building", "brew install --cask basictex   (Linux: texlive-latex-recommended)"),
    ("pdftotext", "resume ATS-text check", "brew install poppler   (Linux: poppler-utils)"),
    ("bun", "job-board search CLIs", "https://bun.sh"),
    ("git", "one-click updates", "https://git-scm.com"),
]:
    if shutil.which(exe):
        ok(f"{exe} found — {what} available")
    else:
        advisory(f"{exe} missing — {what} is off", fix)

# ── 5. updates ───────────────────────────────────────────────────────────────────────────
print("\n[5] staying current")
if os.path.isdir(os.path.join(ROOT, ".git")):
    try:
        r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            ok("git remote set", f"update with: double-click 'Update Kit.command' "
                                 f"(or `git pull && bash install.sh .`)")
        else:
            advisory("git repo has no remote — you cannot pull updates",
                     "clone the kit from GitHub instead of copying the folder")
    except Exception:
        advisory("could not read the git remote", "check `git remote -v` yourself")
else:
    advisory("not a git clone — updates are manual",
             "clone the kit from GitHub to get one-click updates")

# ── verdict ──────────────────────────────────────────────────────────────────────────────
print()
if FAIL:
    print(f"🔴 {len(FAIL)} blocking item(s) — the pipeline will misbehave until these are fixed.")
    print("   Most are handled by one command: open this folder in Claude Code and type /setup")
    sys.exit(1)
if WARN:
    print(f"✅ ready to use. {len(WARN)} optional feature(s) off — see ⚠️ above.")
else:
    print("✅ everything configured. Start with /matrix-hunt or /apply <job posting>.")
sys.exit(0)
