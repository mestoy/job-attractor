#!/usr/bin/env python3
"""log_impression.py — PostToolUse hook on AskUserQuestion. The TARGET-IMPRESSION logger.

Runs in the PostToolUse/AskUserQuestion chain AFTER record_decision.py, and records — systematically,
every time — BOTH what the ranker SURFACED (the picker's options and its top/default) and what the user
DID (his answer). This is the fix to BUG-185: self-learning was ad hoc, captured only if the assistant
remembered to. Now the corrections are a durable, append-only store the Phase-3 verdict miner reads to
derive accepted / rejected / passed-over labels.

⛔ FACTS, NEVER VERDICTS. The row records the surfaced options and the chosen index; it does NOT label
anything "rejected" or "passed-over". Those are DERIVED downstream, so the miner can change its logic
without the raw record lying. The whole point is a non-forgeable trail of what happened.

⛔ FAIL-OPEN, ALWAYS EXIT 0. A hook that blocks the owner's pick is worse than a missed impression. Any
malformed payload, any exception, any slow enrichment: the row is skipped, never the pick. Every path
returns 0. This mirrors record_decision.py's contract; the two share the same stdin.

READ, NEVER COPIED. The option-reference resolver and the pair marker are IMPORTED from their owners
(record_decision.resolve_option_answer, pair_brief.PAIR_MARKER), so a reader that drifts from the
production value is impossible ([[promotion-is-only-as-strong-as-its-reader]]).

pair_brief stays READ-ONLY: this hook is the writer, pair_brief never becomes one.

GENERIC: no owner-specific strings. The marker comes from pair_brief; the target shape is parsed
structurally; the store records whatever THIS user's pickers carry. Ships to the partner kit unchanged.
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Same repo-root resolution as record_decision.py:30 — the path-divergence bug (writer and reader on
# different files) already cost this repo once; both honor CLAUDE_PROJECT_DIR, then the script parent.
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(REPO, "documents", "state", "target-impressions.jsonl")

try:
    from record_decision import resolve_option_answer
except Exception:                                        # pragma: no cover - fail-open import
    def resolve_option_answer(answer, question):
        return str(answer or "")

try:
    from pair_brief import PAIR_MARKER
except Exception:                                        # pragma: no cover - fail-open import
    PAIR_MARKER = "NEXT-STEP"


def parse_target(text):
    """Parse a surfaced target from an option's label+description. Returns {name, company, rung} or
    None. Structural, never name-list based: a target reads 'Name · Title @ Company · rung X'. Tolerant
    of a leading prefix ('next initial contact: ') and badge glyphs. No '@' → not a target."""
    if not text or "@" not in text:
        return None
    segs = [s.strip() for s in str(text).split("·")]
    # Prefer the LAST '@'-bearing segment that still has a name segment before it (i >= 1). This way
    # an email or handle '@' in the leading segment — "Reach Priya (priya@x.com) · VP @ Northwind ·
    # rung 8" — does not shadow the real "@ Company" segment and drop the target to None (red-team S3).
    at_cands = [i for i, s in enumerate(segs) if "@" in s and i >= 1]
    if not at_cands:
        return None
    at_i = at_cands[-1]
    company = segs[at_i].split("@", 1)[1].strip()
    company = re.split(r"\s+(?:rung|source)\b", company, maxsplit=1, flags=re.I)[0]
    company = company.split("·")[0].strip().rstrip(".") or None
    name_seg = segs[at_i - 1]
    if ":" in name_seg:                                  # drop a 'next initial contact:' style prefix
        name_seg = name_seg.rsplit(":", 1)[1]
    name = re.sub(r"^[^\w]+", "", name_seg).strip()      # strip leading emoji / glyphs
    if not name:
        return None
    m = re.search(r"\brung\s+([^\s.,;·)]+)", str(text), re.I)
    return {"name": name, "company": company, "rung": m.group(1) if m else None}


def _match(question, header, options):
    """(trigger|None). A question is a target impression iff the pair marker is present (the NEXT-STEP
    picker), or any option is target-shaped with a rung token (a target picker outside the pair)."""
    if PAIR_MARKER in f"{question}\n{header}":
        return "pair-marker"
    for opt in options:
        t = parse_target(_opt_text(opt))
        if t and t.get("rung"):
            return "target-shaped-option"
    return None


def _opt_text(opt):
    if isinstance(opt, dict):
        return f"{opt.get('label', '')} {opt.get('description', '')}".strip()
    return str(opt)


def _opt_label(opt):
    return str(opt.get("label") if isinstance(opt, dict) else opt).strip()


def _chosen_index(resolved, options):
    """(idx_1based|None). Exact label match first, then a prefix match (labels can carry badge/state
    suffixes the answer omits). No match → None (an off-list / free-text answer)."""
    r = (resolved or "").strip()
    if not r:
        return None
    labels = [_opt_label(o) for o in options]
    for i, lab in enumerate(labels, 1):
        if lab and lab == r:
            return i
    # A label can carry a trailing badge/state the answer omits ("Frank Smith 🔬 resolved" vs the
    # answer "Frank Smith"), so match where the LABEL starts with the answer — never the reverse,
    # which would let a short label swallow a longer, more specific answer and flip accepted vs
    # passed-over (red-team S1). On ties, the longest (most specific) label wins.
    pref = [(i, lab) for i, lab in enumerate(labels, 1) if lab and lab.startswith(r)]
    if pref:
        return max(pref, key=lambda t: len(t[1]))[0]
    return None


def _rank_context():
    """Best-effort, DEFAULT OFF. The shown options already encode what the ranker surfaced, which is
    what BUG-185 needs, so the full ranked snapshot is enrichment only. Gated behind an env knob so it
    never adds a ~1,400-contact recompute to the owner's every pick. Any failure → None, never a block."""
    if not os.environ.get("JOBSEARCH_IMPRESSION_RANKCTX"):
        return None
    import signal
    def _timeout(*_a):                                   # pragma: no cover - env-gated enrichment
        raise TimeoutError("rank_context recompute exceeded its budget")
    prev = None
    try:                                                 # pragma: no cover - env-gated enrichment
        prev = signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(5)                                  # a hung recompute must never stall the turn
        import rank_criteria as rc
        fn = getattr(rc, "rank_people", None)
        ranked = fn(40) if callable(fn) else None
        if not ranked:
            return None
        skip = getattr(rc, "NON_BOSS_HUNT_CATS", set())
        top = [{"pos": i, "name": r.get("name"), "company": r.get("company"),
                "cat": r.get("cat"), "rung": r.get("rung"), "pts": r.get("pts")}
               for i, r in enumerate(r for r in ranked if r.get("cat") not in skip)][:10]
        return {"provenance": "recomputed-at-log-time", "top": top}
    except Exception:
        return None
    finally:
        try:
            signal.alarm(0)
            if prev is not None:
                signal.signal(signal.SIGALRM, prev)
        except Exception:
            pass


def build_row(session, q, answers, get_ctx=_rank_context):
    """A target-impression row for one question, or None if this question is not a target picker.

    get_ctx is a zero-arg callable for the (default-off) rank enrichment; main() passes a memoizer so
    a payload with several matched questions recomputes the ranking at most once (red-team S4)."""
    question = str(q.get("question", ""))
    header = str(q.get("header", ""))
    options = q.get("options") or []
    if not isinstance(options, list):
        return None
    trigger = _match(question, header, options)
    if not trigger:
        return None

    answer_raw = str(answers.get(question, "") or "")
    resolved = resolve_option_answer(answer_raw, q)
    chosen_idx = _chosen_index(resolved, options)

    opt_rows = []
    for i, opt in enumerate(options, 1):
        opt_rows.append({"idx": i, "label": _opt_label(opt),
                         "target": parse_target(_opt_text(opt)), "is_default": i == 1})

    surfaced_top = opt_rows[0]["target"] if opt_rows else None
    # Key on the FULL option payload (labels + targets), JSON-canonical — never a '|'-joined label
    # string, which collides when a label itself contains '|' and under-keys when the same label
    # re-surfaces a DIFFERENT target under option 1 (red-team S2). Canonical dumps make it stable.
    key_src = json.dumps({"s": session, "q": question, "a": answer_raw, "o": opt_rows},
                         sort_keys=True, ensure_ascii=False)
    return {
        "kind": "target-impression", "v": 1,
        "ts": datetime.now(timezone.utc).isoformat(),
        "session": session, "question": question, "header": header,
        "trigger": trigger,
        "options": opt_rows,
        "chosen": {"answer": answer_raw, "resolved": resolved,
                   "idx": chosen_idx, "off_list": chosen_idx is None},
        "surfaced_top": ({"name": surfaced_top["name"], "company": surfaced_top.get("company")}
                         if surfaced_top else None),
        "rank_context": get_ctx(),
        "ledger_key": {"session": session, "question": question, "answer": answer_raw},
        "impression_key": hashlib.sha256(key_src.encode("utf-8")).hexdigest(),
        "source": "posttooluse-hook",
    }


def _existing_keys():
    keys = set()
    if not os.path.exists(STORE):
        return keys
    try:
        with open(STORE, encoding="utf-8") as fh:
            # Bound the parse to the recent tail: a double PostToolUse fires adjacent in time, so the
            # dedupe only needs the recent window, and this keeps the hook off an O(n) whole-file
            # parse as the store grows (red-team N1).
            for ln in fh.read().splitlines()[-1000:]:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    keys.add(json.loads(ln).get("impression_key"))
                except Exception:
                    continue
    except Exception:
        pass
    return keys


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        session = str(payload.get("session_id", ""))
        tool_input = payload.get("tool_input") or {}
        tool_response = payload.get("tool_response") or {}
        questions = tool_input.get("questions")
        if not isinstance(questions, list):
            return 0
        answers = tool_response.get("answers") or tool_input.get("answers") or {}
        if isinstance(answers, str):
            try:
                answers = json.loads(answers)
            except Exception:
                answers = {}
        if not isinstance(answers, dict):
            answers = {}

        # Memoize the (default-off) rank enrichment so several matched questions recompute it at most
        # once, and only on a real match (get_ctx is called from inside build_row after the trigger).
        _ctx_cache = {}
        def get_ctx():
            if "v" not in _ctx_cache:
                _ctx_cache["v"] = _rank_context()
            return _ctx_cache["v"]

        rows = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            try:
                row = build_row(session, q, answers, get_ctx)
            except Exception:
                row = None                               # one bad question never sinks the rest
            if row:
                rows.append(row)
        if not rows:
            return 0

        seen = _existing_keys()
        fresh = [r for r in rows if r["impression_key"] not in seen]
        if not fresh:
            return 0
        os.makedirs(os.path.dirname(STORE), exist_ok=True)
        with open(STORE, "a", encoding="utf-8") as fh:
            for r in fresh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
