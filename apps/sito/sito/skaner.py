"""skanirai: обхожда папката САМО ЗА ЧЕТЕНЕ. За всеки файл: хеш, вид, размер, текст (само се мери), присъда.

Пази се само откъс от текста (за прегледа от човека) и първите байтове за сигналите. Архиви не се отварят —
от тях се взима само хешът на самия файл. Нищо не се пише в изходната папка.
"""
import fnmatch
import hashlib
import os
import re
import time
from datetime import datetime, timezone

from . import VERSIYA, instrumenti, konvertori, prisadi, tekst
from . import config as cf
from .instrumenti import Neyasno

MAKS_SIGNALEN_TEKST = 2_000_000  # първите ~2 MB текст стигат за сигналите
_STRANICA = re.compile(rb"/Type\s*/Page(?![A-Za-z])")


def fid(put):
    return "f" + hashlib.sha256(put.encode("utf-8")).hexdigest()[:12]


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def hash_i_baytove(pat, vid, cfg):
    """SHA-256 поточно. За PDF в същото минаване: страници, /Encrypt и полета за подпис."""
    h = hashlib.sha256()
    pdf = vid == "pdf"
    markeri = [m.encode("latin-1") for m in cfg["dokazatelstvo"].get("pdf_podpis_markeri", [])]
    opashka, stranici, kriptiran, podpis = b"", 0, False, set()
    for b in konvertori.blokove(pat, cfg):
        h.update(b)
        if pdf:
            d = opashka + b
            stranici += sum(1 for m in _STRANICA.finditer(d) if m.end() > len(opashka))
            kriptiran = kriptiran or b"/Encrypt" in d
            for m in markeri:
                if m in d:
                    podpis.add(m.decode("latin-1"))
            opashka = d[-64:]
    info = {}
    if pdf:
        info = {"stranici": stranici or None, "kriptiran": kriptiran, "podpis": podpis}
    return h.hexdigest(), info


class Skaner:
    def __init__(self, koren, cfg, sega):
        self.koren, self.cfg, self.sega = koren, cfg, sega
        self.instr = instrumenti.nalichni(cfg)
        self.zapisi, self.po_hash = [], {}
        self.propusnati = {"sistemni": 0, "vrazki": 0, "dalbochina": 0}

    def pusni(self):
        cfg = self.cfg
        for d, papki, faylove in os.walk(self.koren, followlinks=False):
            rel = os.path.relpath(d, self.koren)
            dalbochina = 0 if rel == "." else rel.count(os.sep) + 1
            sistemna = any(fnmatch.fnmatch(ch, p) for ch in ([] if rel == "." else rel.split(os.sep))
                           for p in cfg["propuskay_papki"])
            papki.sort()
            for ime in sorted(faylove):
                pat = os.path.join(d, ime)
                if sistemna or any(fnmatch.fnmatch(ime, p) for p in cfg["propuskay"]):
                    self.propusnati["sistemni"] += 1
                    continue
                if os.path.islink(pat) or not os.path.isfile(pat):
                    self.propusnati["vrazki"] += 1
                    continue
                if dalbochina > cfg["maks_dalbochina"]:  # броим, но не четем
                    self.propusnati["dalbochina"] += 1
                    continue
                put = os.path.relpath(pat, self.koren).replace(os.sep, "/")
                mt = os.stat(pat).st_mtime
                self.obraboti(pat, put, iso(mt), mt)
        return {"sito": VERSIYA, "koren": os.path.abspath(self.koren),
                "skanirano": self.sega.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "config": os.path.abspath(cfg["_pat"]), "instrumenti": self.instr,
                "maks_dalbochina": cfg["maks_dalbochina"], "propusnati": self.propusnati, "faylove": self.zapisi}

    def obraboti(self, pat, put, promenen, promenen_ts):
        cfg = self.cfg
        kategoriya, vid = cf.vid_po_ime(cfg, put)
        razmer = os.path.getsize(pat)
        sha, bayt = hash_i_baytove(pat, vid, cfg)
        z = {"id": fid(put), "put": put, "vid": vid, "razmer": razmer, "sha256": sha, "promenen": promenen,
             "tekst_bytes": 0, "ochakvan_md_bytes": None, "otkas": None, "proveri": None, "dublikat_na": None,
             "belezhka": None, "reshenie": None, "vidyan": None, "preobrazuvan": None, "spryan": None,
             "kandidat_pdf": None}
        self.zapisi.append(z)

        if kategoriya in cf.SAMO_UVEDOMYAVAT:
            belezhka = None
            if kategoriya == "chist_tekst":  # само бележка „споменава …“ — никога присъда
                belezhka = prisadi.spomenava(*prisadi.signali(cfg, konvertori.nachalo_na_tekst(pat), put, {}))
            prisadi.uvedomi(cfg, z, kategoriya, belezhka)
            return

        if sha in self.po_hash:
            parvi = self.po_hash[sha]
            z.update(prisada="dublikat", klas="dublikat:%s" % vid, dublikat_na=parvi["id"],
                     prichina="същият SHA-256 като %s" % parvi["put"], predlozhenie=cfg["predlozheniya"]["dublikat"],
                     problem=None, signali=[])
            return
        self.po_hash[sha] = z

        info, problem, signalen, n_signalen = dict(bayt), None, [], 0
        rok = time.monotonic() + cfg["maks_vreme_s"]
        if razmer > cfg["maks_razmer_bytes"]:
            problem = "над тавана за размер (%s)" % prisadi.chovesko(cfg["maks_razmer_bytes"])
        else:
            try:
                for red in tekst.redove(konvertori.izvleci(pat, vid, cfg, rok, info, "skan")):
                    z["tekst_bytes"] += len(red.encode("utf-8"))
                    if n_signalen < MAKS_SIGNALEN_TEKST:
                        signalen.append(red)
                        n_signalen += len(red)
            except Neyasno as e:
                problem = str(e)
            except Exception as e:  # един лош файл не спира цялото сканиране — записва се
                problem = "неочаквана грешка при четене: %s: %s" % (type(e).__name__, e)

        if info.get("proveri"):
            z["proveri"] = info["proveri"]
        if info.get("otlozheno"):
            z["otlozheno"] = info["otlozheno"]
        if not problem and not info.get("otlozheno"):
            z["ochakvan_md_bytes"] = len(tekst.glava(z, "0000-00-00T00:00:00Z").encode("utf-8")) + z["tekst_bytes"]
        sig = "".join(signalen)
        if not problem:
            z["otkas"] = sig[:cfg["otkas_znaci"]] if sig else None
        silni, dumi = prisadi.signali(cfg, sig, put, bayt)
        prisadi.reshi(cfg, z, silni, dumi, problem, info, promenen_ts, self.sega, self.instr)




def prenesi(stara, nova):
    """Решенията и прегледите от предишната карта на същата папка. Прегледът оцелява само ако файлът е
    същият (SHA-256) и присъдата е същата; иначе файлът е невидян. Връща (пренесени, изгубени прегледи)."""
    if not stara or os.path.realpath(stara.get("koren", "")) != os.path.realpath(nova["koren"]):
        return 0, 0
    po_id = {z["id"]: z for z in stara.get("faylove", [])}
    preneseni = izgubeni = 0
    for z in nova["faylove"]:
        s = po_id.get(z["id"])
        if not s or z["prisada"] in cf.SAMO_UVEDOMYAVAT:
            continue
        if s.get("sha256") == z["sha256"]:
            for k in ("reshenie", "preobrazuvan", "kandidat_pdf"):
                z[k] = s.get(k)
        elif s.get("reshenie"):
            z["reshenie"] = s["reshenie"]
        v = s.get("vidyan")
        if v and v.get("sha256") == z["sha256"] and s.get("prisada") == z["prisada"]:
            z["vidyan"] = v
            preneseni += 1
        elif v:
            izgubeni += 1
    return preneseni, izgubeni
