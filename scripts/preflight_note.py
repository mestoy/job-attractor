#!/usr/bin/env python3
"""preflight_note.py -- will this outreach note pass the body gates, and if not, EVERY reason in one report (BUG-202 item 2).

mail-draft.sh stops at its first failing gate and runs the reviewer panel in the middle, so a note used to fail one
gate at a time, and every body edit orphaned the panel receipt. This runs the gates that depend only on the BODY, together,
with NO side effects: it writes nothing, logs nothing, sends nothing, and never touches the panel receipt.

    preflight_note.py <body-file> --rung R [--company C] [--targets "A,B"] [--praise-phrasing "..."] [--segment S] [--advisory]
(--company and --segment are accepted so the whole mail-draft argv can be reused; no body gate reads them)

Gates run (the same code mail-draft.sh runs, via body_gates.py and check_outreach.py):
  check_outreach     voice, honesty, retired figures, format, signature, first-contact ingredients and O-A-K
  praise-phrasing    cold-boss: the Stage-2 phrasing he picked appears VERBATIM in the body
  targets            when --targets is given: the body names a declared target and no undeclared blocked company
NOT run, because they do not depend on the body: dedup, the boss registry, the BUILD ruling, attachments, the panel receipt.
mail-draft.sh still runs those, and the panel receipt still has to be taken on the final body.

--advisory is for a PARTIAL draft at each beat: first-contact shape failures (signature, ingredients, O-A-K, a missing
praise phrasing) print as "not covered yet" and do not fail. Voice, honesty, figure and format failures still fail.
The default is the hard gate for the assembled note.

Exit: 0 would pass, 1 would fail, 2 usage.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import body_gates  # noqa: E402

COLD_PRAISE_RUNGS = ("cold-boss",)


def parse(argv):
    opts = {"advisory": False, "rung": "", "company": "", "targets": "", "praise_phrasing": "", "segment": ""}
    flags = {"--rung": "rung", "--company": "company", "--targets": "targets", "--praise-phrasing": "praise_phrasing",
             "--segment": "segment"}
    body, i = None, 1
    while i < len(argv):
        a = argv[i]
        if a == "--advisory":
            opts["advisory"] = True
        elif a in flags and i + 1 < len(argv):
            opts[flags[a]] = argv[i + 1]
            i += 1
        elif a.startswith("--"):
            return None, opts
        elif body is None:
            body = a
        else:
            return None, opts
        i += 1
    return body, opts


def data_root():
    for var in ("JOBSEARCH_DATA_ROOT", "CLAUDE_PROJECT_DIR"):
        v = os.environ.get(var)
        if v and os.path.isdir(v):
            return os.path.abspath(v)
    return os.path.dirname(HERE)


def run(body_path, opts):
    """(hard failures, not-covered-yet notes), each a list of 'gate: message' strings."""
    hard, notes = [], []
    rung = opts["rung"] or "cold-boss"
    advisory = opts["advisory"]
    with open(body_path, encoding="utf-8", errors="ignore") as fh:
        body = fh.read()

    rc, fails, _text = body_gates.check_outreach_text(HERE, body_path, rung, body_gates.mtype_for_rung(rung))
    if rc != 0 and not fails:
        hard.append("check_outreach: it failed without naming a reason (exit %d); run it directly" % rc)
    shape, voice = body_gates.split_shape(fails)
    hard += ["check_outreach: " + f for f in voice]
    for f in shape:
        (notes if advisory else hard).append("check_outreach: " + f)

    phrasing = opts["praise_phrasing"]
    if phrasing:
        if not body_gates.phrasing_in_body(body, phrasing):
            hard.append("praise-phrasing: the picked phrasing does not appear verbatim in the body")
    elif rung in COLD_PRAISE_RUNGS:
        (notes if advisory else hard).append("praise-phrasing: none given; a cold-boss note needs the Stage-2 phrasing he picked")

    if opts["targets"]:
        import io
        out, err = io.StringIO(), io.StringIO()
        if body_gates.targets_cross_check(data_root(), body_path, opts["targets"], out, err) != 0:
            msg = " ".join(l.strip() for l in err.getvalue().splitlines() if l.strip())
            hard.append("targets: " + msg.replace("\u26d4 BLOCKED: ", "")[:400])
    return hard, notes


def main(argv):
    body, opts = parse(argv)
    if not body or not os.path.isfile(body):
        print(__doc__.split("Gates run")[0].strip(), file=sys.stderr)
        return 2
    hard, notes = run(body, opts)
    mode = "advisory" if opts["advisory"] else "hard gate"
    if hard:
        print("\U0001f534 preflight (%s): %d failure(s), every one reported below" % (mode, len(hard)))
        for h in hard:
            print("   ❌ " + h)
    else:
        print("\U0001f7e2 preflight (%s): the body gates pass" % mode)
    for n in notes:
        print("   … not covered yet: " + n)
    print("   (not checked here: dedup, boss registry, BUILD ruling, attachments, and the panel receipt, which must be taken on the final body)")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
