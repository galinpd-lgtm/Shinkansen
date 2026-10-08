"""Агентски изпит: петте стълба мерят предпоставки, изпитът мери резултат.

С текста на сайта (както го вижда бот без JavaScript) работникът (Gemma 4) отговаря на три въпроса — всеки
с дословен цитат. Кодът проверява цитата; цената трябва да съдържа число. Ако има пазач (nemotron-3-super),
той казва само с английски код дали цитатът отговаря на въпроса. Резултат 0–3, отделно от 0–5.
"""
import json
import re

from . import citati
from .model import GreshkaModel
from .pravilnik import IMA, NE, NEPR, dok

NEPOTV = "непотвърдено"
VAPROSI = (
    ("offer", "какво предлагате", "What does this organisation offer?"),
    ("price", "колко струва поне едно нещо", "What does at least one thing cost? Give a price."),
    ("order", "как се заявява", "How does one order, book or request it?"),
)
MAKS_ZNAKA = 16000
MIN_DUMI = 3

SISTEMA = (
    "You answer questions about a website using ONLY the given page text. Answer ONLY JSON: "
    "{\"answers\": [{\"code\": \"<code>\", \"found\": true|false, \"answer\": \"<short>\", \"quote\": \"<verbatim>\"}]}. "
    "The quote MUST be copied verbatim from the page text. If the text does not answer, found=false. Codes: "
    + "; ".join("%s = %s" % (k, en) for k, _, en in VAPROSI) + "."
)
SISTEMA_PAZACH = (
    "You check whether a quote answers a question. Answer ONLY JSON with English codes: "
    "{\"verdict\": \"answers\"} or {\"verdict\": \"does_not_answer\"}. No other text."
)


def izpitai(model, z, tekst):
    if not tekst:
        return {"sastoyanie": NEPR, "prichina": "няма прочетен текст", "otgovori": [], "tochki": 0, "ot": len(VAPROSI)}
    try:
        d = model.chat("rabotnik", SISTEMA, tekst[:MAKS_ZNAKA])
    except GreshkaModel as e:
        return {"sastoyanie": NEPR, "prichina": str(e), "otgovori": [], "tochki": 0, "ot": len(VAPROSI)}
    po_kod = {}
    for it in d.get("answers") or []:
        if isinstance(it, dict) and it.get("code") in {k for k, _, _ in VAPROSI}:
            po_kod.setdefault(it["code"], it)
    pazach = model.ima("pazach")
    otgovori = []
    for kod, vapros, en in VAPROSI:
        it = po_kod.get(kod) or {}
        if not it.get("found"):
            otgovori.append({"kod": kod, "vapros": vapros, "sastoyanie": NE, "dokazatelstvo": [dok(z, selektor="видим текст")],
                             "belezhka": "работникът не намира отговор в текста"})
            continue
        citat = str(it.get("quote") or "")
        ok, prich = citati.proveri(citat, tekst, MIN_DUMI)
        if ok and kod == "price" and not re.search(r"\d", citat):
            ok, prich = False, "цитатът за цена няма число"
        if ok and pazach:
            try:
                p = model.chat("pazach", SISTEMA_PAZACH, json_vapros(en, citat))
                if p.get("verdict") != "answers":
                    ok, prich = False, "пазачът: цитатът не отговаря на въпроса (%s)" % p.get("verdict")
            except GreshkaModel as e:
                prich_p = "пазачът не е питан: %s" % e
                otgovori.append({"kod": kod, "vapros": vapros, "sastoyanie": IMA, "citat": citat, "otgovor": it.get("answer"),
                                 "dokazatelstvo": [dok(z, selektor="видим текст", otkas=citat)], "belezhka": prich_p})
                continue
        if ok:
            otgovori.append({"kod": kod, "vapros": vapros, "sastoyanie": IMA, "citat": citat, "otgovor": it.get("answer"),
                             "dokazatelstvo": [dok(z, selektor="видим текст", otkas=citat)]})
        else:
            # отговор без потвърден цитат не излиза навън — пази се само причината
            otgovori.append({"kod": kod, "vapros": vapros, "sastoyanie": NEPOTV, "prichina": prich})
    return {"sastoyanie": IMA, "model": model.ime("rabotnik"), "pazach": model.ime("pazach") if pazach else None,
            "otgovori": otgovori, "tochki": sum(1 for o in otgovori if o["sastoyanie"] == IMA), "ot": len(VAPROSI)}


def json_vapros(vapros, citat):
    return json.dumps({"question": vapros, "quote": citat}, ensure_ascii=False)
