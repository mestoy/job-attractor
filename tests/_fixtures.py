#!/usr/bin/env python3
"""Shared test fixture: give any test a working kit_config without touching scripts/ for real.

kit issue #137 follow-on. `scripts/kit_config.py` is git-ignored on purpose (it holds one
partner's values; install.sh seeds it from `scripts/kit_config.example.py` on first run) — so a
fresh clone or worktree that never ran install.sh has no such file. Three failure shapes showed
up from that single gap:

  1. tests/test_doctor_app_prereqs.py `shutil.copy`'d the real scripts/kit_config.py into a
     sandbox tree and raised FileNotFoundError before the sandbox even existed.
  2. tests/test_phase_onboard.py loaded scripts/kit_config.py by path directly (same error).
  3. tests/test_gates.py bare-`import kit_config`s (SCRIPTS is on sys.path) raised
     ModuleNotFoundError -- and worse, `scripts/screen_sweep.py._import_sibling()` REGISTERS an
     empty module object into `sys.modules["kit_config"]` *before* it executes the file, so once
     one such import fails, every later bare `import kit_config` in the same process silently
     reuses that empty stub instead of raising -- 39 tests read `AttributeError: module
     'kit_config' has no attribute ...` instead of the real, single root cause.

Every helper below reads scripts/kit_config.py when a partner has installed one and otherwise
falls back to the tracked scripts/kit_config.example.py -- the same file install.sh itself copies
from. None of them ever write scripts/kit_config.py, and none of them touch it if it is already
there: a partner's real, filled-in config is never read as a fixture and never overwritten.
"""
import importlib.util
import os
import shutil
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(KIT, "scripts")
REAL_KIT_CONFIG = os.path.join(SCRIPTS, "kit_config.py")
EXAMPLE_KIT_CONFIG = os.path.join(SCRIPTS, "kit_config.example.py")


def real_or_example_kit_config_path():
    """Path to whichever kit_config source exists on disk right now: the partner's real
    scripts/kit_config.py when present (read-only, never touched), else the tracked
    scripts/kit_config.example.py that install.sh itself seeds a fresh config from. Never
    creates, writes, or copies anything -- callers do that, if they need to, from this path."""
    if os.path.isfile(REAL_KIT_CONFIG):
        return REAL_KIT_CONFIG
    if os.path.isfile(EXAMPLE_KIT_CONFIG):
        return EXAMPLE_KIT_CONFIG
    raise FileNotFoundError(
        "neither scripts/kit_config.py nor scripts/kit_config.example.py ships in scripts/")


def kit_config_source():
    """Text of whichever kit_config source exists (see real_or_example_kit_config_path)."""
    with open(real_or_example_kit_config_path(), encoding="utf-8") as fh:
        return fh.read()


def copied_kit_config(dest_dir):
    """Copy a REAL kit_config.py into <dest_dir>/scripts/kit_config.py, for tests that build a
    throwaway sandbox tree and need a physical file there (e.g. test_doctor_app_prereqs.py's
    subprocess sandbox). Copies from the partner's real config when one exists, else from the
    tracked example. Creates <dest_dir>/scripts/ if needed. Never writes into THIS repo's own
    scripts/ folder -- only into the caller-supplied, already-throwaway dest_dir."""
    dst_scripts = os.path.join(dest_dir, "scripts")
    os.makedirs(dst_scripts, exist_ok=True)
    dst = os.path.join(dst_scripts, "kit_config.py")
    shutil.copy(real_or_example_kit_config_path(), dst)
    return dst


def ensure_kit_config():
    """Make a bare `import kit_config` (with SCRIPTS already on sys.path) resolve in THIS
    process, without ever writing scripts/kit_config.py.

    When the real file is already there, this is a no-op -- the ordinary import machinery
    already finds it, and nothing here may touch it. When it is absent, this loads
    kit_config.example.py's source under the module name "kit_config", with `__file__` pinned
    to the path a real kit_config.py would occupy. That second detail matters:
    scripts/screen_sweep.py's own `_import_sibling()` helper treats a `sys.modules["kit_config"]`
    entry as trustworthy only when its `__file__` matches that exact path, and reloads (and, on
    FileNotFoundError, poisons) the cache otherwise. Pinning it here means screen_sweep's own
    self-heal check finds a match and reuses this fixture instead of re-attempting a real load
    that would fail and cache an empty stub -- the actual mechanism behind the 39-test cascade.

    Idempotent, and a no-op if some earlier call (in this process) already did it.

    One exception (BUG-598): tests/test_gates.py seeds a MARKED scripts/kit_config.py from the example at import,
    only when none exists, because its subprocess tests need the file on disk; it removes only that marked copy.
    """
    if os.path.isfile(REAL_KIT_CONFIG):
        return REAL_KIT_CONFIG

    cached = sys.modules.get("kit_config")
    if cached is not None and os.path.abspath(
            getattr(cached, "__file__", "") or "") == os.path.abspath(REAL_KIT_CONFIG):
        return REAL_KIT_CONFIG

    src = kit_config_source()
    spec = importlib.util.spec_from_loader("kit_config", loader=None, origin=REAL_KIT_CONFIG)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = REAL_KIT_CONFIG
    exec(compile(src, REAL_KIT_CONFIG, "exec"), mod.__dict__)
    sys.modules["kit_config"] = mod
    return REAL_KIT_CONFIG
