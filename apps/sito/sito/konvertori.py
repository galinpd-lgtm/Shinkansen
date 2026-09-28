"""Конверторите: файл → поток от текст. И контейнерите: ZIP и .eml → прикачените файлове, един по един.

Всеки конвертор чете поточно и проверява тавана за време. Всичко, което пречи да се прочете текстът
(няма инструмент, криптиран, повреден, над тавана), е Neyasno с причина — не грешка на програмата.
Изходната папка само се чете: временните файлове са в системната временна папка, никога до оригинала.
"""
import contextlib
import email
import email.policy
import os
import re
import shutil
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from . import config, html_tekst, instrumenti
from .instrumenti import Neyasno, proveri_rok, pusni

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
RAZDELITEL = "!/"  # път вътре в контейнер: arhiv.zip!/papka/dogovor.docx
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

    rezhim „skan“ — само да се измери и да се видят сигналите (OCR и Whisper се отлагат, ако config не казва
    друго); „go“ — пълно преобразуване.
    """
    f = {"html": _html, "docx": _docx, "pdf": _pdf, "pptx": _pptx, "tekst": _tekst, "eml": _eml,
         "media": _media}.get(vid)
    if f is None:
        raise Neyasno("няма конвертор за този вид файл" if vid else "непознат вид файл")
    return f(pat, cfg, rok, info, rezhim)


# ─────────── HTML, текст ───────────

def _html(pat, cfg, rok, info, rezhim):
    yield from html_tekst.tekst_ot_potok(blokove(pat, cfg), cfg["html"]["propuskay_elementi"],
                                         lambda: proveri_rok(rok))


def _tekst(pat, cfg, rok, info, rezhim):
    import codecs
    with open(pat, "rb") as fp:
        nachalo = fp.read(65536)
    try:
        nachalo.decode("utf-8")
        kod = "utf-8-sig"
    except UnicodeDecodeError as e:
        kod = "utf-8-sig" if e.start > len(nachalo) - 4 else "cp1251"
    dek = codecs.getincrementaldecoder(kod)(errors="replace")
    for b in blokove(pat, cfg, rok):
        yield dek.decode(b)
    yield dek.decode(b"", final=True)


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


# ─────────── видео и аудио: Whisper, само ако е локално наличен ───────────

def _media(pat, cfg, rok, info, rezhim):
    w = cfg["whisper"]
    if not instrumenti.nameri(w["komanda"]):
        raise Neyasno("видео/аудио: няма локален Whisper (%s)" % w["komanda"])
    info["proveri"] = "препис от Whisper — провери го"
    if rezhim == "skan":
        info["otlozheno"] = "препис — при преобразуването"
        return
    with tempfile.TemporaryDirectory(prefix="sito-whisper-") as d:
        pusni([w["komanda"], pat, "--language", w.get("ezik", "bg"), "--model", w.get("model", "medium"),
               "--output_format", "txt", "--output_dir", d], rok)
        txt = [x for x in os.listdir(d) if x.endswith(".txt")]
        if not txt:
            raise Neyasno("Whisper не върна препис")
        with open(os.path.join(d, txt[0]), encoding="utf-8", errors="replace") as fp:
            for red in fp:
                yield red


# ─────────── .eml: писмото + прикачените ───────────

def _pismo(pat, cfg):
    try:
        with open(pat, "rb") as fp:
            return email.message_from_binary_file(fp, policy=email.policy.default)
    except Exception as e:  # email хвърля какво ли не при повреден файл
        raise Neyasno("повредено писмо: %s" % e)


def _eml(pat, cfg, rok, info, rezhim):
    m = _pismo(pat, cfg)
    for ime, zag in (("Тема", "subject"), ("От", "from"), ("До", "to"), ("Дата", "date")):
        if m[zag]:
            yield "%s: %s\n" % (ime, " ".join(str(m[zag]).split()))
    yield "\n"
    tyalo = m.get_body(preferencelist=("plain", "html"))
    if tyalo is None:
        return
    try:
        sadarzhanie = tyalo.get_content()
    except (LookupError, ValueError) as e:
        raise Neyasno("писмото не се декодира: %s" % e)
    if tyalo.get_content_subtype() == "html":
        yield from html_tekst.tekst_ot_potok([sadarzhanie.encode("utf-8")], cfg["html"]["propuskay_elementi"])
    else:
        yield sadarzhanie


def _bezopasno(ime):
    ime = re.sub(r"[\\/\x00-\x1f]", "_", ime or "").strip(". ") or "prikacheno"
    return ime[:120]


# ─────────── контейнери ───────────

def _izvadi(izvor, cel, maks, rok):
    """Копира поток във временен файл, с таван за размер и време."""
    n = 0
    with open(cel, "wb") as out:
        for b in iter(lambda: izvor.read(1 << 20), b""):
            n += len(b)
            if n > maks:
                raise Neyasno("над тавана за размер (в контейнер)")
            proveri_rok(rok)
            out.write(b)


def _zip_data(zi):
    try:
        return datetime(*zi.date_time, tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except ValueError:
        return None


def _rok(cfg):
    return time.monotonic() + cfg["maks_vreme_s"]


def deca(pat, vid, cfg):
    """Генератор от (име, временен път или None, дата или None, причина за „неясно“ или None).

    Временният файл живее само докато трае обработката на детето. Всяко дете има свой таван за време.
    """
    if vid == "zip":
        yield from _deca_zip(pat, cfg)
    elif vid == "eml":
        yield from _deca_eml(pat, cfg)


def _deca_zip(pat, cfg):
    try:
        z = zipfile.ZipFile(pat)
    except (zipfile.BadZipFile, OSError) as e:
        raise Neyasno("повреден ZIP: %s" % e)
    with z, tempfile.TemporaryDirectory(prefix="sito-zip-") as d:
        for n, zi in enumerate(z.infolist()):
            if zi.is_dir():
                continue
            if zi.flag_bits & 0x1:
                yield zi.filename, None, _zip_data(zi), "криптиран член на ZIP"
                continue
            if zi.file_size > cfg["maks_razmer_bytes"]:
                yield zi.filename, None, _zip_data(zi), "над тавана за размер"
                continue
            cel = os.path.join(d, "%d%s" % (n, os.path.splitext(zi.filename)[1][:16]))
            try:
                with z.open(zi) as s:
                    _izvadi(s, cel, cfg["maks_razmer_bytes"], _rok(cfg))
            except Neyasno as e:
                yield zi.filename, None, _zip_data(zi), str(e)
                continue
            except (zipfile.BadZipFile, OSError, EOFError, NotImplementedError, RuntimeError) as e:
                yield zi.filename, None, _zip_data(zi), "повреден член на ZIP: %s" % e
                continue
            try:
                yield zi.filename, cel, _zip_data(zi), None
            finally:
                with contextlib.suppress(OSError):
                    os.remove(cel)


def _prikacheni(m):
    for n, part in enumerate(m.iter_attachments(), 1):
        yield "%d_%s" % (n, _bezopasno(part.get_filename())), part


def _deca_eml(pat, cfg):
    m = _pismo(pat, cfg)
    with tempfile.TemporaryDirectory(prefix="sito-eml-") as d:
        for ime, part in _prikacheni(m):
            try:
                danni = part.get_payload(decode=True)
            except Exception as e:
                yield ime, None, None, "прикаченото не се декодира: %s" % e
                continue
            if danni is None:  # вложено писмо (message/rfc822)
                try:
                    danni = part.get_content().as_bytes()
                except Exception as e:
                    yield ime, None, None, "вложеното писмо не се декодира: %s" % e
                    continue
                if not ime.lower().endswith(".eml"):
                    ime += ".eml"
            if len(danni) > cfg["maks_razmer_bytes"]:
                yield ime, None, None, "над тавана за размер"
                continue
            cel = os.path.join(d, "%s" % re.sub(r"[^\w.-]", "_", ime)[-100:])
            with open(cel, "wb") as out:
                out.write(danni)
            try:
                yield ime, cel, None, None
            finally:
                with contextlib.suppress(OSError):
                    os.remove(cel)


@contextlib.contextmanager
def otvori(koren, put, cfg):
    """Истински път до файл, дори когато е вътре в ZIP или .eml. За вложените — временен файл."""
    chasti = put.split(RAZDELITEL)
    tekusht = os.path.join(koren, chasti[0])
    with contextlib.ExitStack() as st:
        for i, ime in enumerate(chasti[1:], 1):
            vid = config.vid_po_ime(cfg, chasti[i - 1])
            gen = deca(tekusht, vid, cfg)
            st.callback(gen.close)
            for dete, pat, _, prichina in gen:
                if dete == ime:
                    if prichina:
                        raise Neyasno(prichina)
                    # детето трябва да оживее извън генератора: копие във собствена временна папка
                    d = st.enter_context(tempfile.TemporaryDirectory(prefix="sito-v-"))
                    cel = os.path.join(d, "f" + os.path.splitext(pat)[1])
                    shutil.copyfile(pat, cel)
                    tekusht = cel
                    break
            else:
                raise Neyasno("няма „%s“ в контейнера" % ime)
        yield tekusht
