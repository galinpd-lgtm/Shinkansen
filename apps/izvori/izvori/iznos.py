"""`iznesi --za filtar`: само одобрените, във формата на `apps/filtar/izvori.example.json` (Z8).

Полетата `eshelon` и `izvor_vid` са добавени отгоре; филтърът ги пренебрегва. Z8 не се променя.
"""
import urllib.parse

from . import registar as rg


def za_filtar(r, cfg):
    izhod = []
    for z in r["izvori"]:
        if z["sastoyanie"] != rg.ODOBREN:
            continue
        p = z.get("proverki") or {}
        em = p.get("emisiya") or {}
        if em.get("rezultat") == "да" and em.get("tip") in ("rss", "atom"):
            tip, url = em["tip"], em["url"]
        else:
            tip, url = "html", (p.get("zhiv") or {}).get("kraen_url") or z["url"]
        vid = cfg["vidove"].get(z["vid"], {})
        zap = {"id": z["id"], "ime": _ime(z, p), "vid": vid.get("filtar_vid", "neizvesten"), "tip": tip, "url": url}
        ezik = (p.get("ezik") or {}).get("ezik")
        if ezik:
            zap["ezik"] = ezik
        zap["eshelon"] = z.get("eshelon")
        zap["izvor_vid"] = z["vid"]
        izhod.append(zap)
    return izhod


def _ime(z, p):
    osnova = z.get("organizaciya") or urllib.parse.urlsplit(z["url"]).hostname
    vs = (p.get("vid_sadarzhanie") or {}).get("ime")
    return "%s — %s" % (osnova, vs) if vs else osnova
