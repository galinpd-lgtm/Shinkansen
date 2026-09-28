"""Картата: JSON файлът след skanirai, и изгледите ѝ за човека (md, html, csv).

Горе е това, по което човекът работи: да/не по клас и по файл, и дали всеки файл е видян. Долу, отделно —
„Не се работи от Сито“: извън обхвата, чист текст и архиви, само с брой и размер по вид.
HTML картата дава за всеки файл връзка към него и откъс от извлечения текст — прегледът е там.
"""
import csv
import html
import io
import json
import os
import urllib.request

from .config import SAMO_UVEDOMYAVAT
from .prisadi import IMENA, chovesko

REDA = ("opakovka", "dokazatelstvo", "zhiv", "tekst", "neyasno", "dublikat") + SAMO_UVEDOMYAVAT


class GreshkaKarta(Exception):
    pass


def zaredi(pat):
    try:
        with open(pat, encoding="utf-8") as f:
            k = json.load(f)
    except (OSError, ValueError) as e:
        raise GreshkaKarta("не мога да прочета картата %s: %s" % (pat, e))
    if not isinstance(k, dict) or "faylove" not in k or "koren" not in k:
        raise GreshkaKarta("%s не е карта на Сито" % pat)
    return k


def zapishi(pat, k):
    d = os.path.dirname(os.path.abspath(pat))
    os.makedirs(d, exist_ok=True)
    with open(pat + ".tmp", "w", encoding="utf-8") as f:
        json.dump(k, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(pat + ".tmp", pat)


def rabotni(k):
    return [z for z in k["faylove"] if z["prisada"] not in SAMO_UVEDOMYAVAT]


def uvedomitelni(k):
    return [z for z in k["faylove"] if z["prisada"] in SAMO_UVEDOMYAVAT]


def _reshenie(z):
    r = z.get("reshenie")
    if not r:
        return "—"
    return ("да" if r["da"] else "не") + " (%s)" % r["rolya"]


def vidyan_tekst(z):
    v = z.get("vidyan")
    if z.get("spryan") and not v:
        return "спрян — чака нов преглед"
    if not v:
        return "—" if z["prisada"] in ("dublikat", "neyasno") else "невидян"
    if v.get("sha256") != z["sha256"]:
        return "невидян (променен след прегледа)"
    return "видян (%s, %s)" % (v["rolya"], v["t"])


def klasove(k, fl=None):
    """Обобщение по клас: брой, размер, очакван MD, колко са решени да/не и колко са видени."""
    po = {}
    for z in (rabotni(k) if fl is None else fl):
        c = po.setdefault(z["klas"], {"klas": z["klas"], "prisada": z["prisada"], "broy": 0, "razmer": 0,
                                      "ochakvan": 0, "neizvesten": 0, "da": 0, "ne": 0, "videni": 0,
                                      "predlozhenie": z["predlozhenie"].split(" · ")[0]})
        c["broy"] += 1
        c["razmer"] += z.get("razmer") or 0
        if z["prisada"] in ("dublikat",) + SAMO_UVEDOMYAVAT:
            pass
        elif z.get("ochakvan_md_bytes") is None:
            c["neizvesten"] += 1
        else:
            c["ochakvan"] += z["ochakvan_md_bytes"]
        r = z.get("reshenie")
        if r:
            c["da" if r["da"] else "ne"] += 1
        if (z.get("vidyan") or {}).get("sha256") == z["sha256"]:
            c["videni"] += 1
    return sorted(po.values(), key=lambda c: (REDA.index(c["prisada"]) if c["prisada"] in REDA else 99, c["klas"]))


def _ochakvan(c):
    if c["prisada"] in ("dublikat",) + SAMO_UVEDOMYAVAT:
        return "—"
    if c["neizvesten"] and not c["ochakvan"]:
        return "неизвестен (%d)" % c["neizvesten"]
    return chovesko(c["ochakvan"]) + (" + %d неизв." % c["neizvesten"] if c["neizvesten"] else "")


def _propusnati(k):
    p = k.get("propusnati", {})
    chasti = ["системни %d" % p.get("sistemni", 0), "връзки %d" % p.get("vrazki", 0)]
    chasti.append("заради дълбочината (над %s папки) %d" % (k.get("maks_dalbochina", "?"), p.get("dalbochina", 0)))
    return "пропуснати: " + ", ".join(chasti)


def _md_kl(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def md(k):
    fl = rabotni(k)
    out = ["# Сито — карта", "",
           "Папка: `%s` · сканирано: %s · файлове: %d · %s" % (k["koren"], k["skanirano"], len(k["faylove"]),
                                                             _propusnati(k)), "",
           "Действие има само за файл с решение „да“ **и** преглед (`vidyah`) със същия SHA-256.", "",
           "## По клас", "",
           "| Клас | Присъда | Брой | Размер | Очакван MD | Предложение | Видени | Да | Не | Решение |",
           "|---|---|---:|---:|---:|---|---:|---:|---:|---|"]
    for c in klasove(k):
        out.append("| `%s` | %s | %d | %s | %s | %s | %d | %d | %d | "
                   "`reshi karta.json --klas %s --da\\|--ne --ot <роля>` |" % (
                       c["klas"], IMENA.get(c["prisada"], c["prisada"]), c["broy"], chovesko(c["razmer"]),
                       _ochakvan(c), c["predlozhenie"], c["videni"], c["da"], c["ne"], c["klas"]))
    out += ["", "## По файл", "",
            "| id | Път | Вид | Размер | Присъда | Защо | Очакван MD | Бележка | Преглед | Решение |",
            "|---|---|---|---:|---|---|---:|---|---|---|"]
    for z in fl:
        prichina = z["prichina"] + (" → `%s`" % z["dublikat_na"] if z.get("dublikat_na") else "")
        belezhka = "; ".join(x for x in (z.get("belezhka"), z.get("proveri"),
                                         (z.get("spryan") or {}).get("prichina")) if x)
        out.append("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            z["id"], _md_kl(z["put"]), z["vid"], chovesko(z.get("razmer")), IMENA.get(z["prisada"], z["prisada"]),
            _md_kl(prichina), chovesko(z.get("ochakvan_md_bytes")), _md_kl(belezhka), vidyan_tekst(z),
            _reshenie(z)))
    out += ["", "## Не се работи от Сито", ""]
    uv = klasove(k, uvedomitelni(k))
    if not uv:
        out.append("Няма.")
    else:
        out += ["| Присъда | Вид | Брой | Размер | Какво да се направи |", "|---|---|---:|---:|---|"]
        for c in uv:
            out.append("| %s | %s | %d | %s | %s |" % (IMENA[c["prisada"]], c["klas"].split(":", 1)[1], c["broy"],
                                                   chovesko(c["razmer"]), c["predlozhenie"]))
        spom = [z for z in uvedomitelni(k) if z.get("belezhka")]
        if spom:
            out += ["", "Бележки (само за сведение, не са присъда):", ""]
            out += ["- %s — %s" % (_md_kl(z["put"]), z["belezhka"]) for z in spom]
    return "\n".join(out) + "\n"


def csv_(k):
    b = io.StringIO()
    w = csv.writer(b)
    w.writerow(["id", "put", "vid", "razmer", "sha256", "prisada", "klas", "prichina", "predlozhenie",
                "ochakvan_md_bytes", "belezhka", "proveri", "dublikat_na", "vidyan", "vidyan_ot", "reshenie",
                "rolya", "md_bytes"])
    for z in k["faylove"]:
        r = z.get("reshenie") or {}
        v = z.get("vidyan") or {}
        w.writerow([z["id"], z["put"], z["vid"], z.get("razmer") or "", z.get("sha256") or "",
                    z["prisada"], z["klas"], z["prichina"], z["predlozhenie"],
                    "" if z.get("ochakvan_md_bytes") is None else z["ochakvan_md_bytes"], z.get("belezhka") or "",
                    z.get("proveri") or "", z.get("dublikat_na") or "",
                    "да" if v.get("sha256") == z["sha256"] else "не", v.get("rolya", ""),
                    ("да" if r.get("da") else "не") if r else "", r.get("rolya", ""),
                    (z.get("preobrazuvan") or {}).get("md_bytes", "")])
    return b.getvalue()


_CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6b66;--line:#e3e0d8;--acc:#8a5a00;--da:#1f7a3a;--ne:#a1261c;
--card:#f2f0ea}
@media (prefers-color-scheme:dark){:root{--bg:#141412;--fg:#ecebe6;--muted:#9a9990;--line:#2d2c28;--acc:#e0b050;
--da:#6fd08c;--ne:#ff8a7a;--card:#1e1d1a}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}
main{max-width:1200px;margin:0 auto}h1{margin:0 0 4px}p.m{color:var(--muted);margin:0 0 24px}
.w{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:8px 0 32px;font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
code{font-size:13px;color:var(--acc)}.da{color:var(--da)}.ne{color:var(--ne)}a{color:var(--acc)}
details{margin-top:4px}summary{cursor:pointer;color:var(--muted)}
pre{white-space:pre-wrap;background:var(--card);padding:8px;border-radius:6px;font-size:13px;max-width:70ch}
"""


def _vrazka(k, z):
    pat = os.path.join(k["koren"], z["put"])
    return "file://" + urllib.request.pathname2url(os.path.abspath(pat))


def html_(k):
    e = html.escape
    r = ["<!doctype html><html lang=\"bg\"><head><meta charset=\"utf-8\">",
         "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Сито — карта</title>",
         "<style>%s</style></head><body><main>" % _CSS,
         "<h1>Сито — карта</h1><p class=\"m\">%s · сканирано %s · %d файла · %s</p>" % (
             e(k["koren"]), e(k["skanirano"]), len(k["faylove"]), e(_propusnati(k))),
         "<p>Действие има само за файл с решение „да“ <b>и</b> преглед: "
         "<code>python -m sito vidyah karta.json &lt;id&gt; … --ot &lt;роля&gt;</code>.</p>",
         "<h2>По клас</h2><div class=\"w\"><table><tr><th>Клас</th><th>Присъда</th><th>Брой</th><th>Размер</th>"
         "<th>Очакван MD</th><th>Предложение</th><th>Видени</th><th>Да</th><th>Не</th></tr>"]
    for c in klasove(k):
        r.append("<tr><td><code>%s</code></td><td>%s</td><td class=n>%d</td><td class=n>%s</td><td class=n>%s</td>"
                 "<td>%s</td><td class=n>%d</td><td class=\"n da\">%d</td><td class=\"n ne\">%d</td></tr>" % (
                     e(c["klas"]), e(IMENA.get(c["prisada"], c["prisada"])), c["broy"], chovesko(c["razmer"]),
                     e(_ochakvan(c)), e(c["predlozhenie"]), c["videni"], c["da"], c["ne"]))
    r.append("</table></div><h2>По файл</h2><div class=\"w\"><table><tr><th>id</th><th>Файл и откъс</th>"
             "<th>Вид</th><th>Размер</th><th>Присъда</th><th>Защо</th><th>Очакван MD</th><th>Преглед</th>"
             "<th>Решение</th></tr>")
    for z in rabotni(k):
        rs = z.get("reshenie")
        klas_r = "" if not rs else (" class=da" if rs["da"] else " class=ne")
        vt = vidyan_tekst(z)
        klas_v = " class=da" if vt.startswith("видян") else (" class=ne" if vt != "—" else "")
        belezhki = [x for x in (z.get("belezhka"), z.get("proveri"), (z.get("spryan") or {}).get("prichina")) if x]
        if z.get("otkas"):
            otkas = "<details><summary>откъс (%d знака)</summary><pre>%s</pre></details>" % (
                len(z["otkas"]), e(z["otkas"]))
        elif z.get("otlozheno"):
            otkas = "<details><summary>няма откъс</summary><pre>текстът идва след %s</pre></details>" % e(
                z["otlozheno"])
        else:
            otkas = ""
        r.append("<tr><td><code>%s</code></td><td><a href=\"%s\">%s</a>%s%s</td><td>%s</td><td class=n>%s</td>"
                 "<td>%s</td><td>%s</td><td class=n>%s</td><td%s>%s</td><td%s>%s</td></tr>" % (
                     e(z["id"]), e(_vrazka(k, z)), e(z["put"]),
                     "".join("<br><small>%s</small>" % e(b) for b in belezhki), otkas,
                     e(z["vid"]), chovesko(z.get("razmer")), e(IMENA.get(z["prisada"], z["prisada"])),
                     e(z["prichina"]), chovesko(z.get("ochakvan_md_bytes")), klas_v, e(vt), klas_r, e(_reshenie(z))))
    r.append("</table></div><h2>Не се работи от Сито</h2>")
    uv = klasove(k, uvedomitelni(k))
    if not uv:
        r.append("<p>Няма.</p>")
    else:
        r.append("<div class=\"w\"><table><tr><th>Присъда</th><th>Вид</th><th>Брой</th><th>Размер</th>"
                 "<th>Какво да се направи</th></tr>")
        for c in uv:
            r.append("<tr><td>%s</td><td>%s</td><td class=n>%d</td><td class=n>%s</td><td>%s</td></tr>" % (
                e(IMENA[c["prisada"]]), e(c["klas"].split(":", 1)[1]), c["broy"], chovesko(c["razmer"]),
                e(c["predlozhenie"])))
        r.append("</table></div>")
        spom = [z for z in uvedomitelni(k) if z.get("belezhka")]
        if spom:
            r.append("<p class=m>Бележки (само за сведение, не са присъда):</p><ul>")
            r += ["<li>%s — %s</li>" % (e(z["put"]), e(z["belezhka"])) for z in spom]
            r.append("</ul>")
    r.append("</main></body></html>\n")
    return "\n".join(r)


