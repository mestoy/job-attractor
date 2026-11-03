"""Real names and contact strings that must never reach a kit file, loaded from OUTSIDE git.

The strings themselves are private, so the kit never carries them. They live in a local,
gitignored file (tests/.private-denylist.txt, one term per line, '#' starts a comment) or in
a file named by the JA_PRIVATE_DENYLIST environment variable. On a machine with neither, the
tests that use this still run their fixture checks and skip only the real-name part, saying why.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, ".private-denylist.txt")
SKIP_MESSAGE = ("no private denylist on this machine (set JA_PRIVATE_DENYLIST or create "
                "tests/.private-denylist.txt); the real-name check is skipped, fixture checks still ran")


def path():
    return os.environ.get("JA_PRIVATE_DENYLIST") or DEFAULT_PATH


def load():
    """Return the list of private terms, or [] when no file is present."""
    p = path()
    if not os.path.isfile(p):
        return []
    out = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            term = line.strip()
            if term and not term.startswith("#"):
                out.append(term)
    return out
