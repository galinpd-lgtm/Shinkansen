"""Дърво на HTML страницата с точните места в изходния текст — само с html.parser.

Всеки елемент помни къде започва и свършва отварящият и затварящият му таг в суровия текст.
Така поправките пипат само отделни парчета, а всичко останало остава байт за байт същото.
"""
import re
from html.parser import HTMLParser

PRAZNI = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
          "source", "track", "wbr"}


class El:
    __slots__ = ("tag", "attrs", "start", "otv_kraj", "zatv", "kraj", "deca", "roditel",
                 "implicitno")

    def __init__(self, tag, attrs, start, otv_kraj, roditel):
        self.tag = tag
        self.attrs = attrs
        self.start = start          # „<“ на отварящия таг
        self.otv_kraj = otv_kraj    # след „>“ на отварящия таг
        self.zatv = None            # „<“ на затварящия таг (None — не е затворен)
        self.kraj = None            # след „>“ на затварящия таг
        self.deca = []              # El или str (текст, вече с разкодирани &…;)
        self.roditel = roditel
        self.implicitno = False     # затворен от чужд затварящ таг, не от своя

    def klasove(self):
        return set((self.attrs.get("class") or "").split())

    def elementi(self):
        return [d for d in self.deca if isinstance(d, El)]

    def predci(self):
        r = self.roditel
        while r is not None:
            yield r
            r = r.roditel

    def obhod(self):
        """Самият елемент и всички под него, по реда в документа."""
        yield self
        for d in self.deca:
            if isinstance(d, El):
                yield from d.obhod()

    def zdrav(self):
        """Затворен със собствения си таг, както и всичко вътре."""
        for e in self.obhod():
            if e.kraj is None or e.implicitno:
                return False
        return True

    def __repr__(self):
        return "<%s %s @%d>" % (self.tag, self.attrs.get("class", ""), self.start)


class Dokument:
    def __init__(self, html, koren, nezatvoreni, visyashti):
        self.html = html
        self.koren = koren
        self.nezatvoreni = nezatvoreni   # елементи без затварящ таг до края
        self.visyashti = visyashti       # затварящи тагове без отварящ: [(таг, място)]

    def vsichki(self):
        for d in self.koren.deca:
            if isinstance(d, El):
                yield from d.obhod()

    def parvi(self, tag):
        for e in self.vsichki():
            if e.tag == tag:
                return e
        return None


class _Parser(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.html = html
        self.redove = [0] + [m.end() for m in re.finditer("\n", html)]
        self.koren = El("#dokument", {}, 0, 0, None)
        self.stek = [self.koren]
        self.visyashti = []

    def _myasto(self):
        red, kol = self.getpos()
        return self.redove[red - 1] + kol

    def _nov(self, tag, attrs):
        start = self._myasto()
        suro = self.get_starttag_text() or ""
        a = {}
        for k, v in attrs:
            a.setdefault(k, v if v is not None else "")
        el = El(tag, a, start, start + len(suro), self.stek[-1])
        self.stek[-1].deca.append(el)
        return el

    def handle_starttag(self, tag, attrs):
        el = self._nov(tag, attrs)
        if tag in PRAZNI:
            el.zatv = el.kraj = el.otv_kraj
        else:
            self.stek.append(el)

    def handle_startendtag(self, tag, attrs):
        el = self._nov(tag, attrs)
        el.zatv = el.kraj = el.otv_kraj

    def handle_endtag(self, tag):
        start = self._myasto()
        kraj = self.html.find(">", start)
        kraj = len(self.html) if kraj < 0 else kraj + 1
        for i in range(len(self.stek) - 1, 0, -1):
            if self.stek[i].tag == tag:
                for vatre in self.stek[i + 1:]:
                    vatre.zatv = vatre.kraj = start
                    vatre.implicitno = True
                el = self.stek[i]
                el.zatv, el.kraj = start, kraj
                del self.stek[i:]
                return
        if tag not in PRAZNI:
            self.visyashti.append((tag, start))

    def handle_data(self, data):
        self.stek[-1].deca.append(data)


def razbor(html):
    p = _Parser(html)
    p.feed(html)
    p.close()
    nezatvoreni = p.stek[1:]
    return Dokument(html, p.koren, nezatvoreni, p.visyashti)


def tekst(el, propusni=None, samo_bg=False, bg_klas="bg-only", en_klas="en-only"):
    """Текстът под елемента на парчета. propusni(el) → True пропуска поддървото."""
    chasti = []

    def _tr(e):
        for d in e.deca:
            if isinstance(d, str):
                chasti.append(d)
            elif propusni and propusni(d):
                continue
            elif samo_bg and en_klas in d.klasove():
                continue
            else:
                _tr(d)
    _tr(el)
    return chasti


def vatre_v(el, uslovie):
    """Самият елемент или някой от предците му отговаря на условието."""
    if uslovie(el):
        return True
    return any(uslovie(p) for p in el.predci())
