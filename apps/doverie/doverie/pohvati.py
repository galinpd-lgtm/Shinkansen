"""Четиринадесетте манипулативни похвата: правила (думи/изрази) и описание за модела.

Всеки открит похват връща: ключ, име, точния откъс от текста и едно изречение обяснение.
Наказанията са част от описанието на похвата (заданието Z7), не тегла на осите.
"""
import re
import statistics

from .tekst import izrechenie_okolo, izrecheniya, normalizirai

# ключ: (име, наказание, как, описание за модела)
POHVATI = {
    "appeal_to_fear": ("Апел към страх", 1.5, "думи+модел",
                       "текстът плаши с опасност, заплаха или крах, без да даде мярка или данни"),
    "false_dichotomy": ("Фалшива дилема", 1.0, "правило",
                        "представя само два изхода, когато има и други"),
    "anonymous_authority": ("Анонимен авторитет", 2.0, "правило",
                            "позовава се на неназовани експерти или изследвания без цитат"),
    "strawman": ("Сламен човек", 1.5, "модел",
                 "преразказва чужда позиция изкривено, за да я обори по-лесно"),
    "cherry_picking": ("Избирателни данни", 1.0, "модел",
                       "подбира само числата, които подкрепят тезата, и мълчи за останалите"),
    "ad_hominem": ("Атака срещу личността", 1.5, "модел",
                   "напада човека вместо довода му"),
    "bandwagon": ("Всички така мислят", 0.8, "правило",
                  "твърди, че нещо е вярно, защото мнозинството го мисли"),
    "slippery_slope": ("Плъзгащ се наклон", 1.0, "модел",
                       "твърди, че малка стъпка неизбежно води до крайно последствие"),
    "appeal_to_tradition": ("Апел към традицията", 0.7, "модел",
                            "нещо е правилно, защото „винаги е било така“"),
    "false_equivalence": ("Фалшива еквивалентност", 1.2, "модел",
                          "поставя знак за равенство между несъизмерими неща"),
    "loaded_language": ("Заредена реторика", 0.8, "модел",
                        "силно емоционални думи вместо описание"),
    "appeal_to_nature": ("Апел към природното", 0.5, "модел",
                         "нещо е добро, защото е „естествено“, или лошо, защото е „изкуствено“"),
    "ai_generated": ("Машинно генериран текст", 2.5, "евристика",
                     "вероятно машинно генериран текст (еднообразни изречения)"),
    "circular_reasoning": ("Кръгово мислене", 1.0, "модел",
                           "заключението е скрито в предпоставката"),
}

SAMO_MODEL = tuple(k for k, v in POHVATI.items() if v[2] == "модел")

_F = re.IGNORECASE | re.UNICODE

STRAH = re.compile(r"\b(заплах\w*|опасн\w*|катастроф\w*|крах\w*|атак\w*)", _F)

DILEMA = [
    re.compile(r"\bили\b[^.!?]{1,80}?,\s*или\b", _F),
    re.compile(r"\bединствено\w*\s+(решение|изход|спасение)", _F),
    re.compile(r"\bняма\s+(друга\s+)?алтернатива", _F),
    re.compile(r"\bняма\s+друг\s+(избор|път|изход)", _F),
]

ANONIMEN = [
    re.compile(r"\b(специалисти|експерти|учени|анализатори)(те)?\s+(твърдят|смятат|казват|предупреждават|са категорични|доказаха)", _F),
    re.compile(r"\bспоред\s+(изследванията|проучванията|експерти(те)?|специалисти(те)?|учени(те)?)\b", _F),
    re.compile(r"\b(изследвания|проучвания)(та)?\s+(показват|доказват|сочат)", _F),
    re.compile(r"\bизточници\s+(твърдят|съобщават|казват)", _F),
]
# в същото изречение има цитат — тогава авторитетът не е анонимен
CITAT = re.compile(r"https?://|www\.|\(\s*\d{4}\s*\)|публикува\w*|списание|доклад\w*\s+на\s+[А-ЯA-Z]"
                   r"|по данни на\s+[А-ЯA-Z]|„[^“]{3,}“", _F)

TALPA = re.compile(r"\b(всички\s+(знаят|смятат|мислят|са съгласни|го казват)|всеки\s+знае"
                   r"|мнозинството\s+(смята|мисли|е съгласно|знае)|никой\s+не\s+се\s+съмнява)", _F)


def nakazanie(kluch):
    return POHVATI[kluch][1]


def zapis(kluch, otkas, obyasnenie, veroyatnost=None):
    ime, nak, _, _ = POHVATI[kluch]
    z = {"kluch": kluch, "ime": ime, "nakazanie": nak, "otkas": otkas, "obyasnenie": obyasnenie}
    if veroyatnost is not None:
        z["veroyatnost"] = veroyatnost
    return z


def _parvo(t, sabl):
    for s in sabl:
        m = s.search(t)
        if m:
            return m
    return None


def strah_kandidat(t):
    """Думите за страх. Връща (брой срещания, първото изречение) — без модел трябват поне 2."""
    t = normalizirai(t)
    sr = list(STRAH.finditer(t))
    if not sr:
        return 0, None
    return len(sr), izrechenie_okolo(t, sr[0].start())


def ai_veroyatnost(t):
    """Проста евристика за еднообразие: сходни дължини на изреченията и повтарящи се начала.

    Под 6 изречения не се оценява (0.0). Не е детектор — само флаг „вероятно“.
    """
    izr = izrecheniya(t)
    if len(izr) < 6:
        return 0.0
    dalj = [len(s.split()) for s in izr]
    sr = statistics.mean(dalj)
    cv = statistics.pstdev(dalj) / sr if sr else 1.0
    ednoobrazie = min(1.0, max(0.0, (0.40 - cv) / 0.30))
    nachala = [s.split()[0].lower() for s in izr if s.split()]
    povtoreni = sum(1 for n in nachala if nachala.count(n) > 1) / len(nachala)
    return round(0.7 * ednoobrazie + 0.3 * povtoreni, 2)


def po_pravila(tekst, s_model=False, ai_flag_ot=0.5):
    """Похватите, които се откриват с думи/изрази. С модел apeal_to_fear само предлага кандидат."""
    t = normalizirai(tekst)
    nam = []

    broy, izr = strah_kandidat(t)
    if broy >= 2 and not s_model:
        nam.append(zapis("appeal_to_fear", izr,
                         "Текстът натрупва думи за опасност и заплаха (%d пъти)." % broy))

    m = _parvo(t, DILEMA)
    if m:
        nam.append(zapis("false_dichotomy", m.group(0),
                         "Представени са само два изхода или един-единствен, без други възможности."))

    for s in ANONIMEN:
        for m in s.finditer(t):
            if not CITAT.search(izrechenie_okolo(t, m.start())):
                nam.append(zapis("anonymous_authority", m.group(0),
                                 "Позоваване на експерти или изследвания, без да е посочено кои."))
                break
        if nam and nam[-1]["kluch"] == "anonymous_authority":
            break

    m = TALPA.search(t)
    if m:
        nam.append(zapis("bandwagon", m.group(0),
                         "Твърдението се опира на това, че „всички“ мислят така, а не на данни."))

    v = ai_veroyatnost(t)
    if v >= ai_flag_ot:
        izr0 = izrecheniya(t)[0]
        nam.append(zapis("ai_generated", izr0,
                         "Вероятно машинно генериран текст: изреченията са необичайно еднообразни.", v))
    return nam
