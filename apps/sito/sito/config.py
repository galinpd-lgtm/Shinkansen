"""Конфигурацията. Ред на търсене: изричен път → $SITO_CONFIG → config.json → config.example.json.

Обхватът (кои разширения се четат, кои са чист текст, архив или извън обхвата), присъдите, думите за
доказателство, правилата за „жив“ файл, таваните и ролите живеят тук — в кода няма списъци.
"""
import json
import os
import re

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRISADI = ("opakovka", "dokazatelstvo", "zhiv", "tekst", "dublikat", "neyasno",
           "izvan_obhvat", "chist_tekst", "arhiv")
SAMO_UVEDOMYAVAT = ("izvan_obhvat", "chist_tekst", "arhiv")  # без решение, без преглед, без --go
CHETIMI = ("html", "docx", "doc", "rtf", "pdf", "pptx")  # видовете, за които двигателят има конвертор


class GreshkaConfig(Exception):
    pass


def nameri(path=None):
    if path:
        return path
    if os.environ.get("SITO_CONFIG"):
        return os.environ["SITO_CONFIG"]
    lokalen = os.path.join(APP, "config.json")
    return lokalen if os.path.exists(lokalen) else os.path.join(APP, "config.example.json")


def zaredi(path=None):
    p = nameri(path)
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise GreshkaConfig("не мога да прочета конфигурацията %s: %s" % (p, e))
    for k in ("roli_reshavashti", "maks_razmer_bytes", "maks_vreme_s", "vidove", "chist_tekst", "arhiv",
              "izvan_obhvat", "opakovka", "dokazatelstvo", "zhiv", "html", "predlozheniya", "belezhki"):
        if k not in cfg:
            raise GreshkaConfig("конфигурацията %s: липсва „%s“" % (p, k))
    if not cfg["roli_reshavashti"]:
        raise GreshkaConfig("roli_reshavashti: нужна е поне една роля")
    for pr in PRISADI:  # само уведомяващите нямат предложение за действие — имат бележка
        kade = "belezhki" if pr in SAMO_UVEDOMYAVAT else "predlozheniya"
        if pr not in cfg[kade]:
            raise GreshkaConfig("%s: липсва „%s“" % (kade, pr))
    if "kandidat_pdf" not in cfg["belezhki"]:
        raise GreshkaConfig("belezhki: липсва „kandidat_pdf“")
    for vid in cfg["vidove"]:
        if vid not in CHETIMI:
            raise GreshkaConfig("vidove: „%s“ — двигателят чете само %s" % (vid, ", ".join(CHETIMI)))

    # разширение → (категория, вид). Категорията е „chete“ или една от присъдите, които само уведомяват.
    karta = {}

    def dobavi(razshireniya, kategoriya, vid, kade):
        for r in razshireniya:
            r = r.lower()
            if r in karta:
                raise GreshkaConfig("разширението %s е и в %s, и в %s" % (r, karta[r][2], kade))
            karta[r] = (kategoriya, vid, kade)

    for vid, razshireniya in cfg["vidove"].items():
        dobavi(razshireniya, "chete", vid, "vidove." + vid)
    dobavi(cfg["chist_tekst"], "chist_tekst", "tekst", "chist_tekst")
    dobavi(cfg["arhiv"], "arhiv", "arhiv", "arhiv")
    for vid, razshireniya in cfg["izvan_obhvat"].items():
        dobavi(razshireniya, "izvan_obhvat", vid, "izvan_obhvat." + vid)
    cfg["_razshireniya"] = karta

    try:
        cfg["_regeksi"] = [(r["ime"], re.compile(r["re"])) for r in cfg["dokazatelstvo"].get("regeksi", [])]
    except (KeyError, re.error) as e:
        raise GreshkaConfig("dokazatelstvo.regeksi: %s" % e)
    cfg["_dumi"] = [(d, re.compile(r"(?<!\w)" + re.escape(d), re.I)) for d in cfg["dokazatelstvo"].get("dumi", [])]
    cfg["dokazatelstvo"].setdefault("vidove", ["pdf", "docx", "doc", "rtf"])
    cfg.setdefault("maks_dalbochina", 64)
    cfg.setdefault("blok_bytes", 1 << 20)
    cfg.setdefault("chunk_dumi", 800)
    cfg.setdefault("otkas_znaci", 2000)
    cfg.setdefault("propuskay", [])
    cfg.setdefault("propuskay_papki", [])
    cfg.setdefault("ocr", {})
    cfg["ocr"].setdefault("ezici", "bul+eng")
    cfg["ocr"].setdefault("dpi", 200)
    cfg["ocr"].setdefault("prag_znaci_na_stranica", 25)
    cfg["ocr"].setdefault("pri_skanirane", False)
    cfg["_pat"] = p
    return cfg


def vid_po_ime(cfg, ime):
    """(категория, вид). Непознато разширение е извън обхвата с вид „?“."""
    r = cfg["_razshireniya"].get(os.path.splitext(ime)[1].lower())
    return (r[0], r[1]) if r else ("izvan_obhvat", "?")
