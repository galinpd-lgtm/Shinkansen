"""Мрежата: учтива и проследима.

- User-Agent `oditor/<версия> (+<адрес на методологията>)` — с име и адрес, никога браузърски и никога чужд.
- Пауза между заявките към един хост (`pauza_na_hosta_s`); паузата между сайтовете е в cli.
- Пренасочванията се следват ръчно, стъпка по стъпка — всяка се записва като доказателство.
- 401/403/429/503 се връщат като отговор, не като грешка: това е защита, не повреда. Нищо не се заобикаля.
- Всяка заявка става запис: адрес, код, заглавки, SHA-256, размер, час по UTC и тялото (до `maks_tyalo_bytes`).

Транспортът е подменяем: тестовете подават речник с отговори и не излизат в мрежата.
"""
import hashlib
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import VERSIYA

PRENASOCHVANIYA = (301, 302, 303, 307, 308)


def user_agent(cfg):
    return "%s/%s (+%s)" % (cfg["user_agent_ime"], VERSIYA, cfg["kontakt"])


class _BezPrenasochvane(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def urllib_transport(url, ua, timeout, maks):
    """→ (код, заглавки, bytes). Мрежова грешка → OSError; изтекло време → TimeoutError."""
    opener = urllib.request.build_opener(_BezPrenasochvane)
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "text/html, text/plain;q=0.9, */*;q=0.5"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers.items()), r.read(maks)
    except urllib.error.HTTPError as e:
        try:
            tyalo = e.read(maks)
        except Exception:
            tyalo = b""
        return e.code, dict((e.headers or {}).items()), tyalo
    except socket.timeout as e:
        raise TimeoutError(str(e))


def host(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def sega_utc():
    return datetime.now(timezone.utc)


def _charset(ct):
    for chast in (ct or "").split(";")[1:]:
        k, _, v = chast.partition("=")
        if k.strip().lower() == "charset" and v.strip():
            return v.strip().strip('"')
    return None


def dekodirai(tyalo, ct):
    try:
        return tyalo.decode(_charset(ct) or "utf-8", "replace")
    except LookupError:
        return tyalo.decode("utf-8", "replace")


class Mrezha:
    def __init__(self, cfg, transport=None, chasovnik=time.monotonic, spi=time.sleep, sega=sega_utc, ua=None):
        self.cfg = cfg
        self.ua = ua or user_agent(cfg)
        self.transport = transport or urllib_transport
        self.chasovnik, self.spi, self.sega = chasovnik, spi, sega
        self.posledna = {}
        self.broy = 0

    def _izchakay(self, h):
        pauza = float(self.cfg["pauza_na_hosta_s"])
        if h in self.posledna:
            ostava = self.posledna[h] + pauza - self.chasovnik()
            if ostava > 0:
                self.spi(ostava)
        self.posledna[h] = self.chasovnik()

    def vzemi(self, url, ua=None):
        """Една заявка, без пренасочвания → запис (dict)."""
        self._izchakay(host(url))
        self.broy += 1
        t = self.sega().isoformat(timespec="seconds").replace("+00:00", "Z")
        z = {"url": url, "t": t, "status": None, "greshka": None, "zaglavki": {}, "sha256": None, "razmer": 0,
             "tyalo": ""}
        if ua:
            z["ua"] = ua
        try:
            status, zagl, tyalo = self.transport(url, ua or self.ua, self.cfg["taymaut_s"], self.cfg["maks_tyalo_bytes"])
            tyalo = tyalo or b""
            z["status"] = status
            z["zaglavki"] = {k.lower(): v for k, v in (zagl or {}).items()}
            z["sha256"] = hashlib.sha256(tyalo).hexdigest()
            z["razmer"] = len(tyalo)
            z["tyalo"] = dekodirai(tyalo, z["zaglavki"].get("content-type"))
        except TimeoutError as e:
            z["greshka"] = "изтекло време: %s" % e
        except (OSError, ValueError) as e:
            z["greshka"] = "%s: %s" % (type(e).__name__, e)
        return z

    def sledvai(self, url, pozvoleno=None, ua=None):
        """Следва пренасочванията → списък от записи (последният е крайният).
        `pozvoleno(url)` се пита преди всяка стъпка; при „не“ веригата спира с грешка „robots“."""
        veriga = []
        for _ in range(int(self.cfg["maks_prenasochvaniya"]) + 1):
            if pozvoleno is not None and not pozvoleno(url):
                veriga.append({"url": url, "t": self.sega().isoformat(timespec="seconds").replace("+00:00", "Z"),
                               "status": None, "greshka": "robots: не е позволено", "zaglavki": {},
                               "sha256": None, "razmer": 0, "tyalo": ""})
                return veriga
            z = self.vzemi(url, ua=ua)
            veriga.append(z)
            if z["greshka"] or z["status"] not in PRENASOCHVANIYA or not z["zaglavki"].get("location"):
                return veriga
            url = urllib.parse.urljoin(url, z["zaglavki"]["location"])
        veriga[-1]["greshka"] = "твърде много пренасочвания"
        return veriga
