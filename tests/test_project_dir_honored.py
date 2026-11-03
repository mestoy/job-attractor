"""BUG-156 (workspace #23, kit #37): CLAUDE_PROJECT_DIR must be honored at CALL time.

Every script named in the bug reads CLAUDE_PROJECT_DIR at IMPORT and freezes it into a module
constant (`REPO`, and paths derived from it such as `employers.REGISTRY`,
`rank_criteria.PROFILE_VIEWS`, `voice_samples.SAMPLES_PATH`). A test harness that sets the
variable AFTER the module was first imported, or a second project in one process, then reads
and WRITES the first tree the module ever saw, which is the live repo.

Each case below runs in a fresh interpreter: import the module with the variable unset, THEN
point CLAUDE_PROJECT_DIR at a temp tree, then call the module's cheapest path-resolving function
and demand it answers from the temp tree. Nothing here writes outside the temp tree; the probes
are read-only and the temp tree is discarded.

⚖️ The precedent is `contact_card._shown_path()`: a patched module constant still wins (existing
tests assign `mod.REPO = tmp` directly), the live environment wins otherwise, and with the
variable unset the import-time default is unchanged.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

# module -> (seed files {rel: text}, probe expression that must be truthy against the temp tree)
PROBES = {
    "check_dup": (
        {"documents/probe-store.md": "Probeco Widgets was contacted here\n"},
        "bool(m.search_file('documents/probe-store.md', {'probeco widgets'}))",
    ),
    "check_style": (
        {"commands/probe-cmd.md": "# probe\n"},
        "'probe-cmd' in m._command_names()",
    ),
    "contact_signals": (
        {"documents/state/contact-roles.jsonl":
         json.dumps({"name": "Probe Person", "title": "VP", "company": "Probeco",
                     "still_there": True, "verified_on": "2026-01-01"}) + "\n"},
        "bool(m.load_role_cache())",
    ),
    "rank_criteria": (
        {"documents/probe.txt": "SENTINEL-156\n"},
        "'SENTINEL-156' in m.rd('documents/probe.txt')",
    ),
    "rank_network_companies": (
        {"documents/probe.txt": "SENTINEL-156\n"},
        "'SENTINEL-156' in m._read('documents/probe.txt')",
    ),
    "resolve_employers": (
        {},
        "m.cache_path().startswith(TMP)",
    ),
    "screen_sweep": (
        {"documents/send-log.jsonl": json.dumps({"company": "Probeco Widgets"}) + "\n"},
        "'probeco widgets' in m.load_prior()[0]",
    ),
    "sync_contacted": (
        {"documents/contact-closeness.json": json.dumps({"contacts": {"probe": {}}})},
        "'contacts' in m.load()[0]",
    ),
    "verify_resume": (
        {"documents/applications/probeco/cv_draft.tex": "%\n"},
        "'probeco' in m.application_slugs()",
    ),
    "voice_samples": (
        {},
        "m.samples_path().startswith(TMP)",
    ),
    "employers": (
        {"documents/employers.jsonl": json.dumps({"key": "probeco", "name": "Probeco"}) + "\n"},
        "m.available()",
    ),
}

# check_dup no longer reads CLAUDE_PROJECT_DIR at all (kit #156: a session rooted outside the install set it to a folder with no stores, so 14 Builds
# could not send). It honors the explicit JOBSEARCH_DATA_ROOT at call time instead, which a harness sets on purpose; every other module here keeps
# CLAUDE_PROJECT_DIR.
REDIRECT_VAR = {"check_dup": "JOBSEARCH_DATA_ROOT", "contact_card": "JOBSEARCH_DATA_ROOT"}   # BUG-720: contact_card reads the install too

DRIVER = r"""
import os, sys, json
sys.path.insert(0, sys.argv[1])
TMP = sys.argv[2]
VAR = sys.argv[5]
os.environ.pop("CLAUDE_PROJECT_DIR", None)
os.environ.pop("JOBSEARCH_DATA_ROOT", None)
m = __import__(sys.argv[3])                 # bound with the variable UNSET
os.environ[VAR] = TMP                       # redirected AFTER import
ok = bool(eval(sys.argv[4]))
print(json.dumps({"ok": ok}))
"""


class ProjectDirHonoredAfterImport(unittest.TestCase):

    def _run(self, mod, seed, probe):
        with tempfile.TemporaryDirectory() as tmp:
            for rel, text in seed.items():
                p = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(text)
            env = dict(os.environ)
            env.pop("CLAUDE_PROJECT_DIR", None)
            r = subprocess.run([sys.executable, "-c", DRIVER, SCRIPTS, tmp, mod, probe, REDIRECT_VAR.get(mod, "CLAUDE_PROJECT_DIR")],
                               capture_output=True, text=True, env=env, cwd=tmp, timeout=120)
            self.assertEqual(r.returncode, 0, f"{mod}: driver crashed\n{r.stderr[-2000:]}")
            last = r.stdout.strip().splitlines()[-1]
            self.assertTrue(json.loads(last)["ok"],
                            f"{mod}: {REDIRECT_VAR.get(mod, 'CLAUDE_PROJECT_DIR')} set after import was ignored "
                            f"(probe: {probe})\n{r.stderr[-1500:]}")


def _make(mod, seed, probe):
    def test(self):
        self._run(mod, seed, probe)
    test.__doc__ = f"{mod} answers from CLAUDE_PROJECT_DIR set after import"
    return test


for _mod, (_seed, _probe) in PROBES.items():
    setattr(ProjectDirHonoredAfterImport, f"test_{_mod}", _make(_mod, _seed, _probe))


class ProjectDirUnsetKeepsDefault(unittest.TestCase):
    """With the variable unset, nothing moves: the import-time default is the answer."""

    def test_defaults_unchanged(self):
        code = (
            "import os, sys; sys.path.insert(0, sys.argv[1]); os.environ.pop('CLAUDE_PROJECT_DIR', None)\n"
            "import rank_criteria, employers, screen_sweep\n"
            "assert rank_criteria._repo() == rank_criteria.REPO\n"
            "assert screen_sweep._repo() == screen_sweep.REPO\n"
            "assert employers._registry_path() == employers.REGISTRY\n"
            "print('ok')"
        )
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        r = subprocess.run([sys.executable, "-c", code, SCRIPTS], capture_output=True, text=True,
                           env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])

    def test_patched_constant_still_wins(self):
        """Existing suites assign `mod.REPO = tmp` directly; that must keep steering the reader
        even when CLAUDE_PROJECT_DIR points elsewhere."""
        code = (
            "import os, sys, tempfile; sys.path.insert(0, sys.argv[1])\n"
            "import rank_criteria as rc\n"
            "a = tempfile.mkdtemp(); b = tempfile.mkdtemp()\n"
            "os.environ['CLAUDE_PROJECT_DIR'] = a\n"
            "rc.REPO = b\n"
            "assert rc._repo() == b, rc._repo()\n"
            "print('ok')"
        )
        r = subprocess.run([sys.executable, "-c", code, SCRIPTS], capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
