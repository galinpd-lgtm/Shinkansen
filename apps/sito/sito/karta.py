"""Картата: JSON файлът след skanirai, и изгледите ѝ за човека (md, html, csv) — да/не по файл и по клас."""
import csv
import html
import io
import json
import os

from .prisadi import IMENA, chovesko

REDA = ("opakovka", "dokazatelstvo", "zhiv", "tekst", "neyasno", "dublikat", "kontejner")


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


def _reshenie(z):
    r = z.get("reshenie")
    if not r:
        return "—"
    return ("да" if r["da"] else "не") + " (%s)" % r["rolya"]


def klasove(k):
    """Обобщение по клас: брой, размер, очакван MD, колко са решени да/не."""
    po = {}
    for z in k["faylove"]:
        c = po.setdefault(z["klas"], {"klas": z["klas"], "prisada": z["prisada"], "broy": 0, "razmer": 0,
                                      "ochakvan": 0, "neizvesten": 0, "da": 0, "ne": 0,
                                      "predlozhenie": z["predlozhenie"].split(" · ")[0]})
        c["broy"] += 1
        c["razmer"] += z.get("razmer") or 0
        if z["prisada"] in ("dublikat", "kontejner"):
            pass
        elif z.get("ochakvan_md_bytes") is None:
            c["neizvesten"] += 1
        else:
            c["ochakvan"] += z["ochakvan_md_bytes"]
        r = z.get("reshenie")
        if r:
            c["da" if r["da"] else "ne"] += 1
    return sorted(po.values(), key=lambda c: (REDA.index(c["prisada"]) if c["prisada"] in REDA else 99, c["klas"]))


def _ochakvan(c):
    if c["prisada"] in ("dublikat", "kontejner"):
        return "—"
    if c["neizvesten"] and not c["ochakvan"]:
        return "неизвестен (%d)" % c["neizvesten"]
    return chovesko(c["ochakvan"]) + (" + %d неизв." % c["neizvesten"] if c["neizvesten"] else "")


def md(k):
    out = ["# Сито — карта", "",
           "Папка: `%s` · сканирано: %s · файлове: %d" % (k["koren"], k["skanirano"], len(k["faylove"])), "",
           "## По клас", "",
           "| Клас | Присъда | Брой | Размер | Очакван MD | Предложение | Да | Не | Решение |",
           "|---|---|---:|---:|---:|---|---:|---:|---|"]
    for c in klasove(k):
        out.append("| `%s` | %s | %d | %s | %s | %s | %d | %d | "
                   "`reshi karta.json --klas %s --da\\|--ne --ot <роля>` |" % (
            c["klas"], IMENA.get(c["prisada"], c["prisada"]), c["broy"], chovesko(c["razmer"]), _ochakvan(c),
            c["predlozhenie"], c["da"], c["ne"], c["klas"]))
    out += ["", "## По файл", "",
            "| id | Път | Вид | Размер | Присъда | Защо | Очакван MD | Провери | Решение |",
            "|---|---|---|---:|---|---|---:|---|---|"]
    for z in k["faylove"]:
        prichina = z["prichina"] + (" → `%s`" % z["dublikat_na"] if z.get("dublikat_na") else "")
        out.append("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            z["id"], _md_kl(z["put"]), z["vid"] or "?", chovesko(z.get("razmer")),
            IMENA.get(z["prisada"], z["prisada"]), _md_kl(prichina), chovesko(z.get("ochakvan_md_bytes")),
            _md_kl(z.get("proveri") or ""), _reshenie(z)))
    return "\n".join(out) + "\n"


def _md_kl(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def csv_(k):
    b = io.StringIO()
    w = csv.writer(b)
    w.writerow(["id", "put", "vid", "razmer", "sha256", "prisada", "klas", "prichina", "predlozhenie",
                "ochakvan_md_bytes", "proveri", "dublikat_na", "reshenie", "rolya", "md_bytes"])
    for z in k["faylove"]:
        r = z.get("reshenie") or {}
        w.writerow([z["id"], z["put"], z["vid"] or "", z.get("razmer") or "", z.get("sha256") or "",
                    z["prisada"], z["klas"], z["prichina"], z["predlozhenie"],
                    "" if z.get("ochakvan_md_bytes") is None else z["ochakvan_md_bytes"], z.get("proveri") or "",
                    z.get("dublikat_na") or "", ("да" if r.get("da") else "не") if r else "", r.get("rolya", ""),
                    (z.get("preobrazuvan") or {}).get("md_bytes", "")])
    return b.getvalue()


_CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6b66;--line:#e3e0d8;--acc:#8a5a00;--da:#1f7a3a;--ne:#a1261c}
@media (prefers-color-scheme:dark){:root{--bg:#141412;--fg:#ecebe6;--muted:#9a9990;--line:#2d2c28;--acc:#e0b050;
--da:#6fd08c;--ne:#ff8a7a}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}
main{max-width:1200px;margin:0 auto}h1{margin:0 0 4px}p.m{color:var(--muted);margin:0 0 24px}
.w{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:8px 0 32px;font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
code{font-size:13px;color:var(--acc)}.da{color:var(--da)}.ne{color:var(--ne)}
"""


def html_(k):
    e = html.escape
    r = ["<!doctype html><html lang=\"bg\"><head><meta charset=\"utf-8\">",
         "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Сито — карта</title>",
         "<style>%s</style></head><body><main>" % _CSS,
         "<h1>Сито — карта</h1><p class=\"m\">%s · сканирано %s · %d файла</p>" % (
             e(k["koren"]), e(k["skanirano"]), len(k["faylove"])),
         "<h2>По клас</h2><div class=\"w\"><table><tr><th>Клас</th><th>Присъда</th><th>Брой</th><th>Размер</th>"
         "<th>Очакван MD</th><th>Предложение</th><th>Да</th><th>Не</th></tr>"]
    for c in klasove(k):
        r.append("<tr><td><code>%s</code></td><td>%s</td><td class=n>%d</td><td class=n>%s</td><td class=n>%s</td>"
                 "<td>%s</td><td class=\"n da\">%d</td><td class=\"n ne\">%d</td></tr>" % (
                     e(c["klas"]), e(IMENA.get(c["prisada"], c["prisada"])), c["broy"], chovesko(c["razmer"]),
                     e(_ochakvan(c)), e(c["predlozhenie"]), c["da"], c["ne"]))
    r.append("</table></div><h2>По файл</h2><div class=\"w\"><table><tr><th>id</th><th>Път</th><th>Вид</th>"
             "<th>Размер</th><th>Присъда</th><th>Защо</th><th>Очакван MD</th><th>Провери</th><th>Решение</th></tr>")
    for z in k["faylove"]:
        rs = z.get("reshenie")
        klas_r = "" if not rs else (" class=da" if rs["da"] else " class=ne")
        r.append("<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td class=n>%s</td><td>%s</td><td>%s</td>"
                 "<td class=n>%s</td><td>%s</td><td%s>%s</td></tr>" % (
                     e(z["id"]), e(z["put"]), e(z["vid"] or "?"), chovesko(z.get("razmer")),
                     e(IMENA.get(z["prisada"], z["prisada"])), e(z["prichina"]),
                     chovesko(z.get("ochakvan_md_bytes")), e(z.get("proveri") or ""), klas_r, e(_reshenie(z))))
    r.append("</table></div></main></body></html>\n")
    return "\n".join(r)
