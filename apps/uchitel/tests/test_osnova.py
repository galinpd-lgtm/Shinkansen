"""Основата: точните места в разбора, прилагането на поправки, сравнението за цялост и шрифтовете в CSS."""
import unittest

from obshto import ZNAK, kanon, procheti

from uchitel import celost, popravki
from uchitel.dom import razbor


class TestDom(unittest.TestCase):
    def test_mestata_sa_tochni(self):
        html = '﻿<html>\r\n<body>\r\n  <p class="a">Здравей &amp; <b>свят</b></p><img src=x>\r\n</body></html>'
        doc = razbor(html)
        p = doc.parvi("p")
        self.assertEqual(html[p.start:p.otv_kraj], '<p class="a">')
        self.assertEqual(html[p.otv_kraj:p.zatv], "Здравей &amp; <b>свят</b>")
        self.assertEqual(html[p.zatv:p.kraj], "</p>")
        img = doc.parvi("img")
        self.assertEqual(html[img.start:img.kraj], "<img src=x>")
        self.assertTrue(p.zdrav())

    def test_nezatvoren_i_visyasht(self):
        doc = razbor("<div><span>а<b>б</span></div></i>")
        self.assertFalse(doc.parvi("span").zdrav())
        self.assertEqual([t for t, _ in doc.visyashti], ["i"])

    def test_crlf_i_bom_ostavat(self):
        rel = "gx10/GX_01_Laboratoriya.html"
        html = "﻿" + procheti(rel).replace("\n", "\r\n")
        p = popravki.popravi(html, kanon(), rel, ZNAK)
        self.assertEqual(p.blokirano, [])
        self.assertTrue(p.novo.startswith("﻿<!DOCTYPE html>\r\n"))
        self.assertEqual(p.novo.count("\n"), p.novo.count("\r\n"))


class TestPrilozhi(unittest.TestCase):
    def test_vmakvania_i_vlozheni(self):
        html = "0123456789"
        # парчето 4–6 е изцяло в 2–8 → отпада; двете вмъквания на 9 остават в реда си
        self.assertEqual(popravki.prilozhi(html, [(2, 8, "X"), (4, 6, "Y"), (9, 9, "a"), (9, 9, "b")]), "01X8ab9")

    def test_zastapvane_e_greshka(self):
        with self.assertRaises(ValueError):
            popravki.prilozhi("0123456789", [(2, 6, "X"), (4, 8, "Y")])


class TestCelost(unittest.TestCase):
    def setUp(self):
        self.k = kanon()
        self.html = procheti("n8n/N8_01_Parvi_potok.html")

    def test_etiketite_sa_razresheni(self):
        novo = self.html.replace(">HUMAN<", '><span class="bg-only">Човек</span><span class="en-only">HUMAN</span><')
        self.assertEqual(celost.sravni(self.html, novo, self.k), [])

    def test_logoto_e_razresheno(self):
        novo = self.html.replace("n8n Академия", "съвсем друго")
        self.assertEqual(celost.sravni(self.html, novo, self.k), [])

    def test_hvashta_promeni_v_sadarzhanieto(self):
        for staro, novo, ochakvano in (
                ("Всеки workflow", "Всеки поток", "текстът се различава"),
                ('<a href="#s2">', '<a>', "връзки: "),
                ('<pre><code>npx', '<div><code>npx', "код: "),
                ("setLang(l){", "setLang(x){", "скриптовете"),
                ("<title>N8-01", "<title>N8-02", "<title>")):
            r = celost.sravni(self.html, self.html.replace(staro, novo, 1), self.k)
            self.assertTrue(any(ochakvano in x for x in r), (staro, r))


class TestShriftoveVCss(unittest.TestCase):
    def test_font_face_ne_se_pipa(self):
        html = procheti("gx10/GX_01_Laboratoriya.html").replace(
            "</style>", "@font-face{font-family:'Inter';src:url(inter.woff2)}\n.x{font-family:Inter,sans-serif}\n</style>", 1)
        p = popravki.popravi(html, kanon(), "gx10/x.html", ZNAK)
        self.assertEqual(p.blokirano, [])
        self.assertIn("@font-face{font-family:'Inter';src:url(inter.woff2)}", p.novo)
        self.assertIn(".x{font-family:Sora,sans-serif}", p.novo)

    def test_bez_vrazka_se_dobavya_edna(self):
        html = procheti("gx10/GX_01_Laboratoriya.html")
        start = html.index('<link href="https://fonts.googleapis.com')
        html = html[:start] + html[html.index(">", start) + 1:]
        p = popravki.popravi(html, kanon(), "gx10/x.html", ZNAK)
        self.assertEqual(p.novo.count("fonts.googleapis.com"), 1)


if __name__ == "__main__":
    unittest.main()
