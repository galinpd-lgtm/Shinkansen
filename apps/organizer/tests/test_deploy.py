"""Тестове на deploy — без истински cPanel: подставен cPanel върху временна папка и PHP сървър за „отвън“.
Отделно — клиентът за cPanel срещу малък HTTP сървър (заглавката с токена, адресите, качването).

    cd apps/organizer && python3 -m unittest discover -s tests -v
"""
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import urllib.parse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
import deploy  # noqa: E402
import ops  # noqa: E402
import organizer  # noqa: E402

EXAMPLE = os.path.join(APP, "examples", "intensive")
NOW = datetime(2026, 10, 1, 9, 30)


class FakeCpanel:
    """Същите методи като deploy.Cpanel, но върху папка „домашна директория“."""

    def __init__(self, home):
        self.home, self.calls = home, []

    def _p(self, rel):
        return os.path.join(self.home, rel)

    def list(self, d):
        self.calls.append(("list", d))
        p = self._p(d)
        return {n: "dir" if os.path.isdir(os.path.join(p, n)) else "file" for n in os.listdir(p)} if os.path.isdir(p) else {}

    def read(self, d, name):
        with open(os.path.join(self._p(d), name), encoding="utf-8") as f:
            return f.read()

    def mkdir(self, parent, name):
        self.calls.append(("mkdir", parent, name))
        os.makedirs(os.path.join(self._p(parent), name), exist_ok=True)

    def rename(self, src, dst):
        self.calls.append(("rename", src, dst))
        os.rename(self._p(src), self._p(dst))

    def extract(self, archive, dest):
        self.calls.append(("extract", archive, dest))
        with tarfile.open(self._p(archive)) as t:
            t.extractall(self._p(dest), filter="data")

    def save(self, d, name, content):
        with open(os.path.join(self._p(d), name), "w", encoding="utf-8") as f:
            f.write(content)

    def upload(self, d, path):
        self.calls.append(("upload", d, os.path.basename(path)))
        shutil.copyfile(path, os.path.join(self._p(d), os.path.basename(path)))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(shutil.which("php"), "няма php")
class Deploy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        site = os.path.join(cls.tmp, "site")
        organizer.build(EXAMPLE, site)
        cls.pkg = ops.package(site, os.path.join(cls.tmp, "pkgs"), name="primer")["tgz"]
        cls.home = os.path.join(cls.tmp, "home")
        os.makedirs(os.path.join(cls.home, "public_html", "ai-start"))
        with open(os.path.join(cls.home, "public_html", "ai-start", "star.html"), "w") as f:
            f.write("старата версия")
        with open(os.path.join(cls.home, "public_html", ".htaccess"), "w") as f:
            f.write("RewriteEngine On\nRewriteRule ^(.*)$ index.php [L]\n")
        cfgphp = os.path.join(cls.tmp, "db.php")
        with open(cfgphp, "w") as f:
            f.write("<?php return ['db' => ['dsn' => 'sqlite:%s'], 'auto_create' => true, 'salt' => 't'];"
                    % os.path.join(cls.tmp, "db.sqlite"))
        cls.port = free_port()
        cls.php = subprocess.Popen(["php", "-S", "127.0.0.1:%d" % cls.port], cwd=os.path.join(cls.home, "public_html"),
                                   env=dict(os.environ, ORGANIZER_CONFIG=cfgphp),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        cls.cfg = {"public_html": "public_html", "dir": "ai-start",
                   "site_url": "http://127.0.0.1:%d/ai-start/" % cls.port}

    @classmethod
    def tearDownClass(cls):
        cls.php.terminate()
        cls.php.wait(5)
        shutil.rmtree(cls.tmp)

    def run_deploy(self, **kw):
        cp = FakeCpanel(self.home)
        steps = deploy.deploy(self.pkg, self.cfg, client=cp, now=NOW, log=lambda *_: None, wait=lambda s: None, **kw)
        return steps, cp

    def test_1_plan_changes_nothing(self):
        steps, cp = self.run_deploy()
        self.assertFalse([c for c in cp.calls if c[0] != "list"], cp.calls)
        self.assertTrue(any("преименувам public_html/ai-start" in n for n, _, _ in steps))
        self.assertTrue(any(".htaccess" in n and "RewriteRule" in note for n, _, note in steps))
        self.assertTrue(os.path.exists(os.path.join(self.home, "public_html", "ai-start", "star.html")))

    def test_2_go_stops_on_unread_htaccess(self):
        steps, cp = self.run_deploy(go=True)
        self.assertEqual(steps[-1][1], False)
        self.assertFalse([c for c in cp.calls if c[0] != "list"], cp.calls)

    def test_3_go_archives_uploads_checks(self):
        steps, cp = self.run_deploy(go=True, htaccess_ok=True)
        res = {n: (ok, note) for n, ok, note in steps}
        pub = os.path.join(self.home, "public_html")
        self.assertTrue(os.path.exists(os.path.join(pub, "_ARHIV_ai-start_2026-10-01_0930", "star.html")))  # не е изтрито
        self.assertTrue(os.path.exists(os.path.join(pub, "_ARHIV_uploads", os.path.basename(self.pkg))))
        self.assertTrue(os.path.exists(os.path.join(pub, "ai-start", "index.html")))
        self.assertTrue(res["маркерът се вижда отвън"][0])
        self.assertTrue(res["всички страници 200 и noindex"][0], res)
        self.assertTrue(res["тестов отговор („Записване“)"][0], res)
        ok, note = res["admin/ иска вход"]                       # php -S не иска парола → 403
        self.assertFalse(ok)
        self.assertIn("ЗАКЛЮЧИ admin/", note)

    def test_4_bad_checksum_refuses(self):
        bad = os.path.join(self.tmp, "bad.tgz")
        shutil.copyfile(self.pkg, bad)
        with open(bad + ".sha256", "w") as f:
            f.write("0" * 64 + "  bad.tgz\n")
        steps = deploy.deploy(bad, self.cfg, client=FakeCpanel(self.home), log=lambda *_: None)
        self.assertEqual(steps, [("SHA-256 на пакета", False, "0000000000000000…")])


class Handler(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _reply(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        Handler.seen.append(("GET", u.path, q, self.headers.get("Authorization")))
        if u.path == "/execute/Fileman/list_files":
            self._reply({"status": 1, "data": [{"file": "ai-start", "type": "dir"}]})
        elif u.path == "/json-api/cpanel":
            self._reply({"cpanelresult": {"data": [{"result": 1}], "event": {"result": 1}}})
        else:
            self._reply({"status": 0, "errors": ["непознато"]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        Handler.seen.append(("POST", self.path, body, self.headers.get("Authorization")))
        self._reply({"status": 1, "data": {"failed": 0, "uploads": []}})


class Client(unittest.TestCase):
    def setUp(self):
        Handler.seen = []
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.cp = deploy.Cpanel("http://127.0.0.1:%d" % self.srv.server_port, "user1", "TOKEN123")

    def tearDown(self):
        self.srv.shutdown()

    def test_requests(self):
        self.assertEqual(self.cp.list("public_html"), {"ai-start": "dir"})
        self.cp.rename("public_html/a", "public_html/b")
        with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as f:
            f.write(b"\x1f\x8b" + "ПАКЕТ".encode())
        self.cp.upload("public_html/_ARHIV_uploads", f.name)
        os.remove(f.name)
        get_list, api2, post = Handler.seen
        self.assertEqual(get_list[3], "cpanel user1:TOKEN123")
        self.assertEqual(get_list[2]["dir"], "public_html")
        self.assertEqual((api2[2]["cpanel_jsonapi_func"], api2[2]["op"], api2[2]["destfiles"]), ("fileop", "rename", "public_html/b"))
        self.assertEqual(post[1], "/execute/Fileman/upload_files")
        self.assertIn(b'name="dir"\r\n\r\npublic_html/_ARHIV_uploads', post[2])
        self.assertIn(b'name="overwrite"\r\n\r\n0', post[2])
        self.assertIn(b"\x1f\x8b" + "ПАКЕТ".encode(), post[2])

    def test_errors_and_token_not_in_message(self):
        with self.assertRaises(deploy.CpanelError) as cm:
            self.cp.uapi("Fileman", "nyama")
        self.assertNotIn("TOKEN123", str(cm.exception))


class Config(unittest.TestCase):
    def test_token_from_file_and_checks(self):
        with tempfile.TemporaryDirectory() as d:
            tok = os.path.join(d, "t")
            with open(tok, "w") as f:
                f.write("abc\n")
            cfg = {"cpanel": "https://x:2083", "user": "u", "public_html": "public_html", "dir": "ai-start",
                   "site_url": "https://example.org/ai-start/", "token_file": tok}
            p = os.path.join(d, "c.json")
            with open(p, "w") as f:
                json.dump(cfg, f)
            self.assertEqual(deploy.load_config(p)["_token"], "abc")
            cfg["dir"] = "../etc"
            with open(p, "w") as f:
                json.dump(cfg, f)
            with self.assertRaises(ValueError):
                deploy.load_config(p)


if __name__ == "__main__":
    unittest.main()
