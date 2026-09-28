"""Общо за тестовете: измислени файлове, създадени по време на теста. Нула мрежа, нула истински документи.

Никъде не се вика LibreOffice или друга имитация на Office.

По подразбиране външните инструменти са „скрити“ (instrumenti.nameri → None), за да не зависи присъдата
от машината. Тестовете за pdftotext, tesseract и antiword/catdoc ги ползват истински и се пропускат без тях.
"""
import base64
import contextlib
import hashlib
import io
import json
import os
import random
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
CFG_PRIMER = os.path.join(APP, "config.example.json")
sys.path.insert(0, APP)

from sito import cli  # noqa: E402

SEGA = "2026-09-28T08:00:00Z"
STARO = 1735689600  # 2025-01-01 — далеч от прага за „жив“
ROLYA = "собственик на архива"

ABZAC = ("Сито отделя смисъла от въздуха. Документите не се местят, преди целият им текст да е в базата. "
         "Всеки абзац тук е измислен и служи само за изпитване на машината, без истински хора и фирми. ")


def dumi(n, sid=1):
    r = random.Random(sid)
    rechnik = ("смисъл въздух текст база абзац документ папка машина човек решение карта отчет парче ред "
               "дума страница архив писмо слайд бележка").split()
    return " ".join(r.choice(rechnik) for _ in range(n))


# ─────────── измислените файлове ───────────

def golyam_html(pat, abzatsi=40, css_kb=1500, js_kb=2000, b64_kb=2500):
    """HTML, който е почти само опаковка: CSS, JS и вградени base64 картинки около малко текст."""
    r = random.Random(7)
    css = "".join(".k%d{color:#%06x;margin:%dpx}\n" % (i, r.randrange(1 << 24), i % 40) for i in range(css_kb * 40))
    js = "".join("function f%d(a){return a*%d+\"<p>не е текст</p>\";}\n" % (i, i) for i in range(js_kb * 22))
    b64 = base64.b64encode(r.randbytes(b64_kb * 1024 * 3 // 4)).decode()
    chast = len(b64) // 3
    with open(pat, "w", encoding="utf-8") as f:
        f.write("<!doctype html><html lang=bg><head><meta charset=utf-8><title>Въздух под налягане</title>")
        f.write("<style>%s .bg{background:url(data:image/png;base64,%s)}</style>" % (css[:len(css) // 2], b64[:chast]))
        f.write("<script>%s</script></head>" % js[:len(js) // 2])
        f.write("<body><nav><a href=/>Начало</a><a href=/x>Меню</a></nav>")
        f.write("<h1>Отчет за въздуха</h1>")
        for i in range(abzatsi):
            f.write("<p>%d. %s</p>\n" % (i, ABZAC))
            if i == abzatsi // 2:
                f.write('<img alt="" src="data:image/jpeg;base64,%s">' % b64[chast:2 * chast])
                f.write("<!-- коментар <script> който не бива да обърква -->")
                f.write("<svg viewBox='0 0 10 10'><text>не е текст</text></svg>")
        f.write("<style>%s</style><script>%s</script>" % (css[len(css) // 2:], js[len(js) // 2:]))
        f.write('<link rel=icon href="data:image/x-icon;base64,%s"></body></html>' % b64[2 * chast:])


def docx(pat, abzatsi, zaglavie=None):
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = []
    if zaglavie:
        body.append('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>%s</w:t></w:r></w:p>' % zaglavie)
    for a in abzatsi:
        body.append('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r><w:r><w:tab/><w:t>край</w:t></w:r></w:p>' % a)
    doc = '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (
        W, "".join(body))
    with zipfile.ZipFile(pat, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/'
                   'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml", doc)


def pptx(pat, slaydove, snimka_kb=600):
    """slaydove: [(заглавие, [редове], бележки или None)]. С „картинка“ вътре — за да е опаковка."""
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    P = "http://schemas.openxmlformats.org/presentationml/2006/main"
    R = "http://schemas.openxmlformats.org/package/2006/relationships"

    def sp(redove):
        return "".join('<p:sp><p:txBody>%s</p:txBody></p:sp>' % "".join(
            "<a:p><a:r><a:t>%s</a:t></a:r></a:p>" % r for r in redove) for _ in [0])

    with zipfile.ZipFile(pat, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        for i, (zag, redove, belezhki) in enumerate(slaydove, 1):
            z.writestr("ppt/slides/slide%d.xml" % i,
                       '<?xml version="1.0"?><p:sld xmlns:p="%s" xmlns:a="%s"><p:cSld><p:spTree>%s</p:spTree>'
                       '</p:cSld></p:sld>' % (P, A, sp([zag] + redove)))
            if belezhki:
                z.writestr("ppt/slides/_rels/slide%d.xml.rels" % i,
                           '<?xml version="1.0"?><Relationships xmlns="%s"><Relationship Id="rId2" Type="http://'
                           'schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../'
                           'notesSlides/notesSlide%d.xml"/></Relationships>' % (R, 10 + i))
                z.writestr("ppt/notesSlides/notesSlide%d.xml" % (10 + i),
                           '<?xml version="1.0"?><p:notes xmlns:p="%s" xmlns:a="%s"><p:cSld><p:spTree>%s%s'
                           '</p:spTree></p:cSld></p:notes>' % (P, A, sp([belezhki]), sp([str(i)])))
        z.writestr("ppt/media/image1.png", random.Random(3).randbytes(snimka_kb * 1024), zipfile.ZIP_STORED)


def pdf(pat, redove=("Sito test PDF text layer",), podpis=False):
    """Малък, но истински PDF с текстов слой (Helvetica). podpis=True добавя поле за електронен подпис."""
    potok = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join("(%s) '" % r for r in redove) + " ET"
    obekti = [
        "<< /Type /Catalog /Pages 2 0 R%s >>" % (" /AcroForm << /Fields [6 0 R] /SigFlags 3 >>" if podpis else ""),
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        "<< /Length %d >>\nstream\n%s\nendstream" % (len(potok), potok),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    if podpis:
        obekti += ["<< /FT /Sig /T (Podpis1) /V 7 0 R >>",
                   "<< /Type /Sig /Filter /Adobe.PPKLite /ByteRange [0 0 0 0] /Contents <00> >>"]
    b = io.BytesIO()
    b.write(b"%PDF-1.4\n")
    pozicii = []
    for i, o in enumerate(obekti, 1):
        pozicii.append(b.tell())
        b.write(("%d 0 obj\n%s\nendobj\n" % (i, o)).encode("latin-1"))
    xref = b.tell()
    b.write(("xref\n0 %d\n0000000000 65535 f \n" % (len(obekti) + 1)).encode())
    for p in pozicii:
        b.write(("%010d 00000 n \n" % p).encode())
    b.write(("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(obekti) + 1, xref)).encode())
    with open(pat, "wb") as f:
        f.write(b.getvalue())


def skaniran_pdf(pat, redove):
    """PDF само от картинка (без текстов слой): текстов PDF → pdftoppm → сиви пиксели → PDF с картинка.
    Иска pdftoppm; тестът, който го ползва, се пропуска без него."""
    import subprocess
    import zlib
    with tempfile.TemporaryDirectory() as d:
        pdf(os.path.join(d, "t.pdf"), redove)
        subprocess.run(["pdftoppm", "-gray", "-r", "150", "-singlefile", os.path.join(d, "t.pdf"),
                        os.path.join(d, "s")], check=True)
        with open(os.path.join(d, "s.pgm"), "rb") as f:
            danni = f.read()
    zag = danni.split(b"\n", 3)  # P5 / ширина височина / 255 / пиксели
    shir, vis = map(int, zag[1].split())
    piks = zlib.compress(zag[3])
    potok = b"q %d 0 0 %d 0 0 cm /Im1 Do Q" % (612, 792)
    obekti = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
              b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
              b"/Resources << /XObject << /Im1 5 0 R >> >> >>",
              b"<< /Length %d >>\nstream\n%s\nendstream" % (len(potok), potok),
              b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
              b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n%s\nendstream"
              % (shir, vis, len(piks), piks)]
    b = io.BytesIO()
    b.write(b"%PDF-1.4\n")
    pozicii = []
    for i, o in enumerate(obekti, 1):
        pozicii.append(b.tell())
        b.write(b"%d 0 obj\n%s\nendobj\n" % (i, o))
    xref = b.tell()
    b.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(obekti) + 1))
    for p in pozicii:
        b.write(b"%010d 00000 n \n" % p)
    b.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(obekti) + 1, xref))
    with open(pat, "wb") as f:
        f.write(b.getvalue())


def rtf(pat, abzatsi, kartinka_kb=0):
    """RTF с таблица на шрифтовете, cp1251 (\\'hh), \\uN и по желание вградена картинка (\\pict)."""
    def kod(t):
        out = []
        for ch in t:
            b = ch.encode("cp1251", "strict") if ch not in "\\{}" else None
            if ch in "\\{}":
                out.append("\\" + ch)
            elif b[0] < 128:
                out.append(ch)
            else:
                out.append("\\'%02x" % b[0])
        return "".join(out)
    tyalo = "".join("{\\pard %s\\par}\n" % kod(a) for a in abzatsi)
    kartinka = ""
    if kartinka_kb:
        heks = random.Random(11).randbytes(kartinka_kb * 1024).hex()
        kartinka = "{\\pict\\pngblip " + "\n".join(heks[i:i + 128] for i in range(0, len(heks), 128)) + "}"
    with open(pat, "w", encoding="ascii") as f:
        f.write("{\\rtf1\\ansi\\ansicpg1251\\deff0{\\fonttbl{\\f0 Times New Roman;}}"
                "{\\colortbl;\\red0\\green0\\blue0;}{\\*\\generator %s;}\n" % kod("Измислен"))
        f.write("{\\info{\\title %s}}\n" % kod("Скрито заглавие"))
        f.write(tyalo)
        f.write("{\\pard \\u1057?\\u1080?\\u1090?\\u1086? \\uc0\\u8212 \\par}\n")
        f.write(kartinka + "}")


def svyat(koren):
    """Основният измислен свят: всички видове в обхвата, дубликат, „договор“, извън обхвата, чист текст, архив."""
    for d in ("kopiya", "rabotni", "sabrano", "__MACOSX"):
        os.makedirs(os.path.join(koren, d))
    golyam_html(os.path.join(koren, "golyam.html"))
    shutil.copyfile(os.path.join(koren, "golyam.html"), os.path.join(koren, "kopiya", "golyam.html"))
    docx(os.path.join(koren, "belezhki.docx"), [ABZAC, dumi(2000, 2)], zaglavie="Бележки от срещата")
    docx(os.path.join(koren, "dogovor.docx"),
         ["ДОГОВОР за изпитване", "Днес страните по договора — Примерна фирма ЕООД, ЕИК 000000000, "
          "представлявана от управителя, и изпълнителят — се споразумяха.", "Подпис: ______  Печат: ______"])
    pptx(os.path.join(koren, "prezentaciya.pptx"),
         [("Въздух под налягане", ["1 GB опаковка", "22 KB смисъл"], "Бележка на говорителя: кажи числата."),
          ("Второ", ["без бележки"], None)])
    pdf(os.path.join(koren, "podpisan.pdf"), ("Signed test document with a text layer long enough",) * 3,
        podpis=True)
    rtf(os.path.join(koren, "pismo.rtf"), ["Писмо в RTF: " + ABZAC, "Втори абзац {с къдрави скоби}."],
        kartinka_kb=64)
    with open(os.path.join(koren, "star.doc"), "wb") as f:  # OLE заглавка без истински Word — за „неясно“
        f.write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(504))
    with open(os.path.join(koren, "rabotni", "plan.docx"), "wb") as f:
        b = io.BytesIO()
        docx(b, ["Жив план: " + dumi(50, 3)])
        f.write(b.getvalue())
    b = io.BytesIO()
    docx(b, ["Документ в архив: " + dumi(30, 4)])
    with zipfile.ZipFile(os.path.join(koren, "sabrano", "arhiv.zip"), "w") as z:
        z.writestr("vatre/v_arhiv.docx", b.getvalue())
    with open(os.path.join(koren, "sabrano", "stari.7z"), "wb") as f:
        f.write(b"7z\xbc\xaf\x27\x1c" + bytes(64))
    with open(os.path.join(koren, "belezhka.md"), "w", encoding="utf-8") as f:
        f.write("# Бележка\n\nТук споменаваме договора с ЕИК 000000000 и фактура — но това е само бележка.\n")
    with open(os.path.join(koren, "spisak.txt"), "w", encoding="utf-8") as f:
        f.write("Списък: " + dumi(40, 5) + "\n")
    with open(os.path.join(koren, "snimka.jpg"), "wb") as f:
        f.write(random.Random(9).randbytes(2048))
    with open(os.path.join(koren, "tablica.xlsx"), "wb") as f:
        f.write(b"PK\x03\x04" + random.Random(12).randbytes(1024))
    with open(os.path.join(koren, "danni.json"), "w", encoding="utf-8") as f:
        json.dump({"dogovor": "договор", "eik": "ЕИК 000000000"}, f, ensure_ascii=False)
    with open(os.path.join(koren, "zapis.mp3"), "wb") as f:
        f.write(random.Random(10).randbytes(4096))
    with open(os.path.join(koren, "neshto.xyz"), "wb") as f:
        f.write(b"?")
    for ime in (".DS_Store", "._golyam.html", "._dogovor.docx"):  # следи от macOS — пропускат се наистина
        with open(os.path.join(koren, ime), "wb") as f:
            f.write(b"\0\5\x16\7" + bytes(60))
    with open(os.path.join(koren, "__MACOSX", "._podpisan.pdf"), "wb") as f:
        f.write(b"\0\5\x16\7")
    staro(koren)


def staro(koren):
    for d, _, fl in os.walk(koren):
        for x in fl:
            os.utime(os.path.join(d, x), (STARO, STARO))


def hashove(koren):
    """Отпечатък на цялата папка: път → (SHA-256, размер, mtime). Празни папки също."""
    r = {}
    for d, papki, fl in os.walk(koren):
        for p in papki:
            r[os.path.relpath(os.path.join(d, p), koren) + "/"] = None
        for x in fl:
            pat = os.path.join(d, x)
            with open(pat, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest()
            st = os.stat(pat)
            r[os.path.relpath(pat, koren)] = (h, st.st_size, st.st_mtime_ns)
    return r


def baytove(pat):
    with open(pat, "rb") as f:
        return f.read()


# ─────────── пускане ───────────

def hod(*argv, cfg=None):
    out, err = io.StringIO(), io.StringIO()
    a = list(argv)
    if cfg:
        a += ["--config", cfg]
    a += ["--sega", SEGA]
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        kod = cli.main(a)
    return kod, out.getvalue(), err.getvalue()


class Papka:
    """Временна папка: src/ (изходната, само за четене), karta.json, izhod/ и config за теста."""

    def __init__(self, svyat_=True, **promeni):
        self.promeni = promeni
        self.svyat_ = svyat_

    def __enter__(self):
        self.d = tempfile.mkdtemp(prefix="sito-test-")
        self.src = os.path.join(self.d, "src")
        os.makedirs(self.src)
        self.karta = os.path.join(self.d, "karta.json")
        self.izhod = os.path.join(self.d, "izhod")
        with open(CFG_PRIMER, encoding="utf-8") as f:
            c = json.load(f)
        c.update(self.promeni)
        self.cfg = os.path.join(self.d, "config.json")
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
        if self.svyat_:
            svyat(self.src)
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.d, ignore_errors=True)

    def hod(self, *argv):
        return hod(*argv, cfg=self.cfg)

    def skanirai(self):
        kod, out, err = self.hod("skanirai", self.src, "--izhod", self.karta)
        assert kod == 0, err
        return self.k()

    def vidyah(self, *idta, rolya=ROLYA):
        kod, out, err = self.hod("vidyah", self.karta, *idta, "--ot", rolya)
        assert kod == 0, err
        return out

    def vidyah_vsichki(self, prisada=None):
        """Човекът е видял всички файлове (или само от присъдата) — по id, един по един."""
        idta = [z["id"] for z in self.k()["faylove"]
                if z["prisada"] not in ("dublikat", "neyasno", "izvan_obhvat", "chist_tekst", "arhiv")
                and (prisada is None or z["prisada"] == prisada)]
        return self.vidyah(*idta) if idta else ""

    def k(self):
        with open(self.karta, encoding="utf-8") as f:
            return json.load(f)

    def po_put(self, put):
        for z in self.k()["faylove"]:
            if z["put"] == put:
                return z
        raise KeyError(put)
