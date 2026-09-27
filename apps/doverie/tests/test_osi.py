"""Осите, теглата от конфигурацията, детерминизмът без модел и решението."""
import json
import os
import tempfile
import unittest

from obshto import APP, cfg, primer

from doverie import osi
from doverie.config import GreshkaConfig, proveri, zaredi
from doverie.ocenka import ocenka, otchet
from doverie.reshenie import reshi


class TestOsi(unittest.TestCase):
    def test_sedem_osi_i_tegla(self):
        rez = ocenka(primer(1), cfg())
        self.assertEqual([o["kluch"] for o in rez["osi"]], list(cfg()["tegla"]))
        self.assertAlmostEqual(sum(o["teglo"] for o in rez["osi"]), 1.0)
        for o in rez["osi"]:
            self.assertTrue(0.0 <= o["ocenka"] <= 10.0)
            self.assertTrue(o["zashto"])

    def test_deterministichno(self):
        a = json.dumps(ocenka(primer(1), cfg()), sort_keys=True, ensure_ascii=False)
        b = json.dumps(ocenka(primer(1), cfg()), sort_keys=True, ensure_ascii=False)
        self.assertEqual(a, b)

    def test_krayna_e_pretheglena_suma(self):
        rez = ocenka(primer(2), cfg())
        suma = sum(o["teglo"] * o["ocenka"] for o in rez["osi"])
        self.assertAlmostEqual(rez["krayna_ocenka"], suma, delta=0.05 + 1e-9)

    def test_granica_na_zakraglyaneto(self):
        c = cfg()
        c["tegla"] = {k: 0.0 for k in c["tegla"]}
        c["tegla"].update(reputaciya=0.5, palnota=0.5)
        osi_ = [{"kluch": "reputaciya", "ocenka": 8.1}, {"kluch": "palnota", "ocenka": 8.8}]
        self.assertEqual(osi.krayna(osi_, c), 8.5)  # 8.45 → 8.5, не 8.4

    def test_teglata_idvat_ot_config(self):
        c = cfg()
        c["tegla"] = {k: 0.0 for k in c["tegla"]}
        c["tegla"]["reputaciya"] = 1.0
        rez = ocenka(primer(1), c, iztochnik="example.org")
        self.assertEqual(rez["krayna_ocenka"], 7.5)

    def test_po_dumi(self):
        c = cfg()
        for oc, d in ((9.0, "Много добра"), (8.5, "Много добра"), (7.0, "Добра"), (6.9, "Средна"),
                      (5.0, "Средна"), (3.0, "Ниска"), (2.9, "Много ниска"), (0.0, "Много ниска")):
            self.assertEqual(osi.po_dumi(oc, c), d, oc)

    def test_okragli_polovinka_nagore(self):
        self.assertEqual(osi.okragli(6.25), 6.3)
        self.assertEqual(osi.okragli(6.35), 6.4)

    def test_reputaciya_ot_registara(self):
        c = cfg()
        self.assertEqual(osi.reputaciya("https://www.example.org/statiya/1", c)[0], 7.5)
        self.assertEqual(osi.reputaciya("novini.example.net", c)[0], 4.0)
        self.assertEqual(osi.reputaciya("example.com", c)[0], c["rep_neizvesten"])
        self.assertEqual(osi.reputaciya(None, c)[0], c["rep_neizvesten"])

    def test_avtor_ne_se_ocenyava(self):
        a = ocenka(primer(1), cfg(), iztochnik="example.org")
        b = ocenka(primer(1), cfg(), iztochnik="example.org", avtor="Петър Примеров")
        self.assertEqual(b["iztochnik"]["avtor"], "Петър Примеров")
        self.assertFalse(b["iztochnik"]["avtor_se_ocenyava"])
        self.assertEqual(a["osi"], b["osi"])
        self.assertEqual(a["krayna_ocenka"], b["krayna_ocenka"])

    def test_originalnost_kopie(self):
        c = cfg()
        sh = osi.shingli(primer(1))
        oc, za, _ = osi.originalnost(primer(1), c, vidyani=[sh])
        self.assertEqual(oc, 1.0)
        oc2, _, _ = osi.originalnost(primer(2), c, vidyani=[sh])
        self.assertGreater(oc2, 9.0)

    def test_pamet_zapomnya(self):
        with tempfile.TemporaryDirectory() as d:
            c = cfg()
            c["pamet"] = os.path.join(d, "pamet.jsonl")
            self.assertEqual(ocenka(primer(2), c, zapomni=True)["osi"][3]["ocenka"], 10.0)
            self.assertEqual(ocenka(primer(2), c)["osi"][3]["ocenka"], 1.0)

    def test_palnota(self):
        self.assertEqual(osi.palnota(primer(2))[0], 10.0)
        oc, za = osi.palnota("Нещо стана.")
        self.assertLess(oc, 5.0)
        self.assertIn("Липсва", za)

    def test_reklama_nisak_interes(self):
        self.assertLess(osi.obshtestven_interes("Купете сега! Само днес отстъпка 50% и безплатна доставка.")[0], 3.0)

    def test_bez_iztochnici_proverimost(self):
        oc, za = osi.proverimost("Цените скочиха с 30%. Заплатите паднаха с 10%.")
        self.assertEqual(oc, 0.0)
        self.assertIn("Липсва посочен източник", za)

    def test_otchet(self):
        t = otchet(ocenka(primer(1), cfg()))
        self.assertIn("Достоверност:", t)
        self.assertIn("Анонимен авторитет", t)


class TestConfig(unittest.TestCase):
    def test_primer_e_validen(self):
        zaredi(os.path.join(APP, "config.example.json"))

    def test_suma_na_teglata(self):
        c = cfg()
        c["tegla"]["palnota"] = 0.5
        self.assertTrue(any("сума" in g for g in proveri(c)))

    def test_produkcionniyat_port_e_zabranen(self):
        c = cfg()
        c["ollama_url"] = "http://127.0.0.1:11434"
        self.assertTrue(proveri(c))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(c, f)
        try:
            with self.assertRaises(GreshkaConfig):
                zaredi(f.name)
        finally:
            os.unlink(f.name)

    def test_primer_bez_model_11435(self):
        self.assertIn(":11435", cfg()["ollama_url"])


class TestReshenie(unittest.TestCase):
    def osi_(self, prozr=8.0):
        return [{"kluch": "prozrachnost", "ocenka": prozr}]

    def p(self, k, **kw):
        return dict({"kluch": k}, **kw)

    def test_propusni(self):
        self.assertEqual(reshi(7.0, [], self.osi_(), cfg())["kod"], "PROPUSNI")

    def test_visoka_s_flag_preduprezhdava(self):
        self.assertEqual(reshi(8.0, [self.p("bandwagon")], self.osi_(), cfg())["kod"], "PREDUPREDI")

    def test_sredna(self):
        self.assertEqual(reshi(4.0, [], self.osi_(), cfg())["kod"], "PREDUPREDI")
        self.assertEqual(reshi(6.9, [], self.osi_(), cfg())["kod"], "PREDUPREDI")

    def test_karantina_nisko(self):
        self.assertEqual(reshi(3.9, [], self.osi_(), cfg())["kod"], "KARANTINA")

    def test_karantina_ai(self):
        self.assertEqual(reshi(8.0, [self.p("ai_generated", veroyatnost=0.85)], self.osi_(), cfg())["kod"], "KARANTINA")
        self.assertEqual(reshi(8.0, [self.p("ai_generated", veroyatnost=0.6)], self.osi_(), cfg())["kod"], "PREDUPREDI")

    def test_kritichen_flag(self):
        self.assertEqual(reshi(8.0, [self.p("anonymous_authority")], self.osi_(1.0), cfg())["kod"], "KARANTINA")
        self.assertEqual(reshi(8.0, [self.p("anonymous_authority")], self.osi_(7.0), cfg())["kod"], "PREDUPREDI")

    def test_primeri(self):
        self.assertEqual(ocenka(primer(2), cfg())["reshenie"]["kod"], "PROPUSNI")
        self.assertEqual(ocenka(primer(1), cfg())["reshenie"]["kod"], "PREDUPREDI")
        self.assertEqual(ocenka(primer(3), cfg())["reshenie"]["kod"], "KARANTINA")
        rez = ocenka("Специалисти твърдят, че водата е опасна. Всички знаят това.", cfg())
        self.assertEqual(rez["reshenie"]["kod"], "KARANTINA")


if __name__ == "__main__":
    unittest.main()
