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
import re
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

    # 🔴 DOCTOR READ kit_config DIRECTLY AND CERTIFIED THE VETO LIST HEALTHY WHILE THE MODULE THAT
    # USES IT COULD NOT LOAD IT AT ALL (found 2026-08-05). check_screen_gate imports ~11 names as
    # ONE tuple, so a single name missing from a long-lived kit_config.py zeroes every screening
    # list there while the list still reads fine from here. A real kit had 22 live veto patterns
    # and a completely dead screen at the same time, and this section printed a green checkmark.
    # ⚖️ Ask the CONSUMER, never the config. A config value nothing can import is not configured.
    try:
        import check_screen_gate as _csg
        if getattr(_csg, "CONFIG_ERROR", None):
            blocking("the screening gate cannot load your config, so EVERY screen passes "
                     f"silently ({_csg.CONFIG_ERROR})",
                     "your scripts/kit_config.py predates a name the code needs — copy the "
                     "missing name(s) from scripts/kit_config.example.py, keeping your values")
        elif not list(getattr(_csg, "INDUSTRY_VETO", []) or []):
            blocking("the screening gate loaded an EMPTY industry veto — it passes everything",
                     "add your deal-breaker industries to INDUSTRY_VETO in scripts/kit_config.py")
        else:
            ok(f"screening gate reads {len(_csg.INDUSTRY_VETO)} veto pattern(s) from your config")
    except Exception as _e:
        advisory(f"could not check the screening gate ({type(_e).__name__})",
                 "run `python3 scripts/check_screen_gate.py -` and read the error")

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

        # 🔴 A STALE settings.json USED TO REPORT GREEN, and that was the worst failure this
        # check could have. Counting hook GROUPS says nothing about WHICH hooks are wired. A
        # months-old file with 7 groups and no `check_pair.py` in it passed as "✅ hooks wired"
        # while the blocking PAIR gate was absent entirely. Anyone who hand-edited one permission
        # keeps their old file forever (the installer only refreshes a byte-identical copy), so
        # this is the normal state of a long-lived install, not an edge case.
        # ⚖️ The fix is a COMPARISON, never a count: every script the shipped example wires must
        # appear in the live file. A health check that cannot say WHICH gate is missing is a
        # health check that certifies its own blind spot.
        def _scripts(obj):
            found = set()
            for groups in (obj.get("hooks") or {}).values():
                for g in groups or []:
                    for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                        for m in re.finditer(r"scripts/([A-Za-z0-9_.-]+\.(?:py|sh))",
                                             str(h.get("command") or "")):
                            found.add(m.group(1))
            return found

        live = _scripts(cfg)
        try:
            want = _scripts(json.loads(_read(".claude", "settings.example.json") or "{}"))
        except Exception:
            want = set()
        missing = sorted(want - live)
        if missing:
            blocking(f"settings.json is STALE — {len(missing)} shipped hook script(s) are not "
                     f"wired: {', '.join(missing)}",
                     "cp .claude/settings.example.json .claude/settings.json   "
                     "(back up first if you customised it)")
        else:
            ok(f"hooks wired ({n} hook group(s), {len(live)} script(s), current with the example)")

        # A hook naming a script that is not on disk fires and fails, which reads as a broken
        # session rather than a missing file.
        gone = sorted(x for x in live if not os.path.exists(os.path.join(ROOT, "scripts", x)))
        if gone:
            blocking(f"{len(gone)} wired hook(s) point at a script that does not exist: "
                     f"{', '.join(gone)}", "re-run `bash install.sh .`")
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

# ── 5. network & closeness ───────────────────────────────────────────────────────────────
# ADVISORY, NEVER BLOCKING. The kit works without these — it just cannot reach the warm rungs
# (5-7), because a warm ask needs a stated relationship and nothing can state one but you.
# The message says exactly that, so a fresh install reads as "next step", not "broken".
print("\n[5] network & closeness (the warm rungs run on this)")
try:
    import glob as _glob
    _exports = _glob.glob(os.path.join(ROOT, "documents", "linkedin-exports", "Connections-*.csv"))
    if _exports:
        ok(f"LinkedIn export ingested ({len(_exports)} on file, emails stripped)")
    else:
        advisory("no LinkedIn export ingested yet — the network surfaces are empty",
                 "LinkedIn → Settings → Data privacy → Get a copy of your data; "
                 "drop the .zip in Downloads, then run /level-network")
    if os.path.exists(os.path.join(ROOT, "documents", "contact-closeness.json")):
        try:
            _cc = json.loads(_read("documents", "contact-closeness.json") or "{}")
            _rows = {k: v for k, v in (_cc.get("contacts") or {}).items() if isinstance(v, dict)}
            _lv = sum(1 for r in _rows.values() if r.get("closeness"))
            ok(f"closeness store present — {_lv}/{len(_rows)} rows levelled",
               "" if _lv == len(_rows) else "finish anytime: /level-network (it resumes)")
        except Exception:
            advisory("closeness store present but unreadable",
                     "a .bak sits beside it; re-run /level-network")
    else:
        advisory("closeness store absent — warm rungs (5-7) stay locked; cold rungs still work",
                 "run /level-network in Claude Code (needs the export above)")
except Exception:
    line("ℹ️ ", "network check skipped (unexpected error) — the rest of the kit is unaffected")

# ── 6. your inputs ───────────────────────────────────────────────────────────────────────
# THREE FILES SEED CORRECTLY AND THEN DEGRADE IN SILENCE, and until 2026-08-05 nothing checked
# any of them. install.sh copies every partner-docs/*.md into documents/ when missing, so they
# are PRESENT. Present and unfilled is the problem:
#   • employer-criteria-matrix.md — rank_criteria.py returns "" and ranks with NO personal
#     weighting, then cites a file that says nothing.
#   • kit_config.SEGMENTS — ships POPULATED with segment-a/b/c. mail-draft.sh validates against
#     that closed list, so a cold send is ACCEPTED and logged under a placeholder lane. The
#     hot-zone comparison (send ~5 per segment, compare reply rates) then compares noise.
#     ⚠️ Worse than a block, because a block would have told you.
#   • writing-samples.md — check_outreach.py has no gate on it, so generic-voiced outreach
#     ships with zero warning.
# ⚖️ The test is a BYTE COMPARISON against the shipped copy in partner-docs/, never a marker
# string: it is the same test install.sh uses to decide whether to refresh, it cannot drift as
# the templates are reworded, and it answers the only question that matters — did you change it.
# ⚖️ ADVISORY, never blocking. On a fresh install unfilled is the CORRECT state, so this reads
# as the next step rather than a fault, the same way section [5] does.
print("\n[6] your inputs (these degrade silently — nothing else reports them)")
import filecmp as _filecmp

for _doc, _what in [
    ("employer-criteria-matrix.md",
     "ranking runs with no personal weighting, and cites a file that says nothing"),
    ("writing-samples.md",
     "outreach gets written in a generic voice and no linter catches it"),
    ("segments.md", "the lanes you test are not yours"),
]:
    _live = os.path.join(ROOT, "documents", _doc)
    _ship = os.path.join(ROOT, "partner-docs", _doc)
    if not os.path.exists(_live):
        advisory(f"documents/{_doc} is missing — {_what}",
                 "run `bash install.sh .` to seed it from partner-docs/")
    elif os.path.exists(_ship) and _filecmp.cmp(_live, _ship, shallow=False):
        advisory(f"documents/{_doc} is still the shipped template — {_what}",
                 f"open documents/{_doc} and fill in the top few rows")
    else:
        ok(f"{_doc} has your edits")

# The segment slugs live in kit_config, not in a doc, and they are the ones that reach a SEND.
try:
    _segs = list(getattr(KC, "SEGMENTS", {}) or {})
    _placeholder = [s for s in _segs if re.fullmatch(r"segment-[a-z]", str(s))]
    if _placeholder:
        advisory(f"kit_config.SEGMENTS still ships placeholder slug(s): {', '.join(_placeholder)} "
                 "— mail-draft.sh will ACCEPT these on a cold send and log it under a lane that "
                 "means nothing, so your reply-rate comparison comes out as noise",
                 "edit SEGMENTS in scripts/kit_config.py and documents/segments.md to your own "
                 "lanes (3 to 5, each backed by something on your verifiable record)")
    elif _segs:
        ok(f"segment slugs are yours: {', '.join(str(s) for s in _segs)}")
    else:
        advisory("kit_config.SEGMENTS is empty — cold sends will be blocked for a missing segment",
                 "define 3 to 5 lanes in scripts/kit_config.py")
except NameError:
    line("ℹ️ ", "segment check skipped (kit_config did not load — see [1])")

# ── 7. updates ───────────────────────────────────────────────────────────────────────────
print("\n[7] staying current")
if os.path.isdir(os.path.join(ROOT, ".git")):
    try:
        # 🔴 THIS USED TO CHECK ONLY THAT `origin` HAD A URL, and that is the blind spot that cost
        # one real install weeks (fixed 2026-08-05). If you forked the kit, `origin` is YOUR repo.
        # Every update then pulls from your own fork, finds nothing, and reports success, while
        # this section printed "✅ git remote set" over the top of it.
        # ⚠️ The updater cannot save you either: it resolves the kit by URL, but falls back to
        # `origin` unconditionally when NO remote URL contains the kit name. A one-remote fork has
        # no such URL, so the fallback fires and the fix never engages.
        # ⚖️ So the question is not "is there a remote", it is "does ANY remote point at the kit".
        rv = subprocess.run(["git", "remote", "-v"], cwd=ROOT,
                            capture_output=True, text=True, timeout=10)
        remotes = rv.stdout if rv.returncode == 0 else ""
        if not remotes.strip():
            advisory("git repo has no remote — you cannot pull updates",
                     "clone the kit from GitHub instead of copying the folder")
        elif "job-attractor" in remotes:
            ok("a remote points at the kit",
               "update with: double-click 'Update Kit.command'")
        else:
            blocking("NO remote points at the kit — updates cannot reach you, and the updater "
                     "will report success anyway",
                     'git remote add kit https://github.com/mestoy/job-attractor-kit '
                     '&& git fetch kit && git merge --ff-only kit/main')

        # A branch tracking a non-kit remote is the same trap wearing different clothes: the fetch
        # succeeds, the merge finds nothing, and nothing says the update never arrived.
        tb = subprocess.run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                            cwd=ROOT, capture_output=True, text=True, timeout=10)
        up = (tb.stdout or "").strip()
        if up and remotes.strip():
            rname = up.split("/", 1)[0]
            rurl = subprocess.run(["git", "remote", "get-url", rname], cwd=ROOT,
                                  capture_output=True, text=True, timeout=10).stdout
            if "job-attractor" not in rurl:
                advisory(f"your branch tracks '{up}', which is not the kit",
                         "a bare `git pull` follows this and delivers nothing; "
                         "use 'Update Kit.command' or merge kit/main explicitly")
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
