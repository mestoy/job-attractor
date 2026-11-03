#!/usr/bin/env python3
"""slice E, the CLI's address logic read in the kit: three paths, one pick, never an invented address. Every address is example.test."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import address_paths as ap  # noqa: E402


def repo_with(records, bounced=()):
    repo = tempfile.mkdtemp(prefix="ap_", dir=os.environ.get("SA_OUT") or None)
    d = os.path.join(repo, "documents", "state", "address")
    os.makedirs(d)
    with open(os.path.join(d, "results.json"), "w", encoding="utf-8") as fh:
        json.dump({"generated": "2026-10-13", "records": records}, fh)
    with open(os.path.join(repo, "documents", "bounced-addresses.txt"), "w", encoding="utf-8") as fh:
        fh.write("# bounced\n" + "\n".join(bounced) + "\n")
    return repo


class Paths(unittest.TestCase):
    def test_a_verified_address_is_the_pick(self):
        repo = repo_with({"a": {"status": "accepted", "to_email": "faketon.bossperson@fake-a.example.test", "source": "hunter.io", "confidence": 95, "checked_at": "2026-10-13T10:00:00Z"}})
        r = ap.paths_for(repo, "a", "Faketon Bossperson")
        self.assertEqual((r["pick"], r["verified"]["address"], r["verified"]["confidence"]), ("verified", "faketon.bossperson@fake-a.example.test", 95))
        shutil.rmtree(repo)

    def test_a_bounced_verified_address_is_never_offered(self):
        repo = repo_with({"a": {"status": "accepted", "to_email": "x.y@fake-a.example.test"}}, bounced=["X.Y@fake-a.example.test"])
        r = ap.paths_for(repo, "a", "Faketon Bossperson")
        self.assertIsNone(r["verified"])
        self.assertEqual(r["pick"], "linkedin")
        shutil.rmtree(repo)

    def test_a_below_bar_find_names_the_domain_so_the_variations_path_is_the_pick_and_is_a_guess(self):
        repo = repo_with({"b": {"status": "open", "rejected": [{"address": "faketon.bossperson@fake-b.example.test", "why": "hunter score 60 is not above 90"}]}})
        r = ap.paths_for(repo, "b", "Faketon Bossperson")
        v = r["variations"]
        self.assertEqual(r["pick"], "variations")
        self.assertTrue(v["guess"])
        self.assertEqual(v["to"], "faketon.bossperson@fake-b.example.test")
        self.assertEqual(v["bcc"], ["faketon@fake-b.example.test", "fbossperson@fake-b.example.test"])
        self.assertEqual(len(v["bcc"]), 2)
        self.assertTrue(all(a.endswith("@fake-b.example.test") for a in v["bcc"]))
        shutil.rmtree(repo)

    def test_a_find_at_a_freemail_domain_is_never_the_company_domain(self):
        for dom in ("gmail.com", "Yahoo.com", "icloud.com", "proton.me", "hotmail.com", "outlook.com"):
            repo = repo_with({"g": {"status": "open", "rejected": [{"address": "faketon.bossperson@%s" % dom}]}})
            r = ap.paths_for(repo, "g", "Faketon Bossperson")
            self.assertIsNone(r["variations"], dom)
            self.assertEqual(r["pick"], "linkedin", dom)
            shutil.rmtree(repo)

    def test_subdomains_country_variants_and_case_of_a_freemail_provider_are_freemail(self):
        for dom in ("mail.yahoo.com", "yahoo.co.uk", "GMAIL.COM", "outlook.fr", "hotmail.co.uk", "yahoo.com.au", "gmx.de", "live.ca", "smtp.gmail.com"):
            repo = repo_with({"g": {"status": "open", "rejected": [{"address": "faketon.bossperson@%s" % dom}]}})
            r = ap.paths_for(repo, "g", "Faketon Bossperson")
            self.assertIsNone(r["variations"], dom)
            self.assertEqual(r["pick"], "linkedin", dom)
            shutil.rmtree(repo)

    def test_a_company_domain_and_a_name_that_merely_contains_a_provider_are_not_freemail(self):
        for dom in ("acme-fake.test", "livefake.test", "yahoofake.test", "mail.acme-fake.test", "fake-gmail.test"):
            repo = repo_with({"g": {"status": "open", "rejected": [{"address": "faketon.bossperson@%s" % dom}]}})
            r = ap.paths_for(repo, "g", "Faketon Bossperson")
            self.assertEqual(r["pick"], "variations", dom)
            self.assertEqual(r["variations"]["domain"], dom)
            shutil.rmtree(repo)

    def test_a_freemail_find_is_skipped_but_a_later_company_find_still_counts(self):
        repo = repo_with({"g": {"status": "open", "rejected": [{"address": "x@gmail.com"}, {"address": "faketon.bossperson@fake-g.example.test"}]}})
        r = ap.paths_for(repo, "g", "Faketon Bossperson")
        self.assertEqual(r["variations"]["domain"], "fake-g.example.test")
        shutil.rmtree(repo)

    def test_with_no_domain_on_record_nothing_is_invented(self):
        repo = repo_with({"c": {"status": "open", "rejected": []}})
        r = ap.paths_for(repo, "c", "Faketon Bossperson")
        self.assertIsNone(r["verified"])
        self.assertIsNone(r["variations"])
        self.assertEqual(r["pick"], "linkedin")
        shutil.rmtree(repo)

    def test_a_common_name_goes_to_linkedin_even_with_a_domain(self):
        repo = repo_with({"d": {"status": "open", "rejected": [{"address": "fake.smith@fake-d.example.test"}]}})
        r = ap.paths_for(repo, "d", "Fake Smith")
        self.assertTrue(r["common_name"])
        self.assertIsNone(r["variations"])
        self.assertEqual(r["pick"], "linkedin")
        shutil.rmtree(repo)

    def test_no_files_at_all_reads_as_linkedin_not_a_crash(self):
        repo = tempfile.mkdtemp(prefix="ap_", dir=os.environ.get("SA_OUT") or None)
        r = ap.paths_for(repo, "z", "Faketon Bossperson")
        self.assertEqual(r["pick"], "linkedin")
        shutil.rmtree(repo)


if __name__ == "__main__":
    unittest.main()
