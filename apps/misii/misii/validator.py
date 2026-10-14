"""Валидатор: JSON Schema (подмножеството, което ползват схемите в `shemi/`) + правилата, които схемата не казва.

Само стандартната библиотека. Поддържа: type, enum, const, properties, required, additionalProperties,
maxProperties, items, minItems, maxItems, minLength, maxLength, pattern, minimum, maximum, format "date" и $ref
към съседна схема по $id. Непозната ключова дума в схема е грешка в схемата — не се пренебрегва тихо.

Правилата отгоре:
- участие: пълнолетен или през родител/учител — дете само не участва;
- автор: при „псевдоним“ и „име“ — има име; при „анонимно“ — няма;
- лични данни: в свободния текст не се приемат лични имейли (общите като info@ минават) и телефонни номера
  (поне 9 цифри, започва с + или 0; ЕИК и дати не са телефон);
- никакви класации: в стойностите няма полета за оценка, точки или рейтинг.
"""
import datetime
import json
import os
import re

from .config import APP

SHEMI = os.path.join(APP, "shemi")
VIDOVE_DOKUMENTI = ("misiya", "otgovor", "prinos", "spisak")
POZNATI = {"$schema", "$id", "title", "description", "type", "enum", "const", "properties", "required",
           "additionalProperties", "maxProperties", "items", "minItems", "maxItems", "minLength", "maxLength",
           "pattern", "minimum", "maximum", "format", "$ref"}
TIPOVE = {
    "object": lambda x: isinstance(x, dict),
    "array": lambda x: isinstance(x, list),
    "string": lambda x: isinstance(x, str),
    "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
    "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
    "boolean": lambda x: isinstance(x, bool),
    "null": lambda x: x is None,
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TELEFON_RE = re.compile(r"(?<!\d)\+?\d[\d\s/().-]{6,}\d(?!\d)")
DATA_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
KLASACII = ("ocenka", "otsenka", "reyting", "rating", "tochki", "klasirane", "rank", "zvezdi", "stars")


class GreshkaShema(Exception):
    """Самата схема е счупена (непозната дума, липсващ $ref) — това е грешка в репото, не във входа."""


_kesh = {}


def shema(ime):
    """Схема по $id (напр. „misiya.schema.json“) или по кратко име („misiya“)."""
    if not ime.endswith(".json"):
        ime += ".schema.json"
    if ime not in _kesh:
        pat = os.path.join(SHEMI, os.path.basename(ime))
        try:
            with open(pat, encoding="utf-8") as f:
                _kesh[ime] = json.load(f)
        except (OSError, ValueError) as e:
            raise GreshkaShema("няма или е неразбираема схемата %s: %s" % (ime, e))
    return _kesh[ime]


def _dat(s):
    try:
        datetime.date.fromisoformat(s)
        return len(s) == 10
    except ValueError:
        return False


def _proveri(x, sh, pat, greshki):
    nepoznati = set(sh) - POZNATI
    if nepoznati:
        raise GreshkaShema("непозната ключова дума в схемата: %s" % ", ".join(sorted(nepoznati)))
    if "$ref" in sh:
        _proveri(x, shema(sh["$ref"]), pat, greshki)
        return
    if "type" in sh:
        t = sh["type"] if isinstance(sh["type"], list) else [sh["type"]]
        if not any(TIPOVE[ti](x) for ti in t):
            greshki.append("%s: трябва да е %s" % (pat, " или ".join(t)))
            return
    if "enum" in sh and x not in sh["enum"]:
        greshki.append("%s: „%s“ не е позволено (позволени: %s)" % (pat, x, ", ".join(map(str, sh["enum"]))))
    if "const" in sh and x != sh["const"]:
        greshki.append("%s: трябва да е „%s“" % (pat, sh["const"]))
    if isinstance(x, str):
        if len(x) < sh.get("minLength", 0):
            greshki.append("%s: под %d знака" % (pat, sh["minLength"]))
        if "maxLength" in sh and len(x) > sh["maxLength"]:
            greshki.append("%s: над %d знака" % (pat, sh["maxLength"]))
        if "pattern" in sh and not re.search(sh["pattern"], x):
            greshki.append("%s: не отговаря на образеца %s" % (pat, sh["pattern"]))
        if sh.get("format") == "date" and not _dat(x):
            greshki.append("%s: трябва да е дата ГГГГ-ММ-ДД" % pat)
    if TIPOVE["number"](x):
        if "minimum" in sh and x < sh["minimum"]:
            greshki.append("%s: под %s" % (pat, sh["minimum"]))
        if "maximum" in sh and x > sh["maximum"]:
            greshki.append("%s: над %s" % (pat, sh["maximum"]))
    if isinstance(x, list):
        if len(x) < sh.get("minItems", 0):
            greshki.append("%s: под %d елемента" % (pat, sh["minItems"]))
        if "maxItems" in sh and len(x) > sh["maxItems"]:
            greshki.append("%s: над %d елемента" % (pat, sh["maxItems"]))
        if "items" in sh:
            for i, y in enumerate(x):
                _proveri(y, sh["items"], "%s[%d]" % (pat, i), greshki)
    if isinstance(x, dict):
        for k in sh.get("required", []):
            if k not in x:
                greshki.append("%s: липсва полето „%s“" % (pat, k))
        if "maxProperties" in sh and len(x) > sh["maxProperties"]:
            greshki.append("%s: над %d полета" % (pat, sh["maxProperties"]))
        props = sh.get("properties", {})
        dop = sh.get("additionalProperties", True)
        for k, v in x.items():
            if k in props:
                _proveri(v, props[k], "%s.%s" % (pat, k), greshki)
            elif dop is False:
                greshki.append("%s: непознато поле „%s“" % (pat, k))
            elif isinstance(dop, dict):
                _proveri(v, dop, "%s.%s" % (pat, k), greshki)


def po_shema(x, ime):
    """→ списък с грешки (празен = валидно) само по JSON Schema."""
    greshki = []
    _proveri(x, shema(ime), "$", greshki)
    return greshki


# ─────────── правилата отгоре ───────────

def _lichni_v_tekst(tekst, obshti):
    problemi = []
    for e in EMAIL_RE.findall(tekst or ""):
        if e.split("@")[0].lower() not in obshti:
            problemi.append("личен имейл в текста — приемат се само общи адреси (info@, office@ …)")
            break
    for m in TELEFON_RE.finditer(tekst or ""):
        kandidat = m.group(0).strip()
        predi = (tekst[max(0, m.start() - 12):m.start()]).upper()
        if (kandidat[0] in "+0" and sum(c.isdigit() for c in kandidat) >= 9 and not DATA_RE.fullmatch(kandidat)
                and not any(w in predi for w in ("ЕИК", "БУЛСТАТ", "EIK", "UIC"))):
            problemi.append("телефонен номер в текста — не се приема (лични данни)")
            break
    return problemi


def _pravila_uchastnik(d, cfg):
    g = []
    u = d.get("uchastie") or {}
    if not (u.get("palnoleten") is True or u.get("prez") in ("roditel", "uchitel")):
        g.append("участие: само пълнолетни; до 18 г. — през родител или учител")
    a = d.get("avtor") or {}
    if a.get("podpis") in ("psevdonim", "ime") and not (a.get("ime") or "").strip():
        g.append("автор: избран е подпис „%s“, но няма име" % a.get("podpis"))
    if a.get("podpis") == "anonimno" and a.get("ime"):
        g.append("автор: при „anonimno“ не се пази име")
    obshti = {x.lower() for x in cfg.get("obshti_adresi", [])}
    tekstove = [d.get("tekst"), d.get("zaglavie")] + [v for v in (d.get("stoynosti") or {}).values() if isinstance(v, str)]
    for t in tekstove:
        for p in _lichni_v_tekst(t, obshti):
            if p not in g:
                g.append(p)
    for k in (d.get("stoynosti") or {}):
        if any(w in k.lower() for w in KLASACII):
            g.append("стойности: „%s“ — без оценки, точки и класации" % k)
    return g


def validirai(x, vid, cfg):
    """→ списък с грешки по схемата и по правилата. `vid`: misiya | otgovor | prinos | spisak."""
    if vid not in VIDOVE_DOKUMENTI:
        raise ValueError("непознат вид документ: %s" % vid)
    g = po_shema(x, vid)
    if g or not isinstance(x, dict):
        return g
    if vid in ("otgovor", "prinos"):
        g += _pravila_uchastnik(x, cfg)
        if vid == "prinos" and not (x.get("tekst") or x.get("snimki")):
            g.append("приносът няма нито текст, нито снимка")
    if vid == "spisak":
        ids = [m["id"] for m in x["misii"]]
        if len(ids) != len(set(ids)):
            g.append("повторен id на мисия в списъка")
        chuzhdi = sorted({m["rayon"] for m in x["misii"]} - {x["rayon"]})
        if chuzhdi:
            g.append("мисии от друг район в списъка: %s" % ", ".join(chuzhdi))
    return g
