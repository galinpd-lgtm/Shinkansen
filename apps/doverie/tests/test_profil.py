"""Z7b: профил на доверие, 10-те въпроса за пълнота, увереност (всяка граница), „гледал човек“ и `proveri`."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from obshto import FalshivModel, cfg, primer

from doverie import cli, osi
from doverie.ocenka import CHOVEK, ocenka, uverenost


def dalag(n_dumi):
    """Текст с точно n_dumi думи, с твърдения с източник (за границите на увереността)."""
    izr = "Според Мария Примерова общината похарчи 12 лева за всеки ученик през 2026 година."  # 13 думи
    d = []
    while len(d) + 13 <= n_dumi:
        d += izr.split()
    d += ["дума"] * (n_dumi - len(d))
    return " ".join(d)


class TestProfilBezModel(unittest.TestCase):
    """Готово е, когато: 1. --bez-model дава профил с „ниска“ увереност и причините, ос 7 от 8 въпроса с бележка."""

    def setUp(self):
        self.rez = ocenka(primer(1), cfg())
        self.p = self.rez["profil"]

    def test_profilat_e_parvi_obshtata_posledna(self):
        self.assertEqual(list(self.rez)[0], "profil")
        self.assertEqual(list(self.p), ["osi", "uverenost", "pokritie_s_dokazatelstva", "chovek", "obshta_ocenka",
                                        "po_dumi"])
        self.assertEqual(self.p["obshta_ocenka"], self.rez["krayna_ocenka"])  # старото остава
        self.assertEqual(self.p["po_dumi"], self.rez["po_dumi"])

    def test_sedem_osi(self):
        self.assertEqual(list(self.p["osi"]), ["1", "2", "3", "4", "5", "6", "7"])
        for o in self.p["osi"].values():
            self.assertEqual(o["izmereno_s"], "правила")
            self.assertIn("ocenka", o)
            self.assertIn("zashto", o)

    def test_niska_s_prichini(self):
        u = self.p["uverenost"]
        self.assertEqual(u["nivo"], "ниска")
        self.assertIn("без модел — само правила и евристики", u["prichini"])
        self.assertTrue(any("въпросите за пълнота" in p for p in u["prichini"]))

    def test_os7_ot_8_vaprosa(self):
        o7 = self.p["osi"]["7"]
        self.assertEqual(len(o7["vaprosi"]), 10)
        neopr = [v for v in o7["vaprosi"] if v["otgovor"] == osi.NEOPREDELIMO]
        self.assertEqual({v["kluch"] for v in neopr}, {"drugata_strana", "znachenie"})  # не се гадаят
        tochki = sum(osi.TOCHKI[v["otgovor"]] for v in o7["vaprosi"] if v["otgovor"] in osi.TOCHKI)
        self.assertEqual(o7["ocenka"], osi.okragli(tochki * 10 / 8))
        self.assertIn("не може да се определи без модел", o7["zashto"])
        self.assertTrue(any("мащабирана до 10" in b for b in self.rez["belezhki"]))

    def test_grubo_pokritie(self):
        pk = self.p["pokritie_s_dokazatelstva"]
        self.assertTrue(pk["grubo"])
        self.assertEqual(pk["dyal"], round(pk["s_iztochnik"] / pk["tvardenia"], 2))

    def test_chovek_vinagi_ne(self):
        self.assertEqual(self.p["chovek"], "не")
        self.assertEqual(ocenka(primer(2), cfg(), model=FalshivModel())["profil"]["chovek"], "не")

    def test_deterministichno(self):
        self.assertEqual(json.dumps(self.rez, sort_keys=True), json.dumps(ocenka(primer(1), cfg()), sort_keys=True))


class TestVaprosi(unittest.TestCase):
    """Готово е, когато: 2. с фалшив модел — 10 въпроса."""

    def test_deset_s_model(self):
        m = FalshivModel(vaprosi={"kak": "частично", "drugata_strana": "не", "znachenie": "частично"})
        rez = ocenka(primer(2), cfg(), model=m)
        o7 = rez["profil"]["osi"]["7"]
        self.assertEqual(o7["izmereno_s"], "модел")
        self.assertEqual([v["otgovor"] for v in o7["vaprosi"]].count(osi.NEOPREDELIMO), 0)
        self.assertEqual(o7["ocenka"], 8.0)  # 7 × 1 + 2 × 0.5 + 0 = 8
        self.assertFalse(any("мащабирана" in b for b in rez["belezhki"]))

    def test_spisakat_e_v_config(self):
        c = cfg()
        c["palnota_vaprosi"] = c["palnota_vaprosi"][:4]
        rez = ocenka(primer(2), c, model=FalshivModel())
        self.assertEqual(len(rez["profil"]["osi"]["7"]["vaprosi"]), 4)
        self.assertEqual(rez["profil"]["osi"]["7"]["ocenka"], 10.0)

    def test_nepoznat_vapros_bez_model_ne_se_gadae(self):
        c = cfg()
        c["palnota_vaprosi"].append({"kluch": "nov", "vapros": "Има ли снимка?"})
        otg = osi.palnota_vaprosi(primer(2), c)
        self.assertEqual(otg[-1]["otgovor"], osi.NEOPREDELIMO)

    def test_lipsvasht_otgovor_vrashta_pravilata(self):
        rez = ocenka(primer(2), cfg(), model=FalshivModel(surovo={"palnota": '{"otgovori": {"koy": "да"}}'}))
        o7 = rez["profil"]["osi"]["7"]
        self.assertEqual(o7["izmereno_s"], "правила")
        self.assertTrue(any(v["otgovor"] == osi.NEOPREDELIMO for v in o7["vaprosi"]))

    def test_otgovori_na_angliyski_i_chisla(self):
        m = FalshivModel(vaprosi={"koy": "yes", "kakvo": "0.5", "koga": "no"})
        o7 = ocenka(primer(2), cfg(), model=m)["profil"]["osi"]["7"]
        self.assertEqual([v["otgovor"] for v in o7["vaprosi"][:3]], ["да", "частично", "не"])


class TestUverenostGranici(unittest.TestCase):
    """Всяка граница от т. 3 поотделно, през самата функция."""

    def u(self, s_model=True, dumi=400, tv=10, s_izt=8, razliki=(), neopr=0):
        pk = {"tvardenia": tv, "s_iztochnik": s_izt, "dyal": round(s_izt / tv, 2) if tv else None}
        return uverenost(s_model, dumi, pk, list(razliki), neopr, cfg())

    def test_visoka(self):
        r = self.u()
        self.assertEqual(r["nivo"], "висока")
        self.assertTrue(r["prichini"])

    def test_bez_model_niska(self):
        self.assertEqual(self.u(s_model=False)["nivo"], "ниска")

    def test_dumi_150(self):
        self.assertEqual(self.u(dumi=149)["nivo"], "ниска")
        self.assertNotEqual(self.u(dumi=150)["nivo"], "ниска")

    def test_dumi_300(self):
        self.assertEqual(self.u(dumi=299)["nivo"], "средна")
        self.assertEqual(self.u(dumi=300)["nivo"], "висока")

    def test_tvardeniya_3(self):
        self.assertEqual(self.u(tv=2, s_izt=2)["nivo"], "ниска")
        self.assertEqual(self.u(tv=3, s_izt=2)["nivo"], "висока")  # 67% ≥ 60%

    def test_pokritie_60(self):
        self.assertEqual(self.u(tv=100, s_izt=59)["nivo"], "средна")
        self.assertEqual(self.u(tv=100, s_izt=60)["nivo"], "висока")
        self.assertIn("покритие", " ".join(self.u(tv=100, s_izt=59)["prichini"]))

    def test_razlika_2_i_1(self):
        self.assertEqual(self.u(razliki=[("Ос", 2.1)])["nivo"], "ниска")
        self.assertEqual(self.u(razliki=[("Ос", 2.0)])["nivo"], "средна")  # не е > 2, но е > 1
        self.assertEqual(self.u(razliki=[("Ос", 1.1)])["nivo"], "средна")
        self.assertEqual(self.u(razliki=[("Ос", 1.0)])["nivo"], "висока")

    def test_vsyaka_prichina_se_izpisva(self):
        r = self.u(s_model=False, dumi=100, tv=1, s_izt=0, razliki=[("Проверимост", 3.0)], neopr=2)
        self.assertEqual(len(r["prichini"]), 5)

    def test_pragovete_sa_v_config(self):
        c = cfg()
        c["uverenost"]["niska_pod_dumi"] = 500
        pk = {"tvardenia": 10, "s_iztochnik": 8, "dyal": 0.8}
        self.assertEqual(uverenost(True, 400, pk, [], 0, c)["nivo"], "ниска")


class TestUverenostPalenPat(unittest.TestCase):
    def test_visoka_s_model(self):
        t = dalag(320)
        pravila = {k: (osi.EVRISTIKI[k](t, cfg())[0], "Като правилата.") for k in osi.S_MODEL if k != "palnota"}
        oc7 = osi.palnota(t, cfg())[0]
        # моделът е съгласен с правилата: пълнотата — чрез отговори, които дават същата оценка ± 1
        m = FalshivModel(tvardenia=(10, 7), osi=pravila,
                         vaprosi={"kak": "не", "zashto": "не", "drugata_strana": "частично"})
        rez = ocenka(t, cfg(), model=m)
        pk = rez["profil"]["pokritie_s_dokazatelstva"]
        self.assertFalse(pk["grubo"])
        self.assertEqual((pk["tvardenia"], pk["s_iztochnik"], pk["dyal"]), (10, 7, 0.7))
        self.assertLessEqual(abs(rez["profil"]["osi"]["7"]["ocenka"] - oc7), 1.0)
        self.assertEqual(rez["profil"]["uverenost"]["nivo"], "висока", rez["profil"]["uverenost"])

    def test_razminavane_pravila_model(self):
        # правилата дават 10 за проверимостта на този текст; моделът казва 2 → разлика 8 → ниска
        m = FalshivModel(tvardenia=(10, 7), osi={"proverimost": (2.0, "Малко източници.")})
        rez = ocenka(dalag(320), cfg(), model=m)
        o2 = rez["profil"]["osi"]["2"]
        self.assertEqual(o2["izmereno_s"], "модел")
        self.assertGreater(o2["razlika"], 2)
        self.assertEqual(rez["profil"]["uverenost"]["nivo"], "ниска")
        self.assertTrue(any("разминават" in p for p in rez["profil"]["uverenost"]["prichini"]))

    def test_kratak_tekst_s_model_niska(self):
        rez = ocenka(dalag(140), cfg(), model=FalshivModel(tvardenia=(10, 8)))
        self.assertEqual(rez["profil"]["uverenost"]["nivo"], "ниска")

    def test_model_bez_broy_tvardeniya_grubo(self):
        rez = ocenka(dalag(320), cfg(), model=FalshivModel())
        self.assertTrue(rez["profil"]["pokritie_s_dokazatelstva"]["grubo"])


def pusni(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        kod = cli.main(list(argv))
    return kod, out.getvalue(), err.getvalue()


class TestProveri(unittest.TestCase):
    def test_zapazi_i_proveri(self):
        with tempfile.TemporaryDirectory() as d:
            prim = os.path.join(os.path.dirname(os.path.abspath(__file__)), "primer_1.txt")
            kod, out, err = pusni("ocenka", "--tekst", prim, "--bez-model", "--zapazi", "--arhiv", d)
            self.assertEqual(kod, 0)
            rid = json.loads(out)["id"]
            self.assertTrue(os.path.exists(os.path.join(d, rid + ".json")))
            kod, out, _ = pusni("proveri", "--id", rid, "--ot", "методист", "--arhiv", d)
            self.assertEqual(kod, 0)
            with open(os.path.join(d, rid + ".json"), encoding="utf-8") as f:
                p = json.load(f)["profil"]
            self.assertEqual(p["chovek"], "проверено от човек")
            self.assertEqual(p["pregled"]["rolya"], "методист")
            self.assertEqual(set(p["pregled"]), {"rolya", "data"})  # без имена

    def test_samo_roli_ne_imena(self):
        with tempfile.TemporaryDirectory() as d:
            kod, _, err = pusni("proveri", "--id", "0123456789abcdef", "--ot", "Петър Примеров", "--arhiv", d)
            self.assertEqual(kod, 2)
            self.assertIn("ролята, не името", err)

    def test_nyama_takava_ocenka(self):
        with tempfile.TemporaryDirectory() as d:
            kod, _, _ = pusni("proveri", "--id", "0123456789abcdef", "--ot", "редактор", "--arhiv", d)
            self.assertEqual(kod, 1)

    def test_losh_id(self):
        with tempfile.TemporaryDirectory() as d:
            kod, _, _ = pusni("proveri", "--id", "../../etc/passwd", "--ot", "редактор", "--arhiv", d)
            self.assertEqual(kod, 2)

    def test_stoynosti(self):
        self.assertEqual(CHOVEK, ("не", "одобрено в сводка", "проверено от човек"))


if __name__ == "__main__":
    unittest.main()
