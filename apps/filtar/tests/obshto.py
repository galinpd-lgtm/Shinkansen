"""Общо за тестовете: пътища, конфигурация, фалшива мрежа от файлове в fixtures/ и фалшив модел. Нула мрежа."""
import copy
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, APP)

from filtar import baza, config  # noqa: E402
from filtar.dov import zaredi_doverie  # noqa: E402

CFG = config.zaredi(os.path.join(APP, "config.example.json"))
DCFG = zaredi_doverie(os.path.join(os.path.dirname(APP), "doverie", "config.example.json"))
SEGA = datetime(2026, 10, 5, 7, 30, tzinfo=timezone.utc)

IZVORI = [
    {"id": "primer-tehno", "ime": "Примерен технологичен портал", "vid": "medija", "tip": "rss",
     "url": "https://example.org/tehno/rss.xml", "ezik": "bg"},
    {"id": "primer-obshtina", "ime": "Примерна общинска емисия", "vid": "oficialen", "tip": "atom",
     "url": "https://example.org/obshtina/atom.xml", "ezik": "bg"},
    {"id": "primer-obshtnost", "ime": "Примерен общностен блог", "vid": "obshtnost", "tip": "rss",
     "url": "https://example.net/blog/feed", "ezik": "bg"},
]


def cfg():
    return copy.deepcopy(CFG)


def dcfg():
    return copy.deepcopy(DCFG)


def procheti(ime):
    with open(os.path.join(FIX, ime), "rb") as f:
        return f.read()


class FalshivaMrezha:
    """Същият подпис като sabirach.http_get. Непознат адрес → 404 (и за robots.txt, и за tdmrep.json)."""

    def __init__(self, stranici=None):
        self.stranici = {
            "https://example.org/tehno/rss.xml": (200, "application/rss+xml", None, {}, procheti("tehno.rss")),
            "https://example.org/obshtina/atom.xml": (200, "application/atom+xml", None, {}, procheti("obshtina.atom")),
            "https://example.net/blog/feed": (200, "application/rss+xml", "utf-8", {}, procheti("obshtnost.rss")),
        }
        self.stranici.update(stranici or {})
        self.zayavki = []

    def __call__(self, url, ua, timeout):
        self.zayavki.append((url, ua, timeout))
        return self.stranici.get(url, (404, "", None, {}, b""))


class Papka:
    """Временна папка с данни и копие на vhod/ от fixtures."""

    def __enter__(self):
        self.d = tempfile.mkdtemp()
        self.danni = os.path.join(self.d, "danni")
        self.vhod = os.path.join(self.d, "vhod")
        shutil.copytree(os.path.join(FIX, "vhod"), self.vhod)
        self.b = baza.otvori(self.danni)
        return self

    def __exit__(self, *a):
        self.b.close()
        shutil.rmtree(self.d)


def pishi_json(path, d):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)


class FalshivModel:
    """Интерфейсът на doverie.model.Model: chat(rolya, sistema, potrebitel) → dict. Пази виканията."""

    def __init__(self, vrata=None):
        self.vikaniya = []
        self.vrata = vrata

    def chat(self, rolya, sistema, potrebitel):
        if self.vrata is not None:
            self.vrata.proveri()
        self.vikaniya.append((rolya, potrebitel[:60]))
        from filtar.dov import ocenka as _o  # noqa: F401
        from doverie.ocenka import PROMPT_OS
        for p in PROMPT_OS.values():
            if potrebitel.startswith(p):
                return {"ocenka": 8, "zashto": "Фалшивият модел: добре."}
        if potrebitel.startswith("Кои от тези манипулативни похвати"):
            return {"pohvati": []}
        if potrebitel.startswith("Прочети новината"):
            return {"kakvo": "Нещо се случи. Описано е в източника.", "znachi": "Фирмите да проверят сроковете."}
        return {"za_chitatelya": "Прегледано.", "silni": [], "slabi": [], "preporaka": "Прочетете."}


class Otvorena:
    def __init__(self, sastoyaniya=None):
        self.sastoyaniya = list(sastoyaniya or [])
        self.pitaniya = 0

    def proveri(self):
        from doverie.vrata import VrataZaeta
        self.pitaniya += 1
        if self.sastoyaniya and self.sastoyaniya.pop(0) == "busy":
            raise VrataZaeta("заето")
