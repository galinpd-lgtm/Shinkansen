"""HTML → чист текст, поточно, със стандартния html.parser.

Преди парсера минават две сита, също поточни:
  1. вградените data:…;base64,… (картинки, шрифтове) се махат още докато текат;
  2. цели елементи от config (script, style, svg, nav, …) и коментарите се махат, без да се пазят в паметта.
Така и файл от 1 GB, който е почти само скриптове и base64, минава с памет от няколко мегабайта.
"""
import codecs
import re
from html.parser import HTMLParser

_DATA_URI = re.compile(r"data:[\w.+/-]{0,100}(?:;[\w.+=-]{1,100}){0,5};base64,", re.I)
_KRAY_DATA = re.compile(r"[\"'()\s<>\\]")
_BASE64 = re.compile(r"[A-Za-z0-9+/=_-]{120,}")
_CHARSET = re.compile(rb"""charset\s*=\s*["']?([\w.:-]{2,40})""", re.I)

BLOKOVI = {"p", "div", "section", "article", "main", "header", "footer", "aside", "ul", "ol", "table", "tr",
           "blockquote", "pre", "figure", "figcaption", "form", "fieldset", "dl", "dt", "dd", "address", "hr",
           "body", "html", "details", "summary", "caption", "thead", "tbody", "tfoot"}


class _BezData:
    """Сито 1: маха data:…;base64,… поточно. Оставя „data:,“ на мястото им."""
    OPASHKA = 800

    def __init__(self):
        self.buf, self.vatre = "", False

    def feed(self, s):
        self.buf += s
        out = []
        while True:
            if self.vatre:
                m = _KRAY_DATA.search(self.buf)
                if not m:
                    self.buf = ""
                    break
                self.buf, self.vatre = self.buf[m.start():], False
                continue
            m = _DATA_URI.search(self.buf)
            if m:
                out.append(self.buf[:m.start()] + "data:,")
                self.buf, self.vatre = self.buf[m.end():], True
                continue
            if len(self.buf) > self.OPASHKA:
                out.append(self.buf[:-self.OPASHKA])
                self.buf = self.buf[-self.OPASHKA:]
            break
        return "".join(out)

    def close(self):
        b, self.buf = ("" if self.vatre else self.buf), ""
        return b


class _BezElementi:
    """Сито 2: маха цели елементи (script, style, …) и коментарите, поточно. На мястото им — интервал."""
    OPASHKA = 32
    MAKS_TAG = 1 << 20

    def __init__(self, elementi):
        self.otvaryasht = re.compile(r"<(?:(!--)|(%s)(?=[\s/>]))" % "|".join(map(re.escape, elementi)), re.I)
        self.buf, self.krai, self.tag = "", None, None

    def feed(self, s):
        self.buf += s
        out = []
        while True:
            if self.tag:  # чакаме края на отварящия таг, за да видим дали е <x … />
                gt = self.buf.find(">")
                if gt < 0:
                    if len(self.buf) > self.MAKS_TAG:
                        self.buf, self.tag = "", None
                    break
                if gt > 0 and self.buf[gt - 1] == "/":
                    self.buf, self.tag = self.buf[gt + 1:], None
                    continue
                self.krai = re.compile(r"</%s\s*>" % re.escape(self.tag), re.I)
                self.buf, self.tag = self.buf[gt + 1:], None
                continue
            if self.krai:
                m = self.krai.search(self.buf)
                if not m:
                    self.buf = self.buf[-self.OPASHKA:]
                    break
                self.buf, self.krai = self.buf[m.end():], None
                continue
            m = self.otvaryasht.search(self.buf)
            if m:
                out.append(self.buf[:m.start()] + " ")
                if m.group(1):
                    self.krai = re.compile("-->")
                    self.buf = self.buf[m.end():]
                else:
                    self.tag = m.group(2).lower()
                    self.buf = self.buf[m.end():]
                continue
            if len(self.buf) > self.OPASHKA:
                out.append(self.buf[:-self.OPASHKA])
                self.buf = self.buf[-self.OPASHKA:]
            break
        return "".join(out)

    def close(self):
        b, self.buf = ("" if (self.krai or self.tag) else self.buf), ""
        return b


class _Tekst(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.izhod = []
        self.v_glava = False
        self.v_zaglavie = False
        self.zaglavie = []
        self.pre = 0

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.v_glava = True
        elif tag == "body":
            self.v_glava = False
        elif tag == "title":
            self.v_zaglavie = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.izhod.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.izhod.append("\n- ")
        elif tag == "br":
            self.izhod.append("\n")
        elif tag in ("td", "th"):
            self.izhod.append(" ")
        elif tag == "pre":
            self.pre += 1
            self.izhod.append("\n\n")
        elif tag in BLOKOVI:
            self.izhod.append("\n\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.izhod.append("\n")

    def handle_endtag(self, tag):
        if tag == "head":
            self.v_glava = False
        elif tag == "title":
            self.v_zaglavie = False
            z = " ".join("".join(self.zaglavie).split())
            if z:
                self.izhod.append("# %s\n\n" % z)
            self.zaglavie = []
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self.izhod.append("\n")
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self.izhod.append("\n\n")
        elif tag in BLOKOVI:
            self.izhod.append("\n\n")

    def handle_data(self, data):
        if self.v_zaglavie:
            self.zaglavie.append(data)
            return
        if self.v_glava:
            return
        data = _BASE64.sub(" ", data)
        if self.pre:
            self.izhod.append(data)
            return
        sabrano = " ".join(data.split())
        if not sabrano:
            if data:
                self.izhod.append(" ")
            return
        self.izhod.append((" " if data[0].isspace() else "") + sabrano + (" " if data[-1].isspace() else ""))

    def vzemi(self):
        v, self.izhod = "".join(self.izhod), []
        return v


def kodirovka(nachalo):
    """Кодировката от BOM или от charset в първите байтове; иначе UTF-8."""
    if nachalo.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if nachalo.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    m = _CHARSET.search(nachalo)
    if m:
        try:
            return codecs.lookup(m.group(1).decode("ascii")).name
        except LookupError:
            pass
    return "utf-8"


def tekst_ot_potok(blokove, elementi, proveri=None):
    """Поток от байтове → поток от текст (сурови парчета, за tekst.redove)."""
    dek, nachalo = None, b""
    s1, s2, p = _BezData(), _BezElementi(elementi), _Tekst()
    for b in blokove:
        if proveri:
            proveri()
        if dek is None:  # кодировката се решава по първите 4 KB, колкото и малки да са блоковете
            nachalo += b
            if len(nachalo) < 4096:
                continue
            dek = codecs.getincrementaldecoder(kodirovka(nachalo[:4096]))(errors="replace")
            b, nachalo = nachalo, b""
        p.feed(s2.feed(s1.feed(dek.decode(b))))
        v = p.vzemi()
        if v:
            yield v
    if dek is None:
        dek = codecs.getincrementaldecoder(kodirovka(nachalo[:4096]))(errors="replace")
        p.feed(s2.feed(s1.feed(dek.decode(nachalo))))
    p.feed(s2.feed(s1.feed(dek.decode(b"", final=True))))
    p.feed(s2.feed(s1.close()))
    p.feed(s2.close())
    p.close()
    v = p.vzemi()
    if v:
        yield v
