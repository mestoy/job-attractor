# Public PR ingestion, pulling a merged public PR into the kit lineage

The public repo (github.com/mestoy/job-attractor) is a sanitized snapshot
published FROM the kit lineage through the PII gate and `.gitattributes`
export-ignore. It is not a source the kit lineage branches from. Traffic
only ever flows kit → public through `publish-public.sh`; this doc is the
one path that moves content the other way, and it goes through review, not
through git history directly.

## The trap

Never rebase or merge the public repo's `main` onto the kit branch, and
never treat the public repo as upstream of the kit. The public repo is a
product of the kit, not a source for it. Pull only the specific commits a
reviewed PR added, never the branch.

## Steps

1. **Review the PR on the public repo.** Read the diff, confirm it touches
   nothing under `documents/`, and confirm `scripts/kit_config.py` is not in
   it.
2. **Run its tests there.** The Actions check already ran `bash
   tests/run_all.sh` on the PR; re-run it locally against the PR branch if
   anything is unclear.
3. **Merge it on the public repo.** Use the normal GitHub merge, so the
   public repo's own history stays accurate.
4. **Fetch the public repo as a remote into the kit checkout.**
   ```
   cd <kit-checkout>
   git remote add public https://github.com/mestoy/job-attractor.git   # once
   git fetch public
   ```
5. **Cherry-pick onto the kit branch.** Pick the merge commit (or the
   individual commits if the PR was squashed differently) onto the branch
   you publish from:
   ```
   git checkout <kit-branch>
   git cherry-pick -m 1 <public-merge-commit-sha>
   # or, for a squashed PR: git cherry-pick <public-commit-sha>
   ```
6. **Run the PII gate.**
   ```
   python3 scripts/pii_gate.py --scan .
   ```
7. **Run the kit's own tests.**
   ```
   bash tests/run_all.sh
   ```
8. **Push the kit.**
   ```
   git push origin <kit-branch>
   ```
9. **Republish the public snapshot** through the existing publish script
   (`publish-public.sh`), the same path every other kit change goes through.
10. **Close the loop.** Comment on the original public PR naming the
    snapshot commit it landed in, so the contributor can see where their
    change ended up even though the commit hash on the public side changed.
