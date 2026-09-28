"""RTF → текст, поточно, само със стандартната библиотека.

Малък четец: групи, контролни думи, \\'hh според \\ansicpgN, \\uN с \\ucN. Пропуска цели групи, които не са
текст на документа (шрифтове, цветове, стилове, картинки, вградени обекти, скрити полета). Не е пълен RTF —
целта е текстът, не видът.
"""
import codecs
import re

_TOKEN = re.compile(rb"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([^\\{}\r\n]+)|[\r\n]+",
                    re.S)
PROPUSKAY = {b"fonttbl", b"colortbl", b"stylesheet", b"info", b"pict", b"object", b"themedata", b"datastore",
             b"xmlnstbl", b"listtable", b"listoverridetable", b"rsidtbl", b"generator", b"latentstyles",
             b"fldinst", b"header", b"footer", b"headerl", b"headerr", b"footerl", b"footerr", b"filetbl",
             b"revtbl", b"pgdsctbl", b"mmathPr", b"colorschememapping", b"bkmkstart", b"bkmkend"}
REDOVE = {b"par": "\n", b"line": "\n", b"row": "\n", b"sect": "\n\n", b"page": "\n\n", b"tab": "\t",
          b"cell": " ", b"emdash": "\u2014", b"endash": "\u2013", b"bullet": "\u2022", b"lquote": "\u2018",
          b"rquote": "\u2019", b"ldblquote": "\u201c", b"rdblquote": "\u201d", b"~": "\u00a0"}


ZAPAS = 64  # най-дългият токен: \\ + 32 букви + 11 знака число + интервал


class _Chetec:
    def __init__(self):
        self.kod = "cp1252"
        self.steka = []            # (пропусни, uc) за всяка отворена група
        self.propusni, self.uc = False, 1
        self.za_propuskane = 0     # знаци след \uN, които са заместител
        self.baytove = bytearray()  # поредица от \'hh, декодира се наведнъж
        self.nachalo_na_grupa = False
        self.izhod = []

    def _baytove_navan(self):
        if self.baytove:
            if not self.propusni:
                self.izhod.append(bytes(self.baytove).decode(self.kod, "replace"))
            self.baytove.clear()

    def token(self, m):
        duma, chislo, heks, simvol, skoba, tekst = m.groups()
        if heks is not None:
            if self.za_propuskane:
                self.za_propuskane -= 1
            else:
                self.baytove.append(int(heks, 16))
            self.nachalo_na_grupa = False
            return
        self._baytove_navan()
        if skoba == b"{":
            self.steka.append((self.propusni, self.uc))
            self.nachalo_na_grupa = True
            return
        if skoba == b"}":
            if self.steka:
                self.propusni, self.uc = self.steka.pop()
            self.nachalo_na_grupa = False
            return
        if simvol is not None:
            if simvol == b"*" and self.nachalo_na_grupa:
                self.propusni = True  # \* — непозната дестинация
            elif not self.propusni and simvol in (b"\\", b"{", b"}"):
                self.izhod.append(simvol.decode())
            elif not self.propusni and simvol == b"~":
                self.izhod.append("\u00a0")
            elif not self.propusni and simvol in (b"\n", b"\r"):
                self.izhod.append("\n")  # „\“ + нов ред е \par
            self.nachalo_na_grupa = False
            return
        if duma is not None:
            if self.nachalo_na_grupa and duma in PROPUSKAY:
                self.propusni = True
            self.nachalo_na_grupa = False
            if duma == b"ansicpg" and chislo:
                try:
                    self.kod = codecs.lookup("cp%d" % int(chislo)).name
                except LookupError:
                    pass
            elif duma == b"uc" and chislo:
                self.uc = int(chislo)
            elif duma == b"u" and chislo:
                n = int(chislo)
                if not self.propusni:
                    self.izhod.append(chr(n + 65536 if n < 0 else n))
                self.za_propuskane = self.uc
            elif duma in REDOVE and not self.propusni:
                self.izhod.append(REDOVE[duma])
            return
        if tekst is not None:
            self.nachalo_na_grupa = False
            if self.za_propuskane:
                n = min(self.za_propuskane, len(tekst))
                self.za_propuskane -= n
                tekst = tekst[n:]
            if tekst and not self.propusni:
                self.izhod.append(tekst.decode(self.kod, "replace"))

    def vzemi(self):
        v, self.izhod = "".join(self.izhod), []
        return v


def tekst_ot_potok(blokove, proveri=None):
    """Поток от байтове → поток от текст. Краят на блока (до ZAPAS байта) чака следващия блок: там токенът
    може да е недовършен (напр. \\' без двете шестнайсетични цифри)."""
    ch, buf = _Chetec(), b""
    for b in blokove:
        if proveri:
            proveri()
        buf += b
        pos, granica = 0, len(buf) - ZAPAS
        for m in _TOKEN.finditer(buf):
            if m.end() > granica:
                break
            ch.token(m)
            pos = m.end()
        buf = buf[pos:]
        v = ch.vzemi()
        if v:
            yield v
    for m in _TOKEN.finditer(buf):
        ch.token(m)
    ch._baytove_navan()
    v = ch.vzemi()
    if v:
        yield v


def e_rtf(nachalo):
    return nachalo.lstrip()[:5] == b"{\\rtf"
