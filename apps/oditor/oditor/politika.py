"""Четене на политиката за поверителност: модел (visok_risk — Mistral-Small-4) отбелязва 10 елемента и за
всеки „има“ дава дословен цитат ≥ 6 думи. Кодът търси цитата; ненамерен → „непотвърдено“. Цитат, който
само обявява темата, не се брои. Моделът не оценява законосъобразност — това е сигнал за юрист.
"""
from . import citati, razbor
from .model import GreshkaModel
from .pravilnik import IMA, NE, NEPR, dok

NEPOTV = "непотвърдено"
ELEMENTI = (
    ("controller", "администратор"), ("contact", "контакт"), ("purposes", "цели"), ("legal_basis", "основания"),
    ("recipients", "получатели"), ("retention", "срокове"), ("rights", "права"),
    ("complaint", "жалба до надзорен орган"), ("cookies", "бисквитки"), ("date", "дата"),
)
MAKS_ZNAKA = 24000
MIN_DUMI = 6

SISTEMA = (
    "You read a website privacy policy. For each element code decide if the policy text states it. "
    "Answer ONLY JSON: {\"items\": [{\"code\": \"<code>\", \"present\": true|false, \"quote\": \"<verbatim>\"}]}. "
    "For present=true the quote MUST be copied verbatim from the text, at least 6 words, and must state the "
    "substance itself — not a heading, a table of contents line or an introduction that only announces the topic. "
    "Do not translate. Do not judge legality. Codes: " + ", ".join(k for k, _ in ELEMENTI) + "."
)


def _zaglaviya(r):
    z = [h["tekst"] for h in r["zaglaviya"]]
    z += [a["tekst"] for a in r["vrazki"] if a["href"].startswith("#")]
    return z


def prochiti(model, z):
    """z — записът на заявката за политиката. → речник с 10 елемента, всеки със състояние и доказателство."""
    if not z or z.get("greshka") or z.get("status") != 200:
        prich = "политиката не е прочетена" + (" (HTTP %s)" % z["status"] if z and z.get("status") else "")
        return {"sastoyanie": NEPR, "prichina": prich, "elementi": []}
    r = razbor.razberi(z.get("tyalo"))
    tekst = "\n".join(r["redove"])
    try:
        d = model.chat("visok_risk", SISTEMA, tekst[:MAKS_ZNAKA])
    except GreshkaModel as e:
        return {"sastoyanie": NEPR, "prichina": str(e), "elementi": [], "url": z["url"]}
    po_kod = {}
    for it in d.get("items") or []:
        if isinstance(it, dict) and it.get("code") in dict(ELEMENTI):
            po_kod.setdefault(it["code"], it)
    zagl = _zaglaviya(r)
    elementi = []
    for kod, ime in ELEMENTI:
        it = po_kod.get(kod)
        if not it:
            elementi.append({"kod": kod, "ime": ime, "sastoyanie": NEPR, "prichina": "моделът не отговори за този елемент"})
            continue
        if not it.get("present"):
            elementi.append({"kod": kod, "ime": ime, "sastoyanie": NE, "dokazatelstvo": [dok(z, selektor="текст на политиката")],
                             "belezhka": "моделът не го намира в текста на политиката"})
            continue
        citat = str(it.get("quote") or "")
        ok, prich = citati.proveri(citat, tekst, MIN_DUMI, zagl)
        if ok:
            elementi.append({"kod": kod, "ime": ime, "sastoyanie": IMA, "citat": citat,
                             "dokazatelstvo": [dok(z, selektor="текст на политиката", otkas=citat)]})
        else:
            elementi.append({"kod": kod, "ime": ime, "sastoyanie": NEPOTV, "prichina": prich})
    return {"sastoyanie": IMA, "url": z["url"], "model": model.ime("visok_risk"), "elementi": elementi,
            "potvardeni": sum(1 for e in elementi if e["sastoyanie"] == IMA), "ot": len(ELEMENTI)}
