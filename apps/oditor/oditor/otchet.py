"""Отчетът (md или json) и разликата „преди/след“.

Правило 1: находка без доказателство не излиза навън — `pravilnik.s_dokazatelstvo` я изхвърля тук,
а броят на изхвърлените се казва. Отговор от модел без потвърден цитат също не излиза.
"""
import json

from .pravilnik import IMA, NEPR, s_dokazatelstvo

METODOLOGIYA = "METHODOLOGY.md"


def _chisti(signali):
    ostavat = [s for s in signali if s_dokazatelstvo(s)]
    return ostavat, len(signali) - len(ostavat)


def za_navan(zapis):
    """Резултатът без снимката и без находките без доказателство → речник за json и md."""
    r = json.loads(json.dumps(zapis["rezultat"]))
    izhvarleni = 0
    for st in r["stalbove"]:
        st["signali"], n = _chisti(st["signali"])
        izhvarleni += n
    for k in ("dopalnitelno", "pravni_signali"):
        r[k], n = _chisti(r[k])
        izhvarleni += n
    out = {"id": zapis["id"], "url": zapis["url"], "t": zapis["t"], "versiya": zapis["versiya"],
           "rulebook": r["rulebook"], "predishen": zapis.get("predishen"), "rezultat": r,
           "izhvarleni_bez_dokazatelstvo": izhvarleni}
    for k in ("politika", "izpit"):
        if zapis.get(k):
            d = json.loads(json.dumps(zapis[k]))
            spisak = "elementi" if k == "politika" else "otgovori"
            for e in d.get(spisak, []):
                if e["sastoyanie"] != IMA:
                    e.pop("citat", None)
                    e.pop("otgovor", None)
            d[spisak] = [e for e in d.get(spisak, []) if s_dokazatelstvo(e) or e.get("prichina")]
            out[k] = d
    return out


def _dok(s):
    chasti = []
    for d in s.get("dokazatelstvo") or []:
        x = "%s · HTTP %s · %s" % (d.get("url"), d.get("status"), d.get("t"))
        if d.get("izvor"):
            x += " · " + d["izvor"]
        if d.get("zaglavka"):
            x += " · `%s`" % d["zaglavka"]
        if d.get("selektor"):
            x += " · `%s`" % d["selektor"]
        if d.get("otkas"):
            x += " · „%s“" % str(d["otkas"]).replace("\n", " ")[:160]
        chasti.append(x)
    return "; ".join(chasti)


def _red(s):
    x = "- **%s** — %s" % (s["ime"], s["sastoyanie"])
    if s.get("stoynost") not in (None, ""):
        v = s["stoynost"]
        x += ": %s" % (", ".join(map(str, v)) if isinstance(v, list) else
                       ", ".join("%s %s" % kv for kv in v.items()) if isinstance(v, dict) else v)
    if s.get("samo_s_js"):
        x += " (само с JavaScript)"
    for k in ("belezhka", "prichina"):
        if s.get(k):
            x += " — %s" % s[k]
    for p in s.get("problemi") or []:
        x += "\n  - %s" % p
    if s["sastoyanie"] != NEPR and s.get("dokazatelstvo"):
        x += "\n  - доказателство: %s" % _dok(s)
    return x


def md(zapis):
    n = za_navan(zapis)
    r = n["rezultat"]
    L = ["# Одитор — %s" % n["url"], "",
         "Проверка `%s` · %s · oditor %s · rulebook %s · заявки: %s" % (n["id"], n["t"], n["versiya"], n["rulebook"],
                                                                         r.get("zayavki")), ""]
    if r.get("kraen_url") and r["kraen_url"] != n["url"]:
        L += ["Краен адрес: %s" % r["kraen_url"], ""]
    L += ["**Оценка: %d от %d** (предпоставки за AI агенти и търсачки)" % (r["tochki"], r["ot"])]
    if n.get("izpit") and n["izpit"].get("sastoyanie") == IMA:
        L += ["**Агентски изпит: %d от %d** (отделно от оценката)" % (n["izpit"]["tochki"], n["izpit"]["ot"])]
    L += [""]
    br = r.get("brauzar")
    if br:
        if br.get("izpolzvan"):
            L += ["Браузър с JavaScript: използван (%s)." % br.get("prichina"), ""]
        else:
            L += ["Браузър с JavaScript: непроверено — %s (повод: %s)." % (br.get("zashto"), br.get("prichina")), ""]
    L += ["| Стълб | Състояние | Точка |", "|---|---|---|"]
    for s in r["stalbove"]:
        L.append("| %s | %s | %d |" % (s["ime"], s["sastoyanie"], s["tochka"]))
    for s in r["stalbove"]:
        L += ["", "## %s — %s" % (s["ime"], s["sastoyanie"]), ""] + [_red(x) for x in s["signali"]]
    L += ["", "## Допълнително (без точки)", ""] + [_red(x) for x in r["dopalnitelno"]]
    L += ["", "## Правни сигнали", "", "_%s_" % r["pravni_belezhka"], ""] + [_red(x) for x in r["pravni_signali"]]
    if r.get("obshti_adresi"):
        L.append("- **общи фирмени адреси**: %s" % ", ".join(r["obshti_adresi"]))
    if r.get("drugi_adresi_ne_se_pazyat"):
        L.append("- други имейл адреси: %d — не се пазят (може да са лични)" % r["drugi_adresi_ne_se_pazyat"])
    p = n.get("politika")
    if p:
        L += ["", "## Политика за поверителност", ""]
        if p.get("sastoyanie") != IMA:
            L.append("непроверено — %s" % p.get("prichina"))
        else:
            L += ["%s · модел %s · потвърдени цитати: %d от %d" % (p["url"], p["model"], p["potvardeni"], p["ot"]),
                  "", "_Отбелязва се само има ли го в текста — не дали е законосъобразно. За юрист._", ""]
            for e in p["elementi"]:
                L.append(_red(e) if e["sastoyanie"] != IMA else "- **%s** — има: „%s“" % (e["ime"], e["citat"]))
    iz = n.get("izpit")
    if iz:
        L += ["", "## Агентски изпит", ""]
        if iz.get("sastoyanie") != IMA:
            L.append("непроверено — %s" % iz.get("prichina"))
        else:
            for o in iz["otgovori"]:
                if o["sastoyanie"] == IMA:
                    L.append("- **%s** — има: „%s“" % (o["vapros"], o["citat"]))
                else:
                    L.append("- **%s** — %s%s" % (o["vapros"], o["sastoyanie"],
                                                  " — %s" % (o.get("prichina") or o.get("belezhka") or "")))
    if n["izhvarleni_bez_dokazatelstvo"]:
        L += ["", "_Изхвърлени находки без доказателство: %d._" % n["izhvarleni_bez_dokazatelstvo"]]
    L += ["", "---", "Методология, правила за заявките, оспорване и отказ: %s (rulebook %s)." % (METODOLOGIYA, n["rulebook"])]
    return "\n".join(L) + "\n"


def json_(zapis):
    return json.dumps(za_navan(zapis), ensure_ascii=False, indent=2) + "\n"


def _sastoyaniya(zapis):
    r = zapis["rezultat"]
    d = {}
    for st in r["stalbove"]:
        d["стълб " + st["ime"]] = st["sastoyanie"]
        for s in st["signali"]:
            d[s["ime"]] = s["sastoyanie"]
    for s in r["dopalnitelno"] + r["pravni_signali"]:
        d[s["ime"]] = s["sastoyanie"]
    for k, spisak, ime in (("politika", "elementi", "политика: "), ("izpit", "otgovori", "изпит: ")):
        for e in (zapis.get(k) or {}).get(spisak, []):
            d[ime + (e.get("ime") or e.get("vapros"))] = e["sastoyanie"]
    return d


def razlika(predi, sled):
    """→ редове „преди → след“ за всичко, което е сменило състоянието си."""
    a, b = _sastoyaniya(predi), _sastoyaniya(sled)
    redove = ["Оценка: %d → %d от %d" % (predi["rezultat"]["tochki"], sled["rezultat"]["tochki"], sled["rezultat"]["ot"])]
    if predi.get("izpit") or sled.get("izpit"):
        redove.append("Изпит: %s → %s" % ((predi.get("izpit") or {}).get("tochki", "—"),
                                          (sled.get("izpit") or {}).get("tochki", "—")))
    if predi["rezultat"]["rulebook"] != sled["rezultat"]["rulebook"]:
        redove.append("Внимание: различен правилник (%s → %s)" % (predi["rezultat"]["rulebook"], sled["rezultat"]["rulebook"]))
    for k in sorted(set(a) | set(b), key=lambda x: (not x.startswith("стълб"), x)):
        if a.get(k) != b.get(k):
            redove.append("%s: %s → %s" % (k, a.get(k, "—"), b.get(k, "—")))
    if len(redove) == 1 + bool(predi.get("izpit") or sled.get("izpit")):
        redove.append("без промяна в състоянията")
    return redove
