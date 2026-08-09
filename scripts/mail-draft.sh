#!/bin/bash
# Apple Mail draft builder — creates a VISIBLE draft (NEVER sends) with the résumé attached.
# Auto-attach uses Mail's AppleScript API, NOT screen/computer-use control. You review the
# draft and hit Send yourself; this script never sends.
# Terminal-only (local osascript); the cloud session can't run this.
#
# Usage:
#   scripts/mail-draft.sh --to "addr@x" [--bcc "a@x,b@x"] --subject "..." \
#       --body-file /path/to/body.txt --attach "/path/to/Resume.pdf"
#   (--bcc comma-separated, NO spaces. --attach optional. body-file is UTF-8 text.)
set -uo pipefail
HERE="$(dirname "$0")"
# Owner-specific values (your name, the résumé filename convention) come from kit_config.py.
eval "$(python3 "$HERE/kit_config.py" --sh 2>/dev/null || true)"
KIT_OWNER_NAME="${KIT_OWNER_NAME:-Your Name}"
KIT_RESUME_EXAMPLE="${KIT_RESUME_EXAMPLE:-$KIT_OWNER_NAME - Resume - <Company>.pdf}"
KIT_RULES_DOC="${KIT_RULES_DOC:-documents/WORKFLOW-RULES.md}"
TO="" BCC="" SUBJECT="" BODYFILE="" ATTACH="" FORCE="" PRAISE_SOURCE="" LACIVITA_CHECK="" PRAISE_PHRASING="" COMPANY="" SEGMENT="" WARM_RUNG="" RUNG="" RUNG_EXPLICIT="" TARGETS="" POST_CONTACT="" NO_RESUME="" MTYPE="outreach" BOSS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --to) TO="$2"; shift 2;;
    --bcc) BCC="$2"; shift 2;;
    --subject) SUBJECT="$2"; shift 2;;
    --body-file) BODYFILE="$2"; shift 2;;
    --attach) ATTACH="$2"; shift 2;;
    --company) COMPANY="$2"; shift 2;;               # REQUIRED: company name — re-checked against blocked-list/dedup at send
    --praise-source) PRAISE_SOURCE="$2"; shift 2;;   # REQUIRED: cite the researched SPECIFIC boss accomplishment + source (Andy A2)
    --praise-phrasing) PRAISE_PHRASING="$2"; shift 2;; # REQUIRED: the Stage-2 phrasing YOU PICKED — must appear verbatim in the body
    --lacivita-check) LACIVITA_CHECK="$2"; shift 2;;  # REQUIRED: "pass" — the A1-A10 checklist was run+reported this email
    --segment) SEGMENT="$2"; shift 2;;                # REQUIRED on cold sends: one of your SEGMENTS slugs (kit_config.SEGMENTS). Andy's hot-zone test.
    --warm) WARM_RUNG="1"; shift;;                    # BACK-COMPAT alias for `--rung warm` (see the profile switch below)
    --rung) RUNG="$2"; RUNG_EXPLICIT=1; shift 2;;     # cold-boss|cold-stranger|warm|referred|event|thank-you|reply|follow-up
    --boss) BOSS="$2"; shift 2;;                      # REQUIRED on cold-boss: the person, checked against the boss registry
    --targets) TARGETS="$2"; shift 2;;                # warm/referred: comma-separated companies NAMED in the ask (dedup'd instead of --company)
    --no-resume) NO_RESUME="1"; shift;;               # explicit opt-out of the mandatory résumé attachment
    --force) FORCE="1"; shift;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

# ── THE GATE PROFILE ──────────────────────────────────────────────────────────────────────────
# The rung is not a label, it is the GATE PROFILE. Every gate below asks which profile it belongs
# to rather than firing unconditionally. Three profiles:
#
#   COLD  (cold-boss, cold-stranger) a stranger. Needs the full boss-hunt evidence: a researched
#         accomplishment with a primary source, the method checklist, the approved praise phrasing,
#         and a segment so the send can become hot-zone data. Dedup: --company must be NEW.
#   WARM  (warm, referred, event) a person you know, or a referral. There IS no boss, no researched
#         accomplishment and no praise beat in a favor asked of a friend, and the boss-hunt
#         checklist is the wrong instrument for it. Requiring that evidence is what made the warm
#         half of the ladder unsendable, so the whole ladder collapsed onto its cold rung.
#         Dedup shifts to --targets: the recipient is a CONNECTOR, not a target, so what must be
#         checked are the companies NAMED IN THE ASK.
#   POST-CONTACT (thank-you, reply, follow-up) someone ALREADY in your process. Skips the cold
#         evidence AND the warm --targets gate, and INVERTS dedup: the company must be
#         already-seen. That inversion is what stops a cold draft wearing a thank-you label to
#         skip the gauntlet.
#
# ⚠️ --rung is OPTIONAL here, unlike the reference implementation it was ported from. An absent
# --rung keeps the historical COLD behavior so no existing call breaks, and `--warm` keeps working
# as an alias rather than as a second code path that can drift.
# A CONTRADICTION MUST NOT RESOLVE SILENTLY. `--warm --rung cold-boss` used to end up COLD, because
# the alias only fills an EMPTY rung and the classifier below then clears WARM_RUNG. Silently
# picking one of two flags the caller disagreed with is how a send goes out under gates nobody
# chose. Say so and stop.
if [ -n "$WARM_RUNG" ] && [ -n "$RUNG" ]; then
  case "$RUNG" in
    warm|referred|event) : ;;   # agreeing spellings of the same intent, harmless
    *) echo "⛔ BLOCKED: --warm and --rung '$RUNG' contradict each other. --warm is an alias for" >&2
       echo "   '--rung warm'. Drop --warm, or pass the rung you actually mean." >&2; exit 4;;
  esac
fi
[ -n "$WARM_RUNG" ] && [ -z "$RUNG" ] && RUNG="warm"
case "$RUNG" in
  ""|cold-boss|cold-stranger) : ;;
  warm|referred|event) : ;;
  thank-you|reply|follow-up) POST_CONTACT=1 ;;
  *) echo "⛔ BLOCKED: unknown --rung '$RUNG'. One of: cold-boss | cold-stranger | warm | referred | event | thank-you | reply | follow-up." >&2
     echo "   The rung selects which evidence is required AND records the register for the tally." >&2; exit 4;;
esac
case "$RUNG" in warm|referred|event) WARM_RUNG=1;; *) WARM_RUNG="";; esac
case "$RUNG" in thank-you) MTYPE=thankyou;; reply) MTYPE=reply;; follow-up) MTYPE=followup;; *) MTYPE=outreach;; esac
[ -n "$TO" ] && [ -n "$SUBJECT" ] && [ -n "$BODYFILE" ] || { echo "need --to --subject --body-file" >&2; exit 2; }
[ -f "$BODYFILE" ] || { echo "body file not found: $BODYFILE" >&2; exit 2; }
[ -z "$ATTACH" ] || [ -f "$ATTACH" ] || { echo "attachment not found: $ATTACH" >&2; exit 2; }
# Résumé DELIVERABLE naming: the recipient SEES the attachment filename, so it must follow the
# convention "<Your Name> - Resume - <Company>.pdf" (documents/cv/), NEVER the internal source
# name like main_<co>.pdf. Patterns come from RESUME_FILENAME_PATTERNS in kit_config.py.
# WARN loudly if the attachment doesn't match.
if [ -n "$ATTACH" ]; then
  _ab="$(basename "$ATTACH")"
  _match=""
  while IFS= read -r _pat; do
    [ -z "$_pat" ] && continue
    case "$_ab" in
      $_pat) _match=1; break;;
    esac
  done <<< "${KIT_RESUME_PATTERNS:-}"
  [ -n "$_match" ] || echo "⚠️  attachment '$_ab' is not named per the convention '$KIT_RESUME_EXAMPLE'. A recipient sees this filename — copy cv/main_<co>.pdf to \"documents/cv/$KIT_RESUME_EXAMPLE\" and attach THAT (never the internal source name)." >&2
fi

# ── RÉSUMÉ ALWAYS ATTACHED (register gap G10) ────────────────────────────────────────────────
# The method attaches the résumé to EVERY boss-hunt email. That was documented as enforced while
# nothing enforced it, so "always" meant "whenever someone remembered to type the flag". Requiring
# an EXPLICIT --no-resume makes skipping it a deliberate, visible act instead of an omission.
if [ -z "$ATTACH" ] && [ -z "$NO_RESUME" ]; then
  echo "⛔ BLOCKED: no --attach. The method attaches your résumé to EVERY outreach email." >&2
  echo "   Attach \"documents/cv/$KIT_RESUME_EXAMPLE\", or pass --no-resume to opt out on purpose." >&2
  exit 4
fi

# METHOD gate: a boss-hunt email cannot fire without proof the
# method was followed — a researched SPECIFIC boss accomplishment + source (Andy A2/A3), and
# a run of the A1-A10 checklist. This is why the method kept getting skipped under volume:
# nothing gated on it. Now it does. --force bypasses only for a deliberate exception.
if [ -z "$FORCE" ]; then
  # G2 — DEDUP / BLOCKED-LIST at the send boundary: a dedup check that only runs at discovery
  # time does not protect the irreversible step, so a blocked or already-contacted company can
  # still reach a visible draft. Re-check here and block on a 🔴 hit.
  if [ -n "$POST_CONTACT" ]; then
    # POST-CONTACT INVERSE ANCHOR. A thank-you / reply / follow-up goes to someone ALREADY in your
    # process, so check_dup --send-gate must return 🔴 ALREADY-SEEN (exit 1). If it returns 🟢 NEW,
    # this is cold outreach wearing a thank-you label to skip the cold gauntlet: BLOCK. It is not
    # forgeable, because the company has to genuinely appear in a SENT or contacted store. The
    # normal dedup below blocks ON 🔴, so it is the OPPOSITE test and is skipped for post-contact.
    [ -n "$COMPANY" ] || { echo "⛔ BLOCKED: post-contact (thank-you/reply/follow-up) needs --company for the already-contacted anchor." >&2; exit 4; }
    if [ -f "$HERE/check_dup.py" ]; then
      python3 "$HERE/check_dup.py" --send-gate "$COMPANY" >/tmp/.md_pc.$$ 2>&1; _pc=$?
      rm -f /tmp/.md_pc.$$
      if [ "$_pc" != "1" ]; then
        echo "⛔ BLOCKED: a '$RUNG' goes to a company ALREADY in your process, but '$COMPANY' has no" >&2
        echo "   strong prior-contact record (check_dup --send-gate exit=$_pc, need 🔴 already-seen)." >&2
        echo "   If this is a NEW target, use a cold rung. You do not thank someone you never contacted." >&2
        exit 4
      fi
    fi
  elif [ -z "$WARM_RUNG" ]; then
    [ -n "$COMPANY" ] || { echo "⛔ BLOCKED: missing --company. Needed to re-check the blocked-list + dedup at send." >&2; exit 4; }
    if [ -f "$HERE/check_dup.py" ]; then
      # --send-gate: only block on BLOCKED-list / SENT / CONTACTED / correspondence stores — NOT the
      # construction records (decision-log, queues) where the in-flight build is expected to appear.
      python3 "$HERE/check_dup.py" --send-gate "$COMPANY" >/tmp/.md_dup.$$ 2>&1; _dc=$?
      if [ "$_dc" = "1" ]; then
        echo "⛔ BLOCKED: check_dup returned 🔴 for '$COMPANY' (blocked-list or strong duplicate). Do NOT send." >&2
        grep -iE "VERDICT|BLOCKED|already|declined" /tmp/.md_dup.$$ | head -3 >&2; rm -f /tmp/.md_dup.$$; exit 4
      fi
      [ "$_dc" = "3" ] && { echo "⚠️  check_dup 🟡 possible-dup for '$COMPANY' — confirm it's genuinely new before sending:" >&2; grep -iE "VERDICT|possible" /tmp/.md_dup.$$ | head -2 >&2; }
      rm -f /tmp/.md_dup.$$
    fi
  else
    # WARM / REFERRED: the recipient's own employer is irrelevant, because the person is a
    # CONNECTOR, not a target. What must be dedup'd are the companies NAMED IN THE ASK, so you
    # never ask a friend for an intro to a company that is blocked or already contacted.
    if [ -z "$TARGETS" ]; then
      if [ -n "$RUNG_EXPLICIT" ]; then
        echo "⛔ BLOCKED: rung '$RUNG' needs --targets \"Co1,Co2,Co3\" — the companies named in the ask." >&2
        echo "   They get dedup'd so you never ask for an intro to a blocked or already-contacted company." >&2
        exit 4
      fi
      # BACK-COMPAT: the bare `--warm` spelling predates --targets, so blocking it would break the
      # one warm call shape that already works. Warn loudly instead, and name what it costs.
      echo "⚠️  --warm with no --targets: the companies named in your ask were NOT dedup-checked, and" >&2
      echo "   this send records no targets, so trio burn-tracking cannot tell what you already asked" >&2
      echo "   about. Prefer: --rung warm --targets \"Co1,Co2,Co3\"." >&2
    else
      _bad=""; _checked=0
      IFS=',' read -ra _tg <<< "$TARGETS"
      for _t in "${_tg[@]}"; do
        _t="$(echo "$_t" | sed 's/^ *//;s/ *$//')"; [ -n "$_t" ] || continue
        _checked=$((_checked+1))
        if [ -f "$HERE/check_dup.py" ]; then
          python3 "$HERE/check_dup.py" --send-gate "$_t" >/tmp/.md_t.$$ 2>&1
          [ "$?" = "1" ] && { echo "⛔ BLOCKED: named target '$_t' is blocked or already contacted — do not ask for an intro to it." >&2; _bad=1; }
          rm -f /tmp/.md_t.$$
        fi
      done
      # A NON-EMPTY --targets THAT DEDUPS NOTHING IS NOT A PASS. `--targets ","` cleared the -n test
      # above, then every element trimmed to empty and hit the `continue`, so the loop ran ZERO
      # dedup checks and the send proceeded. The gate that exists to stop you asking a friend for an
      # intro to a blocked company was bypassable by typing one comma. Presence of the FLAG was
      # being treated as evidence the CHECK ran; those are different facts.
      if [ "$_checked" -eq 0 ]; then
        echo "⛔ BLOCKED: --targets \"$TARGETS\" contains no usable company name, so no dedup ran." >&2
        echo "   Pass the real companies named in the ask, e.g. --targets \"SomeCo,Globex,Initech\"." >&2
        exit 4
      fi
      [ -n "$_bad" ] && exit 4

      # ── G2b — THE BODY MUST NOT NAME A COMPANY THE DEDUP NEVER SAW (2026-07-25) ───────────────
      # The loop above dedups --targets. Nothing checked that --targets is what the BODY actually
      # asks about, and the only other reader of $BODYFILE is the praise-phrasing grep. So
      # `--targets "SomeCo"` with a body asking for intros to SomeCo, Globex and Initech sent with two
      # companies no dedup ever saw — precisely the harm the warm gate exists to prevent, reached by
      # under-declaring the flag rather than by omitting it. Same shape as the `--targets ","` defect
      # right above: the FLAG was treated as evidence about the BODY, and they are different facts.
      #
      # check_dup is the arbiter, which is what lets the extractor be generous: a capitalized phrase
      # that is not a company comes back 🟢 NEW and is ignored, so over-extraction costs a subprocess,
      # not a false block. Only a 🔴 (blocked or already-contacted) stops the send.
      if [ -f "$HERE/check_dup.py" ] && [ -f "$BODYFILE" ]; then
        if ! python3 - "$HERE" "$BODYFILE" "$TARGETS" <<'PYBODY'
import re, sys

here, bodyfile, targets_raw = sys.argv[1], sys.argv[2], sys.argv[3]
body = open(bodyfile, encoding="utf-8", errors="ignore").read()
targets = [t.strip() for t in targets_raw.split(",") if t.strip()]

def bounded(needle, hay):
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(needle) + r"(?![A-Za-z0-9])",
                     hay, re.I) is not None

# POSITIVE CONTROL, and it is the load-bearing half. If NOT ONE of the declared targets appears in
# the body, then either the matcher is broken or --targets describes a different ask than the one
# being sent. Both are failures, and a check that cannot tell "found nothing" from "looked at
# nothing" is not a check (the pre-push PII sweep learned this the expensive way). Refuse.
def declared_in_body(t):
    """A target counts as named if the whole string appears, or a distinctive token of it does.

    Real asks say "Acme" where --targets says "Acme Corp"; requiring the full string would block a
    perfectly correct send, and a gate that blocks correct sends gets --force'd around, which
    disables every other check in this block.
    """
    if bounded(t, body):
        return True
    return any(bounded(tok, body) for tok in re.split(r"[^A-Za-z0-9]+", t) if len(tok) >= 4)

if targets and not any(declared_in_body(t) for t in targets):
    print("⛔ BLOCKED: none of the --targets companies appear in the body.", file=sys.stderr)
    print(f"   --targets: {', '.join(targets)}", file=sys.stderr)
    print("   Either the body asks about different companies, or this check is broken. Both are", file=sys.stderr)
    print("   blockers: --targets must name the companies the ask actually names.", file=sys.stderr)
    sys.exit(1)

# MATCH AGAINST A KNOWN VOCABULARY, NOT AGAINST EXTRACTED PHRASES.
#
# The first version of this check extracted capitalized phrases from the body and asked check_dup
# to judge each one. That is wrong, and the test caught it: check_dup matches BOSS NAMES as well as
# companies, so "Hi Sam" and "Hope" both came back 🔴 and blocked a clean send. A gate with false
# positives on ordinary prose gets --force'd around within a day, which disables every other gate
# in this block too. So the direction is inverted: read the companies the pipeline ALREADY KNOWS
# are blocked or in-process, and look for THOSE in the body. Only a real company name can fire it.
# $HERE is `dirname "$0"`, which is RELATIVE when the script is invoked as `bash scripts/mail-draft.sh`.
# A naive rsplit on it yielded "scripts", the stores never opened, and the vocabulary came back
# empty — caught immediately by the positive control below, which is the whole reason it exists.
import os
repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.abspath(here))
known = set()
stores_read = 0
try:
    with open(repo + "/documents/blocked-employers-list.md", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if not line.lstrip().startswith(("-", "*")):
                continue
            b = re.findall(r"\*\*([^*]+)\*\*", line)
            if b:
                known.update(x.strip() for x in b)
            else:                                   # plain "- SomeCo, Otherco, Thirdco"
                known.update(x.strip() for x in re.split(r"[,;]", line.lstrip("-* ").strip()))
    stores_read += 1
except OSError:
    pass
try:
    import csv
    with open(repo + "/job_search_tracker.csv", encoding="utf-8", errors="ignore") as fh:
        for row in csv.DictReader(fh):
            if (row.get("company") or "").strip():
                known.add(row["company"].strip())
    stores_read += 1
except OSError:
    pass

# Trim to names that can be matched safely. Sub-4-character names collide with English constantly.
known = {k for k in known if 4 <= len(k) <= 60 and not k.startswith(("http", "["))}

# POSITIVE CONTROL #2, same reasoning as the one above: a vocabulary that never loaded would make
# this check pass every body silently, which looks identical to "nothing to report".
#
# The test is READABILITY, not size. A count threshold was the first attempt and it was wrong in a
# way that only showed up in the partner kit: a brand-new user legitimately has an empty blocked
# list and an empty tracker, and "fewer than N known companies" would have blocked every warm send
# they ever tried. Zero known companies is a real answer; zero readable STORES is a broken check.
if stores_read == 0:
    print("⛔ BLOCKED: neither known-company store could be read, so the body/targets", file=sys.stderr)
    print(f"   cross-check cannot have run (looked under {repo}).", file=sys.stderr)
    print("   Expected documents/blocked-employers-list.md and/or job_search_tracker.csv.", file=sys.stderr)
    sys.exit(1)

def mentioned(name):
    """Word-bounded hit, with a casing rule that keeps a common noun from matching a brand.

    A company written in prose is capitalized, UNLESS the brand itself is styled lowercase, in
    which case a lowercase hit is the correct one. Without the casing rule, a one-word company name
    that is also an ordinary English word fires on every sentence that happens to use the word.
    """
    inherently_lower = name == name.lower()
    for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", body, re.I):
        if inherently_lower or m.group(0)[0].isupper():
            return True
    return False

checked, bad = 0, []
for k in sorted(known):
    if any(bounded(t, k) or bounded(k, t) for t in targets):
        continue                                    # declared, and already dedup'd above
    checked += 1
    if mentioned(k):
        bad.append(k)

if bad:
    print("⛔ BLOCKED: the body names companies that are BLOCKED or ALREADY CONTACTED and are", file=sys.stderr)
    print(f"   not in --targets: {', '.join(bad)}", file=sys.stderr)
    print("   You would be asking for an intro to a company already in your process. Either drop", file=sys.stderr)
    print("   it from the body, or add it to --targets and re-run so it is dedup'd on the record.", file=sys.stderr)
    sys.exit(1)
print(f"✅ body/targets cross-check: {checked} undeclared name(s) dedup'd, 0 blocked")
PYBODY
        then
          exit 4
        fi
      fi
    fi
  fi
  # ── The boss-hunt proofs below are COLD-RUNG EVIDENCE ──────────────────────────────────────
  # A warm connector ask has no praise beat and no boss accomplishment, and the A1-A10 checklist is
  # the wrong instrument for it. Requiring them on a warm send is what made the warm lane
  # unsendable, which collapsed the whole ladder onto its cold rung.
  if [ -z "$WARM_RUNG" ] && [ -z "$POST_CONTACT" ]; then
  [ -n "$PRAISE_SOURCE" ] || { echo "⛔ BLOCKED: missing --praise-source. Andy A2 requires a RESEARCHED specific boss accomplishment + source (run boss-research-and-compliment first). No generic product/mission praise." >&2; exit 4; }
  # DEEP boss-research: the praise-source must carry a PRIMARY-SOURCE citation (a URL), not just a
  # bare claim — same rigor as the culture deep-screen. A secondhand metric repeated by a blog is a
  # false-positive risk: praise built on a number the person never claimed reads as flattery.
  case "$PRAISE_SOURCE" in
    *http://*|*https://*) : ;;
    *) echo "⛔ BLOCKED: --praise-source has no primary-source URL. Deep boss-research requires the accomplishment verified to a PRIMARY source (company blog / their own talk / named case study / filing — not a contact-database or SEO blurb) and cited with its URL. If the metric is secondhand-only, drop it." >&2; exit 4;;
  esac
  [ "$LACIVITA_CHECK" = "pass" ] || { echo "⛔ BLOCKED: missing --lacivita-check pass. Run the boss-hunt method checklist and report the ✅/⚠️/❌ table for THIS email first. See $KIT_RULES_DOC." >&2; exit 4; }
  # TWO-STAGE PRAISE gate: the praise TEXT must be a Stage-2 phrasing the HUMAN picked, not one the
  # assistant wrote and then presented as final. Require --praise-phrasing and confirm it appears
  # VERBATIM in the body — you cannot assemble-and-fire without isolating the approved phrasing.
  # See "Boss-praise = two-stage" in $KIT_RULES_DOC.
  [ -n "$PRAISE_PHRASING" ] || { echo "⛔ BLOCKED: missing --praise-phrasing. The praise beat must be a Stage-2 phrasing YOU picked (Stage 1 concept → Stage 2 phrasing). Never author-then-present-as-final. Pass the approved phrasing text." >&2; exit 4; }
  if ! grep -qF -- "$PRAISE_PHRASING" "$BODYFILE"; then
    echo "⛔ BLOCKED: --praise-phrasing text does not appear verbatim in the body. The body's praise beat must be the phrasing approved at Stage 2 (skipping or altering it is an unapproved edit). Reconcile them." >&2; exit 4;
  fi
  # ── BOSS REGISTRY ──────────────────────────────────────────────────────────────────────────
  # A cold-boss send names the person you researched, and that person must already have a fresh
  # registry record. Sends with no recipient identity cannot be attributed to anyone, and the
  # research behind them becomes unrecoverable.
  #
  # ⛔ SCOPED TO cold-boss ALONE, deliberately. Binding this to the shared cold branch would catch
  # cold-stranger, which by definition has no boss. A gate written for one rung binds every rung
  # that falls through to it, and that has been a recurring defect in this pipeline.
  if [ "$RUNG" = "cold-boss" ] && [ -f "$HERE/boss_registry.py" ]; then
    if [ -z "$BOSS" ]; then
      echo "⛔ BLOCKED: missing --boss on a cold-boss send. Name the person you researched." >&2
      exit 4
    fi
    if ! python3 "$HERE/boss_registry.py" check --company "$COMPANY" --person "$BOSS"; then
      exit 4
    fi
  fi
  fi   # end cold-rung-only proofs
  # SEGMENT gate: the method tests segments to find the hot-zone (5/segment, then compare reply
  # rates), so a COLD send with no segment can never become data. Warm/referred and post-contact
  # sends are chosen by relationship, so they carry no segment. Closed vocabulary from
  # kit_config.SEGMENTS (KIT_SEGMENT_SLUGS via --sh): a free-text label defeats the comparison.
  if [ -z "$WARM_RUNG" ] && [ -z "$POST_CONTACT" ]; then
    [ -n "$SEGMENT" ] || { echo "⛔ BLOCKED: missing --segment on a cold send. Pass one of your segment slugs ($KIT_SEGMENT_SLUGS) so the send becomes hot-zone data, or --warm for a relationship-based send. Define segments in scripts/kit_config.py + docs/segments.md." >&2; exit 4; }
    _segok=""; for _s in $KIT_SEGMENT_SLUGS; do [ "$_s" = "$SEGMENT" ] && _segok=1; done
    [ -n "$_segok" ] || { echo "⛔ BLOCKED: --segment '$SEGMENT' is not one of your defined segments ($KIT_SEGMENT_SLUGS). A lane from a discovery sweep is a FINDING, not a segment — see docs/segments.md." >&2; exit 4; }
  fi
fi
[ -z "$PRAISE_SOURCE" ] || echo "  praise-source: $PRAISE_SOURCE"
[ -z "$PRAISE_PHRASING" ] || echo "  praise-phrasing (Stage-2 pick, verbatim in body): $PRAISE_PHRASING"

# SEND-TIME conformance tripwire: scrub AI-tells / retired figures / format
# before building the draft. FAIL blocks unless --force (for a verified false positive).
if [ -f "$HERE/check_outreach.py" ]; then
  # --rung/--type matter: holding a warm connector ask to the cold-boss ingredient shape FAILS
  # correct messages, which is the other half of how the warm lane went unused.
  if ! python3 "$HERE/check_outreach.py" "$BODYFILE" --rung "${RUNG:-cold-boss}" --type "$MTYPE"; then
    if [ -z "$FORCE" ]; then
      echo "⛔ mail-draft blocked by check_outreach (fix the body, or re-run with --force if a false positive)." >&2
      exit 3
    fi
    echo "⚠️  check_outreach FAILED but --force given — proceeding." >&2
  fi
fi

# RÉSUMÉ QA AT SEND: a QA script that nothing consumes is decoration. verify_resume.py existed
# for a long time while NOTHING anywhere checked its exit code, so a failing résumé could be
# attached to a real draft. Verify the SOURCE .tex for the résumé being attached, when findable.
# WARM-RUNG FALLBACK: this used to be gated on -n "$COMPANY" alone, and a warm rung identifies by
# --targets rather than --company. So a warm send attached a résumé that NOTHING had QA'd, silently,
# because the whole block was skipped rather than failed.
_QA_CO="$COMPANY"
[ -z "$_QA_CO" ] && _QA_CO="$(printf '%s' "$TARGETS" | cut -d',' -f1 | sed 's/^ *//;s/ *$//')"
if [ -n "$ATTACH" ] && [ -f "$HERE/verify_resume.py" ] && [ -n "$_QA_CO" ]; then
  _slug="$(printf '%s' "$_QA_CO" | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]')"
  _repo="$(cd "$HERE/.." && pwd)"
  for _tex in "$_repo/cv/main_${_slug}.tex" "$_repo/documents/cv/main_${_slug}.tex"; do
    if [ -f "$_tex" ]; then
      if ! python3 "$HERE/verify_resume.py" "$_tex"; then
        if [ -z "$FORCE" ]; then
          echo "⛔ mail-draft blocked by verify_resume ($_tex). Fix the résumé, or --force if a verified false positive." >&2
          exit 5
        fi
        echo "⚠️  verify_resume FAILED but --force given — proceeding." >&2
      fi
      break
    fi
  done
fi

# ── BUILD GATE AT SEND ────────────────────────────────────────────────────────────────────────
# The PreToolUse/PostToolUse hooks fire on AskUserQuestion ONLY — there is no hook on Bash, Write
# or Edit. So an agent that drafted a body with Write and then ran this script never touched the
# gate at all: check_preview.py guards *asking about* a draft, not drafting, and not the
# irreversible send. Enforce the same ledger check HERE, at the boundary that actually matters.
# check_preview.py's own docstring concedes the point: the send boundary "is the irreversible step
# and the one that matters."
#
# Warm rungs are not company-scoped, so the per-company gate below cannot apply. They still need a
# LANE-level ruling — you having said to work the warm/network lane at all. Proportionality: the
# per-company gate exists to stop expensive misdirected research; a four-sentence connector ask has
# no such failure mode, and you review every draft before sending. But "no gate" is not the answer
# either, so require at least one genuine recorded ruling to exist.
if [ -z "$FORCE" ] && [ -n "$WARM_RUNG" ] && [ -f "$HERE/check_preview.py" ]; then
  if ! python3 - "$HERE" <<'PYLANE'
import sys
sys.path.insert(0, sys.argv[1])
try:
    from check_preview import _build_rulings
except Exception:
    sys.exit(0)          # fail-open only on an import break, never on a missing ruling
sys.exit(0 if _build_rulings() else 1)
PYLANE
  then
    echo "⛔ BLOCKED: warm rung needs a LANE-level ruling. documents/decision-ledger.jsonl holds no" >&2
    echo "   genuine recorded BUILD ruling. Get an explicit go on working the warm lane first." >&2
    exit 6
  fi
fi

if [ -z "$FORCE" ] && [ -n "$COMPANY" ] && [ -z "$WARM_RUNG" ] && [ -z "$POST_CONTACT" ] && [ -f "$HERE/check_preview.py" ]; then
  if ! python3 - "$HERE" "$COMPANY" <<'PYGATE'
import sys, re
sys.path.insert(0, sys.argv[1])
try:
    from check_preview import _build_rulings
except Exception:
    sys.exit(0)          # fail-open only on an import break, never on a missing ruling
co = sys.argv[2].strip().lower()
rulings = {r for r in _build_rulings() if r}

# WORD-BOUNDARY MATCH, bounded on BOTH sides. A naive bidirectional substring test
# (`any(r in co or co in r ...)`) lets a ruling for "ZZ" authorize a real draft to "ZZNorthwind",
# and a ruling for "Alpha" authorize "Alphabet Systems". Bidirectional is still required — a ruling
# recorded from a scorecard as "Alpha (alpha.io)" must still authorize --company Alpha — but each
# direction must respect word boundaries.
def _bounded(needle, hay):
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", hay) is not None

if not rulings or not any(_bounded(r, co) or _bounded(co, r) for r in rulings):
    print(f"⛔ BUILD GATE: no valid BUILD ruling recorded for '{sys.argv[2]}'.", file=sys.stderr)
    print("   workflow-checklist: present the Boss Match Scorecard and get an explicit", file=sys.stderr)
    print("   build/skip ruling BEFORE building or sending. A short go-ahead is not a ruling.", file=sys.stderr)
    sys.exit(1)
PYGATE
  then
    echo "⛔ mail-draft blocked by the BUILD GATE (no recorded ruling for --company \"$COMPANY\")." >&2
    exit 6
  fi
fi

# AppleScript's `POSIX file` REQUIRES absolute paths — a relative path attaches nothing (silent fail).
BODYFILE="$(python3 -c 'import os,sys;print(os.path.abspath(sys.argv[1]))' "$BODYFILE")"
[ -n "$ATTACH" ] && ATTACH="$(python3 -c 'import os,sys;print(os.path.abspath(sys.argv[1]))' "$ATTACH")"

osascript - "$TO" "$BCC" "$SUBJECT" "$BODYFILE" "$ATTACH" <<'APPLESCRIPT'
on run argv
    set toAddr to item 1 of argv
    set bccList to item 2 of argv
    set subj to item 3 of argv
    set bodyFile to item 4 of argv
    set attachPath to item 5 of argv
    set bodyText to (read (POSIX file bodyFile) as «class utf8»)
    -- iOS-QUOTED-BODY FIX: Mail composes in Rich Text (HTML) by default, and a
    -- body injected with bare LF (\n) line breaks gets wrapped so iOS Mail shows the whole body inside
    -- a quote bar (macOS Mail renders it flat). Normalizing LF -> CR (return) makes Mail build clean
    -- paragraphs, which both clients render flat. Handles CRLF too (strip CR first, then LF -> CR).
    set AppleScript's text item delimiters to (ASCII character 13) & (ASCII character 10)
    set bodyText to (text items of bodyText) as text            -- CRLF -> (joined)
    set AppleScript's text item delimiters to (ASCII character 13)
    set bodyText to (text items of bodyText) as text            -- drop any stray CR
    set AppleScript's text item delimiters to (ASCII character 10)
    set _parts to text items of bodyText
    set AppleScript's text item delimiters to return
    set bodyText to _parts as text                              -- LF -> CR (clean paragraphs)
    set AppleScript's text item delimiters to ""
    tell application "Mail"
        -- NOTE: `activate` deliberately removed — bringing Mail to the foreground via
        -- AppleScript `activate` was observed waking unrelated media apps. The visible draft is
        -- still created (visible:true); Mail just won't jump to the front — click over to it.
        launch
        -- let Mail finish launching if it was closed (cold-start race)
        delay 2
        -- trailing newline gives "after the last paragraph" a valid anchor for the attachment
        set m to make new outgoing message with properties {subject:subj, content:bodyText & return, visible:true}
        tell m to make new to recipient at end of to recipients with properties {address:toAddr}
        if bccList is not "" then
            set AppleScript's text item delimiters to ","
            set bccItems to text items of bccList
            set AppleScript's text item delimiters to ""
            repeat with b in bccItems
                if (b as text) is not "" then
                    tell m to make new bcc recipient at end of bcc recipients with properties {address:(b as text)}
                end if
            end repeat
        end if
        if attachPath is not "" then
            -- let Mail fully render the draft before attaching (race-condition fix)
            delay 1.5
            tell m to tell content to make new attachment with properties {file name:(POSIX file attachPath)} at after the last paragraph
            delay 1
        end if
    end tell
end run
APPLESCRIPT
STATUS=$?
if [ $STATUS -eq 0 ]; then
  # STAGED entry in the shared stores so a parallel session sees the in-flight draft. Additive: the
  # "STAGED ... awaiting your send" marker carries no "sent" token, so it never reads as a real send
  # (your own Send later turns it into a SENT record). Re-staging the same company is prevented
  # upstream by the dedup gate, which will then see this company in outreach_log.md.
  _LOG_CO="$COMPANY"
  # Same warm-rung fallback as the résumé QA: a warm send identifies by --targets, not --company.
  [ -z "$_LOG_CO" ] && _LOG_CO="$(printf '%s' "$TARGETS" | cut -d',' -f1 | sed 's/^ *//;s/ *$//')"
  _LOG_CO="${_LOG_CO:-(unspecified)}"
  _OLOG="$(cd "$HERE/.." && pwd)/outreach_log.md"
  _CLOG="$(cd "$HERE/.." && pwd)/documents/correspondence-log.md"
  _TODAY="$(date '+%Y-%m-%d')"
  # ── FOLLOW-UP ARMING, WARM RUNGS ONLY ────────────────────────────────────────────────────────
  # A cold non-replier gets a NEW target, never a chase, so only warm rungs arm a second touch.
  # The token must be PRESENT either way: a cold send writes `FOLLOWUP-DUE: none` so the follow-up
  # checker reads it as a DECISION rather than an un-armed send, which is what stopped every
  # compliant cold send from reding the consistency check forever. This set must stay in sync with
  # ARMS_FOLLOWUP in log_linkedin_send.py, or the two paths disagree and the rule is decorative.
  # ⛔ NO RUNG ARMS A FOLLOW-UP (BUG-094, fixed 2026-08-09). This case armed four rungs while
  # check_followups.ARMS_FOLLOWUP was already empty, so the kit wrote follow-up dates its own
  # checker never looked for. All three sites now agree: here, log_linkedin_send.ARMS_FOLLOWUP,
  # and check_followups.ARMS_FOLLOWUP. The empty case is kept rather than deleted so restoring a
  # rung is a one-line change, and so this stays the single arming site.
  case "$RUNG" in
    *) _FUP="none" ;;
  esac
  # SEND-LOG, the machine-readable record. rank_criteria.py reads the `targets` field to burn-track
  # which companies a warm ask already named, so without this the trio generator keeps proposing
  # companies you already asked about.
  _SLOG="$(cd "$HERE/.." && pwd)/documents/send-log.jsonl"
  if [ -d "$(dirname "$_SLOG")" ]; then
    python3 - "$_SLOG" "${RUNG:-cold-boss}" "$TO" "$_LOG_CO" "$TARGETS" "$SUBJECT" "$_FUP" "$SEGMENT" <<'PYLOG' 2>/dev/null || true
import json, sys, datetime, os
path, rung, to, company, targets, subject, fup, segment = sys.argv[1:9]
# ⛔ ONE DEFINITION OF THE STATUS THIS FILE WRITES. The row below and the rebuild guard further
# down must agree, and they are twelve lines apart. A guard that matched a status this script does
# not write would never fire, and the fix would be present in the file and dead in practice.
STAGED_STATUS = "staged"
# ⚠️ `targets` is a COMMA-SEPARATED STRING, not a list. rank_criteria.burned_targets() reads it as
# `(row.get("targets") or "").split(",")`, and log_linkedin_send.py writes it the same way. A list
# here is silently unreadable to the consumer, so the burn guard that stops one company being named
# in two different warm trios would stay dead while this log looked perfectly populated. Match the
# READER, not what looks tidier in JSON.
row = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
       "date": datetime.date.today().isoformat(),
       "channel": "email", "status": STAGED_STATUS, "rung": rung, "to": to,
       "company": company,
       "targets": ",".join(t.strip() for t in targets.split(",") if t.strip()),
       "subject": subject, "followup_due": fup, "segment": segment}
# ── ONE ROW PER DRAFT, NOT ONE PER BUILD ──────────────────────────────────────────────────
# Rebuilding a draft (a corrected attachment, a reworded subject line) used to append a SECOND
# staged row here while the outreach log's own marker guard correctly deduplicated, so the two
# stores disagreed in BOTH directions and the daily counters could not be reconciled. A rebuild
# is the SAME draft in a later state, so the existing row is overwritten rather than joined.
# ⚠️ Only staged rows are eligible. A row that already reads as sent is history and is never
# touched. Unparseable lines are preserved exactly as found rather than dropped, and the rewrite
# is atomic (temp file + os.replace) so an interrupted run cannot truncate a shared store.
rows, replaced = [], False
if os.path.exists(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                rows.append(line)
for i in range(len(rows) - 1, -1, -1):
    r = rows[i]
    if (isinstance(r, dict) and r.get("status") == STAGED_STATUS and r.get("to") == to
            and r.get("company") == company and r.get("subject") == subject):
        rows[i] = row
        replaced = True
        break
if not replaced:
    rows.append(row)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    for r in rows:
        fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
os.replace(tmp, path)
if replaced:
    print("   ♻️  rebuild: existing staged row updated in place (one row per draft)")
PYLOG
  fi
  _STAG_KEY="STAGED · ${_LOG_CO} · ${SUBJECT}"
  if [ -f "$_OLOG" ] && grep -qF -- "$_STAG_KEY" "$_OLOG" 2>/dev/null; then
    echo "   📝 STAGED entry already present for '${_LOG_CO}' / this subject — not duplicating."
  else
    {
      printf '\n## %s · %s · %s — STAGED (draft)\n' "$_TODAY" "$_LOG_CO" "$TO"
      printf '<!-- %s -->\n' "$_STAG_KEY"
      printf '**Status:** STAGED (draft created, awaiting your send) %s to %s.\n' "$_TODAY" "$TO"
      printf '**Subject:** %s\n' "$SUBJECT"
      # Rung + FOLLOWUP-DUE on the block itself: check_followups.py reads this file, and a SENT
      # block with no FOLLOWUP-DUE token at all is what it flags as un-armed.
      printf '**Rung:** %s | FOLLOWUP-DUE: %s\n' "${RUNG:-cold-boss}" "$_FUP"
      [ -z "$TARGETS" ] || printf '**Targets:** %s\n' "$TARGETS"
    } >> "$_OLOG" 2>/dev/null \
      && echo "   📝 STAGED touch logged to outreach_log.md (company=$_LOG_CO)" || true
    if [ -d "$(dirname "$_CLOG")" ]; then
      printf -- '- %s · OUTBOUND (STAGED, not yet sent) · %s → %s · subj: %s\n' \
        "$_TODAY" "$_LOG_CO" "$TO" "$SUBJECT" >> "$_CLOG" 2>/dev/null || true
    fi
  fi
  echo "OK: draft created in Apple Mail (visible, NOT sent). CONFIRM the résumé is attached, then send it yourself."
else
  echo "ERROR creating draft (exit $STATUS)."
fi
