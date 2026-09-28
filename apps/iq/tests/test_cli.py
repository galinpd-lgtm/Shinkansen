"""Командите през main() върху измислената база: степени, отчет, значка, предпазител, promeni.log, методика."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from obshto import APP, CFG_PAT, KANALI, ZABRANENI, Papka

from iq import cli


class Hod:
    def __init__(self, p):
        self.p = p

    def __call__(self, komanda, *argv, do="2026-09-27", dnes="2026-09-28"):
        out, err = io.StringIO(), io.StringIO()
        vse = [komanda, "--config", CFG_PAT]
        if komanda != "metodika":
            vse += ["--danni", self.p.danni, "--kanali", self.p.kanali, "--papka", self.p.iq, "--dnes", dnes]
            if do:
                vse += ["--do", do]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            kod = cli.main(vse + list(argv))
        return kod, out.getvalue(), err.getvalue()

    def json(self, kanal, *argv, **kw):
        kod, out, err = self("izchisli", "--kanal", kanal, "--json", *argv, **kw)
        self.kod = kod
        return json.loads(out) if out else None


def heh(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def cheti(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestIzchisli(unittest.TestCase):
    def test_trite_kanala_i_malko_danni(self):
        with Papka() as p:
            h = Hod(p)
            ochakvano = {"primeren-glas": "A+", "primeren-vestnik": "A", "primeren-pravila": "B", "primeren-portal": "B",
                         "primeren-byuletin": "C", "primeren-blog": "Без степен", "primeren-sayt": "Спряна"}
            for k, s in ochakvano.items():
                with self.subTest(kanal=k):
                    r = h.json(k)
                    self.assertEqual(h.kod, 0)
                    self.assertEqual(r["stepen"]["kod"], s)

    def test_chislata_sa_verni(self):
        with Papka() as p:
            h = Hod(p)
            v = h.json("primeren-vestnik")["chisla"]
            self.assertEqual(v["zapisi"], 40)
            self.assertEqual(v["sredna"], 8.1)
            self.assertEqual(v["dyal_imenuvani"], 0.85)
            self.assertEqual(v["dyal_pohvati"], 0.025)
            self.assertEqual(v["istoriya_dni"], 200)
            self.assertEqual(v["dyal_uverenost"], 0.5)
            self.assertEqual(v["bez_model"], 20)
            self.assertEqual(v["period"], {"ot": "2026-08-31", "do": "2026-09-27", "dni": 28})
            b = h.json("primeren-byuletin")["chisla"]
            self.assertEqual((b["sredna"], b["dyal_pohvati"], b["dyal_imenuvani"]), (5.0, 0.3, 0.3))
            g = h.json("primeren-glas")["chisla"]
            self.assertEqual(g["sredna"], 9.3)
            bl = h.json("primeren-blog")
            self.assertEqual(bl["chisla"]["zapisi"], 11)  # записът с ОТКАЗ (без оценка) не се брои
            self.assertIn("недостатъчно данни", bl["stepen"]["prichini"][0])
            s = h.json("primeren-sayt")["stepen"]
            self.assertEqual(s["mashinna"]["kod"], "B")
            self.assertIn("Измислено решение", s["prichini"][0])

    def test_tekstov_izhod(self):
        with Papka() as p:
            kod, out, _ = Hod(p)("izchisli", "--kanal", "primeren-portal")
            self.assertEqual(kod, 0)
            self.assertIn("Степен: B (жълто)", out)
            self.assertIn("Средна оценка:                   6,6", out)

    def test_ot(self):
        with Papka() as p:
            h = Hod(p)
            r = h.json("primeren-vestnik", "--ot", "2026-09-21")
            self.assertEqual(r["chisla"]["period"]["dni"], 7)
            self.assertEqual(r["stepen"]["kod"], "Без степен")  # 14 записа за седмица — под 30
            self.assertFalse(os.path.exists(os.path.join(p.iq, "istoriya.jsonl")))  # --ot не влиза в историята

    def test_greshki(self):
        with Papka() as p:
            h = Hod(p)
            kod, _, err = h("izchisli", "--kanal", "nyama-go")
            self.assertEqual(kod, 1)
            self.assertIn("непознат канал", err)
            kod, _, err = h("izchisli", "--kanal", "primeren-vestnik", "--ot", "2026-10-01")
            self.assertEqual(kod, 1)
            kod, _, err = Hod(p)("izchisli", "--kanal", "primeren-vestnik", "--danni", os.path.join(p.d, "nyama"))
            self.assertEqual(kod, 1)
            self.assertIn("няма база", err)
            with self.assertRaises(SystemExit) as e, contextlib.redirect_stderr(io.StringIO()):
                cli.main(["izchisli"])
            self.assertEqual(e.exception.code, 2)

    def test_bazata_ne_se_promenya(self):
        with Papka() as p:
            pat = os.path.join(p.danni, "filtar.sqlite")
            predi = heh(pat)
            h = Hod(p)
            h.json("primeren-vestnik")
            h("otchet", "--kanal", "primeren-vestnik", "--izhod", os.path.join(p.d, "o.md"))
            self.assertEqual(heh(pat), predi)


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestPromeni(unittest.TestCase):
    def test_vloshavane_se_zapisva(self):
        with Papka() as p:
            h = Hod(p)
            log = os.path.join(p.iq, "promeni.log")
            h("izchisli", "--kanal", "primeren-vestnik")                   # A
            h("izchisli", "--kanal", "primeren-vestnik")                   # A отново — няма влошаване
            self.assertFalse(os.path.exists(log))
            _, _, err = h("izchisli", "--kanal", "primeren-vestnik", do="2026-10-20", dnes="2026-10-20")
            self.assertIn("promeni.log", err)
            redove = cheti(log).splitlines()
            self.assertEqual(len(redove), 1)
            self.assertIn("primeren-vestnik · A → Без степен", redove[0])
            h("izchisli", "--kanal", "primeren-vestnik")                   # подобрение — нищо ново
            self.assertEqual(len(cheti(log).splitlines()), 1)
            self.assertEqual(len(cheti(os.path.join(p.iq, "istoriya.jsonl")).splitlines()), 4)

    def test_spryana_ne_e_mashinno_vloshavane(self):
        with Papka() as p:
            h = Hod(p)
            h("izchisli", "--kanal", "primeren-sayt")
            h("izchisli", "--kanal", "primeren-sayt")
            self.assertFalse(os.path.exists(os.path.join(p.iq, "promeni.log")))
            self.assertIn('"stepen": "B"', cheti(os.path.join(p.iq, "istoriya.jsonl")))


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestPredpazitel(unittest.TestCase):
    def test_bez_saglasie_otkaz(self):
        with Papka() as p:
            h = Hod(p)
            # бюлетинът няма поле, блогът има "да" (не true) — и двата се отказват
            for kanal in ("primeren-byuletin", "primeren-blog"):
                for komanda, ime in (("otchet", "o.md"), ("znachka", "b.svg")):
                    with self.subTest(kanal=kanal, komanda=komanda):
                        izh = os.path.join(p.d, kanal + ime)
                        kod, _, err = h(komanda, "--kanal", kanal, "--izhod", izh)
                        self.assertEqual(kod, 1)
                        self.assertIn("отказано", err)
                        self.assertFalse(os.path.exists(izh))

    def test_kanal_izvan_registara(self):
        with Papka() as p:
            with open(p.kanali, "w", encoding="utf-8") as f:
                f.write("[]")
            h = Hod(p)
            self.assertEqual(h("izchisli", "--kanal", "primeren-vestnik")[0], 0)  # изчислението е вътрешно
            kod, _, _ = h("znachka", "--kanal", "primeren-vestnik", "--izhod", os.path.join(p.d, "b.svg"))
            self.assertEqual(kod, 1)

    def test_vatreshno(self):
        with Papka() as p:
            h = Hod(p)
            o, b = os.path.join(p.d, "o.md"), os.path.join(p.d, "b.svg")
            self.assertEqual(h("otchet", "--kanal", "primeren-byuletin", "--vatreshno", "--izhod", o)[0], 0)
            self.assertEqual(h("znachka", "--kanal", "primeren-byuletin", "--vatreshno", "--izhod", b)[0], 0)
            self.assertIn("Вътрешно · непубликувано", cheti(o))
            self.assertIn("вътрешно · непубликувано", cheti(b))

    def test_sas_saglasie(self):
        with Papka() as p:
            h = Hod(p)
            b = os.path.join(p.d, "b.svg")
            self.assertEqual(h("znachka", "--kanal", "primeren-vestnik", "--izhod", b)[0], 0)
            svg = cheti(b)
            self.assertNotIn("вътрешно", svg)
            self.assertIn(">A<", svg)
            self.assertIn("28.09.2026", svg)
            self.assertIn("#2e7d32", svg)
            self.assertNotIn("KAGAMI", svg.upper())
            self.assertEqual(h("znachka", "--kanal", "primeren-vestnik", "--izhod", b, "--podpis", "Примерен подпис")[0], 0)
            self.assertIn("Примерен подпис", cheti(b))


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestOtchet(unittest.TestCase):
    def test_sadarzhanie(self):
        with Papka() as p:
            o = os.path.join(p.d, "o.md")
            self.assertEqual(Hod(p)("otchet", "--kanal", "primeren-vestnik", "--izhod", o)[0], 0)
            t = cheti(o)
            for chast in ("## Степен: A", "## Числата", "## Седемте оси", "Прозрачност на източниците",
                          "## Най-честите манипулативни похвати", "Анонимен авторитет", "„Експертите смятат",
                          "## Тенденция по седмици", "## Методика", "## Ограничения", "31.08.2026 – 27.09.2026",
                          "Оценени записа:** 40", "не проверява фактите"):
                self.assertIn(chast, t)
            self.assertNotIn("Вътрешно", t)

    def test_bez_zabraneni_dumi(self):
        with Papka() as p:
            h = Hod(p)
            for kid, *_ in KANALI:
                o = os.path.join(p.d, kid + ".md")
                h("otchet", "--kanal", kid, "--vatreshno", "--izhod", o)
                t = cheti(o).lower()
                for d in ZABRANENI:
                    self.assertNotIn(d, t, "%s: „%s“" % (kid, d))
            m = os.path.join(p.d, "metodika.md")
            h("metodika", "--izhod", m)
            for d in ZABRANENI:
                self.assertNotIn(d, cheti(m).lower())

    def test_bez_model_samo_b(self):
        with Papka() as p:
            o = os.path.join(p.d, "o.md")
            self.assertEqual(Hod(p)("otchet", "--kanal", "primeren-pravila", "--izhod", o)[0], 0)
            t = cheti(o)
            self.assertIn("## Степен: B", t)
            self.assertIn("оценките са само по правила; A и A+ изискват оценка с модел", t)
            self.assertIn("| Записи със средна или висока увереност | 45% | поне 50% |", t)

    def test_rachno_spryana_v_otcheta(self):
        with Papka() as p:
            o = os.path.join(p.d, "o.md")
            Hod(p)("otchet", "--kanal", "primeren-sayt", "--izhod", o)
            t = cheti(o)
            self.assertIn("## Степен: Спряна", t)
            self.assertIn("поставена **ръчно**", t)
            self.assertIn("Измислено решение за теста.", t)


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestMetodika(unittest.TestCase):
    def test_metodika(self):
        with Papka() as p:
            m = os.path.join(p.d, "metodika.md")
            self.assertEqual(Hod(p)("metodika", "--izhod", m)[0], 0)
            t = cheti(m)
            for chast in ("| A+ | 9,0–10,0 |", "| A | 7,5–8,9 |", "| B | 6,0–7,4 |", "| C | 4,0–5,9 |",
                          "поне 90%", "под 2%", "поне 365 дни", "поне 75%", "под 5%", "поне 90 дни",
                          "| Без степен | под 4,0, или под 30 оценени записа, или под 28 дни история",
                          "никога не се поставя от машината", "последните **28 дни**", "Не се оценяват хора",
                          "поне 50% от записите със средна или висока увереност"):
                self.assertIn(chast, t)


class TestModul(unittest.TestCase):
    def test_python_m(self):
        env = dict(os.environ, SHINKANSEN_RUNS="", SHINKANSEN_SUMMARY_FILE="")
        r = subprocess.run([sys.executable, "-m", "iq", "--help"], cwd=APP, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        for k in ("izchisli", "otchet", "znachka", "metodika"):
            self.assertIn(k, r.stdout)

    def test_dnevnik(self):
        with Papka() as p:
            runs = os.path.join(p.d, "runs")
            with mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": runs, "SHINKANSEN_SUMMARY_FILE": ""}):
                Hod(p)("izchisli", "--kanal", "primeren-vestnik")
            red = json.loads(cheti(os.path.join(runs, "iq.jsonl")))
            self.assertEqual(red["helper"], "iq")
            self.assertTrue(red["ok"])
            self.assertNotIn("Примерен", red["summary"])


if __name__ == "__main__":
    unittest.main()
