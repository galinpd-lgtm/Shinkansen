"""Конфигурацията. Ред на търсене: изричен път → $SITO_CONFIG → config.json → config.example.json.

Присъдите, думите за доказателство, правилата за „жив“ файл, таваните и ролите живеят тук — в кода няма списъци.
"""
import json
import os
import re

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRISADI = ("opakovka", "dokazatelstvo", "zhiv", "tekst", "dublikat", "neyasno", "kontejner")
KONTEJNERI = ("zip",)


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
    for k in ("roli_reshavashti", "maks_razmer_bytes", "maks_vreme_s", "vidove", "opakovka", "dokazatelstvo",
              "zhiv", "html", "predlozheniya"):
        if k not in cfg:
            raise GreshkaConfig("конфигурацията %s: липсва „%s“" % (p, k))
    if not cfg["roli_reshavashti"]:
        raise GreshkaConfig("roli_reshavashti: нужна е поне една роля")
    for pr in PRISADI:
        if pr not in cfg["predlozheniya"]:
            raise GreshkaConfig("predlozheniya: липсва „%s“" % pr)
    vidimi = {}
    for vid, razshireniya in cfg["vidove"].items():
        for r in razshireniya:
            if r.lower() in vidimi:
                raise GreshkaConfig("разширението %s е и в %s, и в %s" % (r, vidimi[r.lower()], vid))
            vidimi[r.lower()] = vid
    try:
        cfg["_regeksi"] = [(r["ime"], re.compile(r["re"])) for r in cfg["dokazatelstvo"].get("regeksi", [])]
    except (KeyError, re.error) as e:
        raise GreshkaConfig("dokazatelstvo.regeksi: %s" % e)
    cfg["_razshireniya"] = vidimi
    cfg["_dumi"] = [(d, re.compile(r"(?<!\w)" + re.escape(d), re.I)) for d in cfg["dokazatelstvo"].get("dumi", [])]
    cfg.setdefault("maks_dalbochina", 3)
    cfg.setdefault("blok_bytes", 1 << 20)
    cfg.setdefault("chunk_dumi", 800)
    cfg.setdefault("propuskay", [])
    cfg.setdefault("ocr", {})
    cfg["ocr"].setdefault("ezici", "bul+eng")
    cfg["ocr"].setdefault("dpi", 200)
    cfg["ocr"].setdefault("prag_znaci_na_stranica", 25)
    cfg["ocr"].setdefault("pri_skanirane", False)
    cfg.setdefault("pptx_pdf_izgled", True)
    cfg.setdefault("whisper", {"komanda": "whisper", "model": "medium", "ezik": "bg"})
    cfg["_pat"] = p
    return cfg


def vid_po_ime(cfg, ime):
    return cfg["_razshireniya"].get(os.path.splitext(ime)[1].lower())
