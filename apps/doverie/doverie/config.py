"""Зареждане на конфигурацията. Теглата, праговете и моделите живеят само в JSON, не в кода.

Ред на търсене: изричен път → $DOVERIE_CONFIG → apps/doverie/config.json → apps/doverie/config.example.json.
"""
import json
import os

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OSI_KLUCHOVE = ("reputaciya", "proverimost", "prozrachnost", "originalnost",
                "obshtestven_interes", "manipulaciya", "palnota")


class GreshkaConfig(Exception):
    pass


def nameri(path=None):
    if path:
        return path
    env = os.environ.get("DOVERIE_CONFIG")
    if env:
        return env
    lokalen = os.path.join(APP, "config.json")
    if os.path.exists(lokalen):
        return lokalen
    return os.path.join(APP, "config.example.json")


def zaredi(path=None):
    p = nameri(path)
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise GreshkaConfig("не мога да прочета конфигурацията %s: %s" % (p, e))
    greshki = proveri(cfg)
    if greshki:
        raise GreshkaConfig("конфигурацията %s: %s" % (p, "; ".join(greshki)))
    return cfg


def proveri(cfg):
    greshki = []
    tegla = cfg.get("tegla")
    if not isinstance(tegla, dict):
        return ["няма „tegla“"]
    for k in OSI_KLUCHOVE:
        if not isinstance(tegla.get(k), (int, float)):
            greshki.append("липсва тегло за „%s“" % k)
    if not greshki and abs(sum(tegla[k] for k in OSI_KLUCHOVE) - 1.0) > 0.001:
        greshki.append("теглата не дават сума 1.0")
    for k in ("po_dumi", "reshenie", "originalnost"):
        if k not in cfg:
            greshki.append("липсва „%s“" % k)
    if "11434" in str(cfg.get("ollama_url", "")):
        greshki.append("ollama_url сочи :11434 (продукционния Ollama) — ползвай тестовия :11435")
    return greshki
