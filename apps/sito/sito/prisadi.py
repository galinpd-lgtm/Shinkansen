"""Присъдите. Правилата (обхват, думи, регекси, пътища, прагове) са в config; тук е само редът, в който се питат.

Първо обхватът — по разширението: izvan_obhvat, chist_tekst и arhiv само уведомяват (без решение, без преглед,
без --go). После, за четимите: dublikat → dokazatelstvo → neyasno → zhiv → opakovka → tekst.
Доказателство може да е само вид от dokazatelstvo.vidove (PDF, DOCX, DOC, RTF — и сканираните PDF). Другаде
същите думи и номера дават само бележка „споменава …“.
"""
import fnmatch
from datetime import timedelta

IMENA = {"opakovka": "опаковка", "dokazatelstvo": "доказателство", "zhiv": "жив", "tekst": "текст",
         "dublikat": "дубликат", "neyasno": "неясно", "izvan_obhvat": "извън обхвата",
         "chist_tekst": "чист текст", "arhiv": "архив"}


def signali(cfg, tekst, put, bayt):
    """Какво сочи към доказателство. Силните (номер по регекс, поле за подпис в PDF) стигат сами."""
    silni, dumi = [], []
    if bayt.get("podpis"):
        silni.append("поле за електронен подпис в PDF (%s)" % ", ".join(sorted(bayt["podpis"])))
    for ime, rx in cfg["_regeksi"]:
        if rx.search(tekst):
            silni.append(ime)
    ime_na_fayl = put.rsplit("/", 1)[-1]
    for d, rx in cfg["_dumi"]:
        if rx.search(tekst) or rx.search(ime_na_fayl):
            dumi.append(d)
    return silni, dumi


def e_dokazatelstvo(cfg, silni, dumi):
    return bool(silni) or len(dumi) >= cfg["dokazatelstvo"].get("min_dumi", 2)


def mozhe_dokazatelstvo(cfg, vid):
    return vid in cfg["dokazatelstvo"]["vidove"]


def spomenava(silni, dumi):
    """Бележката за файл, който не може да е доказателство, но съдържа думите или номерата от config."""
    neshta = [s.split(" (")[0] for s in silni] + dumi
    return ("споменава " + ", ".join(neshta)) if neshta else None


def e_zhiv(cfg, put, promenen_ts, sega):
    """Жив е файлът по правило за път или по скорошна промяна."""
    for patern in cfg["zhiv"].get("patishta", []):
        if fnmatch.fnmatch(put, patern):
            return "пътят отговаря на „%s“" % patern
    dni = cfg["zhiv"].get("promenen_predi_dni")
    if dni and promenen_ts is not None and promenen_ts > (sega - timedelta(days=dni)).timestamp():
        return "променян през последните %d дни" % dni
    return None


def uvedomi(cfg, z, kategoriya, belezhka=None):
    """Присъда само за уведомяване: извън обхвата, чист текст, архив. Без предложение за действие — само бележка."""
    prichina = {"izvan_obhvat": "вид „%s“" % z["vid"],
                "chist_tekst": "TXT/MD",
                "arhiv": "архив — не се отваря и не се чете отвътре"}[kategoriya]
    prichina += "; " + cfg["belezhki"][kategoriya]
    z.update(prisada=kategoriya, prichina=prichina, predlozhenie="",
             klas="%s:%s" % (kategoriya, z["vid"]), problem=None, signali=[], belezhka=belezhka)


def reshi(cfg, z, silni, dumi, problem, info, promenen_ts, sega, instr):
    """Попълва prisada, prichina, predlozhenie, klas, belezhka в записа z (само за четимите видове)."""
    vid = z["vid"]
    belezhka = None
    if mozhe_dokazatelstvo(cfg, vid) and e_dokazatelstvo(cfg, silni, dumi):
        pr = "dokazatelstvo"
        prichina = "; ".join(silni + (["думи: " + ", ".join(dumi)] if dumi else []))
    else:
        if not mozhe_dokazatelstvo(cfg, vid):
            belezhka = spomenava(silni, dumi)
        if problem:
            pr, prichina = "neyasno", problem
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
    z.update(prisada=pr, prichina=prichina, predlozhenie=predl, klas="%s:%s" % (pr, vid),
             problem=problem, signali=silni + ["дума: " + d for d in dumi], belezhka=belezhka)


def chovesko(n):
    if n is None:
        return "—"
    for ed in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or ed == "GB":
            return ("%d %s" % (n, ed)) if ed == "B" else ("%.1f %s" % (n, ed))
        n /= 1024.0
