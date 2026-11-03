"""_import_sibling() (screen_sweep.py, employers.py, registry_equivalence.py,
build_employer_notes.py, seed_employers.py, state.py -- six identical copies) registered the
half-built module in sys.modules BEFORE calling exec_module(). When exec_module then failed
(the sibling file is missing, or exists with a syntax error), the empty, never-executed module
object stayed cached in sys.modules under the bare name forever. Every LATER `from <name> import
X` anywhere else in the process then hit that same poisoned stub and raised AttributeError,
instead of the clean ModuleNotFoundError/ImportError every caller's own try/except is written to
expect and recover from.

Root-cause investigation: this is why 15 of tests/test_gates.py's tests fail identically on
kit main (a6dd8b13) and the app lineage (acb4f6e) -- scripts/kit_config.py is gitignored by
design (seeded by install.sh) and absent from a bare checkout, and _import_sibling("kit_config")
poisons sys.modules the moment ANYTHING imports screen_sweep.py, before any test runs.

Parametrized over the six modules that carry this exact copy-pasted helper. reconcile_findings.py
carries a SEVENTH "_import_sibling", but it's a degenerate fallback stub (unconditionally raises
ImportError, touches neither exec_module nor sys.modules) used only when screen_sweep itself
can't be imported -- a different shape, not this bug, not included here.
"""
import importlib.util
import os
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")

MODULES = [
    "screen_sweep",
    "employers",
    "registry_equivalence",
    "build_employer_notes",
    "seed_employers",
    "state",
]


def _load(modname):
    """Import a scripts/ module fresh, immune to whatever earlier tests left in sys.modules.
    Caller is responsible for restoring sys.modules[modname] afterward (see _clean) -- this
    process runs the WHOLE suite in one interpreter, and every other test file that already did
    a normal `import <modname>` holds a reference expecting sys.modules to keep matching it."""
    spec = importlib.util.spec_from_file_location(modname, os.path.join(SCRIPTS, modname + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ImportSiblingNeverLeavesAPoisonedStub(unittest.TestCase):
    def setUp(self):
        global SCRIPTS
        # This test loads copies of scripts/ modules and pops names from sys.modules; the whole suite shares one interpreter, so put sys.modules back EXACTLY
        # as it was (other tests call importlib.reload on modules like employers and findings_ledger).
        saved = dict(sys.modules)

        def _restore_modules():
            for k in [k for k in sys.modules if k not in saved]:
                del sys.modules[k]
            sys.modules.update(saved)
        self.addCleanup(_restore_modules)
        real = SCRIPTS
        if os.path.exists(os.path.join(real, "kit_config.py")):
            # tests/run_all.sh seeds kit_config.py from the example on a clean clone, so a full run never has it absent, and the case under test IS
            # its absence. Run against a COPY of scripts/ without that one file (same sibling modules, so the real import paths are exercised).
            tmp = tempfile.mkdtemp(prefix="sibling-noconfig-")
            self.addCleanup(shutil.rmtree, tmp, True)
            scripts_copy = os.path.join(tmp, "scripts")
            shutil.copytree(real, scripts_copy, ignore=shutil.ignore_patterns("kit_config.py", "__pycache__", "*.pyc"))
            SCRIPTS = scripts_copy
            self.addCleanup(lambda: globals().__setitem__("SCRIPTS", real))
            # Other tests in the same interpreter put the REAL scripts/ on sys.path, where kit_config.py would still be importable: take it off for this test.
            saved_path = list(sys.path)
            sys.path[:] = [q for q in sys.path if os.path.abspath(q or ".") != os.path.abspath(real)]
            self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved_path))
        sys.path.insert(0, SCRIPTS)
        self.addCleanup(lambda: sys.path.remove(SCRIPTS) if SCRIPTS in sys.path else None)

    def _clean(self, modname):
        """Remove modname from sys.modules for the duration of one call, then put back
        EXACTLY whatever was there before -- never a bare pop-and-forget, which would leave
        the six real modules (employers, screen_sweep, ...) missing from sys.modules for every
        later test file in this same pytest process that already imported them normally and
        expects `importlib.reload()` to keep working against that same object."""
        prior = sys.modules.pop(modname, None)
        if prior is not None:
            self.addCleanup(sys.modules.__setitem__, modname, prior)
        else:
            self.addCleanup(sys.modules.pop, modname, None)

    def test_a_missing_sibling_never_poisons_a_later_real_import(self):
        # kit_config.py IS genuinely absent from this checkout (gitignored, seeded by
        # install.sh) -- the exact real-world case, not a fabricated one.
        self.assertFalse(os.path.exists(os.path.join(SCRIPTS, "kit_config.py")), "this test needs kit_config.py absent to exercise the real case")
        for modname in MODULES:
            with self.subTest(module=modname):
                # Loading the module itself may ALREADY call _import_sibling("kit_config") at
                # its own top level (screen_sweep.py does, in a try/except) -- that is the real
                # trigger path this bug was found through. Reset afterward so THIS call is the
                # one under direct test, isolated from that side effect.
                self._clean("kit_config")
                mod = _load(modname)
                self._clean("kit_config")
                with self.assertRaises((FileNotFoundError, ImportError)):
                    mod._import_sibling("kit_config")
                # THE ACTUAL BEHAVIORAL GUARANTEE: a later, ordinary import of the same bare
                # name must fail cleanly -- never AttributeError from a cached empty stub.
                # NOTE: a `from kit_config import OWNER_FIRST` STATEMENT would not catch this --
                # Python's own bytecode for that form wraps an AttributeError from a partially
                # initialized module into ImportError automatically. The real failure this bug
                # produces (test_gates.py's own `_first_segment_slug()`/`_write_body()`) reads the
                # attribute off an already-imported module object, exactly reproduced here.
                sys.path.insert(0, SCRIPTS)
                try:
                    with self.assertRaises((ModuleNotFoundError, ImportError)):
                        kc = importlib.import_module("kit_config")
                        kc.OWNER_FIRST
                finally:
                    sys.path.remove(SCRIPTS)

    def test_b_a_syntax_error_sibling_surfaces_loudly_and_leaves_no_stub(self):
        broken = os.path.join(SCRIPTS, "ja_test_broken_sibling_fixture.py")
        with open(broken, "w", encoding="utf-8") as fh:
            fh.write("this is not python (\n")
        self.addCleanup(lambda: os.path.exists(broken) and os.remove(broken))
        for modname in MODULES:
            with self.subTest(module=modname):
                self._clean("ja_test_broken_sibling_fixture")
                mod = _load(modname)
                with self.assertRaises(SyntaxError):
                    mod._import_sibling("ja_test_broken_sibling_fixture")
                self.assertTrue(
                    "ja_test_broken_sibling_fixture" not in sys.modules,
                    f"{modname}._import_sibling left a stub behind after a SyntaxError")


if __name__ == "__main__":
    unittest.main()
