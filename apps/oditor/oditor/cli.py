"""python -m oditor proveri | proveri-spisak | otchet | povtorno

Кодове на изход:
  0 готово (и когато сайтът е отказал или е блокирал — това е находка, не грешка на програмата)
  1 грешка: непознат id, неразбираем config или запис, сайт в списъка с изключени
  2 грешна употреба
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone

from . import VERSIYA, baza, config, izpit, obhod, otchet, politika, pravilnik, razbor
from .model import Model
from .mrezha import Mrezha

IZHOD_OK, IZHOD_GRESHKA, IZHOD_UPOTREBA = 0, 1, 2


class Upotreba(Exception):
    pass


class Greshka(Exception):
    pass


def dnevnik(ok, obobshtenie):
    """Ред в $SHINKANSEN_RUNS/oditor.jsonl — само броеве и код, без адреси."""
    sf = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if sf:
        with open(sf, "w", encoding="utf-8") as f:
            f.write(obobshtenie)
        return
    runs = os.environ.get("SHINKANSEN_RUNS")
    if not runs:
        return
    os.makedirs(runs, exist_ok=True)
    zap = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "helper": "oditor",
           "ok": bool(ok), "summary": obobshtenie[:200]}
    with open(os.path.join(runs, "oditor.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(zap, ensure_ascii=False) + "\n")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        raise Upotreba(message)


def parser():
    p = _Parser(prog="python -m oditor", description="Одиторът: технически тест на публичен сайт (rulebook %s)."
                % pravilnik.RULEBOOK)
    obshti = _Parser(add_help=False)
    obshti.add_argument("--config", help="път до config.json")
    obshti.add_argument("--rezultati", help="папката на частната база (по подразбиране rezultati/)")
    obshti.add_argument("--sega", help=argparse.SUPPRESS)  # за тестовете: час по UTC, ISO
    proverka = _Parser(add_help=False)
    proverka.add_argument("--politika", action="store_true", help="чете и политиката за поверителност (+1 заявка, модел)")
    proverka.add_argument("--izpit", action="store_true", help="агентски изпит с модела (без нови заявки)")
    proverka.add_argument("--brauzar", action="store_true", help="пуска браузъра и без повод (за бутона за отказ)")
    sub = p.add_subparsers(dest="komanda", required=True, parser_class=_Parser)
    s = sub.add_parser("proveri", parents=[obshti, proverka], help="проверка на един сайт")
    s.add_argument("url")
    s = sub.add_parser("proveri-spisak", parents=[obshti, proverka], help="проверка на списък (по адрес на ред)")
    s.add_argument("fayl")
    s = sub.add_parser("otchet", parents=[obshti], help="отчет за проверка")
    s.add_argument("id")
    s.add_argument("--format", choices=("md", "json"), default="md")
    s.add_argument("--izhod", help="файл (иначе на екрана)")
    s = sub.add_parser("povtorno", parents=[obshti, proverka], help="повторна проверка и разлика „преди/след“")
    s.add_argument("id")
    return p


def _sega(a):
    if a.sega:
        return datetime.fromisoformat(a.sega.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _t(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _url(u):
    u = (u or "").strip()
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        p = None
    if not p or p.scheme not in ("http", "https") or not p.hostname:
        raise Upotreba("адресът трябва да е http(s)://… („%s“)" % u)
    return u


class Sreda:
    """Всичко подменяемо — за тестовете."""

    def __init__(self, mrezha=None, model=None, brauzar=None, spi=time.sleep):
        self.mrezha, self.model, self.brauzar, self.spi = mrezha, model, brauzar, spi


def _proveri_edin(url, a, cfg, papka, sega, sreda, predishen=None):
    m = sreda.mrezha(cfg) if sreda.mrezha else Mrezha(cfg)
    sn = obhod.snimai(cfg, url, m, brauzar_fabrika=sreda.brauzar, nalozhi_brauzar=a.brauzar)
    rez = pravilnik.oceni(sn)
    zapis = {"id": baza.nov_id(papka, sega.date().isoformat(), urllib.parse.urlsplit(url).hostname),
             "url": url, "t": _t(sega), "versiya": VERSIYA, "rulebook": pravilnik.RULEBOOK,
             "znamena": {"politika": a.politika, "izpit": a.izpit, "brauzar": a.brauzar}}
    if predishen:
        zapis["predishen"] = predishen
    mdl = sreda.model(cfg) if sreda.model else Model(cfg.get("model"))
    kraen = sn["glavna"][-1]
    if a.politika:
        sig = next((s for s in rez["pravni_signali"] if s["kod"] == "politika_poveritelnost"), None)
        if sig and sig["sastoyanie"] == pravilnik.IMA and sig.get("href"):
            pu = urllib.parse.urljoin(sig["dokazatelstvo"][0]["url"], sig["href"])
            r = getattr(m, "robots", None) or obhod.Robots(m, cfg["user_agent_ime"])
            if r.pozvoleno(pu):
                sn["politika"] = m.vzemi(pu)
                zapis["politika"] = politika.prochiti(mdl, sn["politika"])
            else:
                zapis["politika"] = {"sastoyanie": pravilnik.NEPR, "prichina": "robots.txt не пуска към политиката"}
            sn["broy_zayavki"] = rez["zayavki"] = m.broy
        else:
            zapis["politika"] = {"sastoyanie": pravilnik.NEPR,
                                 "prichina": "не е намерена връзка към политика на началната страница"}
    if a.izpit:
        tekst = "\n".join(razbor.razberi(kraen.get("tyalo"))["redove"]) if kraen.get("status") == 200 else ""
        zapis["izpit"] = izpit.izpitai(mdl, kraen, tekst)
    zapis["rezultat"], zapis["snimka"] = rez, sn
    pat = baza.zapishi(papka, zapis)
    print("%s: %d от %d · %s" % (zapis["id"], rez["tochki"], rez["ot"],
                                 " · ".join("%s %s" % (s["ime"], s["sastoyanie"]) for s in rez["stalbove"])))
    if zapis.get("izpit"):
        iz = zapis["izpit"]
        print("    изпит: %s" % ("%d от %d" % (iz["tochki"], iz["ot"]) if iz["sastoyanie"] == pravilnik.IMA
                                 else "непроверено — " + iz["prichina"]))
    if zapis.get("politika"):
        p = zapis["politika"]
        print("    политика: %s" % ("%d от %d потвърдени цитата" % (p["potvardeni"], p["ot"])
                                    if p["sastoyanie"] == pravilnik.IMA else "непроверено — " + p["prichina"]))
    if rez.get("brauzar") and not rez["brauzar"].get("izpolzvan"):
        print("    браузър: непроверено — %s" % rez["brauzar"].get("zashto"))
    print("    запис: %s" % pat)
    return zapis


def izpalni(a, sreda):
    cfg = config.zaredi(a.config)
    papka = a.rezultati or cfg["papka_rezultati"]
    if not os.path.isabs(papka) and not a.rezultati:
        papka = os.path.join(config.APP, papka)
    sega = _sega(a)
    if a.komanda == "otchet":
        z = baza.zaredi(papka, a.id)
        tekst = otchet.md(z) if a.format == "md" else otchet.json_(z)
        if a.izhod:
            with open(a.izhod, "w", encoding="utf-8") as f:
                f.write(tekst)
            print("Отчет: %s" % a.izhod)
        else:
            sys.stdout.write(tekst)
        return "otchet %s" % a.format
    if a.komanda == "proveri":
        try:
            z = _proveri_edin(_url(a.url), a, cfg, papka, sega, sreda)
        except obhod.Izklyuchen as e:
            raise Greshka(str(e))
        return "proveri %d/%d" % (z["rezultat"]["tochki"], z["rezultat"]["ot"])
    if a.komanda == "povtorno":
        predi = baza.zaredi(papka, a.id)
        for k, v in (predi.get("znamena") or {}).items():
            if v:
                setattr(a, k, True)
        try:
            sled = _proveri_edin(predi["url"], a, cfg, papka, sega, sreda, predishen=predi["id"])
        except obhod.Izklyuchen as e:
            raise Greshka(str(e))
        print("Преди/след (%s → %s):" % (predi["id"], sled["id"]))
        for r in otchet.razlika(predi, sled):
            print("    " + r)
        return "povtorno %d→%d" % (predi["rezultat"]["tochki"], sled["rezultat"]["tochki"])
    # proveri-spisak
    try:
        with open(a.fayl, encoding="utf-8") as f:
            adresi = [r.strip() for r in f if r.strip() and not r.strip().startswith("#")]
    except OSError as e:
        raise Greshka("не мога да прочета списъка: %s" % e)
    adresi = [_url(u) for u in adresi]
    gotovi, propusnati = 0, 0
    for i, u in enumerate(adresi):
        if i:
            sreda.spi(float(cfg["pauza_mezhdu_saytove_s"]))
        try:
            _proveri_edin(u, a, cfg, papka, sega, sreda)
            gotovi += 1
        except obhod.Izklyuchen as e:
            print("%s: пропуснат — %s" % (u, e))
            propusnati += 1
    print("Готови %d от %d (пропуснати %d)" % (gotovi, len(adresi), propusnati))
    return "proveri-spisak %d/%d" % (gotovi, len(adresi))


def main(argv=None, sreda=None):
    sreda = sreda or Sreda()
    try:
        a = parser().parse_args(argv)
        obobshtenie = izpalni(a, sreda)
        kod = IZHOD_OK
    except Upotreba as e:
        print("oditor: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_UPOTREBA, "употреба"
    except (Greshka, config.GreshkaConfig, baza.GreshkaBaza) as e:
        print("oditor: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_GRESHKA, type(e).__name__
    except OSError as e:
        print("oditor: %s" % e, file=sys.stderr)
        kod, obobshtenie = IZHOD_GRESHKA, "OSError"
    dnevnik(kod == IZHOD_OK, "%s · exit %d" % (obobshtenie, kod))
    return kod
