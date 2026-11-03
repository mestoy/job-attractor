"""The README's hooks table must name the scripts the kit actually wires (K2).

⛔ THE DRIFT THIS EXISTS TO STOP, because it already happened: the README said the kit "does not
wire the hooks" and gave a reason for each to stay off. That had been true once. The installer was
then changed to wire them, and the paragraph was never revisited. It went on reading as a design
choice for as long as anyone cared to look.

A person reading a wrong version of this section either wires the hooks a second time by hand or
trusts a state the kit is not in. Prose cannot be kept honest by remembering to update it, so this
compares it to the shipped example instead.
"""
import json
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(REPO, "README.md")
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import hook_example  # noqa: E402

# partner-starter keeps this at the root and the shipped kit keeps it under .claude/; backup.sh
# maps one to the other. One resolver so no test answers this question differently.
EXAMPLE = hook_example(REPO)

SECTION = "### The gates are wired for you on the first install"


def _wired():
    with open(EXAMPLE, encoding="utf-8") as fh:
        cfg = json.load(fh)
    out = set()
    for items in (cfg.get("hooks") or {}).values():
        for it in items:
            for hk in it.get("hooks", []):
                for tok in str(hk.get("command", "")).split():
                    tok = tok.strip('"').strip("'")
                    if tok.endswith(".py") or tok.endswith(".sh"):
                        out.add(os.path.basename(tok))
    return out


def _section():
    with open(README, encoding="utf-8") as fh:
        src = fh.read()
    i = src.index(SECTION)
    j = src.index("\n### ", i + len(SECTION))
    return src[i:j]


class TestTheTableTellsTheTruth(unittest.TestCase):
    def test_the_example_wires_something(self):
        """A control. With an empty example every comparison below is vacuously true."""
        self.assertTrue(_wired(), "the shipped example wires no hooks, so this test proves nothing")

    def test_the_section_exists(self):
        """A guard: if the heading is renamed, the rest must fail loudly, not silently skip."""
        self.assertIn(SECTION, open(README, encoding="utf-8").read())

    def test_every_wired_script_is_named_in_the_readme(self):
        named = set(re.findall(r"`([A-Za-z0-9_.-]+\.(?:py|sh))", _section()))
        missing = sorted(_wired() - named)
        self.assertEqual([], missing,
                         "the kit wires these and the README's table does not mention them: %s"
                         % ", ".join(missing))

    def test_the_readme_names_nothing_the_kit_does_not_wire(self):
        named = set(re.findall(r"^\|[^|]*\|([^|]*)\|", _section(), re.M))
        claimed = set()
        for cell in named:
            claimed |= set(re.findall(r"`([A-Za-z0-9_.-]+\.(?:py|sh))", cell))
        extra = sorted(claimed - _wired())
        self.assertEqual([], extra,
                         "the README's table promises hooks the kit does not wire: %s"
                         % ", ".join(extra))

    def test_it_no_longer_claims_the_hooks_ship_unwired(self):
        """The exact false sentence, so a revert of the rewrite is caught."""
        # The section carries a blockquote recording what it USED to say. Quoting the false
        # sentence in order to explain it is not claiming it, so the record is excluded.
        body = "\n".join(ln for ln in _section().splitlines()
                          if not ln.lstrip().startswith(">")).lower()
        for claim in ("stay main-only", "does not wire the hooks", "stays unwired here"):
            self.assertNotIn(claim, body,
                             "the README is back to saying the hooks ship unwired; install.sh "
                             "wires them on the first install")


if __name__ == "__main__":
    unittest.main()
