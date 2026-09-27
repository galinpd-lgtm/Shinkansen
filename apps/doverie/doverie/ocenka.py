"""Пълният път: 7 оси → похвати → крайна оценка → решение → синтез за читателя.

Без модел: правила, шингли и евристики — детерминирано, работи навсякъде.
С модел: по един кратък промпт на ос (само JSON: оценка + едно изречение), един промпт за похватите,
после синтезиращ промпт. Крайната оценка, оценката по думи и решението се смятат в кода, за да са
повторими; моделът пише само текста за читателя.
"""
import hashlib
import json
import re

from . import VERSIYA, osi, pohvati
from .config import OSI_KLUCHOVE
from .model import GreshkaSadarzhanie
from .reshenie import reshi
from .tekst import dumi, ima_otkas, normalizirai

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
FORMA_PROVERIMOST = ('Върни само JSON: {"ocenka": число от 0 до 10, "zashto": "едно изречение", '
                     '"tvardenia": брой извлечени фактически твърдения, "s_iztochnik": колко от тях имат посочен '
                     'източник или документ}.')
PROMPT_VAPROSI = ("Отговори за всеки от тези въпроси дали текстът отговаря на него: „да“, „частично“ или „не“.\n%s\n"
                  'Върни само JSON: {"otgovori": {%s}, "zashto": "едно изречение"}.')
OTGOVORI = {"да": "да", "частично": "частично", "не": "не", "yes": "да", "partial": "частично", "no": "не",
            "1": "да", "0.5": "частично", "0": "не"}

ZABRANENI = re.compile(r"лъж\w*|фалшив\w*\s+новин\w*|фейк\w*", re.IGNORECASE | re.UNICODE)
NEUTRALNO = "Формулировката на модела е пропусната; вижте осите и похватите."


def chisto(s):
    """Инструментът описва, не присъжда: изречение с „лъжа“/„фалшива новина“ не стига до читателя."""
    s = normalizirai(str(s or ""))
    return NEUTRALNO if ZABRANENI.search(s) else s


def _tekst_za_modela(tekst):
    return "ТЕКСТ:\n<<<\n%s\n>>>" % tekst.strip()


# ─────────── оси ───────────

def _os_s_model(model, kluch, tekst, cfg):
    """→ (оценка, защо, допълнително). Допълнително: броят твърдения (проверимост) или 10-те отговора (пълнота)."""
    if kluch == "palnota":
        return _palnota_s_model(model, tekst, cfg["palnota_vaprosi"])
    forma = FORMA_PROVERIMOST if kluch == "proverimost" else FORMA_OS
    otg = model.chat("struktura", SISTEMA, "%s\n%s\n\n%s" % (PROMPT_OS[kluch], forma, _tekst_za_modela(tekst)))
    try:
        oc = osi.ogranichi(float(otg["ocenka"]))
    except (KeyError, TypeError, ValueError):
        raise GreshkaSadarzhanie("няма оценка")
    dop = None
    if kluch == "proverimost":
        try:
            n, m = int(otg["tvardenia"]), int(otg["s_iztochnik"])
            if 0 <= m <= n:
                dop = (n, m)
        except (KeyError, TypeError, ValueError):
            pass
    return oc, chisto(otg.get("zashto")) or "Моделът не даде обяснение.", dop


def _palnota_s_model(model, tekst, vaprosi):
    spisak = "\n".join("- %s: %s" % (v["kluch"], v["vapros"]) for v in vaprosi)
    kluchove = ", ".join('"%s": "да|частично|не"' % v["kluch"] for v in vaprosi)
    otg = model.chat("struktura", SISTEMA, "%s\n\n%s" % (PROMPT_VAPROSI % (spisak, kluchove), _tekst_za_modela(tekst)))
    surovi = otg.get("otgovori") if isinstance(otg, dict) else None
    if not isinstance(surovi, dict):
        raise GreshkaSadarzhanie("няма отговори на въпросите")
    otgovori = []
    for v in vaprosi:
        o = OTGOVORI.get(str(surovi.get(v["kluch"], "")).strip().lower())
        if o is None:
            raise GreshkaSadarzhanie("липсва отговор на „%s“" % v["vapros"])
        otgovori.append({"kluch": v["kluch"], "vapros": v["vapros"], "otgovor": o})
    return osi.ocenka_vaprosi(otgovori), chisto(otg.get("zashto")) or osi.zashto_vaprosi(otgovori), otgovori


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


# ─────────── профил на доверие ───────────

CHOVEK = ("не", "одобрено в сводка", "проверено от човек")


def _izmereno_s(o, pohvati_s_model):
    if o["kluch"] == "manipulaciya":
        return "модел" if pohvati_s_model else "правила"
    return "модел" if o["izvor"] == "модел" else "правила"


def uverenost(s_model, n_dumi, pokritie, razliki, neopredelimi, cfg):
    """Проста и повторима: ниска / висока по правилата от config, иначе средна. Всяка причина се изписва."""
    u = cfg["uverenost"]
    niski = []
    if not s_model:
        niski.append("без модел — само правила и евристики")
    if n_dumi < u["niska_pod_dumi"]:
        niski.append("текстът е под %d думи (%d)" % (u["niska_pod_dumi"], n_dumi))
    if pokritie["tvardenia"] < u["niska_pod_tvardeniya"]:
        niski.append("под %d твърдения (%d)" % (u["niska_pod_tvardeniya"], pokritie["tvardenia"]))
    for ime, r in razliki:
        if r > u["niska_razlika_nad"]:
            niski.append("правилата и моделът се разминават с %.1f по оста „%s“" % (r, ime))
    if neopredelimi:
        niski.append("%d от въпросите за пълнота не могат да се определят без модел" % neopredelimi)
    if niski:
        return {"nivo": "ниска", "prichini": niski}

    visoki, lipsva = [], []
    visoki.append("с модел")
    (visoki if n_dumi >= u["visoka_ot_dumi"] else lipsva).append(
        "%d думи (%s %d)" % (n_dumi, "≥" if n_dumi >= u["visoka_ot_dumi"] else "под", u["visoka_ot_dumi"]))
    dyal = pokritie["dyal"] or 0.0
    (visoki if dyal >= u["visoka_ot_pokritie"] else lipsva).append(
        "покритие с доказателства %d%% (%s %d%%)" % (round(100 * dyal), "≥" if dyal >= u["visoka_ot_pokritie"] else "под",
                                                    round(100 * u["visoka_ot_pokritie"])))
    nay = max((r for _, r in razliki), default=0.0)
    (visoki if nay <= u["visoka_razlika_do"] else lipsva).append(
        "най-голямата разлика между правила и модел е %.1f (%s %s)" % (
            nay, "до" if nay <= u["visoka_razlika_do"] else "над", u["visoka_razlika_do"]))
    if not lipsva:
        return {"nivo": "висока", "prichini": visoki}
    return {"nivo": "средна", "prichini": lipsva}


def profil(spisak_osi, pravila, s_model, pohvati_s_model, tekst, pokritie, neopredelimi, krayna, po_dumi, cfg):
    osi_p, razliki = {}, []
    for i, o in enumerate(spisak_osi, 1):
        z = {"kluch": o["kluch"], "ime": o["ime"], "ocenka": o["ocenka"], "zashto": o["zashto"],
             "izmereno_s": _izmereno_s(o, pohvati_s_model)}
        if "vaprosi" in o:
            z["vaprosi"] = o["vaprosi"]
        if o["kluch"] in pravila and z["izmereno_s"] == "модел":
            z["pravila"] = osi.okragli(pravila[o["kluch"]])
            z["razlika"] = osi.okragli(abs(o["ocenka"] - z["pravila"]))
            razliki.append((o["ime"], z["razlika"]))
        osi_p[str(i)] = z
    return {
        "osi": osi_p,
        "uverenost": uverenost(s_model, len(dumi(tekst)), pokritie, razliki, neopredelimi, cfg),
        "pokritie_s_dokazatelstva": pokritie,
        "chovek": CHOVEK[0],  # ядрото само винаги пише „не“
        "obshta_ocenka": krayna,
        "po_dumi": po_dumi,
    }


def id_na_tekst(tekst):
    return hashlib.sha256(normalizirai(tekst).encode("utf-8")).hexdigest()[:16]


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
    # правилата се смятат винаги — с модел служат за сравнение (увереност)
    pravila = {k: osi.EVRISTIKI[k](tekst, cfg)[0] for k in osi.S_MODEL}
    oc7, za7, vaprosi_pravila = osi.palnota(tekst, cfg)
    n_tv, m_tv = osi.tvardeniya(tekst)
    pokritie = {"tvardenia": n_tv, "s_iztochnik": m_tv, "grubo": True,
                "kak": "груба мярка без модел: изречения с число или цитат; с източник — тези с атрибуция"}
    vaprosi = vaprosi_pravila
    for k in osi.S_MODEL:
        if s_model:
            try:
                oc, za, dop = _os_s_model(model, k, tekst, cfg)
                zap[k] = osi.os_zapis(k, oc, za, cfg, "модел")
                if k == "palnota":
                    vaprosi = dop
                elif k == "proverimost" and dop:
                    pokritie = {"tvardenia": dop[0], "s_iztochnik": dop[1], "grubo": False,
                                "kak": "твърденията са извлечени от модела"}
                continue
            except GreshkaSadarzhanie:
                belezhki.append("%s: моделът не върна оценка — ползвана е евристиката." % osi.IMENA[k])
        if k == "palnota":
            zap[k] = osi.os_zapis(k, oc7, za7, cfg, "евристика")
        else:
            oc, za = osi.EVRISTIKI[k](tekst, cfg)
            zap[k] = osi.os_zapis(k, oc, za, cfg, "евристика")
    zap["palnota"]["vaprosi"] = vaprosi
    neopredelimi = sum(1 for v in vaprosi if v["otgovor"] == osi.NEOPREDELIMO)
    if neopredelimi:
        belezhki.append("Контекстна пълнота: %d от %d въпроса не могат да се определят без модел — оста е смятана от "
                        "останалите %d и мащабирана до 10." % (neopredelimi, len(vaprosi), len(vaprosi) - neopredelimi))
    pokritie["dyal"] = round(pokritie["s_iztochnik"] / pokritie["tvardenia"], 2) if pokritie["tvardenia"] else None
    spisak_osi = [zap[k] for k in OSI_KLUCHOVE]

    krayna = osi.krayna(spisak_osi, cfg)
    po_dumi = osi.po_dumi(krayna, cfg)
    pohvati_s_model = s_model and not any(b.startswith("Моделът не върна похватите") for b in belezhki)
    rez = {
        "profil": profil(spisak_osi, pravila, s_model, pohvati_s_model, tekst, pokritie, neopredelimi,
                         krayna, po_dumi, cfg),
        "id": id_na_tekst(tekst),
        "versiya": VERSIYA,
        "rezhim": "model" if s_model else "bez-model",
        "iztochnik": {"domain": osi.domain(iztochnik), "avtor": avtor or None, "avtor_se_ocenyava": False},
        "osi": spisak_osi,
        "pohvati": namereni,
        "neprovereni_pohvati": neprovereni,
        "krayna_ocenka": krayna,
        "po_dumi": po_dumi,
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
    """Същият ред като JSON: първо профилът, после похватите, общата оценка и решението — най-долу."""
    pr = rez["profil"]
    r = ["Профил на доверие (%s)" % ("с модел" if rez["rezhim"] == "model" else "без модел — само правила"), "", "Оси:"]
    for n, o in pr["osi"].items():
        dop = ""
        if "razlika" in o:
            dop = "  [правила %.1f, разлика %.1f]" % (o["pravila"], o["razlika"])
        r.append("  %s. %-28s %4.1f  %-7s %s%s" % (n, o["ime"], o["ocenka"], o["izmereno_s"], o["zashto"], dop))
    u = pr["uverenost"]
    r += ["", "Увереност: %s" % u["nivo"]] + ["  − %s" % p for p in u["prichini"]]
    pk = pr["pokritie_s_dokazatelstva"]
    dyal = "%d%%" % round(100 * pk["dyal"]) if pk["dyal"] is not None else "—"
    r += ["Покритие с доказателства: %d от %d твърдения имат посочен източник (%s)%s" % (
        pk["s_iztochnik"], pk["tvardenia"], dyal, " — груба мярка" if pk["grubo"] else "")]
    r.append("Гледал човек: %s" % pr["chovek"])
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
    r += ["", "Обща оценка: %.1f / 10 — %s" % (pr["obshta_ocenka"], pr["po_dumi"]),
          "Решение: %s (%s)" % (rez["reshenie"]["ime"], "; ".join(rez["reshenie"]["prichini"]))]
    return "\n".join(r)
