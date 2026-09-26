"""Тестове без мрежа. Тайните в теста се сглобяват на части, за да не хваща филтърът самия тест.

    python3 -m unittest discover -s skills/leak-filter/tests -v
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import leak_filter as lf  # noqa: E402

PRIVATE_IP = ".".join(["10", "20", "30", "40"])
AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
GH = "gh" + "p_" + "a1" * 20
PEM = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
HOME = "/ho" + "me/" + "ivan/projects"


def kinds(line, words=None):
    return [k for k, _ in lf.scan_line(line, lf.compile_words(words or []))]


class Lines(unittest.TestCase):
    def test_ip(self):
        self.assertEqual(kinds("host = %s" % PRIVATE_IP), ["ip"])
        self.assertEqual(kinds("demo 192.0.2.10, 198.51.100.7, 203.0.113.9, 127.0.0.1, 0.0.0.0"), [])
        self.assertEqual(kinds("version 1.2.3.4.5 and 999.1.1.1"), [])

    def test_home_paths(self):
        self.assertEqual(kinds("cd " + HOME), ["home-path"])
        self.assertEqual(kinds("cd /Us" + "ers/maria/Desktop"), ["home-path"])
        self.assertEqual(kinds(r"C:\Us" + r"ers\petar\file.txt"), ["home-path"])
        self.assertEqual(kinds("/home/user/Shinkansen and /home/runner/work"), [])

    def test_secrets(self):
        self.assertEqual(kinds("key=" + AWS), ["aws-key"])
        self.assertEqual(kinds("token: " + GH), ["github-token"])
        self.assertEqual(kinds(PEM), ["private-key"])
        self.assertEqual(kinds('password = "' + "hunter2hunter2" + '"'), ["assigned-secret"])
        self.assertEqual(kinds("https://bob:" + "s3cretpw@example.org/x"), ["url-password"])
        self.assertEqual(kinds('password = ""'), [])
        self.assertEqual(kinds("the token is required"), [])

    def test_words_whole_word_case_insensitive_cyrillic(self):
        self.assertEqual(kinds("ssh Example-Host now", ["example-host"]), ["word"])
        self.assertEqual(kinds("examplehostile", ["examplehost"]), [])
        self.assertEqual(kinds("отиди в Сървърната", ["сървърната"]), ["word"])

    def test_ignore_mark_and_mask(self):
        self.assertEqual(kinds("ip %s  # leak-filter: ignore" % PRIVATE_IP), [])
        self.assertEqual(lf.mask(AWS), "AKIA…******")
        self.assertNotIn("ABCDEF", lf.mask(AWS))


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org")
    subprocess.run(["git", "-C", repo] + list(args), check=True, capture_output=True, env=env)


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("line one\nserver %s\n" % PRIVATE_IP)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "one")
        # поправката: адресът изчезва от файла, но остава в историята
        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("line one\nserver 192.0.2.1\n")
        git(self.repo, "commit", "-q", "-am", "fix")
        # клон с тайна, който не е слят
        git(self.repo, "checkout", "-q", "-b", "side")
        with open(os.path.join(self.repo, "b.txt"), "wb") as f:
            f.write(("k = " + AWS + "\n").encode())
        with open(os.path.join(self.repo, "bin.dat"), "wb") as f:
            f.write(b"\0\1" + PRIVATE_IP.encode())
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "side")
        git(self.repo, "checkout", "-q", "main")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = lf.main(list(args))
        return code, buf.getvalue()

    def test_tree_clean_history_not(self):
        self.assertEqual(lf.scan_tree(self.repo), [])
        hist = lf.dedupe_history(lf.scan_history(self.repo))
        got = sorted((h["file"], h["line"], h["kind"]) for h in hist)
        self.assertEqual(got, [("a.txt", 2, "ip"), ("b.txt", 1, "aws-key")])
        code, out = self.run_main(self.repo)
        self.assertEqual(code, 4)
        self.assertIn("a.txt:2", out)
        self.assertIn("история", out)
        self.assertNotIn(PRIVATE_IP, out)             # отчетът не повтаря находката изцяло

    def test_no_history_is_clean(self):
        code, out = self.run_main(self.repo, "--no-history")
        self.assertEqual(code, 0)
        self.assertIn("ЧИСТО", out)

    def test_words_file_inside_repo_warns(self):
        words = os.path.join(self.repo, "words.txt")
        with open(words, "w") as f:
            f.write("# коментар\nline one\n")
        code, out = self.run_main(self.repo, "--words", words, "--json")
        data = json.loads(out)
        self.assertEqual(code, 4)
        self.assertTrue(any("вътре в репото" in w for w in data["warnings"]))
        self.assertTrue(any(f["kind"] == "word" for f in data["tree"]))

    def test_never_modifies(self):
        before = subprocess.run(["git", "-C", self.repo, "rev-parse", "--all"], capture_output=True).stdout
        with open(os.path.join(self.repo, "a.txt")) as f:
            content = f.read()
        self.run_main(self.repo)
        after = subprocess.run(["git", "-C", self.repo, "rev-parse", "--all"], capture_output=True).stdout
        self.assertEqual(before, after)
        with open(os.path.join(self.repo, "a.txt")) as f:
            self.assertEqual(f.read(), content)

    def test_not_a_repo(self):
        d = os.path.join(self.tmp.name, "plain")
        os.makedirs(d)
        code, out = self.run_main(d)
        self.assertEqual(code, 0)
        self.assertIn("не е git", out)


if __name__ == "__main__":
    unittest.main()
