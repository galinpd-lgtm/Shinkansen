"""Присъдите. Правилата (думи, регекси, пътища, прагове) са в config; тук е само редът, в който се питат.

Ред: dublikat → dokazatelstvo → neyasno → zhiv → opakovka → tekst. Контейнер (ZIP) без пречка е kontejner.
Доказателството е преди „неясно“: подписан PDF без pdftotext пак е доказателство — само MD не може.
"""
import fnmatch
import os
from datetime import timedelta

IMENA = {"opakovka": "опаковка", "dokazatelstvo": "доказателство", "zhiv": "жив", "tekst": "текст",
         "dublikat": "дубликат", "neyasno": "неясно", "kontejner": "контейнер"}


def signali(cfg, tekst, put, bayt):
    """Какво сочи към доказателство. Силните (номер по регекс, поле за подпис в PDF) стигат сами."""
    silni, dumi = [], []
    if bayt.get("podpis"):
        silni.append("поле за електронен подпис в PDF (%s)" % ", ".join(sorted(bayt["podpis"])))
    for ime, rx in cfg["_regeksi"]:
        if rx.search(tekst):
            silni.append(ime)
    ime_na_fayl = os.path.basename(put.split("!/")[-1])
    for d, rx in cfg["_dumi"]:
        if rx.search(tekst) or rx.search(ime_na_fayl):
            dumi.append(d)
    return silni, dumi


def e_dokazatelstvo(cfg, silni, dumi):
    return bool(silni) or len(dumi) >= cfg["dokazatelstvo"].get("min_dumi", 2)


def e_zhiv(cfg, put, promenen_ts, sega):
    """Жив е файлът по правило за път или по скорошна промяна. Вътре в контейнер не е жив."""
    if "!/" in put:
        return None
    for patern in cfg["zhiv"].get("patishta", []):
        if fnmatch.fnmatch(put, patern):
            return "пътят отговаря на „%s“" % patern
    dni = cfg["zhiv"].get("promenen_predi_dni")
    if dni and promenen_ts is not None and promenen_ts > (sega - timedelta(days=dni)).timestamp():
        return "променян през последните %d дни" % dni
    return None


def reshi(cfg, z, silni, dumi, problem, info, promenen_ts, sega, instr):
    """Попълва prisada, prichina, predlozhenie, klas в записа z."""
    vid = z["vid"]
    if e_dokazatelstvo(cfg, silni, dumi):
        pr = "dokazatelstvo"
        prichina = "; ".join(silni + (["думи: " + ", ".join(dumi)] if dumi else []))
    elif problem:
        pr, prichina = "neyasno", problem
    elif vid == "zip":
        pr, prichina = "kontejner", "архив — съдържанието минава поотделно"
    else:
        zhiv = e_zhiv(cfg, z["put"], promenen_ts, sega)
        dyal = (z["tekst_bytes"] / z["razmer"]) if z["razmer"] else 1.0
        op = cfg["opakovka"]
        if zhiv:
            pr, prichina = "zhiv", zhiv
        elif vid in op["vidove"] and info.get("skaniran"):
            pr, prichina = "opakovka", "сканиран — текстът е само в картината"
            if info.get("otlozheno"):
                prichina += "; признаците за доказателство се проверяват след OCR"
        elif info.get("otlozheno"):
            pr, prichina = "tekst", "размерът на текста се знае едва след %s" % info["otlozheno"]
        elif vid in op["vidove"] and dyal < op["prag_tekst_kam_razmer"]:
            pr, prichina = "opakovka", "текстът е %.2f%% от размера (праг %g%%)" % (
                100 * dyal, 100 * op["prag_tekst_kam_razmer"])
        else:
            pr, prichina = "tekst", "текстът е основното съдържание (%.0f%% от размера)" % (100 * min(dyal, 1))
    predl = cfg["predlozheniya"][pr]
    if pr == "dokazatelstvo" and vid == "pdf":
        if instr.get("qpdf"):
            predl += " · компресия без загуба: qpdf (наличен)"
        elif instr.get("gs"):
            predl += " · компресия: Ghostscript (наличен) — само с настройки без загуба"
        else:
            predl += " · компресия: няма qpdf/Ghostscript на машината"
    if pr == "dokazatelstvo" and problem:
        predl += " · MD не може: " + problem
    if pr == "opakovka" and z["razmer"] and z.get("ochakvan_md_bytes"):
        predl += " · очаквано %s → %s" % (chovesko(z["razmer"]), chovesko(z["ochakvan_md_bytes"]))
    z.update(prisada=pr, prichina=prichina, predlozhenie=predl, klas="%s:%s" % (pr, vid or "?"),
             problem=problem, signali=silni + ["дума: " + d for d in dumi])


def chovesko(n):
    if n is None:
        return "—"
    for ed in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or ed == "GB":
            return ("%d %s" % (n, ed)) if ed == "B" else ("%.1f %s" % (n, ed))
        n /= 1024.0
