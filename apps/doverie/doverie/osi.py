"""Седемте оси: имена, евристики (режим без модел), претеглена сума и оценка по думи.

Теглата и праговете идват от конфигурацията. Всяка евристика връща (оценка 0–10, едно изречение защо).
"""
import hashlib
import json
import os
import re
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlparse

from .config import OSI_KLUCHOVE
from .tekst import dumi, izrecheniya, normalizirai

IMENA = {
    "reputaciya": "Репутация на източника",
    "proverimost": "Проверимост на фактите",
    "prozrachnost": "Прозрачност на източниците",
    "originalnost": "Оригиналност",
    "obshtestven_interes": "Обществен интерес",
    "manipulaciya": "Свобода от манипулация",
    "palnota": "Контекстна пълнота",
}
# осите, за които моделът има собствен промпт; останалите са от регистър, шингли и похвати
S_MODEL = ("proverimost", "prozrachnost", "obshtestven_interes", "palnota")

_F = re.IGNORECASE | re.UNICODE


def okragli(x):
    return float(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def ogranichi(x):
    return max(0.0, min(10.0, float(x)))


# ─────────── 1. Репутация — на източника (медия, сайт), никога на автора ───────────

def domain(iztochnik):
    if not iztochnik:
        return None
    s = iztochnik.strip().lower()
    host = urlparse(s if "//" in s else "//" + s).hostname or s
    return host[4:] if host.startswith("www.") else host


def reputaciya(iztochnik, cfg):
    d = domain(iztochnik)
    for z in cfg.get("registar_iztochnici") or []:
        if d and (d == z.get("domain") or d.endswith("." + z.get("domain", "-"))):
            return ogranichi(z["rep_score"]), "Източникът „%s“ е в регистъра." % z.get("ime", d)
    nep = cfg.get("rep_neizvesten", 5.0)
    if not d:
        return nep, "Източникът не е посочен — неутрална оценка."
    return nep, "Източникът не е в регистъра — неутрална оценка."


# ─────────── 2. Проверимост ───────────

TVARDENIE = re.compile(r"\d|\b(заяви|съобщи|обяви|твърд\w+|каза|реши|ще\s+бъде|увелич\w+|намал\w+)\b", _F)
# думите за документ/данни не зависят от главна буква; името след „според“/„каза“ — трябва да е с главна
_DANNI = r"(?i:по\s+данни\s+на)\s+(?!(?i:източници|експерти|специалисти)\b)\w+"
_IME = r"(?i:според)\s+[А-ЯA-Z]|(?i:заяви|каза|съобщи|обяви|посочи|уточни)\w*\s+[А-ЯA-Z]\w+"
IZTOCHNIK = re.compile(r"https?://|www\.|" + _DANNI + "|" + _IME +
                       r"|(?i:\bсъгласно\b|\bдоклад\w*|\bрешение\s+№|\bзакон\w*|\bпостановлени\w+"
                       r"|\bстатистик\w+|\bдокумент\w*)", re.UNICODE)


def proverimost(tekst):
    tv = [s for s in izrecheniya(tekst) if TVARDENIE.search(s)]
    if not tv:
        return 5.0, "Няма ясни фактически твърдения за проверка."
    s_izt = sum(1 for s in tv if IZTOCHNIK.search(s))
    oc = 10.0 * s_izt / len(tv)
    if s_izt == 0:
        return oc, "Липсва посочен източник за нито едно от %d твърдения." % len(tv)
    return oc, "%d от %d твърдения имат посочен източник или документ." % (s_izt, len(tv))


# ─────────── 3. Прозрачност ───────────

IMENUVAN = re.compile(_DANNI + "|" + _IME + r"|https?://|(?i:\bрешение\s+№)"
                      r"|[А-ЯA-Z]\w+\s+[А-ЯA-Z]\w+\s*,\s*(?i:директор|кмет|министър|председател|говорител)", re.UNICODE)
ANONIMEN = re.compile(r"\b(източници|специалисти|експерти|учени)(те)?\s+(твърдят|смятат|казват|съобщават)"
                      r"|\bпожела\w*\s+анонимност|\bненазован\w*|\bанонимн\w*|\bспоред\s+(изследванията|експерти|специалисти)\b"
                      r"|\bзапознат\w*\s+с\s+(темата|случая)", _F)


def prozrachnost(tekst):
    t = normalizirai(tekst)
    im = len(IMENUVAN.findall(t))
    an = len(ANONIMEN.findall(t))
    if im + an == 0:
        return 3.0, "Не са посочени източници — нито именувани, нито анонимни."
    oc = 10.0 * im / (im + an)
    return oc, "Именувани източници: %d, анонимни: %d." % (im, an)


# ─────────── 4. Оригиналност — шингли и Jaccard ───────────

def shingli(tekst, n=5):
    d = dumi(tekst)
    if len(d) < n:
        return {" ".join(d)} if d else set()
    return {hashlib.sha1(" ".join(d[i:i + n]).encode()).hexdigest()[:16] for i in range(len(d) - n + 1)}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def pamet_chetene(path):
    if not path or not os.path.exists(path):
        return []
    zap = []
    with open(path, encoding="utf-8") as f:
        for red in f:
            red = red.strip()
            if red:
                zap.append(set(json.loads(red)["sh"]))
    return zap


def pamet_zapis(path, sh):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"sh": sorted(sh)}) + "\n")


def originalnost(tekst, cfg, vidyani=None):
    """vidyani — списък от множества шингли; ако е None, се чете от cfg['pamet']."""
    oc_cfg = cfg["originalnost"]
    sh = shingli(tekst, oc_cfg.get("shingal", 5))
    if vidyani is None:
        vidyani = pamet_chetene(cfg.get("pamet"))
    if not vidyani:
        return 10.0, "Няма вече видени текстове за сравнение.", sh
    s = max(jaccard(sh, v) for v in vidyani)
    if s >= oc_cfg.get("prag", 0.92):
        return 1.0, "Почти същият текст вече е виждан (сходство %.2f)." % s, sh
    return ogranichi(10.0 * (1.0 - s)), "Най-голямо сходство с видян текст: %.2f." % s, sh


# ─────────── 5. Обществен интерес ───────────

INTERES = re.compile(r"\b(граждан\w*|жител\w*|хора(та)?|бюджет\w*|лев\w*|евро|данъ\w+|такс\w+|прав\w+|закон\w*"
                     r"|болниц\w*|училищ\w*|транспорт\w*|пенси\w+|заплат\w+|услуг\w+|общин\w+|здрав\w+"
                     r"|вод\w+|ток\w*|цен\w+|обществен\w*|пациент\w*|ученици\w*)\b", _F)
REKLAMA = re.compile(r"\b(купете|отстъпк\w+|промоци\w+|спонсориран\w*|реклам\w+|партньорски\s+материал"
                     r"|поръчайте|само\s+днес|безплатна\s+доставка|оферт\w+)\b", _F)


def obshtestven_interes(tekst):
    t = normalizirai(tekst)
    i = len({m.group(0).lower() for m in INTERES.finditer(t)})
    r = len({m.group(0).lower() for m in REKLAMA.finditer(t)})
    oc = ogranichi(4.0 + 1.0 * i - 2.5 * r)
    if r:
        return oc, "Текстът има белези на реклама или PR (%d)." % r
    if i:
        return oc, "Засяга хора, пари, права или услуги (%d различни белега)." % i
    return oc, "Не личи да засяга хора, пари, права или услуги."


# ─────────── 6. Свобода от манипулация ───────────

def manipulaciya(pohvati):
    suma = sum(p["nakazanie"] for p in pohvati)
    oc = ogranichi(10.0 - suma)
    if not pohvati:
        return oc, "Не са открити манипулативни похвати."
    return oc, "Открити похвати: %d (наказание −%.1f)." % (len(pohvati), suma)


# ─────────── 7. Контекстна пълнота — кой, какво, кога, къде, защо ───────────

KOGA = re.compile(r"\b(\d{1,2}\s+(януари|февруари|март|април|май|юни|юли|август|септември|октомври|ноември|декември)"
                  r"|(19|20)\d{2}|вчера|днес|утре|понеделник|вторник|сряда|четвъртък|петък|събота|неделя"
                  r"|миналата\s+седмица|тази\s+седмица|\d{1,2}[.:]\d{2}\s*ч)", _F)
KADE = re.compile(r"\b(във?\s+[А-Я][а-я]+|град\w*|село\w*|област\w*|улица|ул\.|квартал\w*|район\w*|общин\w+)", re.UNICODE)
ZASHTO = re.compile(r"\b(защото|поради|тъй като|причина\w*|заради|с цел|вследствие|понеже)\b", _F)
KOY = re.compile(r"(?<=[\w,;:–-] )[А-Я][а-я]+(?:\s+[А-Я][а-я]+)?", re.UNICODE)


def palnota(tekst):
    t = normalizirai(tekst)
    ima = {
        "кой": bool(KOY.search(t)),
        "какво": len(dumi(t)) >= 25,
        "кога": bool(KOGA.search(t)),
        "къде": bool(KADE.search(t)),
        "защо": bool(ZASHTO.search(t)),
    }
    lipsva = [k for k, v in ima.items() if not v]
    oc = 2.0 * sum(ima.values())
    if not lipsva:
        return oc, "Има кой, какво, кога, къде и защо."
    return oc, "Липсва: %s." % ", ".join(lipsva)


EVRISTIKI = {
    "proverimost": proverimost,
    "prozrachnost": prozrachnost,
    "obshtestven_interes": obshtestven_interes,
    "palnota": palnota,
}


# ─────────── сума и оценка по думи ───────────

def krayna(osi, cfg):
    """Претеглена сума в точна десетична аритметика — иначе 8.45 може да стане 8.4 на границата."""
    t = cfg["tegla"]
    suma = sum(Decimal(str(t[o["kluch"]])) * Decimal(str(o["ocenka"])) for o in osi)
    return float(suma.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def po_dumi(oc, cfg):
    for prag, dumi_ in cfg["po_dumi"]:
        if oc >= prag:
            return dumi_
    return cfg["po_dumi"][-1][1]


def os_zapis(kluch, oc, zashto, cfg, izvor):
    return {"kluch": kluch, "ime": IMENA[kluch], "teglo": cfg["tegla"][kluch],
            "ocenka": okragli(ogranichi(oc)), "zashto": zashto, "izvor": izvor}


assert set(IMENA) == set(OSI_KLUCHOVE)
