"""Конфигурацията и регистърът на каналите. Ред на търсене: изричен път → $IQ_CONFIG → config.json →
config.example.json.

Относителните пътища в нея (filtar_danni, kanali, papka_danni) са спрямо текущата папка, както във филтъра.
Регистърът се само чете: „спряна“ се пише в него на ръка от човек, с писмено основание — кодът никога.
"""
import json
import os

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class GreshkaConfig(Exception):
    pass


def nameri(path=None):
    if path:
        return path
    if os.environ.get("IQ_CONFIG"):
        return os.environ["IQ_CONFIG"]
    lokalen = os.path.join(APP, "config.json")
    return lokalen if os.path.exists(lokalen) else os.path.join(APP, "config.example.json")


def zaredi(path=None):
    p = nameri(path)
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise GreshkaConfig("не мога да прочета конфигурацията %s: %s" % (p, e))
    for k in ("filtar_danni", "kanali", "papka_danni", "prozorec_dni", "imenuvani_prag", "uverenost_dostatachna", "stepeni", "bez_stepen",
              "spryana", "otchet"):
        if k not in cfg:
            raise GreshkaConfig("конфигурацията %s: липсва „%s“" % (p, k))
    predishen = None
    for s in cfg["stepeni"]:
        for k in ("kod", "ot", "cvyat", "cvyat_ime"):
            if k not in s:
                raise GreshkaConfig("степен %s: липсва „%s“" % (s.get("kod", "?"), k))
        if predishen is not None and s["ot"] >= predishen:
            raise GreshkaConfig("степените трябва да са подредени от най-високата надолу")
        predishen = s["ot"]
    return cfg


def _pat(path):
    return path if os.path.isabs(path) or os.path.exists(path) else os.path.join(APP, path)


def kanali(cfg, path=None):
    """Регистърът → {id: запис}. Липсващ файл е празен регистър (тогава нищо няма съгласие)."""
    p = path or cfg.get("kanali")
    if not p:
        return {}
    try:
        with open(_pat(p), encoding="utf-8") as f:
            spisak = json.load(f)
    except OSError:
        return {}
    except ValueError as e:
        raise GreshkaConfig("неразбираем JSON в %s: %s" % (p, e))
    if not isinstance(spisak, list):
        raise GreshkaConfig("регистърът на каналите трябва да е списък")
    rez = {}
    for i, k in enumerate(spisak):
        for pole in ("id", "ime"):
            if not k.get(pole):
                raise GreshkaConfig("канал %d: липсва „%s“" % (i, pole))
        if k["id"] in rez:
            raise GreshkaConfig("повторен канал: %s" % k["id"])
        sp = k.get("spryana")
        if sp is not None:
            for pole in ("osnovanie", "rolya", "data"):
                if not (isinstance(sp, dict) and str(sp.get(pole, "")).strip()):
                    raise GreshkaConfig("канал %s: „spryana“ иска писмено основание, роля и дата (липсва „%s“)"
                                        % (k["id"], pole))
        rez[k["id"]] = k
    return rez


def ima_saglasie(kanal):
    """Само изричното `"saglasie": true` е съгласие — не „да“, не 1, не липса."""
    return bool(kanal) and kanal.get("saglasie") is True
