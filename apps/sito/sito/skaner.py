"""skanirai: обхожда папката САМО ЗА ЧЕТЕНЕ. За всеки файл: хеш, вид, размер, текст (само се мери), присъда.

Текстът не се пази — само размерът му и първите байтове за сигналите. Нищо не се пише в изходната папка:
временните файлове (членове на ZIP, прикачени към писма) са в системната временна папка.
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
        self.propusnati = {"sistemni": 0, "vrazki": 0}

    def pusni(self):
        for d, papki, faylove in os.walk(self.koren, followlinks=False):
            papki.sort()
            for ime in sorted(faylove):
                pat = os.path.join(d, ime)
                if any(fnmatch.fnmatch(ime, p) for p in self.cfg["propuskay"]):
                    self.propusnati["sistemni"] += 1
                    continue
                if os.path.islink(pat) or not os.path.isfile(pat):
                    self.propusnati["vrazki"] += 1
                    continue
                put = os.path.relpath(pat, self.koren).replace(os.sep, "/")
                mt = os.stat(pat).st_mtime
                self.obraboti(pat, put, None, 0, iso(mt), mt)
        return {"sito": VERSIYA, "koren": os.path.abspath(self.koren),
                "skanirano": self.sega.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "config": os.path.abspath(self.cfg["_pat"]), "instrumenti": self.instr,
                "propusnati": self.propusnati, "faylove": self.zapisi}

    def _neyasno_dete(self, put, roditel, promenen, prichina):
        z = {"id": fid(put), "put": put, "vid": cf.vid_po_ime(self.cfg, put), "razmer": None, "sha256": None,
             "promenen": promenen, "roditel": roditel, "tekst_bytes": 0, "ochakvan_md_bytes": None,
             "proveri": None, "dublikat_na": None, "reshenie": None, "preobrazuvan": None}
        prisadi.reshi(self.cfg, z, [], [], prichina, {}, None, self.sega, self.instr)
        self.zapisi.append(z)

    def obraboti(self, pat, put, roditel, dalbochina, promenen, promenen_ts):
        cfg = self.cfg
        vid = cf.vid_po_ime(cfg, put.split(konvertori.RAZDELITEL)[-1])
        razmer = os.path.getsize(pat)
        sha, bayt = hash_i_baytove(pat, vid, cfg)
        z = {"id": fid(put), "put": put, "vid": vid, "razmer": razmer, "sha256": sha, "promenen": promenen,
             "roditel": roditel, "tekst_bytes": 0, "ochakvan_md_bytes": None, "proveri": None,
             "dublikat_na": None, "reshenie": None, "preobrazuvan": None}
        self.zapisi.append(z)
        if sha in self.po_hash:
            parvi = self.po_hash[sha]
            z.update(prisada="dublikat", klas="dublikat:%s" % (vid or "?"), dublikat_na=parvi["id"],
                     prichina="същият SHA-256 като %s" % parvi["put"], predlozhenie=cfg["predlozheniya"]["dublikat"],
                     problem=None, signali=[])
            return
        self.po_hash[sha] = z

        info, problem, signalen, n_signalen = dict(bayt), None, [], 0
        rok = time.monotonic() + cfg["maks_vreme_s"]
        if razmer > cfg["maks_razmer_bytes"]:
            problem = "над тавана за размер (%s)" % prisadi.chovesko(cfg["maks_razmer_bytes"])
        elif vid == "zip":
            pass
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

        if vid in cf.KONTEJNERI + ("eml",) and not problem:
            if dalbochina >= cfg["maks_dalbochina"]:
                if vid == "zip":
                    problem = "над максималната дълбочина (%d) — съдържанието не е прегледано" % dalbochina
            else:
                try:
                    for ime, tpat, data, prichina in konvertori.deca(pat, vid, cfg):
                        dput = put + konvertori.RAZDELITEL + ime
                        if prichina:
                            self._neyasno_dete(dput, z["id"], data or promenen, prichina)
                        else:
                            self.obraboti(tpat, dput, z["id"], dalbochina + 1, data or promenen, None)
                except Neyasno as e:
                    if vid == "zip":
                        problem = str(e)

        if info.get("proveri"):
            z["proveri"] = info["proveri"]
        if info.get("otlozheno"):
            z["otlozheno"] = info["otlozheno"]
        if not problem and vid != "zip" and not info.get("otlozheno"):
            z["ochakvan_md_bytes"] = len(tekst.glava(z, "0000-00-00T00:00:00Z").encode("utf-8")) + z["tekst_bytes"]
        silni, dumi = prisadi.signali(cfg, "".join(signalen), put, bayt)
        prisadi.reshi(cfg, z, silni, dumi, problem, info, promenen_ts, self.sega, self.instr)
