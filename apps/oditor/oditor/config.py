"""Конфигурацията. Ред на търсене: изричен път → $ODITOR_CONFIG → config.json → config.example.json.

Тук е само работното: UA, паузи, папка за резултатите, изключени сайтове, досиета, моделите.
Правилата за оценка НЕ са тук — те са код в `pravilnik.py` с версия, за да е еднаква оценката при еднакъв вход.
Истинските списъци и досиета са в частен config извън репото; в примера са само example-домейни.
"""
import json
import os

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLI = ("rabotnik", "pazach", "visok_risk")


class GreshkaConfig(Exception):
    pass


def nameri(path=None):
    if path:
        return path
    if os.environ.get("ODITOR_CONFIG"):
        return os.environ["ODITOR_CONFIG"]
    lokalen = os.path.join(APP, "config.json")
    return lokalen if os.path.exists(lokalen) else os.path.join(APP, "config.example.json")


def zaredi(path=None):
    p = nameri(path)
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise GreshkaConfig("не мога да прочета конфигурацията %s: %s" % (p, e))
    for k in ("user_agent_ime", "kontakt", "taymaut_s", "pauza_na_hosta_s", "pauza_mezhdu_saytove_s",
              "maks_prenasochvaniya", "maks_tyalo_bytes"):
        if k not in cfg:
            raise GreshkaConfig("конфигурацията %s: липсва „%s“" % (p, k))
    if not str(cfg["kontakt"]).startswith("https://"):
        raise GreshkaConfig("kontakt трябва да е https:// адрес — влиза в User-Agent")
    m = cfg.get("model") or {}
    for r in ROLI:
        if r in m and not (m[r] or {}).get("ime"):
            raise GreshkaConfig("model.%s: липсва „ime“" % r)
    cfg.setdefault("papka_rezultati", "rezultati")
    cfg.setdefault("proba_s_ai_ua", False)
    cfg.setdefault("brauzar", {"vklyuchen": True, "taymaut_s": 30})
    cfg.setdefault("izklyucheni", [])
    cfg.setdefault("dosieta", {})
    cfg.setdefault("model", {})
    return cfg


def na_domeyn(host, domeyn):
    host, domeyn = (host or "").lower().rstrip("."), domeyn.lower().rstrip(".")
    return host == domeyn or host.endswith("." + domeyn)


def izklyuchen(cfg, host):
    return any(na_domeyn(host, d) for d in cfg["izklyucheni"])


def dosie(cfg, host):
    """Досието от регистъра за този хост (адрес, телефон) — или None. Живее само в частния config."""
    for d, v in cfg["dosieta"].items():
        if na_domeyn(host, d):
            return v
    return None
