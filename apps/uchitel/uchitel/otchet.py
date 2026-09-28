"""Отчетите: кратък текст за конзолата, Markdown и CSV — по файлове, по папки, по правила и „за ръчно“."""
import csv
import difflib
import io
import os
from collections import Counter, OrderedDict

from . import obhod, pravila

SIRINA_RED = 200


def _obucheniya(zapisi):
    return [z for _a, z in zapisi if z.status not in (obhod.IZKLYUCHEN, obhod.NE_E_HTML, obhod.VRAZKA)]


def _status(z, pravilo):
    r = z.rezultat(pravilo)
    return r.status if r is not None else "—"


# ── конзола ─────────────────────────────────────────────────────────────────────

def konzola(zapisi, podrobno=True):
    izhod = []
    for z in _obucheniya(zapisi):
        izhod.append("%s  [%s]" % (z.rel, z.status))
        izhod.append("  " + " · ".join("%s: %s" % (p, _status(z, p)) for p in pravila.PRAVILA))
        if podrobno:
            for r in z.rezultati:
                for b in r.popravimo:
                    izhod.append("    ✎ %s — %s" % (r.pravilo, b))
            for pravilo, b, _zap in z.za_rachno():
                izhod.append("    ✋ %s — %s" % (pravilo, b))
            for s in z.stapki:
                izhod.append("    ✓ %s" % s)
    izhod.append("")
    izhod.append(obobshtenie(zapisi))
    return "\n".join(izhod)


def obobshtenie(zapisi):
    broi = Counter(z.status for _a, z in zapisi)
    chasti = ["%s: %d" % (s, n) for s, n in sorted(broi.items())]
    return "Файлове: %d · %s" % (len(zapisi), " · ".join(chasti))


def razlika(zapisi, redove=60):
    """Уеднаквена разлика по файл, с отрязани дълги редове (знакът е data URI)."""
    izhod = []
    for z in _obucheniya(zapisi):
        if z.status != obhod.PROMENEN:
            continue
        d = list(difflib.unified_diff(z.staro.splitlines(), z.novo.splitlines(),
                                      "преди/" + z.rel, "след/" + z.rel, n=0, lineterm=""))
        for red in d[:redove]:
            izhod.append(red if len(red) <= SIRINA_RED else red[:SIRINA_RED] + "…")
        if len(d) > redove:
            izhod.append("… още %d реда" % (len(d) - redove))
    return "\n".join(izhod)


# ── таблици ─────────────────────────────────────────────────────────────────────

def po_papki(zapisi):
    t = OrderedDict()
    for z in sorted(_obucheniya(zapisi), key=lambda z: z.papka):
        red = t.setdefault(z.papka, Counter())
        red["файлове"] += 1
        red[z.status] += 1
        for p in pravila.PRAVILA:
            if _status(z, p) == pravila.NARUSHENIE:
                red[p] += 1
    return t


def po_pravila(zapisi):
    t = OrderedDict((p, Counter()) for p in pravila.PRAVILA)
    for z in _obucheniya(zapisi):
        for p in pravila.PRAVILA:
            t[p][_status(z, p)] += 1
    return t


def za_rachno(zapisi):
    return [(z.rel, p, b, "да" if zap else "не") for z in _obucheniya(zapisi) for p, b, zap in z.za_rachno()]


def _csv(redove, zaglavie):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(zaglavie)
    w.writerows(redove)
    return buf.getvalue()


def csv_failove(zapisi):
    redove = []
    for _a, z in zapisi:
        belezhki = " | ".join("%s: %s" % (r.pravilo, b) for r in z.rezultati for b in r.belezhki())
        redove.append([z.rel, z.papka, z.status] + [_status(z, p) for p in pravila.PRAVILA]
                      + [z.sha_predi or "", z.sha_sled or "", " | ".join(z.stapki), belezhki])
    return _csv(redove, ["файл", "папка", "състояние"] + list(pravila.PRAVILA)
                + ["sha256 преди", "sha256 след", "промени", "бележки"])


def csv_po_papki(zapisi):
    t = po_papki(zapisi)
    koloni = ["файлове", obhod.V_KANON, obhod.POPRAVIMO, obhod.PROMENEN, obhod.BEZ_PROMYANA, obhod.ZA_RACHNO] \
        + list(pravila.PRAVILA)
    return _csv([[p] + [red[k] for k in koloni] for p, red in t.items()], ["папка"] + koloni)


def csv_po_pravila(zapisi):
    t = po_pravila(zapisi)
    koloni = [pravila.OK, pravila.NARUSHENIE, pravila.NE_SE_PRILAGA]
    return _csv([[p] + [red[k] for k in koloni] for p, red in t.items()], ["правило"] + koloni)


def csv_za_rachno(zapisi):
    return _csv(za_rachno(zapisi), ["файл", "правило", "бележка", "записан"])


# ── Markdown ────────────────────────────────────────────────────────────────────

def _md_tablica(zaglavie, redove):
    izhod = ["| " + " | ".join(zaglavie) + " |", "|" + "---|" * len(zaglavie)]
    for r in redove:
        izhod.append("| " + " | ".join(str(x).replace("|", "\\|") for x in r) + " |")
    return "\n".join(izhod)


def markdown(zapisi, zaglavie, vhod, izhod=None, kanon=None):
    obuch = _obucheniya(zapisi)
    md = ["# %s" % zaglavie, "",
          "- Вход: `%s` (само четен)" % vhod]
    if izhod:
        md.append("- Изход: `%s` (нова папка)" % izhod)
    if kanon:
        md.append("- Канон: `%s`" % os.path.basename(kanon))
    md += ["- %s" % obobshtenie(zapisi), "- Обучения (HTML): %d · изключени: %d · други файлове: %d · връзки: %d" % (
        len(obuch), sum(1 for _a, z in zapisi if z.status == obhod.IZKLYUCHEN),
        sum(1 for _a, z in zapisi if z.status == obhod.NE_E_HTML),
        sum(1 for _a, z in zapisi if z.status == obhod.VRAZKA)), ""]

    md += ["## По папки", ""]
    t = po_papki(zapisi)
    koloni = ["файлове", obhod.V_KANON, obhod.POPRAVIMO, obhod.PROMENEN, obhod.ZA_RACHNO]
    md.append(_md_tablica(["папка"] + koloni + ["нарушения по правила"],
                          [[p] + [red[k] for k in koloni]
                           + [", ".join("%s %d" % (pr, red[pr]) for pr in pravila.PRAVILA if red[pr]) or "—"]
                           for p, red in t.items()]))
    md += ["", "## По правила", "", "Състоянието на входа — преди поправката." if izhod else "", ""]
    t = po_pravila(zapisi)
    koloni = [pravila.OK, pravila.NARUSHENIE, pravila.NE_SE_PRILAGA]
    md.append(_md_tablica(["правило"] + koloni, [[p] + [red[k] for k in koloni] for p, red in t.items()]))

    zr = za_rachno(zapisi)
    md += ["", "## За ръчно (%d)" % len(zr), ""]
    if zr:
        md.append(_md_tablica(["файл", "правило", "бележка", "записан"], zr))
    else:
        md.append("Няма.")

    promeneni = [z for z in obuch if z.status == obhod.PROMENEN]
    if izhod is not None:
        md += ["", "## Променени файлове (%d)" % len(promeneni), ""]
        if promeneni:
            md.append(_md_tablica(["файл", "sha256 преди", "sha256 след", "какво"],
                                  [[z.rel, z.sha_predi[:12], z.sha_sled[:12], "; ".join(z.stapki)] for z in promeneni]))
        else:
            md.append("Няма.")
    md.append("")
    return "\n".join(md)


def zapishi(papka, zapisi, zaglavie, vhod, izhod=None, kanon=None):
    os.makedirs(papka, exist_ok=True)
    failove = {
        "otchet.md": markdown(zapisi, zaglavie, vhod, izhod, kanon),
        "failove.csv": csv_failove(zapisi),
        "po_papki.csv": csv_po_papki(zapisi),
        "po_pravila.csv": csv_po_pravila(zapisi),
        "za_rachno.csv": csv_za_rachno(zapisi),
    }
    for ime, sadarzhanie in failove.items():
        # utf-8-sig: Excel разпознава кирилицата в CSV само с BOM
        kod = "utf-8-sig" if ime.endswith(".csv") else "utf-8"
        with open(os.path.join(papka, ime), "w", encoding=kod, newline="") as f:
            f.write(sadarzhanie)
    return sorted(failove)
