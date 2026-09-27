"""Командата: JSON без модел, кодове на изход 0/4/1, дневникът SHINKANSEN_RUNS и HTTP обработчикът — без мрежа."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from obshto import APP, HERE, cfg, primer

from doverie import cli
from doverie import model as model_mod
from doverie import vrata as vrata_mod
from doverie.serve import napravi_handler

PRIMER_1 = os.path.join(HERE, "primer_1.txt")


def pusni(*argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env or {}, clear=False), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        kod = cli.main(list(argv))
    return kod, out.getvalue(), err.getvalue()


def bez_mrezha(*a, **kw):
    raise AssertionError("истинска мрежа в тест")


@mock.patch.object(model_mod, "http_post", bez_mrezha)
class TestCli(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHINKANSEN_RUNS", None)
        os.environ.pop("SHINKANSEN_SUMMARY_FILE", None)

    def test_gotovo_bez_model(self):
        """Готово е, когато: 1. JSON със 7 оси, похвати с откъси, крайна оценка и решение."""
        kod, out, _ = pusni("ocenka", "--tekst", PRIMER_1, "--bez-model")
        self.assertEqual(kod, 0)
        rez = json.loads(out)
        self.assertEqual(len(rez["osi"]), 7)
        self.assertTrue(rez["pohvati"])
        for p in rez["pohvati"]:
            self.assertIn(p["otkas"], " ".join(primer(1).split()))
        self.assertIsInstance(rez["krayna_ocenka"], float)
        self.assertIn(rez["reshenie"]["ime"], ("ПРОПУСНИ", "ПРЕДУПРЕДИ", "КАРАНТИНА"))

    def test_kato_modul(self):
        r = subprocess.run([sys.executable, "-m", "doverie", "ocenka", "--tekst", "tests/primer_1.txt", "--bez-model"],
                           cwd=APP, capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, SHINKANSEN_RUNS=""))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(json.loads(r.stdout)["osi"]), 7)

    def test_format_tekst(self):
        kod, out, _ = pusni("ocenka", "--tekst", PRIMER_1, "--bez-model", "--format", "tekst")
        self.assertEqual(kod, 0)
        self.assertTrue(out.startswith("Достоверност:"))

    def test_busy_izhod_4_bez_vikane(self):
        with mock.patch.object(vrata_mod, "http_get", lambda *a: (200, "busy")):
            kod, out, err = pusni("ocenka", "--tekst", PRIMER_1)
        self.assertEqual(kod, 4)
        self.assertEqual(out, "")
        self.assertIn("заето", err)

    def test_vratata_pada_izhod_1(self):
        def pada(*a):
            raise OSError("няма връзка")
        with mock.patch.object(vrata_mod, "http_get", pada):
            kod, _, err = pusni("ocenka", "--tekst", PRIMER_1)
        self.assertEqual(kod, 1)
        self.assertIn("вратата", err)

    def test_lipsvasht_fail_izhod_1(self):
        self.assertEqual(pusni("ocenka", "--tekst", "/nyama/takav.txt", "--bez-model")[0], 1)

    def test_dnevnik(self):
        with tempfile.TemporaryDirectory() as d:
            pusni("ocenka", "--tekst", PRIMER_1, "--bez-model", env={"SHINKANSEN_RUNS": d})
            with mock.patch.object(vrata_mod, "http_get", lambda *a: (200, "busy")):
                pusni("ocenka", "--tekst", PRIMER_1, env={"SHINKANSEN_RUNS": d})
            with open(os.path.join(d, "doverie.jsonl"), encoding="utf-8") as f:
                redove = [json.loads(r) for r in f]
        self.assertEqual(len(redove), 2)
        self.assertEqual(redove[0]["helper"], "doverie")
        self.assertTrue(redove[0]["ok"])
        self.assertIn("exit 0", redove[0]["summary"])
        self.assertIn("exit 4", redove[1]["summary"])
        # никакви данни от входа
        for r in redove:
            self.assertNotIn("Примерово", json.dumps(r, ensure_ascii=False))


class FalshivaZayavka:
    """Извиква обработчика без сокет: rfile/wfile в паметта."""

    def __init__(self, handler_cls, method, path, tyalo=b""):
        h = handler_cls.__new__(handler_cls)
        h.rfile, h.wfile = io.BytesIO(tyalo), io.BytesIO()
        h.path, h.command = path, method
        h.request_version, h.requestline = "HTTP/1.1", "%s %s HTTP/1.1" % (method, path)
        h.headers = {"Content-Length": str(len(tyalo))}
        h.client_address = ("127.0.0.1", 0)
        getattr(h, "do_" + method)()
        surovo = h.wfile.getvalue().decode("utf-8")
        glava, _, tyalo_otg = surovo.partition("\r\n\r\n")
        self.kod = int(glava.split()[1])
        self.json = json.loads(tyalo_otg)


class TestServe(unittest.TestCase):
    def test_ocenka(self):
        H = napravi_handler(cfg(), bez_model=True)
        z = FalshivaZayavka(H, "POST", "/ocenka", json.dumps({"tekst": primer(2)}).encode())
        self.assertEqual(z.kod, 200)
        self.assertEqual(len(z.json["osi"]), 7)

    def test_prazno(self):
        H = napravi_handler(cfg(), bez_model=True)
        self.assertEqual(FalshivaZayavka(H, "POST", "/ocenka", b'{"tekst": " "}').kod, 400)

    def test_busy_503(self):
        from doverie.vrata import VrataZaeta

        class Zaet:
            def chat(self, *a):
                raise VrataZaeta("заето")
        H = napravi_handler(cfg(), model_fabrika=Zaet)
        self.assertEqual(FalshivaZayavka(H, "POST", "/ocenka", json.dumps({"tekst": primer(2)}).encode()).kod, 503)

    def test_samo_lokalno(self):
        from doverie import serve
        self.assertEqual(serve.HOST, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
