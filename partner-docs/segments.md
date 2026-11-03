# Your search segments — the hot-zone vocabulary (SCAFFOLD — fill this in)

> This is a TEMPLATE. Define YOUR lanes here, then encode them in `scripts/kit_config.py` (`SEGMENTS`).
> `mail-draft.sh` validates `--segment` against those slugs and refuses a free-text value;
> `sweep_segments.sh` reads them to run discovery.

## Why segments are a CLOSED list (Andy LaCivita's hot-zone method)

Andy's rule: send **~5 outreach per segment**, then **compare reply rates** across segments to find your
hot zone — "your focus is on data, not interviews." That only works if a segment is a stable, named lane.
The failure mode to avoid: free-text labels. If nine sends go out under five slightly-different labels that
are really *one* lane, the spread check sees five segments and never warns, and you can never compare. So
the vocabulary is CLOSED: a fixed handful of slugs, defined once, here and in `kit_config.py`.

## The bar to add a segment

Each segment must be backed by **something on YOUR verifiable record** that a stranger could check — a
shipped product, a funded outcome, a domain you actually worked. A lane that only shows up because a
discovery sweep surfaced it is a **finding, not a segment**. Three to five segments is plenty.

## Define yours

Replace the generic `segment-a / segment-b / segment-c` in `kit_config.py` with your real lanes. For each:

| Slug (kit_config key) | Segment (what it is) | The proof YOU own (a stranger can check) |
|---|---|---|
| `your-slug-1` | *(e.g. payments / money movement)* | *(the shipped thing on your résumé that backs it)* |
| `your-slug-2` | *(e.g. applied AI where being wrong is expensive)* | *(...)* |
| `your-slug-3` | *(e.g. a regulated domain you worked)* | *(...)* |

Then set the SWEEP QUERIES for each slug in `kit_config.py` `SEGMENTS` — the search phrases
`sweep_segments.sh` runs (titles + adjacent vocabulary + seniority variants for your band).

## Straddle rule

A company that fits two segments gets **exactly one** label — the one you'd LEAD the outreach email with —
or your reply-rate denominators stop meaning anything.

## Non-segment values

- Warm / referred / follow-up / thank-you outreach carries an **empty** segment (chosen by relationship,
  not by lane).
- The segment gate applies to **cold** boss-hunt / stranger sends only, where the hot-zone comparison lives.
