"""Проверката: всеки пример срещу всяко правило, името на курса от всеки вид лого, изтичане и чист български."""
import json
import os
import unittest

from obshto import KANON_PAT, PRIMERI, VremennaPapka, kanon, procheti, pusni

from uchitel import analiz, obhod, pravila
from uchitel.dom import razbor


def zapis(rel, k=None, koren=PRIMERI):
    return obhod.obraboti(os.path.join(koren, rel), rel, k or kanon())


def status(z, pravilo):
    return z.rezultat(pravilo).status


class TestLogo(unittest.TestCase):
    def ime(self, rel):
        k = kanon()
        doc = razbor(procheti(rel))
        plan = analiz.plan_logo(doc, k, rel)
        return plan[2] if plan[0] in ("смени", "добави") else plan

    def test_imeto_ot_vseki_vid_logo(self):
        self.assertEqual(self.ime("gx10/GX_01_Laboratoriya.html"), "GX10 Хъб · Лаборатория")        # ⬡ KAGAMI …
        self.assertEqual(self.ime("ai_arhitekt/AA_01_Rolite.html"), "AI Архитект Академия")          # 🧠 …
        self.assertEqual(self.ime("n8n/N8_01_Parvi_potok.html"), "n8n")                              # logo.imena
        self.assertEqual(self.ime("devstation/DS_01_Start.html"), "DevStation")                      # logo.imena
        self.assertEqual(self.ime("kagami_way/KW_01_Uvod.html"), "KAGAMI Way")                       # SVG + zapazeni_imena

    def test_bez_logo_e_za_rachno(self):
        z = zapis("bez_logo/BL_01_Index.html")
        self.assertEqual(status(z, "лого"), pravila.NARUSHENIE)
        self.assertIn("logo.ime_po_papka", z.rezultat("лого").za_rachno[0])
        self.assertEqual(z.status, obhod.ZA_RACHNO)

    def test_bez_logo_s_ime_po_papka_e_popravimo(self):
        k = kanon()
        k["logo"]["ime_po_papka"] = {"bez_logo": "Съдържание"}
        z = zapis("bez_logo/BL_01_Index.html", k)
        self.assertEqual(z.rezultat("лого").za_rachno, [])
        self.assertIn("Съдържание", z.rezultat("лого").popravimo[0])

    def test_schupenoto_e_za_rachno(self):
        z = zapis("schupeno/SC_01_Schupeno.html")
        self.assertIn("счупен", z.rezultat("лого").za_rachno[0])
        self.assertEqual(z.status, obhod.ZA_RACHNO)

    def test_samo_emodzhi_i_kagami_nyama_ime(self):
        html = procheti("gx10/GX_01_Laboratoriya.html").replace("⬡ KAGAMI GX10 Хъб · Лаборатория", "⬡ KAGAMI")
        doc = razbor(html)
        plan = analiz.plan_logo(doc, kanon(), "gx10/x.html")
        self.assertEqual(plan[0], "ръчно")
        self.assertIn("няма име", plan[1])

    def test_tvarde_dalgo_ime_ne_se_gadae(self):
        html = procheti("n8n/N8_01_Parvi_potok.html").replace("n8n Академия", "Много дълго описание " * 5)
        plan = analiz.plan_logo(razbor(html), kanon(), "n8n/x.html")
        self.assertEqual(plan[0], "ръчно")

    def test_vrazka_v_logoto_e_za_rachno(self):
        html = procheti("n8n/N8_01_Parvi_potok.html").replace(
            '<span class="brand">n8n Академия</span>', '<span class="brand"><a href="/">n8n Академия</a></span>')
        plan = analiz.plan_logo(razbor(html), kanon(), "n8n/x.html")
        self.assertEqual(plan[0], "ръчно")
        self.assertIn("връзка", plan[1])

    def test_dvuezichno_ime_vzima_balgarskoto(self):
        html = procheti("n8n/N8_01_Parvi_potok.html").replace(
            '<span class="brand">n8n Академия</span>',
            '<span class="brand">⬡ KAGAMI <span class="bg-only">Лаборатория</span><span class="en-only">Lab</span></span>')
        plan = analiz.plan_logo(razbor(html), kanon(), "n8n/x.html")
        self.assertEqual((plan[2], plan[4]), ("Лаборатория", "Lab"))   # английското се пази за EN изгледа

    def test_bez_angliyski_variant_nyama_en(self):
        self.assertIsNone(analiz.plan_logo(razbor(procheti("gx10/GX_01_Laboratoriya.html")), kanon(), "gx10/x.html")[4])
        html = procheti("n8n/N8_01_Parvi_potok.html").replace(
            '<span class="brand">n8n Академия</span>',
            '<span class="brand"><span class="bg-only">⬡ KAGAMI Лаборатория</span><span class="en-only">⬡ KAGAMI</span></span>')
        plan = analiz.plan_logo(razbor(html), kanon(), "n8n/x.html")
        self.assertEqual((plan[2], plan[4]), ("Лаборатория", None))   # в EN частта няма име → българското и в двата

    def test_ednakvo_ime_ne_se_udvoyava(self):
        html = procheti("n8n/N8_01_Parvi_potok.html").replace(
            '<span class="brand">n8n Академия</span>',
            '<span class="brand">KAGAMI <span class="bg-only">GX10</span><span class="en-only">GX10</span></span>')
        self.assertIsNone(analiz.plan_logo(razbor(html), kanon(), "n8n/x.html")[4])


class TestPravila(unittest.TestCase):
    def test_shriftove(self):
        z = zapis("kagami_way/KW_01_Uvod.html")
        self.assertIn("DM Serif Display, Plus Jakarta Sans → Sora", " ".join(z.rezultat("шрифтове").popravimo))
        z = zapis("ai_arhitekt/AA_01_Rolite.html")
        self.assertIn("2 връзки към Google Fonts — остава една", z.rezultat("шрифтове").popravimo)

    def test_nepoznat_shrift_e_za_rachno(self):
        html = procheti("gx10/GX_01_Laboratoriya.html").replace("font-family:'Sora',sans-serif",
                                                                "font-family:'Comic Sans MS',sans-serif")
        r = pravila.shriftove(razbor(html), kanon())
        self.assertIn("Comic Sans MS", r.za_rachno[0])

    def test_izgledi(self):
        z = zapis("n8n/N8_01_Parvi_potok.html")
        r = z.rezultat("изгледи")
        self.assertTrue(any("само на английски" in b for b in r.za_rachno))
        self.assertTrue(any("HUMAN×1" in b for b in r.popravimo))
        html = procheti("gx10/GX_01_Laboratoriya.html").replace("setLang('en')", "noop()")
        self.assertIn("няма превключвател БГ/EN", pravila.izgledi(razbor(html), kanon()).za_rachno)

    def test_tamna_tema(self):
        self.assertEqual(status(zapis("devstation/DS_01_Start.html"), "тъмна тема"), pravila.NARUSHENIE)
        self.assertEqual(status(zapis("gx10/GX_01_Laboratoriya.html"), "тъмна тема"), pravila.OK)

    def test_chist_balgarski(self):
        r = zapis("n8n/N8_01_Parvi_potok.html").rezultat("чист български")
        self.assertEqual(r.status, pravila.NARUSHENIE)
        self.assertIn("workflow", r.za_rachno[0])
        self.assertIn("Execute", r.za_rachno[0])
        self.assertNotIn("n8n", r.za_rachno[0])      # изключение от канона
        self.assertNotIn("HUMAN", r.za_rachno[0])    # етикетите са в правило 3
        self.assertNotIn("npx", r.za_rachno[0])      # кодът не е БГ изглед
        self.assertEqual(status(zapis("gx10/GX_01_Laboratoriya.html"), "чист български"), pravila.OK)

    def test_samo_angliyska_stranica_ne_se_prilaga(self):
        html = "<html><head><title>x</title></head><body><p>Only English here</p></body></html>"
        self.assertEqual(pravila.chist_balgarski(razbor(html), kanon()).status, pravila.NE_SE_PRILAGA)

    def test_celost_ne_se_prilaga_pri_proverka(self):
        self.assertEqual(status(zapis("gx10/GX_01_Laboratoriya.html"), "цялост"), pravila.NE_SE_PRILAGA)


class TestIztichane(unittest.TestCase):
    # Адресите се сглобяват тук, за да няма нито един в репото (филтърът за изтичане ги търси и в историята).
    IP_TS = ".".join(["100", "101", "7", "12"])
    IP_LAN = ".".join(["192", "168", "1", "20"])
    POSHTA = "ivan" + "@" + "firma-primer.bg"
    TELEFON = "+359 " + "88 123 4567"
    PAT = "C:" + "\\" + "Users" + "\\" + "ivan" + "\\" + "Desktop"
    PAROLA = "парола" + ": " + "Tayna-" + "12345"

    def test_namira_vsichko_i_ne_go_pokazva(self):
        k = kanon()
        k["iztichane"]["zabraneni_dumi"] = ["Проект-Х"]
        html = procheti("gx10/GX_01_Laboratoriya.html").replace(
            "Една машина, два модела",
            "Машината е на %s и %s. Пиши на %s или %s. Файлът е в %s. %s. Това е Проект-Х." % (
                self.IP_TS, self.IP_LAN, self.POSHTA, self.TELEFON, self.PAT, self.PAROLA))
        r = pravila.iztichane(razbor(html), k)
        vidove = " ".join(r.za_rachno)
        for vid in ("IP", "e-mail", "телефон", "път", "парола", "забранена дума"):
            self.assertIn(vid, vidove)
        self.assertEqual(sum(1 for b in r.za_rachno if " IP " in b), 2)
        for tayna in (self.IP_TS, self.IP_LAN, self.POSHTA, self.PAROLA, "Tayna-12345"):
            self.assertNotIn(tayna, vidove)   # отчетът показва само началото
        self.assertEqual(r.popravimo, [])     # изтичането никога не се поправя

    def test_pozvoleni_i_obshtestveni_adresi_ne_sa_iztichane(self):
        html = "<p>primer@example.com · 203.0.113.5 · 127.0.0.1 · /home/user</p>"
        self.assertEqual(pravila.iztichane(razbor(html), kanon()).status, pravila.OK)

    def test_iztichaneto_ne_spira_popravkata(self):
        with VremennaPapka() as v:
            rel = "gx10/GX_01_Laboratoriya.html"
            v.pishi(rel, procheti(rel).replace("Една машина", "Машината е на %s. Една машина" % self.IP_TS))
            kod, _out, _err = pusni("prebrandirai", v.vhod, "--izhod", v.pat("izh"), "--go")
            self.assertEqual(kod, 4)
            nov = procheti(rel, v.pat("izh"))
            self.assertIn("kg-logo", nov)
            self.assertIn(self.IP_TS, nov)   # само се казва, не се пипа
            with open(v.pat("izh.otchet", "za_rachno.csv"), encoding="utf-8-sig") as f:
                redove = f.read()
            self.assertIn("изтичане", redove)
            self.assertNotIn(self.IP_TS, redove)


class TestKomanda(unittest.TestCase):
    def test_tekst_i_kod(self):
        kod, out, _err = pusni("proveri", PRIMERI)
        self.assertEqual(kod, 4)
        for p in pravila.PRAVILA:
            self.assertIn(p + ":", out)
        self.assertIn("schupeno/SC_01_Schupeno.html  [за ръчно]", out)

    def test_json(self):
        kod, out, _err = pusni("proveri", PRIMERI, "--format", "json")
        d = {x["fail"]: x for x in json.loads(out)}
        self.assertEqual(len([x for x in d.values() if x["pravila"]]), 7)
        self.assertEqual(d["gx10/img/shema.svg"]["sastoyanie"], obhod.NE_E_HTML)
        self.assertEqual(len(d["gx10/GX_01_Laboratoriya.html"]["pravila"]), len(pravila.PRAVILA))

    def test_nyama_papka(self):
        kod, _out, err = pusni("proveri", os.path.join(PRIMERI, "nyama"))
        self.assertEqual(kod, 2)
        self.assertIn("няма такава папка", err)

    def test_izklyuchena_papka(self):
        with VremennaPapka() as v:
            k_pat = v.pat("kanon.json")
            with open(KANON_PAT, encoding="utf-8") as f:
                k = json.load(f)
            k["izklyuchi"] = ["schupeno"]
            k["logo"]["znak"] = os.path.join(os.path.dirname(PRIMERI), "znak_primer.png")
            with open(k_pat, "w", encoding="utf-8") as f:
                json.dump(k, f, ensure_ascii=False)
            _kod, out, _err = pusni("proveri", v.vhod, "--config", k_pat, "--format", "json")
            d = {x["fail"]: x for x in json.loads(out)}
            self.assertEqual(d["schupeno/SC_01_Schupeno.html"]["sastoyanie"], obhod.IZKLYUCHEN)
            self.assertEqual(d["schupeno/SC_01_Schupeno.html"]["pravila"], [])


if __name__ == "__main__":
    unittest.main()
