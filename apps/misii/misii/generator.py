"""Генераторът: обектите от базата → мисии за един район. Чист: без мрежа, без часовник, без случайност.

Еднакъв вход (база, район, области, дата) → еднакви мисии в еднакъв ред с еднакви id.

Дупки:
- lipsva_pole — полето от областта в config е празно (None, "" или липсва) за обект от позволен тип;
- iztekla_proverka — `proveren_na` е по-стар от `srok_proverka_dni` → „работи ли“;
- karta_bez_registar — обект от картата (`izvor: karta`) без `registar_id` → „има ли такъв обект тук“;
- registar_bez_karta — обект от регистъра без координати → „къде точно е“.

В мисията влизат само полетата на обекта (id, име, тип, адрес, координати, адрес на сайт). Нищо за хора.
"""
import datetime
import re

from .config import OBLASTI

OBEKT_POLETA = ("id", "ime", "tip", "adres", "lat", "lon", "url")
SPECIALNI = {
    "iztekla_proverka": ("raboti_li", "Работи ли още обектът? Мини покрай него и отбележи.", ["raboti_li"]),
    "karta_bez_registar": ("nov_obekt", "На картата тук има такъв обект. Има ли го наистина? Снимай го, без хора в кадър.",
                           ["ima_li", "snimka"]),
    "registar_bez_karta": ("nov_obekt", "Обектът е в регистъра, но не е на картата. Къде точно е? Адрес или ориентир.",
                           ["mestopolozhenie"]),
}


class GreshkaBaza(Exception):
    pass


def _prazno(v):
    return v is None or (isinstance(v, str) and not v.strip()) or v == [] or v == {}


def _obekt_v_misiya(o):
    izhod = {}
    for k in OBEKT_POLETA:
        v = o.get(k)
        if _prazno(v):
            continue
        if k == "url" and not str(v).startswith("https://"):
            continue
        izhod[k] = v
    return izhod


def _chast(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "x"


def _id(rayon, obekt_id, vid, pole):
    return "m-%s-%s-%s" % (_chast(rayon), _chast(obekt_id), _chast(pole or vid))


def _data(s):
    try:
        return datetime.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def obekti(baza):
    if isinstance(baza, dict):
        baza = baza.get("obekti")
    if not isinstance(baza, list):
        raise GreshkaBaza("базата трябва да е списък с обекти или {\"obekti\": [...]}")
    vidyani = set()
    for o in baza:
        if not isinstance(o, dict) or "id" not in o or not o.get("ime"):
            raise GreshkaBaza("обект без „id“ или „ime“: %r" % (o,))
        if o["id"] in vidyani:
            raise GreshkaBaza("повторен id на обект: %s" % o["id"])
        vidyani.add(o["id"])
    return baza


def generiray(baza, rayon, oblasti, cfg, data):
    """→ списък (неподписан): {rayon, izdaden, versiya, oblasti, misii}. `data` — ISO дата на изданието."""
    from . import VERSIYA
    if rayon not in cfg["rayoni"]:
        raise GreshkaBaza("непознат район „%s“ (в config: %s)" % (rayon, ", ".join(sorted(cfg["rayoni"]))))
    for ob in oblasti:
        if ob not in cfg["oblasti"]:
            raise GreshkaBaza("областта „%s“ не е настроена в config" % ob)
    den = _data(data)
    if den is None:
        raise GreshkaBaza("датата трябва да е ГГГГ-ММ-ДД: %s" % data)
    validna_do = (den + datetime.timedelta(days=int(cfg["validna_dni"]))).isoformat()
    srok = den - datetime.timedelta(days=int(cfg["srok_proverka_dni"]))
    red_oblasti = sorted(set(oblasti), key=OBLASTI.index)

    misii = {}

    def dobavi(o, oblast, vid, vapros, poleta, prichina, pole=None):
        mid = _id(rayon, o["id"], vid, pole)
        if mid in misii:
            return
        m = {"id": mid, "rayon": rayon, "oblast": oblast, "vid": vid, "obekt": _obekt_v_misiya(o),
             "vapros": vapros, "poleta": list(poleta), "prichina": prichina, "validna_do": validna_do}
        if pole:
            m["pole"] = pole
        misii[mid] = m

    for o in sorted(obekti(baza), key=lambda x: str(x["id"])):
        if o.get("rayon") != rayon:
            continue
        for oblast in red_oblasti:
            nastr = cfg["oblasti"][oblast]
            if o.get("tip") not in nastr["tipove"]:
                continue
            for prichina, uslovie in (
                ("karta_bez_registar", o.get("izvor") == "karta" and _prazno(o.get("registar_id"))),
                ("registar_bez_karta", o.get("izvor") == "registar" and (_prazno(o.get("lat")) or _prazno(o.get("lon")))),
                ("iztekla_proverka", (_data(o.get("proveren_na")) or den) < srok),
            ):
                if uslovie:
                    vid, vapros, poleta = SPECIALNI[prichina]
                    dobavi(o, oblast, vid, vapros, poleta, prichina)
            for pole, m in sorted(nastr.get("poleta", {}).items()):
                if m.get("samo_tipove") and o.get("tip") not in m["samo_tipove"]:
                    continue
                if _prazno(o.get(pole)):
                    dobavi(o, oblast, m["vid"], m["vapros"], m["poleta"], "lipsva_pole", pole)

    spisak = sorted(misii.values(), key=lambda m: (OBLASTI.index(m["oblast"]), str(m["obekt"]["id"]), m["id"]))
    spisak = spisak[:int(cfg["maks_misii_na_rayon"])]
    return {"rayon": rayon, "izdaden": den.isoformat(), "versiya": VERSIYA, "oblasti": red_oblasti, "misii": spisak}
