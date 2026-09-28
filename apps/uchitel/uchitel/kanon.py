"""Зареждане на канона. Правилата, класовете, шрифтовете и шаблоните живеят само в JSON, не в кода.

Ред на търсене: изричен път → $UCHITEL_KANON → apps/uchitel/kanon.json → apps/uchitel/kanon.example.json.
Пътят до знака (logo.znak) е относителен спрямо папката на самия канон.
"""
import base64
import ipaddress
import json
import os
import re

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RAZDELI = ("izklyuchi", "lenta", "logo", "shriftove", "izgledi", "tamna_tema", "iztichane",
           "chist_balgarski", "celost")
MIME = {".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".gif": "image/gif"}


class GreshkaKanon(Exception):
    pass


def nameri(path=None):
    if path:
        return path
    env = os.environ.get("UCHITEL_KANON")
    if env:
        return env
    lokalen = os.path.join(APP, "kanon.json")
    if os.path.exists(lokalen):
        return lokalen
    return os.path.join(APP, "kanon.example.json")


def zaredi(path=None):
    p = os.path.abspath(nameri(path))
    try:
        with open(p, encoding="utf-8") as f:
            k = json.load(f)
    except (OSError, ValueError) as e:
        raise GreshkaKanon("не мога да прочета канона %s: %s" % (p, e))
    greshki = proveri(k)
    if greshki:
        raise GreshkaKanon("канонът %s: %s" % (p, "; ".join(greshki)))
    k["_papka"] = os.path.dirname(p)
    k["_pat"] = p
    return k


def proveri(k):
    greshki = ["липсва „%s“" % r for r in RAZDELI if r not in k]
    if greshki:
        return greshki
    lg = k["logo"]
    for pole in ("znak", "tekst", "klasove", "marker_klas", "vatreshnost", "kurs_dvuezichno", "nov_blok", "css"):
        if pole not in lg:
            greshki.append("липсва logo.%s" % pole)
    for pole in ("{znak}", "{tekst}", "{kurs}"):
        if pole not in lg.get("vatreshnost", ""):
            greshki.append("logo.vatreshnost няма %s" % pole)
    for pole in ("{bg}", "{en}"):
        if pole not in lg.get("kurs_dvuezichno", ""):
            greshki.append("logo.kurs_dvuezichno няма %s" % pole)
    if lg.get("marker_klas", "") not in lg.get("vatreshnost", ""):
        greshki.append("logo.vatreshnost не съдържа marker_klas — повторно пускане би сменило логото пак")
    for pole in ("tekst", "kod", "zameni", "pozvoleni", "google_fonts"):
        if pole not in k["shriftove"]:
            greshki.append("липсва shriftove.%s" % pole)
    for pole in ("bg_klas", "en_klas", "agent_klas", "prevkluchvatel_ezik", "etiketi", "etiket_shablon",
                 "kirilica"):
        if pole not in k["izgledi"]:
            greshki.append("липсва izgledi.%s" % pole)
    for m in k["iztichane"].get("mrezhi", []):
        try:
            ipaddress.ip_network(m)
        except ValueError:
            greshki.append("iztichane.mrezhi: „%s“ не е мрежа" % m)
    shabloni = list(k["iztichane"].get("shabloni", {}).values()) + k["tamna_tema"].get("tryabva", []) \
        + k["izgledi"]["prevkluchvatel_ezik"] + [k["izgledi"]["kirilica"]]
    for s in shabloni:
        try:
            re.compile(s)
        except re.error as e:
            greshki.append("грешен регулярен израз „%s“: %s" % (s, e))
    if not isinstance(k["izklyuchi"], list):
        greshki.append("izklyuchi трябва да е списък")
    return greshki


def znak_data_uri(k):
    """Знакът като data URI. Липсващ файл е грешка само при поправка — проверката минава и без него."""
    p = k["logo"]["znak"]
    if not os.path.isabs(p):
        p = os.path.join(k["_papka"], p)
    mime = MIME.get(os.path.splitext(p)[1].lower())
    if not mime:
        raise GreshkaKanon("знакът %s: непознат вид файл (очаквам .png, .svg, .webp, .jpg)" % p)
    try:
        with open(p, "rb") as f:
            danni = f.read()
    except OSError as e:
        raise GreshkaKanon("не мога да прочета знака %s: %s" % (p, e))
    return "data:%s;base64,%s" % (mime, base64.b64encode(danni).decode("ascii"))
