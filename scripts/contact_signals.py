#!/usr/bin/env python3
"""Contact signals a people ranker is otherwise blind to: SEGMENT and ENDORSEMENTS.

A ranker that scores people by TITLE alone will hand you a "likely boss" who could never hire
you: the owner of a landscaping business and a Head of Product at a payments company both read
as "founder/CEO" or "product leader" from the title column. What separates them is what the
COMPANY does, and that is not a field LinkedIn exports.

WHAT THIS FILE COVERS, AND WHAT NO EXPORT CAN GIVE YOU. A LinkedIn archive contains ~51 files and
only 3 are usable here (Connections, messages, Invitations):

  · ROLE          — in Connections.csv (`Position`). The ranker categorizes it; what was missing
                    was GATING the likely-boss bands on segment, which `is_reachable_boss()`
                    supplies below.
  · INDUSTRY      — NOT a column anywhere. Derived here from company + title text against your
                    own closed vocabulary in kit_config, and from the sourced employer cache.
  · PRIOR ROLES   — ❌ not exported. `Positions.csv` is YOUR history, not your contacts'.
  · ARTICLES      — ❌ not exported. `Comments`/`Reactions` are yours, storing bare links.
  · VOLUNTEER     — ❌ not exported. Those files describe you.

LinkedIn does not export other people's profiles. The last three need per-profile enrichment
through a licensed data source rather than a crawl: scraping hundreds of profiles risks the
account, and the kit's standing rule is navigate-only. They are deliberately absent here rather
than faked.

⭐ THE SIGNAL MOST PIPELINES MISS: `Endorsement_Received_Info.csv`. Someone who endorsed you spent
social capital on you unprompted. Compare what a ranker usually trusts instead: connect date, and
message depth, which can score a contact "know-well" off six messages YOU sent and one reply. An
endorsement is a signal THEY generated, which is rarer and harder to fake than anything on your
own side of the ledger.

⚠️ Read `endorsement_bonus` before trusting it. Endorsements arrive in rituals, and the guard
against that is in the code.
"""
import csv
import glob
import io
import json
import os
import re
import sys
import zipfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit_config  # noqa: E402

REPO = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def norm(name):
    """The repo-wide contact key. MUST match rank_criteria's `re.sub(r"[^a-z0-9]", "", ...)`
    exactly — a second spelling silently splits every join that uses it."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# ── SEGMENT CLASSIFICATION ──────────────────────────────────────────────────────────────────
# YOUR lanes, from kit_config.SEGMENT_INDUSTRY_PATTERNS. This file is the READER, never a second
# source of truth: add a segment in kit_config and it appears here.
#
# ⚖️ CONSERVATIVE ON PURPOSE, and kit_config explains the asymmetry. A false positive proposes a
# hire-me ask to someone who cannot grant it; a miss only demotes to "who do you know", which is
# safe to send to anyone.
#
# ⛔ FAIL LOUDLY, NEVER TO A BLANK LIST. A missing kit_config attribute once collapsed a tuple
# import elsewhere in this kit and the `except` blanked every veto list to `[]`, so the screen
# passed everything while reporting clean. `getattr` with an explicit default is the fix: an
# unconfigured lane list is a legitimate state (it degrades to the employer cache and otherwise
# returns "unknown", which KEEPS the band), but a BROKEN pattern must raise rather than vanish.
def _compile_segments():
    raw = getattr(kit_config, "SEGMENT_INDUSTRY_PATTERNS", None)
    if raw is None:
        return ()
    out = []
    for slug, pattern in raw.items():
        if not pattern:
            continue
        # No try/except: a malformed regex is a configuration ERROR and must be seen at import,
        # not swallowed into a silently empty vocabulary.
        out.append((slug, re.compile(r"\b(?:" + pattern + r")\b", re.I)))
    return tuple(out)


_SEGMENT_PATTERNS = _compile_segments()


def segment_for(company="", title="", extra=""):
    """(slug, matched_text) for the first segment this contact's text supports, else (None, None).

    Reads company AND title: a "VP Product, Payments" at a generically named holding company is
    segment-relevant, and the title is where that shows. `extra` lets a caller pass a board note
    or headline without this function needing to know where it came from.
    """
    blob = " ".join(x for x in (company, title, extra) if x)
    if not blob.strip():
        return None, None
    for slug, pat in _SEGMENT_PATTERNS:
        m = pat.search(blob)
        if m:
            return slug, m.group(0)
    return None, None


# ── KNOWN OFF-SEGMENT, from kit_config.OFF_SEGMENT_PATTERNS ─────────────────────────────────
# Needed because ABSENCE OF A SEGMENT MATCH IS NOT EVIDENCE OF BEING OFF-SEGMENT, and the first
# version of this reader conflated the two.
#
# 🔴 THE DEFECT, worth keeping in full because it is easy to reintroduce. `segment_for` matches
# domain nouns in the company/title text, and real companies mostly do not carry their industry
# in their name: SomeCo, Otherco, Thirdco, Fourthco all return None. So a single `slug is None` test
# demoted a Head of Product at a major payments company exactly as it demoted an artist-management
# sole trader. A measurement that looked like "almost nobody is segment-relevant" was really
# measuring how rare SELF-DESCRIBING COMPANY NAMES are.
#
# That also broke the asymmetry argument for being aggressive. A miss costing "only a demotion" is
# true for ONE contact and false for the BOARD: when most real targets miss, the likely-boss band
# empties out and the ranker has nobody good left to show.
#
# So the read is TRI-STATE, and only POSITIVE evidence of an off-segment business demotes:
#     "relevant"  — a segment matched
#     "off"       — a business from YOUR off-segment list matched HERE
#     "unknown"   — neither; keep the band and flag it for a human to verify
#
# An empty list is safe: nothing is ever demoted, and every band is kept and flagged.
_OFF_SEGMENT_SRC = [p for p in getattr(kit_config, "OFF_SEGMENT_PATTERNS", []) or [] if p]
_OFF_SEGMENT = (re.compile(r"\b(?:" + "|".join(_OFF_SEGMENT_SRC) + r")\b", re.I)
                if _OFF_SEGMENT_SRC else None)


# ── THE EMPLOYER CACHE — the only thing that actually solves this ───────────────────────────
# Name matching answers "does this company SAY what it does", which is a different question from
# "what does this company DO". Measured on the fresh pool of 2026-07-30: 291 distinct employers,
# **282 of them unknown** from the name alone. Two misses that make the point: `Stripe` reads
# unknown (payments), and `PaymentVerse` reads unknown too, because `\bpayments?\b` needs a word
# boundary that "PaymentVerse" does not provide. Tightening the regex trades one failure for
# another; only real company data settles it.
#
# So: a dated, sourced, append-only cache keyed on the employer name, newest row wins. Populated
# out-of-band (Lusha + public web) rather than guessed here, and consulted BEFORE the patterns so
# a resolved employer always beats a regex. An employer absent from the cache degrades to the
# name read, which is exactly today's behaviour — so this is additive and cannot regress.
EMPLOYER_CACHE = os.path.join(REPO, "documents", "state", "employer-segments.jsonl")
# The closed vocabulary the ingest validates against: YOUR segment slugs, plus "off-segment".
# Derived from kit_config so adding a lane in one place is enough.
_VALID_SEGMENTS = set(getattr(kit_config, "SEGMENT_SLUGS", []) or []) | {"off-segment"}

# ── NOT-FOUND IS A FINDING, NOT AN ABSENCE ──────────────────────────────────────────────────
# Until today a resolver that searched the public web and could not place a company had nowhere
# to write that down: `cmd_ingest` only accepted a row carrying a real segment, so the verdict
# was dropped and the employer reappeared in the next worklist. At scoring time "never looked
# at" and "four agents looked and found nothing" were therefore the SAME state, and the ranker
# gave both the full likely-boss band.
#
# The receipt is in rank_criteria's UNVERIFIED SEGMENT note: the top seven of the board were all
# on the resolvers' not_found list, and "the design was rewarding obscurity". The 0.65 multiplier
# written that evening reduced the magnitude and did not change the ordering, so Rely Health Care
# Services was still #1 five days later.
#
# ⚠️ `not-found` IS NOT A SIXTH SEGMENT. It loads into the cache so the evidence layer can see
# it, and `segment_read` deliberately falls THROUGH it to the name patterns, so the tri-state
# read and the only-`off`-demotes rule are untouched. It moves the SORT, never the band.
_NOT_FOUND = "not-found"
_LOADABLE_SEGMENTS = _VALID_SEGMENTS | {_NOT_FOUND}

# Employer evidence tiers — the people ranker's primary sort key, mirroring the company ranker's
# TIER. Ordering claim: tier 0 sits BELOW tier 1 on purpose. A company no search can place is
# weak evidence of a product org that hires product managers; a company nobody has looked at yet
# is genuine absence of information. Collapsing the two is what let obscurity win.
EV_RESOLVED = 3        # cache row, sourced, confidence not 'low'
EV_LOW_CONF = 2        # cache row, but the resolver flagged it low confidence
EV_UNLOOKED = 1        # no cache row (a bare name-regex hit counts here: an unsourced band is a guess)
EV_NOT_FOUND = 0       # searched, and could not be placed
EV_LABEL = {EV_RESOLVED: "🔬 resolved", EV_LOW_CONF: "🟡 low confidence",
            EV_UNLOOKED: "❓ not yet resolved", EV_NOT_FOUND: "⚪ searched, not placeable"}


def _employer_key(name):
    """Match on the distinctive part: drop the legal suffix and punctuation so
    'LOMAC & Associates LLC' and 'LOMAC and Associates, L.L.C.' are one key."""
    s = (name or "").lower()
    s = re.sub(r"\b(inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|plc|"
               r"sa|s\.a|nv|bv|ag|pty|pte|llp|lp)\b\.?", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def load_employer_cache(path=None):
    """{employer_key: row}. Newest row wins. Returns {} when the cache does not exist yet."""
    path = path or EMPLOYER_CACHE
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue          # a corrupt line must not blind the whole cache
                emp = row.get("employer")
                seg = row.get("segment")
                if not emp or seg not in _LOADABLE_SEGMENTS:
                    continue          # fail closed on an unknown slug rather than inventing a band
                out[_employer_key(emp)] = row
    except OSError:
        return {}
    return out


_EMPLOYER_CACHE = None


def segment_read(company="", title="", extra="", cache=None):
    """('relevant'|'off'|'unknown', detail) — the tri-state segment read.

    Order: the sourced employer cache, then the name patterns. Only 'off' may demote a likely-boss
    band. 'unknown' keeps it, because a company that does not announce its industry in its name is
    the normal case, not a disqualification.
    """
    global _EMPLOYER_CACHE
    if cache is None:
        if _EMPLOYER_CACHE is None:
            _EMPLOYER_CACHE = load_employer_cache()
        cache = _EMPLOYER_CACHE
    row = cache.get(_employer_key(company)) if company else None
    # ⚠️ FALL THROUGH a not-found row, do not read a band off it. The tri-state contract is that
    # only a POSITIVE off-segment match demotes; a not-found employer is still `unknown` here and
    # still KEEPS its band. Its cost is paid in the evidence tier (employer_evidence), which sorts,
    # rather than in the segment read, which rebands. Reading it as a band here would demote every
    # unplaceable employer to connector and silently change the ASK.
    if row is not None and row.get("segment") == _NOT_FOUND:
        row = None
    if row:
        seg = row["segment"]
        src = row.get("source") or "cache"
        if seg == "off-segment":
            return "off", f"{row.get('industry') or 'off-segment'} · {src}"
        return "relevant", f"{seg} · {row.get('industry') or 'resolved'} · {src}"
    slug, hit = segment_for(company, title, extra)
    if slug:
        return "relevant", f"{slug} (matched \"{hit}\")"
    blob = " ".join(x for x in (company, title, extra) if x)
    m = _OFF_SEGMENT.search(blob) if _OFF_SEGMENT else None
    if m:
        return "off", m.group(0).strip()
    return "unknown", None


def employer_evidence(company="", cache=None):
    """(tier, detail) — how well do we actually KNOW this employer?

    Separate from `segment_read` on purpose. segment_read answers "is this company in one of the
    five segments", and its answer may REBAND a contact (only on a positive `off`). This answers
    "how much do we know", and its answer only ever SORTS. Keeping them apart is what lets the
    ranker demote an unknowable employer without changing the ask you make.

    ⚠️ `confidence` and `source` have been written on every cache row since 2026-07-30 and were
    read by nobody, so a band guessed off a LinkedIn headline scored identically to one read off
    the company's own about page. This is the reader.
    """
    global _EMPLOYER_CACHE
    if cache is None:
        if _EMPLOYER_CACHE is None:
            _EMPLOYER_CACHE = load_employer_cache()
        cache = _EMPLOYER_CACHE
    row = cache.get(_employer_key(company)) if company else None
    if not row:
        # No row at all. A name-regex hit does NOT promote: `resolve_employers` already refuses an
        # unsourced band because "an unsourced band is a guess", and a regex is exactly that.
        return EV_UNLOOKED, None
    if row.get("segment") == _NOT_FOUND:
        return EV_NOT_FOUND, (row.get("source") or "searched")
    src = (row.get("source") or "").strip()
    conf = (row.get("confidence") or "").strip().lower()
    if not src:
        return EV_UNLOOKED, None      # a row without a source is not evidence
    if conf == "low":
        return EV_LOW_CONF, src
    return EV_RESOLVED, src


def is_reachable_boss(company="", title="", extra=""):
    """Can this person plausibly MANAGE the role you want?

    The likely-boss predicate has always been two-place — a boss TITLE at a company where that
    title would own the role — but the ranker only ever tested the title half. So an owner of any
    business at all entered the founder-exec band worth 45 base points, and on 2026-07-30 nine
    contacts landed inside 4.2 points of each other: PR, disability advocacy, coaching,
    consulting, a content studio, a founders' community. None could hire a product manager into
    payments or applied AI, and the board was recommending all of them as bosses.

    A person at an off-segment company is not a WORSE contact — they are a DIFFERENT contact,
    reachable at rung 7 ("do you have relationships at [targets]?"). This function decides which
    of those two a contact is; it never drops anyone. Unknown counts as reachable: see segment_read.
    """
    return segment_read(company, title, extra)[0] != "off"


# ── ENDORSEMENTS RECEIVED ───────────────────────────────────────────────────────────────────
_ENDORSE_FILE = "Endorsement_Received_Info.csv"
_EXPORT_NAME_DATE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")


def _export_date(path):
    """Date from the export filename, else mtime. Same rule as parse_network.export_date_from_name:
    filename beats mtime, because an extracted CSV inherits LinkedIn's own archive timestamp and a
    `touch` on a 2025 export would otherwise beat a 2026 one."""
    m = _EXPORT_NAME_DATE.search(os.path.basename(path))
    if m:
        mm, dd, yyyy = (int(x) for x in m.groups())
        try:
            return date(yyyy, mm, dd)
        except ValueError:
            pass
    try:
        return date.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return date.min


def _read_endorsement_csv():
    """Raw text of the newest Endorsement_Received_Info.csv, from a loose dir or inside a .zip."""
    home = os.path.expanduser("~")
    cands = []
    for pat in (f"Downloads/*LinkedInDataExport*/{_ENDORSE_FILE}",
                f"Desktop/*LinkedInDataExport*/{_ENDORSE_FILE}",
                f"Downloads/{_ENDORSE_FILE}"):
        cands += [(_export_date(p), p, None) for p in glob.glob(os.path.join(home, pat))]
    for pat in ("Downloads/*LinkedIn*Export*.zip*", "Desktop/*LinkedIn*Export*.zip*"):
        for z in glob.glob(os.path.join(home, pat)):
            cands.append((_export_date(z), z, "zip"))
    if not cands:
        return None, None
    cands.sort(key=lambda t: t[0], reverse=True)
    _, path, kind = cands[0]
    try:
        if kind == "zip":
            with zipfile.ZipFile(path) as zf:
                inner = [n for n in zf.namelist() if n.endswith(_ENDORSE_FILE)]
                if not inner:
                    return None, None
                return zf.read(inner[0]).decode("utf-8-sig", "ignore"), path
        with open(path, encoding="utf-8-sig", errors="ignore") as fh:
            return fh.read(), path
    except (OSError, zipfile.BadZipFile, KeyError):
        return None, None


def load_endorsements():
    """{contact_key: {"n": count, "skills": [...], "last": "YYYY-MM-DD", "name": display}}.

    Empty dict when no export is reachable — every caller must degrade to previous behavior
    rather than fail, so a partner install with no archive still ranks.
    """
    text, src = _read_endorsement_csv()
    if not text:
        return {}, None
    out = {}
    try:
        for row in csv.DictReader(io.StringIO(text)):
            if (row.get("Endorsement Status") or "").strip().upper() != "ACCEPTED":
                continue
            first = (row.get("Endorser First Name") or "").strip()
            last = (row.get("Endorser Last Name") or "").strip()
            full = f"{first} {last}".strip()
            key = norm(full)
            if not key:
                continue
            rec = out.setdefault(key, {"n": 0, "skills": [], "last": "", "name": full})
            rec["n"] += 1
            skill = (row.get("Skill Name") or "").strip()
            if skill and skill not in rec["skills"]:
                rec["skills"].append(skill)
            d = (row.get("Endorsement Date") or "").strip()[:10].replace("/", "-")
            if d > rec["last"]:
                rec["last"] = d
    except csv.Error:
        return {}, src
    return out, src


# ⚖️ BINARY, NOT SCALED BY COUNT — and the first draft of this got it wrong, so the reason is
# recorded rather than the conclusion alone.
#
# The obvious design is more endorsements = more capital spent, so scale the bonus by count. The
# live data kills it: **600 accepted rows are 22 distinct people, and 21 of those 22 did all of
# their endorsing on a SINGLE DAY.** The top three sit at 52 endorsements each. That is one person
# working down a skills list in one sitting — one act, not 52. A count-scaled bonus would have
# ranked the network by who clicked most patiently, and it would have looked like evidence.
#
# What survives is PRESENCE. 22 of ~710 contacts, about 3%, ever endorsed him at all, and the
# rarity is what makes it selective. So: one flat bonus for having done it, with recency as the
# only modifier, because a 2019 endorsement is a weaker claim on the relationship than a 2025 one.
#
# Still TYPED rather than learned, and that is a stated debt. The kit's rule is that weights get
# LEARNED from send outcomes, but the send log carries no endorsement field, so there is nothing
# to join against yet. Replace with a learned ratio once enough sends to endorsers have landed.
ENDORSEMENT_BONUS = 4.0        # they endorsed you at all: rare, and they initiated it
ENDORSEMENT_STALE_BONUS = 2.0  # same act, but years cold
ENDORSEMENT_STALE_YEARS = 3


# 🔴 SECOND CORRECTION, AND IT NEARLY SHIPPED. After the count-scaling fix above, the term still
# measured the wrong thing. Checked against connect dates from Connections.csv on the reference
# network: **19 of 22 endorsers (86%) endorsed on the SAME DAY they connected**, a gap of zero.
#
# That is the connect-day endorsement ritual, a networking habit people perform on any new
# contact, rather than capital spent on YOU. One case looked exactly like engagement: an
# endorsement stamped the same day as a connection request that opened with a pitch, followed by
# two more pitches. The ranker presented that as evidence the person would help.
#
# So a connect-day endorsement scores ZERO. What survives is the endorsement that came LATER, from
# someone who had already known you a while and chose to vouch anyway. On the reference network
# that was 3 of 22 people, and tiny is the point: the value of the signal is that it is hard to
# earn.
ENDORSEMENT_RITUAL_DAYS = 3   # endorsed within N days of connecting == the ritual, not a signal


def endorsement_bonus(rec, today=None, connected_on=None):
    """(points, reason) for an endorsement record, or (0.0, None).

    Keyed on WHETHER they endorsed, never on how many skills they clicked, and ONLY when the
    endorsement is separated from the connect date. See both correction notes above.
    """
    if not rec or not rec.get("n"):
        return 0.0, None
    today = today or date.today()
    last = (rec.get("last") or "").strip()
    if connected_on and last:
        m0 = re.match(r"(\d{4})-(\d{2})-(\d{2})", last)
        if m0:
            try:
                gap = (date(*(int(x) for x in m0.groups())) - connected_on).days
            except ValueError:
                gap = None
            if gap is not None and abs(gap) <= ENDORSEMENT_RITUAL_DAYS:
                return 0.0, None   # connect-day ritual — carries no information
    stale = False
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", last)
    if m:
        try:
            stale = (today - date(*(int(x) for x in m.groups()))).days > 365 * ENDORSEMENT_STALE_YEARS
        except ValueError:
            pass
    pts = ENDORSEMENT_STALE_BONUS if stale else ENDORSEMENT_BONUS
    skills = ", ".join(rec["skills"][:3])
    tail = f" for {skills}" if skills else ""
    when = f", {last}" if last else ""
    aged = " — years cold" if stale else ""
    return pts, f"🤝 endorsed him{tail}{when}{aged} (+{pts:g})"


def main():
    """Audit view: what these signals see across the current network snapshot."""
    end, src = load_endorsements()
    print("── contact signals ─────────────────────────────────────────────────────────")
    print(f"  endorsements: {len(end)} distinct endorsers"
          + (f"  ·  source: {os.path.basename(src)}" if src else "  ·  NO EXPORT FOUND"))
    if end:
        top = sorted(end.values(), key=lambda r: -r["n"])[:10]
        print("\n  most-endorsing contacts (the unused reciprocity signal):")
        for r in top:
            print(f"    {r['n']:>3}×  {r['name']:<32} {', '.join(r['skills'][:3])[:60]}")
    net = os.path.join(REPO, "documents", "warm-network.md")
    if os.path.exists(net):
        hits, total = {}, 0
        with open(net, encoding="utf-8") as fh:
            for line in fh:
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 6 or cells[0] in ("#", "---") or not cells[0].isdigit():
                    continue
                total += 1
                slug, _ = segment_for(cells[3], cells[2])
                if slug:
                    hits[slug] = hits.get(slug, 0) + 1
        print(f"\n  segment relevance across {total} network rows:")
        for slug in ("payments", "applied-ai", "ai-enablement", "regulated-workflow", "govtech"):
            print(f"    {slug:<20} {hits.get(slug, 0):>4}")
        print(f"    {'(no segment)':<20} {total - sum(hits.values()):>4}")


if __name__ == "__main__":
    main()


# The contact-role cache: a human-verified snapshot of who currently holds which title. A title
# from an export goes stale the moment someone changes jobs, so a verified row is the only one
# worth trusting without a fresh check.
ROLE_CACHE = os.path.join(REPO, "documents", "state", "contact-roles.jsonl")
_ROLE_CACHE = None

# Credential suffixes people append to a surname. Stripped before matching, so `Jane Doe, MBA`
# and `Jane Doe` resolve to one person rather than two.
_CREDENTIALS = re.compile(
    r"\b(mba|phd|ph\.?d|md|rn|bsn|cpa|pmp|cissp|csm|cspo|edld|esq|jd|ma|ms|msc|bs|ba|"
    r"shrm-?cp|shrm-?scp|pe|dvm|do)\b\.?", re.I)


def _contact_key(name):
    return norm(_CREDENTIALS.sub(" ", name or ""))


def load_role_cache(path=None):
    """{contact_key: row}. Newest row wins. {} when the store does not exist yet."""
    path = path or ROLE_CACHE
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue          # a corrupt line must not blind the whole store
                who = row.get("name")
                if not who or not row.get("verified_on"):
                    continue          # an undated verification is not a verification
                out[_contact_key(who)] = row
    except OSError:
        return {}
    return out


_ROLE_CACHE = None


# ⚠️ CREDENTIAL SUFFIXES BREAK THE JOIN, caught the hour this shipped. The ranker reads
# "Ben Cornfield, MBA" from warm-network.md while the store was keyed "Ben Cornfield", so norm()
# produced `bencornfieldmba` against `bencornfield` and the verification silently did not apply,
# printing "unverified" for the very contact the store existed to flag. Strip the trailing
# credential before keying, both sides.
_CREDENTIALS = re.compile(
    r"\b(mba|phd|ph\.?d|md|rn|bsn|cpa|pmp|cissp|csm|cspo|edld|esq|jd|ma|ms|msc|bs|ba|"
    r"shrm-?cp|shrm-?scp|pe|dvm|do)\b\.?", re.I)


def verified_role(name, cache=None):
    """The row for a contact whose CURRENT role was checked by a human, or None."""
    global _ROLE_CACHE
    if cache is None:
        if _ROLE_CACHE is None:
            _ROLE_CACHE = load_role_cache()
        cache = _ROLE_CACHE
    if not name:
        return None
    return cache.get(norm(name)) or cache.get(_contact_key(name))


def role_tell(name, known_since="", cache=None):
    """A one-line note about how much to trust this contact's title, or ''.

    Three states, and the middle one is the whole point:
      · verified   the role was opened and checked on a date, so say when
      · LEFT       the check found they had already moved on
      · unverified the title is an export snapshot from the connect date, never confirmed
    """
    row = verified_role(name, cache)
    if row:
        if row.get("still_there") is False:
            return (f"⛔ ROLE ENDED — verified {row['verified_on']}: "
                    f"{row.get('note') or 'no longer in the stored role'}")
        return f"✅ role verified {row['verified_on']}" + (
            f" ({row['title']} @ {row['company']})" if row.get("title") else "")
    m = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", known_since or "")
    if m:
        yrs = (date.today() - date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days / 365.25
        if yrs >= 1:
            return f"⚠️ title unverified ({yrs:.0f}y old export snapshot)"
    return ""
