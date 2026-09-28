"""Конфигурацията на филтъра. Ред на търсене: изричен път → $FILTAR_CONFIG → config.json → config.example.json.

Относителните пътища в нея (papka_danni, izvori, organizacii, vhod) са спрямо текущата папка.
Ключът за облачния класификатор стои само в частния config.json на GX10 — никога в репото.
"""
import json
import os

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class GreshkaConfig(Exception):
    pass


def nameri(path=None):
    if path:
        return path
    if os.environ.get("FILTAR_CONFIG"):
        return os.environ["FILTAR_CONFIG"]
    lokalen = os.path.join(APP, "config.json")
    return lokalen if os.path.exists(lokalen) else os.path.join(APP, "config.example.json")


def zaredi(path=None):
    p = nameri(path)
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise GreshkaConfig("не мога да прочета конфигурацията %s: %s" % (p, e))
    for k in ("papka_danni", "sloy1", "sloy2", "sloy3", "sloy4", "sloy5", "rubriki", "izdanie"):
        if k not in cfg:
            raise GreshkaConfig("конфигурацията %s: липсва „%s“" % (p, k))
    return cfg


def cheti_json(path, po_podrazbirane=None):
    if not path:
        return po_podrazbirane
    p = path if os.path.isabs(path) or os.path.exists(path) else os.path.join(APP, path)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        if po_podrazbirane is not None:
            return po_podrazbirane
        raise GreshkaConfig("липсва файл: %s" % path)
    except ValueError as e:
        raise GreshkaConfig("неразбираем JSON в %s: %s" % (path, e))


def izvori(cfg, path=None):
    spisak = cheti_json(path or cfg.get("izvori"))
    if not isinstance(spisak, list):
        raise GreshkaConfig("регистърът на източниците трябва да е списък")
    vidyani = set()
    for i, z in enumerate(spisak):
        for k in ("id", "ime", "vid", "tip", "url"):
            if not z.get(k):
                raise GreshkaConfig("източник %d: липсва „%s“" % (i, k))
        if z["tip"] not in ("rss", "atom", "html"):
            raise GreshkaConfig("източник %s: непознат тип „%s“" % (z["id"], z["tip"]))
        if z["id"] in vidyani:
            raise GreshkaConfig("повторен източник: %s" % z["id"])
        vidyani.add(z["id"])
    return spisak
