"""python -m misii validirai | generiray | podpishi | proveri

Кодове на изход:
  0 готово
  1 грешка: невалиден документ, непознат район, счупен подпис, липсващ ключ, неразбираем config или файл
  2 грешна употреба
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from . import config, generator, podpis, validator

IZHOD_OK, IZHOD_GRESHKA, IZHOD_UPOTREBA = 0, 1, 2


class Upotreba(Exception):
    pass


class Greshka(Exception):
    pass


def dnevnik(ok, obobshtenie):
    """Ред в $SHINKANSEN_RUNS/misii.jsonl — само броеве и код, без съдържание."""
    sf = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if sf:
        with open(sf, "w", encoding="utf-8") as f:
            f.write(obobshtenie)
        return
    runs = os.environ.get("SHINKANSEN_RUNS")
    if not runs:
        return
    os.makedirs(runs, exist_ok=True)
    zap = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "helper": "misii",
           "ok": bool(ok), "summary": obobshtenie[:200]}
    with open(os.path.join(runs, "misii.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(zap, ensure_ascii=False) + "\n")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        raise Upotreba(message)


def parser():
    p = _Parser(prog="python -m misii", description="Мисии за местен принос.")
    obshti = _Parser(add_help=False)
    obshti.add_argument("--config", help="път до config.json")
    sub = p.add_subparsers(dest="komanda", required=True, parser_class=_Parser)
    s = sub.add_parser("validirai", parents=[obshti], help="проверка по схемата и правилата")
    s.add_argument("vid", choices=validator.VIDOVE_DOKUMENTI)
    s.add_argument("fayl")
    s = sub.add_parser("generiray", parents=[obshti], help="мисии от дупките в базата за един район")
    s.add_argument("--baza", required=True, help="JSON с обектите")
    s.add_argument("--rayon", required=True)
    s.add_argument("--oblasti", required=True, help="през запетая: kultura,sport,…")
    s.add_argument("--data", help="датата на изданието ГГГГ-ММ-ДД (по подразбиране днес, UTC)")
    s.add_argument("--izhod", help="файл (иначе на екрана)")
    for ime, pom in (("podpishi", "подписва списък"), ("proveri", "проверява подписа и всяка мисия")):
        s = sub.add_parser(ime, parents=[obshti], help=pom)
        s.add_argument("spisak")
        s.add_argument("--klyuch-fayl", help="файл с ключа, извън хранилището (иначе $MISII_KLYUCH)")
    sub.choices["podpishi"].add_argument("--izhod", help="файл (иначе на мястото на входа)")
    return p


def _cheti(pat):
    try:
        with open(pat, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise Greshka("не мога да прочета %s: %s" % (pat, e))
    except ValueError as e:
        raise Greshka("%s не е валиден JSON: %s" % (pat, e))


def _pishi(pat, d):
    tekst = json.dumps(d, ensure_ascii=False, indent=1) + "\n"
    if not pat:
        sys.stdout.write(tekst)
        return
    with open(pat, "w", encoding="utf-8") as f:
        f.write(tekst)


def izpalni(a):
    cfg = config.zaredi(a.config)
    if a.komanda == "validirai":
        g = validator.validirai(_cheti(a.fayl), a.vid, cfg)
        if g:
            raise Greshka("невалиден %s (%d):\n  - %s" % (a.vid, len(g), "\n  - ".join(g)))
        print("%s: валиден %s" % (a.fayl, a.vid))
        return "validirai %s ok" % a.vid
    if a.komanda == "generiray":
        oblasti = [x.strip() for x in a.oblasti.split(",") if x.strip()]
        if not oblasti:
            raise Upotreba("--oblasti е празно")
        data = a.data or datetime.now(timezone.utc).date().isoformat()
        try:
            s = generator.generiray(_cheti(a.baza), a.rayon, oblasti, cfg, data)
        except generator.GreshkaBaza as e:
            raise Greshka(str(e))
        g = validator.validirai(s, "spisak", cfg)
        if g:  # генераторът не пуска навън нещо, което самият помощник би отхвърлил
            raise Greshka("генерираният списък не минава схемата:\n  - %s" % "\n  - ".join(g))
        _pishi(a.izhod, s)
        if a.izhod:
            print("%s: %d мисии за %s (%s)" % (a.izhod, len(s["misii"]), a.rayon, ", ".join(s["oblasti"])))
        return "generiray %d" % len(s["misii"])
    k = podpis.klyuch(cfg, a.klyuch_fayl)
    s = _cheti(a.spisak)
    if a.komanda == "podpishi":
        g = validator.validirai(s, "spisak", cfg)
        if g:
            raise Greshka("не подписвам невалиден списък:\n  - %s" % "\n  - ".join(g))
        _pishi(a.izhod or a.spisak, podpis.podpishi(s, k, cfg["podpis"]["klyuch_id"]))
        print("подписан: %s (%d мисии, ключ %s)" % (a.izhod or a.spisak, len(s["misii"]), cfg["podpis"]["klyuch_id"]))
        return "podpishi %d" % len(s["misii"])
    # proveri: първо подписът, после съдържанието — нищо, дошло отвън, не се изпълнява
    podpis.proveri(s, k, cfg["podpis"]["klyuch_id"])
    g = validator.validirai(s, "spisak", cfg)
    if g:
        raise Greshka("подписът е верен, но списъкът не минава схемата:\n  - %s" % "\n  - ".join(g))
    print("%s: подписът е верен · район %s · %d мисии" % (a.spisak, s["rayon"], len(s["misii"])))
    return "proveri %d" % len(s["misii"])


def main(argv=None):
    try:
        a = parser().parse_args(argv)
        obobshtenie = izpalni(a)
        kod = IZHOD_OK
    except Upotreba as e:
        print("misii: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_UPOTREBA, "употреба"
    except (Greshka, config.GreshkaConfig, podpis.GreshkaPodpis, validator.GreshkaShema) as e:
        print("misii: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_GRESHKA, type(e).__name__
    except OSError as e:
        print("misii: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_GRESHKA, "OSError"
    dnevnik(kod == IZHOD_OK, "%s · exit %d" % (obobshtenie, kod))
    return kod
