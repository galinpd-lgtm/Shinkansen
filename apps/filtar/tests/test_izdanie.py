"""Слой 7, черновата, одобрението и изданието — и правилото за авторското право."""
import json
import os
import unittest
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from obshto import IZVORI, SEGA, FalshivaMrezha, FalshivModel, Otvorena, Papka, cfg, dcfg

from filtar import config, sabirach, sloeve
from filtar import izdanie as izd
from filtar.dov import VrataNeBezopasno, izrecheniya

DEN = date(2026, 10, 5)


def podgotvi(p):
    sabirach.sabiray(p.b, cfg(), IZVORI, SEGA, get=FalshivaMrezha(), vhod=p.vhod)
    sloeve.filtriray(p.b, cfg(), dcfg(), SEGA, organizacii=config.cheti_json("organizacii.example.json"))


class TestChernova(unittest.TestCase):
    def test_gotovo_1(self):
        """Готово е, когато: 1. 3 емисии → ≤10 записа и причина в дневника за всеки отпаднал."""
        with Papka() as p:
            podgotvi(p)
            d, pj = izd.chernova(p.b, cfg(), DEN, p.danni, SEGA)
            self.assertTrue(os.path.exists(pj))
            self.assertTrue(os.path.exists(pj.replace(".json", ".md")))
            self.assertGreater(len(d["zapisi"]), 0)
            self.assertLessEqual(len(d["zapisi"]), 10)
            izbrani = {z["id"] for z in d["zapisi"]}
            for z in p.b.execute("SELECT id FROM zapisi"):
                if z["id"] in izbrani:
                    continue
                red = p.b.execute("SELECT prichina FROM firewall_log WHERE zapis_id=? AND sloy>0 AND reshenie NOT IN "
                                  "('ПРОПУСНИ', 'ПРЕДУПРЕДИ')", (z["id"],)).fetchone()
                if red is None:  # премина слоевете 1–6, но не е подбран → ред на слой 7
                    red = p.b.execute("SELECT prichina FROM firewall_log WHERE zapis_id=? AND sloy=7",
                                      (z["id"],)).fetchone()
                self.assertIsNotNone(red, "запис %d няма причина" % z["id"])

    def test_pravila_na_podbora(self):
        with Papka() as p:
            podgotvi(p)
            d, _ = izd.chernova(p.b, cfg(), DEN, p.danni, SEGA)
            ic = cfg()["izdanie"]
            po_rub, po_izv = {}, {}
            for z in d["zapisi"]:
                self.assertIn(z["reshenie"], ("ПРОПУСНИ", "ПРЕДУПРЕДИ"))
                self.assertTrue(z["izvor"]["ime"] and z["data"] and z["rubrika"]["nomer"])
                po_rub[z["rubrika"]["nomer"]] = po_rub.get(z["rubrika"]["nomer"], 0) + 1
                po_izv[z["izvor"]["ime"]] = po_izv.get(z["izvor"]["ime"], 0) + 1
            self.assertLessEqual(max(po_rub.values()), ic["maks_na_rubrika"])
            self.assertLessEqual(max(po_izv.values()), ic["maks_na_izvor"])
            # без дата не се публикува
            bez = p.b.execute("SELECT id FROM zapisi WHERE data IS NULL AND reshenie IN ('ПРОПУСНИ','ПРЕДУПРЕДИ')").fetchone()
            self.assertNotIn(bez["id"], {z["id"] for z in d["zapisi"]})
            red = p.b.execute("SELECT prichina FROM firewall_log WHERE zapis_id=? AND sloy=7", (bez["id"],)).fetchone()
            self.assertIn("липсва дата", red["prichina"])

    def test_limit_10(self):
        c = cfg()
        c["izdanie"].update(maks_na_rubrika=99, maks_na_izvor=99)
        with Papka() as p:
            podgotvi(p)
            d, _ = izd.chernova(p.b, c, DEN, p.danni, SEGA)
            self.assertEqual(len(d["zapisi"]), 10)
            self.assertTrue(p.b.execute("SELECT 1 FROM firewall_log WHERE sloy=7 AND prichina LIKE 'дневният лимит%'")
                            .fetchone())

    def test_bez_model_prazni_tekstove(self):
        with Papka() as p:
            podgotvi(p)
            d, pj = izd.chernova(p.b, cfg(), DEN, p.danni, SEGA)
            self.assertFalse(d["s_model"])
            self.assertTrue(all(z["kakvo"] == "" and z["znachi"] == "" for z in d["zapisi"]))
            with open(pj.replace(".json", ".md"), encoding="utf-8") as f:
                self.assertIn("без модел", f.read())

    def test_s_model(self):
        with Papka() as p:
            podgotvi(p)
            m = FalshivModel()
            d, _ = izd.chernova(p.b, cfg(), DEN, p.danni, SEGA, model=m)
            self.assertTrue(all(z["kakvo"] and z["znachi"] for z in d["zapisi"]))
            self.assertEqual(len(m.vikaniya), len(d["zapisi"]))

    def test_vratata_spira_bez_fail(self):
        with Papka() as p:
            podgotvi(p)
            with self.assertRaises(VrataNeBezopasno):
                izd.chernova(p.b, cfg(), DEN, p.danni, SEGA, model=FalshivModel(vrata=Otvorena(["ok", "busy"])))
            self.assertFalse(os.path.exists(os.path.join(p.danni, "chernova_2026-10-05.json")))

    def test_citat_e_kratak(self):
        with Papka() as p:
            podgotvi(p)
            d, _ = izd.chernova(p.b, cfg(), DEN, p.danni, SEGA)
            for z in d["zapisi"]:
                self.assertTrue(z["citat"])
                self.assertLessEqual(len(z["citat"]), izd.MAKS_CITAT_ZNACI + 1)
                self.assertNotIn("tekst", z)


class TestOdobri(unittest.TestCase):
    def test_bez_go_nishto(self):
        with Papka() as p:
            podgotvi(p)
            izd.chernova(p.b, cfg(), DEN, p.danni, SEGA)
            predi = sorted(os.listdir(p.danni))
            ostavat, mahnati, izh = izd.odobri(p.b, p.danni, DEN, [2], False, SEGA)
            self.assertIsNone(izh)
            self.assertEqual(len(mahnati), 1)
            self.assertEqual(sorted(os.listdir(p.danni)), predi)
            self.assertEqual(p.b.execute("SELECT COUNT(*) FROM zapisi WHERE odobren IS NOT NULL").fetchone()[0], 0)

    def test_s_go(self):
        with Papka() as p:
            podgotvi(p)
            d, _ = izd.chernova(p.b, cfg(), DEN, p.danni, SEGA)
            ostavat, mahnati, izh = izd.odobri(p.b, p.danni, DEN, [1, 3], True, SEGA)
            self.assertTrue(os.path.exists(izh))
            with open(izh, encoding="utf-8") as f:
                o = json.load(f)
            self.assertEqual([z["nomer"] for z in o["zapisi"]], [z["nomer"] for z in d["zapisi"] if z["nomer"] not in (1, 3)])
            self.assertEqual(p.b.execute("SELECT COUNT(*) FROM firewall_log WHERE reshenie='МАХНАТ'").fetchone()[0], 2)
            # одобреното не влиза в следваща чернова
            d2, _ = izd.chernova(p.b, cfg(), DEN, p.danni, SEGA)
            self.assertFalse({z["id"] for z in o["zapisi"]} & {z["id"] for z in d2["zapisi"]})

    def test_nepoznat_nomer(self):
        with Papka() as p:
            podgotvi(p)
            izd.chernova(p.b, cfg(), DEN, p.danni, SEGA)
            with self.assertRaises(izd.GreshkaIzdanie):
                izd.odobri(p.b, p.danni, DEN, [99], True, SEGA)

    def test_nyama_chernova(self):
        with Papka() as p:
            with self.assertRaises(izd.GreshkaIzdanie):
                izd.odobri(p.b, p.danni, DEN, [], True, SEGA)


class TestIzdanie(unittest.TestCase):
    def napravi(self, p, izhod, dni=(DEN,)):
        podgotvi(p)
        for den in dni:
            izd.chernova(p.b, cfg(), den, p.danni, SEGA, model=FalshivModel())
            izd.odobri(p.b, p.danni, den, [], True, SEGA)
        return izd.izdanie(cfg(), p.danni, izhod, DEN)

    def test_rss_i_json(self):
        with Papka() as p:
            izhod = os.path.join(p.d, "izhod", "radar")
            o = self.napravi(p, izhod)
            self.assertGreater(o["zapisi"], 0)
            koren = ET.parse(os.path.join(izhod, "rss.xml")).getroot()
            self.assertEqual((koren.tag, koren.get("version")), ("rss", "2.0"))
            kanal = koren.find("channel")
            for el in ("title", "link", "description"):
                self.assertTrue(kanal.findtext(el))
            items = kanal.findall("item")
            self.assertEqual(len(items), o["zapisi"])
            for it in items:
                for el in ("title", "link", "guid", "pubDate", "description", "category"):
                    self.assertTrue(it.findtext(el), el)
            with open(os.path.join(izhod, "radar.json"), encoding="utf-8") as f:
                r = json.load(f)
            self.assertEqual(len(r["zapisi"]), o["zapisi"])
            self.assertTrue(os.path.exists(os.path.join(izhod, "po-den", "2026-10-05.json")))

    def test_nikoga_palen_tekst(self):
        with Papka() as p:
            izhod = os.path.join(p.d, "izhod")
            self.napravi(p, izhod)
            with open(os.path.join(izhod, "radar.json"), encoding="utf-8") as f:
                radar = json.load(f)["zapisi"]
            with open(os.path.join(izhod, "rss.xml"), encoding="utf-8") as f:
                rss = f.read()
            items = {it.findtext("link"): it.findtext("description") for it in ET.fromstring(rss).iter("item")}
            self.assertTrue(radar)
            for pub in radar:
                z = p.b.execute("SELECT tekst FROM zapisi WHERE url=?", (pub["url"],)).fetchone()
                vid = json.dumps(pub, ensure_ascii=False) + items[pub["url"]]
                self.assertNotIn(z["tekst"], vid)
                for s in izrecheniya(z["tekst"])[izd.MAKS_CITAT_IZRECHENIYA:]:
                    self.assertNotIn(s, pub["citat"] + items[pub["url"]])  # след цитата — нищо от текста
            with open(os.path.join(izhod, "radar.json"), encoding="utf-8") as f:
                for z in json.load(f)["zapisi"]:
                    self.assertEqual(set(z), {"data", "odobren", "zaglavie", "kakvo", "znachi", "citat", "rubrika",
                                              "izvor", "ocenka", "po_dumi", "url", "reshenie"})

    def test_30_dni(self):
        with Papka() as p:
            izhod = os.path.join(p.d, "izhod")
            podgotvi(p)
            izd.chernova(p.b, cfg(), DEN, p.danni, SEGA)
            izd.odobri(p.b, p.danni, DEN, [], True, SEGA)
            o = izd.izdanie(cfg(), p.danni, izhod, DEN + timedelta(days=29))
            self.assertEqual(o["dni"], 1)
            o = izd.izdanie(cfg(), p.danni, izhod, DEN + timedelta(days=30))
            self.assertEqual(o["dni"], 0)


if __name__ == "__main__":
    unittest.main()
