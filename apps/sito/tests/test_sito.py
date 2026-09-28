"""Сито през main() върху измислен свят: обхват, присъди, преглед, решения, преобразуване, отчет. Нула мрежа."""
import csv
import io
import json
import os
import random
import subprocess
import tracemalloc
import unittest
import zipfile
from unittest import mock

from obshto import (ROLYA, Papka, baytove, docx, golyam_html, hashove, pdf, rtf, skaniran_pdf, staro)

from sito import config, html_tekst, instrumenti, rtf_tekst, tekst

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEZ_INSTRUMENTI = mock.patch.object(instrumenti, "nameri", lambda ime: None)
BEZ_DNEVNIK = mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
CFG = config.zaredi(os.path.join(APP, "config.example.json"))
IMA_OCR = all(map(instrumenti.nameri, ("pdftotext", "pdftoppm", "tesseract")))


def _md(p, z):
    with open(os.path.join(p.izhod, z["id"] + ".md"), encoding="utf-8") as f:
        return f.read()


def _da_i_vidyan(p, prisada_ili_klas, *, vidyah=True):
    p.hod("reshi", p.karta, "--klas", prisada_ili_klas, "--da", "--ot", ROLYA)
    if vidyah:
        idta = [z["id"] for z in p.k()["faylove"] if prisada_ili_klas in (z["prisada"], z["klas"])]
        p.vidyah(*idta)


@BEZ_INSTRUMENTI
@BEZ_DNEVNIK
class TestObhvatIPrisadi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with BEZ_INSTRUMENTI:
            cls.p = Papka().__enter__()
            cls.k = cls.p.skanirai()
        cls.z = {z["put"]: z for z in cls.k["faylove"]}

    @classmethod
    def tearDownClass(cls):
        cls.p.__exit__()

    def test_golyam_html_e_opakovka(self):
        z = self.z["golyam.html"]
        self.assertEqual(z["prisada"], "opakovka")
        self.assertLess(z["ochakvan_md_bytes"], 0.01 * z["razmer"])
        self.assertIn("студен архив", z["predlozhenie"])

    def test_dublikat(self):
        z = self.z["kopiya/golyam.html"]
        self.assertEqual(z["prisada"], "dublikat")
        self.assertEqual(z["dublikat_na"], self.z["golyam.html"]["id"])

    def test_dogovor_e_dokazatelstvo(self):
        z = self.z["dogovor.docx"]
        self.assertEqual(z["prisada"], "dokazatelstvo")
        self.assertIn("ЕИК/БУЛСТАТ номер", z["signali"])

    def test_podpisan_pdf_e_dokazatelstvo_i_bez_pdftotext(self):
        z = self.z["podpisan.pdf"]
        self.assertEqual(z["prisada"], "dokazatelstvo")
        self.assertIn("няма pdftotext", z["problem"])

    def test_izvan_obhvat(self):
        for put, vid in (("snimka.jpg", "snimka"), ("tablica.xlsx", "tablica"), ("danni.json", "danni"),
                         ("zapis.mp3", "audio"), ("neshto.xyz", "?")):
            z = self.z[put]
            self.assertEqual(z["prisada"], "izvan_obhvat", put)
            self.assertEqual(z["vid"], vid, put)
            self.assertIsNotNone(z["sha256"])
        # JSON с „договор“ и ЕИК вътре не се чете: нито присъда, нито бележка
        self.assertIsNone(self.z["danni.json"]["belezhka"])

    def test_chist_tekst(self):
        for put in ("belezhka.md", "spisak.txt"):
            self.assertEqual(self.z[put]["prisada"], "chist_tekst", put)
            self.assertEqual(self.z[put]["predlozhenie"], CFG["predlozheniya"]["chist_tekst"])

    def test_md_s_dogovor_e_samo_belezhka(self):
        z = self.z["belezhka.md"]
        self.assertEqual(z["prisada"], "chist_tekst")
        self.assertIn("споменава", z["belezhka"])
        self.assertIn("договор", z["belezhka"])
        self.assertIn("ЕИК", z["belezhka"])

    def test_arhiv_ne_se_otvarya(self):
        for put in ("sabrano/arhiv.zip", "sabrano/stari.7z"):
            z = self.z[put]
            self.assertEqual(z["prisada"], "arhiv", put)
            self.assertIn("разархивирай", z["predlozhenie"])
            self.assertEqual(len(z["sha256"]), 64)
        self.assertFalse([p for p in self.z if "!/" in p or "v_arhiv" in p])

    def test_rtf(self):
        z = self.z["pismo.rtf"]
        self.assertEqual(z["prisada"], "tekst")  # има картинка, но RTF не е в opakovka.vidove
        self.assertIn("Писмо в RTF", z["otkas"])
        self.assertNotIn("Times New Roman", z["otkas"])
        self.assertNotIn("Скрито заглавие", z["otkas"])

    def test_doc_bez_antiword_e_neyasno(self):
        z = self.z["star.doc"]
        self.assertEqual(z["prisada"], "neyasno")
        self.assertIn("antiword", z["prichina"])

    def test_pptx_kandidat_za_pdf(self):
        z = self.z["prezentaciya.pptx"]
        self.assertEqual(z["prisada"], "opakovka")
        self.assertIn("кандидат за PDF (Canva)", z["predlozhenie"])

    def test_zhiv_po_pat(self):
        self.assertEqual(self.z["rabotni/plan.docx"]["prisada"], "zhiv")

    def test_macos_sledite_se_propuskat(self):
        for put in (".DS_Store", "._golyam.html", "._dogovor.docx", "__MACOSX/._podpisan.pdf"):
            self.assertNotIn(put, self.z)
        self.assertEqual(self.k["propusnati"]["sistemni"], 4)
        self.assertFalse([z for z in self.k["faylove"] if z["put"].rsplit("/", 1)[-1].startswith("._")])

    def test_nishto_ne_e_vidyano_samo(self):
        self.assertTrue(all(z["vidyan"] is None for z in self.k["faylove"]))

    def test_otkas(self):
        z = self.z["belezhki.docx"]
        self.assertLessEqual(len(z["otkas"]), CFG["otkas_znaci"])
        self.assertGreater(len(z["otkas"]), 1500)
        self.assertIn("Бележки от срещата", z["otkas"])


@BEZ_INSTRUMENTI
@BEZ_DNEVNIK
class TestPregled(unittest.TestCase):
    def test_da_bez_vidyan_ne_se_obrabotva(self):
        with Papka() as p:
            p.skanirai()
            _da_i_vidyan(p, "opakovka:html", vidyah=False)
            predi = baytove(p.karta)
            kod, out, err = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertEqual(kod, 0, err)
            self.assertIn("невидян", out)
            self.assertIn("нищо не е записано", out)
            self.assertFalse(os.path.exists(p.izhod))
            self.assertEqual(predi, baytove(p.karta))

    def test_vidyan_posle_promenen_ne_se_obrabotva(self):
        with Papka() as p:
            p.skanirai()
            _da_i_vidyan(p, "tekst:docx")
            z = p.po_put("belezhki.docx")
            self.assertEqual(z["vidyan"]["sha256"], z["sha256"])
            with open(os.path.join(p.src, "belezhki.docx"), "ab") as f:  # тестът е „човекът“, не Сито
                f.write(b"\0")
            kod, out, _ = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertEqual(kod, 0)
            self.assertIn("променен след прегледа", out)
            z = p.po_put("belezhki.docx")
            self.assertIsNone(z["preobrazuvan"])
            self.assertIsNone(z["vidyan"])
            self.assertFalse(os.path.exists(os.path.join(p.izhod, z["id"] + ".md")))
            # и повторното сканиране не пренася стария преглед
            p.skanirai()
            self.assertIsNone(p.po_put("belezhki.docx")["vidyan"])

    def test_vidyah_na_promenen_sled_skaniraneto_ne_se_zapisva(self):
        with Papka() as p:
            p.skanirai()
            z = p.po_put("belezhki.docx")
            with open(os.path.join(p.src, "belezhki.docx"), "ab") as f:
                f.write(b"\0")
            out = p.vidyah(z["id"])
            self.assertIn("променен след сканирането", out)
            self.assertIsNone(p.po_put("belezhki.docx")["vidyan"])

    def test_vidyah_bez_rolya_i_s_ime(self):
        with Papka() as p:
            p.skanirai()
            i = p.po_put("golyam.html")["id"]
            predi = baytove(p.karta)
            kod, _, err = p.hod("vidyah", p.karta, i)
            self.assertEqual(kod, 2)
            self.assertIn("роля", err)
            kod, _, err = p.hod("vidyah", p.karta, i, "--ot", "Иван Иванов")
            self.assertEqual(kod, 2)
            self.assertEqual(predi, baytove(p.karta))

    def test_vidyah_spisak_i_nepoznat_id(self):
        with Papka() as p:
            p.skanirai()
            a, b = p.po_put("golyam.html")["id"], p.po_put("belezhki.docx")["id"]
            predi = baytove(p.karta)
            kod, _, err = p.hod("vidyah", p.karta, a, "nyama", "--ot", ROLYA)
            self.assertEqual(kod, 1)
            self.assertEqual(predi, baytove(p.karta))  # нито един не е отбелязан
            p.vidyah("%s,%s" % (a, b))
            for put in ("golyam.html", "belezhki.docx"):
                v = p.po_put(put)["vidyan"]
                self.assertEqual(v["rolya"], ROLYA)
                self.assertEqual(v["sha256"], p.po_put(put)["sha256"])
                self.assertEqual(v["t"], "2026-09-28T08:00:00Z")

    def test_reshenie_po_klas_ne_dava_vidyan(self):
        with Papka() as p:
            p.skanirai()
            p.hod("reshi", p.karta, "--klas", "opakovka", "--da", "--ot", ROLYA)
            self.assertTrue(all(z["vidyan"] is None for z in p.k()["faylove"]))

    def test_samo_uvedomyavashtite_bez_reshenie_i_pregled(self):
        with Papka() as p:
            p.skanirai()
            for klas in ("izvan_obhvat", "chist_tekst", "arhiv"):
                p.hod("reshi", p.karta, "--klas", klas, "--da", "--ot", ROLYA)
            idta = [z["id"] for z in p.k()["faylove"] if z["prisada"] in ("izvan_obhvat", "chist_tekst", "arhiv")]
            p.vidyah(*idta)
            for z in p.k()["faylove"]:
                if z["prisada"] in ("izvan_obhvat", "chist_tekst", "arhiv"):
                    self.assertIsNone(z["reshenie"], z["put"])
                    self.assertIsNone(z["vidyan"], z["put"])
            kod, out, _ = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertFalse(os.path.exists(p.izhod))

    def test_pregledat_ocelyava_novo_skanirane_na_sashtiya_fayl(self):
        with Papka() as p:
            p.skanirai()
            _da_i_vidyan(p, "opakovka:html")
            kod, out, _ = p.hod("skanirai", p.src, "--izhod", p.karta)
            self.assertIn("прегледа остават", out)
            z = p.po_put("golyam.html")
            self.assertEqual(z["vidyan"]["rolya"], ROLYA)
            self.assertTrue(z["reshenie"]["da"])


@BEZ_INSTRUMENTI
@BEZ_DNEVNIK
class TestPotok(unittest.TestCase):
    def test_zhiv_po_data(self):
        with Papka() as p:
            t = 1790380800  # 2026-09-26 — два дни преди „сега“
            os.utime(os.path.join(p.src, "belezhki.docx"), (t, t))
            p.skanirai()
            self.assertEqual(p.po_put("belezhki.docx")["prisada"], "zhiv")

    def test_tavan_za_razmer_i_vreme(self):
        with Papka(maks_razmer_bytes=100000) as p:
            p.skanirai()
            self.assertIn("над тавана за размер", p.po_put("golyam.html")["prichina"])
        with Papka(maks_vreme_s=0) as p:
            p.skanirai()
            self.assertIn("над тавана за време", p.po_put("golyam.html")["prichina"])

    def test_dalbochina(self):
        with Papka(svyat_=False, maks_dalbochina=2) as p:
            dalboko = os.path.join(p.src, "a", "b", "c", "d")
            os.makedirs(dalboko)
            for pat in (os.path.join(p.src, "a", "b", "plitak.docx"), os.path.join(dalboko, "1.docx"),
                        os.path.join(dalboko, "2.docx")):
                docx(pat, ["текст " + os.path.basename(pat)])
            staro(p.src)
            k = p.skanirai()
            self.assertEqual([z["put"] for z in k["faylove"]], ["a/b/plitak.docx"])
            self.assertEqual(k["propusnati"]["dalbochina"], 2)
            kod, out, _ = p.hod("karta", p.karta)
            self.assertIn("заради дълбочината (над 2 папки) 2", out)
        self.assertGreaterEqual(CFG["maks_dalbochina"], 32)

    def test_izhodnata_papka_e_nepromenena(self):
        with Papka() as p:
            predi = hashove(p.src)
            p.skanirai()
            for fmt in ("md", "html", "csv"):
                self.assertEqual(p.hod("karta", p.karta, "--format", fmt)[0], 0)
            _da_i_vidyan(p, "opakovka")
            _da_i_vidyan(p, "tekst")
            self.assertEqual(p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")[0], 0)
            self.assertEqual(p.hod("otchet", p.karta)[0], 0)
            self.assertEqual(predi, hashove(p.src))

    def test_bez_reshenie_go_ne_pishe_nishto(self):
        with Papka() as p:
            p.skanirai()
            p.vidyah_vsichki()
            predi = baytove(p.karta)
            kod, out, err = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertEqual(kod, 0, err)
            self.assertFalse(os.path.exists(p.izhod))
            self.assertEqual(predi, baytove(p.karta))

    def test_golyam_html_pod_1_procent(self):
        with Papka() as p:
            p.skanirai()
            _da_i_vidyan(p, "opakovka:html")
            kod, out, err = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertEqual(kod, 0, err)
            z = p.po_put("golyam.html")
            md = _md(p, z)
            self.assertLess(z["preobrazuvan"]["md_bytes"], 0.01 * z["razmer"])
            self.assertEqual(z["preobrazuvan"]["md_bytes"], len(md.encode("utf-8")))
            self.assertEqual(z["preobrazuvan"]["vidyan_ot"], ROLYA)
            self.assertIn('istochnik: "golyam.html"', md)
            self.assertEqual(md.count("Сито отделя смисъла от въздуха."), 40)
            for ne in ("function", "base64", "color:#", "Меню", "не е текст", "коментар"):
                self.assertNotIn(ne, md)

    def test_chunks(self):
        with Papka() as p:
            p.skanirai()
            z = p.po_put("belezhki.docx")
            p.hod("reshi", p.karta, "--fayl", z["id"], "--da", "--ot", ROLYA)
            p.vidyah(z["id"])
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            with open(os.path.join(p.izhod, "chunks.jsonl"), encoding="utf-8") as f:
                ch = [json.loads(r) for r in f]
            self.assertGreaterEqual(len(ch), 3)
            do = 0
            for i, c in enumerate(ch):
                self.assertEqual(c["id"], "%s-%04d" % (z["id"], i))
                self.assertEqual(c["sha256"], z["sha256"])
                self.assertEqual(c["poziciya"]["ot_duma"], do)
                do = c["poziciya"]["do_duma"]
                self.assertLessEqual(c["dumi"], 800)
                self.assertEqual(c["dumi"], len(c["tekst"].split()))
            self.assertGreater(ch[0]["dumi"], 600)

    def test_pptx_s_belezhki(self):
        with Papka() as p:
            p.skanirai()
            _da_i_vidyan(p, "opakovka:pptx")
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            z = p.po_put("prezentaciya.pptx")
            md = _md(p, z)
            self.assertIn("22 KB смисъл", md)
            self.assertIn("Бележка на говорителя: кажи числата.", md)
            self.assertEqual(md.count("**Бележки:**"), 1)
            self.assertEqual(sorted(os.listdir(p.izhod)), sorted(["chunks.jsonl", z["id"] + ".md"]))  # без PDF

    def test_rtf_preobrazuvane(self):
        with Papka() as p:
            p.skanirai()
            _da_i_vidyan(p, "tekst:rtf")
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            md = _md(p, p.po_put("pismo.rtf"))
            self.assertIn("Втори абзац {с къдрави скоби}.", md)
            self.assertIn("Сито —", md)
            self.assertNotIn("pngblip", md)


@BEZ_DNEVNIK
class TestLibreOfficeNikade(unittest.TestCase):
    def test_v_koda_i_config_nyama_libreoffice(self):
        for papka in (os.path.join(APP, "sito"), APP):
            for ime in os.listdir(papka):
                if ime.endswith((".py", ".json")):
                    with open(os.path.join(papka, ime), encoding="utf-8") as f:
                        s = f.read().lower()
                    for duma in ("soffice", "libreoffice", "unoconv", "pptx_pdf_izgled"):
                        self.assertNotIn(duma, s, "%s: %s" % (ime, duma))

    def test_ne_se_vika_pri_celiya_hod(self):
        """Целият ход с всички инструменти „налични“: нито един subprocess не е LibreOffice."""
        vikani = []
        istinski = subprocess.run

        def sledi(argv, *a, **kw):
            vikani.append(os.path.basename(str(argv[0])))
            return istinski(argv, *a, **kw)
        with Papka() as p, mock.patch.object(instrumenti, "nameri", lambda ime: "/usr/bin/" + ime), \
                mock.patch.object(subprocess, "run", sledi):
            p.skanirai()
            _da_i_vidyan(p, "opakovka")
            _da_i_vidyan(p, "tekst")
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
        self.assertFalse([v for v in vikani if "office" in v.lower() or v in ("soffice", "unoconv")], vikani)


@BEZ_INSTRUMENTI
@BEZ_DNEVNIK
class TestArhiv(unittest.TestCase):
    def test_zip_ne_se_otvarya(self):
        """От ZIP се взима само хешът на самия файл — zipfile никога не го отваря."""
        otvoreni = []
        istinski = zipfile.ZipFile

        def sledi(f, *a, **kw):
            otvoreni.append(os.path.basename(f) if isinstance(f, str) else "<поток>")
            return istinski(f, *a, **kw)
        with Papka() as p, mock.patch.object(zipfile, "ZipFile", sledi):
            p.skanirai()
            _da_i_vidyan(p, "tekst")
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            z = p.po_put("sabrano/arhiv.zip")
        self.assertNotIn("arhiv.zip", otvoreni)
        self.assertIn("belezhki.docx", otvoreni)  # docx се чете като zip — това е друго
        self.assertEqual(z["prisada"], "arhiv")
        self.assertIsNone(z["otkas"])
        self.assertEqual(z["tekst_bytes"], 0)


@BEZ_INSTRUMENTI
@BEZ_DNEVNIK
class TestChovekatReshava(unittest.TestCase):
    def test_reshi_bez_rolya_i_s_ime(self):
        with Papka() as p:
            p.skanirai()
            predi = baytove(p.karta)
            self.assertEqual(p.hod("reshi", p.karta, "--klas", "opakovka", "--da")[0], 2)
            self.assertEqual(p.hod("reshi", p.karta, "--klas", "opakovka", "--da", "--ot", "Иван Иванов")[0], 2)
            self.assertEqual(predi, baytove(p.karta))

    def test_izhod_vatre_v_izvora_e_otkaz(self):
        with Papka() as p:
            predi = hashove(p.src)
            self.assertEqual(p.hod("skanirai", p.src, "--izhod", os.path.join(p.src, "karta.json"))[0], 2)
            p.skanirai()
            _da_i_vidyan(p, "opakovka")
            kod, _, err = p.hod("preobrazuvay", p.karta, "--izhod", os.path.join(p.src, "izhod"), "--go")
            self.assertEqual(kod, 2)
            self.assertEqual(p.hod("karta", p.karta, "--izhod", os.path.join(p.src, "karta.md"))[0], 2)
            self.assertEqual(predi, hashove(p.src))


@BEZ_INSTRUMENTI
@BEZ_DNEVNIK
class TestKartaIOtchet(unittest.TestCase):
    def test_formati(self):
        with Papka() as p:
            p.skanirai()
            kod, out, _ = p.hod("karta", p.karta)
            self.assertIn("## Не се работи от Сито", out)
            glaven, uved = out.split("## Не се работи от Сито")
            self.assertNotIn("snimka.jpg", glaven)
            self.assertIn("| извън обхвата | tablica | 1 |", uved)
            self.assertIn("| архив | arhiv | 2 |", uved)
            self.assertIn("| чист текст | tekst | 2 |", uved)
            self.assertIn("belezhka.md — споменава", uved)
            self.assertIn("невидян", glaven)
            kod, out, _ = p.hod("karta", p.karta, "--format", "html")
            self.assertTrue(out.startswith("<!doctype html>"))
            self.assertIn('href="file://', out)
            self.assertIn("golyam.html</a>", out)
            self.assertIn("<details><summary>откъс (", out)
            self.assertIn("Сито отделя смисъла", out)
            self.assertIn("Не се работи от Сито", out)
            kod, out, _ = p.hod("karta", p.karta, "--format", "csv")
            redove = list(csv.DictReader(io.StringIO(out)))
            self.assertEqual(len(redove), len(p.k()["faylove"]))
            self.assertIn("vidyan", redove[0])

    def test_otchet_pregledi(self):
        with Papka() as p:
            p.skanirai()
            _da_i_vidyan(p, "opakovka:html")
            _da_i_vidyan(p, "tekst:docx", vidyah=False)
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            kod, out, _ = p.hod("otchet", p.karta)
            self.assertEqual(kod, 0)
            self.assertIn("## Преглед и решения", out)
            # видени 1; решени „да“ 2 (html + docx); обработени 1; спрени като невидени 1
            self.assertRegex(out, r"\| 1 от \d+ \| 2 \| 2 \| 1 \| 1 \|")
            self.assertIn("Чакат преглед", out)
            self.assertIn("belezhki.docx", out.split("Чакат преглед")[1].split("## След")[0])
            self.assertIn("### Не се работи от Сито", out)


class TestHtmlIRtfPotok(unittest.TestCase):
    def _html(self, danni, razmeri):
        r = random.Random(1)

        def bl():
            i = 0
            while i < len(danni):
                n = r.choice(razmeri)
                yield danni[i:i + n]
                i += n
        return "".join(tekst.redove(html_tekst.tekst_ot_potok(bl(), CFG["html"]["propuskay_elementi"])))

    def test_granitsite_na_blokovete_ne_promenyat_teksta(self):
        with Papka(svyat_=False) as p:
            pat = os.path.join(p.d, "m.html")
            golyam_html(pat, abzatsi=6, css_kb=2, js_kb=2, b64_kb=4)
            danni = baytove(pat)
        cyal = self._html(danni, [len(danni)])
        self.assertEqual(cyal, self._html(danni, [1, 2, 3, 7, 13, 64, 500]))
        self.assertIn("Сито отделя смисъла", cyal)

    def test_kodirovka_cp1251(self):
        self.assertIn("Здравей", self._html('<meta charset="windows-1251"><p>Здравей</p>'.encode("cp1251"), [3]))

    def test_pametta_e_malka(self):
        blok = b"x" * (1 << 20)

        def potok():
            yield "<html><body><p>преди</p><script>".encode()
            for _ in range(15):
                yield blok
            yield b"</script><img src=\"data:image/png;base64,"
            for _ in range(15):
                yield b"QUFB" * (1 << 18)
            yield "\"><p>след</p></body></html>".encode()
        tracemalloc.start()
        try:
            t = "".join(tekst.redove(html_tekst.tekst_ot_potok(potok(), CFG["html"]["propuskay_elementi"])))
            _, vrah = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(t, "преди\n\nслед\n")
        self.assertLess(vrah, 16 << 20)

    def test_rtf_granitsi_na_blokove(self):
        with Papka(svyat_=False) as p:
            pat = os.path.join(p.d, "m.rtf")
            rtf(pat, ["Първи абзац с \\ обратна черта.", "Втори: " + "дума " * 50], kartinka_kb=8)
            danni = baytove(pat)

        def txt(n):
            return "".join(tekst.redove(rtf_tekst.tekst_ot_potok(danni[i:i + n] for i in range(0, len(danni), n))))
        cyal = txt(len(danni))
        self.assertEqual(cyal, txt(5))
        self.assertIn("Първи абзац с \\ обратна черта.", cyal)


class TestInstrumenti(unittest.TestCase):
    @unittest.skipUnless(instrumenti.nameri("pdftotext"), "няма pdftotext на машината")
    def test_tekstov_pdf(self):
        with Papka(svyat_=False) as p:
            pdf(os.path.join(p.src, "tekstov.pdf"), ["Sito extracts this sentence from a PDF " * 3] * 4)
            staro(p.src)
            p.skanirai()
            z = p.po_put("tekstov.pdf")
            p.hod("reshi", p.karta, "--fayl", z["id"], "--da", "--ot", ROLYA)
            p.vidyah(z["id"])
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertIn("Sito extracts this sentence", _md(p, z))

    @unittest.skipUnless(IMA_OCR, "няма pdftotext/pdftoppm/tesseract на машината")
    def test_skaniran_pdf_ocr(self):
        with Papka(svyat_=False) as p:
            skaniran_pdf(os.path.join(p.src, "skan.pdf"), ["SCANNED PAGE NUMBER 42", "Sito reads pictures"])
            staro(p.src)
            p.skanirai()
            z = p.po_put("skan.pdf")
            self.assertEqual(z["prisada"], "opakovka", z["prichina"])
            self.assertIn("OCR", z["proveri"])
            p.hod("reshi", p.karta, "--fayl", z["id"], "--da", "--ot", ROLYA)
            p.vidyah(z["id"])
            kod, out, err = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertEqual(kod, 0, err)
            self.assertIn("PAGE", _md(p, z).upper())

    @unittest.skipUnless(IMA_OCR, "няма pdftotext/pdftoppm/tesseract на машината")
    def test_smyana_na_prisadata_pri_ocr_spira(self):
        with Papka(svyat_=False) as p:
            skaniran_pdf(os.path.join(p.src, "skan.pdf"), ["CONTRACT", "INVOICE NUMBER 42"])
            staro(p.src)
            p.skanirai()
            z = p.po_put("skan.pdf")
            self.assertEqual(z["prisada"], "opakovka")
            p.hod("reshi", p.karta, "--fayl", z["id"], "--da", "--ot", ROLYA)
            p.vidyah(z["id"])
            kod, out, _ = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertIn("СПРЯН", out)
            z = p.po_put("skan.pdf")
            self.assertEqual(z["prisada"], "dokazatelstvo")
            self.assertIsNone(z["vidyan"])
            self.assertIsNone(z["preobrazuvan"])
            self.assertIn("нов преглед", z["spryan"]["prichina"])
            self.assertFalse(os.path.exists(os.path.join(p.izhod, z["id"] + ".md")))
            with open(os.path.join(p.izhod, "chunks.jsonl"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "")
            self.assertIn("спрян", p.hod("karta", p.karta)[1])
            # нов преглед → минава
            p.vidyah(z["id"])
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertIsNotNone(p.po_put("skan.pdf")["preobrazuvan"])

    @unittest.skipUnless(instrumenti.nameri("antiword") or instrumenti.nameri("catdoc"),
                         "няма antiword/catdoc на машината")
    def test_doc_s_instrument(self):
        with Papka() as p:
            p.skanirai()  # фалшивият .doc е само OLE заглавка: инструментът трябва да откаже → „неясно“
            self.assertEqual(p.po_put("star.doc")["prisada"], "neyasno")


class TestKonfig(unittest.TestCase):
    def test_v_koda_nyama_spisatsi(self):
        """Думите за доказателство, ролите и разширенията са само в config — не и в кода."""
        papka = os.path.join(APP, "sito")
        for ime in os.listdir(papka):
            if ime.endswith(".py"):
                with open(os.path.join(papka, ime), encoding="utf-8") as f:
                    s = f.read()
                for duma in ("фактура", "собственик на архива", "ЕИК", '".xlsx"', '".zip"', '".jpg"', '".txt"'):
                    self.assertNotIn(duma, s, "%s: „%s“ е в кода" % (ime, duma))

    def test_obhvatat_e_ot_config(self):
        with Papka(svyat_=False, izvan_obhvat={"dokumenti": [".docx"]},
                   vidove={"html": [".html"], "pdf": [".pdf"]}) as p:
            docx(os.path.join(p.src, "a.docx"), ["текст"])
            staro(p.src)
            self.assertEqual(p.skanirai()["faylove"][0]["prisada"], "izvan_obhvat")


if __name__ == "__main__":
    unittest.main()
