"""Конфигурацията. Ред на търсене: изричен път → $IZVORI_CONFIG → config.json → config.example.json.

Видовете, ешелоните, организациите и правилата за вид съдържание живеят тук — в кода няма списъци.
Истинските организации са в частен config извън репото; в примера са само example-домейни.
"""
import json
import os

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESHELONI = ("parvichen", "vtorichen", "posrednik")  # от най-високия надолу


class GreshkaConfig(Exception):
    pass


def nameri(path=None):
    if path:
        return path
    if os.environ.get("IZVORI_CONFIG"):
        return os.environ["IZVORI_CONFIG"]
    lokalen = os.path.join(APP, "config.json")
    return lokalen if os.path.exists(lokalen) else os.path.join(APP, "config.example.json")


def zaredi(path=None):
    p = nameri(path)
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise GreshkaConfig("не мога да прочета конфигурацията %s: %s" % (p, e))
    for k in ("user_agent_ime", "taymaut_s", "pauza_na_domeyn_s", "maks_prenasochvaniya", "maks_glava_bytes",
              "roli_odobryavashti", "vidove", "organizacii", "obichayni_patishta_emisiya", "vid_sadarzhanie",
              "kirilski_ezici"):
        if k not in cfg:
            raise GreshkaConfig("конфигурацията %s: липсва „%s“" % (p, k))
    if len(cfg["obichayni_patishta_emisiya"]) > 4:
        raise GreshkaConfig("obichayni_patishta_emisiya: най-много 4 пътя (без обхождане)")
    for vid, v in cfg["vidove"].items():
        if v.get("eshelon") not in ESHELONI:
            raise GreshkaConfig("вид %s: ешелонът трябва да е един от %s" % (vid, ", ".join(ESHELONI)))
    imena = set()
    for o in cfg["organizacii"]:
        if not o.get("ime") or not o.get("domeyni"):
            raise GreshkaConfig("организация без „ime“ или „domeyni“: %r" % o)
        if o["ime"] in imena:
            raise GreshkaConfig("повторена организация: %s" % o["ime"])
        imena.add(o["ime"])
    cfg.setdefault("eshelon_imena", {e: e for e in ESHELONI})
    cfg.setdefault("maks_tyalo_bytes", 2_000_000)
    cfg.setdefault("registar", "izvori.json")
    return cfg


def organizaciya(cfg, ime):
    for o in cfg["organizacii"]:
        if o["ime"] == ime:
            return o
    return None


def po_domeyn(cfg, host):
    """Организацията, на чийто домейн е хостът (самият домейн или поддомейн) — или None."""
    for o in cfg["organizacii"]:
        if any(na_domeyn(host, d) for d in o["domeyni"]):
            return o
    return None


def na_domeyn(host, domeyn):
    host, domeyn = (host or "").lower().rstrip("."), domeyn.lower().rstrip(".")
    return host == domeyn or host.endswith("." + domeyn)


def eshelon(cfg, vid):
    return cfg["vidove"][vid]["eshelon"]


def po_nisak(a, b):
    """По-ниският от два ешелона (None се пренебрегва)."""
    ako = [e for e in (a, b) if e in ESHELONI]
    return max(ako, key=ESHELONI.index) if ako else None
