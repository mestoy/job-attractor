"""kit#95: wttj-search ships no Algolia key, and a key problem is a NAMED failure, never an empty result.

WTTJ rotates its public search-only Algolia key; the baked-in default went stale and every search
403'd while the CLI still exited 0 with nothing on stdout worth reading. Ruled fix: no default key,
WTTJ_ALGOLIA_KEY is required, a missing key and a 403 both exit 1 with a stderr line whose `code`
names the problem and whose message names the refresh steps.

The CLI is TypeScript. This suite runs it for real under whichever runtime the machine has (bun,
or node >= 22 with type stripping) with `fetch` stubbed to answer 403, so the exit code and the
stderr line are the ones a kit user would see. With no runtime it falls back to the source-level
contract (no literal 32-hex key, the two codes present) and says so in the skip reason.

Set WTTJ_SKILL_DIR to point the suite at another copy of the skill (used to prove red on HEAD).
"""
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from harness import LIVE_REPO

STUB_403 = """
const _status = Number(process.env.STUB_STATUS || "403")
globalThis.fetch = async () => new Response('{"message":"Invalid Application-ID or API key","status":403}', { status: _status, statusText: "Forbidden" })
"""

# node cannot resolve the `../helpers.js` specifiers the TS sources use; map them back to .ts.
NODE_HOOK = """
import { register } from "node:module"
register("data:text/javascript," + encodeURIComponent(`
export async function resolve(spec, ctx, next) {
  if (spec.startsWith(".") && spec.endsWith(".js")) {
    try { return await next(spec.slice(0, -3) + ".ts", ctx) } catch {}
  }
  return next(spec, ctx)
}`), import.meta.url)
""" + STUB_403


def skill_dir():
    env = os.environ.get("WTTJ_SKILL_DIR")
    if env:
        return env
    for cand in (os.path.join(LIVE_REPO, ".agents", "skills", "wttj-search"),
                 os.path.join(os.path.dirname(LIVE_REPO), ".agents", "skills", "wttj-search")):
        if os.path.isfile(os.path.join(cand, "cli", "src", "cli.ts")):
            return cand
    return None


def runtime():
    """('bun', path) | ('node', path) | None."""
    b = shutil.which("bun")
    if b:
        return ("bun", b)
    n = shutil.which("node") or next((p for p in sorted(glob.glob("/vscode/vscode-server/bin/*/*/node"))
                                      if os.path.isfile(p) and os.access(p, os.X_OK)), None)
    if n:
        try:
            v = subprocess.run([n, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
            if int(v.lstrip("v").split(".")[0]) >= 22:
                return ("node", n)
        except Exception:
            pass
    return None


class WttjKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = skill_dir()
        if not cls.skill:
            raise unittest.SkipTest("wttj-search skill not present in this tree")
        cls.cli = os.path.join(cls.skill, "cli")
        cls.rt = runtime()
        cls.tmp = tempfile.mkdtemp(prefix="kit95-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, args, env_key):
        if not self.rt:
            self.skipTest("no bun or node>=22 on this machine; source-level checks below still ran")
        env = {k: v for k, v in os.environ.items() if k != "WTTJ_ALGOLIA_KEY"}
        if env_key is not None:
            env["WTTJ_ALGOLIA_KEY"] = env_key
        kind, exe = self.rt
        if kind == "bun":
            stub = os.path.join(self.tmp, "stub.ts")
            with open(stub, "w") as f:
                f.write(STUB_403)
            cmd = [exe, "--preload", stub, "src/cli.ts"] + args
        else:
            hook = os.path.join(self.tmp, "hook.mjs")
            with open(hook, "w") as f:
                f.write(NODE_HOOK)
            cmd = [exe, "--experimental-strip-types", "--no-warnings", "--import", hook, "src/cli.ts"] + args
        return subprocess.run(cmd, cwd=self.cli, env=env, capture_output=True, text=True, timeout=60)

    def _stderr_json(self, p):
        lines = [l for l in p.stderr.splitlines() if l.startswith("{")]
        self.assertTrue(lines, f"no JSON error line on stderr; stderr={p.stderr!r}")
        return json.loads(lines[-1])

    # -- the thing itself: run the CLI ---------------------------------------------------------
    def test_403_exits_nonzero_and_names_the_key_problem(self):
        p = self._run(["search", "-q", "product manager"], env_key="stale-key")
        self.assertNotEqual(p.returncode, 0, f"403 must not exit 0; stdout={p.stdout!r}")
        err = self._stderr_json(p)
        self.assertEqual(err.get("code"), "WTTJ_KEY_REJECTED", err)
        self.assertIn("WTTJ_ALGOLIA_KEY", err.get("error", ""))
        self.assertIn("403", err.get("error", ""))
        self.assertNotIn('"results"', p.stdout, "a 403 must not print an (empty) result set")

    def test_403_on_detail_is_named_too(self):
        p = self._run(["detail", "12345678-1234-1234-1234-123456789abc"], env_key="stale-key")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self._stderr_json(p).get("code"), "WTTJ_KEY_REJECTED")

    def test_missing_key_is_announced_before_any_network(self):
        p = self._run(["search", "-q", "x"], env_key=None)
        self.assertNotEqual(p.returncode, 0)
        err = self._stderr_json(p)
        self.assertEqual(err.get("code"), "WTTJ_KEY_MISSING", err)
        self.assertIn("WTTJ_ALGOLIA_KEY", err.get("error", ""))
        self.assertIn("csekhvms53-dsn.algolia.net", err.get("error", ""), "message must name the refresh steps")

    def test_blank_key_counts_as_missing(self):
        p = self._run(["search", "-q", "x"], env_key="   ")
        self.assertEqual(self._stderr_json(p).get("code"), "WTTJ_KEY_MISSING")

    # -- source-level contract (runs even without a JS runtime) --------------------------------
    def test_no_baked_in_key_in_source(self):
        with open(os.path.join(self.cli, "src", "helpers.ts"), encoding="utf-8") as f:
            src = f.read()
        self.assertFalse(re.search(r'"[0-9a-f]{32}"', src), "a literal 32-hex Algolia key is baked in")
        self.assertNotIn("DEFAULT_ALGOLIA_KEY", src)

    def test_help_and_docs_name_the_refresh_procedure(self):
        for rel in ("cli/src/cli.ts", "SKILL.md", "cli/README.md"):
            with open(os.path.join(self.skill, rel), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("WTTJ_ALGOLIA_KEY", text, rel)
            self.assertIn("x-algolia-api-key", text, rel)
            self.assertIn("WTTJ_KEY_REJECTED", text, rel)


if __name__ == "__main__":
    unittest.main()
