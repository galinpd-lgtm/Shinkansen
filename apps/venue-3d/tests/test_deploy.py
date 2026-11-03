"""Тестове на deploy.py — без истински cPanel: подставен cPanel върху временна папка и PHP сървър „отвън“.

    cd apps/venue-3d && python3 -m unittest discover -s tests -v

Сградата е измислената арена (site/venue.json + models/arena.example.glb). Пътят: build → package →
план (нищо не се пипа) → качване (старата папка се архивира, status.json се пренася) → формата отговаря.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
import deploy  # noqa: E402  (apps/venue-3d/deploy.py; внася и организатора)

PHP = shutil.which("php")
NOW = datetime(2026, 11, 3, 18, 5)


def make_building(root, **venue_changes):
    os.makedirs(root)
    with open(os.path.join(APP, "site", "venue.json"), encoding="utf-8") as f:
        venue = json.load(f)
    venue.update(venue_changes)
    with open(os.path.join(root, "venue.json"), "w", encoding="utf-8") as f:
        json.dump(venue, f, ensure_ascii=False)
    shutil.copy(os.path.join(APP, "models", "arena.example.glb"), os.path.join(root, "model.glb"))
    shutil.copy(os.path.join(APP, "blender", "skeleton.example.json"), os.path.join(root, "skeleton.json"))
    with open(os.path.join(root, "бележки-за-клиента.txt"), "w") as f:   # не бива да стигне до сървъра
        f.write("вътрешно")
    return root


class FakeCpanel:
    """Същите методи като Cpanel на организатора, но върху папка „домашна директория“."""

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
        self.calls.append(("save", d, name))
        with open(os.path.join(self._p(d), name), "w", encoding="utf-8") as f:
            f.write(content)

    def upload(self, d, path):
        self.calls.append(("upload", d, os.path.basename(path)))
        shutil.copyfile(path, os.path.join(self._p(d), os.path.basename(path)))


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_only_referenced_files_and_the_page(self):
        b = make_building(os.path.join(self.tmp, "arena"))
        out = os.path.join(self.tmp, "out")
        r = deploy.build(b, out, form=True, refresh=30)
        self.assertEqual(r["files"], ["venue.json", "model.glb", "skeleton.json"])
        self.assertFalse(os.path.exists(os.path.join(out, "бележки-за-клиента.txt")))
        with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn('<venue-3d src="venue.json" status="status.json" refresh="30"></venue-3d>', page)
        for rel in ("core/venue-3d.js", "core/status.js", "vendor/three/build/three.module.js",
                    "vendor/three/examples/jsm/libs/draco/gltf/draco_decoder.wasm",
                    "vhod/vhod.php", "vhod/lib.php", "vhod/.htaccess", ".htaccess"):
            self.assertTrue(os.path.exists(os.path.join(out, rel)), rel)
        self.assertFalse(os.path.exists(os.path.join(out, "status.json")))     # пише го формата, не пакетът
        self.assertFalse(os.path.exists(os.path.join(out, "vhod", "config.sample.php")))
        with self.assertRaises(ValueError):
            deploy.build(b, out)                                                # не пипа непразна папка

    def test_without_form_the_page_has_no_status(self):
        out = os.path.join(self.tmp, "out")
        deploy.build(make_building(os.path.join(self.tmp, "arena")), out)
        with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
            self.assertIn('<venue-3d src="venue.json"></venue-3d>', f.read())
        self.assertFalse(os.path.exists(os.path.join(out, "vhod")))

    def test_bad_buildings_are_refused(self):
        for i, (changes, want) in enumerate([
            ({"model": "../../etc/passwd"}, "относителен път"),
            ({"model": "https://cdn.example/model.glb"}, "относителен път"),
            ({"model": "липсва.glb", "skeleton": None}, "няма файл"),
            ({"hotspots": [{"id": "Север"}]}, "негодни id"),
            ({"hotspots": [{"id": "a"}, {"id": "a"}]}, "повтарящи се"),
        ]):
            b = make_building(os.path.join(self.tmp, f"b{i}"), **changes)
            with self.assertRaises(ValueError) as e:
                deploy.build(b, os.path.join(self.tmp, f"o{i}"))
            self.assertIn(want, str(e.exception))
        _, _, errors, warnings = deploy.check_building(make_building(os.path.join(self.tmp, "n"), north_deg=None))
        self.assertEqual(errors, [])
        self.assertTrue(any("north_deg" in w for w in warnings))


@unittest.skipUnless(PHP, "няма php")
class Deploy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        site = os.path.join(cls.tmp, "site")
        deploy.build(make_building(os.path.join(cls.tmp, "arena")), site, form=True)
        import ops
        cls.pkg = ops.package(site, os.path.join(cls.tmp, "pkgs"), name="sgrada")["tgz"]
        cls.home = os.path.join(cls.tmp, "home")
        old = os.path.join(cls.home, "public_html", "sgrada")
        os.makedirs(old)
        with open(os.path.join(old, "index.html"), "w") as f:
            f.write("старата версия")
        cls.status = {"schema_version": "1", "updated": "2026-11-03T18:00:00+02:00",
                      "hotspots": {"north": {"state": "busy", "updated": "2026-11-03T18:00:00+02:00"}}}
        with open(os.path.join(old, "status.json"), "w") as f:
            json.dump(cls.status, f)
        cls.port = cls._free_port()
        cls.php = subprocess.Popen([PHP, "-S", "127.0.0.1:%d" % cls.port], cwd=os.path.join(cls.home, "public_html"),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        cls.cfg = {"public_html": "public_html", "dir": "sgrada", "site_url": "http://127.0.0.1:%d/sgrada/" % cls.port}

    @staticmethod
    def _free_port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    @classmethod
    def tearDownClass(cls):
        cls.php.terminate()
        cls.php.wait(5)
        shutil.rmtree(cls.tmp)

    def write_config(self):
        # vhod.php търси ~/venue3d_config.php — папката над DOCUMENT_ROOT (public_html)
        pub = os.path.join(self.home, "public_html", "sgrada")
        with open(os.path.join(self.home, "venue3d_config.php"), "w") as f:
            f.write("<?php return ['venue_json' => '%s/venue.json', 'status_json' => '%s/status.json', "
                    "'state_dir' => '%s/state', 'people' => ['x' => ['pin' => 'нищо', 'points' => '*']]];"
                    % (pub, pub, self.home))

    def run_deploy(self, **kw):
        cp = FakeCpanel(self.home)
        logs = []
        steps = deploy.deploy(self.pkg, self.cfg, client=cp, now=NOW, log=logs.append, wait=lambda s: None, **kw)
        return steps, cp, logs

    def test_1_plan_changes_nothing(self):
        steps, cp, logs = self.run_deploy()
        self.assertFalse([c for c in cp.calls if c[0] != "list"], cp.calls)
        self.assertTrue(any("преименувам public_html/sgrada" in n for n, _, _ in steps))
        self.assertTrue(any("status.json се пренася" in line for line in logs))
        self.assertFalse([line for line in logs if "тестов отговор" in line or "износ" in line])   # за въпросниците

    def test_2_upload_keeps_status_and_checks_the_form(self):
        self.write_config()
        steps, cp, logs = self.run_deploy(go=True)
        failed = [s for s in steps if s[1] is False]
        self.assertEqual(failed, [], "\n".join(logs))
        archive = os.path.join(self.home, "public_html", "_ARHIV_sgrada_2026-11-03_1805")
        self.assertTrue(os.path.exists(os.path.join(archive, "status.json")))          # нищо не е изтрито
        with open(os.path.join(self.home, "public_html", "sgrada", "status.json")) as f:
            self.assertEqual(json.load(f), self.status)                                # пренесен
        names = [n for n, _, _ in steps]
        self.assertIn("status.json пренесен от _ARHIV_sgrada_2026-11-03_1805", names)
        self.assertTrue(any(n == "формата за входа" and ok for n, ok, _ in steps))
        self.assertTrue(any(n == "venue.json отвън" and ok for n, ok, _ in steps))

    def test_3_missing_server_config_is_reported(self):
        os.remove(os.path.join(self.home, "venue3d_config.php"))
        cp = FakeCpanel(self.home)
        steps = deploy.after_deploy({"vhod/vhod.php"}, self.cfg, cp, None, log=lambda *_: None)
        form = next(s for s in steps if s[0] == "формата за входа")
        self.assertIs(form[1], False)
        self.assertIn("venue3d_config.php", form[2])
        st = next(s for s in steps if s[0].startswith("status.json"))
        self.assertIn("вече има нов запис", st[2])                                    # не пипа новия


if __name__ == "__main__":
    unittest.main()
