"""Shared offline fixtures for the industry-source tests (kit port of AJS #24).

EVERY company here is invented and marked (FAKE) where it appears in a test; every domain ends in
.example.invalid. FakeTransport answers the Wikidata and SEC EDGAR URLs from this synthetic data,
counts calls, and keeps every request header, so a test can prove a cache saved a request and that
the setup email reached SEC's header and nothing else. The industry concept QIDs (financial
services, bank, insurance...) are generic Wikidata concepts, not companies.
"""
import os
import urllib.error
import urllib.parse

SETUP_EMAIL = "tester@example.invalid"


def set_setup_email(email=SETUP_EMAIL):
    """Pretend the person's setup email is `email` (None unsets it); returns the previous value.
    EDGAR runs only when this is set, and the email goes in SEC's User-Agent alone."""
    import importlib
    kc = importlib.import_module("kit_config")
    if isinstance(email, tuple):                     # restoring what an earlier call returned
        old_env, old_kc = email
        if old_env is None:
            os.environ.pop("JOBKIT_OWNER_EMAIL", None)
        else:
            os.environ["JOBKIT_OWNER_EMAIL"] = old_env
        kc.OWNER_EMAIL = old_kc
        return (old_env, old_kc)
    old = (os.environ.get("JOBKIT_OWNER_EMAIL"), getattr(kc, "OWNER_EMAIL", ""))
    if email is None:
        os.environ.pop("JOBKIT_OWNER_EMAIL", None)
        kc.OWNER_EMAIL = ""
    else:
        os.environ["JOBKIT_OWNER_EMAIL"] = email
        kc.OWNER_EMAIL = email
    return old


def claim_item(qid):
    return {"mainsnak": {"datavalue": {"value": {"id": qid}}}}


def claim_str(s):
    return {"mainsnak": {"datavalue": {"value": s}}}


def fake_entity(label, p31=("Q4830453",), p452=(), p856=()):
    claims = {"P31": [claim_item(q) for q in p31]}
    if p452:
        claims["P452"] = [claim_item(q) for q in p452]
    if p856:
        claims["P856"] = [claim_str(u) for u in p856]
    return {"labels": {"en": {"value": label}}, "claims": claims}


def _co(label, qid, industries, domain):
    return fake_entity(label, p452=industries, p856=("https://www.%s/" % domain,))


FIN_QIDS = ("Q837171", "Q57774188")
SEARCH = {
    "Alder Bank": [{"id": "QFAKEA1", "label": "Alder Bank", "description": ""}],
    "Birch Financial": [{"id": "QFAKEB1", "label": "Birch Financial", "description": ""}],
    "Gorse Credit": [{"id": "QFAKEG1", "label": "Gorse Credit", "description": ""}],
    "Dune Capital": [{"id": "QFAKED0", "label": "Dune Capital", "description": "family name"},
                     {"id": "QFAKED1", "label": "Dune Capital", "description": ""}],
    "Quokka Savings": [{"id": "QFAKEQ1", "label": "Quokka Savings", "description": ""}],
    "Elm Mutual": [{"id": "QFAKEE1", "label": "Elm National Corporation", "description": ""},
                   {"id": "QFAKEE2", "label": "Elm Mutual Field", "description": "stadium"}],
}
ENTITIES = {
    "QFAKEA1": _co("Alder Bank", "QFAKEA1", FIN_QIDS, "alder-bank.example.invalid"),
    "QFAKEB1": _co("Birch Financial", "QFAKEB1", ("Q57774188",), "birch-financial.example.invalid"),
    "QFAKEG1": _co("Gorse Credit", "QFAKEG1", ("Q43183",), "gorse-credit.example.invalid"),
    "QFAKED0": fake_entity("Dune Capital", p31=("Q101352",)),
    "QFAKED1": _co("Dune Capital", "QFAKED1", ("Q4290", "Q43015", "Q837171"), "dune-capital.example.invalid"),
    "QFAKEQ1": _co("Quokka Savings", "QFAKEQ1", ("Q837171",), "quokka-savings.example.invalid"),
    "QFAKEE1": _co("Elm National Corporation", "QFAKEE1", ("Q22687",), "elm-mutual.example.invalid"),
    "QFAKEE2": fake_entity("Elm Mutual Field", p31=("Q483110",)),
}
LABELS = {"Q837171": "financial services", "Q57774188": "financial sector", "Q22687": "bank",
          "Q43183": "insurance", "Q4290": "investment", "Q43015": "finance"}
TICKERS = [{"cik_str": 101, "title": "ALDER BANK INC"}, {"cik_str": 102, "title": "BIRCH FINANCIAL CORP"},
           {"cik_str": 103, "title": "GORSE CREDIT INC"}]
SUBMISSIONS = {"0000000101": {"sic": "6021", "sicDescription": "National Commercial Banks"},
               "0000000102": {"sic": "6022", "sicDescription": "State Commercial Banks"},
               "0000000103": {"sic": "6311", "sicDescription": "Life Insurance"}}


class FakeTransport:
    def __init__(self, down=False, sec_down=False, wd_down=False, extra_search=None, extra_entities=None,
                 extra_labels=None, extra_tickers=None, extra_submissions=None):
        self.down = down
        self.sec_down = sec_down
        self.wd_down = wd_down
        self.calls = []          # list of (url, headers)
        self.search = dict(SEARCH)
        self.search.update(extra_search or {})
        self.entities = dict(ENTITIES)
        self.entities.update(extra_entities or {})
        self.labels = dict(LABELS)
        self.labels.update(extra_labels or {})
        self.tickers = list(TICKERS) + list(extra_tickers or [])
        self.submissions = dict(SUBMISSIONS)
        self.submissions.update(extra_submissions or {})

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if self.down:
            raise urllib.error.URLError("fixture: network down")
        u = urllib.parse.urlparse(url)
        if self.wd_down and u.hostname.endswith("wikidata.org"):
            raise urllib.error.URLError("fixture: wikidata down")
        if self.sec_down and u.hostname.endswith("sec.gov"):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        q = urllib.parse.parse_qs(u.query)
        if u.hostname == "www.wikidata.org":
            if q["action"][0] == "wbsearchentities":
                return {"search": self.search.get(q["search"][0], [])}
            ents = {}
            for i in q["ids"][0].split("|"):
                if i in self.entities:
                    ents[i] = self.entities[i]
                elif i in self.labels:
                    ents[i] = {"labels": {"en": {"value": self.labels[i]}}}
            return {"entities": ents}
        if u.hostname == "www.sec.gov" and u.path.endswith("company_tickers.json"):
            return {str(n): t for n, t in enumerate(self.tickers)}
        if u.hostname == "data.sec.gov":
            cik = u.path.split("CIK")[1].split(".")[0]
            return self.submissions[cik]
        raise AssertionError("unexpected host in a request: %s" % url)

    def sec_calls(self):
        return [(u, h) for u, h in self.calls if urllib.parse.urlparse(u).hostname.endswith("sec.gov")]

    def hosts(self):
        return {urllib.parse.urlparse(u).hostname for u, _ in self.calls}
