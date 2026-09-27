"""Събирачът: адреси, RSS/Atom (и windows-1251), HTML, ръчен вход, учтивост, отказ от извличане, копия.

    cd apps/filtar && python3 -m unittest discover -s tests -v
"""
import json
import os
import unittest
from datetime import timedelta

from obshto import IZVORI, SEGA, FalshivaMrezha, Papka, cfg, pishi_json

from filtar import sabirach


def broy(b, sql="SELECT COUNT(*) FROM zapisi", *a):
    return b.execute(sql, a).fetchone()[0]


class TestAdresi(unittest.TestCase):
    def test_kanon(self):
        k = sabirach.kanon
        self.assertEqual(k("HTTPS://Example.org:443/a?utm_source=x&b=1&fbclid=z#kom"), "https://example.org/a?b=1")
        self.assertEqual(k("https://example.org/a?UTM_Medium=x"), "https://example.org/a")
        self.assertEqual(k("http://example.org"), "http://example.org/")
        self.assertIsNone(k("javascript:void(0)"))
        self.assertIsNone(k("ftp://example.org/f"))
        self.assertIsNone(k(""))

    def test_hash_e_sha256_na_kanona(self):
        self.assertEqual(sabirach.url_hash("https://example.org/a?utm_x=1#y"), sabirach.url_hash("https://example.org/a"))
        self.assertEqual(len(sabirach.url_hash("https://example.org/a")), 64)


class TestSabirane(unittest.TestCase):
    def test_tri_emisii(self):
        with Papka() as p:
            o = sabirach.sabiray(p.b, cfg(), IZVORI, SEGA, get=FalshivaMrezha())
            self.assertEqual(o["novi"], 30)
            self.assertEqual(o["greshki"], [])
            # windows-1251 е прочетено правилно
            z = p.b.execute("SELECT * FROM zapisi WHERE izvor='primer-obshtina' ORDER BY id").fetchone()
            self.assertEqual(z["zaglavie"], "Удължен срок за кандидатстване по покана за финансиране")
            self.assertEqual(z["tip"], "atom")
            self.assertTrue(z["data"].startswith("2026-10-05"))
            # HTML в описанието е махнат
            z = p.b.execute("SELECT tekst FROM zapisi WHERE izvor='primer-tehno' ORDER BY id").fetchone()
            self.assertNotIn("<p>", z["tekst"])

    def test_pishe_samo_novoto(self):
        with Papka() as p:
            sabirach.sabiray(p.b, cfg(), IZVORI, SEGA, get=FalshivaMrezha())
            o = sabirach.sabiray(p.b, cfg(), IZVORI, SEGA + timedelta(hours=2), get=FalshivaMrezha())
            self.assertEqual(o["novi"], 0)
            self.assertEqual(broy(p.b), 30)

    def test_spazva_intervala(self):
        with Papka() as p:
            m = FalshivaMrezha()
            sabirach.sabiray(p.b, cfg(), IZVORI, SEGA, get=m)
            n = len(m.zayavki)
            o = sabirach.sabiray(p.b, cfg(), IZVORI, SEGA + timedelta(minutes=10), get=m)
            self.assertEqual(len(m.zayavki), n)  # рано е — нищо не е теглено
            self.assertEqual(o["propusnati"], 3)
            izv = dict(IZVORI[0], fetch_interval_min=5)
            sabirach.sabiray(p.b, cfg(), [izv], SEGA + timedelta(minutes=10), get=m)
            self.assertGreater(len(m.zayavki), n)

    def test_uchtiv(self):
        with Papka() as p:
            m = FalshivaMrezha()
            sabirach.sabiray(p.b, cfg(), IZVORI[:1], SEGA, get=m)
            for url, ua, timeout in m.zayavki:
                self.assertEqual(ua, "KAGAMI-filtar/0.1 (+https://kagami.bg/radar/)")
                self.assertEqual(timeout, 30)
            adresi = [u for u, _, _ in m.zayavki]
            self.assertEqual(adresi, ["https://example.org/robots.txt", "https://example.org/.well-known/tdmrep.json",
                                      "https://example.org/tehno/rss.xml"])  # нищо друго — без обхождане

    def test_greshen_izvor(self):
        with Papka() as p:
            izv = dict(IZVORI[0], url="https://example.org/nyama.xml")
            o = sabirach.sabiray(p.b, cfg(), [izv], SEGA, get=FalshivaMrezha())
            self.assertEqual(len(o["greshki"]), 1)
            self.assertIn("404", o["greshki"][0])


class TestOtkazOtIzvlichane(unittest.TestCase):
    def proba(self, stranici, izv=None):
        with Papka() as p:
            o = sabirach.sabiray(p.b, cfg(), [izv or IZVORI[0]], SEGA, get=FalshivaMrezha(stranici))
            n = broy(p.b)
            log = [dict(r) for r in p.b.execute("SELECT * FROM firewall_log WHERE reshenie='НЕ СЕ СЪБИРА'")]
        return o, n, log

    def test_robots(self):
        o, n, log = self.proba({"https://example.org/robots.txt": (200, "text/plain", "utf-8", {},
                                                                    b"User-agent: *\nDisallow: /tehno/\n")})
        self.assertEqual(n, 0)
        self.assertEqual(len(o["otkazani"]), 1)
        self.assertEqual(o["greshki"], [])
        self.assertIn("robots.txt", log[0]["prichina"])

    def test_robots_pozvolyava(self):
        o, n, _ = self.proba({"https://example.org/robots.txt": (200, "text/plain", "utf-8", {},
                                                                  b"User-agent: *\nDisallow: /drugo/\n")})
        self.assertEqual(n, 10)

    def test_tdmrep_json(self):
        pravila = json.dumps([{"location": "/tehno/*", "tdm-reservation": 1}]).encode()
        o, n, log = self.proba({"https://example.org/.well-known/tdmrep.json": (200, "application/json", None, {}, pravila)})
        self.assertEqual(n, 0)
        self.assertIn("tdmrep", log[0]["prichina"])

    def test_tdmrep_drug_pat(self):
        pravila = json.dumps([{"location": "/drugo/*", "tdm-reservation": 1}]).encode()
        _, n, _ = self.proba({"https://example.org/.well-known/tdmrep.json": (200, "application/json", None, {}, pravila)})
        self.assertEqual(n, 10)

    def test_zaglavki(self):
        from obshto import procheti
        for zagl, duma in (({"tdm-reservation": "1"}, "TDM-Reservation"), ({"x-robots-tag": "noindex, noai"}, "noai")):
            with self.subTest(zagl):
                o, n, log = self.proba({"https://example.org/tehno/rss.xml": (200, "application/rss+xml", None, zagl,
                                                                              procheti("tehno.rss"))})
                self.assertEqual(n, 0)
                self.assertIn(duma, log[0]["prichina"])

    def test_meta_v_html(self):
        izv = {"id": "str", "ime": "Примерна страница", "vid": "dokumentaciya", "tip": "html",
               "url": "https://example.org/docs/novo.html", "ezik": "bg"}
        for meta in ('<meta name="robots" content="noai, noimageai">', '<meta name="tdm-reservation" content="1">'):
            with self.subTest(meta):
                h = ('<html><head><title>Нова версия</title>%s<meta name="description" content="Описание."></head>'
                     "</html>" % meta).encode()
                _, n, log = self.proba({izv["url"]: (200, "text/html", "utf-8", {}, h)}, izv)
                self.assertEqual(n, 0)
                self.assertEqual(len(log), 1)


class TestKopiya(unittest.TestCase):
    def test_sha256_i_data(self):
        with Papka() as p:
            sabirach.sabiray(p.b, cfg(), IZVORI, SEGA, get=FalshivaMrezha())
            kopiya = p.b.execute("SELECT * FROM firewall_log WHERE sloy=0 AND reshenie='КОПИЕ'").fetchall()
            self.assertEqual(len(kopiya), 30 + 3)  # всеки запис + всяка емисия
            z = p.b.execute("SELECT id, sha256, sabrano FROM zapisi ORDER BY id").fetchone()
            red = p.b.execute("SELECT prichina FROM firewall_log WHERE zapis_id=? AND sloy=0", (z["id"],)).fetchone()
            self.assertIn("sha256=" + z["sha256"], red["prichina"])
            self.assertIn("изтеглено " + z["sabrano"], red["prichina"])


class TestHtml(unittest.TestCase):
    def test_samo_zaglavie_i_opisanie(self):
        izv = {"id": "str", "ime": "Примерна страница", "vid": "dokumentaciya", "tip": "html",
               "url": "https://example.org/docs/novo.html", "ezik": "bg"}
        h = ('<html><head><title>Нова версия 2.0</title><meta name="description" content="Кратко описание на версията.">'
             '<meta property="article:published_time" content="2026-10-05T06:00:00+03:00"></head>'
             '<body><p>Дълъг текст, който не се взема.</p><a href="/drugo">връзка</a></body></html>').encode()
        with Papka() as p:
            m = FalshivaMrezha({izv["url"]: (200, "text/html", "utf-8", {}, h)})
            sabirach.sabiray(p.b, cfg(), [izv], SEGA, get=m)
            z = p.b.execute("SELECT * FROM zapisi").fetchone()
            self.assertEqual(z["zaglavie"], "Нова версия 2.0")
            self.assertEqual(z["tekst"], "Кратко описание на версията.")
            self.assertTrue(z["data"].startswith("2026-10-05"))
            self.assertNotIn("https://example.org/drugo", [u for u, _, _ in m.zayavki])


class TestRuchno(unittest.TestCase):
    def test_vhod(self):
        with Papka() as p:
            o = sabirach.sabiray(p.b, cfg(), [], SEGA, vhod=p.vhod)
            self.assertEqual(o["novi"], 1)
            z = p.b.execute("SELECT * FROM zapisi").fetchone()
            self.assertEqual(z["izvor"], "ruchno:posta")
            self.assertEqual(z["tip"], "ruchno")
            self.assertTrue(os.path.exists(os.path.join(p.vhod, "obraboteni", "svodka_2026-10-05.json")))
            self.assertEqual([f for f in os.listdir(p.vhod) if f.endswith(".json")], [])

    def test_losh_fail_ostava(self):
        with Papka() as p:
            pishi_json(os.path.join(p.vhod, "losh.json"), {"zapisi": []})  # без izvor
            o = sabirach.sabiray(p.b, cfg(), [], SEGA, vhod=p.vhod)
            self.assertTrue(any("losh.json" in g for g in o["greshki"]))
            self.assertTrue(os.path.exists(os.path.join(p.vhod, "losh.json")))


if __name__ == "__main__":
    unittest.main()
