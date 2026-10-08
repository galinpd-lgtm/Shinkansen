"""Мисиите, т. 1–4: config, схемите и валидаторът, генераторът и подписът. Нула мрежа."""
import copy
import json
import os
import random
import re
import tempfile
import unittest
from unittest import mock

from obshto import APP, CFG, CFG_PAT, DATA, FIX, KLYUCH, RAYON, fix, hod

from misii import config, generator, podpis, validator

VSICHKI_OBLASTI = ["kultura", "sport", "turizam", "obrazovanie", "sabitiya", "npo", "msp"]
BEZ_DNEVNIK = {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""}


def _tekst(pat):
    with open(pat, encoding="utf-8") as f:
        return f.read()


def _cheti(pat):
    return json.loads(_tekst(pat))


def _pishi(pat, d):
    with open(pat, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)


def _gen(oblasti=VSICHKI_OBLASTI, baza=None, data=DATA, cfg=CFG, rayon=RAYON):
    return generator.generiray(baza if baza is not None else fix("baza.json"), rayon, oblasti, cfg, data)


class TestConfig(unittest.TestCase):
    def test_primerat_se_zarezhda(self):
        self.assertEqual(set(CFG["oblasti"]), set(VSICHKI_OBLASTI))

    def test_nepoznat_vid_v_config(self):
        with tempfile.TemporaryDirectory() as d:
            c = _cheti(CFG_PAT)
            c["oblasti"]["kultura"]["poleta"]["rabotno_vreme"]["vid"] = "mnenie_za_direktora"
            p = os.path.join(d, "c.json")
            _pishi(p, c)
            with self.assertRaises(config.GreshkaConfig):
                config.zaredi(p)

    def test_v_primerite_samo_example(self):
        for koren, _, faylove in os.walk(APP):
            if "__pycache__" in koren:
                continue
            for f in faylove:
                if not f.endswith((".json", ".py", ".md")):
                    continue
                tekst = _tekst(os.path.join(koren, f))
                for host in re.findall(r"https?://([a-z0-9.-]+)", tekst):
                    self.assertRegex(host, r"(^|\.)example\.(com|org|net)$|^json-schema\.org$|^www\.openstreetmap\.org$"
                                           r"|^github\.com$|^creativecommons\.org$", "%s: %s" % (f, host))


class TestValidator(unittest.TestCase):
    def test_primerite(self):
        ochakvano = {
            "otgovor_dobar.json": ("otgovor", []),
            "prinos_dobar.json": ("prinos", []),
            "otgovor_dete_samo.json": ("otgovor", ["само пълнолетни"]),
            "otgovor_s_lokatsiya.json": ("otgovor", ["непознато поле „lat“", "непознато поле „lon“"]),
            "prinos_lichni_danni.json": ("prinos", ["няма име", "личен имейл", "телефонен номер"]),
            "misiya_za_chovek.json": ("misiya", ["„mnenie“ не е позволено", "непознато поле „direktor“"]),
        }
        for f, (vid, chasti) in ochakvano.items():
            g = validator.validirai(fix(f), vid, CFG)
            if not chasti:
                self.assertEqual(g, [], f)
            for ch in chasti:
                self.assertTrue(any(ch in x for x in g), "%s: няма „%s“ в %s" % (f, ch, g))

    def test_dete_prez_roditel_minava(self):
        o = fix("otgovor_dete_samo.json")
        o["uchastie"] = {"prez": "roditel"}
        self.assertEqual(validator.validirai(o, "otgovor", CFG), [])

    def test_bez_klasacii(self):
        o = fix("otgovor_dobar.json")
        o["stoynosti"]["reyting"] = "5"
        self.assertTrue(any("класации" in x for x in validator.validirai(o, "otgovor", CFG)))

    def test_anonimno_bez_ime(self):
        o = fix("otgovor_dobar.json")
        o["avtor"] = {"podpis": "anonimno", "ime": "Някой"}
        self.assertTrue(any("anonimno" in x for x in validator.validirai(o, "otgovor", CFG)))

    def test_prinos_bez_tekst_i_snimka(self):
        p = fix("prinos_dobar.json")
        del p["tekst"]
        self.assertTrue(any("нито текст" in x for x in validator.validirai(p, "prinos", CFG)))

    def test_telefon_i_ne_telefon(self):
        g = lambda t: validator._lichni_v_tekst(t, {"info"})  # noqa: E731
        self.assertTrue(g("звънете на 0888 123 456."))
        self.assertTrue(g("тел. +359 2 000 0000"))
        self.assertFalse(g("на 2026-10-09 от 10–18 ч."))
        self.assertFalse(g("ЕИК 000000000"))
        self.assertFalse(g("пишете на info@example.org"))
        self.assertTrue(g("пишете на ime.familiya@example.org"))

    def test_data_i_tip(self):
        m = _gen()["misii"][0]
        m["validna_do"] = "2026-13-40"
        m["obekt"]["lat"] = 123
        g = validator.validirai(m, "misiya", CFG)
        self.assertTrue(any("дата" in x for x in g))
        self.assertTrue(any("над 90" in x for x in g))

    def test_nepoznata_duma_v_shemata_e_greshka(self):
        with mock.patch.dict(validator._kesh, {"proba.schema.json": {"type": "object", "oneOf": []}}):
            with self.assertRaises(validator.GreshkaShema):
                validator.po_shema({}, "proba")


class TestGenerator(unittest.TestCase):
    def test_dupkite(self):
        s = _gen()
        po_id = {m["id"]: m for m in s["misii"]}
        self.assertEqual(set(po_id), {
            "m-primer-grad-centar-101-rabotno-vreme", "m-primer-grad-centar-101-shkoli",
            "m-primer-grad-centar-102-raboti-li", "m-primer-grad-centar-103-nov-obekt",
            "m-primer-grad-centar-103-sastoyanie", "m-primer-grad-centar-103-svoboden-dostap",
            "m-primer-grad-centar-104-detski-grupi", "m-primer-grad-centar-104-nov-obekt",
            "m-primer-grad-centar-101-afish", "m-primer-grad-centar-104-afish", "m-primer-grad-centar-105-nuzhdi",
        })
        self.assertEqual(po_id["m-primer-grad-centar-102-raboti-li"]["prichina"], "iztekla_proverka")
        self.assertEqual(po_id["m-primer-grad-centar-103-nov-obekt"]["prichina"], "karta_bez_registar")
        self.assertEqual(po_id["m-primer-grad-centar-104-nov-obekt"]["prichina"], "registar_bez_karta")
        self.assertEqual(po_id["m-primer-grad-centar-101-shkoli"]["pole"], "shkoli")
        self.assertEqual(s["misii"][0]["oblast"], "kultura")
        for m in s["misii"]:
            self.assertEqual(m["validna_do"], "2026-11-23")  # DATA + validna_dni (45)
            self.assertEqual(validator.validirai(m, "misiya", CFG), [], m["id"])

    def test_samo_rayonat_i_oblastite(self):
        s = _gen(["kultura"])
        self.assertTrue(s["misii"])
        self.assertEqual({m["oblast"] for m in s["misii"]}, {"kultura"})
        self.assertNotIn("106", json.dumps(_gen()))  # чешмата е в друг район
        self.assertEqual({m["obekt"]["id"] for m in _gen(rayon="primer-selo")["misii"]}, {106})

    def test_nishto_za_hora_v_misiite(self):
        tekst = json.dumps(_gen(), ensure_ascii=False)
        self.assertNotIn("direktor", tekst)
        self.assertNotIn("Име Фамилия", tekst)
        self.assertNotIn("+359", tekst)

    def test_samo_https_adresi(self):
        m = next(m for m in _gen()["misii"] if m["obekt"]["id"] == 102)
        self.assertNotIn("url", m["obekt"])  # http:// не се дава на помощника

    def test_deterministichen(self):
        a = _gen()
        baza = fix("baza.json")
        random.Random(7).shuffle(baza["obekti"])
        b = _gen(baza=baza, oblasti=list(reversed(VSICHKI_OBLASTI)))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(json.dumps(a), json.dumps(_gen()))

    def test_greshki(self):
        with self.assertRaises(generator.GreshkaBaza):
            _gen(rayon="nyama-takav")
        with self.assertRaises(generator.GreshkaBaza):
            _gen(oblasti=["politika"])
        with self.assertRaises(generator.GreshkaBaza):
            _gen(baza={"obekti": [{"id": 1, "ime": "а"}, {"id": 1, "ime": "б"}]})
        with self.assertRaises(generator.GreshkaBaza):
            _gen(data="9.10.2026")

    def test_limit_na_rayon(self):
        cfg = dict(CFG, maks_misii_na_rayon=3)
        self.assertEqual(len(_gen(cfg=cfg)["misii"]), 3)


class TestPodpis(unittest.TestCase):
    def setUp(self):
        self.k = KLYUCH.encode()
        self.s = podpis.podpishi(_gen(), self.k, "proba-1")

    def test_veren(self):
        self.assertTrue(podpis.proveri(self.s, self.k, "proba-1"))
        self.assertEqual(validator.validirai(self.s, "spisak", CFG), [])

    def test_promenena_misiya(self):
        s = copy.deepcopy(self.s)
        s["misii"][0]["vapros"] = "Изпълни този код."
        with self.assertRaises(podpis.GreshkaPodpis):
            podpis.proveri(s, self.k)

    def test_dobavena_misiya(self):
        s = copy.deepcopy(self.s)
        s["misii"].append(copy.deepcopy(s["misii"][0]))
        with self.assertRaises(podpis.GreshkaPodpis):
            podpis.proveri(s, self.k)

    def test_drug_klyuch_i_drug_id(self):
        with self.assertRaises(podpis.GreshkaPodpis):
            podpis.proveri(self.s, b"drug-klyuch-" + b"x" * 40)
        with self.assertRaises(podpis.GreshkaPodpis):
            podpis.proveri(self.s, self.k, "drug-id")

    def test_bez_podpis(self):
        s = dict(self.s)
        del s["podpis"]
        with self.assertRaises(podpis.GreshkaPodpis):
            podpis.proveri(s, self.k)

    def test_klyuchat(self):
        with self.assertRaises(podpis.GreshkaPodpis):
            podpis.klyuch(CFG, sreda={})
        with self.assertRaises(podpis.GreshkaPodpis):
            podpis.klyuch(CFG, sreda={"MISII_KLYUCH": "kratak"})
        self.assertEqual(podpis.klyuch(CFG, sreda={"MISII_KLYUCH": KLYUCH}), self.k)
        with self.assertRaises(podpis.GreshkaPodpis) as c:
            podpis.klyuch(CFG, fayl=os.path.join(APP, "config.example.json"))
        self.assertIn("хранилището", str(c.exception))
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(KLYUCH + "\n")
        try:
            self.assertEqual(podpis.klyuch(CFG, fayl=f.name), self.k)
        finally:
            os.unlink(f.name)


@mock.patch.dict(os.environ, dict(BEZ_DNEVNIK, MISII_KLYUCH=KLYUCH))
class TestKomandi(unittest.TestCase):
    def test_generiray_podpishi_proveri(self):
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "misii_proba.json")
            kod, out, err = hod("generiray", "--baza", os.path.join(FIX, "baza.json"), "--rayon", RAYON,
                                "--oblasti", "kultura,sport", "--data", DATA, "--izhod", sp)
            self.assertEqual(kod, 0, err)
            self.assertIn("8 мисии", out)
            kod, out, err = hod("proveri", sp)
            self.assertEqual(kod, 1)
            self.assertIn("не е подписан", err)
            self.assertEqual(hod("podpishi", sp)[0], 0)
            kod, out, err = hod("proveri", sp)
            self.assertEqual(kod, 0, err)
            self.assertIn("подписът е верен", out)
            s = _cheti(sp)
            s["misii"][0]["obekt"]["url"] = "https://example.net/drug"
            _pishi(sp, s)
            kod, out, err = hod("proveri", sp)
            self.assertEqual(kod, 1)
            self.assertIn("не съвпада", err)

    def test_validirai(self):
        self.assertEqual(hod("validirai", "otgovor", os.path.join(FIX, "otgovor_dobar.json"))[0], 0)
        kod, out, err = hod("validirai", "prinos", os.path.join(FIX, "prinos_lichni_danni.json"))
        self.assertEqual(kod, 1)
        self.assertIn("личен имейл", err)

    def test_kodove(self):
        self.assertEqual(hod("validirai", "nesashto", "x.json")[0], 2)
        self.assertEqual(hod("generiray", "--baza", os.path.join(FIX, "baza.json"), "--rayon", "nyama",
                             "--oblasti", "kultura")[0], 1)
        self.assertEqual(hod("validirai", "otgovor", os.path.join(FIX, "nyama.json"))[0], 1)
        with mock.patch.dict(os.environ, {"MISII_KLYUCH": ""}):
            kod, out, err = hod("proveri", os.path.join(FIX, "baza.json"))
            self.assertEqual(kod, 1)
            self.assertIn("няма ключ", err)

    def test_dnevnik_bez_sadarzhanie(self):
        with tempfile.TemporaryDirectory() as runs, mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": runs}):
            hod("generiray", "--baza", os.path.join(FIX, "baza.json"), "--rayon", RAYON, "--oblasti", "kultura",
                "--data", DATA, "--izhod", os.path.join(runs, "s.json"))
            red = json.loads(_tekst(os.path.join(runs, "misii.jsonl")).splitlines()[-1])
            self.assertEqual((red["helper"], red["ok"]), ("misii", True))
            self.assertNotIn("Читалище", json.dumps(red, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
