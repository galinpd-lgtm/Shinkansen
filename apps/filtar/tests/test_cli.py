"""Командите през main(): sabiray → filtriray → chernova → odobri → izdanie → statistika, кодове 0/4/1, дневник."""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from obshto import APP, IZVORI, SEGA, FalshivaMrezha, Papka, pishi_json

from filtar import cli, sabirach
import doverie.vrata as dvrata

CFG = os.path.join(APP, "config.example.json")


def bez_mrezha(*a, **kw):
    raise AssertionError("истинска мрежа в тест")


class Hod:
    def __init__(self, p):
        self.p = p
        self.izvori = os.path.join(p.d, "izvori.json")
        pishi_json(self.izvori, IZVORI)

    sega = SEGA

    def __call__(self, *argv, env=None, mrezha=None):
        out, err = io.StringIO(), io.StringIO()
        obshti = ["--config", CFG, "--danni", self.p.danni, "--sega", self.sega.isoformat()]
        argv = [argv[0]] + obshti + list(argv[1:])
        with mock.patch.object(sabirach, "http_get", mrezha or FalshivaMrezha()), \
                mock.patch.dict(os.environ, env or {}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            kod = cli.main(argv)
        return kod, out.getvalue(), err.getvalue()


@mock.patch.object(dvrata, "http_get", bez_mrezha)
class TestKomandi(unittest.TestCase):
    def setUp(self):
        for k in ("SHINKANSEN_RUNS", "SHINKANSEN_SUMMARY_FILE"):
            os.environ.pop(k, None)

    def test_celiyat_pat(self):
        with Papka() as p:
            h = Hod(p)
            kod, out, _ = h("sabiray", "--izvori", h.izvori, "--vhod", p.vhod)
            self.assertEqual(kod, 0, out)
            self.assertIn("Нови записи: 31", out)
            kod, out, _ = h("filtriray", "--bez-model")
            self.assertEqual(kod, 0)
            self.assertIn("ОТКАЗ", out)
            kod, out, _ = h("chernova", "--data", "2026-10-05", "--bez-model")
            self.assertEqual(kod, 0)
            self.assertIn("без текстове", out)
            kod, out, _ = h("odobri", "--data", "2026-10-05", "--mahni", "2")
            self.assertEqual(kod, 0)
            self.assertIn("Нищо не е записано", out)
            self.assertFalse(os.path.exists(os.path.join(p.danni, "odobreno_2026-10-05.json")))
            kod, out, _ = h("odobri", "--data", "2026-10-05", "--mahni", "2", "--go")
            self.assertEqual(kod, 0)
            self.assertTrue(os.path.exists(os.path.join(p.danni, "odobreno_2026-10-05.json")))
            izhod = os.path.join(p.d, "izhod", "radar")
            kod, out, _ = h("izdanie", "--izhod", izhod, "--dnes", "2026-10-05")
            self.assertEqual(kod, 0)
            for f in ("radar.json", "rss.xml", os.path.join("po-den", "2026-10-05.json")):
                self.assertTrue(os.path.exists(os.path.join(izhod, f)), f)
            kod, out, _ = h("statistika")
            self.assertEqual(kod, 0)
            self.assertIn("слой 3", out)
            kod, out, _ = h("statistika", "--json")
            self.assertIn("po_sloy", json.loads(out))

    def test_sabiray_chastichno_0_vsichko_1(self):
        with Papka() as p:
            h = Hod(p)
            mrezha = FalshivaMrezha({"https://example.net/blog/feed": (500, "", None, {}, b"")})
            kod, out, err = h("sabiray", "--izvori", h.izvori, mrezha=mrezha)
            self.assertEqual(kod, 0)  # поне един е събран; 4 е само за „заето/горещо“
            self.assertIn("предупреждение: не отговориха 1 от 3", err)
            self.assertIn("primer-obshtnost", err)
            red = p.b.execute("SELECT * FROM firewall_log WHERE reshenie='НЕ ОТГОВАРЯ'").fetchone()
            self.assertEqual(red["izvor"], "primer-obshtnost")
            self.assertIn("500", red["prichina"])
        with Papka() as p:
            h = Hod(p)
            mrezha = FalshivaMrezha({u["url"]: (500, "", None, {}, b"") for u in IZVORI})
            kod, _, _ = h("sabiray", "--izvori", h.izvori, mrezha=mrezha)
            self.assertEqual(kod, 1)

    def test_ne_otgovarya_3_dni(self):
        from datetime import timedelta
        with Papka() as p:
            h = Hod(p)
            pada = FalshivaMrezha({"https://example.net/blog/feed": (500, "", None, {}, b"")})
            for chasa in (0, 30, 60):  # три опита за 2.5 дни
                h.sega = SEGA + timedelta(hours=chasa)
                h("sabiray", "--izvori", h.izvori, mrezha=pada)
            _, out, _ = h("statistika")
            self.assertNotIn("⚠ НЕ ОТГОВАРЯ", out)  # още няма 3 дни
            h.sega = SEGA + timedelta(days=3)
            h("sabiray", "--izvori", h.izvori, mrezha=pada)
            _, out, _ = h("statistika")
            self.assertIn("⚠ НЕ ОТГОВАРЯ", out)
            self.assertIn("primer-obshtnost", out.split("Не отговарят")[1])
            # не е изключен сам: пита се и при следващия ход, и щом отговори — знакът изчезва
            h.sega = SEGA + timedelta(days=3, hours=1)
            kod, izh, _ = h("sabiray", "--izvori", h.izvori)
            self.assertIn("primer-obshtnost", izh)
            _, out, _ = h("statistika")
            self.assertNotIn("⚠ НЕ ОТГОВАРЯ", out)

    def test_otkazano_izvlichane_ne_e_greshka(self):
        with Papka() as p:
            h = Hod(p)
            mrezha = FalshivaMrezha({"https://example.net/robots.txt": (200, "text/plain", "utf-8", {},
                                                                         b"User-agent: *\nDisallow: /\n")})
            kod, out, _ = h("sabiray", "--izvori", h.izvori, mrezha=mrezha)
            self.assertEqual(kod, 0)
            self.assertIn("отказано извличане", out)

    def test_filtriray_vratata_4_nishto_ne_se_gubi(self):
        with Papka() as p:
            h = Hod(p)
            h("sabiray", "--izvori", h.izvori)
            with mock.patch.object(dvrata, "http_get", lambda *a: (200, "busy")):
                kod, _, err = h("filtriray")
            self.assertEqual(kod, 4)
            self.assertIn("не е безопасно", err)
            novi = p.b.execute("SELECT COUNT(*) FROM zapisi WHERE sastoyanie='nov'").fetchone()[0]
            self.assertGreater(novi, 0)
            kod, _, _ = h("filtriray", "--bez-model")
            self.assertEqual(kod, 0)
            self.assertEqual(p.b.execute("SELECT COUNT(*) FROM zapisi WHERE sastoyanie='nov'").fetchone()[0], 0)

    def test_chernova_vratata_4(self):
        with Papka() as p:
            h = Hod(p)
            h("sabiray", "--izvori", h.izvori)
            h("filtriray", "--bez-model")
            with mock.patch.object(dvrata, "http_get", lambda *a: (200, "busy")):
                kod, _, _ = h("chernova", "--data", "2026-10-05")
            self.assertEqual(kod, 4)
            self.assertFalse(os.path.exists(os.path.join(p.danni, "chernova_2026-10-05.json")))

    def test_odobri_bez_chernova_1(self):
        with Papka() as p:
            kod, _, err = Hod(p)("odobri", "--data", "2026-10-05", "--go")
            self.assertEqual(kod, 1)
            self.assertIn("няма чернова", err)

    def test_greshna_data_2(self):
        with Papka() as p, self.assertRaises(SystemExit) as k, contextlib.redirect_stderr(io.StringIO()):
            Hod(p)("chernova", "--data", "5.10.2026")
        self.assertEqual(k.exception.code, 2)

    def test_dnevnik(self):
        with Papka() as p:
            runs = os.path.join(p.d, "runs")
            h = Hod(p)
            h("sabiray", "--izvori", h.izvori, env={"SHINKANSEN_RUNS": runs})
            h("filtriray", "--bez-model", env={"SHINKANSEN_RUNS": runs})
            with open(os.path.join(runs, "filtar.jsonl"), encoding="utf-8") as f:
                redove = [json.loads(r) for r in f]
        self.assertEqual(len(redove), 2)
        self.assertTrue(all(r["helper"] == "filtar" and r["ok"] for r in redove))
        for r in redove:
            self.assertNotIn("Примерово", r["summary"])  # нищо от текстовете

    def test_kato_modul(self):
        with Papka() as p:
            r = subprocess.run([sys.executable, "-m", "filtar", "statistika", "--danni", p.danni], cwd=APP,
                               capture_output=True, text=True, timeout=60, env=dict(os.environ, SHINKANSEN_RUNS=""))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Статистика", r.stdout)


class TestConfig(unittest.TestCase):
    def test_primerite_sa_validni(self):
        from filtar import config
        c = config.zaredi(CFG)
        izv = config.izvori(c, os.path.join(APP, "izvori.example.json"))
        self.assertTrue(all("example." in z["url"] for z in izv))  # никакви истински източници
        self.assertEqual({r["nomer"] for r in c["rubriki"]}, {1, 2, 3, 4, 5, 6})
        self.assertEqual(c["sloy3"]["vreden"]["rezhim"], "izklyuchen")
        self.assertEqual(c["sloy3"]["vreden"]["kluch"], "")  # ключът никога в репото

    def test_greshen_registar(self):
        from filtar import config
        with Papka() as p:
            for losh in ([{"id": "a", "ime": "А", "vid": "medija", "tip": "rss"}],  # без url
                         [{"id": "a", "ime": "А", "vid": "medija", "tip": "ftp", "url": "https://example.org/"}],
                         {"ne": "списък"}):
                with self.subTest(losh):
                    path = os.path.join(p.d, "izvori.json")
                    pishi_json(path, losh)
                    with self.assertRaises(config.GreshkaConfig):
                        config.izvori(config.zaredi(CFG), path)


if __name__ == "__main__":
    unittest.main()
