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
    from kit_config import (OWNER_EMAIL, OWNER_PHONE, OWNER_SITE, OWNER_SITE_URL, RETIRED,
                            RETIRED_PATTERNS, ROLE_IMPLY, AI_TOOL_NAME,
                            EXPIRED_CREDENTIALS, CREDENTIAL_EXPIRY_OK)
    _LISTS_DEGRADED = ""
except Exception as _e:
    # ⚠️ THE FALLBACK IS A DEGRADED GATE AND IT MUST SAY SO. This branch used to be silent, and the
    # failure it hides is total: the import above is ONE TUPLE, so a single missing name in
    # kit_config raises for the WHOLE tuple and every guardrail below falls back to []. The résumé
    # gate then checks against nothing and reports CLEAN.
    # 🔴 THAT IS NOT HYPOTHETICAL. A partner hit it: `EXPIRED_CREDENTIALS` and
    # `CREDENTIAL_EXPIRY_OK` arrived in a kit sync without landing in their config, and while they
    # were missing verify_resume saw **0 retired claims instead of 5** and passed a résumé because
    # it had nothing to compare against. Diagnosed by Matthew 2026-08-06, harvested 2026-08-09.
    # ⚖️ A weaker check that ANNOUNCES itself is a check; a weaker check that reports success is the
    # silent-all-clear shape this repo has now paid for four separate times. Main already carries
    # this pattern in its own verify_resume; this is that fix, ported.
    # ⛔ The fallback VALUES stay, because a fresh install before /setup legitimately has no config
    # and must still run. What changes is that it can no longer be quiet about it.
    OWNER_EMAIL, OWNER_PHONE = "you@example.com", "555-0100"
    OWNER_SITE, OWNER_SITE_URL, AI_TOOL_NAME = "yoursite.example", "https://www.yoursite.example", ""
    RETIRED, RETIRED_PATTERNS, ROLE_IMPLY = [], [], []
    EXPIRED_CREDENTIALS, CREDENTIAL_EXPIRY_OK = [], r"expir|lapsed|inactive|no longer"
    _LISTS_DEGRADED = (f"kit_config did not import ({type(_e).__name__}: {_e}); running with EMPTY "
                       f"RETIRED, RETIRED_PATTERNS, ROLE_IMPLY and EXPIRED_CREDENTIALS, so the "
                       f"honesty guardrails are NOT being checked. Run /setup or fix scripts/"
                       f"kit_config.py, then re-run.")
    print(f"⚠️  verify_resume: {_LISTS_DEGRADED}", file=sys.stderr)
try:
    from check_outreach import BANNED
    pass  # ⛔ DO NOT RESET _LISTS_DEGRADED HERE. There are TWO degradable imports and this
    # is the second one succeeding. Resetting would ERASE a kit_config failure recorded
    # above, leaving only a stderr line and a report that says the gate ran clean, which
    # is the silent-all-clear this whole block exists to prevent.
except Exception as _e:
    # ⛔ A FALLBACK THAT DOES NOT ANNOUNCE ITSELF IS NOT A FALLBACK, IT IS A WEAKER CHECK REPORTING
    # SUCCESS. This hand-copied list holds a fraction of the live one, so with `check_outreach`
    # unimportable a résumé full of AI tells prints "✅ no AI-tell words: clean" and nothing says the
    # gate was running on a third of its vocabulary. A check that degrades and announces it is a
    # check; a check that degrades quietly is a green light.
    BANNED = ["actually", "honestly", "genuinely", "simply", "really", "exactly", "exact",
              "leverage", "delve", "seamless", "robust", "passionate", "proven track record"]
    _LISTS_DEGRADED = ((_LISTS_DEGRADED + " · ") if _LISTS_DEGRADED else "") + (
        f"check_outreach did not import ({type(_e).__name__}: {_e}); running a "
        f"hand-copied fallback of {len(BANNED)} AI-tell words instead of the live list")
    print(f"⚠️  verify_resume: {_LISTS_DEGRADED}", file=sys.stderr)
# Lines and tokens that appear on ONE SIDE ONLY for reasons unrelated to a stale build: the
# contact header (strip_latex drops it, pdftotext keeps it), template icon glyph names, and
# pdftotext's page markers. Comparing them reports drift on a correctly built file.
CONTACT_LINE = re.compile("|".join(re.escape(x) for x in
                                   (OWNER_EMAIL, OWNER_PHONE, "linkedin.com/in/", OWNER_SITE) if x)
                          or r"(?!x)x")
GLYPH_NAMES = re.compile(r"\b[a-z]+-(?:alt|square|logo|android|f)[a-z-]*\b")
PAGE_MARK = re.compile(r"^\s*\d+\s*/\s*\d+\s*$", re.M)
# The header survives as a run of identifiers when pdftotext wraps it onto its own lines, and the
# source has already dropped it. These are the collapsed (letters-and-digits-only) spellings of
# the same identifiers, deleted from the signature where line breaks cannot hide them.
_IDENTS = sorted({re.sub(r"[^a-z0-9]", "", x.lower()) for x in
                  (OWNER_EMAIL, OWNER_PHONE, OWNER_SITE, OWNER_SITE_URL,
                   OWNER_SITE.replace(".", ""), "open to remote") if x} - {""},
                 key=len, reverse=True)          # longest first, so a short one cannot eat a prefix
_IDENT_RE = re.compile("|".join(re.escape(i) for i in _IDENTS)) if _IDENTS else None


def render_signature(text):
    """Collapse rendered text to the characters a reader sees, so a .tex and its pdftotext can be
    compared without tokenization artifacts.

    Hyphens, spaces and line breaks all go: LaTeX breaks "consolidating" as "consolidat-\ning" and
    justifies lines differently from pdftotext's column reconstruction, and none of that is a
    content change. What survives is letters, digits, and the characters that carry a claim
    ($, %, .), which is where a stale build actually shows up.
    """
    text = "\n".join("" if CONTACT_LINE.search(ln) else ln for ln in text.split("\n"))
    text = PAGE_MARK.sub("", text)
    text = GLYPH_NAMES.sub("", text)
    sig = re.sub(r"[^a-z0-9$%]", "", text.lower())
    return _IDENT_RE.sub("", sig) if _IDENT_RE else sig


def source_signature(tex_src):
    """The reader-visible signature of a .tex. Falls back to a crude strip if the linter cannot be
    imported, because a missing import must not silently switch the build-freshness gate off."""
    try:
        from check_style import strip_latex
        return render_signature(strip_latex(tex_src))
    except Exception:
        body = tex_src.split(r"\begin{document}")[-1]
        body = re.sub(r"(?<!\\)%.*", "", body)
        body = re.sub(r"\\[a-zA-Z@]+\*?(\[[^\]]*\])?", " ", body)
        return render_signature(body.replace("{", " ").replace("}", " "))


def build_drift(tex_src, pdf_text):
    """Compare what the SOURCE says against what the BUILT PDF says.

    THE POINT: edits land in a .tex, the fix gets reported, and nobody recompiles. The shipped PDF
    then carries defects the source does not, and every check that read the source described a file
    nobody will ever see. An mtime comparison alone is not enough evidence (a bulk touch moves every
    file at once and says nothing about content), so freshness is decided on the RENDERED TEXT, and
    the mtime supplies the "how long has this been wrong" detail.

    Returns (ratio, sample). ratio is 1.0 for an exact match; sample quotes the first stretch that
    differs, so the operator can see WHAT the PDF says instead.
    """
    import difflib
    a, b = source_signature(tex_src), render_signature(pdf_text)
    if not a or not b:
        return 0.0, "one side had no extractable text"
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ratio = sm.ratio()
    sample = ""
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            sample = (f'source reads "...{a[max(0, i1 - 25):i2 + 25]}...", '
                      f'the PDF reads "...{b[max(0, j1 - 25):j2 + 25]}..."')
            break
    return ratio, sample


def factual_accuracy(text, source_label):
    """Return a list of guardrail-violation strings found in `text`. Empty list means clean.

    Reads the honesty guardrails from kit_config, so this ships with nothing hardcoded: fill
    RETIRED / RETIRED_PATTERNS / EXPIRED_CREDENTIALS and the check has teeth, leave them empty and
    it reports that nothing was configured rather than a false all-clear.
    """
    hits = []
    flat = re.sub(r"[ \t]*\n[ \t]*", " ", text)   # PDF text wraps; a guardrail spans the wrap
    for pat, label in RETIRED_PATTERNS:
        if re.search(pat, flat, re.I | re.S):
            hits.append(f"{label} [{source_label}]")
    for lit in RETIRED:
        if lit.lower() in flat.lower():
            hits.append(f'retired claim "{lit}" [{source_label}]')
    for pat, expired_on in EXPIRED_CREDENTIALS:
        for line in text.split("\n"):
            if re.search(pat, line, re.I) and not re.search(CREDENTIAL_EXPIRY_OK, line, re.I):
                hits.append(f"credential line with no expiry marker (expired {expired_on}): "
                            f'"{line.strip()[:70]}" [{source_label}]')
                break
    return hits


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

# ── PER-CHECK RULINGS ─────────────────────────────────────────────────────────────────────────
# A `% QA-OK: <check> — <reason>` line in the .tex waives ONE named check on ONE file, and the
# reason is printed beside the result so the waiver is visible rather than silent.
#
# WHY THIS EXISTS AND WHY IT IS NARROW. Sometimes you rule that a particular résumé stays at two
# pages. The only tool available before this was `% QA-EXEMPT`, which grandfathers the WHOLE FILE
# out of the gate, honesty checks included. Using it to record a decision about LAYOUT also stops
# checking the claims and the credentials on a résumé you are about to send.
#
# ⛔ THE HONESTY CHECKS ARE NOT WAIVABLE, AT ALL. A layout preference is yours to rule on; a retired
# claim is not a preference. Anything reading on facts, links or credentials is refused here even if
# the marker names it, and the refusal is PRINTED, so a wrong marker is loud rather than ignored.
QA_OK = re.compile(r"^\s*%\s*QA-OK:\s*(.+?)\s+(?:—|--)\s+(.+?)\s*$", re.M)
WAIVABLE = {"page count", "2-line bullet cap", "Summary ≤300"}
NEVER_WAIVABLE = {"factual accuracy (honesty guardrails)", "no retired/incorrect figures",
                  "no AI-tell words", "www link", "role honesty", "STALE BUILD",
                  "ATS email/phone", "ATS no-cid", "credentials"}


def rulings(tex_src):
    """{check name: reason} for every `% QA-OK:` line, minus any that names an honesty check.

    Returns (accepted, refused). `refused` is not silently dropped: `check()` turns each entry into
    a FAIL row, because a marker aimed at an honesty check is either a misunderstanding worth
    correcting or an attempt worth seeing.
    """
    out, refused = {}, []
    for name, reason in QA_OK.findall(tex_src):
        name = name.strip()
        if any(name.lower().startswith(n.lower()[:12]) for n in NEVER_WAIVABLE):
            refused.append(name)
            continue
        out[name] = reason.strip()
    return out, refused


def application_slugs():
    """Canonical company tokens for every company with a LIVE application record on disk.

    THE ENROLLMENT SIGNAL. Deciding which résumés a sweep should hold to the gate used to mean a
    hand-added `% QA-EXEMPT` marker, which is enrollment BY MEMORY: a résumé joined the gate because
    someone remembered to leave it out. `documents/applications/<slug>/` is created by the act of
    applying, so it self-heals — a new application enrolls its résumé and no one has to remember.

    An `outcome.md` in the folder CLOSES the enrollment: a resolved application drops out of the
    sweep on the strength of a recorded fact rather than an age heuristic standing in for one. The
    file is read rather than the directory's date trusted, so an application that is quiet but still
    open stays gated.
    """
    out = set()
    for d in glob.glob(os.path.join(REPO, "documents", "applications", "*")):
        if os.path.isdir(d):
            if os.path.isfile(os.path.join(d, "outcome.md")):
                continue
            tok = re.sub(r"[^a-z0-9]", "", os.path.basename(d).split("_")[0].lower())
            if len(tok) >= 4:      # a 3-character token collides across unrelated companies
                out.add(tok)
    return out


def has_application(tex_path, slugs=None):
    """True when this résumé's company carries a live application record."""
    slugs = application_slugs() if slugs is None else slugs
    base = os.path.basename(tex_path)
    if not base.startswith("main_"):
        return True            # a per-application draft IS an application by construction
    key = re.sub(r"[^a-z0-9]", "", base[5:-4].lower())
    return any(key.startswith(s) or s.startswith(key) for s in slugs)


def check(tex_path):
    full = tex_path if os.path.isabs(tex_path) else os.path.join(REPO, tex_path)
    src = open(full, encoding="utf-8", errors="ignore").read()
    moderncv = "moderncv" in (re.search(r'\\documentclass[^\n]*', src) or [""])[0] \
        if isinstance(re.search(r'\\documentclass[^\n]*', src), re.Match) else "moderncv" in src[:400]
    results = []  # (label, status, detail)  status: PASS/FAIL/WARN

    # ⛔ RULINGS ARE READ ONCE, AT THE TOP, AND A REFUSED WAIVER IS REPORTED FROM HERE, not from
    # inside the page-count branch, which only runs when a PDF exists. A forged waiver on a file
    # with no build must still be reported, so the refusal cannot depend on which other checks
    # happen to run.
    _rules, _refused = rulings(src)
    for _bad in _refused:
        results.append((f"⛔ refused waiver: {_bad}", "FAIL",
                        "an honesty check cannot be waived by a QA-OK marker"))

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
    # ⚠️ A DEGRADED LIST MAY NOT REPORT A CLEAN PASS. "Clean" against a fallback means "clean
    # against a fraction of the list", which is a different claim and must read differently.
    if _LISTS_DEGRADED and not hit_banned:
        results.append(("no AI-tell words", "WARN",
                        f"DEGRADED: checked against {len(BANNED)} fallback words, not the live list"))
    else:
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

    # 4d. FACTUAL ACCURACY on the SOURCE
    src_hits = factual_accuracy(content, "tex")
    pdf_scanned = False

    # 5. PDF checks
    pdf = full[:-4] + ".pdf"
    if os.path.exists(pdf):
        # 5a. mtime evidence for the STALE BUILD verdict below. 60s of grace, because a git
        # checkout or a file copy stamps the pair within a second or two and that is not an edit.
        STALE_GRACE_S = 60
        t_tex, t_pdf = os.path.getmtime(full), os.path.getmtime(pdf)
        older_by = int(t_tex - t_pdf)
        pdf_older = older_by > STALE_GRACE_S
        age = (f"{older_by}s" if older_by < 90 else f"{older_by // 60}m" if older_by < 5400
               else f"{older_by // 3600}h" if older_by < 172800 else f"{older_by // 86400}d")
        # ⚡ ONE EXTRACTION, NOT TWO SPAWNS (ported from the main tree, 2026-08-08). `pdfinfo` used
        # to be spawned solely to read `Pages:`, off a file `pdftotext` re-reads a few lines below.
        # poppler emits one form feed per page, so the count is already in the text this check
        # extracts anyway. Verified upstream across the whole corpus, zero mismatches, 1-page and
        # 2-page files alike, so this removes one external binary from every sweep.
        try:
            txt = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True).stdout
        except Exception:
            txt = None
        try:
            if txt is None:
                raise RuntimeError("pdftotext unavailable")
            pages = txt.count("\f")
            want = 2 if moderncv else 1
            _hit = next((k for k in _rules if k.lower().startswith("page count")), None)
            if pages != want and _hit:
                results.append(("page count", "WARN",
                                f"{pages} (want {want}) — RULED: {_rules[_hit]}"))
            else:
                results.append(("page count", "PASS" if pages == want else "FAIL", f"{pages} (want {want})"))
        except Exception:
            results.append(("page count", "WARN", "pdftotext unavailable"))
        try:
            if txt is None:
                raise RuntimeError("pdftotext unavailable")
            _ats_ok = (OWNER_EMAIL in txt and OWNER_PHONE in txt)
            results.append(("ATS email/phone", "PASS" if _ats_ok else "FAIL",
                            "literal" if _ats_ok else "missing"))
            results.append(("ATS no-cid", "PASS" if "(cid:" not in txt else "FAIL", "clean" if "(cid:" not in txt else "cid markers"))

            # The BUILT artifact is what a stranger reads, so the guardrails run on it too.
            src_hits += factual_accuracy(txt, "PDF")
            pdf_scanned = True

            # 5b. STALE BUILD. Decided on the rendered text, because that is what ships; the
            # mtime only supplies the "how long has this been wrong" detail.
            ratio, sample = build_drift(src, txt)
            # 99.9%: a freshly built pair scores 100.000%, and the nearest divergent file in a
            # real corpus scored 99.40%. Nothing lands in between, so the threshold sits in an
            # empty band rather than on a judgment call.
            if ratio < 0.999:
                results.append(("STALE BUILD", "FAIL",
                                f"the built PDF does NOT match the source ({ratio:.2%} of the "
                                f"rendered text agrees{', PDF is ' + age + ' older' if pdf_older else ''}). "
                                f"{sample}. The .tex was edited and never recompiled, so nothing "
                                f"verified on the source describes what ships. Rebuild with "
                                f"pdflatex, then re-run."))
            elif pdf_older:
                results.append(("build freshness", "WARN",
                                f"PDF is {age} older than the .tex, but the rendered text still "
                                f"matches ({ratio:.2%}), so this is a timestamp, not an unbuilt edit"))
            else:
                results.append(("build freshness", "PASS",
                                f"PDF is current and matches the source ({ratio:.2%})"))
        except Exception as e:
            results.append(("ATS", "WARN", "pdftotext unavailable"))
            results.append(("STALE BUILD", "WARN",
                            f"could not read the built PDF, so it was NOT verified ({e})"))
    else:
        results.append(("PDF checks", "WARN", "no .pdf built"))
        results.append(("STALE BUILD", "WARN", "no .pdf exists, so nothing was verified on what ships"))

    # 6. factual accuracy verdict, source and built artifact together
    seen = list(dict.fromkeys(src_hits))
    scope = "tex + PDF" if pdf_scanned else "tex only, no readable PDF"
    _configured = bool(RETIRED or RETIRED_PATTERNS or EXPIRED_CREDENTIALS)
    results.append(("factual accuracy (honesty guardrails)",
                    "PASS" if not seen else "FAIL",
                    (f"clean, {scope}" if _configured
                     else "no guardrails configured (kit_config.py) — nothing checked")
                    if not seen else " · ".join(seen)))
    return results

def main():
    if len(sys.argv) < 2:
        print('usage: verify_resume.py cv/main_<co>.tex  |  --all  |  --apps'); sys.exit(2)
    # --apps sweeps the per-application drafts. Kept SEPARATE from --all on purpose: a résumé that
    # was already submitted with a defect will fail forever and nothing recovers it, so those files
    # must not turn the daily --all sweep permanently red.
    if sys.argv[1] == "--apps":
        files = sorted(glob.glob(os.path.join(REPO, "documents", "applications", "*", "cv_draft.tex")))
    elif sys.argv[1] in ("--all", "--apps"):
        files = sorted(glob.glob(os.path.join(REPO, "cv", "main_*.tex")))
    else:
        files = [sys.argv[1]]
    any_fail = False
    exempt_ct = 0
    # ⚖️ RE-SUBJECTED, NOT SILENCED. A résumé is GATED while its company has a live application
    # record, and ARCHIVE otherwise. Archive failures are still COMPUTED and still REPORTED, with a
    # count and the command to read them; they only stop driving the exit code, so a sweep reports
    # the handful you actually sent instead of every résumé you ever built.
    # ⛔ This is not a baseline and not an amnesty. No defect is excused.
    show_archive = "--archive" in sys.argv
    _slugs = application_slugs()
    archive_red, archive_ok = [], 0
    for f in files:
        rel = os.path.relpath(f, REPO) if os.path.isabs(f) else f
        # A bare "cv_draft.tex" names nothing under --apps, where every file has that basename.
        name = os.path.basename(rel) if os.path.basename(rel).startswith("main_") \
            else os.path.join(os.path.basename(os.path.dirname(rel)), os.path.basename(rel))
        # QA-EXEMPT: résumés already SENT are kept AS-IS for historical
        # purposes. A "% QA-EXEMPT" marker grandfathers a historical build out of the FAIL gate
        # so the daily sweep only flags CURRENT builds (a new 🔴 = a real regression, not archive noise).
        try:
            exempt = "% QA-EXEMPT" in open(f, encoding="utf-8", errors="ignore").read()
        except Exception:
            exempt = False
        # ⚡ HOISTED ABOVE check() (2026-08-08, ported from the main tree). On a SWEEP an exempt file
        # prints nothing and never counts toward any_fail (the `continue` below), so its verdict used
        # to be computed in full and then discarded. Measured upstream at 40 exempt files, 3.29s of
        # an 11.83s `--all` run, spent on rows no reader ever sees.
        #
        # ⛔ SCOPED TO THE SWEEP, deliberately. A NAMED file still runs check() and still prints its
        # rows below, because asking about one file is asking about that file. That is the send
        # gate's per-résumé QA tripwire, and weakening it here would be the same defect the archive
        # rule already had to be corrected for once, on the artifact that goes to employers.
        if exempt and sys.argv[1] in ("--all", "--apps"):
            exempt_ct += 1
            continue
        res = check(f)
        fails = [r for r in res if r[1] == "FAIL"]
        if exempt:
            exempt_ct += 1
            if sys.argv[1] not in ("--all", "--apps"):
                print(f"📮 {name}  [QA-EXEMPT: sent/historical, kept as-is — not gated]")
                for lbl, st, det in res:
                    mark = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}[st]
                    print(f"   {mark} {lbl}: {det}")
            continue  # historical: never counts toward any_fail
        gated = has_application(f, _slugs)
        if not gated:
            (archive_red.append(name) if fails else None)
            if not fails:
                archive_ok += 1
            if show_archive and fails:
                print(f"\U0001F4E6 {name}  [ARCHIVE: no live application record, not promoted]")
                for lbl, st, det in fails:
                    print(f"     FAIL {lbl}: {det}")
            if sys.argv[1] in ("--all", "--apps"):
                continue
        # ⛔ THE ARCHIVE SUPPRESSION IS FOR THE SWEEP ONLY, AND THE `not _is_sweep` HALF IS THE
        # WHOLE POINT. Ported 2026-08-08 with the defect ALREADY FIXED, so this kit never passes
        # through the broken shape the upstream repo shipped for a while.
        #
        # 🔴 WHAT THE BROKEN SHAPE COST THERE: applying the archive rule to EVERY invocation, not
        # just the sweep, turned the gate off for the two cases that matter most. A company with no
        # `documents/applications/<slug>/` folder is not "archive" — it is the NORMAL state while a
        # résumé is being BUILT, before you apply, and the permanent state for boss-hunt outreach,
        # which never creates an application folder at all. The gate printed ❌ for a retired claim
        # and a bad link and still EXITED 0, so every caller reading the exit code saw green,
        # including the send script that runs this before attaching a résumé.
        #
        # ⚖️ ASKING ABOUT ONE FILE IS ASKING ABOUT THAT FILE. A named file always drives the exit
        # code, gated or not.
        _is_sweep = sys.argv[1] in ("--all", "--apps")
        any_fail = any_fail or (bool(fails) and (gated or not _is_sweep))
        icon = "🔴" if fails else "🟢"
        if sys.argv[1] in ("--all", "--apps"):
            if fails:
                print(f"{icon} {name}")
                for lbl, st, det in fails:
                    print(f"     FAIL {lbl}: {det}")
        else:
            print(f"{icon} {name}")
            for lbl, st, det in res:
                mark = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}[st]
                print(f"   {mark} {lbl}: {det}")
    if sys.argv[1] in ("--all", "--apps"):
        tail = f" ({exempt_ct} historical/QA-EXEMPT skipped)" if exempt_ct else ""
        print(f"\n(only current-build FAILs shown above; everything else passed{tail})" if not any_fail
              else f"\n⬆ GATED résumés with FAILs listed above{tail}")
        # ⛔ THE ARCHIVE LINE IS NOT OPTIONAL. Silence here would be the amnesty this design
        # forbids: the number stays in front of the reader whether or not it drives the exit code.
        if archive_red or archive_ok:
            print(f"\U0001F4E6 ARCHIVE (no live application record): {len(archive_red)} with FAILs, "
                  f"{archive_ok} clean. Not promoted to the exit code."
                  + ("" if show_archive else "  See them: verify_resume.py --all --archive"))
    sys.exit(1 if any_fail else 0)

if __name__ == "__main__":
    main()
