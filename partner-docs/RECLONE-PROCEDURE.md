# Reclone procedure: rebasing your install onto the kit's history

⛔ **Written 2026-08-10 because it did not exist** (kit issue #20). A partner recloned their install
on 2026-08-09, ended up with two diverged lineages, and found that a force-push would destroy ten
files the old remote alone still held. They asked what the sanctioned reconcile was. There was
no answer to give them: the only instruction anywhere was a note in a session handoff. This file is
that missing answer, written from what their reconcile needed.

## What a reclone is for, and when you need one

A reclone gives your `main` a **shared history with `kit/main`**, so `git merge kit/main` applies
cleanly instead of conflicting on every file. You need one when your install was created by copying
files rather than cloning, or when history has diverged far enough that merges stop being useful.

⚖️ **It solves a MERGE problem and creates a REMOTE problem.** After the reclone your local `main`
shares history with the kit and no longer shares history with your own `origin`. Those two lineages
have no merge base. Nothing about that is wrong; it has to be finished deliberately.

## ⛔ The one thing that makes this dangerous

**A reclone brings the KIT's files. It does not bring YOURS.** Anything you generated that lives
outside the kit's tree is not in the kit's history and therefore not in the reclone:

- `.agents/skills/<name>/`, every portal you added with `/add-portal`
- `.claude/commands/*.md` you wrote yourself
- anything else you created that the kit never shipped

On the install that prompted this file, that was **two job-board portals**, `dice-search` and
`indeed-search`. `install.sh` afterwards reported five portals installed and had no idea two were
missing, because it counted what it found rather than comparing against what had been there. That
count is now a baseline comparison, so a shrink is reported, but **it reports the loss, it cannot
undo it.**

---

## The procedure

### 1. Inventory what is yours, BEFORE anything

```
ls -1 .agents/skills/ > /tmp/portals-before.txt
git ls-files '.claude/commands/*' > /tmp/commands-before.txt
cat /tmp/portals-before.txt
```

Write the portal list down somewhere outside the repo. This is the list you will check against
afterward, and it is the only record that survives if something goes wrong.

### 2. Reclone

Clone the kit fresh, then bring your working files across. Your `documents/` directory is
git-ignored and holds your private data, so it moves by copy rather than by git.

### 3. Point the new clone at your own remote

```
git remote add origin <your private fork>
git fetch origin
```

⛔ **Do not push yet.** At this moment your local `main` and `origin/main` have diverged with no
merge base, and the next command you are tempted to run is the destructive one.

### 4. Recover what only the old lineage has, and do it BEFORE the push

This is the step that was missing, and it is what makes the rest safe.

```
git diff --stat main origin/main            # what differs at all
git diff --name-only main origin/main       # every path
```

For each path that exists on `origin` and not locally, decide whether it is yours. Then bring the
ones that are back onto the current lineage:

```
git checkout origin/main -- .agents/skills/<your-portal> .claude/commands/<your-command>
git status                                   # confirm nothing unexpected came along
git commit -m "recover operator-generated files from the pre-reclone lineage"
```

⚠️ **Expect false alarms in that diff, and check before acting.** Files that are now git-ignored
(your `kit_config.py`, your `documents/` copies) show as missing from the local tree while sitting
on disk perfectly fine. A file being in the diff does not mean it is gone.

### 5. Preserve the old lineage, then push

```
git push origin origin/main:refs/heads/pre-reclone-lineage-$(date +%Y-%m-%d)
git push --force-with-lease origin main
```

⚖️ **The branch is the whole safety net and it costs one ref.** It makes an irreversible operation
reversible. The kit has no opinion about how long you keep it; delete it when you stop being nervous.

⛔ `--force-with-lease`, never a bare `--force`. It refuses if the remote moved since your last
fetch, which is the case where someone else's work is about to disappear.

### 6. Verify, against the list from step 1

```
ls -1 .agents/skills/ > /tmp/portals-after.txt
diff /tmp/portals-before.txt /tmp/portals-after.txt && echo "portal coverage intact"
git diff --name-only main origin/main        # should be empty
bash install.sh                              # reports a portal shrink if one happened
```

The last two are the real check. **An empty diff against `origin/main` is what "nothing unique is
stranded" looks like**, and it is worth reading with your own eyes rather than assuming.

---

## What the kit does and does not do for you

| | |
|---|---|
| **Reports a portal shrink** | `install.sh`, against a stored baseline. Only from the second run onward, because the first run has nothing to compare |
| **Refuses to guess** | It never merges, restores or deletes your files. They are yours and only you know which copy you meant |
| **Cannot recover** | Operator-generated files are not in the kit's history. If both your remote and your working tree lose them, they are gone |

⭐ **The lesson worth carrying past this procedure.** The reclone was not the risky part; it worked.
The risk was a step nobody had written down, so it got improvised from a session note, and what
caught it was a partner running a diff by hand before typing a destructive command. If you find yourself about to force-push and you have not run step 4, stop and run step 4.
