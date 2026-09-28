"""python -m sito skanirai | karta | reshi | preobrazuvay | otchet

Кодове на изход:
  0 готово (и когато файл е „неясно“ — то е записано, не е грешка на програмата)
  1 грешка (липсваща папка, неразбираема карта или config, непознат id, празен клас)
  2 грешна употреба (вкл. решение без роля или с роля извън config, изход вътре в изходната папка)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from . import config, karta, otchet, preobrazuvay
from .skaner import Skaner

IZHOD_OK, IZHOD_GRESHKA, IZHOD_UPOTREBA = 0, 1, 2


class Upotreba(Exception):
    pass


class Greshka(Exception):
    pass


def dnevnik(ok, obobshtenie):
    """Ред в $SHINKANSEN_RUNS/sito.jsonl — само броеве и код."""
    sf = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if sf:
        with open(sf, "w", encoding="utf-8") as f:
            f.write(obobshtenie)
        return
    runs = os.environ.get("SHINKANSEN_RUNS")
    if not runs:
        return
    os.makedirs(runs, exist_ok=True)
    zap = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "helper": "sito",
           "ok": bool(ok), "summary": obobshtenie[:200]}
    with open(os.path.join(runs, "sito.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(zap, ensure_ascii=False) + "\n")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        raise Upotreba(message)


def parser():
    p = _Parser(prog="python -m sito", description="Сито (Z14): отделя смисъла от въздуха.")
    obshti = _Parser(add_help=False)
    obshti.add_argument("--config", help="път до config.json")
    obshti.add_argument("--sega", help=argparse.SUPPRESS)  # за тестовете: час по UTC, ISO
    sub = p.add_subparsers(dest="komanda", required=True, parser_class=_Parser)
    s = sub.add_parser("skanirai", parents=[obshti], help="САМО ЧЕТЕНЕ: хеш, вид, размер, присъда, предложение")
    s.add_argument("papka")
    s.add_argument("--izhod", default="karta.json", help="картата (по подразбиране karta.json)")
    k = sub.add_parser("karta", parents=[obshti], help="картата за човека: да/не по файл и по клас")
    k.add_argument("karta")
    k.add_argument("--format", choices=("md", "html", "csv"), default="md")
    k.add_argument("--izhod", help="файл (иначе на екрана)")
    r = sub.add_parser("reshi", parents=[obshti], help="решение за цял клас или за един файл — само човек, с роля")
    r.add_argument("karta")
    koe = r.add_mutually_exclusive_group(required=True)
    koe.add_argument("--klas", help="клас (напр. opakovka:html) или цяла присъда (напр. opakovka)")
    koe.add_argument("--fayl", help="id на файл от картата")
    dane = r.add_mutually_exclusive_group(required=True)
    dane.add_argument("--da", action="store_true")
    dane.add_argument("--ne", action="store_true")
    r.add_argument("--ot", help="ролята (не името) на човека, който решава")
    pr = sub.add_parser("preobrazuvay", parents=[obshti], help="без --go само планът; с --go пише MD + chunks")
    pr.add_argument("karta")
    pr.add_argument("--izhod", required=True, help="папката за MD и chunks.jsonl")
    pr.add_argument("--go", action="store_true", help="наистина пиши")
    o = sub.add_parser("otchet", parents=[obshti], help="преди/след: брой, размер, очакван и реален MD")
    o.add_argument("karta")
    o.add_argument("--izhod", help="файл (иначе на екрана)")
    return p


def _sega(a):
    if a.sega:
        return datetime.fromisoformat(a.sega.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _t(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def vatre(pat, koren):
    """Дали pat е в koren (или е самата koren) — след разрешаване на връзките."""
    p, k = os.path.realpath(pat), os.path.realpath(koren)
    return p == k or p.startswith(k.rstrip(os.sep) + os.sep)


def _ne_vav_izvora(pat, koren, kakvo):
    if vatre(pat, koren):
        raise Upotreba("отказ: %s (%s) е вътре в изходната папка — там Сито само чете" % (kakvo, pat))


def _pishi(pat, tekst, koren):
    _ne_vav_izvora(pat, koren, "изходът")
    d = os.path.dirname(os.path.abspath(pat))
    os.makedirs(d, exist_ok=True)
    with open(pat, "w", encoding="utf-8") as f:
        f.write(tekst)


def _rolya(cfg, rolya):
    if not (rolya or "").strip():
        raise Upotreba("отказ: решението иска роля (--ot). Ролята, не името.")
    if rolya.strip() not in cfg["roli_reshavashti"]:
        raise Upotreba("отказ: „%s“ не е роля от config (roli_reshavashti: %s). Ролята, не името."
                       % (rolya, ", ".join(cfg["roli_reshavashti"])))
    return rolya.strip()


def _izvedi(a, tekst, koren):
    if a.izhod:
        _pishi(a.izhod, tekst, koren)
        print("Записано: %s" % a.izhod)
    else:
        sys.stdout.write(tekst if tekst.endswith("\n") else tekst + "\n")


# ─────────── командите ───────────

def skanirai(a, cfg, sega):
    if not os.path.isdir(a.papka):
        raise Greshka("няма такава папка: %s" % a.papka)
    _ne_vav_izvora(a.izhod, a.papka, "картата")
    k = Skaner(a.papka, cfg, sega).pusni()
    karta.zapishi(a.izhod, k)
    broy = {}
    for z in k["faylove"]:
        broy[z["prisada"]] = broy.get(z["prisada"], 0) + 1
    print("Сканирани %d файла (само четене) → %s" % (len(k["faylove"]), a.izhod))
    for pr in karta.REDA:
        if pr in broy:
            print("  %-14s %d" % (pr, broy[pr]))
    lipsvat = [i for i, ok in k["instrumenti"].items() if not ok]
    if lipsvat:
        print("  липсващи инструменти: %s" % ", ".join(lipsvat))
    return "skanirai %d · %s" % (len(k["faylove"]), ", ".join("%s %d" % kv for kv in sorted(broy.items())))


def reshi(a, cfg, sega):
    rolya = _rolya(cfg, a.ot)
    k = karta.zaredi(a.karta)
    if a.fayl:
        izbrani = [z for z in k["faylove"] if z["id"] == a.fayl]
        if not izbrani:
            raise Greshka("няма файл с id „%s“ в картата" % a.fayl)
        nachin = "fayl"
    else:
        izbrani = [z for z in k["faylove"] if z["klas"] == a.klas or z["prisada"] == a.klas]
        if not izbrani:
            raise Greshka("няма файлове в клас „%s“ (класовете са в `karta`)" % a.klas)
        nachin = "klas"
    t, n, propusnati = _t(sega), 0, 0
    for z in izbrani:
        if a.da and z["prisada"] in preobrazuvay.NEPREOBRAZUVAEMI:
            propusnati += 1
            continue
        z["reshenie"] = {"da": bool(a.da), "rolya": rolya, "t": t, "nachin": nachin,
                         "za": a.fayl if a.fayl else a.klas}
        n += 1
    karta.zapishi(a.karta, k)
    print("Решение „%s“ от %s за %d файла%s" % ("да" if a.da else "не", rolya, n,
                                             (" (пропуснати %d: дубликат/неясно/контейнер — там нищо не се прави)"
                                              % propusnati) if propusnati else ""))
    return "reshi %s %d" % ("da" if a.da else "ne", n)


def izpalni(a):
    cfg = config.zaredi(a.config)
    sega = _sega(a)
    if a.komanda == "skanirai":
        return skanirai(a, cfg, sega)
    if a.komanda == "reshi":
        return reshi(a, cfg, sega)
    k = karta.zaredi(a.karta)
    if a.komanda == "karta":
        tekst = {"md": karta.md, "html": karta.html_, "csv": karta.csv_}[a.format](k)
        _izvedi(a, tekst, k["koren"])
        return "karta %s · %d" % (a.format, len(k["faylove"]))
    if a.komanda == "otchet":
        _izvedi(a, otchet.md(k), k["koren"])
        return "otchet · %d" % len(k["faylove"])
    # preobrazuvay
    _ne_vav_izvora(a.izhod, k["koren"], "изходната папка на MD")
    if not a.go:
        preobrazuvay.plan(k, a.izhod, cfg)
        return "preobrazuvay plan"
    ok, chunks = preobrazuvay.go(k, a.izhod, cfg, _t(sega))
    if ok:
        karta.zapishi(a.karta, k)
    return "preobrazuvay go %d · chunks %d" % (ok, chunks)


def main(argv=None):
    try:
        a = parser().parse_args(argv)
        obobshtenie = izpalni(a)
        kod = IZHOD_OK
    except Upotreba as e:
        print("sito: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_UPOTREBA, "употреба"
    except (Greshka, config.GreshkaConfig, karta.GreshkaKarta) as e:
        print("sito: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_GRESHKA, type(e).__name__
    except OSError as e:
        print("sito: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_GRESHKA, "OSError"
    dnevnik(kod == IZHOD_OK, "%s · exit %d" % (obobshtenie, kod))
    return kod
