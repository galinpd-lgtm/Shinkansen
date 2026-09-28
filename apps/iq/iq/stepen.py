"""Числата за един канал и степента от тях. Чиста логика: без файлове, без база.

Степента се дава по средната оценка, закръглена до 1 знак — същото число, което се показва, решава
степента. Ако каналът е в обхвата на степен, но не изпълнява условията ѝ, се проверява следващата надолу.
„Спряна“ никога не идва оттук: тя е само ръчно решение в регистъра.
"""
import math
from datetime import timedelta
from decimal import Decimal

from .dov import OSI_KLUCHOVE, okragli
from .tekstove import chislo, procent


def _sredno(chisla):
    """Средно в точна десетична аритметика, закръглено до 1 знак (9.25 → 9.3, не 9.2 от двоичната грешка)."""
    chisla = list(chisla)
    if not chisla:
        return None
    return okragli(sum(Decimal(str(x)) for x in chisla) / len(chisla))


def period(do, prozorec_dni, ot=None):
    """→ (от, до) включително. Без `ot` — последните `prozorec_dni` дни до `do`."""
    return (ot or do - timedelta(days=prozorec_dni - 1)), do


def chisla(vsichki, ot, do, cfg):
    """Всички записи на канала (от danni.zapisi) → числата за периода [ot, do]."""
    v = [z for z in vsichki if ot <= z["den"] <= do]
    predi = [z for z in vsichki if z["den"] <= do]
    dni = (do - ot).days + 1
    n = len(v)
    parvi = predi[0]["den"] if predi else None
    ch = {
        "period": {"ot": ot.isoformat(), "do": do.isoformat(), "dni": dni},
        "zapisi": n,
        "sredna": _sredno(z["ocenka"] for z in v),
        "dyal_imenuvani": None, "dyal_pohvati": None,
        "parvi_zapis": parvi.isoformat() if parvi else None,
        "istoriya_dni": (do - parvi).days + 1 if parvi else 0,
        "osi": {}, "sedmici": [], "sedmici_s_publikacii": 0, "pohvati": [],
        "bez_model": sum(1 for z in v if z["rezhim"] == "bez-model"),
        "uverenost": {}, "provereni_ot_chovek": sum(1 for z in v if z["chovek"] == "проверено от човек"),
    }
    if n:
        prag = cfg["imenuvani_prag"]
        ch["dyal_imenuvani"] = round(sum(1 for z in v if z["osi"].get("prozrachnost", 0) >= prag) / n, 4)
        ch["dyal_pohvati"] = round(sum(1 for z in v if z["pohvati"]) / n, 4)
    for k in OSI_KLUCHOVE:
        ch["osi"][k] = _sredno(z["osi"][k] for z in v if k in z["osi"])
    for z in v:
        u = z["uverenost"] or "неизвестна"
        ch["uverenost"][u] = ch["uverenost"].get(u, 0) + 1

    # седмици назад от „до“: последната седмица е [до−6, до]; в изхода — от най-старата
    for i in reversed(range(math.ceil(dni / 7))):
        krai = do - timedelta(days=7 * i)
        nach = max(ot, krai - timedelta(days=6))
        s = [z for z in v if nach <= z["den"] <= krai]
        ch["sedmici"].append({"ot": nach.isoformat(), "do": krai.isoformat(), "zapisi": len(s),
                              "sredna": _sredno(z["ocenka"] for z in s)})
    ch["sedmici_s_publikacii"] = sum(1 for s in ch["sedmici"] if s["zapisi"])

    # похватите: в колко записа се среща всеки, с примери (най-новите първи)
    po_ime = {}
    for z in reversed(v):
        vidyani = set()
        for p in z["pohvati"]:
            e = po_ime.setdefault(p["ime"], {"ime": p["ime"], "zapisi": 0, "primeri": []})
            if p["ime"] not in vidyani:
                vidyani.add(p["ime"])
                e["zapisi"] += 1
            e["primeri"].append({"otkas": p.get("otkas") or "", "zaglavie": z["zaglavie"], "url": z["url"],
                                 "den": z["den"].isoformat()})
    ch["pohvati"] = sorted(po_ime.values(), key=lambda e: (-e["zapisi"], e["ime"]))
    return ch


def _usloviya(s, ch):
    """→ списък с неизпълнените условия на степен s (празен = изпълнява ги)."""
    ne = []
    if "min_imenuvani" in s and ch["dyal_imenuvani"] < s["min_imenuvani"]:
        ne.append("записи с именувани източници %s (нужни поне %s)" % (procent(ch["dyal_imenuvani"]),
                                                                        procent(s["min_imenuvani"])))
    if "maks_pohvati" in s and ch["dyal_pohvati"] >= s["maks_pohvati"]:
        ne.append("записи с манипулативни похвати %s (нужни под %s)" % (procent(ch["dyal_pohvati"]),
                                                                         procent(s["maks_pohvati"])))
    if "min_istoriya_dni" in s and ch["istoriya_dni"] < s["min_istoriya_dni"]:
        ne.append("история %d дни (нужни поне %d)" % (ch["istoriya_dni"], s["min_istoriya_dni"]))
    if "min_sedmici_s_publikacii" in s and ch["sedmici_s_publikacii"] < s["min_sedmici_s_publikacii"]:
        ne.append("седмици с публикации %d от %d (нужни поне %d)" % (ch["sedmici_s_publikacii"], len(ch["sedmici"]),
                                                                       s["min_sedmici_s_publikacii"]))
    return ne


def _bez(cfg, prichini):
    b = cfg["bez_stepen"]
    return {"kod": b["kod"], "cvyat": b["cvyat"], "cvyat_ime": b["cvyat_ime"], "prichini": prichini}


def stepen(ch, cfg):
    """→ {"kod", "cvyat", "cvyat_ime", "prichini": [...]} — машинната степен (никога „Спряна“)."""
    b = cfg["bez_stepen"]
    malko = []
    if ch["zapisi"] < b["min_zapisi"]:
        malko.append("оценени записи %d (нужни поне %d)" % (ch["zapisi"], b["min_zapisi"]))
    if ch["istoriya_dni"] < b["min_istoriya_dni"]:
        malko.append("история %d дни (нужни поне %d)" % (ch["istoriya_dni"], b["min_istoriya_dni"]))
    if malko:
        return _bez(cfg, ["недостатъчно данни: " + "; ".join(malko)])
    prichini = []
    for s in cfg["stepeni"]:
        if ch["sredna"] < s["ot"]:
            continue
        ne = _usloviya(s, ch)
        if not ne:
            return {"kod": s["kod"], "cvyat": s["cvyat"], "cvyat_ime": s["cvyat_ime"], "prichini": prichini}
        prichini.append("не е %s: %s" % (s["kod"], "; ".join(ne)))
    naydolu = cfg["stepeni"][-1]["ot"]
    return _bez(cfg, prichini + ["средна оценка %s — под %s" % (chislo(ch["sredna"]), chislo(naydolu))])


def s_rachno(mashinna, kanal, cfg):
    """Ако в регистъра има ръчно „spryana“, тя замества машинната степен (която остава за сведение)."""
    sp = (kanal or {}).get("spryana")
    if not sp:
        return mashinna
    s = cfg["spryana"]
    return {"kod": s["kod"], "cvyat": s["cvyat"], "cvyat_ime": s["cvyat_ime"],
            "prichini": ["ръчно решение (%s, %s): %s" % (sp["rolya"], sp["data"], sp["osnovanie"])],
            "rachno": True, "mashinna": mashinna}


def rang(kod, cfg):
    """По-голямо = по-добро. „Без степен“ е под всички степени."""
    kodove = [s["kod"] for s in cfg["stepeni"]]
    return len(kodove) - kodove.index(kod) if kod in kodove else 0
