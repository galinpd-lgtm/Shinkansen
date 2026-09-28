"""Командите през main() върху измислен свят: проверките, състоянията, доказателствата, отчетът, износът."""
import csv
import io
import json
import os
import re
import sys
import unittest
from unittest import mock

from obshto import APP, CFG, SEGA, Papka, Svyat, stranici

from izvori import config, proverki

PROIZVODITEL = "Примерен производител"


def _rez(z, k):
    return z["proverki"][k]["rezultat"]


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestProverki(unittest.TestCase):
    def test_vsichko_minava(self):
        with Papka() as p:
            i = p.dobavi("https://example.com/blog/", "proizvoditel")
            kod, out, err = p.hod("validirai")
            self.assertEqual(kod, 0, err)
            z = p.zapis(i)
            self.assertEqual(z["organizaciya"], PROIZVODITEL)  # позната по домейна от config
            self.assertEqual(z["sastoyanie"], "validiran")
            for k in ("domeyn", "zhiv", "emisiya", "razresheniya", "ezik", "vid_sadarzhanie", "eshelon"):
                self.assertEqual(_rez(z, k), "да", k)
            e = z["proverki"]["emisiya"]
            self.assertEqual(e["url"], "https://example.com/blog/feed.xml")
            self.assertEqual(e["nachin"], "link rel=alternate")
            self.assertEqual(e["posleden_zapis"], "2026-09-25T10:30:00+00:00")
            self.assertEqual(z["proverki"]["zhiv"]["posledna_promyana"], "2026-09-25T10:30:00+00:00")
            self.assertEqual(z["proverki"]["ezik"]["ezik"], "en")
            self.assertEqual(z["proverki"]["vid_sadarzhanie"]["vid"], "blog")
            self.assertEqual(z["eshelon"], "parvichen")

    def test_prenasochvane_kam_chuzhd_domeyn(self):
        with Papka() as p:
            i = p.dobavi("https://example.com/novini", "proizvoditel")
            p.hod("validirai")
            z = p.zapis(i)
            d = z["proverki"]["domeyn"]
            self.assertEqual(d["rezultat"], "неясно")
            self.assertIn("чужд домейн", d["belezhka"])
            self.assertEqual(d["kraen_host"], "example.net")
            self.assertEqual(z["proverki"]["zhiv"]["prenasochvaniya"][0]["status"], 301)
            # първичен по вид, но домейнът не е потвърден → и ешелонът е „неясно“, без да се вдига нищо
            self.assertEqual(_rez(z, "eshelon"), "неясно")

    def test_lipsvashta_emisiya(self):
        with Papka() as p:
            i = p.dobavi("https://example.org/press/", "regulator")
            p.hod("validirai")
            z = p.zapis(i)
            e = z["proverki"]["emisiya"]
            self.assertEqual(e["rezultat"], "не")
            self.assertEqual(e["opitani"], ["https://example.org" + x for x in CFG["obichayni_patishta_emisiya"]])
            self.assertEqual(z["sastoyanie"], "validiran")  # липсата на емисия не е пречка
            self.assertEqual(z["proverki"]["ezik"]["ezik"], "bg")
            self.assertEqual(z["proverki"]["vid_sadarzhanie"]["vid"], "pres")
            # не повече от 4 обичайни пътя и нищо друго от сайта (без обхождане)
            poiskani = [u for u, _ in p.svyat.zayavki if u.startswith("https://example.org/")]
            self.assertEqual(sorted(poiskani), sorted(["https://example.org/robots.txt", "https://example.org/press/",
                                                       "https://example.org/.well-known/tdmrep.json"] + e["opitani"]))

    def test_tdm_rezervaciya(self):
        with Papka() as p:
            i = p.dobavi("https://example.org/docs/ai", "regulator")
            p.hod("validirai")
            z = p.zapis(i)
            r = z["proverki"]["razresheniya"]
            self.assertEqual(r["rezultat"], "не")
            self.assertEqual(r["pravo"], "samo_ocenka_i_citat")
            self.assertTrue(r["tdm"]["rezervirano"])
            signali = " | ".join(r["tdm"]["signali"])
            for s in ("заглавка tdm-reservation", "meta tdm-reservation", "meta robots: noai", "meta robots: noimageai",
                      "tdmrep.json"):
                self.assertIn(s, signali)
            self.assertEqual(z["sastoyanie"], "validiran")  # записва се и се уважава, не е пречка
            self.assertEqual(z["proverki"]["vid_sadarzhanie"]["vid"], "dokumentaciya")

    def test_403_e_zashtita_ne_greshka(self):
        with Papka() as p:
            i = p.dobavi("https://example.org/zashtiteno/", "regulator")
            p.hod("validirai")
            z = p.zapis(i)
            self.assertEqual(_rez(z, "zhiv"), "неясно")
            self.assertIn("защита", z["proverki"]["zhiv"]["belezhka"])
            self.assertEqual(z["prechki"], [])
            self.assertEqual(_rez(z, "emisiya"), "неясно")
            # след 403 не се пробват обичайните пътища — нищо не се заобикаля
            self.assertNotIn("https://example.org/feed", [u for u, _ in p.svyat.zayavki])

    def test_404_e_prechka(self):
        with Papka() as p:
            i = p.dobavi("https://example.com/nyama/", "proizvoditel")
            p.hod("validirai")
            z = p.zapis(i)
            self.assertEqual(_rez(z, "zhiv"), "не")
            self.assertEqual(z["sastoyanie"], "kandidat")
            self.assertTrue(z["prechki"])

    def test_bez_otgovor_e_prechka(self):
        st = stranici()
        st["https://example.com/blog/"] = OSError("връзката е отказана")
        with Papka(Svyat(st)) as p:
            i = p.dobavi("https://example.com/blog/", "proizvoditel")
            kod, out, err = p.hod("validirai")
            self.assertEqual(kod, 0, err)
            self.assertEqual(p.zapis(i)["sastoyanie"], "kandidat")

    def test_robots_zabranyava(self):
        with Papka() as p:
            i = p.dobavi("https://news.example.net/tech/", "media")
            p.hod("validirai")
            z = p.zapis(i)
            self.assertEqual(_rez(z, "razresheniya"), "не")
            self.assertEqual(z["proverki"]["razresheniya"]["pravo"], "ne_se_izvlicha")
            self.assertEqual(_rez(z, "zhiv"), "неясно")
            self.assertNotIn("https://news.example.net/tech/", [u for u, _ in p.svyat.zayavki])
            self.assertEqual(z["eshelon"], "vtorichen")

    def test_glavnata_stranica_sochi(self):
        with Papka() as p:
            i = p.dobavi("https://research.example.net/papers/", "izsledvane", PROIZVODITEL)
            p.hod("validirai")
            z = p.zapis(i)
            self.assertEqual(_rez(z, "domeyn"), "да")
            self.assertIn("главната страница", z["proverki"]["domeyn"]["belezhka"])
            e = z["proverki"]["emisiya"]
            self.assertEqual((e["rezultat"], e["nachin"], e["tip"]), ("да", "адресът", "atom"))
            self.assertEqual(z["proverki"]["vid_sadarzhanie"]["vid"], "izsledvane")

    def test_chuzhd_domeyn_bez_vrazka_e_prechka(self):
        with Papka() as p:
            i = p.dobavi("https://example.net/drugade/", "proizvoditel", PROIZVODITEL)
            p.hod("validirai")
            z = p.zapis(i)
            self.assertEqual(_rez(z, "domeyn"), "не")
            self.assertEqual(z["sastoyanie"], "kandidat")

    def test_uchtivost(self):
        with Papka() as p:
            p.dobavi("https://example.com/blog/", "proizvoditel")
            p.hod("validirai")
            for _, ua in p.svyat.zayavki:
                self.assertTrue(ua.startswith("izvori/"), ua)
                self.assertNotIn("Mozilla", ua)
            # поне 6 с между две заявки към един домейн
            self.assertTrue(p.svyat.spane)
            self.assertTrue(all(s <= CFG["pauza_na_domeyn_s"] for s in p.svyat.spane))
            self.assertGreaterEqual(sum(p.svyat.spane) + 0.1 * len(p.svyat.zayavki),
                                    CFG["pauza_na_domeyn_s"] * (len(p.svyat.zayavki) - 1) - 1e-6)


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestEshelon(unittest.TestCase):
    def test_mashinata_ne_vdiga(self):
        with Papka() as p:
            i = p.dobavi("https://example.com/blog/", "proizvoditel")
            r = p.registar()
            r["izvori"][0]["eshelon"] = "posrednik"  # човек го е свалил на ръка
            with open(p.reg, "w", encoding="utf-8") as f:
                json.dump(r, f)
            p.hod("validirai")
            self.assertEqual(p.zapis(i)["eshelon"], "posrednik")

    def test_agenciya_e_posrednik(self):
        with Papka() as p:
            i = p.dobavi("https://example.net/drugade/", "agenciya")
            self.assertEqual(p.zapis(i)["eshelon"], "posrednik")

    def test_po_nisak(self):
        self.assertEqual(config.po_nisak("parvichen", "vtorichen"), "vtorichen")
        self.assertEqual(config.po_nisak("posrednik", "parvichen"), "posrednik")
        self.assertEqual(config.po_nisak("parvichen", None), "parvichen")


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestChovekat(unittest.TestCase):
    def _validiran(self, p):
        i = p.dobavi("https://example.com/blog/", "proizvoditel")
        p.hod("validirai")
        return i

    def test_odobrenie_bez_rolya_e_otkaz(self):
        with Papka() as p:
            i = self._validiran(p)
            kod, _, err = p.hod("odobri", i)
            self.assertEqual(kod, 2)
            self.assertIn("роля", err)
            kod, _, err = p.hod("odobri", i, "--ot", "  ")
            self.assertEqual(kod, 2)
            kod, _, err = p.hod("odobri", i, "--ot", "Иван Иванов")  # име, не роля
            self.assertEqual(kod, 2)
            self.assertEqual(p.zapis(i)["sastoyanie"], "validiran")

    def test_odobrenie_s_rolya(self):
        with Papka() as p:
            i = self._validiran(p)
            kod, out, err = p.hod("odobri", i, "--ot", "редактор", "--belezhka", "проверено")
            self.assertEqual(kod, 0, err)
            z = p.zapis(i)
            self.assertEqual(z["sastoyanie"], "odobren")
            self.assertEqual(z["odobren"]["rolya"], "редактор")
            self.assertEqual(z["istoriya"][-1]["koy"], "редактор")

    def test_kandidat_ne_se_odobryava(self):
        with Papka() as p:
            i = p.dobavi("https://example.com/blog/", "proizvoditel")
            kod, _, err = p.hod("odobri", i, "--ot", "редактор")
            self.assertEqual(kod, 1)
            self.assertEqual(p.zapis(i)["sastoyanie"], "kandidat")

    def test_otkaz(self):
        with Papka() as p:
            i = self._validiran(p)
            self.assertEqual(p.hod("otkazhi", i, "--ot", "редактор")[0], 2)  # без причина
            self.assertEqual(p.hod("otkazhi", i, "--prichina", "дубликат")[0], 2)  # без роля
            kod, _, err = p.hod("otkazhi", i, "--ot", "редактор", "--prichina", "дубликат")
            self.assertEqual(kod, 0, err)
            self.assertEqual(p.zapis(i)["sastoyanie"], "otkazan")
            p.hod("validirai")  # отказаните не се проверяват
            self.assertEqual(p.zapis(i)["sastoyanie"], "otkazan")

    def test_nepoznat_id(self):
        with Papka() as p:
            self.assertEqual(p.hod("odobri", "nyama", "--ot", "редактор")[0], 1)

    def test_dobavi(self):
        with Papka() as p:
            p.dobavi("https://example.com/blog/", "proizvoditel")
            self.assertEqual(p.hod("dobavi", "https://EXAMPLE.com/blog", "--vid", "proizvoditel")[0], 1)
            self.assertEqual(p.hod("dobavi", "https://example.com/x", "--vid", "nepoznat")[0], 2)
            self.assertEqual(p.hod("dobavi", "ftp://example.com/x", "--vid", "media")[0], 2)
            self.assertEqual(p.hod("dobavi", "https://example.com/x", "--vid", "media",
                                   "--organizaciya", "Никаква")[0], 2)
            self.assertEqual(p.hod("dobavi", "https://example.com/x")[0], 2)  # липсва --vid
            self.assertEqual(len(p.registar()["izvori"]), 1)


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestPovtorna(unittest.TestCase):
    def test_izcheznala_emisiya(self):
        svyat = Svyat()
        with Papka(svyat) as p:
            i = p.dobavi("https://example.com/blog/", "proizvoditel")
            p.hod("validirai")
            p.hod("odobri", i, "--ot", "редактор")
            del svyat.st["https://example.com/blog/feed.xml"]
            kod, out, err = p.hod("validirai", sega="2026-10-05T08:00:00Z")
            self.assertEqual(kod, 0, err)
            z = p.zapis(i)
            self.assertEqual(z["sastoyanie"], "za_pregled")
            self.assertIn("изчезнала емисия", " ".join(z["za_pregled_prichini"]))
            # не се изключва сам: пак се проверява и човек решава
            p.hod("validirai", sega="2026-10-06T08:00:00Z")
            self.assertEqual(p.zapis(i)["sastoyanie"], "za_pregled")
            self.assertEqual(p.hod("odobri", i, "--ot", "редактор")[0], 0)
            self.assertEqual(p.zapis(i)["sastoyanie"], "odobren")

    def test_nov_domeyn_404_i_tdm(self):
        for promyana, ochakvano in (
                (lambda st: st.update({"https://example.com/blog/": (301, {"location": "https://example.net/drugade/"},
                                                                     b"")}), "нов домейн"),
                (lambda st: st.pop("https://example.com/blog/"), "404"),
                (lambda st: st.update({"https://example.com/.well-known/tdmrep.json":
                                       (200, {}, b'[{"location": "/blog/*", "tdm-reservation": 1}]')}),
                 "нова TDM забрана")):
            with self.subTest(ochakvano=ochakvano):
                svyat = Svyat()
                with Papka(svyat) as p:
                    i = p.dobavi("https://example.com/blog/", "proizvoditel")
                    p.hod("validirai")
                    p.hod("odobri", i, "--ot", "редактор")
                    promyana(svyat.st)
                    p.hod("validirai", sega="2026-10-05T08:00:00Z")
                    z = p.zapis(i)
                    self.assertEqual(z["sastoyanie"], "za_pregled")
                    self.assertIn(ochakvano, " ".join(z["za_pregled_prichini"]))

    def test_bez_promyana_ostava_odobren(self):
        with Papka() as p:
            i = p.dobavi("https://example.com/blog/", "proizvoditel")
            p.hod("validirai")
            p.hod("odobri", i, "--ot", "редактор")
            p.hod("validirai", sega="2026-10-05T08:00:00Z")
            self.assertEqual(p.zapis(i)["sastoyanie"], "odobren")


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestDokazatelstva(unittest.TestCase):
    def test_samo_se_dobavya(self):
        with Papka() as p:
            i = p.dobavi("https://example.com/blog/", "proizvoditel")
            p.hod("validirai")
            papka = os.path.join(p.dok, i)
            parvo = os.path.join(papka, "2026-09-28.json")
            with open(parvo, "rb") as f:
                predi = f.read()
            p.hod("validirai")  # същия ден
            self.assertEqual(sorted(os.listdir(papka)), ["2026-09-28-2.json", "2026-09-28.json"])
            with open(parvo, "rb") as f:
                self.assertEqual(f.read(), predi)

    def test_sadarzhanie(self):
        with Papka() as p:
            i = p.dobavi("https://example.com/blog/", "proizvoditel")
            p.hod("validirai")
            with open(os.path.join(p.dok, i, "2026-09-28.json"), encoding="utf-8") as f:
                d = json.load(f)
            self.assertEqual(d["t"], "2026-09-28T08:00:00Z")
            self.assertTrue(d["ua"].startswith("izvori/"))
            stranica = next(z for z in d["zayavki"] if z["url"] == "https://example.com/blog/")
            self.assertEqual(len(stranica["sha256"]), 64)
            self.assertIn("last-modified", stranica["zaglavki"])
            self.assertTrue(stranica["otkas"].startswith("<head>"))
            self.assertLessEqual(len(stranica["otkas"].encode("utf-8")), CFG["maks_glava_bytes"])
            self.assertTrue(any(z["url"].endswith("/robots.txt") for z in d["zayavki"]))
            self.assertIn("domeyn", d["proverki"])


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestIzhod(unittest.TestCase):
    def _svyat(self, p):
        a = p.dobavi("https://example.com/blog/", "proizvoditel")
        b = p.dobavi("https://example.org/press/", "regulator")
        c = p.dobavi("https://example.org/docs/ai", "regulator")
        d = p.dobavi("https://example.com/nyama/", "proizvoditel")
        p.hod("validirai")
        p.hod("odobri", a, "--ot", "редактор")
        p.hod("odobri", b, "--ot", "главен редактор")
        return a, b, c, d

    def test_iznesi_samo_odobrenite(self):
        with Papka() as p:
            a, b, c, d = self._svyat(p)
            izhod = os.path.join(p.d, "izvori_filtar.json")
            kod, out, err = p.hod("iznesi", "--za", "filtar", "--izhod", izhod)
            self.assertEqual(kod, 0, err)
            with open(izhod, encoding="utf-8") as f:
                spisak = json.load(f)
            self.assertEqual([z["id"] for z in spisak], [a, b])  # c е валидиран, d е кандидат — не
            self.assertEqual(spisak[0]["tip"], "rss")
            self.assertEqual(spisak[0]["url"], "https://example.com/blog/feed.xml")
            self.assertEqual(spisak[0]["eshelon"], "parvichen")
            self.assertEqual(spisak[0]["izvor_vid"], "proizvoditel")
            self.assertEqual(spisak[0]["vid"], "oficialen")
            self.assertEqual(spisak[1]["tip"], "html")  # без емисия — страницата
            self.assertEqual(spisak[1]["ezik"], "bg")

    def test_iznosat_se_chete_ot_filtara(self):
        """Форматът е този на Z8: регистърът на филтъра го приема такъв, какъвто е."""
        sys.path.insert(0, os.path.join(os.path.dirname(APP), "filtar"))
        from filtar import config as fcfg
        with Papka() as p:
            self._svyat(p)
            izhod = os.path.join(p.d, "izvori_filtar.json")
            p.hod("iznesi", "--za", "filtar", "--izhod", izhod)
            self.assertEqual(len(fcfg.izvori({}, izhod)), 2)

    def test_otchet_md(self):
        with Papka() as p:
            a, b, c, d = self._svyat(p)
            kod, out, err = p.hod("otchet")
            self.assertEqual(kod, 0, err)
            self.assertIn("| одобрен | 2 |", out)
            self.assertIn("| валидиран | 1 |", out)
            self.assertIn("| кандидат | 1 |", out)
            self.assertIn("## Резервирано по TDM", out)
            self.assertIn("## Без емисия", out)
            self.assertIn("код 404", out)  # защо кандидатът не е минал
            izhod = os.path.join(p.d, "otchet.md")
            self.assertEqual(p.hod("otchet", "--izhod", izhod)[0], 0)
            self.assertTrue(os.path.exists(izhod))

    def test_otchet_csv(self):
        with Papka() as p:
            self._svyat(p)
            kod, out, err = p.hod("otchet", "--format", "csv")
            self.assertEqual(kod, 0, err)
            redove = list(csv.DictReader(io.StringIO(out)))
            self.assertEqual(len(redove), 4)
            self.assertEqual({r["sastoyanie"] for r in redove}, {"odobren", "validiran", "kandidat"})

    def test_prazen_registar(self):
        with Papka() as p:
            self.assertEqual(p.hod("otchet")[0], 0)
            izhod = os.path.join(p.d, "f.json")
            self.assertEqual(p.hod("iznesi", "--za", "filtar", "--izhod", izhod)[0], 0)
            with open(izhod, encoding="utf-8") as f:
                self.assertEqual(json.load(f), [])

    def test_greshen_registar(self):
        with Papka() as p:
            with open(p.reg, "w", encoding="utf-8") as f:
                f.write("{не е json")
            self.assertEqual(p.hod("otchet")[0], 1)


class TestBezIzmisleniDanni(unittest.TestCase):
    """В репото примерите са само с example.org, example.com и example.net."""
    RAZRESHENI = re.compile(r"^([a-z0-9-]+\.)*example\.(org|com|net)$")
    NASHI = {"github.com"}  # адресът за връзка в User-Agent — самото репо, не източник

    def test_samo_example_domeyni(self):
        adres = re.compile(r"https?://([^/\s\"'<>)]+)")
        for koren, _, faylove in os.walk(APP):
            if "__pycache__" in koren:
                continue
            for ime in faylove:
                if not ime.endswith((".py", ".json", ".md", ".html", ".rss", ".atom", ".txt")):
                    continue
                pat = os.path.join(koren, ime)
                with open(pat, encoding="utf-8") as f:
                    tekst = f.read()
                for h in adres.findall(tekst):
                    h = h.split(":")[0].lower()
                    if h in self.NASHI or h in ("www.w3.org", "purl.org") or "%" in h:
                        continue
                    with self.subTest(fayl=os.path.relpath(pat, APP), host=h):
                        self.assertRegex(h, self.RAZRESHENI)

    def test_primernyat_registar(self):
        with open(os.path.join(APP, "izvori.example.json"), encoding="utf-8") as f:
            r = json.load(f)
        self.assertTrue(r["izvori"])
        for z in r["izvori"]:
            self.assertRegex(proverki.host(z["url"]), self.RAZRESHENI)
        for o in CFG["organizacii"]:
            for d in o["domeyni"]:
                self.assertRegex(d, self.RAZRESHENI)


if __name__ == "__main__":
    unittest.main()
