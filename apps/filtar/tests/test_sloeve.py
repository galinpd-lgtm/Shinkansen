"""Седемте слоя: по поне един тест на слой, пълният ход с фалшив модел и спиране на вратата."""
import json
import unittest
from datetime import timedelta
from unittest import mock

from obshto import IZVORI, SEGA, FalshivaMrezha, FalshivModel, Otvorena, Papka, cfg, dcfg

from filtar import baza, config, sabirach, sloeve
from filtar.dov import VrataNeBezopasno
from filtar.vreden import Klasifikator
import doverie.vrata as dvrata

ORGS = config.cheti_json("organizacii.example.json")
DYLAG = ("Община Примерово обяви нова програма за подкрепа на малки фирми, съобщи Николай Примеров, кмет на Примерово. "
         + " ".join("Изречение номер %d описва подробност по програмата за фирмите в града според решение № %d." % (i, 100 + i)
                    for i in range(12)))


def vkarai(b, tekst=DYLAG, url="https://example.org/a", izvor="primer-tehno", vid="medija", ezik="bg",
           zaglavie="Заглавие", status=200, tip="rss", data="2026-10-05T07:00:00+03:00"):
    cur = b.execute("INSERT INTO zapisi (izvor, izvor_ime, izvor_vid, ezik, kluch, url, url_kanon, url_hash, zaglavie, "
                    "tekst, data, sabrano, http_status, tip) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (izvor, "Примерен източник", vid, ezik, "%s|%s|%s" % (izvor, url, tekst[:20]), url,
                     sabirach.kanon(url), sabirach.url_hash(url), zaglavie, tekst, data, SEGA.isoformat(), status, tip))
    b.commit()
    return cur.lastrowid


def reshenie(b, zid):
    return b.execute("SELECT reshenie, sloy, prichina FROM zapisi WHERE id=?", (zid,)).fetchone()


def filtr(p, **kw):
    return sloeve.filtriray(p.b, cfg(), dcfg(), SEGA, organizacii=ORGS, **kw)


class TestSloy1(unittest.TestCase):
    def test_tehnicheska(self):
        with Papka() as p:
            a = vkarai(p.b, url="javascript:void(0)")
            b_ = vkarai(p.b, url="https://example.org/b", status=500)
            c = vkarai(p.b, url="https://example.org/c", tip="application/pdf")
            d = vkarai(p.b, url="https://example.org/d", tekst="Кратко.")
            e = vkarai(p.b, url="https://example.org/e")
            filtr(p)
            for zid, duma in ((a, "невалиден адрес"), (b_, "500"), (c, "тип"), (d, "100 знака")):
                r = reshenie(p.b, zid)
                self.assertEqual((r["reshenie"], r["sloy"]), ("ОТКАЗ", 1))
                self.assertIn(duma, r["prichina"])
            self.assertNotEqual(reshenie(p.b, e)["sloy"], 1)


class TestSloy2(unittest.TestCase):
    def test_sash_adres_pazi_parviya(self):
        with Papka() as p:
            a = vkarai(p.b, url="https://example.org/x")
            b_ = vkarai(p.b, url="https://example.org/x?utm_source=feed#top", izvor="primer-obshtnost",
                        tekst=DYLAG + " Друг край.")
            filtr(p)
            self.assertNotEqual(reshenie(p.b, a)["reshenie"], "ПРОПУСНАТ")
            r = reshenie(p.b, b_)
            self.assertEqual((r["reshenie"], r["sloy"]), ("ПРОПУСНАТ", 2))
            self.assertIn("запис %d" % a, r["prichina"])

    def test_pochti_dublikat(self):
        with Papka() as p:
            a = vkarai(p.b, url="https://example.org/1")
            b_ = vkarai(p.b, url="https://example.org/2", tekst=DYLAG + " Край.")
            c = vkarai(p.b, url="https://example.org/3", tekst=DYLAG.replace("Изречение", "Абзац"))
            filtr(p)
            self.assertEqual(reshenie(p.b, b_)["reshenie"], "ПРОПУСНАТ")
            self.assertIn("почти", reshenie(p.b, b_)["prichina"])
            self.assertNotEqual(reshenie(p.b, c)["reshenie"], "ПРОПУСНАТ")
            self.assertNotEqual(reshenie(p.b, a)["reshenie"], "ПРОПУСНАТ")


class TestSloy3(unittest.TestCase):
    KRATAK = ("Община Примерово удължава срока за подаване на документи по поканата до петнадесети ноември. "
              "Промяната е по решение № 251 на общинския съвет. Документите се подават по електронен път. "
              "Въпроси се изпращат до отдел „Проекти“ до пети ноември.")

    def test_prag_na_dumite(self):
        with Papka() as p:
            medija = vkarai(p.b, tekst=self.KRATAK, url="https://example.org/m")
            oficialen = vkarai(p.b, tekst=self.KRATAK, url="https://example.org/o", izvor="primer-obshtina",
                               vid="oficialen")
            filtr(p)
            r = reshenie(p.b, medija)
            self.assertEqual((r["reshenie"], r["sloy"]), ("ОТКАЗ", 3))
            self.assertIn("под прага от 100", r["prichina"])
            self.assertNotEqual(reshenie(p.b, oficialen)["sloy"], 3)

    def test_ezik(self):
        en = " ".join(["The example laboratory released a new model for many languages today."] * 12)
        with Papka() as p:
            bg = vkarai(p.b, tekst=en, url="https://example.org/bg")
            en_izvor = vkarai(p.b, tekst=en + " Extra.", url="https://example.org/en", ezik="en")
            filtr(p)
            self.assertIn("кирилица", reshenie(p.b, bg)["prichina"])
            self.assertNotEqual(reshenie(p.b, en_izvor)["sloy"], 3)

    def test_platena_stena_i_reklama(self):
        with Papka() as p:
            a = vkarai(p.b, tekst=DYLAG + " Само за абонати.", url="https://example.org/p")
            b_ = vkarai(p.b, tekst=DYLAG.replace("Изречение", "Точка"), url="https://example.org/r",
                        zaglavie="Спонсорирано: нова услуга")
            filtr(p)
            self.assertIn("платена стена", reshenie(p.b, a)["prichina"])
            self.assertIn("реклама", reshenie(p.b, b_)["prichina"])


class FalshivPost:
    def __init__(self, sadarzhanie, status=200):
        self.sadarzhanie, self.status, self.vikaniya = sadarzhanie, status, []

    def __call__(self, url, body, zaglavki, timeout):
        self.vikaniya.append((url, body, zaglavki))
        return self.status, json.dumps({"message": {"content": self.sadarzhanie}})


class TestKlasifikator(unittest.TestCase):
    def kl(self, sadarzhanie, **vcfg):
        v = dict(cfg()["sloy3"]["vreden"], **vcfg)
        post = FalshivPost(sadarzhanie)
        return Klasifikator(v, "http://g", post=post, vrata=Otvorena()), post

    def test_izklyuchen_po_podrazbirane(self):
        kl, _ = self.kl("{}")
        self.assertFalse(kl.vklyuchen)

    def test_opasno_karantina(self):
        with Papka() as p:
            kl, post = self.kl('{"opasno": true, "kategoriya": "насилие"}', rezhim="lokalen")
            zid = vkarai(p.b)
            filtr(p, klasifikator=kl)
            r = reshenie(p.b, zid)
            self.assertEqual((r["reshenie"], r["sloy"]), ("КАРАНТИНА", 3))
            self.assertIn("насилие", r["prichina"])
            self.assertEqual(post.vikaniya[0][0], "http://127.0.0.1:11435/api/chat")
            self.assertNotIn("Authorization", post.vikaniya[0][2])
            # записът не е изтрит — остава в архива
            self.assertEqual(p.b.execute("SELECT COUNT(*) FROM zapisi").fetchone()[0], 1)

    def test_unsafe_duma(self):
        kl, _ = self.kl("unsafe\nS1", rezhim="lokalen")
        self.assertEqual(kl.e_opasno("текст"), (True, ""))
        kl, _ = self.kl("safe", rezhim="lokalen")
        self.assertEqual(kl.e_opasno("текст"), (False, ""))

    def test_oblachen_s_kluch(self):
        kl, post = self.kl('{"opasno": false}', rezhim="oblachen", oblachen_url="https://oblak.example.org", kluch="k-test")
        self.assertEqual(kl.e_opasno("текст"), (False, ""))
        url, _, zagl = post.vikaniya[0]
        self.assertEqual(url, "https://oblak.example.org/api/chat")
        self.assertEqual(zagl["Authorization"], "Bearer k-test")

    def test_oblachen_bez_kluch_propuska(self):
        with Papka() as p:
            kl, post = self.kl('{"opasno": true}', rezhim="oblachen", oblachen_url="https://oblak.example.org", kluch="")
            zid = vkarai(p.b)
            filtr(p, klasifikator=kl)
            self.assertEqual(post.vikaniya, [])
            self.assertNotEqual(reshenie(p.b, zid)["sloy"], 3)
            red = p.b.execute("SELECT prichina FROM firewall_log WHERE zapis_id=? AND sloy=3", (zid,)).fetchone()
            self.assertIn("няма ключ", red["prichina"])

    def test_oblak_bez_vratata(self):
        v = dict(cfg()["sloy3"]["vreden"], rezhim="oblachen", oblachen_url="https://oblak.example.org", kluch="k")
        post = FalshivPost('{"opasno": false}')
        kl = Klasifikator(v, "http://g", post=post)
        self.assertIsNone(kl.vrata)
        with mock.patch.object(dvrata, "http_get", lambda *a: (200, "busy")):  # горещо — облакът пак работи
            self.assertEqual(kl.e_opasno("текст"), (False, ""))

    def test_oblak_dneven_tavan(self):
        with Papka() as p:
            v = dict(cfg()["sloy3"]["vreden"], rezhim="oblachen", oblachen_url="https://oblak.example.org",
                     kluch="k", dnevna_granica=2)
            post = FalshivPost('{"opasno": false}')
            kl = Klasifikator(v, None, post=post)
            ids = [vkarai(p.b, url="https://example.org/%d" % i, tekst=DYLAG.replace("Изречение", "Ред%d" % i))
                   for i in range(4)]
            filtr(p, klasifikator=kl)
            self.assertEqual(len(post.vikaniya), 2)
            for zid in ids:  # всички продължават нататък
                self.assertNotEqual(reshenie(p.b, zid)["sloy"], 3)
            red = p.b.execute("SELECT prichina FROM firewall_log WHERE zapis_id=? AND sloy=3", (ids[3],)).fetchone()
            self.assertIn("таван", red["prichina"])
            # на следващия ден таванът е нов
            post.vikaniya.clear()
            zid = vkarai(p.b, url="https://example.org/utre", tekst=DYLAG.replace("Изречение", "Утре"))
            sloeve.filtriray(p.b, cfg(), dcfg(), SEGA + timedelta(days=1), organizacii=ORGS, klasifikator=kl)
            self.assertEqual(len(post.vikaniya), 1)

    def test_oblak_greshka_ne_spira_statiyata(self):
        with Papka() as p:
            v = dict(cfg()["sloy3"]["vreden"], rezhim="oblachen", oblachen_url="https://oblak.example.org", kluch="k")
            kl = Klasifikator(v, None, post=FalshivPost("{}", status=429))
            zid = vkarai(p.b)
            filtr(p, klasifikator=kl)
            self.assertGreater(reshenie(p.b, zid)["sloy"], 3)  # статията продължи нататък
            red = p.b.execute("SELECT prichina FROM firewall_log WHERE zapis_id=? AND sloy=3", (zid,)).fetchone()
            self.assertIn("429", red["prichina"])

    def test_lokalen_zad_vratata(self):
        v = dict(cfg()["sloy3"]["vreden"], rezhim="lokalen")
        post = FalshivPost("{}")
        kl = Klasifikator(v, "http://g", post=post)
        self.assertIsNotNone(kl.vrata)
        with mock.patch.object(dvrata, "http_get", lambda *a: (200, "busy")):
            with self.assertRaises(VrataNeBezopasno):
                kl.e_opasno("текст")
        self.assertEqual(post.vikaniya, [])

    def test_vratata_spira(self):
        v = dict(cfg()["sloy3"]["vreden"], rezhim="lokalen")
        post = FalshivPost("{}")
        kl = Klasifikator(v, "http://g", post=post, vrata=Otvorena(["busy"]))
        with self.assertRaises(VrataNeBezopasno):
            kl.e_opasno("текст")
        self.assertEqual(post.vikaniya, [])


class TestSloy4i5(unittest.TestCase):
    ANONIMEN = ("Експерти смятат, че всичко ще се срине. Всички знаят това. Или ще действаме, или ще загубим. "
                "Опасността е огромна и заплахата расте. "
                + " ".join("Изречение номер %d описва още подробности за положението в града днес." % i for i in range(12)))

    def test_barza_ocenka_otkaz(self):
        with Papka() as p:
            zid = vkarai(p.b, tekst=self.ANONIMEN)  # неутрален източник (5.0), текстът сам дърпа надолу
            filtr(p)
            r = reshenie(p.b, zid)
            self.assertEqual((r["reshenie"], r["sloy"]), ("ОТКАЗ", 4))
            self.assertIn("бърза оценка", r["prichina"])

    def test_nisak_izvor_karantina_bez_model(self):
        with Papka() as p:
            baza.izvor(p.b, "slab", "Слаб", "medija")
            p.b.execute("UPDATE izvori SET rep_score=2.5, preizchislena=? WHERE id='slab'", (SEGA.isoformat(),))
            zid = vkarai(p.b, izvor="slab")
            m = FalshivModel()
            filtr(p, model=m)
            r = reshenie(p.b, zid)
            self.assertEqual((r["reshenie"], r["sloy"]), ("КАРАНТИНА", 5))
            self.assertEqual(m.vikaniya, [])  # за такъв източник моделът не се вика

    def test_vseki_zapochva_s_5(self):
        with Papka() as p:
            for izv in IZVORI:
                self.assertEqual(baza.izvor(p.b, izv["id"], izv["ime"], izv["vid"])["rep_score"], 5.0)

    def test_preizchislyavane(self):
        with Papka() as p:
            baza.izvor(p.b, "i", "И", "medija")
            for dni, oc in ((1, 9.0), (20, 3.0), (40, 0.0)):  # последният е извън 30-те дни
                p.b.execute("INSERT INTO zapisi (izvor, kluch, sastoyanie, ocenka, obraboteno) VALUES (?,?,?,?,?)",
                            ("i", "k%d" % dni, "obraboten", oc, (SEGA - timedelta(days=dni)).isoformat()))
            sloeve.preizchisli(p.b, cfg(), SEGA)
            # (2·9 + 1·3) / 3 = 7.0 — последните 7 дни тежат двойно
            self.assertEqual(p.b.execute("SELECT rep_score FROM izvori WHERE id='i'").fetchone()[0], 7.0)
            # седмица не е минала — не се преизчислява
            p.b.execute("UPDATE zapisi SET ocenka=0 WHERE izvor='i'")
            sloeve.preizchisli(p.b, cfg(), SEGA + timedelta(days=3))
            self.assertEqual(p.b.execute("SELECT rep_score FROM izvori WHERE id='i'").fetchone()[0], 7.0)
            sloeve.preizchisli(p.b, cfg(), SEGA + timedelta(days=8))
            self.assertEqual(p.b.execute("SELECT rep_score FROM izvori WHERE id='i'").fetchone()[0], 0.0)

    def test_bez_danni_ostava(self):
        with Papka() as p:
            baza.izvor(p.b, "i", "И", "medija")
            sloeve.preizchisli(p.b, cfg(), SEGA)
            self.assertEqual(p.b.execute("SELECT rep_score FROM izvori WHERE id='i'").fetchone()[0], 5.0)


class TestSloy6(unittest.TestCase):
    def z(self, tekst):
        return {"zaglavie": "", "tekst": tekst}

    def test_rubriki(self):
        c = cfg()
        self.assertEqual(sloeve.obogati(self.z("Нов езиков модел с API и токени."), c, [])[0], 1)
        self.assertEqual(sloeve.obogati(self.z("Изискванията на AI Act и GDPR."), c, [])[0], 5)
        self.assertEqual(sloeve.obogati(self.z("Безплатно обучение и уебинар."), c, [])[0], 3)
        self.assertEqual(sloeve.obogati(self.z("Покана за финансиране, срок за кандидатстване."), c, [])[0], 4)
        self.assertEqual(sloeve.obogati(self.z("Нова версия с рендер и 3D моделиране."), c, [])[0], 2)
        self.assertEqual(sloeve.obogati(self.z("Общинският съвет във Варна."), c, [])[0], 6)
        self.assertIsNone(sloeve.obogati(self.z("Времето утре е слънчево."), c, [])[0])

    def test_ai_ne_sa_malki_bukvi(self):
        self.assertIsNone(sloeve.obogati(self.z("Май ai не е дума тук."), cfg(), [])[0])

    def test_organizacii_i_temi(self):
        rub, orgs, temi = sloeve.obogati(self.z("ПАИ и Община Примерово обявиха обучение и уебинар."), cfg(), ORGS)
        self.assertEqual(set(orgs), {"Примерна агенция за иновации", "Община Примерово"})
        self.assertIn("уебинар", temi)
        self.assertLessEqual(len(temi), 5)


class TestPalenHod(unittest.TestCase):
    def test_s_model(self):
        with Papka() as p:
            sabirach.sabiray(p.b, cfg(), IZVORI, SEGA, get=FalshivaMrezha())
            m = FalshivModel()
            o = filtr(p, model=m)
            self.assertGreater(len(m.vikaniya), 0)
            self.assertEqual(p.b.execute("SELECT COUNT(*) FROM zapisi WHERE sastoyanie='nov'").fetchone()[0], 0)
            self.assertEqual(sum(o.values()), 30)
            z = p.b.execute("SELECT doverie FROM zapisi WHERE reshenie='ПРОПУСНИ' LIMIT 1").fetchone()
            self.assertEqual(json.loads(z["doverie"])["rezhim"], "model")

    def test_vratata_spira_i_prodalzhava(self):
        with Papka() as p:
            sabirach.sabiray(p.b, cfg(), IZVORI, SEGA, get=FalshivaMrezha())
            vrata = Otvorena(["ok"] * 12 + ["busy"])
            with self.assertRaises(VrataNeBezopasno):
                filtr(p, model=FalshivModel(vrata=vrata))
            p.b.rollback()
            novi = p.b.execute("SELECT COUNT(*) FROM zapisi WHERE sastoyanie='nov'").fetchone()[0]
            self.assertGreater(novi, 0)
            self.assertLess(novi, 30)
            # нищо не е загубено: следващото пускане довършва
            filtr(p, model=FalshivModel())
            self.assertEqual(p.b.execute("SELECT COUNT(*) FROM zapisi WHERE sastoyanie='nov'").fetchone()[0], 0)
            # и никой запис няма два крайни реда
            dvoyni = p.b.execute("SELECT zapis_id FROM firewall_log WHERE sloy BETWEEN 1 AND 6 AND reshenie<>'ПРЕДУПРЕДИ' "
                                 "GROUP BY zapis_id HAVING COUNT(*)>1").fetchall()
            self.assertEqual(dvoyni, [])

    def test_vseki_ima_red_v_dnevnika(self):
        with Papka() as p:
            sabirach.sabiray(p.b, cfg(), IZVORI, SEGA, get=FalshivaMrezha(), vhod=p.vhod)
            filtr(p)
            for z in p.b.execute("SELECT id, reshenie, prichina FROM zapisi"):
                red = p.b.execute("SELECT * FROM firewall_log WHERE zapis_id=? AND sloy>0 AND reshenie=?",
                                  (z["id"], z["reshenie"])).fetchone()
                self.assertIsNotNone(red, z["id"])
                self.assertTrue(red["prichina"])


if __name__ == "__main__":
    unittest.main()
