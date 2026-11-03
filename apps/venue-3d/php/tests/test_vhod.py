"""Формата за входа (php/vhod.php) — целият път през истински PHP сървър, без мрежа навън.

    cd apps/venue-3d && python3 -m unittest discover -s php/tests -v

Вход с ПИН → запис на състояние → status.json, който страницата приема (проверява се със същия
core/status.js през node). Пропуска се, ако няма php (или node за последната проверка).
"""
import http.cookiejar
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PHP_DIR = os.path.dirname(HERE)
APP = os.path.dirname(PHP_DIR)
PHP = shutil.which("php")
NODE = shutil.which("node")
PIN_NORTH, PIN_BOSS = "482913", "905127"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


@unittest.skipUnless(PHP, "няма php")
class Vhod(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        site = os.path.join(cls.tmp.name, "public_html", "sgrada")
        os.makedirs(site)
        for f in ("vhod.php", "lib.php"):
            shutil.copy(os.path.join(PHP_DIR, f), site)
        shutil.copy(os.path.join(APP, "site", "venue.json"), site)
        cls.status = os.path.join(site, "status.json")
        cls.state = os.path.join(cls.tmp.name, "state")
        hashes = {pin: subprocess.check_output([PHP, "-r", f'echo password_hash("{pin}", PASSWORD_DEFAULT);'], text=True)
                  for pin in (PIN_NORTH, PIN_BOSS)}
        cls.cfg = os.path.join(cls.tmp.name, "venue3d_config.php")
        with open(os.path.join(cls.tmp.name, "cfg.json"), "w", encoding="utf-8") as f:
            json.dump({
                "venue_json": os.path.join(site, "venue.json"), "status_json": cls.status, "state_dir": cls.state,
                "timezone": "Europe/Sofia", "max_age_min": 30, "salt": "test",
                "people": {"Северен вход": {"pin": hashes[PIN_NORTH], "points": ["north"]},
                           "Отговорник": {"pin": hashes[PIN_BOSS], "points": "*"}},
            }, f, ensure_ascii=False)
        with open(cls.cfg, "w") as f:   # хешовете съдържат $ — през JSON, не в PHP низ
            f.write("<?php return json_decode(file_get_contents(__DIR__ . '/cfg.json'), true);")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        env = dict(os.environ, VENUE3D_CONFIG=cls.cfg)
        cls.proc = subprocess.Popen([PHP, "-S", f"127.0.0.1:{cls.port}"], cwd=os.path.join(cls.tmp.name, "public_html"),
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.tmp.cleanup()

    def setUp(self):
        if os.path.exists(self.status):
            os.remove(self.status)
        shutil.rmtree(self.state, ignore_errors=True)
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)

    # -------------------------------------------------------------- помощни

    def get(self):
        with self.opener.open(f"http://127.0.0.1:{self.port}/sgrada/vhod.php") as r:
            return r.read().decode()

    def post(self, data, csrf=None):
        page = self.get()
        token = csrf if csrf is not None else re.search(r'name="csrf" value="([0-9a-f]+)"', page).group(1)
        body = urllib.parse.urlencode(dict(data, csrf=token)).encode()
        try:
            self.opener.open(f"http://127.0.0.1:{self.port}/sgrada/vhod.php", body)
        except urllib.error.HTTPError as e:   # 303 → към формата (без автоматично следване)
            self.assertEqual(e.code, 303)
        return self.get()

    def login(self, pin):
        return self.post({"act": "login", "pin": pin})

    def saved(self):
        with open(self.status, encoding="utf-8") as f:
            return json.load(f)

    # -------------------------------------------------------------- тестове

    def test_pin_screen_without_session(self):
        page = self.get()
        self.assertIn('name="pin"', page)
        self.assertNotIn("Северен вход (главен)", page)

    def test_wrong_pin_then_pause_after_five(self):
        for _ in range(5):
            self.assertIn("Грешен ПИН", self.login("000000"))
        self.assertIn("Твърде много грешни ПИН-ове", self.login(PIN_NORTH))   # дори верният — паузата важи
        with open(os.path.join(self.state, "pin_fails.json")) as f:
            self.assertNotIn("127.0.0.1", f.read())                             # адресът само като отпечатък

    def test_steward_sees_only_own_point_and_sets_state(self):
        page = self.login(PIN_NORTH)
        self.assertIn("Северен вход (главен)", page)
        self.assertNotIn("Южен вход", page)
        page = self.post({"act": "set", "id": "north", "state": "busy", "note_bg": "Опашка\x07 около   10 мин.", "note_en": ""})
        self.assertIn("Записано: Северен вход (главен) — Опашка.", page)
        st = self.saved()
        entry = st["hotspots"]["north"]
        self.assertEqual(entry["state"], "busy")
        self.assertEqual(entry["note"], {"bg": "Опашка около 10 мин."})             # без управляващи знаци
        self.assertRegex(entry["updated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertEqual(st["max_age_min"], 30)
        self.assertNotIn("Северен вход\"", json.dumps(st, ensure_ascii=False))       # без имена на хора
        # чужда точка — отказ, файлът не се пипа
        page = self.post({"act": "set", "id": "south", "state": "open"})
        self.assertIn("Тази точка не е твоя.", page)
        self.assertNotIn("south", self.saved()["hotspots"])
        with open(os.path.join(self.state, "vhod.log"), encoding="utf-8") as f:
            log = [json.loads(line) for line in f]
        self.assertEqual([(e["who"], e["id"], e["state"]) for e in log], [("Северен вход", "north", "busy")])

    def test_confirm_refreshes_only_own_points_and_clear_removes(self):
        self.login(PIN_BOSS)
        self.post({"act": "set", "id": "south", "state": "closed"})
        self.post({"act": "set", "id": "north", "state": "open"})
        # южният е проверен преди час
        st = self.saved()
        st["hotspots"]["south"]["updated"] = "2026-01-01T10:00:00+02:00"
        with open(self.status, "w", encoding="utf-8") as f:
            json.dump(st, f)
        self.assertIn("изтекло", self.get())
        # северният потвърждава — южният остава стар
        self.jar.clear()
        self.login(PIN_NORTH)
        self.assertIn("Потвърдено", self.post({"act": "confirm"}))
        self.assertEqual(self.saved()["hotspots"]["south"]["updated"], "2026-01-01T10:00:00+02:00")
        self.assertIn("Изчистено", self.post({"act": "clear", "id": "north"}))
        self.assertNotIn("north", self.saved()["hotspots"])

    def test_csrf_and_unknown_state_are_refused(self):
        self.login(PIN_NORTH)
        self.assertIn("Формата е остаряла", self.post({"act": "set", "id": "north", "state": "open"}, csrf="00"))
        self.assertIn("Непознато състояние", self.post({"act": "set", "id": "north", "state": "maybe"}))
        self.assertFalse(os.path.exists(self.status))
        self.assertIn('name="pin"', self.post({"act": "logout"}))

    def test_output_is_escaped(self):
        self.login(PIN_NORTH)
        page = self.post({"act": "set", "id": "north", "state": "open", "note_bg": '<script>alert(1)</script>"'})
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    @unittest.skipUnless(NODE, "няма node")
    def test_written_file_is_what_the_page_accepts(self):
        self.login(PIN_BOSS)
        self.post({"act": "set", "id": "north", "state": "busy", "note_bg": "Опашка", "note_en": "Queue"})
        self.post({"act": "set", "id": "tickets", "state": "closed"})
        script = (
            "import { parseStatus, stateOf } from './core/status.js';"
            "import { parseVenue } from './core/venue-data.js';"
            "import { readFileSync } from 'node:fs';"
            "const ids = parseVenue(JSON.parse(readFileSync('site/venue.json','utf8'))).venue.hotspots.map(h => h.id);"
            f"const r = parseStatus(JSON.parse(readFileSync({json.dumps(self.status)},'utf8')), ids);"
            "console.log(JSON.stringify({errors: r.errors, warnings: r.warnings,"
            " north: stateOf(r.status,'north'), tickets: stateOf(r.status,'tickets')?.state}));"
        )
        out = json.loads(subprocess.check_output([NODE, "--input-type=module", "-e", script], cwd=APP, text=True))
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["north"]["state"], "busy")
        self.assertEqual(out["north"]["note"], {"bg": "Опашка", "en": "Queue"})
        self.assertEqual(out["tickets"], "closed")


if __name__ == "__main__":
    unittest.main()
