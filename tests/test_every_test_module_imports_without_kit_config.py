"""BUG-736 guard: a missing scripts/kit_config.py can never drop a test class.

scripts/kit_config.py is gitignored, so a fresh worktree has only kit_config.example.py. A test
module that does `import kit_config` (directly or through a script) then fails to IMPORT, and a
run reports the same count as its baseline while whole classes never executed. Each candidate
module here is imported in a CLEAN interpreter (no conftest, so no pytest seed to hide the gap)
and must not die on kit_config. A real scripts/kit_config.py is hidden in the probe, so an installed tree
is checked as strictly as a bare one. Candidates: every tests/test_*.py that names kit_config or a
script that names it. Fix a failure by importing tests/_kit_config_shim.py first in that file.
"""
import os
import re
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")

_PROBE = (
    "import importlib, sys\n"
    "sys.path[:0] = [sys.argv[1], sys.argv[2], sys.argv[3]]\n"
    "sys.modules.pop('kit_config', None)\n"
    "class _Hide:\n"
    "    def find_spec(self, name, path=None, target=None):\n"
    "        if name == 'kit_config':\n"
    "            raise ModuleNotFoundError(\"No module named 'kit_config' (hidden by the guard)\")\n"
    "sys.meta_path.insert(0, _Hide())\n"
    "try:\n"
    "    importlib.import_module(sys.argv[4])\n"
    "except BaseException as e:\n"
    "    print(type(e).__name__ + ': ' + str(e)[:200])\n"
    "    sys.exit(3 if 'kit_config' in str(e) else 0)\n"
)


def _candidates():
    users = ["kit_config"]
    for f in os.listdir(SCRIPTS):
        if f.endswith(".py") and f != "kit_config.example.py":
            with open(os.path.join(SCRIPTS, f), encoding="utf-8", errors="ignore") as fh:
                if "kit_config" in fh.read():
                    users.append(f[:-3])
    pat = re.compile(r"\b(" + "|".join(map(re.escape, users)) + r")\b")
    out = []
    for f in sorted(os.listdir(HERE)):
        if f.startswith("test_") and f.endswith(".py") and f != os.path.basename(__file__):
            with open(os.path.join(HERE, f), encoding="utf-8", errors="ignore") as fh:
                if pat.search(fh.read()):
                    out.append(f[:-3])
    return out


def _probe(name):
    p = subprocess.run([sys.executable, "-c", _PROBE, HERE, SCRIPTS, KIT, name],
                       capture_output=True, text=True, cwd=KIT, timeout=120,
                       env=dict(os.environ, BUG736_HIDE_REAL_KIT_CONFIG="1"))
    return name, p.returncode, (p.stdout.strip().splitlines() or [""])[-1]


class EveryTestModuleImportsWithoutAKitConfig(unittest.TestCase):
    def test_no_module_dies_on_a_missing_kit_config(self):
        mods = _candidates()
        self.assertGreater(len(mods), 50, "the candidate scan found almost nothing: an empty check")
        with ThreadPoolExecutor(max_workers=8) as ex:
            bad = [(n, msg) for n, rc, msg in ex.map(_probe, mods) if rc == 3]
        self.assertEqual(bad, [], "these test modules cannot be imported without scripts/kit_config.py; "
                                  "import tests/_kit_config_shim.py first in each: %r" % bad)


if __name__ == "__main__":
    unittest.main()
