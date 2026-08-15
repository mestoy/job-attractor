#!/usr/bin/env python3
"""#33: cmd_ingest must reject a source that is not a citation.

Before the fix, cmd_ingest validated only that `source` was non-empty, so a row citing
"well-known company" or "web search" landed at the top evidence tier next to a row citing a real
URL. This suite is red before the source-shape gate and green after. It runs the REAL script via
the CLI (reads the production value), never a re-implementation of the check.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(KIT, "scripts", "resolve_employers.py")


def run_ingest(rows):
    """Dry-run cmd_ingest over `rows` and return its combined output. Dry-run touches no store."""
    fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"employers": rows}, fh)
    fh.close()
    try:
        out = subprocess.run(
            [sys.executable, SCRIPT, "ingest", fh.name, "--dry-run"],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        os.unlink(fh.name)
    return out.stdout + out.stderr


def _row(source):
    # A generic valid segment from the kit's configurable vocabulary, so this asserts the SOURCE
    # mechanism rather than any one user's shipped segment slugs.
    return {"employer": "Acme Co", "segment": "segment-a", "industry": "widgets", "source": source}


class TestSourceShapeGate(unittest.TestCase):
    def test_bare_assertion_source_is_rejected(self):
        # The exact offenders measured in the 209-row store.
        for assertion in ("well-known company", "web search", "well-known organization",
                          "well-known federal agency"):
            out = run_ingest([_row(assertion)])
            self.assertIn("rejected: 1", out, f"{assertion!r} should be rejected as a non-source")
            self.assertIn("would add: 0", out, f"{assertion!r} must not land")

    def test_url_source_is_accepted(self):
        out = run_ingest([_row("https://acme.com/about")])
        self.assertIn("would add: 1", out)

    def test_bare_domain_source_is_accepted(self):
        out = run_ingest([_row("acme.com/careers")])
        self.assertIn("would add: 1", out)

    def test_named_ruling_source_is_accepted(self):
        # A dated ruling with a wikilink is a real citation, not a bare assertion.
        out = run_ingest([_row("Michael's ruling 2026-08-12 [[drug-pharma-industry-excluded]]")])
        self.assertIn("would add: 1", out)

    def test_source_containing_search_but_named_is_accepted(self):
        # A NAMED authoritative source (SEC EDGAR) is a citation even though it says "search".
        out = run_ingest([_row("SEC EDGAR full-text search result for Acme Co")])
        self.assertIn("would add: 1", out)

    def test_paraphrased_assertions_are_rejected(self):
        # The adversarial cases: an assertion wearing a lead-in or an article still has no locator,
        # so it is not a citation. These slipped through the first anchored/blocklist gate.
        for guess in ("Based on web search", "a well-known company",
                      "Per web search, this is a payments company",
                      "based on my training data", "likely a payments company",
                      "presumably a fintech company based on the name", "common sense"):
            out = run_ingest([_row(guess)])
            self.assertIn("rejected: 1", out, f"{guess!r} has no locator, must be rejected")
            self.assertIn("would add: 0", out, f"{guess!r} must not land")


if __name__ == "__main__":
    unittest.main()
