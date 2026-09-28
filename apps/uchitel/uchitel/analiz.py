"""Общото между проверката и поправката: къде е лентата, къде е логото, как се казва курсът,
кои шрифтове се ползват и кои етикети HUMAN/AGENT чакат превод.
"""
import html as html_mod
import re
import unicodedata
from urllib.parse import parse_qs, urlsplit

from .dom import tekst, vatre_v

GOOGLE = "fonts.googleapis.com/css"
IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?(['"]?)(https?://fonts\.googleapis\.com/css[^'")\s]*)\1\s*\)?\s*;?""",
                    re.I)
DEKLARACIYA = re.compile(r"(?i)(?<![\w-])(font-family|font)\s*:\s*([^;{}]*)")
FONT_FACE = re.compile(r"(?is)@font-face\s*\{[^}]*\}")
STIL_ATR = re.compile(r"""(?is)(?<![\w-])style\s*=\s*(["'])(.*?)\1""")
HREF_ATR = re.compile(r"""(?is)(?<![\w-])href\s*=\s*(["'])(.*?)\1""")
RAZMER = re.compile(r"(?i)^.*?[\d.]+(?:px|rem|em|%|pt|pc|vw|vh|vmin|vmax|ex|ch|cm|mm|in)"
                    r"(?:\s*/\s*[\d.]+[a-z%]*)?\s+(.+)$")
NEVIDIMI = "‍️︎⃣"


# ── лента и лого ────────────────────────────────────────────────────────────────

def nameri_lenta(doc, k):
    kl = set(k["lenta"].get("klasove", []))
    tagove = set(k["lenta"].get("tagove", []))
    for e in doc.vsichki():
        if e.tag in tagove or (e.klasove() & kl):
            return e
    return None


def _e_logo(e, k):
    return bool(e.klasove() & set(k["logo"]["klasove"]))


def nameri_logo(doc, k):
    """Първият елемент с клас на лого — първо в лентата, иначе преди първото h1. Първият по ред е и най-външният."""
    agent = k["izgledi"]["agent_klas"]
    lenta = nameri_lenta(doc, k)
    if lenta is not None:
        for e in lenta.obhod():
            if e is not lenta and _e_logo(e, k):
                return e
    h1 = doc.parvi("h1")
    granica = h1.start if h1 is not None else len(doc.html)
    for e in doc.vsichki():
        if e.start >= granica:
            break
        if _e_logo(e, k) and not vatre_v(e, lambda x: agent in x.klasove()):
            return e
    return None


def e_kanonichno(logo, k):
    m = k["logo"]["marker_klas"]
    return any(m in e.klasove() for e in logo.obhod())


def _chisti(t, k):
    lg = k["logo"]
    if lg.get("mahni_simvoli", True):
        t = "".join(ch for ch in t if ch not in NEVIDIMI and unicodedata.category(ch) not in ("So", "Sk", "Cs", "Co"))
    for d in lg.get("mahni_dumi", []):
        t = re.sub(r"(?<!\w)%s(?!\w)" % re.escape(d), " ", t, flags=re.I)
    return " ".join(t.split()).strip(" ·|—–-:/•")


def _validno(ime, k):
    lg = k["logo"]
    if not ime:
        return "в логото няма име на курса"
    if len(ime) < lg.get("min_dalzhina", 2):
        return "името „%s“ е твърде кратко" % ime
    if len(ime) > lg.get("max_dalzhina", 48):
        return "името „%s…“ е твърде дълго" % ime[:30]
    if not any(ch.isalpha() for ch in ime):
        return "името „%s“ няма букви" % ime
    if "__" in ime or "{" in ime or "}" in ime:
        return "името „%s“ прилича на незаменен шаблон" % ime
    return None


def ime_po_papka(k, rel):
    """Името от logo.ime_po_papka по най-близката папка нагоре от файла."""
    mapa = k["logo"].get("ime_po_papka") or {}
    chasti = rel.replace("\\", "/").split("/")[:-1]
    for p in reversed(chasti):
        if p in mapa:
            return mapa[p]
    return None


def _ime_ot_tekst(surovo, k):
    for z in k["logo"].get("zapazeni_imena", []):
        if z.lower() in surovo.lower():
            return z
    ime = _chisti(surovo, k)
    return k["logo"].get("imena", {}).get(ime, ime)


def ime_na_kursa(logo, k, rel):
    """(име, откъде, английско име или None) или (None, защо не, None). Съмнително име не се гадае.

    Ако старият блок има отделни bg-only/en-only части, английското име се пази за EN изгледа.
    Ако няма (или там е само „KAGAMI“), българското остава и в двата изгледа."""
    iz = k["izgledi"]
    sluzhebni = ("title", "desc", "style", "script")
    bg = " ".join(" ".join(tekst(logo, propusni=lambda d: d.tag in sluzhebni
                                  or iz["en_klas"] in d.klasove())).split())
    ime = _ime_ot_tekst(bg, k)
    if not ime:
        po_papka = ime_po_papka(k, rel)
        if po_papka:
            return po_papka, "от logo.ime_po_papka", None
    greshka = _validno(ime, k)
    if greshka:
        return None, greshka, None
    en = None
    if any(iz["en_klas"] in d.klasove() for d in logo.obhod()):
        surovo = " ".join(" ".join(tekst(logo, propusni=lambda d: d.tag in sluzhebni
                                         or iz["bg_klas"] in d.klasove())).split())
        en = _ime_ot_tekst(surovo, k) or None
        if en is not None:
            greshka = _validno(en, k)
            if greshka:
                return None, "английското име: %s" % greshka, None
            if en == ime:
                en = None
    return ime, "от логото", en


def ime_za_pokaz(plan):
    """„Лаборатория“ или „Лаборатория / Lab“ — за отчета."""
    en = plan[4] if len(plan) > 4 else None
    return plan[2] + (" / " + en if en else "")


def plan_logo(doc, k, rel):
    """Какво ще стане с логото — едно решение за проверката и за поправката:
    ("канон",) · ("смени", елемент, име, откъде, английско име или None) · ("добави", лента, име) ·
    ("ръчно", защо)."""
    el = nameri_logo(doc, k)
    if el is not None and e_kanonichno(el, k):
        return ("канон",)
    if el is None:
        lenta = nameri_lenta(doc, k)
        ime = ime_po_papka(k, rel)
        if lenta is None:
            return ("ръчно", "няма лого и няма заглавна лента, в която да се сложи")
        if not ime:
            return ("ръчно", "няма лого, а името на курса не е зададено в logo.ime_po_papka")
        return ("добави", lenta, ime)
    if not el.zdrav():
        return ("ръчно", "блокът на логото е счупен (незатворен таг), ред %d" % (doc.html.count("\n", 0, el.start) + 1))
    if any(e.tag == "a" for e in el.obhod() if e is not el):
        return ("ръчно", "в блока на логото има връзка — смяната би я махнала")
    ime, otkade, en = ime_na_kursa(el, k, rel)
    if ime is None:
        return ("ръчно", "името на курса не може да се извади сигурно: %s" % otkade)
    return ("смени", el, ime, otkade, en)


# ── шрифтове ────────────────────────────────────────────────────────────────────

def familii_ot_url(url):
    q = parse_qs(urlsplit(html_mod.unescape(url)).query)
    return [f.split(":")[0].replace("+", " ").strip() for f in q.get("family", [])]


def familii(svoystvo, stoynost):
    v = re.sub(r"(?i)!important", "", stoynost).strip()
    if svoystvo.lower() == "font":
        m = RAZMER.match(v)
        if not m:
            return []
        v = m.group(1)
    r = []
    for ch in v.split(","):
        ch = ch.strip().strip("'\"").strip()
        if ch and not ch.lower().startswith("var("):
            r.append(ch)
    return r


def _deklaracii(css, otmestvane):
    """[(начало, край, свойство, стойност)] в абсолютни места, без тези в @font-face."""
    izklyucheni = [(m.start(), m.end()) for m in FONT_FACE.finditer(css)]
    for m in DEKLARACIYA.finditer(css):
        if any(a <= m.start() < b for a, b in izklyucheni):
            continue
        yield otmestvane + m.start(2), otmestvane + m.end(2), m.group(1), m.group(2)


def css_parcheta(doc):
    """Всички места с CSS: съдържанието на <style> и стойностите на style="…" — [(начало, текст)]."""
    for e in doc.vsichki():
        if e.tag == "style" and e.zatv is not None:
            yield e.otv_kraj, doc.html[e.otv_kraj:e.zatv]
        suro = doc.html[e.start:e.otv_kraj]
        for m in STIL_ATR.finditer(suro):
            yield e.start + m.start(2), m.group(2)


def shriftove(doc, k):
    """Какво има в страницата по шрифтове — за проверката и за поправката."""
    sh = k["shriftove"]
    vrazki = [e for e in doc.vsichki() if e.tag == "link" and GOOGLE in (e.attrs.get("href") or "")]
    importi = []
    for e in doc.vsichki():
        if e.tag == "style" and e.zatv is not None:
            for m in IMPORT.finditer(doc.html[e.otv_kraj:e.zatv]):
                importi.append((e.otv_kraj + m.start(), e.otv_kraj + m.end(), m.group(2)))
    deklaracii = []
    for otm, css in css_parcheta(doc):
        deklaracii.extend(_deklaracii(css, otm))
    zameni = {z.lower() for z in sh["zameni"]}
    pozvoleni = {p.lower() for p in sh["pozvoleni"]}
    za_smyana, nepoznati = set(), set()
    for _a, _b, svoystvo, stoynost in deklaracii:
        for f in familii(svoystvo, stoynost):
            if f.lower() in zameni:
                za_smyana.add(f)
            elif f.lower() not in pozvoleni:
                nepoznati.add(f)
    for e in vrazki:
        for f in familii_ot_url(e.attrs.get("href", "")):
            if f.lower() in zameni:
                za_smyana.add(f)
            elif f.lower() not in pozvoleni:
                nepoznati.add(f)
    return {"vrazki": vrazki, "importi": importi, "deklaracii": deklaracii,
            "za_smyana": sorted(za_smyana), "nepoznati": sorted(nepoznati)}


# ── етикети HUMAN/AGENT ─────────────────────────────────────────────────────────

ZABRANENI_ZA_ETIKET = {"script", "style", "code", "pre", "title", "textarea", "kbd", "samp"}


def etiketi(doc, k, logo=None):
    """Листови елементи с текст точно HUMAN/AGENT в изгледа за човека: [(елемент, етикет, вътре_в_bg)]."""
    iz = k["izgledi"]
    mapa = iz["etiketi"]
    r = []
    for e in doc.vsichki():
        if e.kraj is None or e.elementi() or e.tag in ZABRANENI_ZA_ETIKET:
            continue
        t = doc.html[e.otv_kraj:e.zatv].strip()
        if t not in mapa:
            continue
        if vatre_v(e, lambda x: x.tag in ZABRANENI_ZA_ETIKET or iz["agent_klas"] in x.klasove()
                   or iz["en_klas"] in x.klasove()):
            continue
        if logo is not None and vatre_v(e, lambda x: x is logo):
            continue
        r.append((e, t, vatre_v(e, lambda x: iz["bg_klas"] in x.klasove())))
    return r
