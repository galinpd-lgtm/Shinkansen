"""Общо за тестовете: измислена мрежа от файлове във fixtures/, фалшив часовник, временна папка. Нула мрежа.

Всички адреси са на example.com, example.org и example.net.
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

from izvori import cli, config  # noqa: E402
from izvori.mrezha import Mrezha  # noqa: E402

CFG = config.zaredi(CFG_PAT)
SEGA = "2026-09-28T08:00:00Z"
HTML = {"content-type": "text/html; charset=utf-8"}


def fix(ime):
    with open(os.path.join(FIX, ime), "rb") as f:
        return f.read()


def stranici():
    """Основният измислен свят. Всеки непознат адрес → 404 (и robots.txt, и tdmrep.json)."""
    return {
        # производител: блог с емисия, обявена в <link>
        "https://example.com/blog/": (200, dict(HTML, **{"last-modified": "Fri, 25 Sep 2026 10:30:00 GMT"}),
                                      fix("blog.html")),
        "https://example.com/blog/feed.xml": (200, {"content-type": "application/rss+xml"}, fix("feed.rss")),
        "https://example.com/": (200, HTML, fix("glavna.html")),
        # производител: пренасочване към чужд домейн
        "https://example.com/novini": (301, {"location": "https://example.net/drugade/"}, b""),
        "https://example.net/drugade/": (200, HTML, fix("blog.html")),
        # регулатор: страница без емисия
        "https://example.org/press/": (200, HTML, fix("bez_emisiya.html")),
        # регулатор: TDM резервация (заглавка, meta и tdmrep.json)
        "https://example.org/docs/ai": (200, dict(HTML, **{"tdm-reservation": "1"}), fix("tdm.html")),
        "https://example.org/.well-known/tdmrep.json": (200, {"content-type": "application/json"}, fix("tdmrep.json")),
        # регулатор: защита
        "https://example.org/zashtiteno/": (403, HTML, b"<html><body>Forbidden</body></html>"),
        # изследвания на поддомейн извън домейна на производителя, към който главната му страница сочи
        "https://research.example.net/papers/": (200, {"content-type": "application/atom+xml"}, fix("feed.atom")),
        # медия, която забранява на izvori в robots.txt
        "https://news.example.net/robots.txt": (200, {"content-type": "text/plain"}, fix("robots_zabrana.txt")),
        "https://news.example.net/tech/": (200, HTML, fix("blog.html")),
    }


class Svyat:
    """Фалшив транспорт + часовник. `zayavki` е всичко поискано, с UA."""

    def __init__(self, st=None):
        self.st = stranici() if st is None else st
        self.zayavki, self.spane, self.vreme = [], [], 1000.0

    def transport(self, url, ua, timeout, maks):
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

    def fabrika(self, cfg):
        return Mrezha(cfg, transport=self.transport, chasovnik=self.chasovnik, spi=self.spi)


class Papka:
    """Временна папка с празен регистър. `hod(...)` пуска main() и връща (код, stdout, stderr)."""

    def __init__(self, svyat=None):
        self.svyat = svyat or Svyat()

    def __enter__(self):
        self.d = tempfile.mkdtemp()
        self.reg = os.path.join(self.d, "izvori.json")
        self.dok = os.path.join(self.d, "dokazatelstva")
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.d)

    def hod(self, komanda, *argv, sega=SEGA):
        out, err = io.StringIO(), io.StringIO()
        vse = [komanda, "--config", CFG_PAT, "--registar", self.reg, "--sega", sega] + list(argv)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            kod = cli.main(vse, mrezha_fabrika=self.svyat.fabrika)
        return kod, out.getvalue(), err.getvalue()

    def registar(self):
        with open(self.reg, encoding="utf-8") as f:
            return json.load(f)

    def zapis(self, izvor_id):
        return next(z for z in self.registar()["izvori"] if z["id"] == izvor_id)

    def dobavi(self, url, vid, org=None):
        argv = [url, "--vid", vid] + (["--organizaciya", org] if org else [])
        kod, out, err = self.hod("dobavi", *argv)
        assert kod == 0, err
        return out.split(":")[0]
