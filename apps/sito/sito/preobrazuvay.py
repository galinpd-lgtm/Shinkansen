"""preobrazuvay: само файл с решение „да“ И преглед (vidyan) със същия SHA-256 → <id>.md + chunks.jsonl.

Без --go само показва плана и не пише нищо. Двигателят не пише в база: зареждането е частна стъпка (адаптер).
Преди да се пише, хешът се сверява: променен след прегледа файл е невидян и спира. Смени ли се присъдата при
OCR (напр. стане доказателство), файлът спира и чака нов преглед — нищо от него не се записва.
"""
import json
import os
import shutil
import tempfile
import time

from . import config as cf
from . import konvertori, prisadi, tekst
from .instrumenti import Neyasno
from .skaner import hash_i_baytove

NEPREOBRAZUVAEMI = ("dublikat", "neyasno") + cf.SAMO_UVEDOMYAVAT


class Spryan(Exception):
    """Файлът спира и чака нов преглед от човек."""


def viden(z):
    v = z.get("vidyan")
    return bool(v) and v.get("sha256") == z["sha256"]


def razdeli(karta):
    """(за преобразуване, пропуснати с причина)."""
    da, ne = [], []
    for z in karta["faylove"]:
        r = z.get("reshenie")
        if z["prisada"] in NEPREOBRAZUVAEMI:
            ne.append((z, "%s — нищо не се прави" % z["prisada"]))
        elif not r:
            ne.append((z, "без решение"))
        elif not r["da"]:
            ne.append((z, "решено „не“"))
        elif z.get("problem"):
            ne.append((z, "MD не може: %s" % z["problem"]))
        elif not viden(z):
            ne.append((z, "невидян — чака преглед (vidyah)"))
        else:
            da.append(z)
    return da, ne


def plan(karta, izhod, cfg):
    da, ne = razdeli(karta)
    print("План (нищо не е записано; за запис — --go):")
    print("  изход: %s" % izhod)
    for z in da:
        print("  ✓ %s  %s → %s.md  (%s, видян от %s, очаквано %s)" % (
            z["id"], z["put"], z["id"], z["prisada"], z["vidyan"]["rolya"],
            prisadi.chovesko(z.get("ochakvan_md_bytes"))))
    for z, prichina in ne:
        if prichina.startswith("невидян"):
            print("  ✗ %s  %s — %s" % (z["id"], z["put"], prichina))
    broy = {}
    for _, prichina in ne:
        k = prichina.split(" — ")[0].split(":")[0]
        broy[k] = broy.get(k, 0) + 1
    print("  за преобразуване: %d · пропуснати: %d%s" % (
        len(da), len(ne), (" (" + ", ".join("%s %d" % kv for kv in sorted(broy.items())) + ")") if ne else ""))
    return da


def _preobrazuvay_edin(z, pat, izhod, cfg, t, chf):
    """Един файл → <id>.md и парчетата му. Парчетата отиват в chunks само ако файлът мине докрай."""
    sha, bayt = hash_i_baytove(pat, z["vid"], cfg)
    if sha != z["sha256"] or sha != z["vidyan"]["sha256"]:
        raise Spryan("файлът е променен след прегледа — невидян; сканирай и прегледай наново")
    info = dict(bayt)
    rok = time.monotonic() + cfg["maks_vreme_s"]
    md_pat = os.path.join(izhod, z["id"] + ".md")
    parcheta = tekst.Parcheta(cfg["chunk_dumi"])
    md_bytes, n, signalen = 0, 0, []
    try:
        with open(md_pat + ".tmp", "w", encoding="utf-8") as f, \
                tempfile.TemporaryFile("w+", encoding="utf-8") as moi:
            g = tekst.glava(z, t)
            f.write(g)
            md_bytes += len(g.encode("utf-8"))
            for red in tekst.redove(konvertori.izvleci(pat, z["vid"], cfg, rok, info, "go")):
                f.write(red)
                md_bytes += len(red.encode("utf-8"))
                if z.get("otlozheno") and len(signalen) < 20000:
                    signalen.append(red)
                for p in parcheta.feed(red):
                    n = _chunk(moi, z, n, p)
            for p in parcheta.close():
                n = _chunk(moi, z, n, p)
            if z.get("otlozheno"):
                _sled_otlozhenoto(z, cfg, "".join(signalen), bayt)
            moi.seek(0)
            shutil.copyfileobj(moi, chf)
    except BaseException:
        if os.path.exists(md_pat + ".tmp"):
            os.remove(md_pat + ".tmp")
        raise
    os.replace(md_pat + ".tmp", md_pat)
    zapis = {"t": t, "md": os.path.basename(md_pat), "md_bytes": md_bytes, "chunks": n,
             "vidyan_ot": z["vidyan"]["rolya"]}
    if info.get("proveri") or z.get("proveri"):
        zapis["proveri"] = info.get("proveri") or z.get("proveri")
    return zapis


def _sled_otlozhenoto(z, cfg, tekst_, bayt):
    """OCR идва едва сега. Ако присъдата се смени (напр. стане доказателство), файлът спира: присъдата се
    записва, прегледът се губи, нищо не се пише. Човекът трябва да го види наново."""
    silni, dumi = prisadi.signali(cfg, tekst_, z["put"], bayt)
    if (z["prisada"] != "dokazatelstvo" and prisadi.mozhe_dokazatelstvo(cfg, z["vid"])
            and prisadi.e_dokazatelstvo(cfg, silni, dumi)):
        predi = z["prisada"]
        z.update(prisada="dokazatelstvo", klas="dokazatelstvo:%s" % z["vid"],
                 signali=silni + ["дума: " + d for d in dumi],
                 prichina="след OCR: %s" % "; ".join(silni + (["думи: " + ", ".join(dumi)] if dumi else [])),
                 predlozhenie=cfg["predlozheniya"]["dokazatelstvo"])
        z["otkas"] = tekst_[:cfg["otkas_znaci"]]
        raise Spryan("след OCR присъдата е „доказателство“ (беше %s) — спира и чака нов преглед" % predi)


def _chunk(fp, z, k, parche):
    tekst_, ot, do = parche
    zap = {"id": "%s-%04d" % (z["id"], k), "istochnik": z["put"], "sha256": z["sha256"],
           "poziciya": {"n": k, "ot_duma": ot, "do_duma": do}, "dumi": do - ot, "tekst": tekst_}
    if z.get("proveri"):
        zap["proveri"] = z["proveri"]
    fp.write(json.dumps(zap, ensure_ascii=False) + "\n")
    return k + 1


def go(karta, izhod, cfg, t):
    """Връща (преобразувани, парчета, спрени). Без годни файлове не създава нищо — нито папка, нито файл."""
    da = plan(karta, izhod, cfg)
    if not da:
        print("Няма решени с „да“ и видени — нищо не е записано.")
        return 0, 0, 0
    os.makedirs(izhod, exist_ok=True)
    chunks_pat = os.path.join(izhod, "chunks.jsonl")
    ok = n_chunks = spreni = 0
    with open(chunks_pat + ".tmp", "w", encoding="utf-8") as chf:
        for z in da:
            try:
                zapis = _preobrazuvay_edin(z, os.path.join(karta["koren"], z["put"]), izhod, cfg, t, chf)
            except Spryan as e:
                z["vidyan"] = None
                z["spryan"] = {"t": t, "prichina": str(e)}
                spreni += 1
                print("  СПРЯН: %s — %s" % (z["put"], e))
                continue
            except (Neyasno, OSError) as e:
                print("  пропуснат: %s — %s" % (z["put"], e))
                continue
            z["preobrazuvan"] = zapis
            z["spryan"] = None
            ok += 1
            n_chunks += zapis["chunks"]
            print("  готово: %s → %s (%s, %d парчета)" % (z["put"], zapis["md"],
                                                          prisadi.chovesko(zapis["md_bytes"]), zapis["chunks"]))
    os.replace(chunks_pat + ".tmp", chunks_pat)
    print("Преобразувани %d от %d · спрени %d · парчета: %d → %s" % (ok, len(da), spreni, n_chunks, chunks_pat))
    return ok, n_chunks, spreni
