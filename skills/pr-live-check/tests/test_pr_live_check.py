"""Тестове без мрежа: „отдалеченото“ хранилище е локално, с ref refs/pull/1/head като в GitHub.

    python3 -m unittest discover -s skills/pr-live-check/tests -v
"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pr_live_check as plc  # noqa: E402

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org")


def sh(cwd, *args):
    return subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


PASSING = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
FAILING = ("import unittest\nclass T(unittest.TestCase):\n    def test_bad(self):\n"
           "        self.assertEqual(1, 2, 'counted wrong')\n")


class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.origin = os.path.join(t, "origin.git")
        seed = os.path.join(t, "seed")
        os.makedirs(seed)
        sh(seed, "git", "init", "-q", "-b", "main")
        write(os.path.join(seed, "app/tests/test_a.py"), PASSING)
        sh(seed, "git", "add", "-A")
        sh(seed, "git", "commit", "-q", "-m", "base")
        # PR 1: добавя паднал тест; PR 2: всичко минава
        sh(seed, "git", "checkout", "-q", "-b", "pr1")
        write(os.path.join(seed, "lib/tests/test_b.py"), FAILING)
        sh(seed, "git", "add", "-A")
        sh(seed, "git", "commit", "-q", "-m", "PR one: broken")
        sh(seed, "git", "checkout", "-q", "main")
        sh(seed, "git", "checkout", "-q", "-b", "feature")
        write(os.path.join(seed, "app/extra.txt"), "x\n")
        sh(seed, "git", "add", "-A")
        sh(seed, "git", "commit", "-q", "-m", "feature ok")
        sh(t, "git", "clone", "-q", "--bare", seed, self.origin)
        sh(self.origin, "git", "update-ref", "refs/pull/1/head", "refs/heads/pr1")
        # локалното хранилище, от което се пуска проверката
        self.local = os.path.join(t, "local")
        sh(t, "git", "clone", "-q", self.origin, self.local)
        self.refs_before = sh(self.local, "git", "for-each-ref")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = plc.main(["--repo", self.local] + list(args))
        return code, out.getvalue(), err.getvalue()

    def test_pr_with_failing_test(self):
        code, out, _ = self.run_main("--pr", "1")
        self.assertEqual(code, 4)
        self.assertIn("PR #1", out)
        self.assertIn("PR one: broken", out)
        self.assertIn("ok       unittest app", out)
        self.assertIn("ПАДНА (1) unittest lib", out)
        self.assertIn("counted wrong", out)
        self.assertIn("ПАДНАХА 1 от 2", out)
        self.assertLessEqual(len(out.strip().splitlines()), 20)

    def test_ref_with_explicit_test_and_live(self):
        code, out, _ = self.run_main("--ref", "feature", "--test", "test -f app/extra.txt",
                                     "--live", "echo live-output; exit 3")
        self.assertEqual(code, 4)
        self.assertIn("ok       test: test -f app/extra.txt", out)
        self.assertIn("ПАДНА (3) live:", out)
        self.assertIn("live-output", out)

    def test_local_repo_untouched_and_workdir_removed(self):
        before = set(os.listdir(tempfile.gettempdir()))
        self.run_main("--pr", "1")
        self.assertEqual(sh(self.local, "git", "for-each-ref"), self.refs_before)
        self.assertEqual(sh(self.local, "git", "status", "--porcelain"), "")
        left = [d for d in set(os.listdir(tempfile.gettempdir())) - before if d.startswith("pr-live-check-")]
        self.assertEqual(left, [])

    def test_missing_pr(self):
        code, _, err = self.run_main("--pr", "99")
        self.assertEqual(code, 1)
        self.assertIn("не можах да изтегля", err)

    def test_timeout(self):
        code, out, _ = self.run_main("--ref", "main", "--test", "sleep 5", "--timeout", "1")
        self.assertEqual(code, 4)
        self.assertIn("ТАЙМАУТ", out)


class Report(unittest.TestCase):
    def test_capped_at_20_lines(self):
        results = [{"label": "t%d" % i, "ok": i % 2 == 0, "code": 1, "secs": 0.1,
                    "tail": ["line a", "line b", "line c", "line d"]} for i in range(30)]
        text = plc.report("PR #9 · abc · x", results)
        self.assertLessEqual(len(text.splitlines()), 20)
        self.assertTrue(text.splitlines()[-1].startswith("ПАДНАХА 15 от 30"))

    def test_no_tests_is_not_success(self):
        self.assertIn("НЯМА ТЕСТОВЕ", plc.report("x", []))


if __name__ == "__main__":
    unittest.main()
