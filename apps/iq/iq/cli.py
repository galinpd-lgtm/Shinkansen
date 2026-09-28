"""python -m iq izchisli | otchet | znachka | metodika

Кодове на изход:
  0 готово (izchisli: и когато степента е „Без степен“)
  1 грешка или отказ (otchet/znachka за канал без `"saglasie": true` в регистъра и без --vatreshno)
  2 грешна употреба
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

from . import config, danni, istoriya, metodika, otchet, znachka
from . import stepen as st
from .tekstove import chislo, den, procent

IZHOD_OK, IZHOD_GRESHKA = 0, 1


class Otkaz(Exception):
    pass


def dnevnik(ok, obobshtenie):
    """Ред в $SHINKANSEN_RUNS/iq.jsonl — само степен, броеве и код; нищо от текстовете."""
    sf = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if sf:
        with open(sf, "w", encoding="utf-8") as f:
            f.write(obobshtenie)
        return
    runs = os.environ.get("SHINKANSEN_RUNS")
    if not runs:
        return
    os.makedirs(runs, exist_ok=True)
    zap = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "helper": "iq",
           "ok": bool(ok), "summary": obobshtenie[:200]}
    with open(os.path.join(runs, "iq.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(zap, ensure_ascii=False) + "\n")


def _den(s):
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError("датата е ГГГГ-ММ-ДД")


def parser():
    p = argparse.ArgumentParser(prog="python -m iq", description="Степен на качество на информационен канал.")
    obshti = argparse.ArgumentParser(add_help=False)
    obshti.add_argument("--config", help="път до config.json")
    kanal = argparse.ArgumentParser(add_help=False)
    kanal.add_argument("--kanal", required=True, help="id на канала (както е в базата на филтъра)")
    kanal.add_argument("--danni", help="папката с базата на филтъра (замества filtar_danni)")
    kanal.add_argument("--kanali", help="регистърът на каналите (замества config)")
    kanal.add_argument("--ot", type=_den, help="начало на периода (иначе последните prozorec_dni дни)")
    kanal.add_argument("--do", type=_den, help="край на периода (по подразбиране днес)")
    kanal.add_argument("--papka", help="папката на IQ за istoriya.jsonl и promeni.log (замества papka_danni)")
    kanal.add_argument("--dnes", type=_den, help=argparse.SUPPRESS)  # за тестовете: „днес“
    sub = p.add_subparsers(dest="komanda", required=True)
    i = sub.add_parser("izchisli", parents=[obshti, kanal], help="степен и числата отдолу")
    i.add_argument("--json", action="store_true", help="изход като JSON")
    for ime, pom in (("otchet", "отчет на български (Markdown)"), ("znachka", "значка SVG")):
        s = sub.add_parser(ime, parents=[obshti, kanal], help=pom)
        s.add_argument("--izhod", required=True, help="файл за изхода")
        s.add_argument("--vatreshno", action="store_true",
                       help="за вътрешна употреба без съгласие на канала — с надпис „вътрешно · непубликувано“")
    sub.choices["znachka"].add_argument("--podpis", help="по желание: кратък подпис под значката")
    m = sub.add_parser("metodika", parents=[obshti], help="публичното описание на методиката")
    m.add_argument("--izhod", required=True)
    return p


def izchisli(a, cfg):
    """→ {"kanal", "ch", "stepen", "mashinna", "izchisleno"}."""
    dnes = a.dnes or date.today()
    do = a.do or dnes
    ot, do = st.period(do, cfg["prozorec_dni"], a.ot)
    if ot > do:
        raise config.GreshkaConfig("--ot е след --do")
    registar = config.kanali(cfg, a.kanali)
    b = danni.otvori(a.danni or cfg["filtar_danni"])
    try:
        zap = registar.get(a.kanal)
        if zap is None and not danni.ima_kanal(b, a.kanal):
            raise danni.GreshkaDanni("непознат канал „%s“: няма го нито в регистъра, нито в базата" % a.kanal)
        kanal = dict(zap or {"id": a.kanal, "ime": danni.ime_ot_bazata(b, a.kanal) or a.kanal})
        ch = st.chisla(danni.zapisi(b, a.kanal), ot, do, cfg)
    finally:
        b.close()
    mashinna = st.stepen(ch, cfg)
    return {"kanal": kanal, "ch": ch, "mashinna": mashinna, "stepen": st.s_rachno(mashinna, zap, cfg),
            "izchisleno": dnes.isoformat()}


def _pokazhi(r):
    ch, s = r["ch"], r["stepen"]
    p = ch["period"]
    print("%s (%s) · %s – %s" % (r["kanal"]["ime"], r["kanal"]["id"], den(p["ot"]), den(p["do"])))
    print("Степен: %s (%s)" % (s["kod"], s["cvyat_ime"]))
    for x in s["prichini"]:
        print("  · %s" % x)
    print("Оценени записа:                  %d" % ch["zapisi"])
    print("Средна оценка:                   %s" % chislo(ch["sredna"]))
    print("Записи с именувани източници:    %s" % procent(ch["dyal_imenuvani"]))
    print("Записи с манипулативни похвати:  %s" % procent(ch["dyal_pohvati"]))
    print("Средна или висока увереност:     %s" % procent(ch["dyal_uverenost"]))
    print("История:                         %d дни" % ch["istoriya_dni"])
    print("Седмици с публикации:            %d от %d" % (ch["sedmici_s_publikacii"], len(ch["sedmici"])))


def _pazach(a, r):
    """Предпазителят: без изрично `"saglasie": true` в регистъра — само с --vatreshno."""
    if a.vatreshno or config.ima_saglasie(r["kanal"]):
        return
    raise Otkaz("отказано: каналът „%s“ няма \"saglasie\": true в регистъра. Публикуване на степен за конкретен "
                "канал е решение след правен преглед. За вътрешна употреба добави --vatreshno." % r["kanal"]["id"])


def _pishi(path, tekst):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tekst)


def izpalni(a):
    """→ (код, обобщение за дневника)."""
    cfg = config.zaredi(a.config)
    if a.komanda == "metodika":
        _pishi(a.izhod, metodika.tekst(cfg))
        print("Методика: %s" % a.izhod)
        return IZHOD_OK, "методика · exit 0"

    r = izchisli(a, cfg)
    s = r["stepen"]
    if a.komanda == "izchisli":
        if a.ot is None:  # само редовното изчисление влиза в историята
            red = istoriya.zapishi(a.papka or cfg["papka_danni"], a.kanal, r["ch"], r["mashinna"],
                                   r["izchisleno"], cfg)
            if red:
                print("влошаване, записано в promeni.log: %s" % red, file=sys.stderr)
        if a.json:
            print(json.dumps({"kanal": r["kanal"]["id"], "stepen": s, "chisla": r["ch"],
                              "izchisleno": r["izchisleno"]}, ensure_ascii=False, indent=2))
        else:
            _pokazhi(r)
        return IZHOD_OK, "%s · записи %d · exit 0" % (s["kod"], r["ch"]["zapisi"])

    _pazach(a, r)
    if a.komanda == "otchet":
        _pishi(a.izhod, otchet.tekst(r, cfg, vatreshno=a.vatreshno))
        print("Отчет: %s (степен %s%s)" % (a.izhod, s["kod"], ", вътрешно" if a.vatreshno else ""))
    else:
        _pishi(a.izhod, znachka.svg(s, r["izchisleno"], vatreshno=a.vatreshno, podpis=a.podpis))
        print("Значка: %s (степен %s%s)" % (a.izhod, s["kod"], ", вътрешно" if a.vatreshno else ""))
    return IZHOD_OK, "%s %s · exit 0" % (a.komanda, s["kod"])


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        kod, obobshtenie = izpalni(a)
    except (Otkaz, config.GreshkaConfig, danni.GreshkaDanni) as e:
        print("iq: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_GRESHKA, "%s · exit 1" % type(e).__name__
    except OSError as e:
        print("iq: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_GRESHKA, "OSError · exit 1"
    dnevnik(kod == IZHOD_OK, obobshtenie)
    return kod
