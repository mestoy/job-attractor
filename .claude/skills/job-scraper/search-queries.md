# Search Queries for Job Scraper

**Candidate:** _[fill in a one-line summary — target roles, remote/location constraint, and top deal-breakers. See `documents/PROFILE.md` and `.claude/skills/job-application-assistant/04-job-evaluation.md` for the full profile.]_

## Search Sites

The kit ships CLI search skills for several US-facing job sources (used first, in parallel):

- **linkedin-search** — LinkedIn public job listings (`--location "<City, State>"` or `"Remote"`).
- **builtin-search** — Built In (builtin.com), US tech & startup roles (national + remote).
- **wttj-search** — Welcome to the Jungle (welcometothejungle.com), US roles.
- **hiring-cafe-search** — Hiring Cafe (hiring.cafe), US ATS-aggregated roles. **Note:** a raw `hiring.cafe/jobs/<id>` URL is JavaScript-rendered and unfetchable via WebFetch or curl — both return only the generic search interface, never the posting text. To re-fetch a hiring.cafe posting, use `bun run .agents/skills/hiring-cafe-search/cli/src/cli.ts detail <id>` (the `id` is returned in the original `search` result), not WebFetch on the URL.
- **bestpmjobs-search** — a PM-specific job board (national + remote). *(Swap or add boards for your field via `/add-portal`.)*

WebSearch sources (no CLI):

- **wellfound.com** (startups — small/early-stage orgs are in scope), **indeed.com**, **glassdoor.com** (jobs + reviews/salaries), **dice.com**, and company career pages via `site:` WebSearch.
- **greenhouse.io** and **ashbyhq.com** direct — `site:job-boards.greenhouse.io` / `site:jobs.ashbyhq.com` WebSearch surfaces company career pages hosted on these ATSes (recovers postings hiring-cafe's detail pages often can't reach).
- **Google Jobs** — a plain WebSearch without a `site:` restriction surfaces Google's Jobs carousel as a general-net supplement.

## Query recipes (customize these to your search)

Define a handful of query "lanes" that match your target roles and sectors. For each lane, list the CLI invocations and `site:` WebSearch strings. A generic pattern:

```
# CLI examples (remote-only by default; adjust flags per each CLI's SKILL.md)
bun run .agents/skills/linkedin-search/cli/src/cli.ts search "[JOB_TITLE]" --location "Remote"
bun run .agents/skills/builtin-search/cli/src/cli.ts search "[JOB_TITLE]" --remote

# WebSearch site: recipes
site:job-boards.greenhouse.io  [JOB_TITLE] remote
site:jobs.ashbyhq.com          [JOB_TITLE] remote
site:glassdoor.com             [JOB_TITLE] jobs remote
[JOB_TITLE] remote              # plain query → Google Jobs carousel
```

Guidance:
- **Cast a reasonable net on title level** — include the adjacent titles you'd genuinely take (e.g. Senior / Staff / Principal / Lead / Director if applicable), not just one exact string.
- **Encode your hard filters** in the queries where the CLI supports it (e.g. remote-only), and enforce the rest at ranking time.
- **Keep batches small:** find ~10 postings, `/rank` them, then find ~10 more — don't scrape hundreds before ranking.
- Add new lanes as your search focus evolves; date-stamp additions so you remember why you added them.
