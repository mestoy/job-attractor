"""BUG-736: one shared seed for `kit_config`, so a bare checkout can never drop a test class.

scripts/kit_config.py is gitignored (install.sh seeds it from kit_config.example.py), so a fresh
worktree has only the example. A test file that does `import kit_config` then fails to IMPORT, and
a run reports the same count as its baseline while whole classes never executed (an empty check
passing). Import this module FIRST in any test file that imports kit_config, directly or through a
script. It executes the example into a module object registered as `kit_config` for this process
only and never writes a file into the tree. A real scripts/kit_config.py, when present, wins.
tests/conftest.py calls the same seed, so pytest and plain unittest runs behave alike.
"""
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(os.path.dirname(_HERE), "scripts")


def seed():
    """Register `kit_config` in sys.modules from the example when no real config exists."""
    if "kit_config" in sys.modules:
        return sys.modules["kit_config"]
    real = os.path.join(_SCRIPTS, "kit_config.py")
    example = os.path.join(_SCRIPTS, "kit_config.example.py")
    # BUG736_HIDE_REAL_KIT_CONFIG=1 (set by the import guard) makes an installed tree behave bare.
    hide = os.environ.get("BUG736_HIDE_REAL_KIT_CONFIG") == "1"
    if (os.path.isfile(real) and not hide) or not os.path.isfile(example):
        return None  # a real config loads the normal way; no example means nothing to seed from
    mod = types.ModuleType("kit_config")
    # _import_sibling("kit_config") checks its cache against this path, so it treats the seeded
    # module as already loaded instead of retrying a load of a file that does not exist.
    mod.__file__ = real
    with open(example, encoding="utf-8") as fh:
        exec(compile(fh.read(), example, "exec"), mod.__dict__)
    sys.modules["kit_config"] = mod
    return mod


seed()
