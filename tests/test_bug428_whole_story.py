#!/usr/bin/env python3
"""RETIRED (BUG-549). This file used to drive the real, already-published V46.1 candidate page
(/home/vscode/render/v461-candidate/app/design/job-attractor-app.html) with pytest + Playwright,
picking its card by SHAPE (carries `seats`, a 3-row CPO/CTO/CEO `panel`, no `panel_seats`) rather
than a real slug, because that shape was how the original BUG-428 report identified the Quorble
card on that one build.

Both legs of that setup are gone: the candidate page no longer exists, so every test here always
skipped; and even without that, the shape it matched is now 0 of 101 real cards (`panel_seats`
replaced the 3-row panel after the Designer-replaces-CEO ruling, 2026-09-19, which this file's own
`test_the_cards_data_shape_is_recorded` was written to notice and did not, because it never ran).
It also imported `pytest`, which is not installed here, so `unittest discover` (tests/run_all.sh)
could not even skip it -- loading the module raised, and that import error is what BUG-549 is.

WHAT BUG-428 WAS, for the record (this is the content worth keeping, so it is kept here rather
than re-derived from a comment elsewhere): the owner reported that "See the whole story" on a card
did not display the scorecard. A run against the real V46.1 page found it worked in Cards and
Terminal (#right opened with real content, both viewport sizes, no console errors), and failed
only in Constellation, where the scorecard's content landed inside #right but #right itself stayed
invisible (zero-size / display:none). That is BUG-426's own symptom, reached through Constellation,
not a separate defect -- BUG-428 and BUG-426 are the same bug.

WHERE THE GUARD LIVES NOW, AND WHAT IT SAYS TODAY. tests/test_bug426_constellation_scorecard.py
builds app2.py fresh against the bundled example feed (current source, current shape, no pinned
artifact to go stale) and checks that "See the whole story" shows the scorecard in every
adventure (Cards, Terminal, Constellation) at both sizes. It does NOT prove that today: its two
Constellation cases, test_constellation_desktop and test_constellation_phone, are RED ("See the
whole story" is not reachable there), and BUG-426 stays open. Cards and Terminal are the cases
that pass. tests/test_bug503_story_door_shows_full_scorecard.py covers the full scorecard on the
same door (it guards a later, unrelated regression, a shadowed `expanded` variable), likewise on
the current source and fixture.

This file is kept, emptied of its pytest/live-page dependency, as the record of what BUG-428 was
and where its guard lives (and that the Constellation half of that guard is still red) -- not as a test that runs anything.
"""
