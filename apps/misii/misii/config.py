"""Конфигурацията. Ред на търсене: изричен път → $MISII_CONFIG → config.json → config.example.json.

Районите, областите, полетата и въпросите живеят тук — всяка област е настройка, не отделен код.
Истинските райони и обекти са в частен config и частна база извън репото; в примера са само измислени.
"""
import json
import os

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBLASTI = ("kultura", "sport", "turizam", "obrazovanie", "sabitiya", "npo", "msp")
VIDOVE = ("raboti_li", "rabotno_vreme", "sastoyanie", "dostapnost", "snimka", "nov_obekt", "mestno_sabitie",
          "nuzhdi_npo", "lichen_prinos")


class GreshkaConfig(Exception):
    pass


def nameri(path=None):
    if path:
        return path
    if os.environ.get("MISII_CONFIG"):
        return os.environ["MISII_CONFIG"]
    lokalen = os.path.join(APP, "config.json")
    return lokalen if os.path.exists(lokalen) else os.path.join(APP, "config.example.json")


def zaredi(path=None):
    p = nameri(path)
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise GreshkaConfig("не мога да прочета конфигурацията %s: %s" % (p, e))
    for k in ("rayoni", "validna_dni", "srok_proverka_dni", "maks_misii_na_rayon", "podpis", "oblasti",
              "obshti_adresi"):
        if k not in cfg:
            raise GreshkaConfig("конфигурацията %s: липсва „%s“" % (p, k))
    for o, v in cfg["oblasti"].items():
        if o not in OBLASTI:
            raise GreshkaConfig("непозната област „%s“ (позволени: %s)" % (o, ", ".join(OBLASTI)))
        if not v.get("tipove"):
            raise GreshkaConfig("област %s: липсва „tipove“" % o)
        for pole, m in (v.get("poleta") or {}).items():
            if m.get("vid") not in VIDOVE:
                raise GreshkaConfig("област %s, поле %s: видът трябва да е един от %s" % (o, pole, ", ".join(VIDOVE)))
            if not m.get("vapros") or not m.get("poleta"):
                raise GreshkaConfig("област %s, поле %s: липсва „vapros“ или „poleta“" % (o, pole))
    cfg.setdefault("osm_atributsiya", "© участниците в OpenStreetMap, ODbL 1.0")
    return cfg
