"""Сито през main() върху измислен свят: присъди, само четене, решения, преобразуване, отчет. Нула мрежа."""
import csv
import io
import json
import os
import random
import tracemalloc
import unittest
from unittest import mock

from obshto import ROLYA, Papka, baytove, golyam_html, hashove, pdf, pptx, skaniran_pdf, staro

from sito import config, html_tekst, instrumenti, tekst

BEZ_INSTRUMENTI = mock.patch.object(instrumenti, "nameri", lambda ime: None)
CFG = config.zaredi(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "config.example.json"))


def _md(p, z):
    with open(os.path.join(p.izhod, z["id"] + ".md"), encoding="utf-8") as f:
        return f.read()


@BEZ_INSTRUMENTI
@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestPrisadi(unittest.TestCase):
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
        self.assertEqual(z["klas"], "opakovka:html")
        self.assertLess(z["ochakvan_md_bytes"], 0.01 * z["razmer"])
        self.assertIn("студен архив", z["predlozhenie"])

    def test_dublikat(self):
        z = self.z["kopiya/golyam.html"]
        self.assertEqual(z["prisada"], "dublikat")
        self.assertEqual(z["dublikat_na"], self.z["golyam.html"]["id"])
        # дубликат и вътре в архив: копието на belezhki.docx сочи към оригинала
        v = self.z["sabrano/arhiv.zip!/vatre/belezhki_kopie.docx"]
        self.assertEqual(v["prisada"], "dublikat")
        self.assertEqual(v["dublikat_na"], self.z["belezhki.docx"]["id"])

    def test_dogovor_e_dokazatelstvo(self):
        z = self.z["dogovor.docx"]
        self.assertEqual(z["prisada"], "dokazatelstvo")
        self.assertIn("ЕИК/БУЛСТАТ номер", z["signali"])
        self.assertIn("дума: договор", z["signali"])

    def test_podpisan_pdf_e_dokazatelstvo_i_bez_pdftotext(self):
        z = self.z["podpisan.pdf"]
        self.assertEqual(z["prisada"], "dokazatelstvo")
        self.assertTrue(any("поле за електронен подпис" in s for s in z["signali"]))
        self.assertIn("няма pdftotext", z["problem"])  # MD не може, но присъдата е ясна
        self.assertIn("няма qpdf/Ghostscript", z["predlozhenie"])

    def test_docx_e_tekst(self):
        z = self.z["belezhki.docx"]
        self.assertEqual(z["prisada"], "tekst")
        self.assertGreater(z["tekst_bytes"], 10000)

    def test_pptx_opakovka(self):
        z = self.z["prezentaciya.pptx"]
        self.assertEqual(z["prisada"], "opakovka")

    def test_zhiv_po_pat(self):
        z = self.z["rabotni/plan.txt"]
        self.assertEqual(z["prisada"], "zhiv")
        self.assertIn("rabotni/*", z["prichina"])

    def test_zip_kontejner_i_deca(self):
        z = self.z["sabrano/arhiv.zip"]
        self.assertEqual(z["prisada"], "kontejner")
        dete = self.z["sabrano/arhiv.zip!/vatre/v_arhiv.docx"]
        self.assertEqual(dete["roditel"], z["id"])
        self.assertEqual(dete["prisada"], "tekst")
        self.assertIsNotNone(dete["sha256"])

    def test_eml_i_prikacheni(self):
        z = self.z["pismo.eml"]
        self.assertEqual(z["prisada"], "tekst")
        dete = self.z["pismo.eml!/1_belezhka.txt"]
        self.assertEqual(dete["roditel"], z["id"])
        self.assertEqual(dete["vid"], "tekst")

    def test_neyasni(self):
        self.assertIn("криптиран", self.z["zaklyuchen.zip!/tayno.txt"]["prichina"])
        self.assertEqual(self.z["zaklyuchen.zip!/tayno.txt"]["prisada"], "neyasno")
        self.assertEqual(self.z["povreden.docx"]["prisada"], "neyasno")
        self.assertIn("повреден", self.z["povreden.docx"]["prichina"])
        self.assertEqual(self.z["snimka.jpg"]["prisada"], "neyasno")
        self.assertEqual(self.z["zapis.mp3"]["prisada"], "neyasno")
        self.assertIn("Whisper", self.z["zapis.mp3"]["prichina"])

    def test_sistemnite_se_propuskat(self):
        self.assertNotIn(".DS_Store", self.z)
        self.assertEqual(self.k["propusnati"]["sistemni"], 1)

    def test_idta_sa_unikalni_i_stabilni(self):
        idta = [z["id"] for z in self.k["faylove"]]
        self.assertEqual(len(idta), len(set(idta)))
        k2 = self.p.skanirai()
        self.assertEqual(idta, [z["id"] for z in k2["faylove"]])


@BEZ_INSTRUMENTI
@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestPotok(unittest.TestCase):
    def test_zhiv_po_data(self):
        with Papka() as p:
            pat = os.path.join(p.src, "belezhki.docx")
            t = 1790380800  # 2026-09-26 — два дни преди „сега“
            os.utime(pat, (t, t))
            p.skanirai()
            self.assertEqual(p.po_put("belezhki.docx")["prisada"], "zhiv")
            self.assertIn("30 дни", p.po_put("belezhki.docx")["prichina"])

    def test_tavan_za_razmer_i_vreme(self):
        with Papka(maks_razmer_bytes=100000) as p:
            p.skanirai()
            z = p.po_put("golyam.html")
            self.assertEqual(z["prisada"], "neyasno")
            self.assertIn("над тавана за размер", z["prichina"])
        with Papka(maks_vreme_s=0) as p:
            p.skanirai()
            self.assertIn("над тавана за време", p.po_put("golyam.html")["prichina"])

    def test_izhodnata_papka_e_nepromenena(self):
        """Целият ход — skanirai, karta, reshi, preobrazuvay --go, otchet — не пипа изходната папка."""
        with Papka() as p:
            predi = hashove(p.src)
            p.skanirai()
            for fmt in ("md", "html", "csv"):
                self.assertEqual(p.hod("karta", p.karta, "--format", fmt)[0], 0)
            self.assertEqual(p.hod("reshi", p.karta, "--klas", "opakovka", "--da", "--ot", ROLYA)[0], 0)
            self.assertEqual(p.hod("reshi", p.karta, "--klas", "tekst", "--da", "--ot", ROLYA)[0], 0)
            self.assertEqual(p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")[0], 0)
            self.assertEqual(p.hod("otchet", p.karta)[0], 0)
            self.assertEqual(predi, hashove(p.src))

    def test_bez_reshenie_go_ne_pishe_nishto(self):
        with Papka() as p:
            p.skanirai()
            predi = baytove(p.karta)
            kod, out, err = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertEqual(kod, 0, err)
            self.assertIn("нищо не е записано", out)
            self.assertFalse(os.path.exists(p.izhod))
            self.assertEqual(predi, baytove(p.karta))
            # и решено „не“ също не пише
            p.hod("reshi", p.karta, "--klas", "opakovka", "--ne", "--ot", ROLYA)
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertFalse(os.path.exists(p.izhod))

    def test_plan_bez_go_ne_pishe(self):
        with Papka() as p:
            p.skanirai()
            p.hod("reshi", p.karta, "--klas", "opakovka:html", "--da", "--ot", ROLYA)
            kod, out, _ = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod)
            self.assertEqual(kod, 0)
            self.assertIn("golyam.html", out)
            self.assertIn("--go", out)
            self.assertFalse(os.path.exists(p.izhod))

    def test_golyam_html_pod_1_procent(self):
        with Papka() as p:
            p.skanirai()
            p.hod("reshi", p.karta, "--klas", "opakovka:html", "--da", "--ot", ROLYA)
            kod, out, err = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertEqual(kod, 0, err)
            z = p.po_put("golyam.html")
            md = _md(p, z)
            self.assertLess(z["preobrazuvan"]["md_bytes"], 0.01 * z["razmer"])
            self.assertEqual(z["preobrazuvan"]["md_bytes"], len(md.encode("utf-8")))
            self.assertEqual(z["preobrazuvan"]["md_bytes"], z["ochakvan_md_bytes"] - len("0000-00-00T00:00:00Z")
                             + len(z["preobrazuvan"]["t"]))
            self.assertIn('istochnik: "golyam.html"', md)
            self.assertIn("sha256: " + z["sha256"], md)
            self.assertIn("# Въздух под налягане", md)
            self.assertIn("# Отчет за въздуха", md)
            self.assertEqual(md.count("Сито отделя смисъла от въздуха."), 40)
            for ne in ("function", "base64", "color:#", "Меню", "не е текст", "коментар"):
                self.assertNotIn(ne, md)
            # дубликатът не се преобразува, дори клас „dublikat“ да е поискан
            self.assertFalse(os.path.exists(os.path.join(p.izhod, p.po_put("kopiya/golyam.html")["id"] + ".md")))

    def test_chunks(self):
        with Papka() as p:
            p.skanirai()
            z = p.po_put("belezhki.docx")
            p.hod("reshi", p.karta, "--fayl", z["id"], "--da", "--ot", ROLYA)
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            with open(os.path.join(p.izhod, "chunks.jsonl"), encoding="utf-8") as f:
                ch = [json.loads(r) for r in f]
            self.assertGreaterEqual(len(ch), 3)
            do = 0
            for i, c in enumerate(ch):
                self.assertEqual(c["id"], "%s-%04d" % (z["id"], i))
                self.assertEqual(c["istochnik"], "belezhki.docx")
                self.assertEqual(c["sha256"], z["sha256"])
                self.assertEqual(c["poziciya"]["n"], i)
                self.assertEqual(c["poziciya"]["ot_duma"], do)
                do = c["poziciya"]["do_duma"]
                self.assertLessEqual(c["dumi"], 800)
                self.assertEqual(c["dumi"], len(c["tekst"].split()))
            self.assertGreater(ch[0]["dumi"], 600)
            self.assertEqual(p.po_put("belezhki.docx")["preobrazuvan"]["chunks"], len(ch))
            md = _md(p, z)
            self.assertIn("# Бележки от срещата", md)
            self.assertIn("край", md)

    def test_pptx_s_belezhki(self):
        with Papka() as p:
            p.skanirai()
            p.hod("reshi", p.karta, "--klas", "opakovka:pptx", "--da", "--ot", ROLYA)
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            md = _md(p, p.po_put("prezentaciya.pptx"))
            self.assertIn("## Слайд 1", md)
            self.assertIn("22 KB смисъл", md)
            self.assertIn("**Бележки:**", md)
            self.assertIn("Бележка на говорителя: кажи числата.", md)
            self.assertIn("## Слайд 2", md)
            self.assertEqual(md.count("**Бележки:**"), 1)

    def test_zip_i_eml_deca_se_preobrazuvat(self):
        with Papka() as p:
            p.skanirai()
            p.hod("reshi", p.karta, "--klas", "tekst", "--da", "--ot", ROLYA)
            kod, out, err = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertEqual(kod, 0, err)
            self.assertIn("Документ в архив", _md(p, p.po_put("sabrano/arhiv.zip!/vatre/v_arhiv.docx")))
            self.assertIn("Прикачена бележка", _md(p, p.po_put("pismo.eml!/1_belezhka.txt")))
            pismo = _md(p, p.po_put("pismo.eml"))
            self.assertIn("Тема: Измислено писмо", pismo)
            self.assertIn("прикачвам файловете", pismo)

    def test_promenen_sled_skaniraneto_se_propuska(self):
        with Papka() as p:
            p.skanirai()
            p.hod("reshi", p.karta, "--fayl", p.po_put("belezhki.docx")["id"], "--da", "--ot", ROLYA)
            with open(os.path.join(p.src, "belezhki.docx"), "ab") as f:  # тестът е „човекът“, не Сито
                f.write(b"\0")
            kod, out, _ = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertEqual(kod, 0)
            self.assertIn("променен след сканирането", out)
            self.assertIsNone(p.po_put("belezhki.docx")["preobrazuvan"])


@BEZ_INSTRUMENTI
@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestChovekatReshava(unittest.TestCase):
    def test_bez_rolya_i_s_ime(self):
        with Papka() as p:
            p.skanirai()
            predi = baytove(p.karta)
            kod, _, err = p.hod("reshi", p.karta, "--klas", "opakovka", "--da")
            self.assertEqual(kod, 2)
            self.assertIn("роля", err)
            kod, _, err = p.hod("reshi", p.karta, "--klas", "opakovka", "--da", "--ot", "Иван Иванов")
            self.assertEqual(kod, 2)
            self.assertIn("не е роля", err)
            self.assertEqual(predi, baytove(p.karta))

    def test_partidno_i_po_fayl(self):
        with Papka() as p:
            p.skanirai()
            kod, out, _ = p.hod("reshi", p.karta, "--klas", "opakovka", "--da", "--ot", ROLYA)
            self.assertEqual(kod, 0)
            k = p.k()
            for z in k["faylove"]:
                if z["prisada"] == "opakovka":
                    self.assertEqual(z["reshenie"]["da"], True)
                    self.assertEqual(z["reshenie"]["rolya"], ROLYA)
                    self.assertEqual(z["reshenie"]["nachin"], "klas")
                else:
                    self.assertIsNone(z["reshenie"])
            z = p.po_put("prezentaciya.pptx")
            p.hod("reshi", p.karta, "--fayl", z["id"], "--ne", "--ot", ROLYA)
            self.assertEqual(p.po_put("prezentaciya.pptx")["reshenie"]["da"], False)
            self.assertEqual(p.hod("reshi", p.karta, "--fayl", "nyama", "--da", "--ot", ROLYA)[0], 1)
            self.assertEqual(p.hod("reshi", p.karta, "--klas", "nyama:takav", "--da", "--ot", ROLYA)[0], 1)

    def test_da_za_dublikat_ne_se_zapisva(self):
        with Papka() as p:
            p.skanirai()
            kod, out, _ = p.hod("reshi", p.karta, "--klas", "dublikat", "--da", "--ot", ROLYA)
            self.assertEqual(kod, 0)
            self.assertIn("пропуснати", out)
            self.assertIsNone(p.po_put("kopiya/golyam.html")["reshenie"])

    def test_izhod_vatre_v_izvora_e_otkaz(self):
        with Papka() as p:
            predi = hashove(p.src)
            kod, _, err = p.hod("skanirai", p.src, "--izhod", os.path.join(p.src, "karta.json"))
            self.assertEqual(kod, 2)
            p.skanirai()
            p.hod("reshi", p.karta, "--klas", "opakovka", "--da", "--ot", ROLYA)
            kod, _, err = p.hod("preobrazuvay", p.karta, "--izhod", os.path.join(p.src, "izhod"), "--go")
            self.assertEqual(kod, 2)
            self.assertIn("само чете", err)
            kod, _, _ = p.hod("karta", p.karta, "--izhod", os.path.join(p.src, "karta.md"))
            self.assertEqual(kod, 2)
            self.assertEqual(predi, hashove(p.src))

    def test_nyama_papka(self):
        with Papka(svyat_=False) as p:
            self.assertEqual(p.hod("skanirai", os.path.join(p.d, "nyama"), "--izhod", p.karta)[0], 1)


@BEZ_INSTRUMENTI
@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestKartaIOtchet(unittest.TestCase):
    def test_formati(self):
        with Papka() as p:
            p.skanirai()
            kod, out, _ = p.hod("karta", p.karta)
            self.assertEqual(kod, 0)
            self.assertIn("| `opakovka:html` | опаковка |", out)
            self.assertIn("reshi karta.json --klas opakovka:html", out)
            kod, out, _ = p.hod("karta", p.karta, "--format", "html")
            self.assertTrue(out.startswith("<!doctype html>"))
            self.assertIn("prefers-color-scheme", out)
            kod, out, _ = p.hod("karta", p.karta, "--format", "csv")
            redove = list(csv.DictReader(io.StringIO(out)))
            self.assertEqual(len(redove), len(p.k()["faylove"]))
            self.assertEqual({r["prisada"] for r in redove if r["put"] == "golyam.html"}, {"opakovka"})
            izh = os.path.join(p.d, "karta.md")
            self.assertEqual(p.hod("karta", p.karta, "--izhod", izh)[0], 0)
            self.assertTrue(os.path.exists(izh))

    def test_otchet_predi_i_sled(self):
        with Papka() as p:
            p.skanirai()
            kod, out, _ = p.hod("otchet", p.karta)
            self.assertIn("## Преди", out)
            self.assertIn("Нищо не е преобразувано", out)
            p.hod("reshi", p.karta, "--klas", "opakovka:html", "--da", "--ot", ROLYA)
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            kod, out, _ = p.hod("otchet", p.karta)
            self.assertEqual(kod, 0)
            self.assertIn("реален MD", out)
            self.assertIn("| golyam.html | опаковка |", out)

    def test_nerazbiraema_karta(self):
        with Papka(svyat_=False) as p:
            with open(p.karta, "w") as f:
                f.write("{}")
            self.assertEqual(p.hod("karta", p.karta)[0], 1)


class TestHtmlPotok(unittest.TestCase):
    def _tekst(self, danni, razmeri):
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
        cyal = self._tekst(danni, [len(danni)])
        self.assertEqual(cyal, self._tekst(danni, [1, 2, 3, 7, 13, 64, 500]))
        self.assertIn("Сито отделя смисъла", cyal)
        self.assertNotIn("base64", cyal)

    def test_samozatvaryasht_i_entitii(self):
        t = self._tekst("<p>A&amp;B</p><svg/><p>след svg</p><script src=x></script><p>край</p>".encode(), [5])
        self.assertEqual(t, "A&B\n\nслед svg\n\nкрай\n")

    def test_kodirovka_cp1251(self):
        danni = '<meta charset="windows-1251"><p>Здравей</p>'.encode("cp1251")
        self.assertIn("Здравей", self._tekst(danni, [3]))

    def test_pametta_e_malka(self):
        """30 MB скрипт и base64 минават с памет под 16 MB — нищо не се държи цяло."""
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


class TestInstrumenti(unittest.TestCase):
    @unittest.skipUnless(instrumenti.nameri("pdftotext"), "няма pdftotext на машината")
    def test_tekstov_pdf(self):
        with Papka(svyat_=False) as p:
            pdf(os.path.join(p.src, "tekstov.pdf"), ["Sito extracts this sentence from a PDF " * 3] * 4)
            staro(p.src)
            p.skanirai()
            z = p.po_put("tekstov.pdf")
            self.assertNotEqual(z["prisada"], "neyasno", z["prichina"])
            p.hod("reshi", p.karta, "--fayl", z["id"], "--da", "--ot", ROLYA)
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertIn("Sito extracts this sentence", _md(p, z))

    @unittest.skipUnless(all(map(instrumenti.nameri, ("pdftotext", "pdftoppm", "tesseract"))),
                         "няма pdftotext/pdftoppm/tesseract на машината")
    def test_skaniran_pdf_ocr(self):
        with Papka(svyat_=False) as p:
            skaniran_pdf(os.path.join(p.src, "skan.pdf"), ["SCANNED INVOICE NUMBER 42", "Sito reads pictures"])
            staro(p.src)
            p.skanirai()
            z = p.po_put("skan.pdf")
            self.assertEqual(z["prisada"], "opakovka", z["prichina"])
            self.assertIn("сканиран", z["prichina"])
            self.assertIn("OCR", z["proveri"])
            self.assertIsNone(z["ochakvan_md_bytes"])  # OCR се отлага за преобразуването
            p.hod("reshi", p.karta, "--fayl", z["id"], "--da", "--ot", ROLYA)
            kod, out, err = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertEqual(kod, 0, err)
            md = _md(p, z)
            self.assertIn("INVOICE", md.upper())
            self.assertIn("proveri:", md)
            with open(os.path.join(p.izhod, "chunks.jsonl"), encoding="utf-8") as f:
                self.assertIn("proveri", json.loads(f.readline()))

    @unittest.skipUnless(all(map(instrumenti.nameri, ("pdftotext", "pdftoppm", "tesseract"))),
                         "няма pdftotext/pdftoppm/tesseract на машината")
    def test_skaniran_dogovor_sled_ocr_e_dokazatelstvo(self):
        with Papka(svyat_=False) as p:
            skaniran_pdf(os.path.join(p.src, "skan.pdf"), ["CONTRACT", "INVOICE NUMBER 42"])
            staro(p.src)
            p.skanirai()
            z = p.po_put("skan.pdf")
            self.assertEqual(z["prisada"], "opakovka")
            self.assertIn("след OCR", z["prichina"])
            p.hod("reshi", p.karta, "--fayl", z["id"], "--da", "--ot", ROLYA)
            kod, out, _ = p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            self.assertIn("признаци на доказателство", out)
            z = p.po_put("skan.pdf")
            self.assertEqual(z["prisada"], "dokazatelstvo")
            self.assertEqual(z["preobrazuvan"]["prisada_smenena"], {"ot": "opakovka", "na": "dokazatelstvo"})

    @unittest.skipUnless(instrumenti.nameri("soffice"), "няма LibreOffice на машината")
    def test_pptx_pdf_izgled(self):
        with Papka(svyat_=False, pptx_pdf_izgled=True) as p:
            pptx(os.path.join(p.src, "d.pptx"), [("Изглед", ["ред"], "бележка")], snimka_kb=1)
            staro(p.src)
            predi = hashove(p.src)
            p.skanirai()
            z = p.po_put("d.pptx")
            p.hod("reshi", p.karta, "--fayl", z["id"], "--da", "--ot", ROLYA)
            p.hod("preobrazuvay", p.karta, "--izhod", p.izhod, "--go")
            pr = p.po_put("d.pptx")["preobrazuvan"]
            if "pdf_izgled_greshka" in pr:
                self.skipTest("LibreOffice не успя тук: %s" % pr["pdf_izgled_greshka"])
            with open(os.path.join(p.izhod, pr["pdf_izgled"]), "rb") as f:
                self.assertEqual(f.read(5), b"%PDF-")
            self.assertEqual(predi, hashove(p.src))  # без lock файлове до оригинала


class TestKonfig(unittest.TestCase):
    def test_v_koda_nyama_spisatsi(self):
        """Думите за доказателство и ролите са само в config — не и в кода."""
        papka = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sito")
        for ime in os.listdir(papka):
            if ime.endswith(".py"):
                with open(os.path.join(papka, ime), encoding="utf-8") as f:
                    s = f.read()
                for duma in ("фактура", "собственик на архива", "ЕИК"):
                    self.assertNotIn(duma, s, "%s: „%s“ е в кода" % (ime, duma))


if __name__ == "__main__":
    unittest.main()
