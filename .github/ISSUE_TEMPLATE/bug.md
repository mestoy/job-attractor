---
name: Bug
about: A shipped script errors, two rules contradict each other, or a referenced file is missing
title: "[bug] "
labels: needs-triage
---

- [ ] **kind**: script-error | rule-contradiction | missing-file | other
- [ ] **surface**: the file or script involved
- [ ] **expected**: one line, what should have happened
- [ ] **observed**: the verbatim error or behavior (scrub any absolute path to `~/`)
- [ ] **repro**: the command that triggers it

Do not include your own data, preferences, or anything specific to one job
search. This is for defects in the shipped kit only.
