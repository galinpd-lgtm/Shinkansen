"""Пълният път: 7 оси → похвати → крайна оценка → решение → синтез за читателя.

Без модел: правила, шингли и евристики — детерминирано, работи навсякъде.
С модел: по един кратък промпт на ос (само JSON: оценка + едно изречение), един промпт за похватите,
после синтезиращ промпт. Крайната оценка, оценката по думи и решението се смятат в кода, за да са
повторими; моделът пише само текста за читателя.
"""
import json
import re

from . import VERSIYA, osi, pohvati
from .config import OSI_KLUCHOVE
from .model import GreshkaSadarzhanie
from .reshenie import reshi
from .tekst import ima_otkas, normalizirai

SISTEMA = ("Ти си внимателен редактор. Оценяваш текст на български. Описваш какво има и какво липсва "
           "в текста; не присъждаш дали е верен. Отговаряш само с JSON, на прост български, "
           "с кратки изречения.")

PROMPT_OS = {
    "proverimost": "Извлечи фактическите твърдения в текста и отбележи кои имат посочен източник или "
                   "документ. Оценка 10 = всички твърдения имат източник, 0 = нито едно.",
    "prozrachnost": "Преброй именуваните и анонимните източници и цитираните официални документи. "
                    "Оценка 10 = всички източници са назовани, 0 = само анонимни или никакви.",
    "obshtestven_interes": "Засяга ли текстът хора, пари, права или обществени услуги? Реклама или PR "
                           "получава ниска оценка. Оценка 10 = пряко засяга много хора.",
    "palnota": "Има ли текстът кой, какво, кога, къде и защо? Оценка 10 = има всичките пет.",
}
FORMA_OS = 'Върни само JSON: {"ocenka": число от 0 до 10, "zashto": "едно изречение"}.'

ZABRANENI = re.compile(r"лъж\w*|фалшив\w*\s+новин\w*|фейк\w*", re.IGNORECASE | re.UNICODE)
NEUTRALNO = "Формулировката на модела е пропусната; вижте осите и похватите."


def chisto(s):
    """Инструментът описва, не присъжда: изречение с „лъжа“/„фалшива новина“ не стига до читателя."""
    s = normalizirai(str(s or ""))
    return NEUTRALNO if ZABRANENI.search(s) else s


def _tekst_za_modela(tekst):
    return "ТЕКСТ:\n<<<\n%s\n>>>" % tekst.strip()


# ─────────── оси ───────────

def _os_s_model(model, kluch, tekst):
    otg = model.chat("struktura", SISTEMA, "%s\n%s\n\n%s" % (PROMPT_OS[kluch], FORMA_OS, _tekst_za_modela(tekst)))
    try:
        oc = osi.ogranichi(float(otg["ocenka"]))
    except (KeyError, TypeError, ValueError):
        raise GreshkaSadarzhanie("няма оценка")
    return oc, chisto(otg.get("zashto")) or "Моделът не даде обяснение."


# ─────────── похвати ───────────

def _pohvati_s_model(model, tekst, strah):
    kluchove = list(pohvati.SAMO_MODEL) + ["appeal_to_fear"]
    spisak = "\n".join("- %s: %s — %s" % (k, pohvati.POHVATI[k][0], pohvati.POHVATI[k][3]) for k in kluchove)
    podskazka = ""
    if strah:
        podskazka = ("\nВ текста има думи за опасност/заплаха (напр. в: „%s“). Потвърди appeal_to_fear "
                     "само ако текстът наистина плаши без мярка." % strah)
    otg = model.chat("struktura", SISTEMA,
                     "Кои от тези манипулативни похвати има в текста?\n%s%s\n\n"
                     'Върни само JSON: {"pohvati": [{"kluch": "...", "otkas": "точен откъс от текста", '
                     '"obyasnenie": "едно изречение"}]}. Откъсът трябва да е дословно от текста. '
                     'Ако няма похвати, върни {"pohvati": []}.\n\n%s' % (spisak, podskazka, _tekst_za_modela(tekst)))
    nam, vidyani = [], set()
    for p in (otg.get("pohvati") or []) if isinstance(otg, dict) else []:
        if not isinstance(p, dict):
            continue
        k, otkas = p.get("kluch"), normalizirai(p.get("otkas"))
        if k not in kluchove or k in vidyani:
            continue
        if k == "appeal_to_fear" and not strah:
            continue  # думи + потвърждение: без думите моделът сам не стига
        if not ima_otkas(tekst, otkas):
            continue  # откъс, който го няма в текста, не се показва
        vidyani.add(k)
        nam.append(pohvati.zapis(k, otkas, chisto(p.get("obyasnenie")) or pohvati.POHVATI[k][3].capitalize() + "."))
    return nam


# ─────────── синтез ───────────

def _sintez_evristika(rez):
    silni = ["%s: %s" % (o["ime"], o["zashto"]) for o in rez["osi"] if o["ocenka"] >= 7.0]
    slabi = ["%s: %s" % (o["ime"], o["zashto"]) for o in rez["osi"] if o["ocenka"] <= 4.0]
    slabi += ["Открит похват: %s — „%s“" % (p["ime"], p["otkas"]) for p in rez["pohvati"]]
    preporaka = {
        "PROPUSNI": "Може да се чете без особени резерви.",
        "PREDUPREDI": "Четете внимателно и проверете отбелязаните места.",
        "KARANTINA": "Преди да се позовете на текста, потърсете и друг, независим източник.",
    }[rez["reshenie"]["kod"]]
    naj_slaba = min(rez["osi"], key=lambda o: o["ocenka"])
    za = "Оценка %.1f от 10 (%s). Най-слабо: %s." % (rez["krayna_ocenka"], rez["po_dumi"].lower(),
                                                      naj_slaba["ime"].lower())
    return {"za_chitatelya": za, "silni": silni, "slabi": slabi, "preporaka": preporaka}


def _sintez_s_model(model, rez):
    danni = {
        "krayna_ocenka": rez["krayna_ocenka"], "po_dumi": rez["po_dumi"], "reshenie": rez["reshenie"]["ime"],
        "osi": [{"ime": o["ime"], "ocenka": o["ocenka"], "zashto": o["zashto"]} for o in rez["osi"]],
        "pohvati": [{"ime": p["ime"], "otkas": p["otkas"]} for p in rez["pohvati"]],
    }
    otg = model.chat("pisach", SISTEMA,
                     "Ето оценката на един текст по седем оси. Крайната оценка и решението вече са сметнати — "
                     "не ги променяй. Напиши за обикновен читател.\n"
                     'Върни само JSON: {"za_chitatelya": "едно изречение", "silni": ["..."], '
                     '"slabi": ["..."], "preporaka": "едно изречение"}.\n\n'
                     + json.dumps(danni, ensure_ascii=False))
    rezerva = _sintez_evristika(rez)
    if not isinstance(otg, dict):
        return rezerva
    spisak = lambda v: [chisto(x) for x in v if str(x).strip()] if isinstance(v, list) else None  # noqa: E731
    return {
        "za_chitatelya": chisto(otg.get("za_chitatelya")) or rezerva["za_chitatelya"],
        "silni": spisak(otg.get("silni")) if spisak(otg.get("silni")) is not None else rezerva["silni"],
        "slabi": spisak(otg.get("slabi")) if spisak(otg.get("slabi")) is not None else rezerva["slabi"],
        "preporaka": chisto(otg.get("preporaka")) or rezerva["preporaka"],
    }


# ─────────── главният вход ───────────

def ocenka(tekst, cfg, model=None, iztochnik=None, avtor=None, vidyani=None, zapomni=False):
    """Оценява текста. model=None → режим без модел. Връща dict по схемата от README.

    avtor се пази в изхода, но не се оценява (без профили на отделни хора).
    VrataNeBezopasno (заето, недостъпна врата, няма врата) / GreshkaModel се пропускат нагоре — моделът не се вика повече.
    """
    tekst = tekst or ""
    s_model = model is not None
    belezhki = []

    # похвати: правилата винаги, моделът — ако го има
    namereni = pohvati.po_pravila(tekst, s_model=s_model, ai_flag_ot=cfg["reshenie"]["ai_flag_ot"])
    if s_model:
        _, strah = pohvati.strah_kandidat(tekst)
        try:
            namereni += _pohvati_s_model(model, tekst, strah)
        except GreshkaSadarzhanie:
            belezhki.append("Моделът не върна похватите в нужния вид — показани са само тези по правила.")
        neprovereni = []
    else:
        neprovereni = list(pohvati.SAMO_MODEL)
    red = list(pohvati.POHVATI)
    namereni.sort(key=lambda p: red.index(p["kluch"]))

    # оси
    zap = {}
    oc, za = osi.reputaciya(iztochnik, cfg)
    zap["reputaciya"] = osi.os_zapis("reputaciya", oc, za, cfg, "регистър")
    oc, za, sh = osi.originalnost(tekst, cfg, vidyani)
    zap["originalnost"] = osi.os_zapis("originalnost", oc, za, cfg, "шингли")
    oc, za = osi.manipulaciya(namereni)
    zap["manipulaciya"] = osi.os_zapis("manipulaciya", oc, za, cfg, "похвати")
    for k in osi.S_MODEL:
        if s_model:
            try:
                oc, za = _os_s_model(model, k, tekst)
                zap[k] = osi.os_zapis(k, oc, za, cfg, "модел")
                continue
            except GreshkaSadarzhanie:
                belezhki.append("%s: моделът не върна оценка — ползвана е евристиката." % osi.IMENA[k])
        oc, za = osi.EVRISTIKI[k](tekst)
        zap[k] = osi.os_zapis(k, oc, za, cfg, "евристика")
    spisak_osi = [zap[k] for k in OSI_KLUCHOVE]

    krayna = osi.krayna(spisak_osi, cfg)
    rez = {
        "versiya": VERSIYA,
        "rezhim": "model" if s_model else "bez-model",
        "iztochnik": {"domain": osi.domain(iztochnik), "avtor": avtor or None, "avtor_se_ocenyava": False},
        "osi": spisak_osi,
        "pohvati": namereni,
        "neprovereni_pohvati": neprovereni,
        "krayna_ocenka": krayna,
        "po_dumi": osi.po_dumi(krayna, cfg),
    }
    rez["reshenie"] = reshi(krayna, namereni, spisak_osi, cfg)
    if s_model:
        try:
            rez["sintez"] = _sintez_s_model(model, rez)
        except GreshkaSadarzhanie:
            belezhki.append("Синтезът от модела не беше в нужния вид — ползван е шаблонът.")
            rez["sintez"] = _sintez_evristika(rez)
    else:
        rez["sintez"] = _sintez_evristika(rez)
    rez["belezhki"] = belezhki

    if zapomni and cfg.get("pamet"):
        osi.pamet_zapis(cfg["pamet"], sh)
    return rez


# ─────────── текстов отчет ───────────

def otchet(rez):
    r = ["Достоверност: %.1f / 10 — %s" % (rez["krayna_ocenka"], rez["po_dumi"]),
         "Решение: %s (%s)" % (rez["reshenie"]["ime"], "; ".join(rez["reshenie"]["prichini"])),
         "Режим: %s" % ("с модел" if rez["rezhim"] == "model" else "без модел (само правила и евристики)"),
         "", "Оси:"]
    for o in rez["osi"]:
        r.append("  %-28s %4.1f  (%2d%%)  %s" % (o["ime"], o["ocenka"], round(o["teglo"] * 100), o["zashto"]))
    r.append("")
    if rez["pohvati"]:
        r.append("Открити похвати (%d):" % len(rez["pohvati"]))
        for p in rez["pohvati"]:
            ver = " — вероятност %.2f" % p["veroyatnost"] if "veroyatnost" in p else ""
            r.append("  − %s (−%.1f)%s: „%s“" % (p["ime"], p["nakazanie"], ver, p["otkas"]))
            r.append("    %s" % p["obyasnenie"])
    else:
        r.append("Открити похвати: няма.")
    if rez["neprovereni_pohvati"]:
        r.append("Непроверени без модел: %s." % ", ".join(pohvati.POHVATI[k][0] for k in rez["neprovereni_pohvati"]))
    s = rez["sintez"]
    r += ["", "За читателя: %s" % s["za_chitatelya"], "Препоръка: %s" % s["preporaka"]]
    for b in rez.get("belezhki") or []:
        r.append("Бележка: %s" % b)
    return "\n".join(r)
