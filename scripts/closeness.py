#!/usr/bin/env python3
"""closeness.py — the one place that turns a stated relationship into a sanctioned ASK.

WHY THIS EXISTS. A pipeline that ranks PEOPLE by title and company will, sooner or later, do one
of two things, and both are the same defect:

    a stranger  scored as warm      ->  an introduction request to someone you never spoke to
    a friend    scored by title     ->  a hire-me ask to a social acquaintance

THE ASK WAS DERIVED FROM THE PERSON'S CATEGORY, NEVER FROM THE RELATIONSHIP. The boss-hunt
ladder's warm rungs (5/6/7) require a real relationship; rungs 1/2 require none. Only YOU can say
which one exists, and this module is where that answer, once recorded in
`documents/contact-closeness.json`, becomes the rung, the ask language, and the score bonus.

WHY THIS IS A MODULE AND NOT A FUNCTION IN ONE CALLER. The ranker RECOMMENDS a rung and
`check_preview.py` REFUSES one. If those two read different tables they will disagree, and the one
that drifts is the one nobody re-reads. One table, two consumers.

PROVENANCE IS PART OF THE ANSWER, NOT METADATA. A strong tier levelled from message volume is not
the same as one you stated: an event organiser can rack up a two-way thread without ever becoming
a relationship, so an INFERRED strong tier scores thin and carries a confirm flag until you
confirm the person. It fails the other way too: an old friendship can predate your message archive
entirely, which is why an ABSENT row never silently means cold — it means nobody asked you yet.

The store is created and filled by `level_contacts.py` (the /level-network interview). This module
only ever READS it.

Stdlib only. The kit promises "Standard library only, no install step, no network."
"""
from __future__ import annotations

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
STORE = os.path.join(REPO, "documents", "contact-closeness.json")

# Score bonuses, used by the ranker when it is wired to this module. The shipped defaults were
# ratified on the upstream repo's live pool: big enough that people you know sort ahead of
# strangers with similar titles, small enough that a strong stranger boss still surfaces within a
# few picks (a "work the knowns first" ordering was explicitly rejected there). Override per name
# in kit_config.py — each knob gets its OWN try/except, because folding new names into one shared
# import makes the whole import fail on an older kit_config and fall back to defaults in silence.
try:
    from kit_config import CLOSENESS_STRONG
except Exception:
    CLOSENESS_STRONG = 6.0
try:
    from kit_config import CLOSENESS_THIN
except Exception:
    CLOSENESS_THIN = 3.0

# A strong tier that YOU stated is worth the strong bonus. One inferred from message traffic is
# not, until you confirm the person (volume is not intimacy — see the module docstring).
INFERRED_SOURCES = ("inferred-from-messages",)

# The value a levelling answer writes, so the machine pass can never overwrite a human one.
# ⚠️ WRITE-ONLY BY CONTRACT. Nothing anywhere may compare against this value. The upstream twin of
# this module spells it differently, and any stated spelling must count as stated — so overwrite
# protection keys on the NEGATIVE space instead, membership in INFERRED_SOURCES: "a human said
# this" is anything the machine pass did not write, however it is spelled. If a future reader ever
# needs "was this stated", write `source not in INFERRED_SOURCES`, never `source == STATED_SOURCE`.
STATED_SOURCE = "stated-by-owner"

# ── ROWS THE STORE ITSELF DOUBTS ────────────────────────────────────────────────────────────────
# Two markers, both PROSE rather than fields, ON PURPOSE — one detector serves every store this
# module ever reads, and no schema migration is needed to add a doubt:
#
#   `⚠️CONTRADICTS`  a key whose text says a two-way thread exists against a never-spoke tag —
#                    written when a NEWER export contradicts a recorded answer.
#   AMBIGUOUS        inside the `evidence` TEXT: a brief exchange (2-5 msgs both ways) that could
#                    be a relationship or could be connect-and-pleasantries.
#
# ⛔ THE ASK SHAPE DOES NOT MOVE FOR THESE. They stay cold: a two-way thread is no more proof of a
# relationship than volume is, and granting a warm ask on a marker that says "re-check" would be
# inventing the exact certainty the marker denies. Cold is the floor and the floor is where
# uncertainty belongs. What they DO get is a flag — doubted rows are the levelling queue, and one
# recorded answer outranks the guess forever.
_AMBIGUOUS_RE = re.compile(r"ambiguous", re.I)


# ── THREAD DEPTH — A SECOND AXIS, NEVER A ROUTE TO A TIER ──────────────────────────────────────
# Closeness says how STRONG a tie is. Depth says whether it is LIVE. They are independent: a
# decades-old friendship can be stored `know-not-close` because the message-depth inference saw
# only a handshake-length thread — strong tie, dead thread. Collapsing the two axes gets both
# wrong, so depth informs the ASK and the SCORE and never sets, reads, or implies a `closeness`
# value; the sanctioned rung keeps keying on the stated tier alone, so thread evidence can NARROW
# an ask and never WIDEN one.
#
# The signal is whether they ever wrote back, and how long ago.
#   `live`    — they wrote back within DEPTH_LIVE_DAYS.
#   `cooling` — they wrote back, but longer ago than that.
#   `dead`    — they wrote back, but longer ago than DEPTH_DEAD_DAYS.
#   `never`   — there IS thread data and they never wrote back. Evidence of silence.
#   `unknown` — there is no thread data at all. NOT evidence of anything.
#
# `never` and `unknown` are kept SEPARATE on purpose. A first pass conflated them, scoring both
# cold (right) and letting BOTH trigger the reunion gate (not right) — a store where most rows
# carry no message thread at all would then refuse a warm ask to nearly half the network on the
# strength of data nobody had. Absence of evidence is not evidence of absence, and a gate is
# exactly where that distinction has to be paid for. So both score 0, and only `never` and `dead`
# — the two states an actual thread backs — can trigger the reunion gate.
try:
    from kit_config import DEPTH_LIVE_DAYS
except Exception:
    DEPTH_LIVE_DAYS = 90
try:
    from kit_config import DEPTH_DEAD_DAYS
except Exception:
    DEPTH_DEAD_DAYS = 365
DEPTH_LIVE, DEPTH_COOLING, DEPTH_DEAD = "live", "cooling", "dead"
DEPTH_NEVER, DEPTH_UNKNOWN = "never", "unknown"
# The only states an actual thread backs. The reunion gate reads THIS, never the raw state, so a
# row with no message data can never be refused a warm ask for want of evidence nobody collected.
DEPTH_EVIDENCED_COLD = (DEPTH_DEAD, DEPTH_NEVER)


def thread_state(row, today=None):
    """(state, last_inbound_or_None) — is this thread live, and when did they last write?

    Pure. Reads only the `messages` block written by the message-parsing step. Never raises: an
    unparseable date degrades to `dead`, which is the safe direction for scoring and is still
    evidenced (they did write; we just cannot date it).
    """
    if not row:
        return DEPTH_UNKNOWN, None
    msgs = row.get("messages")
    if not isinstance(msgs, dict) or not msgs.get("total"):
        return DEPTH_UNKNOWN, None          # no thread on record — not a finding, an absence
    if not msgs.get("they_sent"):
        return DEPTH_NEVER, None            # a thread exists and they are not in it
    last = msgs.get("last_inbound")
    if not last:
        # They wrote back, but this row predates date capture. Not `never` (they DID reply) and not
        # `live` (nothing says it was recent) — `dead` is the honest floor until a re-parse dates it.
        return DEPTH_DEAD, None
    try:
        from datetime import date as _d
        y, m, d = (int(x) for x in str(last)[:10].split("-"))
        age = ((today or _d.today()) - _d(y, m, d)).days
    except Exception:
        return DEPTH_DEAD, None
    if age <= DEPTH_LIVE_DAYS:
        return DEPTH_LIVE, last
    if age <= DEPTH_DEAD_DAYS:
        return DEPTH_COOLING, last
    return DEPTH_DEAD, last


def uncertainty(row):
    """A reason this row's tier is doubted by the store itself, or None."""
    if not row:
        return None
    if row.get("⚠️CONTRADICTS"):
        return "store flags a two-way thread against this tag — level it"
    if _AMBIGUOUS_RE.search(str(row.get("evidence") or "")):
        return "brief exchange, ambiguous — level it"
    return None

# Outreach handling is a SEPARATE AXIS from closeness and always overrides it. Knowing someone is
# never permission to contact them: a paused or declined contact stays paused whatever their tier
# says, until YOU raise them again.
#
# 🔴 HANDLING STATE LIVES IN `outreach_status`, AND THAT IS WHERE THIS CHECK LOOKS FIRST. The
# upstream version of this check originally keyed on a `hold` field that no live row carried, so
# it caught 1 of 7 held contacts and missed the rest — including strong-tier rows it would have
# SURFACED with a bonus. A guard that promotes the people it exists to suppress. The regression
# test for this class must build fixture rows in the REAL shape (outreach_status values), never an
# idealised `hold` field.
#
# ⚖️ MATCHED ON THE STATE, NOT ON WHO SET IT. Different installs suffix the value with different
# names (`PAUSED-by-<owner>`), and a forked per-tree constant is two copies of one rule — the copy
# nobody re-reads is the one that drifts. So the patterns below are suffix-blind and shared
# VERBATIM with the upstream module: `paused-by-anyone` is the same fact to one table, and the
# unrecognised-status belt in is_held() means any spelling neither pattern knows still fails safe.
_HOLD_PATTERNS = (
    (re.compile(r"^paused\b", re.I),   "paused until the owner raises them"),
    (re.compile(r"^declined\b", re.I), "the owner declined this contact"),
    # 2026-08-02: the tier regex below already recognised do-not-contact spellings but the STATUS
    # matcher did not, so a do-not-contact written into `outreach_status` fell through to the
    # "unrecognised" catch-all. Same suffix-blind matching as the other two, same reason.
    (re.compile(r"^do-?not-?contact\b", re.I), "do-not-contact, stated by the owner"),
)
# Belt, not braces: a tier can also carry the state. Same suffix-blind matching, same reason.
HOLD_TIERS = {"known-DO-NOT-CONTACT"}
_HOLD_TIER_RE = re.compile(r"^(paused|declined|do-?not-?contact|known-DO-NOT-CONTACT)\b", re.I)

# tier -> (rung_key, band_label, ask, strength)
# rung_key is `log_linkedin_send.RUNGS` vocabulary ON PURPOSE, so the ranker's recommendation, the
# send log's record and `rung_ladder.py`'s measured reply rates are ONE vocabulary end to end. A
# second spelling here would silently split the ladder's denominator, which has already happened
# once upstream with followup/follow-up.
TIERS = {
    # ⚠️ THE BAND SAYS "warm 7 (5-6 if positioned)" AND THE PARENTHESIS IS THE POINT (2026-08-11).
    # It used to read a flat "warm 5-7", which promised two rungs no closeness answer can grant.
    # Read Andy's ladder: rung 5 is *they know someone at the target*, rung 6 is *they work at the
    # target*. Both turn on where the person SITS, which is a fact about their employer, not about
    # how well the owner knows them. Only rung 7 turns on standing, so rung 7 is the ceiling any tier
    # here can reach on its own. A strong tie makes the INTRODUCTION ask fair the moment the
    # position fact is true, and says nothing about it when it is not.
    # ⛔ Nothing branches on this string — `rank_criteria` unpacks it and never reads it, and
    # `check_preview` never touches it — so it is a label for a HUMAN, which is exactly why a label
    # that overstates access is worth fixing. The same category error in its load-bearing form was
    # BUG-161. [[shared-community-opens-rung-7]]
    "worked-together":    ("warm",          "warm 7 (5-6 if positioned)", "full warm ask; the rung 5-6 INTRODUCTION ask needs the position fact (they know someone at the target, or work there)", "strong"),
    "know-well":          ("warm",          "warm 7 (5-6 if positioned)", "full warm ask; the rung 5-6 INTRODUCTION ask needs the position fact (they know someone at the target, or work there)", "strong"),
    "personal-friend":    ("warm",          "warm 7 (5-6 if positioned)", "full warm ask; confirm the ask shape first, then the position fact for rungs 5-6", "strong"),
    "classmate":          ("warm",          "warm 7 (5-6 if positioned)", "full warm ask; the rung 5-6 INTRODUCTION ask needs the position fact (they know someone at the target, or work there)", "strong"),
    # THE REDUCED-ASK RULE: friendly-but-thin is a warm rung whose ask must EARN the request. You
    # cannot ask an acquaintance to hire you. Note what this does NOT do: the person stays
    # rank-worthy. "What you may ask" and "whether they are worth reaching" are two columns, never
    # one, and collapsing them is how a useful contact gets silently dropped.
    "know-not-close":     ("warm",          "warm 7",    'reduced ask only: "do you have relationships at [targets]?" NEVER hire-me', "thin"),
    # ⭐ RE-RULED to warm 7 on 2026-08-11. This used to read rung 10 on the reasoning that a shared
    # context is where you MET rather than a relationship. The occasion for revisiting it: the same
    # tier was MISSING from the upstream table entirely, so upstream it fell to the cold floor while
    # here it opened rung 10, and the two copies gave opposite answers to the same question.
    # 🧭 Settled at Kuya Andy's read, from his own ladder. Rungs 5 and 6 are SITUATIONAL (they know
    # someone at the target / they work there), so neither is something a closeness tier can grant.
    # Only rung 7 turns on standing, and its ask survives a thin tie by construction: not "vouch for
    # me" but "do you have relationships at these three?" Andy: "It doesn't have to be perfect
    # alignment to your target unit. You just need an 'in.'" A shared group is an in, not a
    # reference. Rung 10 was rejected because it is for someone met briefly with no thread, and
    # these contacts wrote real paragraphs.
    "shared-community":   ("warm",          "warm 7",    'reduced ask only: "do you have relationships at [targets]?" NEVER hire-me', "thin"),
    "best-friend-lapsed": ("reunion",       "off-ladder","reunion with NO ask; outreach later, separately",  "strong"),
    "known-level-tbd":    ("warm",          "BLOCKED",   "ask the level before building anything",           "thin"),
    "never-spoke":        (None,            None,        None,                                               "none"),
}

# Informal spellings a human answer might use. Handled as code aliases rather than data edits:
# rewriting a stated answer to match this table would be the tail wagging the dog, and every
# rewrite is a chance to lose one. Unmapped tiers still fall to the cold floor with a flag, so a
# NEW spelling degrades safely rather than silently becoming warm.
TIER_ALIASES = {
    "friend": "personal-friend",
    "acquaintance": "know-not-close",
}

# `never-spoke` splits on whether the person is plausibly the boss. A rung 3-4 hire-me ask TO A
# STRANGER WHO IS THE BOSS is not a mistake, it is the cold boss hunt and the method's main lane.
# What is a mistake is a hire-me ask to a stranger who could never hire you.
BOSS_CATEGORIES = {"product-leader", "founder-exec"}

_CREDENTIAL_TAIL = re.compile(r",.*$")
_PARENTHETICAL = re.compile(r"\(.*?\)")
_NON_ALPHA = re.compile(r"[^a-z ]+")


def normalize_name(raw):
    """Normalization is mandatory here, not cosmetic.

    LinkedIn names carry credential tails ("Jane Doe, PMP, CSPO") and parentheticals
    ("Jane (Jan) Doe"), and a naive dict lookup misses every one of them. The miss that matters is
    a HELD contact whose lookup fails: the hold check is silently defeated for exactly the person
    it exists to protect. Match on the entity, never the bare token.
    """
    s = str(raw or "").lower()
    s = _PARENTHETICAL.sub(" ", s)
    s = _CREDENTIAL_TAIL.sub("", s)
    s = _NON_ALPHA.sub(" ", s)
    return " ".join(s.split())


def load(path=None):
    """{normalized name: row}. Returns None when the store is ABSENT, which is not the same as empty.

    A fresh install has no store at all, and its gate must keep working rather than fail every
    warm send. `None` lets a caller tell "no store here" apart from "store says nobody".
    """
    p = path or STORE
    try:
        with open(p, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    contacts = raw.get("contacts") or {}
    out = {}
    for name, row in contacts.items():
        if not isinstance(row, dict):
            continue
        row = dict(row)
        row["display_name"] = name
        out[normalize_name(name)] = row
    return out


def tier_for(name, store):
    """The stated row, or None when this person is ABSENT.

    Absent is deliberately distinct from `never-spoke`. Never-spoke is an answer; absent is a
    question nobody asked yet — run /level-network to ask it.
    """
    if not store:
        return None
    return store.get(normalize_name(name))


def is_held(row):
    """Handling state, which overrides closeness entirely. Returns a reason or None.

    Order matters: `outreach_status` FIRST, because that is where the live data keeps it (see the
    _HOLD_PATTERNS comment for the miss this prevents).
    """
    if not row:
        return None
    status = str(row.get("outreach_status") or "").strip()
    for pat, reason in _HOLD_PATTERNS:
        if pat.search(status):
            note = row.get("paused_note") or row.get("decline_note")
            return reason + (f" — {str(note).strip()}" if note else "")
    if row.get("do_not_contact") is True:
        return "do-not-contact, stated by the owner"
    tier = str(row.get("closeness") or "")
    if tier in HOLD_TIERS or _HOLD_TIER_RE.search(tier):
        return "do-not-contact, stated by the owner"
    if status:
        # An unrecognised handling state is a HOLD, not a pass. A new value someone adds to the
        # store must fail safe: the cost of over-holding is one missed send you can unblock, and
        # the cost of under-holding is contacting someone you said not to.
        return f"unrecognised outreach_status {status!r} — holding until it is understood"
    return None


def held_contacts(store):
    """Every held row, for the ranker's `skipped` report and for the regression test."""
    if not store:
        return {}
    return {k: r for k, r in store.items() if is_held(r)}


def rung_for(row, category, today=None):
    """(rung_key, band, ask, bonus, flag) — the sanctioned ask for this person.

    `bonus` is added to the score; `flag` is a human note or None. Never raises: an unknown tier
    degrades to the cold shape with a flag, because the failure mode that matters is granting a
    WARMER ask than the relationship supports, and cold is the floor.

    ⚖️ THE ARITY IS DELIBERATELY UNCHANGED. The reunion gate below could have been a sixth tuple
    element, and was not: this function has two consumers by design — the ranker RECOMMENDS and
    the preview gate REFUSES — and a silent arity change breaks the refusing one, which is the one
    whose failure is invisible until a send goes out wrong. The depth verdict travels in the
    rung/band/ask/flag it already returns.
    """
    if row is None:
        # Cold shapes presume no relationship, so an unknown person fails SAFE. The flag is the
        # point: it converts a silent guess into a question you answer once and reuse forever.
        return _cold(category) + (0.0, "closeness UNRECORDED — run /level-network, then re-rank")

    tier = row.get("closeness")
    tier = TIER_ALIASES.get(tier, tier)
    if tier == "never-spoke" or tier is None:
        return _cold(category) + (0.0, uncertainty(row))

    spec = TIERS.get(tier)
    if spec is None:
        return _cold(category) + (0.0, f"unknown closeness tier {tier!r} — cold shape until levelled")

    rung, band, ask, strength = spec
    if tier == "known-level-tbd":
        return rung, band, ask, CLOSENESS_THIN, "level TBD — ask before building"

    doubt = uncertainty(row)
    inferred = str(row.get("source") or "") in INFERRED_SOURCES

    # ── THE REUNION GATE ─────────────────────────────────────────────────────────────────────
    # A STRONG tie whose thread is dead gets a reunion with NO ask, rather than the ladder's
    # usual bounded, easy-to-decline rung-7 style ask. That style is friction reduction CALIBRATED
    # FOR WEAK TIES — a bounded ask for someone who owes you nothing. Aimed at a close friend it
    # makes the ask SMALLER than the relationship and reads as transactional, and a job ask inside
    # the first contact after a long silence colors the reunion however carefully it is written.
    #
    # ⚖️ THE BONUS STAYS STRONG ON PURPOSE. What you may ASK and whether someone is worth REACHING
    # are two different columns (the reduced-ask rule, TIERS above). Docking points for a dead
    # thread would bury exactly the oldest relationships this gate exists to protect. Depth
    # changes the SHAPE of the ask, never the WORTH of the person.
    #
    # ⛔ SCOPED TO STRONG TIERS ONLY. A gate written for one rung binds every rung falling through
    # to it. A `know-not-close` contact with a dead thread is a stranger, not a reunion; they keep
    # the reduced warm-7 ask.
    if strength == "strong":
        _state, _last = thread_state(row, today)
        if _state in DEPTH_EVIDENCED_COLD:
            why = ("never wrote back" if _state == DEPTH_NEVER
                   else f"last heard from them {_last}" if _last else "thread long cold")
            return ("reunion", "off-ladder",
                    "reunion with NO ask; the outreach comes later, as its own message",
                    CLOSENESS_STRONG if not inferred else CLOSENESS_THIN,
                    f"strong tie, {why} — reunion first, and own the gap")

    if strength == "strong" and inferred:
        # The inferred-strong haircut. Scores thin AND says why, so confirming is a one-line fix
        # rather than a mystery.
        #
        # 2026-08-02: the ASK TEXT changes too, not only the bonus. Before this, an inferred
        # know-well returned the literal "full warm ask" string with the caveat living only in the
        # flag, and any consumer that printed the ask without the flag presented a machine guess as
        # the owner's judgment. The sanctioned shape until the owner confirms is the reduced
        # rung-7 ask, mirroring know-not-close. Refusal is UNCHANGED on purpose: thinness is
        # scoring, not refusal, so the gate still passes these rows.
        return rung, band, \
            ('INFERRED tier, not stated — reduced ask until confirmed: "do you have relationships '
             'at [targets]?"'), CLOSENESS_THIN, \
            doubt or "levelled from messages — confirm before a full warm ask"
    bonus = CLOSENESS_STRONG if strength == "strong" else CLOSENESS_THIN
    if doubt:
        # A doubted tier never earns the strong bonus, whatever it claims.
        bonus = min(bonus, CLOSENESS_THIN)
    return rung, band, ask, bonus, doubt


def levelling_queue(store):
    """Rows the store doubts, for the interview's re-ask set.

    One recorded answer outranks the guess forever; `STATED_SOURCE` makes it permanent.
    """
    if not store:
        return []
    out = []
    for row in store.values():
        why = uncertainty(row)
        if why and not is_held(row):
            out.append((row.get("display_name"), row.get("closeness"), why))
    return sorted(out, key=lambda r: (r[1] or "", r[0] or ""))


def _cold(category):
    if category in BOSS_CATEGORIES:
        return ("cold-boss", "rung 3-4", "hire-me ask is legitimate to a stranger who IS the boss")
    return ("cold-stranger", "rung 1-2", "connect only, zero ask")


def summary(store):
    """Coverage, for doctor.py and the briefing. A store nobody can see the shape of goes unmaintained."""
    if store is None:
        return None
    tally, inferred = {}, 0
    for row in store.values():
        t = row.get("closeness") or "unset"
        tally[t] = tally.get(t, 0) + 1
        if str(row.get("source") or "") in INFERRED_SOURCES and \
                (TIERS.get(t) or ("", "", "", ""))[3] == "strong":
            inferred += 1
    return {"total": len(store), "by_tier": tally, "inferred_strong": inferred}


if __name__ == "__main__":
    import sys
    st = load()
    if st is None:
        print(f"no closeness store at {STORE}")
        print("create it: run /level-network in Claude Code (needs a LinkedIn export)")
        sys.exit(1)
    s = summary(st)
    print(f"closeness store: {s['total']} contacts")
    for tier, n in sorted(s["by_tier"].items(), key=lambda kv: -kv[1]):
        canon = TIER_ALIASES.get(tier, tier)
        spec = TIERS.get(canon)
        band = spec[1] if spec else ("HOLD" if canon in HOLD_TIERS else "cold (unmapped)")
        alias = f"  (alias of {canon})" if canon != tier else ""
        print(f"  {tier:22s} {n:5d}   {band or 'cold'}{alias}")
    print(f"\n  {len(held_contacts(st))} contacts are HELD (paused, declined, or do-not-contact) and")
    print("  are excluded before scoring; handling state overrides closeness.")
    print(f"  {len(levelling_queue(st))} rows the store doubts itself, waiting on a level.")
    print(f"\n  {s['inferred_strong']} strong-tier rows are levelled from messages, so they score thin")
    print("  until you confirm them (volume is not intimacy).")
