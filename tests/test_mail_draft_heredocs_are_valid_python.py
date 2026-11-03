"""Every Python heredoc inside mail-draft.sh must actually parse as Python.

⛔ WHY THIS EXISTS: on 2026-09-21 the send-log writer in mail-draft.sh had a shell `case` block
sitting INSIDE its `python3 - <<'PYLOG'` heredoc, put there by a bad port. Python raised
SyntaxError on line 9 of the heredoc every single time. The call ends in `2>/dev/null || true`, so
the error went to nowhere, the script carried on, printed its success line and exited 0 — and
documents/send-log.jsonl was never written at all.

WHAT THAT COSTS: the people-ranker dedups on `to_name` from that file. With no row, a person you
emailed comes back as uncontacted and gets approached twice. The outreach_log still got its STAGED
entry, so the run LOOKED logged.

A heredoc is text to the shell. `bash -n` is happy with anything inside it, and no test that runs
the script can see the difference between "wrote nothing because it had nothing to write" and
"could not run at all", because the failure is discarded on the way out. So the heredocs are
parsed directly here, which is the only place the error is visible.
"""
import ast
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "mail-draft.sh")

# ⛔ THE FIRST VERSION OF THIS REGEX REQUIRED THE TAG TO END THE LINE, AND THE ONE HEREDOC THAT
# WAS BROKEN DID NOT: it reads `<<'PYLOG' 2>/dev/null || true`. So the detector matched nothing and
# the test went green over a SyntaxError. Redirections and `|| true` are exactly what follows a
# heredoc tag in a call whose failure is being discarded, which is the call most worth checking.
HEREDOC = re.compile(r"""python3\b[^\n]*?<<\s*'?([A-Z][A-Z0-9_]*)'?""")


def _heredocs():
    """[(tag, first line number, body)] for every python3 heredoc in the script."""
    with open(SCRIPT, encoding="utf-8") as fh:
        lines = fh.readlines()
    out = []
    i = 0
    while i < len(lines):
        m = HEREDOC.search(lines[i])
        if not m:
            i += 1
            continue
        tag = m.group(1)
        j = i + 1
        body = []
        while j < len(lines) and lines[j].rstrip("\n").strip() != tag:
            body.append(lines[j])
            j += 1
        out.append((tag, i + 2, "".join(body)))
        i = j + 1
    return out


class TestTheHeredocsParse(unittest.TestCase):
    def test_there_are_some_to_check(self):
        """A control. An empty list would make the loop below pass without looking at anything,
        which is the exact failure class this file was written about."""
        self.assertTrue(_heredocs(),
                        "found no python3 heredocs in mail-draft.sh, so nothing was checked")

    def test_the_send_log_writer_is_among_them(self):
        """A second control, naming the one heredoc whose breakage started this. A detector that
        silently stops matching it would otherwise leave the test green forever."""
        self.assertIn("PYLOG", [tag for tag, _s, _b in _heredocs()],
                      "the send-log writer's heredoc was not found, so it is not being checked")

    def test_every_heredoc_is_valid_python(self):
        for tag, start, body in _heredocs():
            with self.subTest(tag=tag):
                try:
                    ast.parse(body)
                except SyntaxError as e:
                    self.fail(
                        "the %s heredoc (mail-draft.sh line %d) is not valid Python: line %d, %s\n"
                        "  %s\n"
                        "Shell that lands inside a heredoc is passed to python as source. The "
                        "call discards stderr, so this fails in total silence and the script "
                        "still prints success."
                        % (tag, start, e.lineno, e.msg, (e.text or "").strip()))


if __name__ == "__main__":
    unittest.main()
