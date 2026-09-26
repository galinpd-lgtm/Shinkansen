"""Тестове без външна мрежа — сървърът слуша само на 127.0.0.1, на свободен порт.

    python3 -m unittest discover -s skills/preview-serve/tests -v
"""
import io
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import preview_serve as ps  # noqa: E402


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


class Serve(unittest.TestCase):
    def setUp(self):
        # прокси от средата не бива да прихваща 127.0.0.1
        self._env = {k: os.environ.pop(k) for k in list(os.environ) if k.lower().endswith("_proxy")}
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.site = os.path.join(base, "site")
        os.makedirs(os.path.join(self.site, "sub"))
        os.makedirs(os.path.join(self.site, ".git"))
        with open(os.path.join(self.site, "index.html"), "w") as f:
            f.write("<h1>hello preview</h1>")
        with open(os.path.join(self.site, ".env"), "w") as f:
            f.write("SECRET=1")
        with open(os.path.join(self.site, ".git", "config"), "w") as f:
            f.write("[core]")
        with open(os.path.join(self.site, "sub", "a.txt"), "w") as f:
            f.write("A")
        with open(os.path.join(base, "outside.txt"), "w") as f:
            f.write("outside")
        os.symlink(os.path.join(base, "outside.txt"), os.path.join(self.site, "link.txt"))
        with redirect_stderr(io.StringIO()):
            self.httpd, self.thread, self.timer = ps.start(self.site, "127.0.0.1", 0, seconds=30)
        self.url = "http://127.0.0.1:%d/" % self.httpd.server_address[1]

    def tearDown(self):
        self.timer.cancel()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()
        os.environ.update(self._env)

    def test_serves_files(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(get(self.url), (200, "<h1>hello preview</h1>"))
            self.assertEqual(get(self.url + "sub/a.txt"), (200, "A"))

    def test_hidden_and_outside_are_404(self):
        with redirect_stderr(io.StringIO()):
            for path in (".env", ".git/config", "sub/../.env", "link.txt", "%2eenv"):
                self.assertEqual(get(self.url + path)[0], 404, path)

    def test_listing_hides_dotfiles(self):
        os.remove(os.path.join(self.site, "index.html"))
        with redirect_stderr(io.StringIO()):
            code, body = get(self.url)
        self.assertEqual(code, 200)
        self.assertIn("sub/", body)
        self.assertNotIn(".env", body)
        self.assertNotIn(".git", body)

    def test_read_only(self):
        req = urllib.request.Request(self.url + "new.txt", data=b"x", method="PUT")
        with redirect_stderr(io.StringIO()), self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 501)
        self.assertFalse(os.path.exists(os.path.join(self.site, "new.txt")))


class StopsByItself(unittest.TestCase):
    def test_stops_after_time(self):
        with tempfile.TemporaryDirectory() as d:
            httpd, thread, timer = ps.start(d, "127.0.0.1", 0, seconds=0.3)
            thread.join(5)
            self.assertFalse(thread.is_alive())
            httpd.server_close()


class Hosts(unittest.TestCase):
    def test_loopback(self):
        for h in ("127.0.0.1", "::1", "localhost", "127.0.1.1"):
            self.assertTrue(ps.is_loopback(h), h)
        for h in ("0.0.0.0", "192.0.2.10", "example-host"):
            self.assertFalse(ps.is_loopback(h), h)

    def test_bad_args(self):
        with tempfile.TemporaryDirectory() as d, redirect_stderr(io.StringIO()):
            for args in ([d, "--minutes", "0"], [d, "--minutes", "999"], [d, "--port", "70000"],
                         [os.path.join(d, "none")]):
                with self.assertRaises(SystemExit) as cm:
                    ps.main(args)
                self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
