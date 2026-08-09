#!/usr/bin/env python3
"""kit_config.py — the ONE file that makes these scripts yours. Fill this in first.

Every mechanism script in this folder imports its person-specific values from here, so
nothing about a particular job seeker is baked into the tooling. Each value can also be
overridden by an environment variable (shown in brackets) without editing this file.

Two different kinds of list live below, and the difference matters:

  * HONESTY lists (RETIRED, RETIRED_PATTERNS, ROLE_IMPLY) ship EMPTY. They encode the
    specific figures and claims YOU have retired from your own résumé. Nobody else's
    list is useful to you, and a wrong one is worse than none.

  * SCREENING lists (INDUSTRY_VETO, PE_FLAG, REMOTE_*, POLITICS_*) ship POPULATED with a
    working example set. An empty screening list does not "screen nothing loudly" — it
    silently passes everything, which is the exact failure this tooling exists to catch.
    Edit them to your own deal-breakers; do not blank them.

Usage from Python:   from kit_config import OWNER_SITE, RETIRED
Usage from bash:     eval "$(python3 scripts/kit_config.py --sh)"
"""
import os
import re

def _env(key, default):
    v = os.environ.get(key, "").strip()
    return v or default


# ─────────────────────────────────────────────────────────────────────────────
# 1. IDENTITY — used by the résumé QA, the outreach linter and the mail drafter.
# ─────────────────────────────────────────────────────────────────────────────
OWNER_NAME  = _env("JOBKIT_OWNER_NAME",  "Your Name")          # [JOBKIT_OWNER_NAME]
OWNER_SITE  = _env("JOBKIT_OWNER_SITE",  "yoursite.example")   # [JOBKIT_OWNER_SITE] no scheme
OWNER_EMAIL = _env("JOBKIT_OWNER_EMAIL", "you@example.com")    # [JOBKIT_OWNER_EMAIL]
OWNER_PHONE = _env("JOBKIT_OWNER_PHONE", "555-0100")           # [JOBKIT_OWNER_PHONE] the fragment
                                                               # that must appear literally in the
                                                               # résumé PDF's text layer
OWNER_FIRST = OWNER_NAME.split()[0] if OWNER_NAME.split() else "You"

# The site URL exactly as it should appear on the résumé (verify_resume checks for this string).
OWNER_SITE_URL = _env("JOBKIT_OWNER_SITE_URL", f"https://www.{OWNER_SITE}")

MAINTAINER_EMAIL = _env("JOBKIT_MAINTAINER_EMAIL", "")  # where mailto-fallback feedback reaches the kit maintainer; set via env, blank = GitHub issues URL only

# ─────────────────────────────────────────────────────────────────────────────
# 2. DELIVERABLE NAMING — the recipient SEES the attachment filename, so it must be
#    "<Your Name> - Resume - <Company>.pdf", never an internal source name.
#    Shell-glob patterns; mail-draft.sh warns when an attachment matches none of them.
# ─────────────────────────────────────────────────────────────────────────────
RESUME_FILENAME_PATTERNS = [
    f"{OWNER_NAME} - Resume*.pdf",
    f"{OWNER_NAME} - Resume*.docx",
    f"{OWNER_NAME} - Cover*",
    f"{OWNER_NAME} - Resume + Cover*",
]
RESUME_FILENAME_EXAMPLE = f"{OWNER_NAME} - Resume - <Company>.pdf"

# ─────────────────────────────────────────────────────────────────────────────
# 3. HONESTY GUARDRAILS — ship EMPTY on purpose. Fill with YOUR retired claims.
# ─────────────────────────────────────────────────────────────────────────────

# Literal strings that must never appear again in a résumé or an outreach email: figures
# you have since corrected, product names you got wrong, claims you cannot source.
# Example shape (yours will differ):
#   RETIRED = ["$11.5M", "adopted company-wide", "Acme Connect"]
RETIRED = []

# (regex, human-readable reason) for retired claims that mutate as you retype them.
# A literal list leaks: if you retire "2 million people use X", the variant
# "2 million people CAN use X" sails straight through. Catch the family, not the string.
# Example shape:
#   RETIRED_PATTERNS = [
#       (r"2\s*(million|m)\s+(people|residents)\s+(who\s+)?(can\s+)?(use|used|using)",
#        '"2M people use" (2M = people SERVED, never users)'),
#   ]
RETIRED_PATTERNS = []

# ── Role-claim honesty ───────────────────────────────────────────────────────
# The guardrail against honest-sounding drift: describing something your TEAM shipped as
# something YOU built. Résumé QA warns; the outreach linter fails.
#
# Getting this check right is harder than it looks, and the obvious version is wrong. A first
# cut keyed on verb-noun PROXIMITY — "I built" within ~40 chars of api|platform|pipeline. A
# red-team of that version found it blocked 8 out of 8 TRUE statements ("I built <side project>
# with an AI coding tool", "I built a RAG pipeline") while passing 5 out of 5 evasions of the
# actually-dishonest claim ("We built <Employer>'s API", "I've built…", "I developed…").
# Precisely backwards: it suppressed the differentiator and waved through the falsehood.
#
# The tell is not the VERB, it is the OBJECT — whether you are claiming an EMPLOYER'S artifact.
# "I built my own scheduling app" is true. "I built <Employer>'s payments API" is not, if you
# owned the requirements and an engineer wrote the code. So fill in these two lists and the
# patterns build themselves. Leave EMPLOYERS empty and you only get the generic checks.
EMPLOYERS = []      # e.g. ["acme", "acme corp"] — employers whose engineering work is not yours
SELF_BUILT = []     # e.g. ["my portfolio", "sidequest"] — things you genuinely built yourself

_ARTIFACT = r"(api|platform|pipeline|backend|infrastructure|system)"
_VERB = r"\b(i|we)(?:'ve| have)?\s+(built|coded|engineered|architected|developed|wrote|implemented)\b"

ROLE_IMPLY_PATTERNS = []
if EMPLOYERS:
    ROLE_IMPLY_PATTERNS.append((
        _VERB + r"[^.]{0,40}?\b(" + "|".join(re.escape(e.lower()) for e in EMPLOYERS) +
        r")\b[^.]{0,25}\b" + _ARTIFACT + r"\b",
        "claims authorship of an EMPLOYER's engineering artifact. If you owned the requirements "
        "and the decision rather than the code, say \"drove/led/shipped\" and scope it to what "
        "you personally owned",
    ))
# Possessive object = someone else's artifact. Excludes anything in SELF_BUILT, or this fires
# on a true statement about your own work.
_EXCL = "".join(r"(?!" + re.escape(s.lower()) + r")" for s in SELF_BUILT) or ""
ROLE_IMPLY_PATTERNS.append((
    _VERB + r"[^.]{0,30}?\b" + _EXCL + r"[a-z]+'s\s+[^.]{0,20}\b" + _ARTIFACT + r"\b",
    "claims authorship of someone ELSE's engineering artifact (possessive object) — scope the "
    "claim to what you personally owned",
))
ROLE_IMPLY_PATTERNS.append((
    r"\bas an engineer\b|engineer[- ]turned[- ]pm|came up as an engineer|\bmy engineering background\b",
    "implies an engineering background — check this against your own history",
))
# Regex-only view, for checks that don't need the guidance text.
ROLE_IMPLY = [p for p, _ in ROLE_IMPLY_PATTERNS]

# AI tooling you want named explicitly whenever you reference agentic/AI work.
# Set to "" to disable the check.
AI_TOOL_NAME = _env("JOBKIT_AI_TOOL_NAME", "Claude Code")

# ── Expired credentials ──────────────────────────────────────────────────────
# Certifications that have LAPSED. A résumé line that names one without saying so reads as
# current, which is a claim you cannot support in an interview. Each entry is
# (regex matching the cert name, the month/year it expired). The check is LINE-SCOPED: a line
# that names the cert and carries no expiry marker fails.
# Example shape:
#   EXPIRED_CREDENTIALS = [(r"\bCSPO\b|Certified Scrum Product Owner", "May 2024")]
EXPIRED_CREDENTIALS = []
# Words that count as saying so, on the same line as the cert name.
CREDENTIAL_EXPIRY_OK = r"expir|lapsed|inactive|no longer"

# ─────────────────────────────────────────────────────────────────────────────
# 4. VOICE MARKERS — how check_preview.py recognizes that a question is showing you
#    DRAFTED OUTREACH TEXT (a praise beat, a hook, a phrasing option) rather than an
#    ordinary planning question. Add your own recurring tics.
# ─────────────────────────────────────────────────────────────────────────────
VOICE_MARKERS = [
    OWNER_SITE.lower(),
]

# PROOF POINTS — the concrete, checkable things YOU built or moved: dollar figures, program
# names, signature technologies, awards. check_preview.py detector (b) fires when a first-person
# claim ("I built …", "I've scaled …", "my work on …") lands within ~80 characters of one of
# these, which is the shape of a drafted credential line rather than a planning question.
#
# ⚠️ These are REGEX FRAGMENTS matched against lowercased text, so escape any literal `$` or `.`
# (`\$35b`, `v1\.0`). Ship yours here; an EMPTY list simply disables detector (b) — the other
# three detectors still fire, so the gate degrades rather than opening.
PROOF_POINTS = [
    # r"\$40m", r"0-to-1", r"claims platform", r"the migration",  ← shapes, not real values
]
#
# These are compiled CASE-SENSITIVELY (check_preview.py applies no flags). Scope any
# case-insensitive part inline with (?i:...) instead of asking for a blanket flag: a blanket
# re.I on a pattern holding a [A-Z] anchor makes that anchor match lowercase too, so an anchor
# written to pin a proper noun quietly matches any word and the check stops discriminating.
VOICE_MARKER_PATTERNS = [
    r"(?i:\b(hi|hey|tgif),)\s+[A-Z][a-z]+!",         # a greeting line: "Hi, Jane!", NAME stays [A-Z]
    r"(?i:\b(praise|phrasing|beat|angle|hook)\b)",   # no [A-Z] anchor, so loose is fine here
]

# ─────────────────────────────────────────────────────────────────────────────
# 5. SCREENING FILTERS — ship POPULATED. Edit to your deal-breakers; do NOT blank.
#    These drive check_screen_gate.py, which fails a candidate whose write-up MENTIONS
#    a veto term without recording an explicit verdict on it. Silence is a failure.
# ─────────────────────────────────────────────────────────────────────────────
INDUSTRY_VETO = [
    r"\bdefense\b", r"\bdod\b", r"\bwarfighter", r"\bmilitary\b", r"\bweapons?\b",
    r"law[- ]enforcement", r"\bpolice\b", r"\bpolicing\b", r"\bcorrections\b(?!.{0,20}\bfor\b)",
    r"sportsbook", r"\bigaming\b", r"\bcasino\b", r"\bgambling\b", r"\bsports bett",
    r"\bcrypto\b", r"\bweb3\b", r"\bdefi\b", r"\bnft\b",
    r"merchant cash advance", r"\bmca\b", r"factor rate", r"revenue[- ]based financing",
    # ── PREDATORY-LENDING AND DTC-Rx TERMS. Added after a veto list gained REACH — once the
    # RESOLVED employer INDUSTRY text fed this list instead of only the company NAME, the very
    # first batch surfaced two companies that were deal-breakers under rules already held, and
    # that this list had no words for: a "buy-now-pay-later" lender and a "ketamine telehealth"
    # provider. The rules were right; the patterns were narrower than the rules. If your own
    # deal-breakers are written down anywhere in prose, check that this list can actually SAY them.
    r"buy[- ]now[,]?[- ]pay[- ]later", r"\bbnpl\b", r"pay in 4", r"lease[- ]to[- ]own",
    r"rent[- ]to[- ]own", r"\bsubprime\b", r"payday (loan|lend)", r"earned wage access",
    # ⚠️ NARROWED THE SAME DAY IT WAS WRITTEN, and the reason generalises. The first version listed
    # bare `\btelehealth\b` and `\btelemedicine\b`. That is far broader than the actual rule,
    # which is direct-to-consumer PRESCRIPTION marketing, and healthtech generally sits INSIDE a
    # regulated-workflow target lane. A bare telehealth veto would have quietly emptied a whole
    # target lane to catch one company that `\bketamine\b` already catches.
    # ⛔ OVER-BLOCKING IS INVISIBLE: a vetoed row just never appears, and nothing tells you why.
    # Write the narrowest pattern that says your rule, never the broadest one that contains it.
    r"direct[- ]to[- ]consumer (rx|pharmac|prescri|telehealth)",
    r"telehealth[^.]{0,40}\b(prescri|\brx\b|pharmac)", r"\bketamine\b",
    r"\bcompounding pharmac",
]
INDUSTRY_CLEARED = [
    r"industry:?\s*cleared", r"industry cleared", r"not a deal[- ]breaker industry",
    r"picks[- ]and[- ]shovels", r"infra(structure)? not",
]

# Remote: a write-up that names a disqualifying arrangement must also carry a confirming verdict.
REMOTE_DISQUAL = [
    r"\bhybrid\b", r"\brto\b", r"return[- ]to[- ]office", r"relocat", r"onsite required",
    r"in[- ]office", r"\d+\s*days?\s*(a|per)?\s*(week|in office)",
    r"fixed .{0,15}(overlap|timezone|time zone)",
]
REMOTE_CONFIRM = [
    r"fully remote", r"100% remote", r"remote[- ]first", r"permanently remote",
    r"work from anywhere", r"remote \(us", r"us[- ]remote confirmed", r"no hybrid", r"not hybrid",
]

# Politics: only meaningful if political alignment is one of your hard filters. If it is
# not, set both lists to [] — the gate then ignores the topic entirely.
POLITICS_DISQUAL = [r"right[- ]lean", r"conservative[- ]lean", r"founder .{0,20}donat"]
POLITICS_CLEAR = [
    r"apolitical", r"progressive", r"left[- ]lean", r"no political red flag",
    r"politics:?\s*(clean|pass|clear)", r"political screen clean",
]

# Ownership: majority private-equity ownership correlates with margin extraction, leadership
# churn and layoffs. Flagged unless the write-up adjudicates it.
PE_FLAG = [
    r"private equity", r"\bpe[- ]owned", r"\bpe[- ]backed", r"leveraged buyout", r"\blbo\b",
    r"\bbuyout\b", r"portfolio company",
]
PE_CLEARED = [
    r"not pe[- ]owned", r"pe:?\s*(cleared|none|n/a|ok)", r"bootstrapped", r"vc[- ]backed",
    r"venture[- ]backed", r"founder[- ]owned", r"publicly traded", r"pe override",
    r"seed[- ]stage", r"series [a-c]\b",
]

# ─────────────────────────────────────────────────────────────────────────────
# 5b. THE BATCH ENGINE — comp floor + your hot-zone SEGMENTS.
#     Drive screen_sweep.py (the mechanical filter) and sweep_segments.sh (the discovery
#     sweep). Ship POPULATED with generic examples; REPLACE with your own — see docs/segments.md.
# ─────────────────────────────────────────────────────────────────────────────

# Salary floor for the mechanical screen. A posting whose stated max is below this is dropped;
# "not stated" is kept and flagged. Set to YOUR floor. 0 = no comp filtering (keeps everything).
COMP_FLOOR = int(_env("JOBKIT_COMP_FLOOR", "150000"))

# ⭐ Your SEGMENTS — the hot-zone lanes you test (Andy LaCivita: send ~5 per segment, then compare
# reply rates; five labels inside one lane produce no comparison). Each KEY is a segment slug that
# mail-draft.sh --segment validates against; each VALUE is the list of sweep queries for that lane.
# ⚠️ These ship as GENERIC EXAMPLES. Replace both the slugs and the queries with your own lanes —
# something on YOUR verifiable record backs each one (docs/segments.md explains the discipline).
SEGMENTS = {
    "segment-a": [
        "product manager", "senior product manager", "staff product manager",
        "principal product manager", "product owner", "director of product",
    ],
    "segment-b": [
        "ai product manager", "product manager machine learning", "product manager platform",
        "product manager data", "senior product manager ai", "product owner ai",
    ],
    "segment-c": [
        "product manager fintech", "product manager payments", "product manager compliance",
        "product manager healthcare", "senior product manager", "product owner",
    ],
}
SEGMENT_SLUGS = list(SEGMENTS.keys())

# ⭐ INDUSTRY patterns per segment — a DIFFERENT question from SEGMENTS above.
# SEGMENTS holds the job TITLES you search for. This holds the words that say what a COMPANY does,
# and it is what decides whether a contact can plausibly be your boss. `contact_signals.py` reads
# it; the people ranker gates its likely-boss bands on the answer.
#
# Keys should be your segment slugs; values are regex fragments joined with |.
#
# ⚖️ BE CONSERVATIVE, and the asymmetry is not the obvious one. A false positive proposes a
# hire-me ask to someone who cannot grant it. A miss only demotes to "who do you know", which is
# safe to send to anyone. So match on distinctive domain nouns and never on generic business
# words: "payments" is a signal, while "solutions", "technology", "partners", "group" are not.
#
# ⚠️ SHIPS EMPTY ON PURPOSE. With no patterns the read falls back to the sourced employer cache
# and otherwise returns "unknown", which KEEPS the band and flags it. That is the safe default.
# Populate it when you know your lanes.
SEGMENT_INDUSTRY_PATTERNS = {
    # "segment-a": r"payments?|paytech|fintech|billing|invoicing|merchant acquir|checkout",
    # "segment-b": r"applied ai|machine learning|\bllm\b|generative ai|computer vision",
}

# ⭐ OFF-SEGMENT vocabulary — businesses that plainly cannot hire someone into your lanes.
#
# 🔴 THIS EXISTS BECAUSE ABSENCE OF A MATCH IS NOT EVIDENCE OF BEING OFF-SEGMENT, and conflating
# the two shipped a real defect. Most real companies do not carry their industry in their name, so
# a bare "no segment matched" test demoted a Head of Product at a well-known payments company
# exactly as it demoted an artist-management sole trader. The read is TRI-STATE, and only a
# POSITIVE match here demotes anyone:
#     "relevant" — a segment matched          "off" — a business matched THIS list
#     "unknown"  — neither, so keep the band and flag it for a human to verify
#
# ⚠️ Also ships empty. An empty list means nothing is ever demoted, which is the safe direction.
OFF_SEGMENT_PATTERNS = [
    # r"public relations", r"artist manage", r"talent agency", r"life coach",
    # r"real estate", r"realty", r"restaurant", r"catering", r"salon",
    # r"landscap", r"plumbing", r"roofing", r"staffing", r"recruit(?:ing|ment)",
]

# ─────────────────────────────────────────────────────────────────────────────
# 6. COMPANY ALIASES — rebrands and trading names, so dedup does not treat one company
#    as two. Each set is one entity. Add the ones you actually run into.
# ─────────────────────────────────────────────────────────────────────────────
COMPANY_ALIASES = [
    {"timescale", "tigerdata"},     # example: a real public rebrand
]

# Where the rules you tailor live, cited in gate failure messages.
# Names your job-search METHOD goes by. check_preview nudges when a decision picker carries no
# read from the method you adopted — the method's suggestion belongs at option 1, so you choose
# informed by the playbook rather than by whatever the assistant happened to prefer.
# Set to [] to switch the nudge off.
METHOD_TERMS = ["lacivita", "andy"]

# ⛔ THIS PATH MUST MATCH WHERE THE FILE ACTUALLY SHIPS. It said `documents/WORKFLOW-RULES.md` from
# the first release until 2026-08-03, and the installer puts the rulebook at the kit ROOT, so the
# path resolved to nothing in every partner install ever made.
#
# WHY THAT WAS EXPENSIVE AND SILENT: the session-start briefing tells the agent *"Re-read {RULES_DOC}
# from the file at every gate, never from memory."* Reading a missing file raises nothing and returns
# nothing, so the one mechanism built to stop rule drift was a no-op, and it reported no problem
# while being one. `kit_doctor.py` now FAILS on a dangling RULES_DOC so this cannot recur quietly.
# ⚠️ THIS VALUE WAS WRONGLY "FIXED" AND RESTORED TWICE ON 2026-08-03. It is CORRECT as written.
# install.sh seeds documents/WORKFLOW-RULES.md from the root copy at install time, and
# documents/ is git-ignored, so the path being absent in an UNINSTALLED kit is the normal
# pre-install state, NOT a dangling pointer. It was twice changed to "WORKFLOW-RULES.md" by
# someone reading a file listing instead of running the installer. Do not "fix" it again.
RULES_DOC = "documents/WORKFLOW-RULES.md"

# ─────────────────────────────────────────────────────────────────────────────
# 7. DECISION LEDGER — the tamper-evident record of the rulings YOU actually made.
#    LEDGER_PATH is relative to the project dir. LEDGER_KEYFILE must sit OUTSIDE the
#    project so the key is never committed, never synced, and never stored next to the
#    ledger it authenticates. Change it if ~ is not where you want key material.
# ─────────────────────────────────────────────────────────────────────────────
LEDGER_PATH = _env("JOBKIT_LEDGER_PATH", os.path.join("documents", "decision-ledger.jsonl"))
LEDGER_KEYFILE = _env("JOBKIT_LEDGER_KEYFILE", "~/.jobsearch-ledger-key")

# ─────────────────────────────────────────────────────────────────────────────
# 7b. THE BACKFILL WINDOW — how far back backfill_linkedin_sends.py reaches when it
#     pulls LinkedIn messages into the send log, and therefore into the rung ladder.
#
#     ⚠️ THIS IS A JUDGMENT CALL, NOT A DEFAULT TO ACCEPT. A LinkedIn export goes back
#     years, and messages from an EARLIER search were sent to different people, for
#     different roles, under different conditions. Folding them into the ladder moves
#     the reply rate you read every session while telling you nothing about the search
#     you are running now. Set this to the date THIS search began.
#
#     Ships DELIBERATELY BLANK. Blank means the script refuses to run rather than
#     guessing a window on your behalf, because guessing wrong here silently rewrites
#     the numbers you make decisions from.
# ─────────────────────────────────────────────────────────────────────────────
BACKFILL_SINCE = _env("JOBKIT_BACKFILL_SINCE", "")

# ─────────────────────────────────────────────────────────────────────────────
# 8. NETWORK EXCLUSIONS — personal history, ship EMPTY (an empty list is a no-op).
#    Drive session_start.py, parse_network.py, rank_network_companies.py and
#    rank_criteria.py. These are the warm-network equivalent of the HONESTY lists:
#    facts about YOUR past, useless to anyone else, so they ship blank and exclude
#    nobody until you fill them in.
# ─────────────────────────────────────────────────────────────────────────────

# YOUR OWN past employers. Their PEOPLE are your warm network, but the COMPANIES are
# where that network came FROM, not hiring targets — so they are filtered out of the
# daily picks (session_start.py) and the network-sourced company ranking
# (rank_network_companies.py), and their LEADERSHIP tier is dropped from the warm list
# (parse_network.py, rank_criteria.py). [] excludes nobody. Add your employer names,
# e.g. ["acme", "acme corp"]; matched as word-boundary substrings of a company name.
EXCLUDED_EMPLOYERS = []

# Specific NAMED people to always exclude from the warm network (e.g. a founder whose
# leadership you are deliberately routing around). [] excludes nobody. Full names,
# e.g. ["Jane Doe"]; matched as a word-boundary literal against a contact's full name.
EXCLUDED_PEOPLE = []

# The LEADERSHIP tier filtered out of an EXCLUDED_EMPLOYERS company — peers below this
# line STAY in scope, because the exclusion is about leadership harm, not former
# teammates. Ships POPULATED as an example C-suite / VP / Director / Founder band, but
# it is a no-op until EXCLUDED_EMPLOYERS or EXCLUDED_PEOPLE is non-empty (nothing is an
# excluded employer, so no title is ever tested). These are raw regex fragments; edit
# to the title band you want dropped.
EXCLUDED_EMPLOYER_LEADERSHIP_TITLES = [
    r"\bfounder\b", r"\bco-?founder\b", r"\bceo\b", r"\bcto\b", r"\bcoo\b", r"\bcpo\b",
    r"\bchief\b", r"\bvp\b", r"\bvice president\b", r"\bhead of\b", r"\bdirector\b",
    r"\bpresident\b", r"\bpartner\b",
]

# ISO date (YYYY-MM-DD) you began the search. A connection made ON/AFTER this date skews
# toward search networking rather than a real relationship, so parse_network.py flags it
# 🔴 "search-era" and it must not receive a warm-rung ask. "" disables the flag entirely
# (nothing is ever marked search-era) — the neutral default. Also accepts "09 Jun 2023".
SEARCH_START_DATE = ""

# ─────────────────────────────────────────────────────────────────────────────
# 9. NETWORK EXPORT AUTO-DISCOVERY — where parse_network.py looks for a LinkedIn
#    connections export. Home-relative shell globs, so nothing about one machine's
#    layout is baked in. Edit if you keep your export somewhere else.
# ─────────────────────────────────────────────────────────────────────────────

# Home-relative globs for an already-unzipped Connections.csv, newest match wins.
NETWORK_EXPORT_GLOBS = [
    "Downloads/*LinkedInDataExport*/Connections.csv",
    "Desktop/*LinkedInDataExport*/Connections.csv",
    "Downloads/Connections.csv",
]
# Home-relative globs for the export .zip (Connections.csv is read from inside it).
NETWORK_EXPORT_ZIP_GLOBS = [
    "Downloads/*LinkedIn*Export*.zip",
    "Desktop/*LinkedIn*Export*.zip",
]

# ─────────────────────────────────────────────────────────────────────────────
# 10. NAMED-COMPANY VETO — a SCREENING list, ships POPULATED. Do NOT blank it.
#     check_customer_base.py uses this to catch a company whose INDUSTRY is a
#     deal-breaker but whose NAME contains none of the banned WORDS in INDUSTRY_VETO
#     (a defense prime or a crypto exchange rarely writes "defense"/"crypto" in a
#     product-manager posting). An empty veto list does not screen nothing loudly — it
#     silently passes every known-bad name, the exact miss this list exists to catch.
#     It is a curated FLOOR, incomplete by construction; it does not replace the
#     per-company screen. Each entry is a word-boundary regex on the company NAME.
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ EXAMPLE public classifications — edit to YOUR employers, and keep it consistent
#    with INDUSTRY_VETO above (if you do not veto gambling, drop the gambling names).
# NOT_A_COMPANY — pool rows that are a PAGE TITLE or ATS boilerplate rather than an employer.
# A scraper reads whatever the careers page put in the heading, so a pool accumulates rows like
# "Company Overview" and "Job Opportunities" that no screen can ever clear and no veto can ever
# catch. They are not companies, so they must be dropped as ARTIFACTS, not screened as employers.
NOT_A_COMPANY = [
    r"^company overview$", r"^your job$", r"^opportunities\b", r"\bcareers? (site|page)$",
    r"\bcandidate experience page$", r"\bjob opportunities$", r"\bcareer site$",
    r"\bcorporate openings\b", r"\btalent acquisition team$", r"\bglobal career site$",
    r"^company$", r"^overview$", r"^jobs?$",
]

VETO_EMPLOYERS = [
    r"\bcoinbase\b", r"\bkraken\b", r"\bbinance\b",                       # crypto exchanges
    r"\bpalantir\b", r"\banduril\b", r"\blockheed\b", r"\braytheon\b",    # defense primes
    r"\bnorthrop\b", r"\bgeneral dynamics\b", r"\bbooz allen\b", r"\bleidos\b",
    r"\baxon\b", r"\bflock safety\b", r"\bcellebrite\b",                  # law-enforcement vendors
    r"\bdraftkings\b", r"\bfanduel\b",                                    # gambling
]

# ─────────────────────────────────────────────────────────────────────────────
# 11. SCORING WEIGHTS — the tunable knobs that turn recorded signals into a rank.
#     These are the ONE thing a different user re-tunes, so they live here instead of
#     inside the ranker code. Drive rank_network_companies.py (warm-path scoring) and
#     rank_criteria.py (company + people ranking). Ship with working defaults.
# ─────────────────────────────────────────────────────────────────────────────

# How a warm PATH into a company is scored (rank_network_companies.py). A product
# contact can hire or refer INTO product; a senior contact can create a seat; a body you
# merely know is worth least. Retune the emphasis without editing the ranker.
NETWORK_SCORE_WEIGHTS = {"product": 3, "senior": 2, "person": 1}

# The employer-criteria matrix, weighted (rank_criteria.py). Leadership stability is the
# top weight because a bad-leadership exit is the most expensive miss. Reweight here.
CRITERIA_WEIGHTS = {
    "wlb": 10.0,                   # work-life-balance rating
    "retention": 10.0,             # %recommend / retention
    "leadership_stability": 10.0,  # leadership/culture stability — the top-weighted criterion
    "calm_pace": 8.0,              # calm / mature / bootstrapped pace
    "boss_reachable": 3.0,         # readiness tiebreak: a boss with an email on file
    "sourced_praise": 2.0,         # readiness tiebreak: a sourced praise link
}
WLB_FLOOR = 3.0             # WLB rating below this = veto-level drop (row excluded)
WLB_RANGE = 2.0             # full WLB weight is reached at WLB_FLOOR + WLB_RANGE
LEADERSHIP_CLEAN_TIER = 3   # culture-confidence tier at/above which leadership scores full weight
LEADERSHIP_CAVEAT_FRACTION = 0.3    # turmoil/reorg flagged → this fraction of the leadership weight
LEADERSHIP_UNPROVEN_FRACTION = 0.5  # unproven screen → this fraction of the leadership weight
# Per-tier discount on the culture-derived score (keys are the confidence tiers 0-4).
CONFIDENCE_MULTIPLIER = {4: 1.0, 3: 0.9, 2: 0.75, 1: 0.6, 0: 0.5}

# The people pool ("who can help first", rank_criteria.py --pool people). Base score by
# category: a product LEADER who can hire you outranks a senior exec, an IC peer, a
# connector who routes you. Retune the emphasis here.
PERSON_WEIGHTS = {"product-leader": 40, "senior-exec": 33, "product-ic": 25,
                  "connector": 15, "other": 5}
PERSON_EMAIL_BONUS = 5      # +score when a contact is reachable NOW (email on file)
PERSON_REENTRY_BONUS = 8    # +score when their company is already in your pipeline (warm re-entry)

# ─────────────────────────────────────────────────────────────────────────────
# 12. CRITERIA MATRIX DOC — the doc your employer-criteria matrix lives in, cited in
#     rank_criteria.py's printed headers. Change it if your file lives elsewhere.
# ─────────────────────────────────────────────────────────────────────────────
CRITERIA_MATRIX_DOC = "documents/employer-criteria-matrix.md"


def _as_shell():
    """Emit shell assignments so bash scripts can read the same config."""
    def q(s):
        return "'" + str(s).replace("'", "'\\''") + "'"
    lines = [
        f"KIT_OWNER_NAME={q(OWNER_NAME)}",
        f"KIT_OWNER_FIRST={q(OWNER_FIRST)}",
        f"KIT_OWNER_SITE={q(OWNER_SITE)}",
        f"KIT_OWNER_EMAIL={q(OWNER_EMAIL)}",
        f"KIT_RESUME_EXAMPLE={q(RESUME_FILENAME_EXAMPLE)}",
        f"KIT_RULES_DOC={q(RULES_DOC)}",
        f"KIT_COMP_FLOOR={q(COMP_FLOOR)}",
        # space-separated segment slugs, for the mail-draft.sh --segment gate
        f"KIT_SEGMENT_SLUGS={q(' '.join(SEGMENT_SLUGS))}",
        # newline-separated glob patterns
        "KIT_RESUME_PATTERNS=" + q("\n".join(RESUME_FILENAME_PATTERNS)),
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--sh":
        print(_as_shell())
    elif len(sys.argv) > 1 and sys.argv[1] == "--segments":
        print("\n".join(SEGMENT_SLUGS))
    elif len(sys.argv) > 2 and sys.argv[1] == "--segment-queries":
        print("\n".join(SEGMENTS.get(sys.argv[2], [])))
    else:
        print(f"owner:   {OWNER_NAME} <{OWNER_EMAIL}>  {OWNER_SITE_URL}")
        print(f"résumé:  {RESUME_FILENAME_EXAMPLE}")
        print(f"honesty: {len(RETIRED)} retired literal(s), {len(RETIRED_PATTERNS)} pattern(s)")
        print(f"screens: {len(INDUSTRY_VETO)} industry veto term(s), {len(PE_FLAG)} ownership flag(s)")
        if not RETIRED and not RETIRED_PATTERNS:
            print("\n⚠️  RETIRED lists are empty — the honesty gate is a no-op until you fill them.")
