# Best PM Jobs URL Reference

Public, unauthenticated pages on [bestpmjobs.com](https://www.bestpmjobs.com), a
product-management-specific job board built on the "JobBoardly" white-label platform.

> Personal use only — keep volume low. `robots.txt` allows all paths (`Allow: /`).

## Search

```
GET https://www.bestpmjobs.com/jobs
```

Query params (from the page's own GET search form, `<form action="/jobs" method="get">`):

| Param | Meaning | Example |
|-------|---------|---------|
| `q` | Free-text query (title, company, etc.) | `product manager` |
| `place` | Free-text location filter | `United States`, `Remote` |
| `remote` | Remote-only filter | `true` |
| `page` | 1-indexed page | `2` |
| `salary_min` / `salary_max` | Salary range filter (not exposed by this CLI) | `150000` |
| `category_id[]` / `type[]` | Category / employment-type filters (not exposed by this CLI) | — |

Returns server-rendered HTML with **no JSON-LD** — a flat list of job cards, each an
`<a class="block rounded-xl border" href="/jobs/<slug>">` wrapping:
- `<h3>` — title
- the following `<p>` — company name
- a `text-xs font-medium` badge `<p>` — employment type (e.g. `Full-time`)
- a `<span class="truncate">` following the location-pin SVG — location text (e.g.
  `Remote`, or a city)

No posting date appears on this page — only `detail` resolves it.

The CLI parses each card by splitting on
`<a class="block rounded-xl border"` and extracting fields independently per chunk, so
one malformed card cannot break the rest.

## Detail

```
GET https://www.bestpmjobs.com/jobs/<slug>
```

`<slug>` is the trailing path segment (e.g. `staff-product-manager-9870498c`). The page
embeds a full `schema.org JobPosting` in a `<script type="application/ld+json">` block:

| JSON-LD field | Maps to |
|---------------|---------|
| `title` | title |
| `description` | HTML description (decoded/cleaned to plain text with paragraph breaks) |
| `datePosted` | posted date |
| `validThrough` | closing date |
| `employmentType` | e.g. `FULL_TIME` |
| `hiringOrganization.name` | company |
| `jobLocationType` | `TELECOMMUTE` → remote |
| `applicantLocationRequirements[].name` | eligible countries, appended to a `Remote (...)` location string |
| `jobLocation.address` | city/region/country, for non-remote roles |

The CLI also extracts the site's own tracked apply link separately from the JSON-LD, via
`id="apply-btn"` on the page's "Apply now" button — this is the real external ATS URL
(Ashby/Greenhouse/Lever/etc.) rather than a link back to the Best PM Jobs page itself.

## Notes

- No authentication required.
- Respect rate limits — the CLI backs off on 429/5xx, same as the other portal skills.
- The site shows a marketing "subscribe for early access" popup/sticky-bar to browsers;
  this is not an access wall and does not affect the public HTML/JSON-LD content.
- Built on the "JobBoardly" platform (`assets.jobboardly.com`, `gid://job-boardly/...`
  identifiers visible in page metadata) — worth checking if other niche PM/tech job
  boards share this exact markup before writing a new parser from scratch.
