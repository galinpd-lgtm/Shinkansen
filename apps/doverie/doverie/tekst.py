"""Общи помощни функции върху текст: изречения, думи, нормализиране, извличане от HTML."""
import html.parser
import re

_IZR = re.compile(r"[^.!?…]+(?:[.!?…]+[»“\"')]*|$)")
_DUMA = re.compile(r"\w+", re.UNICODE)


def normalizirai(t):
    return re.sub(r"\s+", " ", (t or "")).strip()


def izrecheniya(t):
    t = normalizirai(t)
    return [s.strip() for s in _IZR.findall(t) if s.strip()]


def dumi(t):
    return _DUMA.findall((t or "").lower())


def izrechenie_okolo(t, poz):
    """Изречението, в което попада позиция poz от нормализирания текст t."""
    nachalo = max(t.rfind(z, 0, poz) for z in ".!?…") + 1
    kraj_kandidati = [i for i in (t.find(z, poz) for z in ".!?…") if i != -1]
    kraj = (min(kraj_kandidati) + 1) if kraj_kandidati else len(t)
    return t[nachalo:kraj].strip()


def ima_otkas(tekst, otkas):
    """Истина, ако откъсът е дословно в текста (след нормализиране на интервалите)."""
    o = normalizirai(otkas)
    return bool(o) and o in normalizirai(tekst)


class _Izvlichach(html.parser.HTMLParser):
    PROPUSNI = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form"}
    BLOKOVI = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "br", "div", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chasti, self._skrito = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.PROPUSNI:
            self._skrito += 1
        elif tag in self.BLOKOVI:
            self.chasti.append("\n")

    def handle_endtag(self, tag):
        if tag in self.PROPUSNI and self._skrito:
            self._skrito -= 1
        elif tag in self.BLOKOVI:
            self.chasti.append("\n")

    def handle_data(self, data):
        if not self._skrito:
            self.chasti.append(data)


def ot_html(h):
    p = _Izvlichach()
    p.feed(h)
    redove = [normalizirai(r) for r in "".join(p.chasti).split("\n")]
    return "\n".join(r for r in redove if r)
