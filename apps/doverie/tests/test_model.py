"""Клиентът към Ollama, топлинната врата и пълният път с фалшив модел. Нула мрежа:
HTTP функциите се подменят, а доверие.model.http_post / доверие.vrata.http_get вдигат грешка, ако бъдат викнати."""
import json
import re
import unittest
from unittest import mock

from obshto import FalshivModel, cfg, primer

from doverie import model as model_mod
from doverie import vrata as vrata_mod
from doverie.model import GreshkaModel, Model
from doverie.ocenka import ocenka
from doverie.vrata import Vrata, VrataGreshka, VrataLipsva, VrataNeBezopasno, VrataZaeta


def bez_mrezha(*a, **kw):
    raise AssertionError("истинска мрежа в тест")


def ollama_otg(sadarzhanie):
    return 200, json.dumps({"message": {"role": "assistant", "content": json.dumps(sadarzhanie, ensure_ascii=False)}})


def otvorena():
    return Vrata("http://g", get=lambda *a: (200, "ok"))


class Zapis:
    def __init__(self, *otg):
        self.otg, self.vikaniya = list(otg), []

    def __call__(self, *a):
        self.vikaniya.append(a)
        return self.otg.pop(0) if len(self.otg) > 1 else self.otg[0]


@mock.patch.object(model_mod, "http_post", bez_mrezha)
@mock.patch.object(vrata_mod, "http_get", bez_mrezha)
class TestKlient(unittest.TestCase):
    def test_tyalo_na_zayavkata(self):
        post = Zapis(ollama_otg({"ocenka": 7, "zashto": "Добре."}))
        v = Vrata("http://127.0.0.1:9109/vrata", get=Zapis((200, '{"state": "ok"}')))
        m = Model(cfg(), vrata=v, post=post)
        self.assertEqual(m.chat("struktura", "с", "п"), {"ocenka": 7, "zashto": "Добре."})
        url, body, timeout = post.vikaniya[0]
        self.assertEqual(url, "http://127.0.0.1:11435/api/chat")
        self.assertEqual(body["model"], "gpt-oss:20b")
        self.assertEqual(body["think"], "low")
        self.assertEqual(body["format"], "json")
        self.assertFalse(body["stream"])
        self.assertEqual(timeout, cfg()["taymaut_s"])
        self.assertEqual(v.pitaniya, 1)

    def test_pisach(self):
        post = Zapis(ollama_otg({}))
        Model(cfg(), vrata=otvorena(), post=post).chat("pisach", "с", "п")
        self.assertEqual(post.vikaniya[0][1]["model"], "gemma4:26b")

    def test_busy_spira_vikaneto(self):
        for otg in ((200, "busy"), (200, '{"state": "hot"}'), (200, '{"busy": true}'), (503, "")):
            with self.subTest(otg):
                post = Zapis(ollama_otg({}))
                m = Model(cfg(), vrata=Vrata("http://g", get=Zapis(otg)), post=post)
                with self.assertRaises(VrataZaeta):
                    m.chat("struktura", "с", "п")
                self.assertEqual(post.vikaniya, [])

    def test_vratata_ne_otgovarya(self):
        def pada(*a):
            raise OSError("отказана връзка")
        post = Zapis(ollama_otg({}))
        with self.assertRaises(VrataGreshka) as k:
            Model(cfg(), vrata=Vrata("http://g", get=pada), post=post).chat("struktura", "с", "п")
        self.assertIsInstance(k.exception, VrataNeBezopasno)
        self.assertEqual(post.vikaniya, [])

    def test_nerazbiraem_kod_na_vratata(self):
        post = Zapis(ollama_otg({}))
        with self.assertRaises(VrataGreshka):
            Model(cfg(), vrata=Vrata("http://g", get=Zapis((404, ""))), post=post).chat("struktura", "с", "п")
        self.assertEqual(post.vikaniya, [])

    def test_bez_gate_url_nikakvo_vikane(self):
        for url in (None, ""):
            with self.subTest(url):
                c = cfg()
                c["gate_url"] = url
                post = Zapis(ollama_otg({}))
                with self.assertRaises(VrataLipsva) as k:
                    Model(c, post=post).chat("struktura", "с", "п")
                self.assertIsInstance(k.exception, VrataNeBezopasno)
                self.assertEqual(post.vikaniya, [])

    def test_vratata_se_pita_predi_vsyako_vikane(self):
        get = Zapis((200, "ok"))
        m = FalshivModelSVrata(Vrata("http://g", get=get))
        ocenka(primer(1), cfg(), model=m)
        self.assertEqual(get.vikaniya.__len__(), len(m.vikaniya))
        self.assertEqual(len(m.vikaniya), 6)  # 4 оси + похвати + синтез

    def test_busy_po_sredata_spira_vsichko(self):
        get = Zapis((200, "ok"), (200, "ok"), (200, "busy"))
        m = FalshivModelSVrata(Vrata("http://g", get=get))
        with self.assertRaises(VrataZaeta):
            ocenka(primer(1), cfg(), model=m)
        self.assertEqual(len(m.vikaniya), 2)

    def test_think_nepodderzhan_opit_bez_nego(self):
        post = Zapis((400, '{"error": "model does not support thinking"}'), ollama_otg({"ok": 1}))
        self.assertEqual(Model(cfg(), vrata=otvorena(), post=post).chat("pisach", "с", "п"), {"ok": 1})
        self.assertIn("think", post.vikaniya[0][1])
        self.assertNotIn("think", post.vikaniya[1][1])

    def test_ollama_greshka(self):
        with self.assertRaises(GreshkaModel):
            Model(cfg(), vrata=otvorena(), post=Zapis((500, "x"))).chat("pisach", "с", "п")

    def test_json_v_ograzhdane(self):
        post = Zapis((200, json.dumps({"message": {"content": 'Ето:\n```json\n{"ocenka": 3}\n```'}})))
        self.assertEqual(Model(cfg(), vrata=otvorena(), post=post).chat("pisach", "с", "п"), {"ocenka": 3})


class FalshivModelSVrata(FalshivModel):
    def __init__(self, vrata, **kw):
        super().__init__(**kw)
        self.vrata = vrata

    def chat(self, *a):
        self.vrata.proveri()
        return super().chat(*a)


class TestPalenPat(unittest.TestCase):
    def test_sedem_osi_i_sintez(self):
        m = FalshivModel(
            osi={"proverimost": (8, "Повечето твърдения имат източник."), "palnota": (9.5, "Пълен.")},
            pohvati=[{"kluch": "loaded_language", "otkas": "истински крах", "obyasnenie": "Силни думи."}])
        rez = ocenka(primer(1), cfg(), model=m, iztochnik="example.org")
        self.assertEqual(rez["rezhim"], "model")
        self.assertEqual(len(rez["osi"]), 7)
        po_kluch = {o["kluch"]: o for o in rez["osi"]}
        self.assertEqual(po_kluch["proverimost"]["ocenka"], 8.0)
        self.assertEqual(po_kluch["proverimost"]["izvor"], "модел")
        self.assertEqual(po_kluch["reputaciya"]["izvor"], "регистър")
        self.assertIn("loaded_language", {p["kluch"] for p in rez["pohvati"]})
        self.assertEqual(rez["neprovereni_pohvati"], [])
        self.assertEqual(rez["sintez"]["za_chitatelya"], "Текстът е прегледан.")
        self.assertEqual([r for r, _, _ in m.vikaniya].count("pisach"), 1)
        self.assertIn(rez["reshenie"]["kod"], ("PROPUSNI", "PREDUPREDI", "KARANTINA"))

    def test_losh_json_za_os_vrashta_evristika(self):
        m = FalshivModel(surovo={"palnota": '{"nyama": 1}'})
        rez = ocenka(primer(2), cfg(), model=m)
        po_kluch = {o["kluch"]: o for o in rez["osi"]}
        self.assertEqual(po_kluch["palnota"]["izvor"], "евристика")
        self.assertTrue(any("Контекстна пълнота" in b for b in rez["belezhki"]))

    def test_ocenkata_se_ogranichava(self):
        rez = ocenka(primer(2), cfg(), model=FalshivModel(osi={"proverimost": (42, "Много.")}))
        self.assertEqual(rez["osi"][1]["ocenka"], 10.0)

    def test_nikoga_lazha(self):
        m = FalshivModel(
            osi={"prozrachnost": (1, "Това е фалшива новина.")},
            sintez={"za_chitatelya": "Статията е лъжа.", "silni": [], "slabi": ["Фейк."], "preporaka": "Не вярвайте."})
        rez = ocenka(primer(1), cfg(), model=m)
        izhod = json.dumps(rez, ensure_ascii=False)
        self.assertIsNone(re.search(r"лъж|фалшив\w*\s+новин|фейк", izhod, re.IGNORECASE))
        # и в промптите към модела
        for _, s, p in m.vikaniya:
            self.assertIsNone(re.search(r"лъж|фалшив\w*\s+новин", s + p.replace(primer(1), ""), re.IGNORECASE))

    def test_bez_model_nikoga_lazha(self):
        for n in (1, 2, 3):
            izhod = json.dumps(ocenka(primer(n), cfg()), ensure_ascii=False)
            self.assertIsNone(re.search(r"лъж|фалшив\w*\s+новин|фейк", izhod, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
