"""Seeds a working `kit_config` module into sys.modules before test collection.

scripts/kit_config.py is gitignored by design (seeded by install.sh from kit_config.example.py),
so it's absent on a bare checkout -- exactly this one. Before kit#test_gates-15's poisoning fix
(fix/import-sibling-poisoning), several test files only ever collected because _import_sibling()
accidentally left a poisoned-but-present empty stub in sys.modules['kit_config'] the moment
ANYTHING imported screen_sweep.py first. Closing that poisoning correctly means these files'
own bare `import kit_config` now fails cleanly, and they can no longer even collect:
test_kf2_contactcard.py, test_new_card.py, test_panel_seats.py, test_resolve_employers.py,
test_ships_mechanism_not_values.py (56 tests total).

This seeds the SAME real default values kit_config.example.py ships (executed into a fresh
module object, not a bare empty stub), keyed with __file__ pointing at the exact path
_import_sibling() checks its cache against (scripts/kit_config.py) so its early-return guard
treats this as the already-loaded module and never re-attempts a load of a file that still,
genuinely, does not exist on disk.

Does NOT mask the missing-file case tests/test_import_sibling_no_poisoning.py exists to prove:
that file's own tests explicitly `sys.modules.pop("kit_config", None)` before each assertion,
recreating the true bare-checkout condition for the one call under test, and restore whatever
was here (this seeded module) afterward -- the same save-and-restore contract that test file's
own `_clean()` helper already carries.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _kit_config_shim  # noqa: E402,F401  BUG-736: the shared seed (see that module)


import pytest

# BUG-684: browser skips are loud (and failures under REQUIRE_BROWSERS=1); the hooks live in tests/_browser_skip_plugin.py.
from _browser_skip_plugin import pytest_runtest_makereport, pytest_make_collect_report, pytest_terminal_summary  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _restore_jobsearch_data_root():
    """kit #156: scripts resolve their stores from their own install unless JOBSEARCH_DATA_ROOT is set.
    Test fixtures that point a script at a temp tree set it next to CLAUDE_PROJECT_DIR; whatever they set
    is put back after each test so it cannot redirect the next one."""
    before = os.environ.get("JOBSEARCH_DATA_ROOT")
    yield
    if before is None:
        os.environ.pop("JOBSEARCH_DATA_ROOT", None)
    else:
        os.environ["JOBSEARCH_DATA_ROOT"] = before
