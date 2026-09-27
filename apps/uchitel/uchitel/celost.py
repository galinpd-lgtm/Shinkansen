"""Правило 7: цялост след промяна. Същият брой заглавия, секции, връзки и код, същият текст и скриптове.

Разрешени са само разликите в логото (блокът му не се брои), шрифтовете (CSS не е текст) и етикетите
HUMAN/AGENT ↔ Човек/Агент (сливат се в едно при сравнението). Всичко друго → файлът не се пише.
"""
import re

from . import analiz
from .dom import razbor, tekst

SELEKTOR = re.compile(r"^([a-z0-9]*)(?:\.([\w-]+))?(?:\[([\w-]+)\])?$")


def _savpada(e, chast):
    m = SELEKTOR.match(chast.strip())
    if not m:
        raise ValueError("непознат селектор „%s“ в celost.broi" % chast)
    tag, klas, atr = m.groups()
    return ((not tag or e.tag == tag) and (not klas or klas in e.klasove())
            and (not atr or atr in e.attrs))


def otpechatak(html, k):
    doc = razbor(html)
    logo = analiz.nameri_logo(doc, k)

    def v_logoto(e):
        return logo is not None and (e is logo or any(p is logo for p in e.predci()))

    broi = {}
    for ime, selektor in k["celost"]["broi"].items():
        chasti = selektor.split(",")
        broi[ime] = sum(1 for e in doc.vsichki()
                        if not v_logoto(e) and any(_savpada(e, c) for c in chasti))

    etiketi = k["izgledi"]["etiketi"]
    zamestiteli = {}
    for i, (en, bg) in enumerate(sorted(etiketi.items())):
        zamestiteli[en] = zamestiteli[bg] = "\x00етикет%d\x00" % i
    dumi = []
    for d in " ".join(tekst(doc.koren, propusni=lambda e: e.tag in ("script", "style", "head") or e is logo)).split():
        d = zamestiteli.get(d, d)
        if not (dumi and d == dumi[-1] and d.startswith("\x00")):
            dumi.append(d)

    zaglavie = doc.parvi("title")
    skriptove = [html[e.otv_kraj:e.zatv] for e in doc.vsichki() if e.tag == "script" and e.zatv is not None]
    return {"broi": broi, "dumi": dumi, "skriptove": skriptove,
            "zaglavie": " ".join(tekst(zaglavie)) if zaglavie is not None else None,
            "schupeni": (len(doc.nezatvoreni), len(doc.visyashti))}


def sravni(staro, novo, k):
    """Списък с разликите. Празен → цялостта е запазена."""
    a, b = otpechatak(staro, k), otpechatak(novo, k)
    r = []
    for ime in a["broi"]:
        if a["broi"][ime] != b["broi"][ime]:
            r.append("%s: %d → %d" % (ime, a["broi"][ime], b["broi"][ime]))
    if a["dumi"] != b["dumi"]:
        for i, (x, y) in enumerate(zip(a["dumi"], b["dumi"])):
            if x != y:
                r.append("текстът се различава при дума %d: „%s“ → „%s“" % (i + 1, x, y))
                break
        else:
            r.append("текстът се различава по дължина: %d → %d думи" % (len(a["dumi"]), len(b["dumi"])))
    if a["skriptove"] != b["skriptove"]:
        r.append("скриптовете се различават")
    if a["zaglavie"] != b["zaglavie"]:
        r.append("<title> се различава")
    if a["schupeni"] != b["schupeni"]:
        r.append("незатворени/висящи тагове: %s → %s" % (a["schupeni"], b["schupeni"]))
    return r
