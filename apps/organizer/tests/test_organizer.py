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


def write_event(folder, event, speakers=(), partners=()):
    with open(os.path.join(folder, "event.json"), "w", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False)
    os.makedirs(os.path.join(folder, "data"), exist_ok=True)
    for sub in ("assets", "izvori"):                                 # кадрите и източниците от примера
        if not os.path.exists(os.path.join(folder, sub)):
            shutil.copytree(os.path.join(EXAMPLE, sub), os.path.join(folder, sub))
    for name, lst in (("lektori", speakers), ("partnyori", partners)):
        with open(os.path.join(folder, "data", name + ".json"), "w", encoding="utf-8") as f:
            json.dump(list(lst), f, ensure_ascii=False)


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

    def test_media_rules(self):
        self.bad(lambda e, p: e["topics"][1]["demo"]["media"][0].pop("alt"), "липсва alt")
        self.bad(lambda e, p: e["topics"][1]["demo"]["media"][0].update(src="assets/x.mov"), "картинка")
        self.bad(lambda e, p: e["topics"][1]["demo"]["images"].append({"src": "assets/v.mp4", "alt": "в"}), "само в media")
        self.bad(lambda e, p: e["gallery"]["groups"][0]["media"][0].pop("alt"), "галерия/Кадри")
        self.bad(lambda e, p: e["forms"][0].update(slug="galeria"), "slug е зает")

    def test_theme_scripts_rules(self):
        self.bad(lambda e, p: e["theme"].update(scripts=["https://evil.example/x.js"]), "theme.scripts")
        self.bad(lambda e, p: e["theme"].update(scripts=["../x.js"]), "theme.scripts")
        self.bad(lambda e, p: e["theme"].update(script_attrs={"onload": "x"}), "script_attrs")
        self.bad(lambda e, p: e["theme"].update(page_audio="assets/eva/audio.mp3"), "page_audio")

    def test_image_needs_alt_and_file(self):
        self.bad(lambda e, p: e["topics"][1]["demo"]["images"][0].pop("alt"), "липсва alt")
        self.bad(lambda e, p: e["topics"][1]["demo"]["images"][0].update(src="../x.png"), "images[0].src")
        event = copy.deepcopy(example()[0])
        event["topics"][1]["demo"]["images"][0]["src"] = "assets/demo/nyama.png"
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            write_event(src, event)
            with self.assertRaises(ValueError) as cm:
                organizer.build(src, out)
            self.assertIn("nyama.png", str(cm.exception))

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
        self.bad(lambda e, p: p.update(speakers=[{"role": "x"}]), "иска name")
        self.bad(lambda e, p: p.update(speakers=[{"name": "А", "link": "javascript:alert(1)"}]), ".link")

    def test_table_row_width(self):
        self.bad(lambda e, p: e["topics"][1]["sections"][0]["table"]["rows"].append(["само една"]), "всеки ред")

    def test_duplicate_form_table(self):
        self.bad(lambda e, p: [f.update(table="edna") for f in e["forms"]], "таблица")

    def test_config_file_outside_home(self):
        self.bad(lambda e, p: e["server"].update(config_file="../etc/x.php"), "config_file")

    def test_bad_forbid_regex(self):
        self.bad(lambda e, p: e["publish"].update(forbid_regex=["(("]), "forbid_regex")

    def test_pending_markers_listed(self):
        event, people = example()
        waits = organizer.pending(event, "[ЧАКА") + organizer.pending(people, "[ЧАКА", "data")
        self.assertEqual([w[0] for w in waits], ["event.place.note", "event.topics[0].source.text",
                                                 "event.privacy.blocks[0].list[1]"])

    def test_name_field_without_personal_is_flagged(self):
        event, people = example()
        event = copy.deepcopy(event)
        event["forms"][0]["fields"][7].pop("personal")
        _, todo = organizer.check(event, people)
        self.assertTrue(any("zapis/ime" in t and "personal" in t for t in todo), todo)
        spec = organizer.forms_spec(example()[0])
        flags = {f["id"]: f["personal"] for f in spec["forms"]["zapis"]["fields"]}
        self.assertEqual((flags["ime"], flags["email"], flags["saglasie"], flags["rolya"]), (True, True, True, False))

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
        for rel in ("index.html", "programa.html", "razpisanie.html", "lektori.html", "organizatori.html",
                    "privacy.html", "anketa.html", "tehnika.html", "tema-01-parvi-razgovor.html",
                    "tema-02-pamet.html", "tema-03-zashtita.html", "data/lektori.json", "data/partnyori.json",
                    "api/forms.json", "api/submit.php", "api/lib.php", "admin/export.php", "sql/schema.sql",
                    "sql/config.sample.php", "sql/.htaccess", ".htaccess", "assets/present.js"):
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
        page = self.read("tema-01-parvi-razgovor.html")
        labels = re.findall(r'<article class="lab-col"><h3>([^<]+)</h3>', page)
        self.assertEqual(labels, [r["label"] for r in self.event["lab_roles"]])
        self.assertIn("--cols:4", page)

    def test_topic_sections_and_demo(self):
        page = self.read("tema-02-pamet.html")
        self.assertIn("<h2>Видове информация</h2>", page)
        self.assertIn("<th>Къде се обработва</th>", page)
        self.assertIn("<h2>Бази</h2>", page)
        self.assertIn("Демо на живо", page)
        order = [page.index(h) for h in ("<h2>Видове информация</h2>", "Демо на живо", "<h2>Лаборатория</h2>",
                                         "<h2>Какво отнасяш вкъщи</h2>")]
        self.assertEqual(order, sorted(order))
        self.assertIn('class="stat"><b>до 10</b>', self.read("index.html"))
        self.assertIn('<p class="hero-note">Подгряващо събитие за <a href="https://example.org/">', self.read("index.html"))
        one = self.read("tema-01-parvi-razgovor.html")
        self.assertIn('class="block source"', one)
        self.assertIn("<dt>Роля</dt>", one)
        self.assertIn("Как да поставя задача", one)
        three = self.read("tema-03-zashtita.html")
        self.assertNotIn('class="block demo"', three)                 # "demo": false
        self.assertNotIn('class="block source"', three)               # изходник само с тире
        self.assertIn("<h2>Критерии</h2>", three)
        self.assertFalse(any(t.startswith("тема 3: няма") for t in self.todo), self.todo)

    def test_slots_and_placeholders_for_people(self):
        page = self.read("lektori.html")
        self.assertEqual(page.count('class="person empty"'), 3)
        self.assertIn("Лектор · Памет и бази данни", page)
        self.assertIn("очаква потвърждение", page)
        self.assertEqual(self.read("organizatori.html").count('class="person empty"'), 4)
        org = self.read("organizatori.html")
        self.assertIn("Примерна организация ЕООД", org)
        self.assertIn("<h2>Организаторите</h2>", org)
        self.assertLess(org.index('<p class="kicker">Организатор</p>'), org.index('<p class="kicker">Съорганизатор</p>'))

    def test_images_and_form_nav(self):
        page = self.read("tema-02-pamet.html")
        self.assertIn('<a href="assets/demo/primer_1.png"><img src="assets/demo/primer_1.png" alt="Син квадрат', page)
        self.assertIn('loading="lazy"', page)
        self.assertIn("<figcaption>Кадър 1</figcaption>", page)
        self.assertIn("assets/demo/primer_2.png", self.written)
        self.assertIn('<a href="tehnika.html">Техника</a>', self.read("index.html"))   # forms[].nav
        nav = re.search(r"<nav>(.*?)</nav>", self.read("index.html")).group(1)
        self.assertEqual(nav.count('href="anketa.html"'), 1)

    def test_media_video_and_gallery(self):
        page = self.read("tema-02-pamet.html")
        self.assertIn('<video controls muted playsinline preload="metadata" poster="assets/demo/primer_1.png"', page)
        self.assertIn('<source src="assets/media/primer_video.webm" type="video/webm">', page)
        self.assertNotIn("autoplay", page)
        self.assertIn("<figcaption>Видео в демото: <b>без звук</b>", page)      # caption минава през md()
        gal = self.read("galeria.html")
        self.assertIn("<h2>Кадри</h2>", gal)
        self.assertIn("<h2>Видео</h2>", gal)
        self.assertIn('<a href="galeria.html" aria-current="page">Галерия</a>', gal)
        self.assertIn('href="galeria.html">Галерия</a>', self.read("index.html"))
        css = self.read("assets/style.css")
        self.assertIn("@media (min-width:480px){.shots{grid-template-columns:repeat(2", css)
        self.assertIn("@media (min-width:900px){.shots{grid-template-columns:repeat(3", css)

    def test_media_files_missing_and_size(self):
        event, _ = example()
        with tempfile.TemporaryDirectory() as d:
            write_event(d, event)
            os.remove(os.path.join(d, "assets", "media", "primer_video.webm"))
            with open(os.path.join(d, "assets", "demo", "primer_1.png"), "ab") as f:
                f.write(b"\0" * (900 * 1024))
            err, todo = organizer.media_files(d, event)
            self.assertTrue(any("няма файл assets/media/primer_video.webm" in e for e in err), err)
            self.assertTrue(any("primer_1.png е 0.9 MB" in t and "800 KB" in t for t in todo), todo)
            self.assertEqual(organizer.main(["check", d]), 1)

    def test_theme_scripts_on_every_page_and_audio_warning(self):
        event = copy.deepcopy(self.event)
        event["theme"]["scripts"] = ["assets/eva/eva.js"]
        event["theme"]["script_attrs"] = {"data-base": "assets/eva/", "data-voice": "Калина \"К\""}
        event["theme"]["page_audio"] = "assets/eva/audio/{page}.mp3"
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            write_event(src, event)
            _, todo = organizer.media_files(src, event)
            err, _ = organizer.media_files(src, event)
            self.assertIn("theme.scripts: няма файл assets/eva/eva.js", err)
            os.makedirs(os.path.join(src, "assets", "eva", "audio"))
            with open(os.path.join(src, "assets", "eva", "eva.js"), "w") as f:
                f.write("/* Ева */")
            for name in ("index", "programa"):
                open(os.path.join(src, "assets", "eva", "audio", name + ".mp3"), "wb").close()
            err, todo = organizer.media_files(src, event)
            self.assertEqual(err, [])
            audio = [t for t in todo if t.startswith("звук:")]
            self.assertEqual(len(audio), 1)
            self.assertIn("tema-02-pamet", audio[0])
            self.assertNotIn(" index,", audio[0])
            written, _ = organizer.build(src, out)
            self.assertIn("assets/eva/eva.js", written)
            tag = '<script src="assets/eva/eva.js" defer data-base="assets/eva/" data-voice="Калина &quot;К&quot;"></script>'
            for rel in written:
                if rel.endswith(".html"):
                    with open(os.path.join(out, rel), encoding="utf-8") as f:
                        page = f.read()
                    self.assertIn(tag, page, rel)
                    self.assertLess(page.index(tag), page.index("</body>"))

    def test_topic_without_lab(self):
        # тема 3 в примера е защитата: "lab": false — няма блок и не е липса
        self.assertNotIn("<h2>Лаборатория</h2>", self.read("tema-03-zashtita.html"))
        self.assertIn("<h2>Лаборатория</h2>", self.read("tema-02-pamet.html"))
        self.assertFalse(any(t.startswith("тема 3: лабораторията") for t in self.todo), self.todo)
        event, people = example()
        event = copy.deepcopy(event)
        event["topics"][2]["lab"] = ["грешно"]
        self.assertTrue(any("lab е" in e for e in organizer.check(event, people)[0]))

    def test_present_chain_across_pages(self):
        order = organizer.page_order(self.event)
        self.assertEqual(order[:3], ["index.html", "programa.html", "tema-01-parvi-razgovor.html"])
        page = self.read("tema-01-parvi-razgovor.html")
        self.assertIn('<link rel="prev" href="programa.html">', page)
        self.assertIn('<link rel="next" href="tema-02-pamet.html">', page)

    def test_schema_sql_one_table_per_form(self):
        sql = self.read("sql/schema.sql")
        for t in ("primer_intenziv_zapis", "primer_intenziv_zapis_kontakt", "primer_intenziv_tehnika",
                  "primer_intenziv_tehnika_kontakt", "primer_intenziv_rate"):
            self.assertIn("CREATE TABLE IF NOT EXISTS `%s`" % t, sql)
        self.assertIn("Require all denied", self.read("sql/.htaccess"))

    def test_theme_defaults_and_overrides(self):
        css = organizer.theme_css({"accent": "#fc6a3e"})
        self.assertIn("--accent-text:#fc6a3e", css)
        self.assertIn("--on-accent:#ffffff", css)
        css = organizer.theme_css({"accent": "#fc6a3e", "accent_text": "#b8431f", "on_accent": "#151515",
                                   "font_brand": "Syne, sans-serif"})
        self.assertIn("--accent-text:#b8431f", css)
        self.assertIn("--font-brand:Syne, sans-serif", css)
        errors, _ = organizer.check(dict(self.event, theme={"accent_text": "orange"}), {"speakers": [], "partners": []})
        self.assertTrue(any("accent_text" in e for e in errors))

    def test_headings_fit_narrow_screens(self):
        # широк шрифт + дълга дума на 360 px не бива да излиза вдясно (урок от AI старт: „Поверителност“ +44 px)
        css = self.read("assets/style.css")
        self.assertRegex(css, r"h1,h2,h3\{[^}]*overflow-wrap:break-word")
        self.assertIn("h1{font-size:clamp(1.55rem,7.2vw,", css)

    def test_no_uppercase_tracking(self):
        css = self.read("assets/style.css")
        self.assertNotIn("uppercase", css)
        self.assertNotRegex(css, r"letter-spacing:\s*\.\d")

    def test_broken_link_stops_build(self):
        event = copy.deepcopy(self.event)
        event["tagline"] = "Виж [тук](nyama.html)."
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            write_event(src, event)
            with self.assertRaises(ValueError) as cm:
                organizer.build(src, out)
            self.assertIn("nyama.html", str(cm.exception))

    def test_forbid_regex(self):
        event = copy.deepcopy(self.event)
        event["brand"]["legal"] = "Примерна организация ООД"
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            write_event(src, event)
            with self.assertRaises(ValueError) as cm:
                organizer.build(src, out)
            self.assertIn("ООД", str(cm.exception))

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
            if rel.endswith((".png", ".jpg", ".woff2", ".webm", ".mp4", ".webp")):
                continue
            text = self.read(rel)
            self.assertNotRegex(text, r"(?i)password\s*=|'pass'\s*=>\s*'[^'П]", rel)

    def test_forbidden_text_stops_build(self):
        event = copy.deepcopy(self.event)
        event["topics"][1]["summary"] = "Старата дата 10–12 май 2030 е останала тук."
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            write_event(src, event)
            with self.assertRaises(ValueError) as cm:
                organizer.build(src, out)
            self.assertIn("tema-02-pamet.html", str(cm.exception))
            self.assertEqual(organizer.main(["build", src, out]), 1)

    def test_demo_has_no_php(self):
        with tempfile.TemporaryDirectory() as out:
            written, _ = organizer.build(EXAMPLE, out, demo=True)
            self.assertFalse(any(w.startswith(("api/", "admin/", "sql/")) for w in written))
            with open(os.path.join(out, "anketa.html"), encoding="utf-8") as f:
                self.assertIn('data-demo="1"', f.read())

    def test_escaping(self):
        event = copy.deepcopy(self.event)
        event["title"] = '<script>alert(1)</script>'
        event["topics"][0]["summary"] = '**смело** [връзка](javascript:alert(1)) <img src=x>'
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            write_event(src, event, speakers=[{"name": "<b>Х</b>", "link": "https://example.org/x"}])
            organizer.build(src, out)
            for rel in ("index.html", "tema-01-parvi-razgovor.html", "lektori.html"):
                with open(os.path.join(out, rel), encoding="utf-8") as f:
                    page = f.read()
                self.assertNotIn("<script>alert", page)
                self.assertNotIn('href="javascript:', page)
                self.assertNotIn("<img src=x>", page)
            with open(os.path.join(out, "tema-01-parvi-razgovor.html"), encoding="utf-8") as f:
                self.assertIn("<b>смело</b>", f.read())
            with open(os.path.join(out, "lektori.html"), encoding="utf-8") as f:
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
if (strpos($path, '/admin/') === 0) {
    if (isset($_SERVER['HTTP_X_TEST_LOCKED'])) { $_SERVER['REMOTE_USER'] = 'test'; }
    chdir(__DIR__ . '/admin');
    require __DIR__ . '/admin/export.php';
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
            f.write("<?php return ['db' => ['dsn' => 'sqlite:%s'], 'auto_create' => true, 'salt' => 'test'];"
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
        self.assertEqual(self.req("admin/")[0], 403)
        self.assertEqual(self.req("admin/", headers={"Authorization": "Basic eDp5"})[0], 403)
        code, page = self.req("admin/", headers={"X-Test-Locked": "1"})
        self.assertEqual(code, 200)
        self.assertIn("?form=zapis", page)
        code, text = self.req("admin/?form=zapis", headers={"X-Test-Locked": "1"})
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(len(rows), 2, rows)          # заглавие + един отговор (ботовете не са записани)
        head, row = rows
        self.assertEqual(head[2], "С какво се занимаваш?")
        rec = dict(zip(head, row))
        self.assertEqual(rec["Кои теми те интересуват най-много?"], "2. Памет")
        self.assertEqual(rec["Какво искаш да можеш след интензива?"], "'=CMD()")
        self.assertNotIn("не се пази", text)
        self.assertEqual(rec["Име (по желание)"], "Ива")            # износът съединява личното обратно

    def test_5_personal_fields_stored_apart(self):
        import sqlite3
        ok = {"_form": "zapis", "rolya": "Фотограф", "opit": "Никакъв", "ime": "Петя", "email": "p@example.org",
              "saglasie": "1", "_t": "9"}
        self.assertEqual(self.req("api/submit.php", ok)[0], 200)
        anon = {"_form": "zapis", "rolya": "Дизайнер", "opit": "Никакъв", "_t": "9"}
        self.assertEqual(self.req("api/submit.php", anon)[0], 200)
        db = sqlite3.connect(os.path.join(self.tmp.name, "db.sqlite"))
        answers = [json.loads(r[0]) for r in db.execute("SELECT answers FROM primer_intenziv_zapis")]
        self.assertTrue(answers)
        for a in answers:
            self.assertFalse({"ime", "email", "saglasie"} & set(a), a)
        contacts = {r[0]: json.loads(r[1]) for r in db.execute("SELECT response_id, data FROM primer_intenziv_zapis_kontakt")}
        petya = [c for c in contacts.values() if c.get("ime") == "Петя"]
        self.assertEqual(petya, [{"ime": "Петя", "email": "p@example.org", "saglasie": True}])
        last_anon = db.execute("SELECT id FROM primer_intenziv_zapis ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertNotIn(last_anon, contacts)                      # без лични данни няма ред в _kontakt

    def test_9_rate_limit(self):
        ok = {"_form": "tehnika", "mashina": "Свой лаптоп", "problem": "x", "lichni_danni": "Не",
              "ime": "А", "email": "a@example.org", "saglasie": "1", "_t": "9"}
        codes = [self.req("api/submit.php", ok)[0] for _ in range(12)]
        self.assertIn(429, codes)
        self.assertLessEqual(codes.count(200), 10)

    def test_3_plain_post_redirects(self):
        url = "api/submit.php"
        data = {"_form": "tehnika", "mashina": "Свой лаптоп", "problem": "Бавни оферти", "lichni_danni": "Не",
                "ime": "Ива", "email": "iva@example.org", "saglasie": "1"}

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
