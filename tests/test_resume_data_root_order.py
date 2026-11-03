"""Slice I data-root amendment: verify_resume and review_resume resolve the person's data root as
JOBSEARCH_DATA_ROOT, else CLAUDE_PROJECT_DIR, else their own folder. Each script is imported in a
fresh interpreter so the import-time binding is what is tested. Paths are obviously fake."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")


def run(code, env_extra):
    env = {k: v for k, v in os.environ.items() if k not in ("JOBSEARCH_DATA_ROOT", "CLAUDE_PROJECT_DIR")}
    env.update(env_extra)
    out = subprocess.run([sys.executable, "-c", code], cwd=SCRIPTS, env=env, capture_output=True, text=True)
    return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr


VERIFY = "import verify_resume as v; print(v._repo())"
REVIEW = "import review_resume as r; print(r.PANEL_DIR)"


class DataRootOrder(unittest.TestCase):
    def test_verify_first_name_wins(self):
        self.assertEqual(run(VERIFY, {"JOBSEARCH_DATA_ROOT": "/fake-root-a", "CLAUDE_PROJECT_DIR": "/fake-root-b"}), "/fake-root-a")

    def test_verify_second_name(self):
        self.assertEqual(run(VERIFY, {"CLAUDE_PROJECT_DIR": "/fake-root-b"}), "/fake-root-b")

    def test_verify_own_folder(self):
        self.assertEqual(run(VERIFY, {}), ROOT)

    def test_review_first_name_wins(self):
        self.assertEqual(run(REVIEW, {"JOBSEARCH_DATA_ROOT": "/fake-root-a", "CLAUDE_PROJECT_DIR": "/fake-root-b"}),
                         "/fake-root-a/documents/state/resume-panels")

    def test_review_second_name(self):
        self.assertEqual(run(REVIEW, {"CLAUDE_PROJECT_DIR": "/fake-root-b"}), "/fake-root-b/documents/state/resume-panels")

    def test_review_own_folder(self):
        self.assertEqual(run(REVIEW, {}), os.path.join(ROOT, "documents/state/resume-panels"))

    def test_verify_call_time_data_root(self):
        code = "import os, verify_resume as v; os.environ['JOBSEARCH_DATA_ROOT']='/fake-root-c'; print(v._repo())"
        self.assertEqual(run(code, {"CLAUDE_PROJECT_DIR": "/fake-root-b"}), "/fake-root-c")


if __name__ == "__main__":
    unittest.main()
