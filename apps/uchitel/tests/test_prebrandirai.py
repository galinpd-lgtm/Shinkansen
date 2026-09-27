"""Поправката: никога върху входа, разликата е само лого/шрифт/етикети, цялост, повторно пускане, отчети."""
import csv
import difflib
import hashlib
import json
import os
import re
import unittest
from unittest import mock

from obshto import KANON_PAT, PRIMERI, VremennaPapka, otpechatak_papka, procheti, pusni

from uchitel import popravki

POPRAVENI = ["ai_arhitekt/AA_01_Rolite.html", "devstation/DS_01_Start.html", "gx10/GX_01_Laboratoriya.html",
             "kagami_way/KW_01_Uvod.html", "n8n/N8_01_Parvi_potok.html"]
ZA_RACHNO = ["bez_logo/BL_01_Index.html", "schupeno/SC_01_Schupeno.html"]

# Всеки сменен ред трябва да е за логото, шрифтовете или етикетите — нищо друго.
RAZRESHENI = re.compile(r"kg-logo|data-uchitel|fonts\.googleapis\.com|font-family|font:|topbar-brand|class=\"(?:logo|brand|nav-brand)\""
                        r"|btn-human|btn-agent|^\s*$")


def sha(pat):
    with open(pat, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class TestGo(unittest.TestCase):
    def test_go_ne_pishe_varhu_vhoda(self):
        with VremennaPapka() as v:
            predi = otpechatak_papka(v.vhod)
            kod, out, _err = pusni("prebrandirai", v.vhod, "--izhod", v.pat("izh"), "--go")
            self.assertEqual(kod, 4)   # има файлове „за ръчно“
            self.assertEqual(otpechatak_papka(v.vhod), predi)
            self.assertIn("Входът не е пипан", out)
            self.assertEqual(sorted(os.listdir(v.vhod)), sorted(os.listdir(v.pat("izh"))))

    def test_izhodat_e_palno_kopie(self):
        """Празните папки и символните връзки също са в изхода; връзките остават връзки."""
        with VremennaPapka() as v:
            os.makedirs(os.path.join(v.vhod, "prazna"))
            os.symlink("gx10", os.path.join(v.vhod, "gx10_vrazka"))
            os.symlink("GX_01_Laboratoriya.html", os.path.join(v.vhod, "gx10", "posledno.html"))
            pusni("prebrandirai", v.vhod, "--izhod", v.pat("izh"), "--go")
            self.assertTrue(os.path.isdir(v.pat("izh", "prazna")))
            self.assertEqual(os.readlink(v.pat("izh", "gx10_vrazka")), "gx10")
            self.assertEqual(os.readlink(v.pat("izh", "gx10", "posledno.html")), "GX_01_Laboratoriya.html")
            self.assertIn("kg-logo", procheti("gx10/posledno.html", v.pat("izh")))   # сочи поправения файл

    def test_bez_go_nishto_ne_se_pishe(self):
        with VremennaPapka() as v:
            predi = otpechatak_papka(v.vhod)
            kod, out, _err = pusni("prebrandirai", v.vhod, "--izhod", v.pat("izh"))
            self.assertEqual(otpechatak_papka(v.vhod), predi)
            self.assertFalse(os.path.exists(v.pat("izh")))
            self.assertFalse(os.path.exists(v.pat("izh.otchet")))
            self.assertIn("Разлика (нищо не е записано", out)
            self.assertIn("+++ след/gx10/GX_01_Laboratoriya.html", out)

    def test_otkazva_izhod_vav_vhoda_i_palna_papka(self):
        with VremennaPapka() as v:
            predi = otpechatak_papka(v.vhod)
            for izhod in (v.vhod, os.path.join(v.vhod, "novo"), v.koren):
                kod, _out, err = pusni("prebrandirai", v.vhod, "--izhod", izhod, "--go")
                self.assertEqual(kod, 2, izhod)
                self.assertIn("отказвам", err)
            os.makedirs(v.pat("palna"))
            open(v.pat("palna", "x.txt"), "w").close()
            kod, _out, err = pusni("prebrandirai", v.vhod, "--izhod", v.pat("palna"), "--go")
            self.assertEqual(kod, 2)
            self.assertIn("не е празна", err)
            self.assertEqual(otpechatak_papka(v.vhod), predi)
            self.assertFalse(os.path.exists(os.path.join(v.vhod, "novo")))

    def test_otchetat_ne_moje_vav_vhoda(self):
        with VremennaPapka() as v:
            kod, _out, err = pusni("prebrandirai", v.vhod, "--izhod", v.pat("izh"), "--go",
                                   "--otchet", os.path.join(v.vhod, "otchet"))
            self.assertEqual(kod, 2)
            self.assertFalse(os.path.exists(v.pat("izh")))


class TestRezultat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = VremennaPapka().__enter__()
        cls.izh = cls.v.pat("izh")
        cls.kod, cls.out, _ = pusni("prebrandirai", cls.v.vhod, "--izhod", cls.izh, "--go")

    @classmethod
    def tearDownClass(cls):
        cls.v.__exit__()

    def test_razlikata_e_samo_logo_shrift_etiketi(self):
        for rel in POPRAVENI:
            staro, novo = procheti(rel, self.v.vhod), procheti(rel, self.izh)
            self.assertNotEqual(staro, novo, rel)
            for red in difflib.unified_diff(staro.splitlines(), novo.splitlines(), n=0, lineterm=""):
                if red.startswith(("---", "+++", "@@")):
                    continue
                if red[1:].strip().startswith("@import"):
                    continue
                self.assertRegex(red[1:], RAZRESHENI, "%s: неочаквана промяна: %s" % (rel, red[:160]))

    def test_logoto_e_kanonichno(self):
        nov = procheti("gx10/GX_01_Laboratoriya.html", self.izh)
        self.assertIn('<span class="topbar-brand"><span class="kg-logo"><img class="kg-logo-znak" src="data:image/png;base64,', nov)
        self.assertIn('<span class="kg-logo-ime">КАГАМИ</span><span class="kg-logo-kurs">GX10 Хъб · Лаборатория</span>', nov)
        self.assertNotIn("⬡", nov)
        self.assertEqual(nov.count('<style data-uchitel="logo">'), 1)
        nov = procheti("ai_arhitekt/AA_01_Rolite.html", self.izh)
        self.assertNotIn("🧠", nov)
        self.assertIn('<a class="topbar-brand" href="index.html">', procheti("kagami_way/KW_01_Uvod.html", self.izh))

    def test_shriftove(self):
        nov = procheti("ai_arhitekt/AA_01_Rolite.html", self.izh)
        self.assertEqual(nov.count("fonts.googleapis.com"), 1)   # подменена, не добавена втора
        self.assertNotIn("Inter", nov)
        self.assertIn(".hero h1{font-family:'Sora', sans-serif;", nov)   # 'Inter', 'Sora' → без повторение
        self.assertIn(".note{font:600 .9rem/1.5 'Sora',sans-serif}", nov)
        nov = procheti("kagami_way/KW_01_Uvod.html", self.izh)
        self.assertNotIn("DM Serif", nov)
        self.assertNotIn("Plus Jakarta", nov)

    def test_etiketi(self):
        nov = procheti("n8n/N8_01_Parvi_potok.html", self.izh)
        self.assertIn('<span class="bg-only">Човек</span><span class="en-only">HUMAN</span>', nov)
        self.assertIn('<span class="bg-only">Агент</span><span class="en-only">AGENT</span>', nov)
        self.assertIn("AGENT VIEW — ENGLISH ONLY", nov)   # коментарът и изгледът за агента не се пипат

    def test_za_rachno_se_kopirat_kakto_sa(self):
        for rel in ZA_RACHNO + ["gx10/img/shema.svg"]:
            self.assertEqual(sha(os.path.join(self.v.vhod, rel)), sha(os.path.join(self.izh, rel)), rel)

    def test_otchetite(self):
        otchet = self.izh + ".otchet"
        self.assertEqual(sorted(os.listdir(otchet)),
                         ["failove.csv", "otchet.md", "po_papki.csv", "po_pravila.csv", "za_rachno.csv"])
        with open(os.path.join(otchet, "failove.csv"), encoding="utf-8-sig") as f:
            redove = {r["файл"]: r for r in csv.DictReader(f)}
        for rel, r in redove.items():
            self.assertEqual(r["sha256 преди"], sha(os.path.join(self.v.vhod, rel)), rel)
            self.assertEqual(r["sha256 след"], sha(os.path.join(self.izh, rel)), rel)
        self.assertEqual(redove["gx10/GX_01_Laboratoriya.html"]["състояние"], "променен")
        self.assertEqual(redove["schupeno/SC_01_Schupeno.html"]["състояние"], "за ръчно")
        with open(os.path.join(otchet, "za_rachno.csv"), encoding="utf-8-sig") as f:
            zr = list(csv.DictReader(f))
        self.assertIn(("schupeno/SC_01_Schupeno.html", "не"), [(r["файл"], r["записан"]) for r in zr])
        md = procheti(os.path.join(otchet, "otchet.md"))
        for zaglavie in ("## По папки", "## По правила", "## За ръчно", "## Променени файлове"):
            self.assertIn(zaglavie, md)

    def test_povtorno_pusnato_nishto_ne_smenya(self):
        kod, out, _err = pusni("prebrandirai", self.izh, "--izhod", self.v.pat("izh2"))
        self.assertIn("Няма какво да се промени", out)
        self.assertNotIn("[променен]", out)
        kod, out, _err = pusni("proveri", self.izh, "--format", "json")
        d = {x["fail"]: x for x in json.loads(out)}
        for rel in POPRAVENI:
            st = {p["pravilo"]: p["status"] for p in d[rel]["pravila"]}
            self.assertEqual((st["лого"], st["шрифтове"]), ("ок", "ок"), rel)


class TestCelostVPopravkata(unittest.TestCase):
    def test_povredeno_sadarzhanie_ne_se_pishe(self):
        """Ако поправката по грешка махне заглавие, файлът отива „за ръчно“ и се копира както е."""
        istinska = popravki.prilozhi

        def povredi(html, redakcii):
            return re.sub(r"(?s)<h2[^>]*>.*?</h2>", "", istinska(html, redakcii), count=1)

        with VremennaPapka() as v, mock.patch.object(popravki, "prilozhi", povredi):
            kod, out, _err = pusni("prebrandirai", v.vhod, "--izhod", v.pat("izh"), "--go")
            self.assertEqual(kod, 4)
            self.assertNotIn("[променен]", out)
            for rel in POPRAVENI:
                self.assertEqual(sha(os.path.join(v.vhod, rel)), sha(os.path.join(v.pat("izh"), rel)), rel)
            with open(v.pat("izh.otchet", "za_rachno.csv"), encoding="utf-8-sig") as f:
                zr = [r for r in csv.DictReader(f) if r["правило"] == "цялост"]
            self.assertEqual(len(zr), len(POPRAVENI))
            self.assertIn("заглавия", zr[0]["бележка"])

    def test_bez_logo_s_ime_po_papka_se_popravya(self):
        with VremennaPapka() as v:
            with open(KANON_PAT, encoding="utf-8") as f:
                k = json.load(f)
            k["logo"]["ime_po_papka"] = {"bez_logo": "Съдържание"}
            k["logo"]["znak"] = os.path.join(os.path.dirname(PRIMERI), "znak_primer.png")
            with open(v.pat("kanon.json"), "w", encoding="utf-8") as f:
                json.dump(k, f, ensure_ascii=False)
            pusni("prebrandirai", v.vhod, "--izhod", v.pat("izh"), "--go", "--config", v.pat("kanon.json"))
            nov = procheti("bez_logo/BL_01_Index.html", v.pat("izh"))
            self.assertIn('<div class="topbar"><span class="topbar-brand"><span class="kg-logo">', nov)
            self.assertIn('<span class="kg-logo-kurs">Съдържание</span>', nov)


class TestOtchetKomanda(unittest.TestCase):
    def test_pishe_otcheta_izvan_vhoda(self):
        with VremennaPapka() as v:
            predi = otpechatak_papka(v.vhod)
            kod, out, _err = pusni("otchet", v.vhod, "--izhod", v.pat("otchet"))
            self.assertEqual(kod, 0)
            self.assertIn("otchet.md", os.listdir(v.pat("otchet")))
            self.assertEqual(otpechatak_papka(v.vhod), predi)
            kod, _out, err = pusni("otchet", v.vhod, "--izhod", os.path.join(v.vhod, "otchet"))
            self.assertEqual(kod, 2)
            self.assertEqual(otpechatak_papka(v.vhod), predi)


if __name__ == "__main__":
    unittest.main()
