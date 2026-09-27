"""Всеки от 14-те похвата: поне един положителен и един отрицателен пример.

    cd apps/doverie && python3 -m unittest discover -s tests -v
"""
import unittest

from obshto import FalshivModel, cfg, primer

from doverie import pohvati
from doverie.ocenka import ocenka

NEUTRALEN = ("Общинският съвет в град Примерово прие вчера бюджета за 2027 г. "
             "По данни на общинската дирекция „Финанси“ разходите за училища растат с 4%.")

# похвати по правила: ключ → (положителен текст, отрицателен текст)
PRAVILA = {
    "appeal_to_fear": ("Опасността расте. Заплахата е огромна и ни чака крах.",
                       "Пожарникарите обясниха как да се пазим, ако има опасност от пожар."),
    "false_dichotomy": ("Или приемаме закона, или страната ще загине.",
                        "Съветът може да приеме закона или да го отложи за следващата сесия."),
    "anonymous_authority": ("Специалисти твърдят, че водата е опасна.",
                            "Специалисти твърдят, че водата е чиста, според доклад на Примерната лаборатория (2026)."),
    "bandwagon": ("Всички знаят, че това е вярно.",
                  "Всички пътници бяха качени на автобуса."),
}

# похвати само с модел: ключ → точен откъс, който присъства в текста
MODELNI = {
    "strawman": "Опонентите искат просто да затворят всички училища.",
    "cherry_picking": "Само през юли продажбите скочиха с 40%.",
    "ad_hominem": "Той е провален човек, затова предложението му е безсмислено.",
    "slippery_slope": "Днес платен паркинг, утре платен въздух.",
    "appeal_to_tradition": "Винаги е било така и така трябва да остане.",
    "false_equivalence": "Една дупка на пътя е същото като срутен мост.",
    "loaded_language": "Чудовищното решение на безумците от съвета.",
    "appeal_to_nature": "Това е естествено, значи е полезно.",
    "circular_reasoning": "Решението е правилно, защото е вярно решение.",
}


def kluchove(rez):
    return {p["kluch"] for p in rez["pohvati"]}


class TestPravila(unittest.TestCase):
    def test_polozhitelni(self):
        for k, (da, _) in PRAVILA.items():
            with self.subTest(k):
                rez = ocenka(da, cfg())
                self.assertIn(k, kluchove(rez))
                p = next(p for p in rez["pohvati"] if p["kluch"] == k)
                self.assertIn(p["otkas"], da)  # точният откъс от текста
                self.assertEqual(p["ime"], pohvati.POHVATI[k][0])
                self.assertTrue(p["obyasnenie"].endswith("."))

    def test_otricatelni(self):
        for k, (_, ne) in PRAVILA.items():
            with self.subTest(k):
                self.assertNotIn(k, kluchove(ocenka(ne, cfg())))

    def test_strah_edna_duma_ne_stiga_bez_model(self):
        self.assertNotIn("appeal_to_fear", kluchove(ocenka("Има опасност от лед по пътищата.", cfg())))

    def test_ai_polozhitelen_i_otricatelen(self):
        rez = ocenka(primer(3), cfg())
        p = next(p for p in rez["pohvati"] if p["kluch"] == "ai_generated")
        self.assertGreaterEqual(p["veroyatnost"], 0.85)
        self.assertNotIn("ai_generated", kluchove(ocenka(primer(2), cfg())))
        self.assertNotIn("ai_generated", kluchove(ocenka(primer(1), cfg())))

    def test_ai_kratak_tekst_ne_se_ocenyava(self):
        self.assertEqual(pohvati.ai_veroyatnost("Едно. Две. Три."), 0.0)

    def test_neutralen_bez_pohvati(self):
        self.assertEqual(ocenka(NEUTRALEN, cfg())["pohvati"], [])

    def test_bez_model_neprovereni(self):
        self.assertEqual(set(ocenka(NEUTRALEN, cfg())["neprovereni_pohvati"]), set(MODELNI))

    def test_chetirinadeset(self):
        self.assertEqual(len(pohvati.POHVATI), 14)
        self.assertEqual(set(PRAVILA) | set(MODELNI) | {"ai_generated"}, set(pohvati.POHVATI))


class TestModelni(unittest.TestCase):
    def test_polozhitelni(self):
        for k, otkas in MODELNI.items():
            with self.subTest(k):
                tekst = NEUTRALEN + " " + otkas
                m = FalshivModel(pohvati=[{"kluch": k, "otkas": otkas, "obyasnenie": "Обяснение."}])
                rez = ocenka(tekst, cfg(), model=m)
                self.assertIn(k, kluchove(rez))

    def test_otricatelni(self):
        for k in MODELNI:
            with self.subTest(k):
                self.assertNotIn(k, kluchove(ocenka(NEUTRALEN, cfg(), model=FalshivModel())))

    def test_izmislen_otkas_se_otkhvarlya(self):
        m = FalshivModel(pohvati=[{"kluch": "strawman", "otkas": "Това го няма в текста.", "obyasnenie": "."}])
        self.assertNotIn("strawman", kluchove(ocenka(NEUTRALEN, cfg(), model=m)))

    def test_nepoznat_kluch_se_otkhvarlya(self):
        m = FalshivModel(pohvati=[{"kluch": "izmislen", "otkas": "Общинският съвет", "obyasnenie": "."}])
        self.assertEqual(ocenka(NEUTRALEN, cfg(), model=m)["pohvati"], [])

    def test_strah_dumi_plus_potvarzhdenie(self):
        tekst = "Опасността расте. Заплахата е огромна."
        potv = FalshivModel(pohvati=[{"kluch": "appeal_to_fear", "otkas": "Заплахата е огромна.", "obyasnenie": "Плаши."}])
        self.assertIn("appeal_to_fear", kluchove(ocenka(tekst, cfg(), model=potv)))
        # думите сами, без потвърждение от модела — няма похват
        self.assertNotIn("appeal_to_fear", kluchove(ocenka(tekst, cfg(), model=FalshivModel())))
        # моделът „потвърждава“, но в текста няма думи за страх — няма похват
        m = FalshivModel(pohvati=[{"kluch": "appeal_to_fear", "otkas": "Общинският съвет", "obyasnenie": "."}])
        self.assertNotIn("appeal_to_fear", kluchove(ocenka(NEUTRALEN, cfg(), model=m)))


if __name__ == "__main__":
    unittest.main()
