"""An obviously fake kit folder for slice B: a blocked list, a send log, one card file. No real person or company (every name says FAKE)."""
import json
import os
import shutil
import tempfile

BLOCKED = "FAKEBLOCKED Defense Works"
SENT = "FAKE-SENT Co (NOT REAL)"
CLEAN_LIVE = "FAKE-LIVE Analytics (NOT REAL)"
CLEAN_RADAR = "FAKE-RADAR Freight (NOT REAL)"
CLEAN_NOBOARD = "FAKE-NOBOARD Labs (NOT REAL)"
VETOED = "FAKE-VETO Gambling Games (NOT REAL)"


def make_repo(veto=True):
    repo = tempfile.mkdtemp(prefix="sB-repo-", dir=os.environ.get("SA_OUT") or None)
    state = os.path.join(repo, "documents", "state")
    os.makedirs(state)
    with open(os.path.join(repo, "documents", "blocked-employers-list.md"), "w", encoding="utf-8") as fh:
        fh.write("# Blocked employers\n\n- %s: defense mission, ruled out by the fake owner\n" % BLOCKED)
    rows = [{"date": "2026-09-02", "rung": "warm", "replied": False, "status": "sent", "name": "Faketon Person (NOT REAL)", "company": SENT}]
    with open(os.path.join(repo, "documents", "send-log.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
    with open(os.path.join(state, "fake-card-co-card-2026-10-07.md"), "w", encoding="utf-8") as fh:
        fh.write("# FAKE-CARD Co (NOT REAL) · applied-ai · panel 80/80/80\n\nNothing else matters for this fixture.\n")
    # a card file for each of the first six Find companies (fake-co-001 ... 006), so the engine has unread items to read
    for i, name in enumerate([CLEAN_LIVE, BLOCKED, CLEAN_RADAR, SENT, CLEAN_NOBOARD, VETOED], 1):
        with open(os.path.join(state, "fake-co-%03d-card-2026-10-07.md" % i), "w", encoding="utf-8") as fh:
            fh.write("# %s \u00b7 applied-ai \u00b7 panel 80/80/80\n\nNothing else matters for this fixture.\n" % name)
    with open(os.path.join(repo, "kit_config.py"), "w", encoding="utf-8") as fh:
        fh.write("INDUSTRY_VETO = [r'gambling']\nVETO_EMPLOYERS = []\n" if veto else "INDUSTRY_VETO = []\nVETO_EMPLOYERS = []\n")
    return repo


def drop(repo):
    shutil.rmtree(repo, True)
