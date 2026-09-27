"""Поправката: само логото, шрифтовете и етикетите. Работи с точни парчета от суровия текст —
всичко извън тях остава байт за байт същото. Съдържанието на уроците не се пипа.

popravi(...) → Popravka: novo (новият текст или None), blokirano (защо файлът не се пише), stapki (какво е сменено).
"""
import html as html_mod
import re

from . import analiz, celost
from .dom import razbor


class Popravka:
    def __init__(self):
        self.novo = None
        self.blokirano = []   # [(правило, защо)] — файлът не се пише
        self.stapki = []


def _poziciya_head(doc):
    head = doc.parvi("head")
    if head is None or head.zatv is None or head.implicitno:
        return None
    return head.zatv


def _logo(doc, k, rel, znak, redakcii, p):
    lg = k["logo"]
    plan = analiz.plan_logo(doc, k, rel)
    if plan[0] == "канон":
        return False
    if plan[0] == "ръчно":
        p.blokirano.append(("лого", plan[1]))
        return False
    esc = html_mod.escape
    ime = plan[2]
    vatre = lg["vatreshnost"].format(znak=znak, tekst=esc(lg["tekst"]), kurs=esc(ime))
    if plan[0] == "добави":
        lenta = plan[1]
        redakcii.append((lenta.otv_kraj, lenta.otv_kraj, lg["nov_blok"].format(vatreshnost=vatre)))
        p.stapki.append("лого: добавено „%s · %s“" % (lg["tekst"], ime))
    else:
        el = plan[1]
        redakcii.append((el.otv_kraj, el.zatv, vatre))
        p.stapki.append("лого: „%s · %s“" % (lg["tekst"], ime))
    return True


def _smeni_familii(stoynost, sh):
    novo = stoynost
    for z in sh["zameni"]:
        novo = re.sub(r"(?i)(?<![\w-])%s(?![\w-])" % re.escape(z), sh["tekst"], novo)
    if novo == stoynost:
        return novo
    # font-family: 'Sora', 'Inter' → 'Sora', 'Sora' → остава първото
    chasti, videni, izhod = novo.split(","), set(), []
    for ch in chasti:
        kl = ch.strip().strip("'\"").strip().lower()
        if kl and kl in videni:
            continue
        videni.add(kl)
        izhod.append(ch)
    return ",".join(izhod)


def _nov_red(html):
    """Вмъкнатите редове следват файла: \r\n, ако той е с \r\n."""
    return "\r\n" if "\r\n" in html else "\n"


def _shriftove(doc, k, redakcii, p, head_poz):
    sh = k["shriftove"]
    a = analiz.shriftove(doc, k)
    vrazki, importi = a["vrazki"], a["importi"]
    if vrazki:
        parva = vrazki[0]
        if parva.attrs.get("href") != sh["google_fonts"]:
            suro = doc.html[parva.start:parva.otv_kraj]
            m = analiz.HREF_ATR.search(suro)
            if not m:
                p.blokirano.append(("шрифтове", "не мога да намеря href на връзката"))
                return
            redakcii.append((parva.start + m.start(2), parva.start + m.end(2), sh["google_fonts"]))
            p.stapki.append("шрифтове: връзката към Google Fonts е подменена")
        for e in vrazki[1:]:
            redakcii.append((e.start, e.kraj, ""))
            p.stapki.append("шрифтове: втората връзка към Google Fonts е махната")
        for a_, b_, _url in importi:
            redakcii.append((a_, b_, ""))
            p.stapki.append("шрифтове: @import на Google Fonts е махнат")
    elif importi:
        a_, b_, url = importi[0]
        if url != sh["google_fonts"]:
            suro = doc.html[a_:b_]
            i = suro.index(url)
            redakcii.append((a_ + i, a_ + i + len(url), sh["google_fonts"]))
            p.stapki.append("шрифтове: адресът в @import е подменен")
        for a_, b_, _url in importi[1:]:
            redakcii.append((a_, b_, ""))
    else:
        if head_poz is None:
            p.blokirano.append(("шрифтове", "няма </head>, където да се сложи връзката"))
            return
        redakcii.append((head_poz, head_poz, '<link href="%s" rel="stylesheet">%s' % (sh["google_fonts"],
                                                                                   _nov_red(doc.html))))
        p.stapki.append("шрифтове: добавена връзка към Google Fonts")
    smeneni = 0
    for a_, b_, _svoystvo, stoynost in a["deklaracii"]:
        novo = _smeni_familii(stoynost, sh)
        if novo != stoynost:
            redakcii.append((a_, b_, novo))
            smeneni += 1
    if smeneni:
        p.stapki.append("шрифтове: %s → %s (%d места)" % (", ".join(a["za_smyana"]), sh["tekst"], smeneni))


def _etiketi(doc, k, redakcii, p):
    iz = k["izgledi"]
    logo = analiz.nameri_logo(doc, k)
    broi = 0
    for e, t, v_bg in analiz.etiketi(doc, k, logo):
        suro = doc.html[e.otv_kraj:e.zatv]
        i = e.otv_kraj + suro.index(t)
        bg = iz["etiketi"][t]
        novo = bg if v_bg else iz["etiket_shablon"].format(bg=bg, en=t)
        redakcii.append((i, i + len(t), novo))
        broi += 1
    if broi:
        p.stapki.append("етикети: %d × HUMAN/AGENT → Човек/Агент в българския изглед" % broi)


def prilozhi(html, redakcii):
    """Прилага [(начало, край, нов текст)]. Парче изцяло в друго отпада (логото покрива всичко в себе си).
    Вмъкванията на едно и също място остават в реда, в който са дадени."""
    podredeni = sorted(enumerate(redakcii), key=lambda x: (x[1][0], x[1][0] != x[1][1], -(x[1][1] - x[1][0]), x[0]))
    izbrani = []
    for _i, (a, b, t) in podredeni:
        if izbrani and a < izbrani[-1][1]:
            if b <= izbrani[-1][1]:
                continue
            raise ValueError("застъпващи се поправки при %d–%d" % (a, b))
        izbrani.append((a, b, t))
    chasti, posledno = [], 0
    for a, b, t in izbrani:
        chasti.append(html[posledno:a])
        chasti.append(t)
        posledno = b
    chasti.append(html[posledno:])
    return "".join(chasti)


def popravi(html, k, rel, znak):
    p = Popravka()
    doc = razbor(html)
    redakcii = []
    head_poz = _poziciya_head(doc)
    if _logo(doc, k, rel, znak, redakcii, p):
        if 'data-uchitel="logo"' not in html:
            if head_poz is None:
                p.blokirano.append(("лого", "няма </head>, където да се сложи стилът на логото"))
            else:
                redakcii.append((head_poz, head_poz, '<style data-uchitel="logo">%s</style>%s' % (
                    k["logo"]["css"], _nov_red(html))))
    _shriftove(doc, k, redakcii, p, head_poz)
    _etiketi(doc, k, redakcii, p)
    if p.blokirano:
        return p
    if not redakcii:
        p.novo = html
        return p
    try:
        novo = prilozhi(html, redakcii)
    except ValueError as e:
        p.blokirano.append(("цялост", str(e)))
        return p
    razliki = celost.sravni(html, novo, k)
    if razliki:
        p.blokirano.append(("цялост", "; ".join(razliki)))
        return p
    p.novo = novo
    return p
