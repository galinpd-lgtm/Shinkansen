"""Общо за тестовете: измислен свят от файлове във fixtures/, фалшив часовник, браузър и модел. Нула мрежа.

Всички адреси са на example.com, example.org и example.net. Браузърът никога не е истинският Playwright —
дори да е инсталиран на машината, тестовете подават фалшив.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
CFG_PAT = os.path.join(APP, "config.example.json")
sys.path.insert(0, APP)

from oditor import cli, config  # noqa: E402
from oditor.mrezha import Mrezha  # noqa: E402

CFG = config.zaredi(CFG_PAT)
SEGA = "2026-10-08T08:00:00Z"
HTML = {"content-type": "text/html; charset=utf-8"}
TXT = {"content-type": "text/plain; charset=utf-8"}


def fix(ime):
    with open(os.path.join(FIX, ime), "rb") as f:
        return f.read()


def fix_json(ime):
    return json.loads(fix(ime).decode("utf-8"))


def stranici():
    """Основният измислен свят. Всеки непознат адрес → 404 (и robots.txt, и llms.txt)."""
    return {
        # добър сайт: всичко има, robots.txt пуска всички, llms.txt е истински текст
        "https://example.com/robots.txt": (200, TXT, b"User-agent: *\nAllow: /\n"),
        "https://example.com/": (200, fix_json("zaglavki_dobar.json"), fix("dobar.html")),
        "https://example.com/llms.txt": (200, TXT, fix("llms.txt")),
        "https://example.com/poveritelnost": (200, HTML, fix("politika_palna.html")),
        # сайт с JavaScript: без него — празна обвивка; llms.txt връща страница за грешка с код 200
        "https://example.org/": (200, HTML, fix("js_sayt.html")),
        "https://example.org/llms.txt": (200, HTML, fix("js_sayt.html")),
        # защитна стена
        "https://example.net/": (403, HTML, fix("zashtita_403.html")),
        # отложено събитие с грешен eventStatus; после — поправено (подменя се в теста)
        "https://teatar.example.com/": (200, HTML, fix("otlozheno.html")),
        # robots.txt моли AI ботовете да не влизат
        "https://ai.example.org/robots.txt": (200, TXT, fix("robots_ai_zabrana.txt")),
        "https://ai.example.org/": (200, HTML, fix("dobar.html")),
        # robots.txt моли нашия обхождащ да не влиза
        "https://bez-nas.example.net/robots.txt": (200, TXT, fix("robots_oditor_zabrana.txt")),
        "https://bez-nas.example.net/": (200, HTML, fix("dobar.html")),
        # сайт само на чужд език; http → https пренасочване
        "http://hostel.example.net/": (301, {"location": "https://hostel.example.net/"}, b""),
        "https://hostel.example.net/": (200, HTML, fix("chuzhd_ezik.html")),
        # политика само с въведение
        "https://vavedenie.example.com/": (200, HTML, fix("dobar.html")),
        "https://vavedenie.example.com/poveritelnost": (200, HTML, fix("politika_vavedenie.html")),
    }


class Svyat:
    """Фалшив транспорт + часовник. `zayavki` е всичко поискано, с UA."""

    def __init__(self, st=None):
        self.st = stranici() if st is None else st
        self.zayavki, self.spane, self.vreme = [], [], 1000.0

    def transport(self, url, ua, timeout, maks):
        ua.encode("latin-1")  # като истинския http.client: заглавката е само latin-1
        self.zayavki.append((url, ua))
        self.vreme += 0.1
        if url not in self.st:
            return 404, {"content-type": "text/html"}, b"<html><body>404</body></html>"
        st = self.st[url]
        if isinstance(st, Exception):
            raise st
        return st

    def chasovnik(self):
        return self.vreme

    def spi(self, s):
        self.spane.append(s)
        self.vreme += s

    def mrezha(self, cfg):
        return Mrezha(cfg, transport=self.transport, chasovnik=self.chasovnik, spi=self.spi)

    def adresi(self):
        return [u for u, _ in self.zayavki]


class Brauzar:
    """Фалшив браузър: адрес → HTML (статус 200, банерът по желание). Непознат адрес → браузърът падна."""

    def __init__(self, stranici=None):
        self.stranici = stranici or {}
        self.vikan = []

    def __call__(self, url, ua, timeout_s):
        self.vikan.append(url)
        if url not in self.stranici:
            raise RuntimeError("няма запис за %s" % url)
        html, banner, otkaz = self.stranici[url]
        return {"izpolzvan": True, "status": 200, "url": url, "t": "2026-10-08T08:00:05Z", "html": html,
                "banner": banner, "otkaz_buton": otkaz if banner else None, "otkaz_tekst": "Отказвам" if otkaz else None}


class Model:
    """Фалшив модел със същия интерфейс като `oditor.model.Model`: роля → функция(система, текст) → dict."""

    def __init__(self, otgovori=None, roli=("rabotnik", "pazach", "visok_risk")):
        self.otgovori = otgovori or {}
        self.roli = roli
        self.vikaniya = []

    def ima(self, rolya):
        return rolya in self.roli

    def ime(self, rolya):
        return {"rabotnik": "gemma4", "pazach": "nemotron-3-super", "visok_risk": "mistral-small-4"}[rolya]

    def chat(self, rolya, sistema, potrebitel):
        from oditor.model import GreshkaModel
        self.vikaniya.append((rolya, potrebitel))
        f = self.otgovori.get(rolya)
        if f is None:
            raise GreshkaModel("няма модел за %s" % rolya)
        return f(sistema, potrebitel)


class Papka:
    """Временна папка за частната база. `hod(...)` пуска main() и връща (код, stdout, stderr)."""

    def __init__(self, svyat=None, brauzar=None, model=None):
        self.svyat = svyat or Svyat()
        self.brauzar = brauzar or Brauzar()
        self.model = model or Model()

    def __enter__(self):
        self.d = tempfile.mkdtemp()
        self.rez = os.path.join(self.d, "rezultati")
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.d)

    def hod(self, komanda, *argv, sega=SEGA):
        out, err = io.StringIO(), io.StringIO()
        vse = [komanda, "--config", CFG_PAT, "--rezultati", self.rez, "--sega", sega] + list(argv)
        sreda = cli.Sreda(mrezha=self.svyat.mrezha, model=lambda cfg: self.model, brauzar=self.brauzar,
                          spi=self.svyat.spi)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            kod = cli.main(vse, sreda=sreda)
        return kod, out.getvalue(), err.getvalue()

    def proveri(self, url, *argv):
        kod, out, err = self.hod("proveri", url, *argv)
        assert kod == 0, err
        return out.split(":")[0]

    def zapis(self, rid):
        with open(os.path.join(self.rez, rid + ".json"), encoding="utf-8") as f:
            return json.load(f)
