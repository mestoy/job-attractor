"""The kit ships to partners, so no file in it may name a person's workspace or home folder (proxy 223).

Two strings: the workspace path of the owner's own repo, and a macOS home folder. Both are written below as two literals joined, so this
file does not itself contain either one. Every file under the kit root is read (the .git folder is skipped), binary files are skipped, and a
planted positive control proves the scan would find a leak: it plants each string in a scratch tree and requires the same function to report it.
"""
import os
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEEDLES = ("/workspaces/" + "ai-job-search", "/Users" + "/")
MAX_BYTES = 25 * 1024 * 1024


def _paths(root, use_git):
    """Every file the kit ships. In a git checkout that is `git ls-files` (so an owner's untracked working folders cannot turn the check red);
    anywhere else, every file under root except .git."""
    if use_git:
        import subprocess
        out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, check=True).stdout
        return [os.path.join(root, p) for p in out.decode("utf-8", errors="ignore").split("\0") if p]
    found = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        found += [os.path.join(base, n) for n in files]
    return found


def _is_git_checkout(root):
    return os.path.exists(os.path.join(root, ".git"))


def scan(root, use_git=None):
    """[(relative path, needle)] for every shipped file under root that holds one of the needles. `use_git` defaults to whether root is a git
    checkout."""
    hits = []
    for path in _paths(root, _is_git_checkout(root) if use_git is None else use_git):
        try:
            if os.path.islink(path) or os.path.getsize(path) > MAX_BYTES:
                continue
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        text = raw.decode("utf-8", errors="ignore")
        for needle in NEEDLES:
            if needle in text:
                hits.append((os.path.relpath(path, root), needle))
    return hits


class NoWorkspacePathsInTheKit(unittest.TestCase):
    def test_the_kit_names_no_workspace_or_home_path(self):
        hits = scan(KIT)
        self.assertEqual([], hits, "the kit must not name a person's workspace or home folder: %r" % hits[:10])

    def test_positive_control_a_planted_leak_is_found_and_a_clean_file_is_not(self):
        """An empty check passes. Plant each needle in a scratch tree (one inside a .git folder, which is skipped) and require the scan to find
        exactly the planted ones."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "tests")); os.makedirs(os.path.join(tmp, ".git"))
            with open(os.path.join(tmp, "tests", "leaky_workspace.py"), "w", encoding="utf-8") as fh:
                fh.write('PATH = "%s/documents/state/feed.json"\n' % NEEDLES[0])
            with open(os.path.join(tmp, "tests", "leaky_home.md"), "w", encoding="utf-8") as fh:
                fh.write("see %sexample-person/notes\n" % NEEDLES[1])
            with open(os.path.join(tmp, "tests", "clean.py"), "w", encoding="utf-8") as fh:
                fh.write('PATH = "documents/state/feed.json"\n')
            with open(os.path.join(tmp, ".git", "config"), "w", encoding="utf-8") as fh:
                fh.write("path = %s/x\n" % NEEDLES[0])
            hits = scan(tmp, use_git=False)
        self.assertEqual({("tests/leaky_workspace.py", NEEDLES[0]), ("tests/leaky_home.md", NEEDLES[1])}, {(p.replace(os.sep, "/"), n) for p, n in hits})


    def test_in_a_git_checkout_only_tracked_files_count_and_a_tracked_leak_is_found(self):
        """The kit ships what git tracks. An untracked working folder (the owner keeps some beside the kit) must not turn this red, and a
        TRACKED leak still must."""
        import subprocess
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        with tempfile.TemporaryDirectory() as tmp:
            def run(*cmd):
                subprocess.run(cmd, cwd=tmp, env=env, check=True, capture_output=True)
            run("git", "init", "-q")
            with open(os.path.join(tmp, "shipped.py"), "w", encoding="utf-8") as fh:
                fh.write('PATH = "%s/x"\n' % NEEDLES[0])
            with open(os.path.join(tmp, "clean.py"), "w", encoding="utf-8") as fh:
                fh.write("X = 1\n")
            run("git", "add", "shipped.py", "clean.py")
            os.makedirs(os.path.join(tmp, "untracked-work"))
            with open(os.path.join(tmp, "untracked-work", "notes.md"), "w", encoding="utf-8") as fh:
                fh.write("see %sexample/notes\n" % NEEDLES[1])
            hits = scan(tmp)
        self.assertEqual([("shipped.py", NEEDLES[0])], hits)


if __name__ == "__main__":
    unittest.main()
