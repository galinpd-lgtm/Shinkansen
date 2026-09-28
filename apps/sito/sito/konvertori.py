"""Конверторите: файл → поток от текст. Само за видовете в обхвата: HTML, DOCX, DOC, RTF, PDF, PPTX.

Всеки конвертор чете поточно и проверява тавана за време. Всичко, което пречи да се прочете текстът
(няма инструмент, криптиран, повреден, над тавана), е Neyasno с причина — не грешка на програмата.
Архиви не се отварят. Изходната папка само се чете: временните файлове са в системната временна папка.
Никаква имитация на Office: DOCX и PPTX се четат като XML, DOC — с antiword/catdoc, RTF — със собствен четец.
"""
import contextlib
import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from . import html_tekst, instrumenti, rtf_tekst
from .instrumenti import Neyasno, proveri_rok, pusni

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def blokove(pat, cfg, rok=None):
    n = cfg["blok_bytes"]
    with open(pat, "rb") as f:
        while True:
            b = f.read(n)
            if not b:
                return
            if rok:
                proveri_rok(rok)
            yield b


def izvleci(pat, vid, cfg, rok, info, rezhim="skan"):
    """Генератор от сурови парчета текст. info се попълва: stranici, skaniran, proveri, otlozheno …

    rezhim „skan“ — само да се измери и да се видят сигналите (OCR се отлага, ако config не казва друго);
    „go“ — пълно преобразуване.
    """
    f = {"html": _html, "docx": _docx, "doc": _doc, "rtf": _rtf, "pdf": _pdf, "pptx": _pptx}.get(vid)
    if f is None:
        raise Neyasno("няма конвертор за вид „%s“" % vid)
    return f(pat, cfg, rok, info, rezhim)


# ─────────── HTML, текст ───────────

def _html(pat, cfg, rok, info, rezhim):
    yield from html_tekst.tekst_ot_potok(blokove(pat, cfg), cfg["html"]["propuskay_elementi"],
                                         lambda: proveri_rok(rok))


def nachalo_na_tekst(pat, n=2_000_000):
    """Първите n байта от чист текст (TXT/MD) — само за бележката „споменава …“. Не се преобразува."""
    with open(pat, "rb") as fp:
        danni = fp.read(n)
    try:
        return danni.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        return danni.decode("utf-8-sig" if e.start > len(danni) - 4 else "cp1251", "replace")


# ─────────── RTF (собствен четец) и DOC (antiword / catdoc) ───────────

def _rtf(pat, cfg, rok, info, rezhim):
    with open(pat, "rb") as fp:
        if not rtf_tekst.e_rtf(fp.read(64)):
            raise Neyasno("повреден RTF: не започва с {\\rtf")
    yield from rtf_tekst.tekst_ot_potok(blokove(pat, cfg), lambda: proveri_rok(rok))


def _doc(pat, cfg, rok, info, rezhim):
    with open(pat, "rb") as fp:
        nachalo = fp.read(8)
    if rtf_tekst.e_rtf(nachalo):  # често: RTF, записан като .doc
        yield from _rtf(pat, cfg, rok, info, rezhim)
        return
    if nachalo != OLE:
        raise Neyasno("повреден DOC: не е OLE файл")
    if instrumenti.nameri("antiword"):
        out = pusni(["antiword", "-w", "0", "-m", "UTF-8.txt", pat], rok)
    elif instrumenti.nameri("catdoc"):
        out = pusni(["catdoc", "-w", "-d", "utf-8", pat], rok)
    else:
        raise Neyasno("DOC: няма antiword или catdoc на машината")
    yield out.decode("utf-8", "replace")


# ─────────── Office: DOCX и PPTX (zipfile + XML, поточно) ───────────

@contextlib.contextmanager
def _office(pat):
    with open(pat, "rb") as fp:
        if fp.read(8) == OLE:
            raise Neyasno("криптиран или стар формат (OLE контейнер) — няма конвертор")
    try:
        z = zipfile.ZipFile(pat)
    except (zipfile.BadZipFile, OSError) as e:
        raise Neyasno("повреден файл: %s" % e)
    with z:
        yield z


def _xml_parcheta(stream, rok, paragraf, tekst, dopalnitelno=None):
    """iterparse върху член на zip: абзаците идват един по един и веднага се изчистват от паметта."""
    buf, prefiks = [], ""
    try:
        for ev, el in ET.iterparse(stream, events=("start", "end")):
            if ev == "start":
                if el.tag == paragraf:
                    buf, prefiks = [], ""
                continue
            if el.tag == tekst:
                buf.append(el.text or "")
            elif dopalnitelno and el.tag in dopalnitelno:
                r = dopalnitelno[el.tag](el)
                if r is None:
                    continue
                if r.startswith("#"):
                    prefiks = r
                else:
                    buf.append(r)
            elif el.tag == paragraf:
                proveri_rok(rok)
                t = "".join(buf)
                if t.strip():
                    yield prefiks + t + "\n\n"
                el.clear()
    except ET.ParseError as e:
        raise Neyasno("повреден XML: %s" % e)


def _stil(el):
    v = el.get(W + "val") or ""
    m = re.match(r"(?i)heading\s?(\d)$", v)
    if m:
        return "#" * min(6, int(m.group(1))) + " "
    if v.lower() == "title":
        return "# "
    return None


def _docx(pat, cfg, rok, info, rezhim):
    with _office(pat) as z:
        if "word/document.xml" not in z.namelist():
            raise Neyasno("повреден DOCX: няма word/document.xml")
        with z.open("word/document.xml") as s:
            yield from _xml_parcheta(s, rok, W + "p", W + "t",
                                     {W + "tab": lambda e: "\t", W + "br": lambda e: "\n",
                                      W + "cr": lambda e: "\n", W + "pStyle": _stil})


def _nomer(ime):
    m = re.search(r"(\d+)\.xml$", ime)
    return int(m.group(1)) if m else 0


def _pptx(pat, cfg, rok, info, rezhim):
    with _office(pat) as z:
        imena = z.namelist()
        slaydove = sorted((n for n in imena if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=_nomer)
        if not slaydove:
            raise Neyasno("повреден PPTX: няма слайдове")
        info["slaydove"] = len(slaydove)
        for n in slaydove:
            yield "\n\n## Слайд %d\n\n" % _nomer(n)
            with z.open(n) as s:
                yield from _xml_parcheta(s, rok, A + "p", A + "t")
            belezhki = _belezhki_na(z, n, imena)
            if belezhki:
                parcheta = []
                with z.open(belezhki) as s:
                    for p in _xml_parcheta(s, rok, A + "p", A + "t"):
                        if not re.fullmatch(r"\s*\d+\s*", p):  # номерът на слайда в бележките
                            parcheta.append(p)
                if parcheta:
                    yield "\n**Бележки:**\n\n"
                    yield from parcheta


def _belezhki_na(z, slayd, imena):
    rels = "ppt/slides/_rels/%s.rels" % os.path.basename(slayd)
    if rels not in imena:
        return None
    try:
        with z.open(rels) as s:
            koren = ET.parse(s).getroot()
    except ET.ParseError:
        return None
    for r in koren.iter(REL + "Relationship"):
        if r.get("Type", "").endswith("/notesSlide"):
            cel = os.path.normpath(os.path.join("ppt/slides", r.get("Target", ""))).replace(os.sep, "/")
            return cel if cel in imena else None
    return None


# ─────────── PDF: pdftotext; сканиран → OCR (pdftoppm + tesseract) ───────────

def _stranici(pat, rok, info):
    if info.get("stranici"):
        return info["stranici"]
    if instrumenti.nameri("pdfinfo"):
        try:
            out = pusni(["pdfinfo", pat], rok).decode("utf-8", "replace")
            m = re.search(r"^Pages:\s+(\d+)", out, re.M)
            if m:
                info["stranici"] = int(m.group(1))
        except Neyasno:
            pass
    return info.get("stranici") or 1


def _pdf(pat, cfg, rok, info, rezhim):
    if not instrumenti.nameri("pdftotext"):
        raise Neyasno("PDF: няма pdftotext на машината")
    with tempfile.TemporaryDirectory(prefix="sito-") as d:
        izhod = os.path.join(d, "t.txt")
        try:
            pusni(["pdftotext", "-enc", "UTF-8", pat, izhod], rok)
        except Neyasno as e:
            raise Neyasno(("криптиран PDF — " if info.get("kriptiran") else "") + str(e))
        znaci = 0
        with open(izhod, "rb") as fp:
            for b in iter(lambda: fp.read(1 << 20), b""):
                znaci += sum(len(x) for x in b.split())
        prag = cfg["ocr"]["prag_znaci_na_stranica"] * _stranici(pat, rok, info)
        if znaci >= prag:
            import codecs
            dek = codecs.getincrementaldecoder("utf-8")(errors="replace")
            with open(izhod, "rb") as fp:
                for b in iter(lambda: fp.read(1 << 20), b""):
                    proveri_rok(rok)
                    yield dek.decode(b).replace("\f", "\n\n")
            return
    info["skaniran"] = True
    info["proveri"] = "сканиран PDF — текстът е от OCR, провери го"
    if not (instrumenti.nameri("pdftoppm") and instrumenti.nameri("tesseract")):
        raise Neyasno("сканиран PDF — няма OCR на машината (pdftoppm + tesseract)")
    if rezhim == "skan" and not cfg["ocr"]["pri_skanirane"]:
        info["otlozheno"] = "OCR — при преобразуването"
        return
    yield from _ocr(pat, cfg, rok)


def _ocr(pat, cfg, rok):
    with tempfile.TemporaryDirectory(prefix="sito-ocr-") as d:
        pusni(["pdftoppm", "-r", str(cfg["ocr"]["dpi"]), "-png", pat, os.path.join(d, "s")], rok)
        for n, ime in enumerate(sorted(os.listdir(d), key=lambda x: (len(x), x)), 1):
            out = pusni(["tesseract", os.path.join(d, ime), "stdout", "-l", cfg["ocr"]["ezici"]], rok)
            yield "\n\n## Страница %d\n\n" % n
            yield out.decode("utf-8", "replace")
