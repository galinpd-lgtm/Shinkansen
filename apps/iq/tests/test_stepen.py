"""Степените и границите им — чистата логика, без база."""
import unittest
from datetime import date, timedelta

from obshto import cfg

from iq import stepen as st


def ch(**k):
    c = {"zapisi": 40, "sredna": 8.0, "dyal_imenuvani": 1.0, "dyal_pohvati": 0.0, "dyal_uverenost": 1.0,
         "istoriya_dni": 400,
         "sedmici": [{}] * 4, "sedmici_s_publikacii": 4}
    c.update(k)
    return c


def kod(**k):
    return st.stepen(ch(**k), cfg())["kod"]


class TestGranici(unittest.TestCase):
    def test_srednata_ocenka(self):
        for sredna, ochakvano in ((10.0, "A+"), (9.0, "A+"), (8.9, "A"), (7.5, "A"), (7.4, "B"), (6.0, "B"),
                                  (5.9, "C"), (4.0, "C"), (3.9, "Без степен"), (0.0, "Без степен")):
            with self.subTest(sredna=sredna):
                self.assertEqual(kod(sredna=sredna), ochakvano)

    def test_a_plus_usloviya(self):
        self.assertEqual(kod(sredna=9.5, dyal_imenuvani=0.90), "A+")
        self.assertEqual(kod(sredna=9.5, dyal_imenuvani=0.89), "A")
        self.assertEqual(kod(sredna=9.5, dyal_pohvati=0.0199), "A+")
        self.assertEqual(kod(sredna=9.5, dyal_pohvati=0.02), "A")
        self.assertEqual(kod(sredna=9.5, istoriya_dni=365), "A+")
        self.assertEqual(kod(sredna=9.5, istoriya_dni=364), "A")

    def test_a_usloviya(self):
        self.assertEqual(kod(sredna=8.0, dyal_imenuvani=0.75), "A")
        self.assertEqual(kod(sredna=8.0, dyal_imenuvani=0.7499), "B")
        self.assertEqual(kod(sredna=8.0, dyal_pohvati=0.0499), "A")
        self.assertEqual(kod(sredna=8.0, dyal_pohvati=0.05), "B")
        self.assertEqual(kod(sredna=8.0, istoriya_dni=90), "A")
        self.assertEqual(kod(sredna=8.0, istoriya_dni=89), "B")

    def test_uverenost(self):
        # A и A+ искат поне половината записи със средна или висока увереност; иначе най-много B
        self.assertEqual(kod(sredna=9.5, dyal_uverenost=0.5), "A+")
        self.assertEqual(kod(sredna=9.5, dyal_uverenost=0.4999), "B")
        self.assertEqual(kod(sredna=8.0, dyal_uverenost=0.5), "A")
        self.assertEqual(kod(sredna=8.0, dyal_uverenost=0.4999), "B")
        self.assertEqual(kod(sredna=8.0, dyal_uverenost=0.0), "B")
        self.assertEqual(kod(sredna=6.5, dyal_uverenost=0.0), "B")  # B не иска модел
        self.assertEqual(kod(sredna=9.5, dyal_uverenost=0.0, dyal_pohvati=0.2), "C")
        r = st.stepen(ch(sredna=8.0, dyal_uverenost=0.2), cfg())
        self.assertIn("оценките са само по правила; A и A+ изискват оценка с модел", r["prichini"][0])
        self.assertIn("20% (нужни поне 50%)", r["prichini"][0])

    def test_uverenost_pragat_e_v_config(self):
        c = cfg()
        for s in c["stepeni"][:2]:
            s["min_uverenost"] = 0.1
        self.assertEqual(st.stepen(ch(sredna=8.0, dyal_uverenost=0.2), c)["kod"], "A")

    def test_b_usloviya(self):
        self.assertEqual(kod(sredna=6.5, dyal_pohvati=0.1499), "B")
        self.assertEqual(kod(sredna=6.5, dyal_pohvati=0.15), "C")
        self.assertEqual(kod(sredna=6.5, sedmici_s_publikacii=3), "B")
        self.assertEqual(kod(sredna=6.5, sedmici_s_publikacii=2), "C")

    def test_c_nyama_dopalnitelni_usloviya(self):
        self.assertEqual(kod(sredna=5.0, dyal_imenuvani=0.0, dyal_pohvati=1.0, sedmici_s_publikacii=1), "C")

    def test_pada_stapalo_po_stapalo(self):
        # в обхвата на A+, но без именувани източници и с много похвати → чак до C
        r = st.stepen(ch(sredna=9.5, dyal_imenuvani=0.1, dyal_pohvati=0.2), cfg())
        self.assertEqual(r["kod"], "C")
        self.assertEqual([p.split(":")[0] for p in r["prichini"]], ["не е A+", "не е A", "не е B"])

    def test_malko_danni(self):
        self.assertEqual(kod(zapisi=29), "Без степен")
        self.assertEqual(kod(zapisi=30), "A")
        self.assertEqual(kod(istoriya_dni=27), "Без степен")
        self.assertEqual(kod(istoriya_dni=28, zapisi=30), "B")  # A иска 90 дни
        r = st.stepen(ch(zapisi=5, istoriya_dni=10), cfg())
        self.assertIn("недостатъчно данни", r["prichini"][0])

    def test_mashinata_nikoga_ne_spira(self):
        for sredna in (0.0, 2.0, 3.9, 4.0, 6.0, 9.9):
            for zapisi in (0, 29, 30, 500):
                for pohvati in (0.0, 0.5, 1.0):
                    self.assertNotEqual(kod(sredna=sredna, zapisi=zapisi, dyal_pohvati=pohvati), "Спряна")

    def test_rachno_spryana(self):
        mashinna = st.stepen(ch(), cfg())
        k = {"id": "x", "spryana": {"osnovanie": "писмено решение", "rolya": "съвет", "data": "2026-09-15"}}
        r = st.s_rachno(mashinna, k, cfg())
        self.assertEqual(r["kod"], "Спряна")
        self.assertEqual(r["cvyat_ime"], "червено")
        self.assertEqual(r["mashinna"]["kod"], "A")
        self.assertIs(st.s_rachno(mashinna, {"id": "x"}, cfg()), mashinna)

    def test_rang(self):
        c = cfg()
        red = [st.rang(k, c) for k in ("A+", "A", "B", "C", "Без степен")]
        self.assertEqual(red, sorted(red, reverse=True))
        self.assertEqual(len(set(red)), 5)

    def test_pragovete_sa_v_config(self):
        c = cfg()
        c["stepeni"][1]["ot"] = 8.5
        self.assertEqual(st.stepen(ch(sredna=8.0), c)["kod"], "B")


def zapis(den, ocenka, proz=10.0, pohvati=()):
    return {"id": 0, "den": den, "zaglavie": "", "url": "", "ocenka": ocenka,
            "osi": {"prozrachnost": proz}, "pohvati": [{"ime": p, "otkas": "…"} for p in pohvati],
            "rezhim": "bez-model", "uverenost": "ниска", "chovek": "не"}


class TestChisla(unittest.TestCase):
    DO = date(2026, 9, 27)

    def test_prozorec_i_sredna(self):
        ot, do = st.period(self.DO, 28)
        self.assertEqual(ot, date(2026, 8, 31))
        z = [zapis(date(2026, 1, 1), 1.0)] + [zapis(self.DO - timedelta(days=i), o)
                                               for i, o in enumerate([9.2, 9.4, 9.1, 9.3])]
        c = st.chisla(z, ot, do, cfg())
        self.assertEqual(c["zapisi"], 4)            # старият запис е извън прозореца
        self.assertEqual(c["sredna"], 9.3)          # 9.25 → 9.3, точна десетична аритметика
        self.assertEqual(c["istoriya_dni"], 270)    # но историята започва от него
        self.assertEqual(c["sedmici_s_publikacii"], 1)
        self.assertEqual(len(c["sedmici"]), 4)

    def test_dyal_uverenost(self):
        z = [zapis(self.DO, 7.0) for _ in range(4)]
        z[0]["uverenost"], z[1]["uverenost"] = "средна", "висока"
        c = st.chisla(z, self.DO - timedelta(days=27), self.DO, cfg())
        self.assertEqual(c["dyal_uverenost"], 0.5)

    def test_imenuvani_i_pohvati(self):
        z = [zapis(self.DO, 7.0, proz=5.0), zapis(self.DO, 7.0, proz=4.9),
             zapis(self.DO, 7.0, pohvati=["Апел към страх", "Апел към страх"]), zapis(self.DO, 7.0)]
        c = st.chisla(z, self.DO - timedelta(days=27), self.DO, cfg())
        self.assertEqual(c["dyal_imenuvani"], 0.75)  # прагът 5.0 е включително
        self.assertEqual(c["dyal_pohvati"], 0.25)
        self.assertEqual(c["pohvati"][0]["zapisi"], 1)  # един запис, макар и с два откъса
        self.assertEqual(len(c["pohvati"][0]["primeri"]), 2)

    def test_bez_zapisi(self):
        c = st.chisla([], self.DO - timedelta(days=27), self.DO, cfg())
        self.assertIsNone(c["sredna"])
        self.assertEqual(st.stepen(c, cfg())["kod"], "Без степен")


if __name__ == "__main__":
    unittest.main()
