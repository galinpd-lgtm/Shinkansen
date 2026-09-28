"""Мрежата: учтива и проследима.

- Идентифициращ User-Agent `izvori/<версия>` с адрес за връзка; никога браузърски.
- Най-много една заявка на домейн на `pauza_na_domeyn_s` секунди (по подразбиране 6).
- Пренасочванията се следват ръчно, стъпка по стъпка, за да се види всяка и да се пита robots за всеки хост.
- 401/403 се връщат като отговор, не като грешка: това е защита, не повреда на източника. Нищо не се заобикаля.
- Всяка заявка се записва (адрес, код, заглавки, SHA-256, час по UTC, откъс до maks_glava_bytes) за доказателствата.

Транспортът е подменяем: тестовете подават речник с отговори и не излизат в мрежата.
"""
import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import VERSIYA

PRENASOCHVANIYA = (301, 302, 303, 307, 308)


def user_agent(cfg):
    ua = "%s/%s" % (cfg["user_agent_ime"], VERSIYA)
    return "%s (+%s)" % (ua, cfg["kontakt"]) if cfg.get("kontakt") else ua


class _BezPrenasochvane(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def urllib_transport(url, ua, timeout, maks):
    """→ (код, заглавки {малки букви: стойност}, bytes). Мрежова грешка → OSError."""
    opener = urllib.request.build_opener(_BezPrenasochvane)
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "text/html, application/xhtml+xml, "
                                                                          "application/rss+xml, application/atom+xml, "
                                                                          "application/xml;q=0.9, */*;q=0.5"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(maks)
    except urllib.error.HTTPError as e:
        try:
            tyalo = e.read(maks)
        except Exception:
            tyalo = b""
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, tyalo


def host(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def sega_utc():
    return datetime.now(timezone.utc)


class Otgovor:
    def __init__(self, url, status=None, zaglavki=None, tyalo=b"", greshka=None, t=None):
        self.url, self.status, self.zaglavki, self.tyalo, self.greshka, self.t = \
            url, status, zaglavki or {}, tyalo, greshka, t

    @property
    def ok(self):
        return self.greshka is None and self.status == 200

    def content_type(self):
        return self.zaglavki.get("content-type", "").split(";")[0].strip().lower()

    def charset(self):
        for chast in self.zaglavki.get("content-type", "").split(";")[1:]:
            k, _, v = chast.partition("=")
            if k.strip().lower() == "charset" and v.strip():
                return v.strip().strip('"')
        return None

    def tekst(self):
        try:
            return self.tyalo.decode(self.charset() or "utf-8", "replace")
        except LookupError:
            return self.tyalo.decode("utf-8", "replace")


class Mrezha:
    def __init__(self, cfg, transport=None, chasovnik=time.monotonic, spi=time.sleep, sega=sega_utc):
        self.cfg = cfg
        self.ua = user_agent(cfg)
        self.transport = transport or urllib_transport
        self.chasovnik, self.spi, self.sega = chasovnik, spi, sega
        self.posledna = {}   # хост → кога е последната заявка към него
        self.zayavki = []    # всичко видяно в този ход — за доказателствата

    def _izchakay(self, h):
        pauza = float(self.cfg["pauza_na_domeyn_s"])
        if h in self.posledna:
            ostava = self.posledna[h] + pauza - self.chasovnik()
            if ostava > 0:
                self.spi(ostava)
        self.posledna[h] = self.chasovnik()

    def vzemi(self, url):
        """Една заявка, без пренасочвания."""
        self._izchakay(host(url))
        t = self.sega().isoformat(timespec="seconds")
        try:
            status, zagl, tyalo = self.transport(url, self.ua, self.cfg["taymaut_s"], self.cfg["maks_tyalo_bytes"])
            o = Otgovor(url, status, {k.lower(): v for k, v in zagl.items()}, tyalo or b"", t=t)
        except (OSError, ValueError) as e:
            o = Otgovor(url, greshka="%s: %s" % (type(e).__name__, e), t=t)
        self._zapishi(o)
        return o

    def sledvai(self, url, pozvoleno=None):
        """Следва пренасочванията → списък от отговори (последният е крайният).
        `pozvoleno(url)` се пита преди всяка стъпка; при „не“ веригата спира с греshка „robots“."""
        verigi = []
        for _ in range(int(self.cfg["maks_prenasochvaniya"]) + 1):
            if pozvoleno is not None and not pozvoleno(url):
                verigi.append(Otgovor(url, greshka="robots: не е позволено", t=self.sega().isoformat(timespec="seconds")))
                return verigi
            o = self.vzemi(url)
            verigi.append(o)
            if o.greshka or o.status not in PRENASOCHVANIYA or not o.zaglavki.get("location"):
                return verigi
            url = urllib.parse.urljoin(url, o.zaglavki["location"])
        verigi[-1].greshka = "твърде много пренасочвания"
        return verigi

    def _zapishi(self, o):
        z = {"url": o.url, "t": o.t, "status": o.status, "greshka": o.greshka,
             "zaglavki": o.zaglavki, "sha256": hashlib.sha256(o.tyalo).hexdigest() if o.greshka is None else None,
             "razmer": len(o.tyalo)}
        if o.tyalo:
            z["otkas"] = otkas(o.tyalo, self.cfg["maks_glava_bytes"])
        self.zayavki.append(z)


def otkas(tyalo, maks):
    """До `maks` байта: от <head> нататък, ако има такъв, иначе от началото."""
    i = tyalo[:200_000].lower().find(b"<head")
    parche = tyalo[i if i >= 0 else 0:][:maks]
    return parche.decode("utf-8", "replace")
