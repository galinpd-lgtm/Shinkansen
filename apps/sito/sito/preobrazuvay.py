"""preobrazuvay: само решените с „да“ → <id>.md (източникът най-горе) + chunks.jsonl.

Без --go само показва плана и не пише нищо. Двигателят не пише в база: зареждането е частна стъпка (адаптер).
Преди да се пише, хешът се сверява с картата: променен след сканирането файл се пропуска.
"""
import json
import os
import shutil
import tempfile
import time

from . import instrumenti, konvertori, prisadi, tekst
from .instrumenti import Neyasno
from .skaner import hash_i_baytove

NEPREOBRAZUVAEMI = ("dublikat", "neyasno", "kontejner")


def razdeli(karta):
    """(за преобразуване, пропуснати с причина)."""
    da, ne = [], []
    for z in karta["faylove"]:
        r = z.get("reshenie")
        if not r:
            ne.append((z, "без решение"))
        elif not r["da"]:
            ne.append((z, "решено „не“"))
        elif z["prisada"] in NEPREOBRAZUVAEMI:
            ne.append((z, "%s — нищо не се прави" % z["prisada"]))
        elif z.get("problem"):
            ne.append((z, "MD не може: %s" % z["problem"]))
        else:
            da.append(z)
    return da, ne


def plan(karta, izhod, cfg):
    da, ne = razdeli(karta)
    print("План (нищо не е записано; за запис — --go):")
    print("  изход: %s" % izhod)
    for z in da:
        izg = " + <id>.pdf (изглед)" if z["vid"] == "pptx" and _izgled_vklyuchen(cfg) else ""
        print("  ✓ %s  %s → %s.md%s  (%s, очаквано %s)" % (z["id"], z["put"], z["id"], izg, z["prisada"],
                                                              _b(z.get("ochakvan_md_bytes"))))
    broy = {}
    for _, prichina in ne:
        k = prichina.split(" — ")[0].split(":")[0]
        broy[k] = broy.get(k, 0) + 1
    print("  за преобразуване: %d · пропуснати: %d%s" % (
        len(da), len(ne), (" (" + ", ".join("%s %d" % kv for kv in sorted(broy.items())) + ")") if ne else ""))
    return da


def _b(n):
    from .prisadi import chovesko
    return chovesko(n)


def _izgled_vklyuchen(cfg):
    return bool(cfg.get("pptx_pdf_izgled")) and bool(instrumenti.nameri("soffice"))


def _pdf_izgled(pat, cel, cfg):
    rok = time.monotonic() + cfg["maks_vreme_s"]
    with tempfile.TemporaryDirectory(prefix="sito-lo-") as d:
        kopie = os.path.join(d, "f.pptx")  # копие: LibreOffice не бива да оставя lock файлове до оригинала
        shutil.copyfile(pat, kopie)
        env = dict(os.environ, HOME=d)
        pusni_argumenti = [instrumenti.nameri("soffice"), "--headless", "--norestore", "--convert-to", "pdf",
                           "--outdir", d, kopie]
        instrumenti.pusni(pusni_argumenti, rok, cwd=d, env=env)
        izhoden = os.path.join(d, "f.pdf")
        if not os.path.exists(izhoden):
            raise Neyasno("LibreOffice не върна PDF")
        shutil.move(izhoden, cel)


def _preobrazuvay_edin(z, pat, izhod, cfg, t, chf):
    """Един файл → <id>.md и парчетата му. Парчетата отиват в chunks само ако файлът мине докрай."""
    sha, bayt = hash_i_baytove(pat, z["vid"], cfg)
    if sha != z["sha256"]:
        raise Neyasno("файлът е променен след сканирането — сканирай наново")
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
            moi.seek(0)
            shutil.copyfileobj(moi, chf)
    except BaseException:
        if os.path.exists(md_pat + ".tmp"):
            os.remove(md_pat + ".tmp")
        raise
    os.replace(md_pat + ".tmp", md_pat)
    zapis = {"t": t, "md": os.path.basename(md_pat), "md_bytes": md_bytes, "chunks": n}
    if info.get("proveri") or z.get("proveri"):
        zapis["proveri"] = info.get("proveri") or z.get("proveri")
    if z.get("otlozheno"):
        _sled_otlozhenoto(z, cfg, "".join(signalen), bayt, zapis)
    if z["vid"] == "pptx" and _izgled_vklyuchen(cfg):
        try:
            _pdf_izgled(pat, os.path.join(izhod, z["id"] + ".pdf"), cfg)
            zapis["pdf_izgled"] = z["id"] + ".pdf"
        except Neyasno as e:
            zapis["pdf_izgled_greshka"] = str(e)
    return zapis


def _sled_otlozhenoto(z, cfg, tekst_, bayt, zapis):
    """OCR/преписът идва едва сега: ако в него има признаци на доказателство, присъдата става доказателство.

    Решението на човека остава записано, но картата вече казва истината и оригиналът не е кандидат за архив.
    """
    silni, dumi = prisadi.signali(cfg, tekst_, z["put"], bayt)
    if z["prisada"] != "dokazatelstvo" and prisadi.e_dokazatelstvo(cfg, silni, dumi):
        predi = z["prisada"]
        z.update(prisada="dokazatelstvo", klas="dokazatelstvo:%s" % z["vid"],
                 signali=silni + ["дума: " + d for d in dumi],
                 prichina="след %s: %s" % (z["otlozheno"].split(" — ")[0],
                                           "; ".join(silni + (["думи: " + ", ".join(dumi)] if dumi else []))),
                 predlozhenie=cfg["predlozheniya"]["dokazatelstvo"])
        zapis["prisada_smenena"] = {"ot": predi, "na": "dokazatelstvo"}
        print("  внимание: %s — след %s има признаци на доказателство; присъдата е „доказателство“ (беше %s)"
              % (z["put"], z["otlozheno"].split(" — ")[0], predi))


def _chunk(fp, z, k, parche):
    tekst_, ot, do = parche
    zap = {"id": "%s-%04d" % (z["id"], k), "istochnik": z["put"], "sha256": z["sha256"],
           "poziciya": {"n": k, "ot_duma": ot, "do_duma": do}, "dumi": do - ot, "tekst": tekst_}
    if z.get("proveri"):
        zap["proveri"] = z["proveri"]
    fp.write(json.dumps(zap, ensure_ascii=False) + "\n")
    return k + 1


def go(karta, izhod, cfg, t):
    """Връща (преобразувани, парчета). Без решени с „да“ не създава нищо — нито папка, нито файл."""
    da = plan(karta, izhod, cfg)
    if not da:
        print("Няма решени с „да“ — нищо не е записано.")
        return 0, 0
    os.makedirs(izhod, exist_ok=True)
    chunks_pat = os.path.join(izhod, "chunks.jsonl")
    ok = n_chunks = 0
    with open(chunks_pat + ".tmp", "w", encoding="utf-8") as chf:
        for z in da:
            try:
                with konvertori.otvori(karta["koren"], z["put"], cfg) as pat:
                    zapis = _preobrazuvay_edin(z, pat, izhod, cfg, t, chf)
            except Neyasno as e:
                print("  пропуснат: %s — %s" % (z["put"], e))
                continue
            except OSError as e:
                print("  пропуснат: %s — %s" % (z["put"], e))
                continue
            z["preobrazuvan"] = zapis
            ok += 1
            n_chunks += zapis["chunks"]
            print("  готово: %s → %s (%s, %d парчета)" % (z["put"], zapis["md"], _b(zapis["md_bytes"]),
                                                          zapis["chunks"]))
    os.replace(chunks_pat + ".tmp", chunks_pat)
    print("Преобразувани %d от %d · парчета: %d → %s" % (ok, len(da), n_chunks, chunks_pat))
    return ok, n_chunks
