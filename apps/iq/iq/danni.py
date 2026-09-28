"""Четене на базата на филтъра (Z8) — само за четене; IQ никога не пише в нея.

Запис на канала е ред от `zapisi` с `izvor` = id на канала и изчислена оценка на Z7 (`ocenka` не е NULL).
Денят на записа е датата на публикация (`data`); без нея — денят на събиране (`sabrano`).
"""
import json
import os
import sqlite3
from datetime import date


class GreshkaDanni(Exception):
    pass


def otvori(papka):
    p = os.path.join(papka, "filtar.sqlite")
    if not os.path.exists(p):
        raise GreshkaDanni("няма база на филтъра: %s" % p)
    b = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
    b.row_factory = sqlite3.Row
    return b


def _den(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def zapisi(b, kanal):
    """→ списък dict-ове, подредени по ден: den, id, zaglavie, url, ocenka, osi {ключ: оценка},
    pohvati [{ime, otkas}], rezhim, uverenost, chovek."""
    rez = []
    for r in b.execute("SELECT id, izvor_ime, zaglavie, url, data, sabrano, ocenka, doverie FROM zapisi "
                       "WHERE izvor=? AND ocenka IS NOT NULL", (kanal,)):
        den = _den(r["data"]) or _den(r["sabrano"])
        if den is None:
            continue
        try:
            d = json.loads(r["doverie"]) if r["doverie"] else {}
        except ValueError:
            d = {}
        prof = d.get("profil") or {}
        rez.append({
            "id": r["id"], "den": den, "ime_na_izvor": r["izvor_ime"], "zaglavie": r["zaglavie"] or "",
            "url": r["url"] or "", "ocenka": float(r["ocenka"]),
            "osi": {o["kluch"]: float(o["ocenka"]) for o in d.get("osi") or [] if o.get("ocenka") is not None},
            "pohvati": [p for p in d.get("pohvati") or [] if p.get("ime")],
            "rezhim": d.get("rezhim"),
            "uverenost": (prof.get("uverenost") or {}).get("nivo"),
            "chovek": prof.get("chovek"),
        })
    rez.sort(key=lambda z: (z["den"], z["id"]))
    return rez


def ime_ot_bazata(b, kanal):
    r = b.execute("SELECT izvor_ime FROM zapisi WHERE izvor=? AND izvor_ime IS NOT NULL LIMIT 1", (kanal,)).fetchone()
    return r["izvor_ime"] if r else None


def ima_kanal(b, kanal):
    return b.execute("SELECT 1 FROM zapisi WHERE izvor=? LIMIT 1", (kanal,)).fetchone() is not None
