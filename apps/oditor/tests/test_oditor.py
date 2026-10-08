"""Одиторът върху измислен свят: правилникът, учтивото обхождане, браузърът, моделът и цитатите, отчетът,
„преди/след“ и командите. Нула мрежа, нула истински модел, нула истински браузър."""
import json
import os
import tempfile
import unittest
from unittest import mock

from obshto import CFG, SEGA, Brauzar, Model, Papka, Svyat, fix, stranici

from oditor import citati, obhod, otchet, pravilnik
from oditor.model import GreshkaModel
from oditor.model import Model as IstinskiModel
from oditor.mrezha import user_agent

SASTOYANIYA = set(pravilnik.SASTOYANIYA)


def _stalb(z, kod):
    return next(s for s in z["rezultat"]["stalbove"] if s["kod"] == kod)


def _signal(z, kod):
    r = z["rezultat"]
    for s in [x for st in r["stalbove"] for x in st["signali"]] + r["dopalnitelno"] + r["pravni_signali"]:
        if s["kod"] == kod:
            return s
    raise KeyError(kod)


def _vsichki_signali(r):
    return [x for st in r["stalbove"] for x in st["signali"]] + r["dopalnitelno"] + r["pravni_signali"]


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestPravilnik(unittest.TestCase):
    def test_dobar_sayt_5_ot_5(self):
        with Papka() as p:
            z = p.zapis(p.proveri("https://example.com/"))
            r = z["rezultat"]
            self.assertEqual((r["tochki"], r["ot"]), (5, 5))
            self.assertEqual(r["rulebook"], "v1")
            self.assertEqual(z["rulebook"], "v1")
            self.assertEqual(_signal(z, "org_tip")["stoynost"], "EventVenue")
            self.assertEqual(_signal(z, "sabitiya")["sastoyanie"], "има")
            self.assertEqual(_signal(z, "registar")["sastoyanie"], "има")  # досието от config.example.json
            for kod in ("hsts", "csp", "xcto", "viewport", "llms_txt", "politika_poveritelnost", "banner", "eik",
                        "dostapnost"):
                self.assertEqual(_signal(z, kod)["sastoyanie"], "има", kod)
            self.assertEqual(_signal(z, "xfo")["sastoyanie"], "не_е_намерено")
            self.assertEqual(_signal(z, "cms")["stoynost"], "WordPress 6.6")
            self.assertEqual(_signal(z, "trakeri")["stoynost"], ["Google Tag Manager", "Google Analytics"])
            self.assertEqual(_signal(z, "banner")["stoynost"], "Cookiebot")

    def test_vsyaka_nahodka_ima_dokazatelstvo_ili_prichina(self):
        with Papka() as p:
            for url in ("https://example.com/", "https://example.org/", "https://example.net/",
                        "https://bez-nas.example.net/", "http://hostel.example.net/"):
                r = p.zapis(p.proveri(url))["rezultat"]
                for s in _vsichki_signali(r):
                    self.assertIn(s["sastoyanie"], SASTOYANIYA, (url, s["kod"]))
                    self.assertTrue(pravilnik.s_dokazatelstvo(s), (url, s["kod"]))
                    for d in s.get("dokazatelstvo") or []:
                        self.assertTrue(d["url"] and d["t"], (url, s["kod"]))

    def test_ednakav_vhod_ednakva_ocenka(self):
        with Papka() as p:
            sn = p.zapis(p.proveri("https://example.com/"))["snimka"]
        a, b = pravilnik.oceni(json.loads(json.dumps(sn))), pravilnik.oceni(json.loads(json.dumps(sn)))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_nikoga_lipsva(self):
        with Papka() as p:
            for url in ("https://example.org/", "https://example.net/", "https://teatar.example.com/"):
                kod, out, err = p.hod("otchet", p.proveri(url))
                self.assertEqual(kod, 0, err)
                self.assertNotIn("липсва", out.lower())
                self.assertNotIn("нарушава", out.lower())

    def test_otlozheno_sabitie_s_greshen_status(self):
        with Papka() as p:
            z = p.zapis(p.proveri("https://teatar.example.com/"))
            s = _signal(z, "sabitiya")
            self.assertEqual(s["sastoyanie"], "не_е_намерено")
            self.assertTrue(any("EventScheduled" in x and "отложен" in x for x in s["problemi"]))
            self.assertTrue(any("offers" in x for x in s["problemi"]))
            self.assertEqual(_stalb(z, "struktura")["sastoyanie"], "не_е_намерено")
            self.assertEqual(_stalb(z, "dostap")["sastoyanie"], "има")

    def test_chuzhd_ezik_ne_gubi_tochka(self):
        with Papka() as p:
            z = p.zapis(p.proveri("http://hostel.example.net/"))
            self.assertEqual(_stalb(z, "ezici")["sastoyanie"], "има")
            self.assertEqual(_signal(z, "chuzhd_ezik")["stoynost"], "en")
            self.assertEqual(z["rezultat"]["kraen_url"], "https://hostel.example.net/")
            self.assertEqual(_signal(z, "https")["sastoyanie"], "има")
            # пренасочването е доказателство
            self.assertEqual(_signal(z, "https")["dokazatelstvo"][0]["status"], 301)

    def test_lichni_adresi_ne_se_pazyat(self):
        with Papka() as p:
            rid = p.proveri("https://example.com/")
            r = p.zapis(rid)["rezultat"]
            self.assertEqual(r["obshti_adresi"], ["info@example.com"])
            self.assertEqual(r["drugi_adresi_ne_se_pazyat"], 1)
            for fmt in ("md", "json"):
                kod, out, err = p.hod("otchet", rid, "--format", fmt)
                self.assertNotIn("ivan.petrov", out)


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestObhod(unittest.TestCase):
    def test_tri_zayavki_i_nash_ua(self):
        with Papka() as p:
            p.proveri("https://example.com/")
            self.assertEqual(p.svyat.adresi(), ["https://example.com/robots.txt", "https://example.com/",
                                                "https://example.com/llms.txt"])
            ua = p.svyat.zayavki[0][1]
            self.assertEqual(ua, user_agent(CFG))
            self.assertTrue(ua.startswith("oditor/"))
            self.assertIn("(+https://", ua)
            self.assertEqual({u for _, u in p.svyat.zayavki}, {ua})

    def test_pauza_na_hosta_i_mezhdu_saytovete(self):
        with Papka() as p:
            spisak = os.path.join(p.d, "spisak.txt")
            with open(spisak, "w", encoding="utf-8") as f:
                f.write("# коментар\nhttps://example.com/\n\nhttps://teatar.example.com/\n")
            kod, out, err = p.hod("proveri-spisak", spisak)
            self.assertEqual(kod, 0, err)
            self.assertIn("Готови 2 от 2", out)
            self.assertIn(float(CFG["pauza_mezhdu_saytove_s"]), p.svyat.spane)
            # между заявките към един хост има пауза, поне pauza_na_hosta_s от предишната
            self.assertTrue(any(abs(s - (CFG["pauza_na_hosta_s"] - 0.1)) < 1e-6 for s in p.svyat.spane))

    def test_robots_spira_nas(self):
        with Papka() as p:
            z = p.zapis(p.proveri("https://bez-nas.example.net/"))
            self.assertEqual(p.svyat.adresi(), ["https://bez-nas.example.net/robots.txt"])
            self.assertEqual(z["rezultat"]["tochki"], 0)
            for st in z["rezultat"]["stalbove"]:
                self.assertEqual(st["sastoyanie"], "непроверено")
            self.assertIn("robots", _signal(z, "status_200")["prichina"])
            self.assertEqual(p.brauzar.vikan, [])

    def test_robots_spira_ai_botovete(self):
        with Papka() as p:
            z = p.zapis(p.proveri("https://ai.example.org/"))
            s = _signal(z, "ai_robots")
            self.assertEqual(s["sastoyanie"], "блокирано")
            self.assertEqual(s["stoynost"], ["GPTBot", "ClaudeBot"])
            self.assertIn("предпочитание", s["belezhka"])
            self.assertEqual(_stalb(z, "dostap")["tochka"], 0)

    def test_robots_5xx_nishto_ne_se_tegli(self):
        st = stranici()
        st["https://example.com/robots.txt"] = (503, {}, b"")
        with Papka(Svyat(st)) as p:
            z = p.zapis(p.proveri("https://example.com/"))
            self.assertEqual(p.svyat.adresi(), ["https://example.com/robots.txt"])
            self.assertEqual(_signal(z, "ai_robots")["sastoyanie"], "непроверено")

    def test_izklyuchen_sayt_bez_nito_edna_zayavka(self):
        with Papka() as p:
            kod, out, err = p.hod("proveri", "https://opt-out.example.net/")
            self.assertEqual(kod, 1)
            self.assertIn("поискал да не бъде проверяван", err)
            self.assertEqual(p.svyat.zayavki, [])

    def test_proba_s_ai_ua_e_ascii_i_chestna(self):
        cfg = dict(CFG, proba_s_ai_ua=True)
        sv = Svyat()
        sn = obhod.snimai(cfg, "https://example.com/", sv.mrezha(cfg), brauzar_fabrika=Brauzar())
        self.assertEqual(set(sn["ai_ua"]), set(pravilnik.AI_BOTOVE))
        for bot, z in sn["ai_ua"].items():
            self.assertIsNone(z["greshka"])
            self.assertTrue(z["ua"].startswith(bot + " (probe by oditor/"))
        self.assertEqual(pravilnik.oceni(sn)["stalbove"][0]["signali"][3]["sastoyanie"], "има")

    def test_llms_txt_html_s_200_ne_se_broi(self):
        with Papka() as p:
            z = p.zapis(p.proveri("https://example.org/"))
            s = _signal(z, "llms_txt")
            self.assertEqual(s["sastoyanie"], "не_е_намерено")
            self.assertIn("HTML", s["belezhka"])


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestBrauzar(unittest.TestCase):
    def test_js_sayt_bez_brauzar(self):
        # без фабрика за браузър и без Playwright на машината
        with mock.patch("oditor.brauzar.nalichen", return_value=False):
            sv = Svyat()
            sn = obhod.snimai(CFG, "https://example.org/", sv.mrezha(CFG))
        self.assertEqual(sn["brauzar"]["izpolzvan"], False)
        self.assertEqual(sn["brauzar"]["zashto"], "Playwright не е инсталиран")
        self.assertIn("малко текст", sn["brauzar"]["prichina"])
        r = pravilnik.oceni(sn)
        tekst = next(s for s in r["stalbove"][0]["signali"] if s["kod"] == "tekst")
        self.assertEqual(tekst["sastoyanie"], "не_е_намерено")
        self.assertIn("без JavaScript", tekst["belezhka"])
        self.assertEqual(r["brauzar"]["sastoyanie"], "непроверено")
        otkaz = next(s for s in r["pravni_signali"] if s["kod"] == "otkaz_buton")
        self.assertEqual(otkaz["sastoyanie"], "непроверено")

    def test_js_sayt_s_brauzar(self):
        br = Brauzar({"https://example.org/": (fix("js_sayt_brauzar.html").decode("utf-8"), True, True)})
        with Papka(brauzar=br) as p:
            z = p.zapis(p.proveri("https://example.org/"))
            self.assertEqual(br.vikan, ["https://example.org/"])
            self.assertTrue(z["rezultat"]["brauzar"]["izpolzvan"])
            org = _signal(z, "org_tip")
            self.assertEqual(org["sastoyanie"], "има")
            self.assertTrue(org["samo_s_js"])
            self.assertEqual(org["dokazatelstvo"][0]["izvor"], "браузър (JavaScript)")
            # ботът без JavaScript пак вижда малко текст — това остава находка
            self.assertEqual(_signal(z, "tekst")["sastoyanie"], "не_е_намерено")
            self.assertEqual(_signal(z, "otkaz_buton")["sastoyanie"], "има")
            kod, out, err = p.hod("otchet", z["id"])
            self.assertIn("(само с JavaScript)", out)
            self.assertIn("Браузър с JavaScript: използван", out)

    def test_zashtitna_stena_403(self):
        with Papka() as p:
            z = p.zapis(p.proveri("https://example.net/"))
            self.assertEqual(p.brauzar.vikan, ["https://example.net/"])  # втори опит, отбелязан
            self.assertIn("падна", z["rezultat"]["brauzar"]["zashto"])
            self.assertEqual(z["rezultat"]["brauzar"]["prichina"], "отказ HTTP 403")
            s = _signal(z, "status_200")
            self.assertEqual(s["sastoyanie"], "блокирано")
            self.assertIn("защита, не повреда", s["belezhka"])
            for st in z["rezultat"]["stalbove"]:
                self.assertEqual(st["sastoyanie"], "блокирано", st["kod"])
            self.assertEqual(_signal(z, "org_tip")["sastoyanie"], "блокирано")

    def test_brauzar_izklyuchen_v_config(self):
        cfg = dict(CFG, brauzar={"vklyuchen": False})
        sn = obhod.snimai(cfg, "https://example.org/", Svyat().mrezha(cfg), brauzar_fabrika=Brauzar())
        self.assertEqual(sn["brauzar"]["zashto"], "изключен в config")


class TestCitati(unittest.TestCase):
    TEKST = fix("politika_palna.html").decode("utf-8")

    def test_doslovno_sled_normalizirane(self):
        ok, prich = citati.proveri("Администратор на личните данни е «Примерна зала» ЕООД", self.TEKST)
        self.assertTrue(ok, prich)

    def test_nenameren(self):
        ok, prich = citati.proveri("Администратор на личните данни е друго дружество ООД", self.TEKST)
        self.assertFalse(ok)
        self.assertIn("не е намерен", prich)

    def test_kratak(self):
        ok, prich = citati.proveri("Срокове", self.TEKST)
        self.assertFalse(ok)
        self.assertIn("под 6 думи", prich)

    def test_samo_obyavyava_temata(self):
        ok, prich = citati.proveri("В тази политика ще намерите информация за администратора", self.TEKST)
        self.assertFalse(ok)
        self.assertIn("обявява темата", prich)


def _politika_otgovor(cit_admin, cit_celi):
    def f(sistema, tekst):
        return {"items": [
            {"code": "controller", "present": True, "quote": cit_admin},
            {"code": "purposes", "present": True, "quote": cit_celi},
            {"code": "retention", "present": True, "quote": "Данните се пазят вечно и никога не се трият от системата"},
            {"code": "cookies", "present": False, "quote": ""},
        ]}
    return f


@mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""})
class TestPolitikaIIzpit(unittest.TestCase):
    def test_palna_politika(self):
        m = Model({"visok_risk": _politika_otgovor(
            "Администратор на личните данни е „Примерна зала“ ЕООД",
            "Обработваме данните ви, за да продаваме билети и да изпращаме потвърждения")})
        with Papka(model=m) as p:
            z = p.zapis(p.proveri("https://example.com/", "--politika"))
            self.assertIn("https://example.com/poveritelnost", p.svyat.adresi())
            pol = z["politika"]
            e = {x["kod"]: x for x in pol["elementi"]}
            self.assertEqual(e["controller"]["sastoyanie"], "има")
            self.assertEqual(e["purposes"]["sastoyanie"], "има")
            self.assertEqual(e["retention"]["sastoyanie"], "непотвърдено")  # измислен цитат
            self.assertEqual(e["cookies"]["sastoyanie"], "не_е_намерено")
            self.assertEqual(e["rights"]["sastoyanie"], "непроверено")     # моделът мълчи
            self.assertEqual(pol["potvardeni"], 2)
            self.assertEqual(m.vikaniya[0][0], "visok_risk")
            kod, out, err = p.hod("otchet", z["id"], "--format", "json")
            self.assertNotIn("вечно", out)  # непотвърденият цитат не излиза навън

    def test_politika_samo_s_vavedenie(self):
        m = Model({"visok_risk": _politika_otgovor(
            "В тази политика ще намерите кой е администраторът",
            "за какви цели обработваме данните и какви са правата ви")})
        with Papka(model=m) as p:
            z = p.zapis(p.proveri("https://vavedenie.example.com/", "--politika"))
            e = {x["kod"]: x for x in z["politika"]["elementi"]}
            self.assertEqual(e["controller"]["sastoyanie"], "непотвърдено")
            self.assertIn("обявява темата", e["controller"]["prichina"])
            self.assertEqual(e["purposes"]["sastoyanie"], "непотвърдено")  # от средата на въвеждащото изречение
            self.assertEqual(z["politika"]["potvardeni"], 0)

    def test_model_bez_vrata_ne_se_vika(self):
        posti = []
        m = IstinskiModel(dict(CFG["model"], gate_url=None), post=lambda *a: posti.append(a))
        with self.assertRaises(GreshkaModel) as c:
            m.chat("visok_risk", "s", "t")
        self.assertIn("gate_url", str(c.exception))
        self.assertEqual(posti, [])

    def test_model_zaeta_mashina(self):
        posti = []
        m = IstinskiModel(dict(CFG["model"], gate_url="http://vrata.example.net/"),
                          post=lambda *a: posti.append(a), get=lambda url, t: (200, '{"busy": true}'))
        with self.assertRaises(GreshkaModel):
            m.chat("rabotnik", "s", "t")
        self.assertEqual(posti, [])

    def test_model_vika_api_chat_s_json(self):
        posti = []

        def post(url, body, t):
            posti.append((url, body))
            return 200, json.dumps({"message": {"content": '{"verdict": "answers"}'}})
        m = IstinskiModel(dict(CFG["model"], gate_url="http://vrata.example.net/"), post=post,
                          get=lambda url, t: (200, "ok"))
        self.assertEqual(m.chat("pazach", "s", "t"), {"verdict": "answers"})
        url, body = posti[0]
        self.assertTrue(url.endswith("/api/chat"))
        self.assertEqual((body["model"], body["format"], body["stream"]), ("nemotron-3-super", "json", False))

    def test_izpit(self):
        def rabotnik(sistema, tekst):
            return {"answers": [
                {"code": "offer", "found": True, "answer": "концерти",
                 "quote": "Всяка седмица представяме концерти, театрални постановки и детски програми"},
                {"code": "price", "found": True, "answer": "25 евро", "quote": "Билетите струват 25 евро"},
                {"code": "order", "found": True, "answer": "форма",
                 "quote": "попълнете формата за резервация или се обадете на касата"},
            ]}
        pazach_vikan = []

        def pazach(sistema, tekst):
            pazach_vikan.append(json.loads(tekst))
            return {"verdict": "does_not_answer" if "касата" in tekst else "answers"}
        m = Model({"rabotnik": rabotnik, "pazach": pazach})
        with Papka(model=m) as p:
            z = p.zapis(p.proveri("https://example.com/", "--izpit"))
            self.assertEqual(len(p.svyat.zayavki), 3)  # изпитът не прави нови заявки
            iz = z["izpit"]
            o = {x["kod"]: x for x in iz["otgovori"]}
            self.assertEqual(o["offer"]["sastoyanie"], "има")
            self.assertEqual(o["price"]["sastoyanie"], "има")
            self.assertEqual(o["order"]["sastoyanie"], "непотвърдено")
            self.assertIn("пазачът", o["order"]["prichina"])
            self.assertEqual((iz["tochki"], iz["ot"]), (2, 3))
            self.assertEqual(set(pazach_vikan[0]), {"question", "quote"})
            self.assertEqual(z["rezultat"]["ot"], 5)  # изпитът е отделно от 0–5

    def test_izpit_cena_bez_chislo(self):
        m = Model({"rabotnik": lambda s, t: {"answers": [
            {"code": "price", "found": True, "quote": "и се купуват онлайн или на касата"}]}}, roli=("rabotnik",))
        with Papka(model=m) as p:
            z = p.zapis(p.proveri("https://example.com/", "--izpit"))
            o = {x["kod"]: x for x in z["izpit"]["otgovori"]}
            self.assertEqual(o["price"]["sastoyanie"], "непотвърдено")
            self.assertIn("число", o["price"]["prichina"])
            self.assertEqual(o["offer"]["sastoyanie"], "не_е_намерено")

    def test_izpit_bez_model(self):
        with Papka(model=Model(roli=())) as p:
            z = p.zapis(p.proveri("https://example.com/", "--izpit"))
            self.assertEqual(z["izpit"]["sastoyanie"], "непроверено")


class TestKomandi(unittest.TestCase):
    def test_povtorno_predi_sled(self):
        with mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""}), Papka() as p:
            predi = p.proveri("https://teatar.example.com/")
            p.svyat.st["https://teatar.example.com/"] = (200, {"content-type": "text/html; charset=utf-8"},
                                                         fix("sled_popravka.html"))
            kod, out, err = p.hod("povtorno", predi, sega="2026-10-09T08:00:00Z")
            self.assertEqual(kod, 0, err)
            self.assertIn("Оценка: 3 → 4 от 5", out)
            self.assertIn("стълб Структура: не_е_намерено → има", out)
            sled = sorted(os.listdir(p.rez))[-1][:-5]
            self.assertEqual(p.zapis(sled)["predishen"], predi)
            self.assertTrue(os.path.exists(os.path.join(p.rez, predi + ".json")))  # нищо не се презаписва

    def test_otchet_izhvarlya_bez_dokazatelstvo(self):
        with mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""}), Papka() as p:
            rid = p.proveri("https://example.com/")
            pat = os.path.join(p.rez, rid + ".json")
            z = p.zapis(rid)
            z["rezultat"]["dopalnitelno"].append({"kod": "izmisleno", "ime": "измислено", "sastoyanie": "има",
                                                  "dokazatelstvo": []})
            with open(pat, "w", encoding="utf-8") as f:
                json.dump(z, f, ensure_ascii=False)
            kod, out, err = p.hod("otchet", rid, "--format", "json")
            d = json.loads(out)
            self.assertEqual(d["izhvarleni_bez_dokazatelstvo"], 1)
            self.assertNotIn("izmisleno", out)
            self.assertNotIn("snimka", d)
            kod, out, err = p.hod("otchet", rid)
            self.assertIn("Изхвърлени находки без доказателство: 1", out)
            self.assertIn("METHODOLOGY.md", out)
            self.assertIn("rulebook v1", out)

    def test_kodove_na_izhod(self):
        with mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": "", "SHINKANSEN_SUMMARY_FILE": ""}), Papka() as p:
            self.assertEqual(p.hod("proveri", "ftp://example.com/")[0], 2)
            self.assertEqual(p.hod("nyama-takava")[0], 2)
            self.assertEqual(p.hod("otchet", "20261008-nyama-1")[0], 1)
            self.assertEqual(p.hod("otchet", "../config")[0], 1)
            # отказ от сайта е находка, не грешка
            self.assertEqual(p.hod("proveri", "https://example.net/")[0], 0)

    def test_dnevnik_bez_adresi(self):
        with tempfile.TemporaryDirectory() as runs, \
                mock.patch.dict(os.environ, {"SHINKANSEN_RUNS": runs, "SHINKANSEN_SUMMARY_FILE": ""}), Papka() as p:
            p.proveri("https://example.com/")
            with open(os.path.join(runs, "oditor.jsonl"), encoding="utf-8") as f:
                redove = [json.loads(r) for r in f]
            self.assertEqual(redove[-1]["helper"], "oditor")
            self.assertTrue(redove[-1]["ok"])
            self.assertIn("5/5", redove[-1]["summary"])
            self.assertNotIn("example", json.dumps(redove))

    def test_config_primerite_sa_samo_example(self):
        tekst = json.dumps(CFG)
        import re
        for host in re.findall(r"[a-z0-9.-]+\.(?:com|org|net|bg|eu)\b", tekst):
            self.assertRegex(host, r"(^|\.)example\.(com|org|net)$|^github\.com$", host)
        self.assertEqual(CFG["model"]["rabotnik"]["ime"], "gemma4")
        self.assertNotIn("gpt-oss", tekst)


if __name__ == "__main__":
    unittest.main()
