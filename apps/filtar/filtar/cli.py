"""python -m filtar sabiray | filtriray | chernova | odobri | izdanie | statistika

Кодове на изход:
  0 готово (sabiray: събран е поне един източник; неотговорилите са в предупреждение и в дневника)
  4 само „заето/горещо, опитай по-късно“: вратата на Z7 спря filtriray/chernova — моделът не е викан,
    нищо не се губи, следващото пускане продължава оттам
  1 грешка (sabiray: не е отговорил нито един източник) · 2 грешна употреба
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone

from . import baza, config
from . import izdanie as izd
from . import sabirach, sloeve, statistika
from .dov import GreshkaModel, Model, VrataNeBezopasno, zaredi_doverie
from .vreden import Klasifikator

IZHOD_OK, IZHOD_GRESHKA, IZHOD_4 = 0, 1, 4


def dnevnik(ok, obobshtenie):
    """Ред в $SHINKANSEN_RUNS/filtar.jsonl — само броеве и кодове, нищо от текстовете."""
    sf = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if sf:
        with open(sf, "w", encoding="utf-8") as f:
            f.write(obobshtenie)
        return
    runs = os.environ.get("SHINKANSEN_RUNS")
    if not runs:
        return
    os.makedirs(runs, exist_ok=True)
    zap = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "helper": "filtar",
           "ok": bool(ok), "summary": obobshtenie[:200]}
    with open(os.path.join(runs, "filtar.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(zap, ensure_ascii=False) + "\n")


def _den(s):
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError("датата е ГГГГ-ММ-ДД")


def _nomera(s):
    try:
        return sorted({int(x) for x in s.split(",") if x.strip()})
    except ValueError:
        raise argparse.ArgumentTypeError("--mahni очаква номера, напр. 3,7")


def parser():
    p = argparse.ArgumentParser(prog="python -m filtar", description="Информационният филтър и радарът.")
    obshti = argparse.ArgumentParser(add_help=False)
    obshti.add_argument("--config", help="път до config.json")
    obshti.add_argument("--danni", help="папката с базата и черновите (замества papka_danni)")
    obshti.add_argument("--sega", help=argparse.SUPPRESS)  # за тестовете: „сега“ в ISO
    sub = p.add_subparsers(dest="komanda", required=True)
    s = sub.add_parser("sabiray", parents=[obshti], help="събира от източниците и от vhod/")
    s.add_argument("--izvori", help="регистърът на източниците (замества config)")
    s.add_argument("--vhod", help="папката с ръчните JSON файлове (замества config)")
    f = sub.add_parser("filtriray", parents=[obshti], help="7-те слоя върху несортираното")
    f.add_argument("--bez-model", action="store_true", help="Z7 без модел; класификаторът не се вика")
    c = sub.add_parser("chernova", parents=[obshti], help="до 10 записа → chernova_<дата>.json и .md")
    c.add_argument("--data", required=True, type=_den)
    c.add_argument("--bez-model", action="store_true", help="без текстовете „какво се случи“ и „какво значи“")
    o = sub.add_parser("odobri", parents=[obshti], help="без --go само показва; с --go пише odobreno_<дата>.json")
    o.add_argument("--data", required=True, type=_den)
    o.add_argument("--mahni", type=_nomera, default=[], help="номера от черновата, напр. 3,7")
    o.add_argument("--go", action="store_true", help="наистина пиши")
    i = sub.add_parser("izdanie", parents=[obshti], help="radar.json, rss.xml, po-den/ от одобреното")
    i.add_argument("--izhod", required=True)
    i.add_argument("--dnes", type=_den, help="краят на 30-дневния прозорец (по подразбиране днес)")
    t = sub.add_parser("statistika", parents=[obshti], help="решения по слой и по източник")
    t.add_argument("--json", action="store_true")
    return p


def _sega(a):
    if a.sega:
        d = datetime.fromisoformat(a.sega)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _model(cfg, bez_model):
    if bez_model:
        return None, None
    dcfg = zaredi_doverie(cfg.get("doverie_config"))
    kl = Klasifikator(cfg["sloy3"].get("vreden", {}), dcfg.get("gate_url"))
    return Model(dcfg), (kl if kl.vklyuchen else None)


def izpalni(a):
    """→ (код, обобщение за дневника)."""
    cfg = config.zaredi(a.config)
    papka = a.danni or cfg["papka_danni"]
    sega = _sega(a)
    b = baza.otvori(papka)
    try:
        if a.komanda == "sabiray":
            izvori = config.izvori(cfg, a.izvori)
            o = sabirach.sabiray(b, cfg, izvori, sega, vhod=a.vhod or cfg.get("vhod"))
            for iid, sast in o["izvori"]:
                print("%-28s %s" % (iid, sast))
            for g in o["greshki"]:
                if g.startswith("vhod/"):
                    print("vhod: %s" % g[5:], file=sys.stderr)
            print("Нови записи: %d · пропуснати (рано е): %d · с грешка: %d" % (
                o["novi"], o["propusnati"], len(o["greshki"])))
            opitani = len(o["izvori"])
            greshni = [iid for iid, s in o["izvori"] if s.startswith("грешка")]
            kod = IZHOD_GRESHKA if opitani and len(greshni) == opitani else IZHOD_OK
            if greshni:
                print("предупреждение: не отговориха %d от %d източника: %s" % (len(greshni), opitani, ", ".join(greshni)),
                      file=sys.stderr)
            return kod, "нови %d · не отговориха %d · exit %d" % (o["novi"], len(greshni), kod)

        if a.komanda == "filtriray":
            model, kl = _model(cfg, a.bez_model)
            orgs = config.cheti_json(cfg.get("organizacii"), [])
            dcfg = zaredi_doverie(cfg.get("doverie_config"))
            o = sloeve.filtriray(b, cfg, dcfg, sega, model=model, klasifikator=kl, organizacii=orgs)
            obsh = ", ".join("%s %d" % (k, v) for k, v in sorted(o.items())) or "няма нови"
            print("Обработени: %s" % obsh)
            return IZHOD_OK, "%s · exit 0" % obsh

        if a.komanda == "chernova":
            model, _ = _model(cfg, a.bez_model)
            d, pj = izd.chernova(b, cfg, a.data, papka, sega, model=model)
            print("Чернова: %s (%d записа%s)" % (pj, len(d["zapisi"]), "" if d["s_model"] else ", без текстове"))
            return IZHOD_OK, "чернова %d записа · exit 0" % len(d["zapisi"])

        if a.komanda == "odobri":
            ostavat, mahnati, izh = izd.odobri(b, papka, a.data, a.mahni, a.go, sega)
            for z in ostavat:
                print("  ✓ %d. %s" % (z["nomer"], z["zaglavie"]))
            for z in mahnati:
                print("  ✗ %d. %s" % (z["nomer"], z["zaglavie"]))
            if izh:
                print("Одобрено: %s (%d записа)" % (izh, len(ostavat)))
            else:
                print("Нищо не е записано. За одобряване добави --go.")
            return IZHOD_OK, "%s %d · exit 0" % ("одобрени" if izh else "преглед", len(ostavat))

        if a.komanda == "izdanie":
            o = izd.izdanie(cfg, papka, a.izhod, a.dnes or sega.date())
            print("Издание в %s: %d дни, %d записа (radar.json, rss.xml, po-den/)" % (a.izhod, o["dni"], o["zapisi"]))
            return IZHOD_OK, "издание %d дни · exit 0" % o["dni"]

        if a.komanda == "statistika":
            s = statistika.statistika(b, sega, cfg.get("ne_otgovarya_sled_dni", 3))
            print(json.dumps(s, ensure_ascii=False, indent=2) if a.json else statistika.otchet(s))
            return IZHOD_OK, "статистика · exit 0"
    finally:
        b.rollback()
        b.close()
    return IZHOD_GRESHKA, "непозната команда"


def main(argv=None):
    a = parser().parse_args(argv)
    t0 = time.monotonic()
    try:
        kod, obsh = izpalni(a)
    except VrataNeBezopasno as e:
        print("не е безопасно сега: %s. Моделът не е викан; следващото пускане продължава." % e, file=sys.stderr)
        dnevnik(True, "%s · вратата · exit 4" % a.komanda)
        return IZHOD_4
    except (config.GreshkaConfig, izd.GreshkaIzdanie, GreshkaModel, OSError, ValueError) as e:
        print("грешка: %s" % e, file=sys.stderr)
        dnevnik(False, "%s · грешка · exit 1" % a.komanda)
        return IZHOD_GRESHKA
    dnevnik(kod != IZHOD_GRESHKA, "%s · %s · %.1fs" % (a.komanda, obsh, time.monotonic() - t0))
    return kod
