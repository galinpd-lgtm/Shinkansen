"""Топлинна врата: преди всяко викане на модела пита GET <gate_url>.

Заето е, когато вратата отговори с 503/429, с текст „busy“/„hot“ или с JSON, в който
state/status е „busy“/„hot“ или busy е true.

Вратата никога не се заобикаля. Моделът не се вика и изходът е 4 („не е безопасно сега, опитай по-късно“) и когато:
вратата не отговаря или отговорът е неразбираем, и когато няма зададен gate_url.
"""
import json
import urllib.error
import urllib.request

ZAETO = {"busy", "hot", "zaeto", "заето", "горещо"}


class VrataNeBezopasno(Exception):
    """Не е безопасно да се вика моделът сега — без викане, изход 4. Нищо не се губи."""


class VrataZaeta(VrataNeBezopasno):
    """Машината е заета или гореща."""


class VrataGreshka(VrataNeBezopasno):
    """Вратата не отговаря или отговорът е неразбираем."""


class VrataLipsva(VrataNeBezopasno):
    """Няма зададен gate_url — без врата моделът не се вика."""


def http_get(url, timeout):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace") if e.fp else ""


def e_zaeto(status, tyalo):
    if status in (429, 503):
        return True
    if status != 200:
        raise VrataGreshka("вратата върна код %d" % status)
    t = (tyalo or "").strip()
    try:
        d = json.loads(t)
    except ValueError:
        return t.lower() in ZAETO
    if isinstance(d, dict):
        if d.get("busy") is True:
            return True
        return str(d.get("state", d.get("status", ""))).lower() in ZAETO
    return str(d).lower() in ZAETO


class Vrata:
    def __init__(self, url, get=None, timeout=5):
        self.url, self.timeout = url, timeout
        self._get = get or (lambda *a: http_get(*a))
        self.pitaniya = 0

    def proveri(self):
        """Вдига VrataZaeta, VrataGreshka или VrataLipsva; иначе връща нищо."""
        if not self.url:
            raise VrataLipsva("няма зададен gate_url — без топлинна врата моделът не се вика "
                              "(задай gate_url в конфигурацията или ползвай --bez-model)")
        self.pitaniya += 1
        try:
            status, tyalo = self._get(self.url, self.timeout)
        except VrataGreshka:
            raise
        except Exception as e:  # мрежа, таймаут, отказ
            raise VrataGreshka("вратата не отговаря: %s" % e)
        if e_zaeto(status, tyalo):
            raise VrataZaeta("машината е заета или гореща — моделът не е викан")
