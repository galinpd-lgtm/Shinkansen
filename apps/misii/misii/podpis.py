"""Подписване и проверка на списъка с мисии.

Прототип: HMAC-SHA256 само със стандартната библиотека. Подписва се каноничният JSON на целия списък без полето
`podpis` (подредени ключове, без интервали, UTF-8) — така всяка промяна в коя да е мисия чупи подписа.

ВНИМАНИЕ: HMAC е общ таен ключ. Който може да провери подписа, може и да подписва. За публичен помощник,
свален от хиляди хора, това не стига — там трябва подпис с двойка ключове (Ed25519): частният остава само на
нашата машина, публичният е вграден в помощника. Изборът и пазенето на ключа решава човекът (README).

Ключът никога не е в репото: идва от променлива на средата или от файл извън хранилището.
"""
import hashlib
import hmac
import json
import os

from .config import APP

ALGORITAM = "HMAC-SHA256"
MIN_KLYUCH = 32


class GreshkaPodpis(Exception):
    pass


def kanonichen(spisak):
    bez = {k: v for k, v in spisak.items() if k != "podpis"}
    return json.dumps(bez, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _v_repoto(pat):
    koren = os.path.dirname(os.path.dirname(APP))  # apps/misii → корена на хранилището
    pat = os.path.realpath(pat)
    return pat == koren or pat.startswith(os.path.realpath(koren) + os.sep)


def klyuch(cfg, fayl=None, sreda=None):
    """Ключът: от файл (извън репото) или от променливата в config (`podpis.klyuch_env`). → bytes."""
    sreda = os.environ if sreda is None else sreda
    if fayl:
        if _v_repoto(fayl):
            raise GreshkaPodpis("ключът е в хранилището (%s) — премести го извън него" % fayl)
        try:
            with open(fayl, "rb") as f:
                k = f.read().strip()
        except OSError as e:
            raise GreshkaPodpis("не мога да прочета ключа: %s" % e)
    else:
        ime = cfg["podpis"].get("klyuch_env", "MISII_KLYUCH")
        k = (sreda.get(ime) or "").strip().encode("utf-8")
        if not k:
            raise GreshkaPodpis("няма ключ: задай $%s или --klyuch-fayl (файл извън хранилището)" % ime)
    if len(k) < MIN_KLYUCH:
        raise GreshkaPodpis("ключът е под %d байта" % MIN_KLYUCH)
    return k


def podpishi(spisak, k, klyuch_id):
    s = dict(spisak)
    s.pop("podpis", None)
    s["podpis"] = {"algoritam": ALGORITAM, "klyuch_id": klyuch_id,
                   "stoynost": hmac.new(k, kanonichen(s), hashlib.sha256).hexdigest()}
    return s


def proveri(spisak, k, klyuch_id=None):
    """Подписът верен ли е. Невярен, липсващ или с друг алгоритъм/ключ → GreshkaPodpis. Нищо не се „поправя“."""
    p = spisak.get("podpis") if isinstance(spisak, dict) else None
    if not isinstance(p, dict) or not p.get("stoynost"):
        raise GreshkaPodpis("списъкът не е подписан")
    if p.get("algoritam") != ALGORITAM:
        raise GreshkaPodpis("непознат алгоритъм „%s“" % p.get("algoritam"))
    if klyuch_id and p.get("klyuch_id") != klyuch_id:
        raise GreshkaPodpis("подписан с друг ключ („%s“, очакван „%s“)" % (p.get("klyuch_id"), klyuch_id))
    ochakvan = hmac.new(k, kanonichen(spisak), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(ochakvan, str(p["stoynost"])):
        raise GreshkaPodpis("подписът не съвпада — списъкът е променен или подписан с друг ключ")
    return True
