"""Малка значка SVG: степен + дата на изчисляване. По подразбиране без име на организация вътре —
подпис се добавя само изрично (`--podpis`). Вътрешната значка носи „вътрешно · непубликувано“."""
from xml.sax.saxutils import escape

from .otchet import VATRESHNO
from .tekstove import den


def _tamen(hex_cvyat):
    """Тъмен ли е фонът — за бял или черен текст отгоре."""
    h = hex_cvyat.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b < 150


def svg(stepen, izchisleno, vatreshno=False, podpis=None):
    shir, vis, lyavo = 216, 44, 140
    dolu = [t for t in (podpis, VATRESHNO if vatreshno else None) if t]
    vis_obsho = vis + 16 * len(dolu)
    tekst_cv = "#fff" if _tamen(stepen["cvyat"]) else "#111"
    duma = stepen["kod"].split()
    zaglavie = "Качество на канала: %s · изчислено %s%s" % (stepen["kod"], den(izchisleno),
                                                            (" · " + VATRESHNO) if vatreshno else "")
    chasti = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" '
        'aria-label="%s">' % (shir, vis_obsho, shir, vis_obsho, escape(zaglavie, {'"': "&quot;"})),
        "<title>%s</title>" % escape(zaglavie),
        '<rect width="%d" height="%d" rx="4" fill="#444"/>' % (shir, vis_obsho),
        '<rect x="%d" width="%d" height="%d" rx="4" fill="%s"/>' % (lyavo, shir - lyavo, vis, stepen["cvyat"]),
        '<rect x="%d" width="8" height="%d" fill="%s"/>' % (lyavo, vis, stepen["cvyat"]),
        '<g font-family="DejaVu Sans,Verdana,sans-serif" fill="#fff">',
        '<text x="10" y="19" font-size="12">Качество на канала</text>',
        '<text x="10" y="35" font-size="11" fill="#ddd">%s</text>' % den(izchisleno),
    ]
    sreda = (lyavo + shir) // 2
    if len(stepen["kod"]) <= 2:  # A+, A, B, C — едро
        chasti.append('<text x="%d" y="30" font-size="22" font-weight="bold" text-anchor="middle" fill="%s">%s</text>'
                      % (sreda, tekst_cv, escape(stepen["kod"])))
    else:  # „Без степен“, „Спряна“ — по една дума на ред
        y0 = 22 - 7 * (len(duma) - 1) + 4
        for i, d in enumerate(duma):
            chasti.append('<text x="%d" y="%d" font-size="12" font-weight="bold" text-anchor="middle" fill="%s">%s</text>'
                          % (sreda, y0 + 14 * i, tekst_cv, escape(d)))
    for i, t in enumerate(dolu):
        chasti.append('<text x="%d" y="%d" font-size="10" text-anchor="middle" fill="#eee">%s</text>' % (
            shir // 2, vis + 12 + 16 * i, escape(t)))
    chasti += ["</g>", "</svg>", ""]
    return "\n".join(chasti)
