# Contributing

This is the public snapshot of the Job Attractor kit
(github.com/mestoy/job-attractor). It is published from a private lineage
through a PII gate and an export-ignore list, so a pull request opened here
cannot be merged straight back into that lineage. The maintainer reviews it,
merges it here, then cherry-picks it upstream and republishes. See "What
happens to your PR" below for the full path.

## Where to file

Open an issue on this repo.

- Use the **bug** template for a shipped script that errors, two rules that
  contradict each other, or a file a script or doc points at that the kit
  never shipped.
- Use the **enhancement** template for an idea: a gap the kit does not cover
  yet, or a change to how something generic works.

What does NOT belong here: your own data, your own preferences, or anything
specific to one job search. This kit reads every person-specific value from
`documents/` and `scripts/kit_config.py`, both git-ignored. An issue that
only makes sense with your résumé, your target companies, or your screening
criteria attached is not something the maintainer can act on generically.
Keep issues about the tooling, not about a search.

## What a good issue carries

The same fields the kit's own feedback protocol asks for:

- **kind**, script-error, rule-contradiction, missing-file, or other
- **surface**, the file or script involved
- **expected**, one line, what should have happened
- **observed**, the verbatim error or behavior, with any path scrubbed to
  `~/` (never paste an absolute home-directory path)
- **repro**, the command that triggers it

Both templates prompt for these fields directly.

## Pull requests

1. Fork the repo and branch from `main`.
2. Edit only files outside `documents/`. That folder does not exist in this
   snapshot for a reason: it is where a real job search's data lives, and it
   never belongs in a diff.
3. Keep `scripts/kit_config.py` out of the diff. Only `scripts/kit_config.example.py`
   ships here; if your local copy of the real file exists, make sure your
   editor and `git add` never pick it up.
4. Run `bash tests/run_all.sh` before you open the PR, and paste its last
   line into the PR description.
5. No personal data or real names anywhere in the diff: not in code, not in
   comments, not in fixtures, not in the commit message.
6. One change per PR. A PR that mixes a bug fix with an unrelated cleanup is
   harder to review and harder to cherry-pick.

## What happens to your PR

Opening it runs the Actions check, which is `bash tests/run_all.sh` on a
clean checkout. The maintainer reviews PRs in a daily pass, not
continuously, so expect a reply within a week rather than immediately.

If it is merged here, the maintainer cherry-picks it into the private
lineage, runs it through the PII gate, and includes it in the next published
snapshot. Because of that extra hop, the public history you see later may
not show your original commit hash, the content lands through a
cherry-pick rather than a fast-forward. Your name stays on the commit as its
author either way.

## Reading a failed check

The Actions log for a failing PR shows which test failed by name. If the
fingerprint guard fires instead of (or alongside) a test failure, it means a
test wrote into one of the kit's live data files during the run. That is
always the test's isolation bug, not a problem with your change or your
data, fix how the test isolates itself rather than touching the guard or
the data it flagged. You can reproduce the same check locally with
`bash tests/run_all.sh`.

## macOS notes

A few scripts are macOS-only: `scripts/mail-draft.sh` shells out to
`osascript`, and the `.command` launchers are double-click wrappers for
Finder. A Linux contributor can still run everything else, including the
full test suite, `install.sh`, and every script that does not touch Mail.app
or Finder directly.

## Labels

- **partner-feedback**, filed through the kit's own feedback protocol
  rather than opened by hand; same fields, different origin.
- **needs-triage**, new, not yet reviewed by the maintainer.
- **wontfix-private**, the behavior is intentional for the maintainer's own
  private lineage and will not change in the public kit.
