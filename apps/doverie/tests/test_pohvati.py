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


class TestOtricaniya(unittest.TestCase):
    """Отреченото не е похват: „не всички“ не е „всички така мислят“, „няма опасност“ не е апел към страх."""

    SLUCHAI = {
        "bandwagon": (
            ["Всички знаят, че е така.", "Всеки знае отговора.", "Мнозинството смята, че е вярно.",
             "Никой не се съмнява, че е така.",  # двойно отрицание = „всички са съгласни“ — остава похват
             "Ако не действаме, всички знаят какво следва."],  # отрицанието е в друга част на изречението
            ["Не всички са съгласни с мерките.", "Не всеки знае това правило.", "Едва ли всички знаят какво става.",
             "Далеч не всички смятат така.", "Съвсем не всички мислят така.", "Надали всички са съгласни.",
             "Не е вярно, че всички знаят това.", "Никой не знае какво ще стане."]),
        "false_dichotomy": (
            ["Няма алтернатива на този план.", "Това е единственото решение.", "Или ще платим, или ще загубим.",
             "Няма друг избор за града."],
            ["Това не е единственото решение.", "Не е вярно, че няма алтернатива.",
             "Едва ли е единственото решение.", "Това съвсем не е единственият изход."]),
        "appeal_to_fear": (
            ["Опасността е огромна. Заплахата расте.", "Опасността не е малка. Заплахата расте."],
            ["Няма опасност за хората. Заплаха няма и за децата.", "Водата не е опасна. Не представлява заплаха.",
             "Без опасност за здравето. Никаква заплаха за децата.", "Опасност няма. Заплаха няма."]),
    }

    def test_polozhitelni(self):
        for k, (da, _) in self.SLUCHAI.items():
            for t in da:
                with self.subTest(k, t=t):
                    self.assertIn(k, kluchove(ocenka(t, cfg())))

    def test_otricatelni(self):
        for k, (_, ne) in self.SLUCHAI.items():
            for t in ne:
                with self.subTest(k, t=t):
                    self.assertNotIn(k, kluchove(ocenka(t, cfg())))

    def test_otrechenoto_ne_zasenchva_sledvashtoto(self):
        # първото е отречено, второто не — хваща се второто, с неговия откъс
        rez = ocenka("Не всички са съгласни. Но всички знаят, че цените растат.", cfg())
        p = next(p for p in rez["pohvati"] if p["kluch"] == "bandwagon")
        self.assertEqual(p["otkas"].lower(), "всички знаят")
        self.assertIn("всички знаят", "Но всички знаят, че цените растат.")

    def test_anonimen_avtoritet_ostava_i_s_otricanie(self):
        # „експертите не смятат“ пак е позоваване на неназовани експерти — не е грешка от същия вид
        self.assertIn("anonymous_authority", kluchove(ocenka("Експертите смятат, че това не е опасно.", cfg())))


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
