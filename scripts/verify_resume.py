#!/usr/bin/env python3
"""verify_resume.py — mechanical QA for a tailored résumé (deterministic checks only).

Catches what the LLM shouldn't have to eyeball, and what tailoring bugs break:
page count · Summary ≤300 chars · ATS text layer (email/phone literal, no cid) ·
the www link · and REVERSE-CHRONOLOGICAL experience order (Andy's method).

Tailoring (Summary/Skills/bullet emphasis) stays a human+LLM job; this only verifies.

Usage:
  scripts/verify_resume.py cv/main_<co>.tex     # one résumé (.tex + matching .pdf)
  scripts/verify_resume.py --all                # every cv/main_*.tex
"""
import sys, os, re, glob, subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Hold résumé prose to the SAME honesty bar as email bodies. Reuse check_outreach's canonical
# word-lists (single source of truth) with a safe fallback.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from kit_config import (OWNER_EMAIL, OWNER_PHONE, OWNER_SITE_URL, RETIRED,
                            ROLE_IMPLY, AI_TOOL_NAME)
except Exception:
    OWNER_EMAIL, OWNER_PHONE = "you@example.com", "555-0100"
    OWNER_SITE_URL, AI_TOOL_NAME = "https://www.yoursite.example", ""
    RETIRED, ROLE_IMPLY = [], []
try:
    from check_outreach import BANNED
except Exception:
    BANNED = ["actually", "honestly", "genuinely", "simply", "really", "exactly", "exact",
              "leverage", "delve", "seamless", "robust", "passionate", "proven track record"]
MON = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}

def startkey(datestr):
    left = re.split(r'--|–|—|to', datestr)[0].strip()
    m = re.search(r'([A-Z][a-z]{2})\s+(\d{4})', left)
    if m: return int(m.group(2)) * 100 + MON.get(m.group(1), 1)
    y = re.search(r'(\d{4})', left)
    return int(y.group(1)) * 100 if y else 0

def experience_order(src, moderncv):
    """Return (entries, is_reverse_chron or None-if-unparseable)."""
    if moderncv:
        # scope to an Experience section if present
        seg = src
        m = re.search(r'\\section\{[^}]*(Experience|Employment)[^}]*\}(.*?)(\\section\{|\Z)', src, re.S | re.I)
        if m: seg = m.group(2)
        ents = re.findall(r'\\cventry\{([^}]*)\}\{[^}]*\}\{([^}]*)\}', seg)
        exp = [(c, d) for d, c in ents if re.search(r'\d{4}', d)]
    else:
        ents = re.findall(r'\\textbf\{([^}]+)\}\s*\\hfill[^\n]*?\$\\cdot\$\s*([^\\\n]+?)\\\\', src)
        exp = [(c, d) for c, d in ents if re.search(r'\d{4}', d) and re.search(r'--|–|—', d)]
    if len(exp) < 2:
        return exp, None
    keys = [startkey(d) for _, d in exp]
    return exp, (keys == sorted(keys, reverse=True))

def check(tex_path):
    full = tex_path if os.path.isabs(tex_path) else os.path.join(REPO, tex_path)
    src = open(full, encoding="utf-8", errors="ignore").read()
    moderncv = "moderncv" in (re.search(r'\\documentclass[^\n]*', src) or [""])[0] \
        if isinstance(re.search(r'\\documentclass[^\n]*', src), re.Match) else "moderncv" in src[:400]
    results = []  # (label, status, detail)  status: PASS/FAIL/WARN

    # 1. Summary length (article template)
    m = re.search(r'\\section\*?\{Summary\}\s*\n(.+?)\n\s*\n', src, re.S)
    if m:
        t = re.sub(r'\\[%$&]', lambda x: x.group()[1], m.group(1)).strip()
        t = re.sub(r'\s+', ' ', t)
        results.append(("Summary ≤300", "PASS" if len(t) <= 300 else "FAIL", f"{len(t)} chars"))
        # 1b. Summary voice consistency: the Summary must use the same
        # subject-dropped voice as the experience bullets — NO first-person ("I drove…", "my", "me").
        # First person in the Summary while bullets are subject-dropped is an inconsistency tripwire.
        # (Outreach EMAILS stay first-person; this rule is résumé-Summary-only.)
        fp = re.findall(r"(?:^|[^A-Za-z'])(I|I'm|I've|I'll|my|My|me|Me)(?=[^A-Za-z]|$)", t)
        results.append(("Summary voice (no 1st-person)",
                        "PASS" if not fp else "FAIL",
                        "subject-dropped, matches bullets" if not fp
                        else f"first-person in Summary {sorted(set(fp))} — rewrite subject-dropped to match the bullets"))
    else:
        results.append(("Summary ≤300", "WARN", "no Summary section found"))

    # content = source minus LaTeX comments (comments don't render)
    content = re.sub(r'(?<!\\)%.*', '', src)

    # 2. www link (moderncv templates legitimately show no site link)
    if OWNER_SITE_URL in src:
        results.append(("www link", "PASS", OWNER_SITE_URL))
    elif moderncv:
        results.append(("www link", "WARN", "moderncv shows no site link (expected)"))
    else:
        results.append(("www link", "FAIL", "missing/non-www"))

    # 3. reverse-chron order
    exp, rc = experience_order(src, moderncv)
    order = " > ".join(f"{c.strip()}({d.strip()[:9]})" for c, d in exp)
    if rc is None:
        results.append(("reverse-chron", "WARN", f"unparseable ({'moderncv' if moderncv else 'article'})"))
    else:
        results.append(("reverse-chron", "PASS" if rc else "FAIL", order))

    # 4. no em-dash in rendered content — the literal char OR LaTeX '---' markup (en-dash '--' is fine)
    emdash = ("—" in content) or ("---" in content)
    results.append(("no em-dash", "PASS" if not emdash else "FAIL",
                    "clean" if not emdash else ("literal —" if "—" in content else "LaTeX --- (renders em-dash)")))

    # 4c. HONESTY / AI-tells scan — same bar as email bodies (check_outreach BANNED + your RETIRED)
    clow = content.lower()
    hit_banned = [w for w in BANNED if re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", clow)]
    results.append(("no AI-tell words", "PASS" if not hit_banned else "FAIL",
                    "clean" if not hit_banned else f"found: {', '.join(hit_banned)}"))
    hit_retired = [w for w in RETIRED if w.lower() in clow]
    results.append(("no retired/incorrect figures",
                    "PASS" if not hit_retired else "FAIL",
                    ("clean" if RETIRED else "no RETIRED list configured (kit_config.py) — nothing checked")
                    if not hit_retired else f"found: {', '.join(hit_retired)}"))
    if ROLE_IMPLY:
        hit_role = [p for p in ROLE_IMPLY if re.search(p, clow)]
        results.append(("role-claim honesty", "PASS" if not hit_role else "WARN",
                        "clean" if not hit_role
                        else "claims a role or an artifact that may not be yours — check it against your own history"))
    # Your AI tool must be named when AI/agentic tooling is referenced
    if AI_TOOL_NAME:
        mentions_ai_tool = bool(re.search(r"agentic|\bllm\b|ai enablement|ai tooling|ai product|vibe cod|ai[- ]assisted", clow))
        if mentions_ai_tool:
            results.append((f"names '{AI_TOOL_NAME}'", "PASS" if AI_TOOL_NAME.lower() in clow else "FAIL",
                            "present" if AI_TOOL_NAME.lower() in clow
                            else f"AI tooling referenced but '{AI_TOOL_NAME}' not named"))

    # 4b. 2-line bullet cap (article/plain-professional template): flag any \item whose
    # rendered text is long enough to likely wrap past 2 lines (the rule: start a new bullet
    # if it doesn't fit on 2 lines). Char heuristic tuned to this template's width;
    # confirmed 3-line offenders ran ~245+ chars, real 2-line bullets top out ~185.
    if not moderncv:
        def _vis(t):
            t = re.sub(r'\\[a-zA-Z]+\*?(\[[^\]]*\])?', '', t)   # strip \commands
            t = t.replace('{', '').replace('}', '')
            t = re.sub(r'\\([%$&#])', r'\1', t)                 # unescape \% \$ \& \#
            return re.sub(r'\s+', ' ', t).strip()
        CAP = 195
        items = [_vis(it) for it in re.findall(r'\\item\s+(.+)', content)]
        longs = [s for s in items if len(s) > CAP]
        if longs:
            results.append(("2-line bullet cap", "WARN",
                            f"{len(longs)} bullet(s) >{CAP} chars (likely >2 lines): "
                            + " | ".join(f'"{s[:45]}…" ({len(s)})' for s in longs)))
        else:
            results.append(("2-line bullet cap", "PASS", f"all {len(items)} bullets ≤{CAP} chars"))

    # 5. PDF checks
    pdf = full[:-4] + ".pdf"
    if os.path.exists(pdf):
        try:
            info = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
            pages = int(re.search(r'Pages:\s*(\d+)', info).group(1))
            want = 2 if moderncv else 1
            results.append(("page count", "PASS" if pages == want else "FAIL", f"{pages} (want {want})"))
        except Exception:
            results.append(("page count", "WARN", "pdfinfo unavailable"))
        try:
            txt = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True).stdout
            _ats_ok = (OWNER_EMAIL in txt and OWNER_PHONE in txt)
            results.append(("ATS email/phone", "PASS" if _ats_ok else "FAIL",
                            "literal" if _ats_ok else "missing"))
            results.append(("ATS no-cid", "PASS" if "(cid:" not in txt else "FAIL", "clean" if "(cid:" not in txt else "cid markers"))
        except Exception:
            results.append(("ATS", "WARN", "pdftotext unavailable"))
    else:
        results.append(("PDF checks", "WARN", "no .pdf built"))
    return results

def main():
    if len(sys.argv) < 2:
        print('usage: verify_resume.py cv/main_<co>.tex  |  --all'); sys.exit(2)
    files = sorted(glob.glob(os.path.join(REPO, "cv", "main_*.tex"))) if sys.argv[1] == "--all" else [sys.argv[1]]
    any_fail = False
    exempt_ct = 0
    for f in files:
        rel = os.path.relpath(f, REPO) if os.path.isabs(f) else f
        # QA-EXEMPT: résumés already SENT are kept AS-IS for historical
        # purposes. A "% QA-EXEMPT" marker grandfathers a historical build out of the FAIL gate
        # so the daily sweep only flags CURRENT builds (a new 🔴 = a real regression, not archive noise).
        try:
            exempt = "% QA-EXEMPT" in open(f, encoding="utf-8", errors="ignore").read()
        except Exception:
            exempt = False
        res = check(f)
        fails = [r for r in res if r[1] == "FAIL"]
        if exempt:
            exempt_ct += 1
            if sys.argv[1] != "--all":
                print(f"📮 {os.path.basename(rel)}  [QA-EXEMPT: sent/historical, kept as-is — not gated]")
                for lbl, st, det in res:
                    mark = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}[st]
                    print(f"   {mark} {lbl}: {det}")
            continue  # historical: never counts toward any_fail
        any_fail = any_fail or bool(fails)
        icon = "🔴" if fails else "🟢"
        if sys.argv[1] == "--all":
            if fails:
                print(f"{icon} {os.path.basename(rel)}")
                for lbl, st, det in fails:
                    print(f"     FAIL {lbl}: {det}")
        else:
            print(f"{icon} {os.path.basename(rel)}")
            for lbl, st, det in res:
                mark = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}[st]
                print(f"   {mark} {lbl}: {det}")
    if sys.argv[1] == "--all":
        tail = f" ({exempt_ct} historical/QA-EXEMPT skipped)" if exempt_ct else ""
        print(f"\n(only current-build FAILs shown above; everything else passed{tail})" if not any_fail
              else f"\n⬆ CURRENT résumés with FAILs listed above{tail}")
    sys.exit(1 if any_fail else 0)

if __name__ == "__main__":
    main()
