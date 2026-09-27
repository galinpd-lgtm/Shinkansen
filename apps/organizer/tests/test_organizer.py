"""Тестове на организатора — без мрежа. PHP частта се изпитва само ако има php (иначе се пропуска).

    cd apps/organizer && python3 -m unittest discover -s tests -v
"""
import copy
import csv
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
import organizer  # noqa: E402

EXAMPLE = os.path.join(APP, "examples", "intensive")
PHP = shutil.which("php")


def example():
    return organizer.load(EXAMPLE)


def write_event(folder, event, people=None):
    with open(os.path.join(folder, "event.json"), "w", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False)
    with open(os.path.join(folder, "people.json"), "w", encoding="utf-8") as f:
        json.dump(people or {"speakers": [], "partners": []}, f, ensure_ascii=False)


class Check(unittest.TestCase):
    def test_example_has_no_errors(self):
        errors, todo = organizer.check(*example())
        self.assertEqual(errors, [])
        self.assertTrue(any("търсачките" in t for t in todo))

    def bad(self, mutate, needle):
        event, people = example()
        event = copy.deepcopy(event)
        mutate(event, people)
        errors, _ = organizer.check(event, people)
        self.assertTrue(any(needle in e for e in errors), errors)

    def test_schedule_points_to_missing_topic(self):
        self.bad(lambda e, p: e["schedule"][0]["slots"][1].update(topics=[99]), "несъществуваща тема 99")

    def test_day_outside_dates(self):
        self.bad(lambda e, p: e["schedule"][0].update(date="2030-06-01"), "извън dates")

    def test_overlapping_slots(self):
        self.bad(lambda e, p: e["schedule"][0]["slots"][1].update({"from": "18:10"}), "застъпва")

    def test_unknown_lab_role(self):
        self.bad(lambda e, p: e["topics"][0]["lab"].update(pilot=["x"]), "непозната роля")

    def test_reserved_form_slug(self):
        self.bad(lambda e, p: e["forms"][0].update(slug="programa"), "slug е зает")

    def test_bad_color_and_font(self):
        self.bad(lambda e, p: e["theme"].update(accent="red"), "theme.accent")
        self.bad(lambda e, p: e["theme"].update(font_body="x;}body{display:none"), "theme.font_body")

    def test_fonts_only_from_google(self):
        self.bad(lambda e, p: e["theme"].update(fonts_css="https://evil.example/f.css"), "fonts_css")

    def test_person_without_name_or_js_link(self):
        self.bad(lambda e, p: p.update(speakers=[{"role": "x"}]), "липсва name")
        self.bad(lambda e, p: p.update(speakers=[{"name": "А", "link": "javascript:alert(1)"}]), ".link")

    def test_required_if_points_to_missing_field(self):
        self.bad(lambda e, p: e["forms"][0]["fields"][-1].update(required_if=["nyama"]), "required_if")


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = cls.tmp.name
        cls.written, cls.todo = organizer.build(EXAMPLE, cls.out)
        cls.event, _ = example()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def read(self, rel):
        with open(os.path.join(self.out, rel), encoding="utf-8") as f:
            return f.read()

    def test_pages(self):
        for rel in ("index.html", "programa.html", "razpisanie.html", "anketa.html", "tehnika.html",
                    "tema-01.html", "tema-02.html", "tema-03.html", "people.json", "api/forms.json",
                    "api/submit.php", "api/lib.php", "export/index.php", ".htaccess", "assets/present.js"):
            self.assertIn(rel, self.written)

    def test_hidden_until_go(self):
        for rel in self.written:
            if rel.endswith(".html"):
                self.assertIn('<meta name="robots" content="noindex, nofollow">', self.read(rel), rel)
        self.assertIn('X-Robots-Tag "noindex, nofollow"', self.read(".htaccess"))
        self.assertNotIn("sitemap.xml", self.written)

    def test_go_makes_it_indexable(self):
        event = copy.deepcopy(self.event)
        event["publish"] = {"indexable": True, "base_url": "https://example.org/ev/"}
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            write_event(src, event)
            written, _ = organizer.build(src, out)
            with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
                page = f.read()
            self.assertIn('content="index, follow"', page)
            self.assertIn('<link rel="canonical" href="https://example.org/ev/">', page)
            self.assertIn("sitemap.xml", written)
            with open(os.path.join(out, ".htaccess"), encoding="utf-8") as f:
                self.assertNotIn("X-Robots-Tag", f.read())

    def test_every_page_has_slides_and_present_mode(self):
        for rel in self.written:
            if rel.endswith(".html"):
                page = self.read(rel)
                self.assertIn("data-slide", page, rel)
                self.assertIn('src="assets/present.js"', page, rel)

    def test_lab_has_all_roles_in_order(self):
        page = self.read("tema-01.html")
        labels = re.findall(r'<article class="lab-col"><h3>([^<]+)</h3>', page)
        self.assertEqual(labels, [r["label"] for r in self.event["lab_roles"]])
        self.assertIn("--cols:4", page)

    def test_topic_sections_and_demo(self):
        page = self.read("tema-02.html")
        self.assertIn("<h2>Видове информация</h2>", page)
        self.assertIn("<h2>Бази</h2>", page)
        self.assertIn("Демо на живо", page)
        self.assertNotIn('class="block demo"', self.read("tema-03.html"))

    def test_placeholders_for_people(self):
        page = self.read("index.html")
        self.assertEqual(page.count('class="person empty"'), 8)

    def test_form_options_from_topics(self):
        page = self.read("anketa.html")
        for t in self.event["topics"]:
            self.assertIn('value="%d. %s"' % (t["n"], t["title"]), page)
        spec = json.loads(self.read("api/forms.json"))
        temi = next(f for f in spec["forms"]["zapis"]["fields"] if f["id"] == "temi")
        self.assertEqual(temi["max"], 3)
        self.assertEqual(len(temi["options"]), len(self.event["topics"]))

    def test_no_secrets_in_output(self):
        for rel in self.written:
            text = self.read(rel)
            self.assertNotRegex(text, r"(?i)password\s*=|'pass'\s*=>\s*'[^'П]", rel)

    def test_demo_has_no_php(self):
        with tempfile.TemporaryDirectory() as out:
            written, _ = organizer.build(EXAMPLE, out, demo=True)
            self.assertFalse(any(w.startswith(("api/", "export/")) for w in written))
            with open(os.path.join(out, "anketa.html"), encoding="utf-8") as f:
                self.assertIn('data-demo="1"', f.read())

    def test_escaping(self):
        event = copy.deepcopy(self.event)
        event["title"] = '<script>alert(1)</script>'
        event["topics"][0]["summary"] = '**смело** [връзка](javascript:alert(1)) <img src=x>'
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            write_event(src, event, {"speakers": [{"name": "<b>Х</b>", "link": "https://example.org/x"}]})
            organizer.build(src, out)
            for rel in ("index.html", "tema-01.html"):
                with open(os.path.join(out, rel), encoding="utf-8") as f:
                    page = f.read()
                self.assertNotIn("<script>alert", page)
                self.assertNotIn('href="javascript:', page)
                self.assertNotIn("<img src=x>", page)
            with open(os.path.join(out, "tema-01.html"), encoding="utf-8") as f:
                self.assertIn("<b>смело</b>", f.read())
            with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
                self.assertIn("&lt;b&gt;Х&lt;/b&gt;", f.read())


class Cli(unittest.TestCase):
    def test_new_check_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "ev")
            self.assertEqual(organizer.main(["new", ev]), 0)
            self.assertEqual(organizer.main(["new", ev]), 2)   # не презаписва
            self.assertEqual(organizer.main(["check", ev]), 0)
            self.assertEqual(organizer.main(["build", ev, os.path.join(tmp, "out"), "--demo"]), 0)

    def test_check_fails_on_error(self):
        event, _ = example()
        event = copy.deepcopy(event)
        event["dates"]["to"] = "2000-01-01"
        with tempfile.TemporaryDirectory() as tmp:
            write_event(tmp, event)
            self.assertEqual(organizer.main(["check", tmp]), 1)
            self.assertEqual(organizer.main(["build", tmp, os.path.join(tmp, "out")]), 1)


ROUTER = """<?php
// Тестов рутер: за export/ слага REMOTE_USER, както би го сложил сървърът след вход с парола.
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
if (strpos($path, '/export/') === 0) {
    if (isset($_SERVER['HTTP_X_TEST_LOCKED'])) { $_SERVER['REMOTE_USER'] = 'test'; }
    chdir(__DIR__ . '/export');
    require __DIR__ . '/export/index.php';
    return true;
}
return false;
"""


@unittest.skipUnless(PHP, "няма php")
class LivePhp(unittest.TestCase):
    """Сглобен сайт + вградения сървър на PHP + SQLite вместо MySQL: целият път запис → износ."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.site = os.path.join(cls.tmp.name, "site")
        organizer.build(EXAMPLE, cls.site)
        with open(os.path.join(cls.site, "_router.php"), "w") as f:
            f.write(ROUTER)
        cls.cfg = os.path.join(cls.tmp.name, "cfg.php")
        with open(cls.cfg, "w") as f:
            f.write("<?php return ['db' => ['dsn' => 'sqlite:%s', 'prefix' => 't_']];"
                    % os.path.join(cls.tmp.name, "db.sqlite"))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        env = dict(os.environ, ORGANIZER_CONFIG=cls.cfg)
        cls.proc = subprocess.Popen([PHP, "-S", "127.0.0.1:%d" % cls.port, "_router.php"], cwd=cls.site,
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

    def req(self, path, data=None, headers=None, json_body=True):
        url = "http://127.0.0.1:%d/%s" % (self.port, path)
        body = None
        h = dict(headers or {})
        if data is not None:
            if json_body:
                body = json.dumps(data).encode()
                h["Content-Type"] = "application/json"
            else:
                body = urllib.parse.urlencode(data, doseq=True).encode()
        r = urllib.request.Request(url, data=body, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8-sig")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8-sig")

    def test_1_rejects(self):
        self.assertEqual(self.req("api/submit.php")[0], 405)
        self.assertEqual(self.req("api/submit.php", {"_form": "nope"})[0], 400)
        code, body = self.req("api/submit.php", {"_form": "zapis", "rolya": "Хакер"})
        self.assertEqual(code, 422)
        self.assertEqual(set(json.loads(body)["fields"]), {"rolya", "opit"})

    def test_2_saves_and_exports(self):
        ok = {"_form": "zapis", "rolya": "Инженер", "opit": "Никакъв", "temi": ["2. Памет"],
              "tsel": "=CMD()", "ime": "Ива", "saglasie": "1", "evil": "не се пази", "_t": "12"}
        code, body = self.req("api/submit.php", ok)
        self.assertEqual((code, json.loads(body)["ok"]), (200, True))
        # капанът: казва „добре“, но не записва
        self.assertEqual(self.req("api/submit.php", dict(ok, _hp="bot"))[0], 200)
        self.assertEqual(self.req("api/submit.php", dict(ok, _t="1"))[0], 200)
        # износ без заключена папка → отказ
        self.assertEqual(self.req("export/")[0], 403)
        self.assertEqual(self.req("export/", headers={"Authorization": "Basic eDp5"})[0], 403)
        code, page = self.req("export/", headers={"X-Test-Locked": "1"})
        self.assertEqual(code, 200)
        self.assertIn("?form=zapis", page)
        code, text = self.req("export/?form=zapis", headers={"X-Test-Locked": "1"})
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(len(rows), 2, rows)          # заглавие + един отговор (ботовете не са записани)
        head, row = rows
        self.assertEqual(head[2], "С какво се занимаваш?")
        rec = dict(zip(head, row))
        self.assertEqual(rec["Кои теми те интересуват най-много?"], "2. Памет")
        self.assertEqual(rec["Какво искаш да можеш след интензива?"], "'=CMD()")
        self.assertNotIn("не се пази", text)

    def test_3_plain_post_redirects(self):
        url = "api/submit.php"
        data = {"_form": "tehnika", "mashina": "Свой лаптоп", "problem": "Бавни оферти", "lichni_danni": "Не"}

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        r = urllib.request.Request("http://127.0.0.1:%d/%s" % (self.port, url),
                                   data=urllib.parse.urlencode(data).encode())
        with self.assertRaises(urllib.error.HTTPError) as cm:
            opener.open(r, timeout=5)
        self.assertEqual(cm.exception.code, 303)
        self.assertEqual(cm.exception.headers["Location"], "../tehnika.html?ok=1")

    def test_php_unit(self):
        r = subprocess.run([PHP, os.path.join(APP, "php", "tests", "validate_test.php")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


import urllib.parse  # noqa: E402  (ползва се в LivePhp)

if __name__ == "__main__":
    unittest.main()
