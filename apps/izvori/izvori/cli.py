"""python -m izvori dobavi | validirai | odobri | otkazhi | otchet | iznesi

Кодове на изход:
  0 готово
  1 грешка (непознат id, неразбираем регистър, одобрение от недопустимо състояние, повторен адрес)
  2 грешна употреба (вкл. одобрение или отказ без роля, или с роля извън config)
"""
import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone

from . import VERSIYA, config, dokazatelstva, iznos, otchet, proverki
from . import registar as rg
from .mrezha import Mrezha, user_agent

IZHOD_OK, IZHOD_GRESHKA, IZHOD_UPOTREBA = 0, 1, 2


class Upotreba(Exception):
    pass


class Greshka(Exception):
    pass


def dnevnik(ok, obobshtenie):
    """Ред в $SHINKANSEN_RUNS/izvori.jsonl — само броеве и код."""
    sf = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if sf:
        with open(sf, "w", encoding="utf-8") as f:
            f.write(obobshtenie)
        return
    runs = os.environ.get("SHINKANSEN_RUNS")
    if not runs:
        return
    os.makedirs(runs, exist_ok=True)
    zap = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "helper": "izvori",
           "ok": bool(ok), "summary": obobshtenie[:200]}
    with open(os.path.join(runs, "izvori.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(zap, ensure_ascii=False) + "\n")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        raise Upotreba(message)


def parser():
    p = _Parser(prog="python -m izvori", description="Регистър и валидиране на първоизточници (Z12).")
    obshti = _Parser(add_help=False)
    obshti.add_argument("--config", help="път до config.json")
    obshti.add_argument("--registar", help="регистърът (по подразбиране izvori.json)")
    obshti.add_argument("--dokazatelstva", help="папката с доказателствата (по подразбиране до регистъра)")
    obshti.add_argument("--sega", help=argparse.SUPPRESS)  # за тестовете: час по UTC, ISO
    sub = p.add_subparsers(dest="komanda", required=True, parser_class=_Parser)
    d = sub.add_parser("dobavi", parents=[obshti], help="нов кандидат")
    d.add_argument("url")
    d.add_argument("--vid", required=True, help="вид от config (proizvoditel, regulator, …)")
    d.add_argument("--organizaciya", help="името на организацията, както е в config")
    v = sub.add_parser("validirai", parents=[obshti], help="машинна проверка, записва доказателства")
    v.add_argument("--samo", help="само този id")
    for ime, pom in (("odobri", "одобрение — само човек, с роля"), ("otkazhi", "отказ — само човек, с роля")):
        s = sub.add_parser(ime, parents=[obshti], help=pom)
        s.add_argument("id")
        s.add_argument("--ot", help="ролята (не името) на човека, който решава")
    sub.choices["odobri"].add_argument("--belezhka", default="")
    sub.choices["otkazhi"].add_argument("--prichina")
    o = sub.add_parser("otchet", parents=[obshti], help="какво е минало, какво не и защо")
    o.add_argument("--format", choices=("md", "csv"), default="md")
    o.add_argument("--izhod", help="файл (иначе на екрана)")
    i = sub.add_parser("iznesi", parents=[obshti], help="само одобрените, във формата на Z8")
    i.add_argument("--za", required=True, choices=("filtar",))
    i.add_argument("--izhod", default="izvori_filtar.json")
    return p


def _sega(a):
    if a.sega:
        return datetime.fromisoformat(a.sega.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _t(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _pishi(path, tekst):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tekst)


def _rolya(cfg, rolya):
    if not (rolya or "").strip():
        raise Upotreba("отказ: решението иска роля (--ot). Ролята, не името.")
    if rolya.strip() not in cfg["roli_odobryavashti"]:
        raise Upotreba("отказ: „%s“ не е роля от config (roli_odobryavashti: %s). Ролята, не името."
                       % (rolya, ", ".join(cfg["roli_odobryavashti"])))
    return rolya.strip()


# ─────────── командите ───────────

def dobavi(a, cfg, r, sega):
    if a.vid not in cfg["vidove"]:
        raise Upotreba("непознат вид „%s“ (от config: %s)" % (a.vid, ", ".join(cfg["vidove"])))
    url = a.url.strip()
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        p = None
    if not p or p.scheme not in ("http", "https") or not p.hostname:
        raise Upotreba("адресът трябва да е http(s)://…")
    org = a.organizaciya
    if org and config.organizaciya(cfg, org) is None:
        raise Upotreba("организацията „%s“ не е в config (organizacii[].ime)" % org)
    if not org:
        o = config.po_domeyn(cfg, p.hostname)
        org = o["ime"] if o else None
    for z in r["izvori"]:
        if rg.kanon(z["url"]) == rg.kanon(url):
            raise Greshka("адресът вече е в регистъра като „%s“" % z["id"])
    t = _t(sega)
    zapis = {"id": rg.nov_id(r, url), "url": url, "vid": a.vid, "organizaciya": org,
             "eshelon": config.eshelon(cfg, a.vid), "sastoyanie": rg.KANDIDAT, "dobaven": t,
             "istoriya": [{"t": t, "ot": None, "kam": rg.KANDIDAT, "koy": rg.MASHINA, "belezhka": "добавен"}]}
    r["izvori"].append(zapis)
    print("%s: кандидат (%s, %s%s)" % (zapis["id"], a.vid, cfg["eshelon_imena"].get(zapis["eshelon"]),
                                        ", " + org if org else ", без организация"))
    return "dobavi %s" % zapis["id"]


def validirai(a, cfg, r, sega, papka_dok, mrezha_fabrika):
    if a.samo:
        izbrani = [rg.nameri(r, a.samo)]
    else:
        izbrani = [z for z in r["izvori"] if z["sastoyanie"] != rg.OTKAZAN]
    t, den = _t(sega), sega.date().isoformat()
    broy = {}
    for z in izbrani:
        if z["sastoyanie"] == rg.OTKAZAN:
            print("%s: отказан — не се проверява" % z["id"])
            continue
        m = mrezha_fabrika(cfg)
        predishni = (dokazatelstva.posledno(papka_dok, z["id"]) or {}).get("proverki")
        p, prechki = proverki.validirai(cfg, z, m)
        predi = z["sastoyanie"]
        if predi in (rg.ODOBREN, rg.ZA_PREGLED):
            prichini = proverki.sravni(predishni, p)
            if prichini:
                z["za_pregled_prichini"] = prichini
                if predi == rg.ODOBREN:
                    rg.smeni(z, rg.ZA_PREGLED, t, belezhka="; ".join(prichini))
        else:
            novo = rg.KANDIDAT if prechki else rg.VALIDIRAN
            if novo != predi:
                rg.smeni(z, novo, t, belezhka="; ".join(prechki) or "без пречка")
        z["eshelon"] = p["eshelon"]["eshelon"]
        z["proverki"], z["prechki"], z["validirano"] = p, prechki, t
        dok = {"id": z["id"], "url": z["url"], "t": t, "ua": user_agent(cfg), "versiya": VERSIYA,
               "sastoyanie_predi": predi, "sastoyanie_sled": z["sastoyanie"], "proverki": p, "prechki": prechki,
               "zayavki": m.zayavki}
        pat = dokazatelstva.zapishi(papka_dok, z["id"], den, dok)
        broy[z["sastoyanie"]] = broy.get(z["sastoyanie"], 0) + 1
        kratko = " · ".join("%s %s" % (proverki.IMENA[k], p[k]["rezultat"]) for k in p)
        print("%s: %s — %s" % (z["id"], rg.IMENA[z["sastoyanie"]], kratko))
        for x in prechki:
            print("    пречка: %s" % x)
        if z["sastoyanie"] == rg.ZA_PREGLED:
            for x in z.get("za_pregled_prichini") or []:
                print("    за преглед: %s" % x)
        print("    доказателства: %s" % pat)
    return "validirai %d · %s" % (sum(broy.values()), ", ".join("%s %d" % kv for kv in sorted(broy.items())))


def odobri(a, cfg, r, sega):
    rolya = _rolya(cfg, a.ot)
    z = rg.nameri(r, a.id)
    if z["sastoyanie"] not in (rg.VALIDIRAN, rg.ZA_PREGLED):
        raise Greshka("„%s“ е %s — одобрява се само валидиран или за преглед (първо validirai)"
                      % (z["id"], rg.IMENA[z["sastoyanie"]]))
    t = _t(sega)
    z["odobren"] = {"rolya": rolya, "t": t, "belezhka": a.belezhka}
    z.pop("za_pregled_prichini", None)
    rg.smeni(z, rg.ODOBREN, t, ot=rolya, belezhka=a.belezhka)
    print("%s: одобрен от %s" % (z["id"], rolya))
    return "odobri"


def otkazhi(a, cfg, r, sega):
    rolya = _rolya(cfg, a.ot)
    if not (a.prichina or "").strip():
        raise Upotreba("отказът иска причина (--prichina)")
    z = rg.nameri(r, a.id)
    t = _t(sega)
    z["otkazan"] = {"rolya": rolya, "t": t, "prichina": a.prichina.strip()}
    rg.smeni(z, rg.OTKAZAN, t, ot=rolya, belezhka=a.prichina.strip())
    print("%s: отказан от %s" % (z["id"], rolya))
    return "otkazhi"


def izpalni(a, mrezha_fabrika=None):
    cfg = config.zaredi(a.config)
    pat = a.registar or cfg.get("registar") or "izvori.json"
    papka_dok = a.dokazatelstva or cfg.get("papka_dokazatelstva") or \
        os.path.join(os.path.dirname(os.path.abspath(pat)), "dokazatelstva")
    sega = _sega(a)
    r = rg.zaredi(pat)
    if a.komanda == "otchet":
        tekst = otchet.md(r, cfg, pat, _t(sega)) if a.format == "md" else otchet.csv_(r, cfg)
        if a.izhod:
            _pishi(a.izhod, tekst)
            print("Отчет: %s" % a.izhod)
        else:
            sys.stdout.write(tekst if tekst.endswith("\n") else tekst + "\n")
        return "otchet %s · %d" % (a.format, len(r["izvori"]))
    if a.komanda == "iznesi":
        spisak = iznos.za_filtar(r, cfg)
        _pishi(a.izhod, json.dumps(spisak, ensure_ascii=False, indent=2) + "\n")
        print("Изнесени %d одобрени от %d → %s" % (len(spisak), len(r["izvori"]), a.izhod))
        return "iznesi %d" % len(spisak)
    if a.komanda == "validirai":
        fab = mrezha_fabrika or (lambda c: Mrezha(c))
        obobshtenie = validirai(a, cfg, r, sega, papka_dok, fab)
    else:
        obobshtenie = {"dobavi": dobavi, "odobri": odobri, "otkazhi": otkazhi}[a.komanda](a, cfg, r, sega)
    rg.zapishi(pat, r)
    return obobshtenie


def main(argv=None, mrezha_fabrika=None):
    try:
        a = parser().parse_args(argv)
        obobshtenie = izpalni(a, mrezha_fabrika)
        kod = IZHOD_OK
    except Upotreba as e:
        print("izvori: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_UPOTREBA, "употреба"
    except (Greshka, config.GreshkaConfig, rg.GreshkaRegistar) as e:
        print("izvori: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_GRESHKA, type(e).__name__
    except OSError as e:
        print("izvori: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_GRESHKA, "OSError"
    dnevnik(kod == IZHOD_OK, "%s · exit %d" % (obobshtenie, kod))
    return kod
