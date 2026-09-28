"""Регистърът: един JSON файл със списък от източници и техните състояния.

    kandidat → validiran → odobren | otkazan
                               ↘ za_pregled (повторна проверка на одобрен е засякла промяна)

Само `odobri` и `otkazhi` (човек, с роля) водят до odobren и otkazan. Машината може най-много да върне
източник към kandidat или да го сложи за преглед — никога не одобрява и никога не изключва сама.
Всяка смяна на състояние се добавя в `istoriya` на записа.
"""
import json
import os
import re
import urllib.parse

KANDIDAT, VALIDIRAN, ODOBREN, OTKAZAN, ZA_PREGLED = "kandidat", "validiran", "odobren", "otkazan", "za_pregled"
SASTOYANIYA = (KANDIDAT, VALIDIRAN, ODOBREN, OTKAZAN, ZA_PREGLED)
IMENA = {KANDIDAT: "кандидат", VALIDIRAN: "валидиран", ODOBREN: "одобрен", OTKAZAN: "отказан",
         ZA_PREGLED: "за преглед"}
MASHINA = "машина"


class GreshkaRegistar(Exception):
    pass


def prazen():
    return {"versiya": 1, "izvori": []}


def zaredi(path):
    """Липсващ файл е празен регистър."""
    if not os.path.exists(path):
        return prazen()
    try:
        with open(path, encoding="utf-8") as f:
            r = json.load(f)
    except (OSError, ValueError) as e:
        raise GreshkaRegistar("не мога да прочета регистъра %s: %s" % (path, e))
    if not isinstance(r, dict) or not isinstance(r.get("izvori"), list):
        raise GreshkaRegistar("регистърът %s трябва да е {\"izvori\": [...]}" % path)
    vidyani = set()
    for z in r["izvori"]:
        for k in ("id", "url", "vid", "sastoyanie"):
            if not z.get(k):
                raise GreshkaRegistar("запис без „%s“: %r" % (k, z.get("id")))
        if z["sastoyanie"] not in SASTOYANIYA:
            raise GreshkaRegistar("%s: непознато състояние „%s“" % (z["id"], z["sastoyanie"]))
        if z["id"] in vidyani:
            raise GreshkaRegistar("повторен id: %s" % z["id"])
        vidyani.add(z["id"])
    return r


def zapishi(path, r):
    """Атомарно: временен файл до регистъра и после замяна."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    vremenen = path + ".tmp"
    with open(vremenen, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(vremenen, path)


def nameri(r, izvor_id):
    for z in r["izvori"]:
        if z["id"] == izvor_id:
            return z
    raise GreshkaRegistar("няма източник „%s“ в регистъра" % izvor_id)


def kanon(url):
    p = urllib.parse.urlsplit(url.strip())
    h = (p.hostname or "").lower()
    if p.port:
        h += ":%d" % p.port
    return urllib.parse.urlunsplit((p.scheme.lower(), h, p.path.rstrip("/") or "/", p.query, ""))


def nov_id(r, url):
    p = urllib.parse.urlsplit(url)
    h = (p.hostname or "").lower()
    h = h[4:] if h.startswith("www.") else h
    osnova = re.sub(r"[^a-z0-9]+", "-", (h + " " + p.path).lower()).strip("-")[:60].strip("-") or "izvor"
    zaeti = {z["id"] for z in r["izvori"]}
    kandidat, n = osnova, 2
    while kandidat in zaeti:
        kandidat, n = "%s-%d" % (osnova, n), n + 1
    return kandidat


def smeni(zapis, novo, t, ot=MASHINA, belezhka=""):
    staro = zapis["sastoyanie"]
    zapis["sastoyanie"] = novo
    zapis.setdefault("istoriya", []).append({"t": t, "ot": staro, "kam": novo, "koy": ot, "belezhka": belezhka})
