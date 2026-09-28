"""`otchet`: какво е минало, какво не и защо — Markdown за човека, CSV за таблица."""
import csv
import io

from . import registar as rg
from .proverki import IMENA as PROVERKI

RED = (rg.ODOBREN, rg.VALIDIRAN, rg.ZA_PREGLED, rg.KANDIDAT, rg.OTKAZAN)
ZAGLAVIYA = {rg.ODOBREN: "Одобрени", rg.VALIDIRAN: "Валидирани — чакат човек", rg.ZA_PREGLED: "За преглед",
             rg.KANDIDAT: "Кандидати", rg.OTKAZAN: "Отказани"}
KOLONI = ("domeyn", "zhiv", "emisiya", "razresheniya", "ezik", "vid_sadarzhanie")  # ешелонът е отделна колона


def _rez(z, k):
    return (z.get("proverki") or {}).get(k, {}).get("rezultat", "—")


def _bez_emisiya(z):
    return bool(z.get("proverki")) and _rez(z, "emisiya") != "да"


def _tdm(z):
    return bool(((z.get("proverki") or {}).get("razresheniya") or {}).get("tdm", {}).get("rezervirano"))


def zashto(z):
    """Един ред: защо записът е там, където е."""
    s = z["sastoyanie"]
    if s == rg.OTKAZAN:
        o = z.get("otkazan") or {}
        return "отказан от %s: %s" % (o.get("rolya", "?"), o.get("prichina", ""))
    if s == rg.ZA_PREGLED:
        return "; ".join(z.get("za_pregled_prichini") or []) or "за преглед"
    if s == rg.KANDIDAT:
        if not z.get("proverki"):
            return "още не е проверен (validirai)"
        return "; ".join(z.get("prechki") or []) or "—"
    if s == rg.ODOBREN:
        o = z.get("odobren") or {}
        return "одобрен от %s%s" % (o.get("rolya", "?"), (": " + o["belezhka"]) if o.get("belezhka") else "")
    bel = [z["proverki"][k]["belezhka"] for k in ("domeyn", "zhiv", "emisiya", "razresheniya", "eshelon")
           if z.get("proverki", {}).get(k, {}).get("rezultat") == "неясно"]
    return ("без пречка; неясно: " + "; ".join(bel)) if bel else "без пречка"


def _md(s):
    return str(s if s is not None else "—").replace("|", "\\|").replace("\n", " ")


def md(r, cfg, pat, sega):
    izvori = r["izvori"]
    broy = {s: sum(1 for z in izvori if z["sastoyanie"] == s) for s in RED}
    red = ["# Извори — отчет", "",
           "Регистър: `%s` · към %s UTC · %d източника" % (pat, sega, len(izvori)), "",
           "| Състояние | Брой |", "|---|---|"]
    red += ["| %s | %d |" % (rg.IMENA[s], broy[s]) for s in RED]
    red += ["", "Проверени без емисия: **%d** · с TDM резервация: **%d** · кандидати с пречка: **%d**"
            % (sum(_bez_emisiya(z) for z in izvori), sum(_tdm(z) for z in izvori),
               sum(1 for z in izvori if z["sastoyanie"] == rg.KANDIDAT and z.get("prechki"))), "",
            "`validiran` значи само, че машината не е намерила пречка. Одобрява човек.", ""]
    zagl = "| id | организация | вид | ешелон | " + " | ".join(PROVERKI[k] for k in KOLONI) + " | защо |"
    for s in RED:
        grupa = [z for z in izvori if z["sastoyanie"] == s]
        if not grupa:
            continue
        red += ["## %s (%d)" % (ZAGLAVIYA[s], len(grupa)), "", zagl, "|" + "---|" * (len(KOLONI) + 5)]
        for z in grupa:
            vid = cfg["vidove"].get(z["vid"], {}).get("ime", z["vid"])
            esh = cfg["eshelon_imena"].get(z.get("eshelon"), z.get("eshelon"))
            if _rez(z, "eshelon") == "неясно":
                esh += " (неясно)"
            red.append("| `%s` | %s | %s | %s | %s | %s |" % (
                _md(z["id"]), _md(z.get("organizaciya")), _md(vid), _md(esh),
                " | ".join(_md(_rez(z, k)) for k in KOLONI), _md(zashto(z))))
        red.append("")
    tdm = [z for z in izvori if _tdm(z)]
    if tdm:
        red += ["## Резервирано по TDM — оценка и цитат да, пълно копие не", ""]
        red += ["- `%s` — %s" % (z["id"], "; ".join(z["proverki"]["razresheniya"]["tdm"]["signali"])) for z in tdm]
        red.append("")
    bez = [z for z in izvori if _bez_emisiya(z) and z["sastoyanie"] != rg.OTKAZAN]
    if bez:
        red += ["## Без емисия — решава се отделно (страница без емисия или ръчно)", ""]
        red += ["- `%s` — %s" % (z["id"], z["proverki"]["emisiya"].get("belezhka", "")) for z in bez]
        red.append("")
    return "\n".join(red)


def csv_(r, cfg):
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["id", "url", "organizaciya", "vid", "eshelon", "sastoyanie"] + list(KOLONI) + ["eshelon_proverka"] +
               ["emisiya_url", "tdm_signali", "ezik_kod", "validirano", "zashto"])
    for z in r["izvori"]:
        p = z.get("proverki") or {}
        w.writerow([z["id"], z["url"], z.get("organizaciya") or "", z["vid"], z.get("eshelon") or "",
                    z["sastoyanie"]] + [_rez(z, k) for k in KOLONI] + [_rez(z, "eshelon")] +
                   [p.get("emisiya", {}).get("url") or "",
                    "; ".join(p.get("razresheniya", {}).get("tdm", {}).get("signali", [])),
                    p.get("ezik", {}).get("ezik") or "", z.get("validirano") or "", zashto(z)])
    return out.getvalue()
