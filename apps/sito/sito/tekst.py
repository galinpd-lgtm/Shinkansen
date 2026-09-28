"""Общото за текста: заглавката на MD, подреждане на редовете (поточно) и парчетата за базата (chunks)."""
import json
import re

from . import VERSIYA

_INTERVALI = re.compile(r"[ \t\u00a0\u200b]+")
_PRAZNI = re.compile(r"^[-#*|>\s]*$")


def glava(z, t):
    """Източникът най-горе в MD: път (относителен), SHA-256, дата. Същата функция дава и очаквания размер."""
    r = ["---",
         "istochnik: %s" % json.dumps(z["put"], ensure_ascii=False),
         "sha256: %s" % z["sha256"],
         "data: %s" % (z.get("promenen") or "—"),
         "vid: %s" % z["vid"],
         "preobrazuvano: %s" % t,
         "sito: %s" % VERSIYA]
    if z.get("proveri"):
        r.append("proveri: %s" % json.dumps(z["proveri"], ensure_ascii=False))
    return "\n".join(r + ["---", "", ""])


class Redove:
    """Поток от парчета текст → чисти редове. Най-много един празен ред между абзаците, без празни в началото.

    Държи в паметта само недовършения ред — никога целия текст.
    """

    def __init__(self):
        self.opashka = ""
        self.nachalo = True   # в началото празните редове се махат
        self.chaka = False    # празен ред, който се пуска само ако след него дойде текст

    def feed(self, parche):
        self.opashka += parche
        if "\n" not in self.opashka:
            if len(self.opashka) < 1 << 20:
                return
            parche, self.opashka = self.opashka, ""  # безкраен ред без нов ред: режем го на 1 MB
            yield from self._red(parche)
            return
        *redove, self.opashka = self.opashka.split("\n")
        for r in redove:
            yield from self._red(r)

    def close(self):
        if self.opashka:
            r, self.opashka = self.opashka, ""
            yield from self._red(r)

    def _red(self, r):
        r = _INTERVALI.sub(" ", r).strip()
        if _PRAZNI.match(r):
            self.chaka = not self.nachalo
            return
        if self.chaka:
            yield "\n"
        self.nachalo = self.chaka = False
        yield r + "\n"


def redove(parcheta):
    """Генератор от парчета → генератор от чисти редове."""
    rd = Redove()
    for p in parcheta:
        yield from rd.feed(p)
    yield from rd.close()


class Parcheta:
    """Редове → парчета от около n думи. Режем на граница на ред; ред, по-дълъг от n думи, се реже по думи."""

    def __init__(self, n):
        self.n = n
        self.redove, self.dumi, self.ot = [], 0, 0

    def feed(self, red):
        d = red.split()
        if not d:
            if self.redove:
                self.redove.append("")
            return
        if len(d) <= self.n:
            if self.dumi + len(d) > self.n:
                yield self._izpusni()
            self.redove.append(red.rstrip("\n"))
            self.dumi += len(d)
            if self.dumi >= self.n:
                yield self._izpusni()
            return
        while d:  # ред, по-дълъг от едно парче: доплъва текущото и се реже по думи
            mesto = self.n - self.dumi
            self.redove.append(" ".join(d[:mesto]))
            self.dumi += len(d[:mesto])
            d = d[mesto:]
            if self.dumi >= self.n:
                yield self._izpusni()

    def close(self):
        if self.dumi:
            yield self._izpusni()

    def _izpusni(self):
        tekst = "\n".join(self.redove).strip()
        p = (tekst, self.ot, self.ot + self.dumi)
        self.ot += self.dumi
        self.redove, self.dumi = [], 0
        return p
