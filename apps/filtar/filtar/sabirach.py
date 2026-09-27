"""Събирачът: rss · atom (и windows-1251) · html (само заглавие и описание) · ruchno (JSON в vhod/).

Учтив е: собствен User-Agent, спазва fetch_interval на източника и robots.txt, таймаут, не обхожда сайтове
(тегли само адреса на емисията или страницата), не заобикаля платени стени. Пише само новото.

Авторско право: източник, който е отказал машинно извличане (robots.txt, TDM-Reservation — заглавка,
/.well-known/tdmrep.json или meta, — `noai` в X-Robots-Tag или meta robots), не се събира.
Всяко копие (емисията и всеки запис) получава SHA-256 и дата на изтегляне в дневника. Пълните текстове
остават само във вътрешната база — за одит и спорове, никога на публичен адрес.
"""
import email.utils
import fnmatch
import glob
import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from . import baza
from .dov import normalizirai, ot_html

NS_ATOM = "{http://www.w3.org/2005/Atom}"
NS_CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
PREMAHNI = re.compile(r"^(utm_.*|fbclid)$", re.IGNORECASE)


class GreshkaIzvor(Exception):
    pass


class OtkazanIzvor(GreshkaIzvor):
    """Източникът е отказал машинно извличане — не се събира. Не е повреда."""


# ─────────── адреси ───────────

def kanon(url):
    """Каноничен адрес: без utm_*, fbclid и #; малки букви в схемата и хоста; без порта по подразбиране."""
    try:
        p = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.hostname:
        return None
    host = p.hostname.lower()
    if p.port and not ((p.scheme == "http" and p.port == 80) or (p.scheme == "https" and p.port == 443)):
        host += ":%d" % p.port
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not PREMAHNI.match(k)]
    return urllib.parse.urlunsplit((p.scheme.lower(), host, p.path or "/", urllib.parse.urlencode(q), ""))


def url_hash(url):
    k = kanon(url)
    return hashlib.sha256(k.encode("utf-8")).hexdigest() if k else None


def domain(url):
    try:
        h = urllib.parse.urlsplit(url or "").hostname or ""
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


# ─────────── мрежа ───────────

def http_get(url, ua, timeout):
    """→ (status, content_type, charset, заглавки {малки букви: стойност}, bytes). Мрежовите грешки се вдигат."""
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/rss+xml, application/atom+xml, "
                                                                          "application/xml, text/xml, text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            zagl = {k.lower(): v for k, v in r.headers.items()}
            return r.status, r.headers.get_content_type(), r.headers.get_content_charset(), zagl, r.read(5_000_000)
    except urllib.error.HTTPError as e:
        return e.code, "", None, {}, b""


def robots_pozvolyava(url, ua, get, timeout):
    """robots.txt на хоста: 404 или липса → позволено; грешка при четене → не теглим (учтиво)."""
    p = urllib.parse.urlsplit(url)
    robots = "%s://%s/robots.txt" % (p.scheme, p.netloc)
    try:
        status, _, charset, _, tyalo = get(robots, ua, timeout)
    except Exception:
        return False
    if status in (404, 410):
        return True
    if status != 200:
        return False
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(tyalo.decode(charset or "utf-8", "replace").splitlines())
    return rp.can_fetch(ua, url)


def tdm_rezervaciya(url, ua, get, timeout):
    """TDM Reservation Protocol: /.well-known/tdmrep.json с правило за пътя и tdm-reservation 1 → отказано.
    Липсващ файл → няма резервация. Неразбираем файл → няма резервация (заглавките и meta се проверяват отделно)."""
    p = urllib.parse.urlsplit(url)
    try:
        status, _, charset, _, tyalo = get("%s://%s/.well-known/tdmrep.json" % (p.scheme, p.netloc), ua, timeout)
    except Exception:
        return False
    if status != 200:
        return False
    try:
        pravila = json.loads(tyalo.decode(charset or "utf-8", "replace"))
    except ValueError:
        return False
    for pr in pravila if isinstance(pravila, list) else []:
        if isinstance(pr, dict) and fnmatch.fnmatch(p.path or "/", pr.get("location", "")) \
                and str(pr.get("tdm-reservation")) == "1":
            return True
    return False


_META_TAGOVE = re.compile(r"<meta\s+[^>]*>", re.IGNORECASE)


def otkaz_ot_izvlichane(zagl, tyalo, charset):
    """Причина за отказ от машинно извличане в заглавките или в meta таговете — или None."""
    if str(zagl.get("tdm-reservation", "")).strip() == "1":
        return "заглавка TDM-Reservation: 1"
    if "noai" in zagl.get("x-robots-tag", "").lower():
        return "заглавка X-Robots-Tag: noai"
    glava = tyalo[:200_000].decode(charset or "utf-8", "replace")
    for tag in _META_TAGOVE.findall(glava):
        a = {k.lower(): v[1:-1] for k, v in _ATTR.findall(tag)}
        ime, sad = (a.get("name") or "").lower(), (a.get("content") or "").lower()
        if ime == "tdm-reservation" and sad.strip() == "1":
            return "meta tdm-reservation"
        if ime in ("robots", "kagami-filtar") and ("noai" in sad or "noimageai" in sad):
            return "meta robots: noai"
    return None


def sha256(b):
    return hashlib.sha256(b).hexdigest()


# ─────────── разбор ───────────

def _xml(tyalo, charset):
    """ElementTree чете кодировката от XML декларацията (и windows-1251). Без декларация — от заглавката."""
    if charset and not tyalo.lstrip().startswith(b"<?xml"):
        tyalo = tyalo.decode(charset, "replace").encode("utf-8")
    try:
        return ET.fromstring(tyalo)
    except ET.ParseError as e:
        raise GreshkaIzvor("неразбираем XML: %s" % e)


def _t(el):
    return normalizirai("".join(el.itertext())) if el is not None else ""


def _data(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.isoformat(timespec="seconds")


def razberi_rss(koren):
    kanal = koren.find("channel")
    if kanal is None:
        raise GreshkaIzvor("не е RSS (няма channel)")
    for it in kanal.findall("item"):
        sadarzhanie = it.find(NS_CONTENT + "encoded")
        html_ = sadarzhanie.text if sadarzhanie is not None and sadarzhanie.text else (it.findtext("description") or "")
        link = (it.findtext("link") or "").strip()
        yield {"guid": (it.findtext("guid") or link).strip(), "url": link, "zaglavie": normalizirai(it.findtext("title")),
               "tekst": ot_html(html_), "data": _data(it.findtext("pubDate"))}


def razberi_atom(koren):
    if koren.tag != NS_ATOM + "feed":
        raise GreshkaIzvor("не е Atom (няма feed)")
    for e in koren.findall(NS_ATOM + "entry"):
        link = ""
        for l in e.findall(NS_ATOM + "link"):
            if l.get("rel", "alternate") == "alternate":
                link = l.get("href", "")
                break
        sad = e.find(NS_ATOM + "content")
        if sad is None:
            sad = e.find(NS_ATOM + "summary")
        tekst = ot_html(sad.text or "") if sad is not None and sad.get("type") in ("html", "xhtml") else _t(sad)
        yield {"guid": (e.findtext(NS_ATOM + "id") or link).strip(), "url": link,
               "zaglavie": _t(e.find(NS_ATOM + "title")), "tekst": tekst,
               "data": _data(e.findtext(NS_ATOM + "published") or e.findtext(NS_ATOM + "updated"))}


_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META = re.compile(r"<meta\s+[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"""(\w[\w:-]*)\s*=\s*("[^"]*"|'[^']*')""")


def razberi_html(url, tyalo, charset):
    """Само заглавие и описание от страницата — без обхождане на връзките."""
    h = tyalo.decode(charset or "utf-8", "replace")
    m = _TITLE.search(h)
    zaglavie = ot_html(m.group(1)) if m else ""
    opisanie, data = "", None
    for tag in _META.findall(h):
        a = {k.lower(): v[1:-1] for k, v in _ATTR.findall(tag)}
        ime = (a.get("name") or a.get("property") or "").lower()
        if ime in ("description", "og:description") and not opisanie:
            opisanie = ot_html(a.get("content", ""))
        if ime in ("article:published_time", "date") and not data:
            data = _data(a.get("content"))
    yield {"guid": url, "url": url, "zaglavie": zaglavie, "tekst": opisanie, "data": data}


# ─────────── ход ───────────

def _zapishi(b, izv, z, sega, status, tip):
    kluch = "%s|%s" % (izv["id"], z.get("guid") or z.get("url") or z.get("zaglavie"))
    if b.execute("SELECT 1 FROM zapisi WHERE kluch=?", (kluch,)).fetchone():
        return False
    vreme = sega.isoformat(timespec="seconds")
    h = sha256(("%s\n%s" % (z.get("zaglavie") or "", z.get("tekst") or "")).encode("utf-8"))
    cur = b.execute("INSERT INTO zapisi (izvor, izvor_ime, izvor_vid, izvor_url, ezik, kluch, url, url_kanon, url_hash, "
                    "zaglavie, tekst, data, sabrano, http_status, tip, sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (izv["id"], izv.get("ime"), izv.get("vid"), izv.get("url"), izv.get("ezik"), kluch,
                     z.get("url"), kanon(z.get("url")), url_hash(z.get("url")), z.get("zaglavie"), z.get("tekst"),
                     z.get("data"), vreme, status, tip, h))
    baza.log(b, vreme, 0, "КОПИЕ", "sha256=%s · изтеглено %s" % (h, vreme), cur.lastrowid, izv["id"])
    return True


def _tip(content_type, tip_izvor):
    ct = (content_type or "").lower()
    if "html" in ct:
        return "html"
    if "atom" in ct:
        return "atom"
    if "rss" in ct:
        return "rss"
    if "xml" in ct:
        return "xml"
    return ct or tip_izvor


def sabiray_izvor(b, izv, cfg, sega, get):
    """→ (брой нови, състояние). Вдига GreshkaIzvor при неуспех."""
    ua, timeout = cfg["user_agent"], cfg.get("taymaut_s", 30)
    if not robots_pozvolyava(izv["url"], ua, get, timeout):
        raise OtkazanIzvor("robots.txt не позволява или не се чете")
    if tdm_rezervaciya(izv["url"], ua, get, timeout):
        raise OtkazanIzvor("tdmrep.json: машинното извличане е резервирано")
    try:
        status, ct, charset, zagl, tyalo = get(izv["url"], ua, timeout)
    except Exception as e:
        raise GreshkaIzvor("не отговаря: %s" % e)
    if status != 200:
        raise GreshkaIzvor("отговор %d" % status)
    otkaz = otkaz_ot_izvlichane(zagl, tyalo, charset)
    if otkaz:
        raise OtkazanIzvor(otkaz)
    vreme = sega.isoformat(timespec="seconds")
    baza.log(b, vreme, 0, "КОПИЕ", "емисия sha256=%s · изтеглено %s" % (sha256(tyalo), vreme), None, izv["id"])
    tip = _tip(ct, izv["tip"])
    if izv["tip"] == "html":
        zapisi = razberi_html(izv["url"], tyalo, charset)
    else:
        koren = _xml(tyalo, charset)
        zapisi = razberi_atom(koren) if koren.tag == NS_ATOM + "feed" else razberi_rss(koren)
    novi = sum(1 for z in list(zapisi) if _zapishi(b, izv, z, sega, status, tip))
    return novi


def vreme_e(b, izv, cfg, sega):
    r = b.execute("SELECT posleden_opit FROM izvori WHERE id=?", (izv["id"],)).fetchone()
    if not r or not r["posleden_opit"]:
        return True
    interval = izv.get("fetch_interval_min", cfg.get("fetch_interval_min", 15))
    return sega - datetime.fromisoformat(r["posleden_opit"]) >= timedelta(minutes=interval)


def sabiray_ruchno(b, papka, sega):
    """JSON файловете в vhod/ → записи; прочетеният файл отива в vhod/obraboteni/. → (нови, грешки)."""
    novi, greshki = 0, []
    for p in sorted(glob.glob(os.path.join(papka, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            izv = d["izvor"]
            if not izv.get("ime"):
                raise KeyError("izvor.ime")
            iid = "ruchno:" + (izv.get("id") or izv["ime"])
            info = {"id": iid, "ime": izv["ime"], "vid": izv.get("vid", "neizvesten"), "url": izv.get("url"),
                    "ezik": izv.get("ezik", "bg")}
            baza.izvor(b, iid, info["ime"], info["vid"])
            for z in d["zapisi"]:
                novi += _zapishi(b, info, {"guid": z.get("url") or z.get("zaglavie"), "url": z.get("url"),
                                           "zaglavie": normalizirai(z.get("zaglavie")),
                                           "tekst": normalizirai(z.get("tekst")), "data": _data(z.get("data"))},
                                 sega, None, "ruchno")
        except (OSError, ValueError, KeyError, TypeError) as e:
            greshki.append("%s: %s" % (os.path.basename(p), e))
            continue
        cel = os.path.join(papka, "obraboteni")
        os.makedirs(cel, exist_ok=True)
        shutil.move(p, os.path.join(cel, os.path.basename(p)))
    return novi, greshki


def sabiray(b, cfg, izvori, sega, get=None, vhod=None):
    """Един ход. → {"novi", "izvori": [(id, състояние)], "greshki": [...], "propusnati": брой}."""
    get = get or http_get
    otchet = {"novi": 0, "izvori": [], "greshki": [], "otkazani": [], "propusnati": 0}
    for izv in izvori:
        baza.izvor(b, izv["id"], izv["ime"], izv["vid"], cfg["sloy5"]["nachalna"])
        if not vreme_e(b, izv, cfg, sega):
            otchet["propusnati"] += 1
            continue
        try:
            n = sabiray_izvor(b, izv, cfg, sega, get)
            sast = "наред · нови %d" % n
            otchet["novi"] += n
        except OtkazanIzvor as e:
            sast = "отказано извличане: %s" % e
            otchet["otkazani"].append("%s: %s" % (izv["id"], e))
            baza.log(b, sega.isoformat(timespec="seconds"), 0, "НЕ СЕ СЪБИРА", sast, None, izv["id"])
        except GreshkaIzvor as e:
            sast = "грешка: %s" % e
            otchet["greshki"].append("%s: %s" % (izv["id"], e))
        b.execute("UPDATE izvori SET posleden_opit=?, posledno_sastoyanie=? WHERE id=?",
                  (sega.isoformat(timespec="seconds"), sast, izv["id"]))
        otchet["izvori"].append((izv["id"], sast))
    if vhod and os.path.isdir(vhod):
        n, gr = sabiray_ruchno(b, vhod, sega)
        otchet["novi"] += n
        otchet["greshki"] += ["vhod/" + g for g in gr]
    b.commit()
    return otchet
