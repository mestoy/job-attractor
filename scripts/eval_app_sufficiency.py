#!/usr/bin/env python3
"""Does the app carry enough to reach the verdict the operator reached?

A two-arm agreement test. Blinded judges read ONE card's evidence and name a verdict;
half see only what the app renders from the feed, half see the whole source card. Both
arms are scored against the operator's own recorded verdict.

The control is the point. Agreement alone is uninterpretable -- 80% could be good or
useless. The GAP between arms is the app's contribution: zero means the app's shaping
adds nothing over the raw card, and negative means the trim is throwing evidence away.

Blinding is the other half, and it is the part that fails silently. Both arms are
redacted, so a judge cannot read the answer off the header, and judges must be fresh
sessions with no prior exposure to this pipeline -- a seat that has read the handoffs
will reproduce the verdict from memory and the test will pass while proving nothing.

Ground truth is the card's own recorded verdict. SENT means it was ruled BUILD and then
sent, so it scores as BUILD. CARDED_UNRULED has no ruling by definition and is excluded;
so is PASS, which is too rare to stratify.

Usage:
  eval_app_sufficiency.py build --feed F --cards-dir D --out O [--n 24] [--seed 7]
  eval_app_sufficiency.py score --out O --judgments J
"""
import argparse, json, os, random, re, sys

TRUTH_MAP = {"SENT": "BUILD", "BUILD": "BUILD", "RADAR": "RADAR", "PARK": "PARK", "DROP": "DROP"}
EXCLUDED = {"CARDED_UNRULED", "PASS"}
VERDICTS = ["BUILD", "RADAR", "PARK", "DROP"]
GLYPHS = "▶○‖✗✓◇"


VERDICT_RE = re.compile(
    r"\b(?:BUILD(?:S|ING)?|RADAR|PARK(?:ED|S|ING)?|DROP(?:PED|S|PING)?|SENT|PREP|CARDED_UNRULED)\b",
    re.IGNORECASE)
FIT_RE = re.compile(r"\b(?:GOOD|STRONG|POOR|WEAK|NO|BAD)\s+FIT\b", re.IGNORECASE)


def redact(text):
    """Strip the answer from BOTH arms, identically, so neither is advantaged.

    Removing the header is not enough, and neither is a case-sensitive mask -- that was the
    second mistake. A scorecard ARGUES to its verdict and then states it, in prose and in any
    case: "card stays RADAR", "this card is parked by his own ruling", "a card that already
    DROPs", "Hold at radar". Blinded judges found every one of those surviving a mask that
    only matched bare uppercase tokens.

    So the match is case-insensitive and covers inflections. That over-masks -- "building a
    product" and "he sent the note" go too -- which degrades readability in both arms equally,
    and a fair comparison is worth more here than prose that reads nicely.

    What it still cannot reach is a card that states its reasoning so completely that the
    verdict follows: "he would not qualify for a federal suitability determination" names a
    DROP without using the word. That is why every card carries a mask count: contamination is
    reported beside the rate rather than discovered afterwards.
    """
    text = re.sub(r"STATUS:\s*[" + GLYPHS + r"]?\s*[A-Z][A-Z_-]{2,}", "STATUS: [redacted]", text)
    text = VERDICT_RE.sub("[VERDICT]", text)
    text = FIT_RE.sub("[FIT]", text)
    text = re.sub(r"[" + GLYPHS + r"]\s*\[VERDICT\]", "[VERDICT]", text)
    return text


def mask_count(text):
    """How many times this document had to have its answer taken out. A contamination proxy:
    a card that discussed its verdict twenty times leaves more to infer than one that never did."""
    return text.count("[VERDICT]") + text.count("[FIT]")


def residual_leaks(text):
    """Verdict tokens that survived the mask. Must be zero; printed loudly when it is not."""
    return VERDICT_RE.findall(text)


def render_app_view(c):
    """Only what the app puts on screen. No verdict, no queue status."""
    L = [f"# {c.get('company','(unknown)')}", ""]
    boss = c.get("boss")
    if isinstance(boss, dict):
        bits = [boss.get("name"), boss.get("title")]
        conf = boss.get("confidence")
        line = " — ".join(b for b in bits if b) or "(none named)"
        boss = line + (f" ({conf})" if conf else "")
    if boss:
        L.append(f"- **Boss:** {boss}")
    if c.get("remote"):
        L.append(f"- **Remote:** {c['remote']}")
    seg = c.get("segment")
    if seg and not VERDICT_RE.fullmatch(str(seg).strip()):
        L.append(f"- **Segment:** {seg}")
    if c.get("age_days") is not None:
        L.append(f"- **Age:** {c['age_days']} days")
    L += ["", "## Panel", ""]
    seats = c.get("panel_seats") or []
    if seats:
        for s in seats:
            why = (s.get("why") or "").strip()
            L.append(f"- **{s.get('name')} {s.get('score')}** — {why or '(no reasoning recorded)'}")
        if c.get("mean") is not None:
            L.append(f"- Mean {c['mean']}")
    else:
        L.append("- Not enough data to show a panel. Seats carry scores with no reasoning behind them.")
    L += ["", "## Gates", ""]
    for g in (c.get("gates") or []):
        why = (g.get("why") or g.get("w") or "").strip()
        L.append(f"- **{g.get('name') or g.get('key')}** — {why or 'UNRESOLVED — nothing recorded.'}")
    src = c.get("sources") or []
    L += ["", "## Sources", ""]
    L += [f"- {s.get('label') or s.get('kind') or 'source'}: {s.get('url') or s.get('note') or ''}".rstrip()
          for s in src] or ["- None recorded."]
    if c.get("owed"):
        L += ["", "## Still owed", "", str(c["owed"])]
    return redact("\n".join(L)) + "\n"


def newest_card(cards_dir, slug):
    hits = sorted(f for f in os.listdir(cards_dir) if f.startswith(slug + "-card-") and f.endswith(".md"))
    return os.path.join(cards_dir, hits[-1]) if hits else None


def build(a):
    feed = json.load(open(a.feed, encoding="utf-8"))
    pool = {}
    for c in feed.get("cards", []):
        v = c.get("verdict")
        if v in EXCLUDED or v not in TRUTH_MAP:
            continue
        pool.setdefault(TRUTH_MAP[v], []).append(c)

    rng = random.Random(a.seed)
    per = max(1, a.n // len(VERDICTS))
    picked = []
    for v in VERDICTS:
        group = pool.get(v, [])
        rng.shuffle(group)
        picked += group[:per]
    if not picked:
        sys.exit("no ruled cards found in the feed")

    app_dir, card_dir = os.path.join(a.out, "arm-app"), os.path.join(a.out, "arm-card")
    for d in (app_dir, card_dir):
        os.makedirs(d, exist_ok=True)

    truth, missing = {}, []
    for c in picked:
        slug = c["slug"]
        truth[slug] = TRUTH_MAP[c["verdict"]]
        open(os.path.join(app_dir, slug + ".md"), "w", encoding="utf-8").write(render_app_view(c))
        src = newest_card(a.cards_dir, slug)
        if src:
            open(os.path.join(card_dir, slug + ".md"), "w", encoding="utf-8").write(
                redact(open(src, encoding="utf-8").read()))
        else:
            missing.append(slug)

    json.dump({"truth": truth, "seed": a.seed, "missing_source_card": missing},
              open(os.path.join(a.out, "truth.json"), "w", encoding="utf-8"), indent=2, sort_keys=True)

    open(os.path.join(a.out, "BRIEF.md"), "w", encoding="utf-8").write(f"""# Judge brief

You are reading the evidence on ONE company. Name the verdict it deserves.

- **BUILD** — worth going after now; act on it.
- **RADAR** — worth knowing about; no action owed.
- **PARK** — hold; something is unresolved.
- **DROP** — not worth pursuing.

Rules:
1. Judge ONLY from the file you were given. Do not open the repo, the ledger, other cards,
   or any session notes. If you have prior context on this pipeline, say so and stop.
2. A gate with nothing recorded is UNRESOLVED, never a pass.
3. Answer as one line of JSON per card: {{"slug": "...", "verdict": "BUILD|RADAR|PARK|DROP", "why": "one sentence"}}

The answer has been redacted from every file; if you can still
see a stated verdict, report it rather than using it -- that is a leak and it invalidates
the run.
""")

    leaks, masks = [], {}
    for d, arm in ((app_dir, "app"), (card_dir, "card")):
        per_card = {}
        for f in sorted(os.listdir(d)):
            t = open(os.path.join(d, f), encoding="utf-8").read()
            per_card[f[:-3]] = mask_count(t)
            if residual_leaks(t):
                leaks.append(f"{arm}/{f}: {sorted(set(x.upper() for x in residual_leaks(t)))}")
        masks[arm] = per_card

    manifest = {"masks_per_card": masks, "seed": a.seed, "n": len(picked)}
    json.dump(manifest, open(os.path.join(a.out, "contamination.json"), "w", encoding="utf-8"),
              indent=2, sort_keys=True)

    print(f"built {len(picked)} cards ({per} per verdict) into {a.out}")
    for arm in ("app", "card"):
        v = list(masks[arm].values())
        worst = max(masks[arm], key=masks[arm].get)
        print(f"  arm-{arm:<5}: {len(v)} files · masks/card mean {sum(v)/len(v):.1f}, "
              f"max {max(v)} ({worst})")
    if missing:
        print(f"  NOTE     : {len(missing)} slugs had no source card")
    print("  LEAKS    : " + ("\n             ".join(leaks) if leaks
                             else "none — no verdict token survives the mask in either arm"))


def score(a):
    truth = json.load(open(os.path.join(a.out, "truth.json"), encoding="utf-8"))["truth"]
    arms = {}
    for line in open(a.judgments, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        arm, slug = r.get("arm", "?"), r.get("slug")
        if slug not in truth:
            continue
        hit, tot = arms.setdefault(arm, [0, 0])
        arms[arm] = [hit + (1 if r.get("verdict") == truth[slug] else 0), tot + 1]

    print("arm        agree   n    rate")
    for arm in sorted(arms):
        hit, tot = arms[arm]
        print(f"{arm:<10} {hit:>5}  {tot:>3}   {hit/tot:.0%}" if tot else f"{arm:<10}  no rows")
    if {"app", "card"} <= set(arms):
        ha, ta = arms["app"]; hc, tc = arms["card"]
        if ta and tc:
            gap = ha/ta - hc/tc
            print(f"\ngap (app − card): {gap:+.0%}")
            print("  " + ("the app's shaping costs agreement — the trim is dropping evidence" if gap < -0.05
                          else "the app's shaping adds nothing over the raw card" if gap < 0.05
                          else "the app's shaping helps"))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.set_defaults(fn=build)
    b.add_argument("--feed", required=True); b.add_argument("--cards-dir", required=True)
    b.add_argument("--out", required=True); b.add_argument("--n", type=int, default=24)
    b.add_argument("--seed", type=int, default=7)
    s = sub.add_parser("score"); s.set_defaults(fn=score)
    s.add_argument("--out", required=True); s.add_argument("--judgments", required=True)
    a = p.parse_args(); a.fn(a)
