"""Седемте правила на канона. Всяко връща Rezultat: ок / нарушение / не се прилага, с бележки.

Бележките са два вида: „поправимо“ (Учител го оправя при prebrandirai) и „за ръчно“ (само го казва).
Изтичането, тъмната тема и чистият български са само проверка — никога не се поправят.
"""
import ipaddress
import re
from collections import Counter

from . import analiz
from .dom import tekst

OK, NARUSHENIE, NE_SE_PRILAGA = "ок", "нарушение", "не се прилага"
PRAVILA = ("лого", "шрифтове", "изгледи", "тъмна тема", "изтичане", "чист български", "цялост")
IPV4 = re.compile(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(?![\d.]*\d)")
LATINICA = re.compile(r"[A-Za-z][A-Za-z0-9'’_.+/-]*")


class Rezultat:
    def __init__(self, pravilo):
        self.pravilo = pravilo
        self.status = OK
        self.popravimo = []   # какво ще оправи prebrandirai
        self.za_rachno = []   # какво иска човек

    def narushenie(self, belezhka, popravimo=False):
        self.status = NARUSHENIE
        (self.popravimo if popravimo else self.za_rachno).append(belezhka)

    def belezhki(self):
        return self.popravimo + self.za_rachno

    def kato_dict(self):
        return {"pravilo": self.pravilo, "status": self.status, "popravimo": self.popravimo,
                "za_rachno": self.za_rachno}


def maska(s):
    """Отчетът сам не бива да изтича — показва се само началото."""
    s = s.strip()
    return s if len(s) <= 4 else s[:4] + "…"


# ── 1. лого ─────────────────────────────────────────────────────────────────────

def logo(doc, k, rel):
    r = Rezultat("лого")
    plan = analiz.plan_logo(doc, k, rel)
    t = k["logo"]["tekst"]
    if plan[0] == "ръчно":
        r.narushenie(plan[1])
    elif plan[0] == "добави":
        r.narushenie("няма лого — ще се сложи „%s · %s“ (от logo.ime_po_papka)" % (t, plan[2]), popravimo=True)
    elif plan[0] == "смени":
        r.narushenie("старо лого — ще стане „%s · %s“ (%s)" % (t, analiz.ime_za_pokaz(plan), plan[3]), popravimo=True)
    return r


# ── 2. шрифтове ─────────────────────────────────────────────────────────────────

def shriftove(doc, k):
    r = Rezultat("шрифтове")
    sh = k["shriftove"]
    a = analiz.shriftove(doc, k)
    vrazki, importi = a["vrazki"], a["importi"]
    if not vrazki and not importi:
        r.narushenie("няма връзка към Google Fonts — ще се добави каноничната", popravimo=True)
    else:
        if vrazki and vrazki[0].attrs.get("href") != sh["google_fonts"]:
            r.narushenie("връзката към Google Fonts не е каноничната — ще се подмени", popravimo=True)
        if len(vrazki) + len(importi) > 1:
            r.narushenie("%d връзки към Google Fonts — остава една" % (len(vrazki) + len(importi)), popravimo=True)
        if importi and not vrazki:
            r.narushenie("шрифтовете идват с @import — адресът ще се подмени", popravimo=True)
    if a["za_smyana"]:
        r.narushenie("%s → %s" % (", ".join(a["za_smyana"]), sh["tekst"]), popravimo=True)
    if a["nepoznati"]:
        r.narushenie("непознати шрифтове (не се пипат): %s" % ", ".join(a["nepoznati"]))
    return r


# ── 3. двата изгледа ────────────────────────────────────────────────────────────

def izgledi(doc, k):
    r = Rezultat("изгледи")
    iz = k["izgledi"]
    if not all(re.search(s, doc.html) for s in iz["prevkluchvatel_ezik"]):
        r.narushenie("няма превключвател БГ/EN")
    kirilica = re.compile(iz["kirilica"])
    for e in doc.vsichki():
        if iz["agent_klas"] not in e.klasove():
            continue
        if any(iz["bg_klas"] in d.klasove() or iz["en_klas"] in d.klasove() for d in e.obhod()):
            r.narushenie("изгледът за агента има двуезични части — трябва да е само на английски")
        t = " ".join(tekst(e, propusni=lambda d: d.tag in ("script", "style")))
        m = kirilica.search(t)
        if m:
            otkas = " ".join(t[max(0, m.start() - 10):m.start() + 20].split())
            r.narushenie("изгледът за агента не е само на английски: „%s“" % otkas)
    et = analiz.etiketi(doc, k, analiz.nameri_logo(doc, k))
    if et:
        broi = Counter(t for _e, t, _bg in et)
        r.narushenie("етикети в българския изглед: %s → %s" % (
            ", ".join("%s×%d" % (t, n) for t, n in sorted(broi.items())),
            ", ".join(iz["etiketi"][t] for t in sorted(broi))), popravimo=True)
    return r


# ── 4. тъмна тема ───────────────────────────────────────────────────────────────

def tamna_tema(doc, k):
    r = Rezultat("тъмна тема")
    tt = k["tamna_tema"]
    for s in tt.get("tryabva", []):
        if not re.search(s, doc.html, re.I):
            r.narushenie("не е намерено: %s" % s)
    malki = doc.html.lower()
    for c in tt.get("zabraneni", []):
        if c.lower() in malki:
            r.narushenie("забранен цвят %s" % c)
    return r


# ── 5. изтичане ─────────────────────────────────────────────────────────────────

def _red(html, i):
    return html.count("\n", 0, i) + 1


def iztichane(doc, k):
    r = Rezultat("изтичане")
    iz = k["iztichane"]
    html = doc.html
    mrezhi = [ipaddress.ip_network(m) for m in iz.get("mrezhi", [])]
    pozvoleni = [p.lower() for p in iz.get("pozvoleni", [])]
    nameri = []
    for m in IPV4.finditer(html):
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if any(ip in n for n in mrezhi):
            nameri.append((m.start(), "IP", m.group(1)))
    for vid, s in iz.get("shabloni", {}).items():
        for m in re.finditer(s, html):
            t = m.group(0)
            if any(t.lower().endswith(p) for p in pozvoleni):
                continue
            nameri.append((m.start(), vid, t))
    for d in iz.get("zabraneni_dumi", []):
        for m in re.finditer(r"(?<!\w)%s(?!\w)" % re.escape(d), html, re.I):
            nameri.append((m.start(), "забранена дума", m.group(0)))
    for i, vid, t in sorted(nameri):
        r.narushenie("ред %d: %s „%s“" % (_red(html, i), vid, maska(t)))
    return r


# ── 6. чист български ───────────────────────────────────────────────────────────

def chist_balgarski(doc, k):
    r = Rezultat("чист български")
    cb, iz = k["chist_balgarski"], k["izgledi"]
    kirilica = re.compile(iz["kirilica"])
    propusni_tagove = set(cb.get("propusni_tagove", []))
    propusni_klasove = set(cb.get("propusni_klasove", []))
    logo_el = analiz.nameri_logo(doc, k)

    def propusni(e):
        kl = e.klasove()
        return (e.tag in propusni_tagove or kl & propusni_klasove or iz["en_klas"] in kl or iz["agent_klas"] in kl
                or e is logo_el)

    t = " ".join(tekst(doc.koren, propusni=propusni))
    if not kirilica.search(t):
        r.status = NE_SE_PRILAGA
        return r
    # етикетите HUMAN/AGENT са в правило 3 (и се поправят) — тук не се броят втори път
    izkl = {w.lower() for w in cb.get("izklyucheniya", []) + list(iz["etiketi"])}
    broi = Counter()
    for m in LATINICA.finditer(t):
        w = m.group(0).rstrip(".'’-/")
        if len(w) < 2 or any(ch.isdigit() or ch in "._/+" for ch in w) or w.lower() in izkl:
            continue
        if w.isupper() and len(w) <= cb.get("akronim_max", 4):
            continue
        broi[w] += 1
    if broi:
        do = cb.get("pokazhi_do", 12)
        dumi = ", ".join("%s×%d" % (w, n) if n > 1 else w for w, n in broi.most_common(do))
        oshte = len(broi) - do
        r.narushenie("английски думи в БГ изгледа: %s%s" % (dumi, " (+%d)" % oshte if oshte > 0 else ""))
    return r


# ── 7. цялост (само при поправка) ───────────────────────────────────────────────

def celost_ne_se_prilaga():
    r = Rezultat("цялост")
    r.status = NE_SE_PRILAGA
    return r


def vsichki(doc, k, rel):
    return [logo(doc, k, rel), shriftove(doc, k), izgledi(doc, k), tamna_tema(doc, k), iztichane(doc, k),
            chist_balgarski(doc, k)]

