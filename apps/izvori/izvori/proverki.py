"""Седемте проверки при `validirai`. Всяка дава резултат „да“ / „не“ / „неясно“, бележка и какво е видяно.

Проверките описват, не решават: `validiran` значи само, че машината не е намерила пречка. Пречка е
„не“ за официален домейн или за жив и HTTPS — и **непрочетена страница** (защита 401/403, robots, 429 или
друг код без тяло): каквото машината не е видяла, не е валидирано. Всичко останало (липсваща емисия, TDM
резервация, неясен език или вид) се записва за човека, който одобрява.
"""
import fnmatch
import json
import re
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from html.parser import HTMLParser

from . import config
from .mrezha import host

DA, NE, NEYASNO = "да", "не", "неясно"
NS_ATOM = "{http://www.w3.org/2005/Atom}"
TIPOVE_EMISIYA = ("application/rss+xml", "application/atom+xml")
KIRILICA = re.compile(r"[\u0400-\u04FF]")
LATINICA = re.compile(r"[A-Za-z\u00C0-\u024F]")
PRECHKI = ("domeyn", "zhiv")
ZASHTITA = "защита — нужна ръчна проверка или друг канал"
NEPROCHETENA = "страницата не е прочетена — нужна ръчна проверка или друг канал"


def _r(rezultat, belezhka="", **kw):
    return dict(rezultat=rezultat, belezhka=belezhka, **kw)


# ─────────── разбор на HTML (само стандартната библиотека) ───────────

class Stranica(HTMLParser):
    """lang на <html>, <link rel=alternate>, <meta>, адресите на <a> и видимият текст (за брояча на азбуката)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang, self.emisii, self.meta, self.vrazki, self.tekst = None, [], {}, [], []
        self._skrit = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"].strip()
        elif tag == "link" and "alternate" in a.get("rel", "").lower().split() \
                and a.get("type", "").lower() in TIPOVE_EMISIYA and a.get("href"):
            self.emisii.append((a["href"].strip(), a["type"].lower()))
        elif tag == "meta":
            ime = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if ime:
                self.meta.setdefault(ime, a.get("content", ""))
        elif tag == "a" and a.get("href"):
            self.vrazki.append(a["href"].strip())
        if tag in ("script", "style", "noscript", "template"):
            self._skrit += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self._skrit:
            self._skrit -= 1

    def handle_data(self, data):
        if not self._skrit and len(self.tekst) < 5000:
            self.tekst.append(data)


def razberi(otg):
    s = Stranica()
    try:
        s.feed(otg.tekst()[:1_000_000])
        s.close()
    except Exception:  # счупен HTML не спира проверката — просто се вижда по-малко
        pass
    return s


def _data(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def emisiya_ot(otg):
    """Разбор на емисия, прочетена веднъж → {"tip", "zapisi", "posleden_zapis", "ezik"} или None, ако не е емисия."""
    try:
        koren = ET.fromstring(otg.tyalo)
    except ET.ParseError:
        return None
    if koren.tag == "rss" or koren.find("channel") is not None:
        kanal = koren.find("channel")
        if kanal is None:
            return None
        dati = [_data(i.findtext("pubDate")) for i in kanal.findall("item")]
        return {"tip": "rss", "zapisi": len(dati), "posleden_zapis": max([d for d in dati if d], default=None),
                "ezik": (kanal.findtext("language") or "").strip() or None}
    if koren.tag == NS_ATOM + "feed":
        dati = [_data(e.findtext(NS_ATOM + "published") or e.findtext(NS_ATOM + "updated"))
                for e in koren.findall(NS_ATOM + "entry")]
        return {"tip": "atom", "zapisi": len(dati), "posleden_zapis": max([d for d in dati if d], default=None),
                "ezik": koren.get("{http://www.w3.org/XML/1998/namespace}lang")}
    return None


# ─────────── robots.txt ───────────

class Robots:
    """robots.txt по хост, прочетен веднъж на ход. RFC 9309: 4xx → всичко позволено; 5xx или няма отговор →
    нищо не се тегли от този хост."""

    def __init__(self, mrezha):
        self.m, self.kesh = mrezha, {}

    def za(self, url):
        p = urllib.parse.urlsplit(url)
        kluch = "%s://%s" % (p.scheme, p.netloc)
        if kluch not in self.kesh:
            o = self.m.sledvai(kluch + "/robots.txt")[-1]
            if o.greshka or o.status >= 500:
                self.kesh[kluch] = {"status": o.status, "dostapen": False, "rp": None,
                                    "belezhka": o.greshka or "robots.txt: код %s" % o.status}
            elif o.status == 200:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(o.tekst().splitlines())
                self.kesh[kluch] = {"status": 200, "dostapen": True, "rp": rp, "belezhka": ""}
            else:
                self.kesh[kluch] = {"status": o.status, "dostapen": True, "rp": None,
                                    "belezhka": "robots.txt: код %s — всичко позволено" % o.status}
        return self.kesh[kluch]

    def pozvoleno(self, url):
        r = self.za(url)
        if not r["dostapen"]:
            return False
        return True if r["rp"] is None else r["rp"].can_fetch(self.m.ua, url)


# ─────────── 1. Официален домейн ───────────

def _na_org(h, org):
    return bool(org) and any(config.na_domeyn(h, d) for d in org["domeyni"])


def domeyn(cfg, zapis, verigi, m, robots):
    org = config.organizaciya(cfg, zapis.get("organizaciya")) if zapis.get("organizaciya") else None
    nachalen, kraen = host(zapis["url"]), host(verigi[-1].url) if verigi else host(zapis["url"])
    if org is None:
        return _r(NEYASNO, "организацията не е в config — няма с какво да се сравни домейнът",
                  host=nachalen, kraen_host=kraen)
    domeyni = org["domeyni"]
    if _na_org(nachalen, org):
        if kraen and not _na_org(kraen, org):
            return _r(NEYASNO, "пренасочване към чужд домейн: %s → %s" % (nachalen, kraen),
                      host=nachalen, kraen_host=kraen, domeyni=domeyni)
        return _r(DA, "адресът е на домейна на организацията", host=nachalen, kraen_host=kraen, domeyni=domeyni)
    # не е на домейна — сочи ли главната страница на организацията към него?
    glavna = org.get("glavna") or "https://%s/" % domeyni[0]
    gv = m.sledvai(glavna, robots.pozvoleno)
    if gv[-1].ok:
        s = razberi(gv[-1])
        for href in s.vrazki:
            if host(urllib.parse.urljoin(gv[-1].url, href)) == nachalen:
                if kraen and kraen != nachalen and not _na_org(kraen, org):
                    return _r(NEYASNO, "главната страница сочи към %s, но той пренасочва към %s" % (nachalen, kraen),
                              host=nachalen, kraen_host=kraen, domeyni=domeyni, glavna=glavna)
                return _r(DA, "главната страница на организацията сочи към %s" % nachalen,
                          host=nachalen, kraen_host=kraen, domeyni=domeyni, glavna=glavna)
    elif gv[-1].greshka or gv[-1].status in (401, 403, 429):
        return _r(NEYASNO, "главната страница не се прочете (%s) — връзката не може да се потвърди"
                  % (gv[-1].greshka or gv[-1].status), host=nachalen, kraen_host=kraen, domeyni=domeyni, glavna=glavna)
    if _na_org(kraen, org):
        return _r(NEYASNO, "адресът пренасочва към домейна на организацията (%s) — впиши крайния адрес" % kraen,
                  host=nachalen, kraen_host=kraen, domeyni=domeyni)
    return _r(NE, "%s не е на домейна на организацията и главната ѝ страница не сочи към него" % nachalen,
              host=nachalen, kraen_host=kraen, domeyni=domeyni, glavna=glavna)


# ─────────── 2. Жив и HTTPS ───────────

def zhiv(zapis, verigi):
    kraen = verigi[-1]
    stapki = [{"url": o.url, "status": o.status} for o in verigi]
    obshto = dict(kraen_url=kraen.url, status=kraen.status, prenasochvaniya=stapki[:-1],
                  posledna_promyana=_data(kraen.zaglavki.get("last-modified")))
    if kraen.greshka and kraen.greshka.startswith("robots"):
        return _r(NEYASNO, "robots.txt не позволява страницата — не е теглена", **obshto)
    if kraen.greshka:
        return _r(NE, "няма отговор: %s" % kraen.greshka, **obshto)
    if kraen.status in (401, 403):
        return _r(NEYASNO, "защита (%d) — не е грешка на източника; нищо не се заобикаля" % kraen.status, **obshto)
    if kraen.status == 429:
        return _r(NEYASNO, "твърде много заявки (429) — опитай по-късно", **obshto)
    if kraen.status in (404, 410) or kraen.status >= 500:
        return _r(NE, "код %d" % kraen.status, **obshto)
    if kraen.status != 200:
        return _r(NEYASNO, "неочакван код %s" % kraen.status, **obshto)
    if urllib.parse.urlsplit(kraen.url).scheme != "https":
        return _r(NE, "крайният адрес не е HTTPS", **obshto)
    if urllib.parse.urlsplit(zapis["url"]).scheme != "https":
        return _r(DA, "отговаря; пренасочва от HTTP към HTTPS — впиши HTTPS адреса", **obshto)
    return _r(DA, "отговаря с 200 по HTTPS", **obshto)


# ─────────── 3. Емисия ───────────

def emisiya(cfg, verigi, m, robots, org=None):
    kraen = verigi[-1]
    if not kraen.ok:
        return _r(NEYASNO, "страницата не е прочетена — емисията не е търсена")
    samata = emisiya_ot(kraen)
    if samata:
        return _r(DA, "адресът сам е емисия", url=kraen.url, nachin="адресът", **samata)
    s = razberi(kraen)
    if s.emisii:
        href, _ = s.emisii[0]
        url = urllib.parse.urljoin(kraen.url, href)
        return _procheti_emisiya(url, "link rel=alternate", m, robots, org, nevalidna_e=NEYASNO)
    p = urllib.parse.urlsplit(kraen.url)
    opitani = []
    for pat in cfg["obichayni_patishta_emisiya"][:4]:
        url = "%s://%s%s" % (p.scheme, p.netloc, pat)
        opitani.append(url)
        r = _procheti_emisiya(url, "обичаен път", m, robots, org, nevalidna_e=None)
        if r:
            return r
    return _r(NE, "няма <link rel=alternate> и нито един от обичайните пътища не е емисия", opitani=opitani)


def _procheti_emisiya(url, nachin, m, robots, org, nevalidna_e):
    v = m.sledvai(url, robots.pozvoleno)
    o = v[-1]
    if not o.ok:
        if nevalidna_e is None:
            return None
        return _r(nevalidna_e, "емисията е обявена, но не се чете (%s)" % (o.greshka or o.status), url=url, nachin=nachin)
    e = emisiya_ot(o)
    if e is None:
        if nevalidna_e is None:
            return None
        return _r(nevalidna_e, "емисията е обявена, но не е валиден RSS/Atom", url=url, nachin=nachin)
    belezhka = "валиден %s, %d записа" % (e["tip"].upper(), e["zapisi"])
    if org and not _na_org(host(o.url), org):
        belezhka += "; емисията е на чужд домейн (%s)" % host(o.url)
    return _r(DA, belezhka, url=o.url, nachin=nachin, **e)


# ─────────── 4. Разрешения ───────────

def razresheniya(cfg, zapis, verigi, m, robots):
    kraen = verigi[-1]
    r = robots.za(kraen.url if not kraen.greshka else zapis["url"])
    pozv = robots.pozvoleno(kraen.url)
    signali = []
    if kraen.greshka is None and kraen.status is not None:
        z = kraen.zaglavki
        if str(z.get("tdm-reservation", "")).strip() == "1":
            signali.append("заглавка tdm-reservation: 1")
        xr = z.get("x-robots-tag", "").lower()
        for d in ("noai", "noimageai"):
            if d in xr:
                signali.append("заглавка X-Robots-Tag: %s" % d)
        if kraen.ok:
            s = razberi(kraen)
            if s.meta.get("tdm-reservation", "").strip() == "1":
                signali.append("meta tdm-reservation: 1")
            for ime in ("robots", cfg["user_agent_ime"]):
                sad = s.meta.get(ime, "").lower()
                for d in ("noai", "noimageai"):
                    if d in sad:
                        signali.append("meta %s: %s" % (ime, d))
    tdmrep = _tdmrep(kraen.url if not kraen.greshka else zapis["url"], m, robots)
    if tdmrep:
        signali.append(tdmrep)
    obshto = dict(robots={"status": r["status"], "pozvoleno": pozv, "belezhka": r["belezhka"]},
                  tdm={"rezervirano": bool(signali), "signali": signali})
    if not r["dostapen"]:
        return _r(NEYASNO, "robots.txt не се чете — нищо не се тегли", pravo="ne_se_izvlicha", **obshto)
    if not pozv:
        return _r(NE, "robots.txt не позволява на %s" % cfg["user_agent_ime"], pravo="ne_se_izvlicha", **obshto)
    if signali:
        return _r(NE, "резервирано право на извличане (TDM): оценка и цитат да, пълно копие не",
                  pravo="samo_ocenka_i_citat", **obshto)
    return _r(DA, "robots позволява; няма TDM резервация", pravo="palno", **obshto)


def _tdmrep(url, m, robots):
    p = urllib.parse.urlsplit(url)
    adres = "%s://%s/.well-known/tdmrep.json" % (p.scheme, p.netloc)
    if not robots.pozvoleno(adres):
        return None
    o = m.vzemi(adres)
    if not o.ok:
        return None
    try:
        pravila = json.loads(o.tekst())
    except ValueError:
        return None
    for pr in pravila if isinstance(pravila, list) else []:
        if isinstance(pr, dict) and fnmatch.fnmatch(p.path or "/", pr.get("location", "")) \
                and str(pr.get("tdm-reservation")) == "1":
            return "/.well-known/tdmrep.json: %s" % pr.get("location")
    return None


# ─────────── 5. Език ───────────

def ezik(cfg, verigi, em):
    kraen = verigi[-1]
    if not kraen.ok:
        return _r(NEYASNO, "страницата не е прочетена")
    if em.get("nachin") == "адресът":
        lang, tekst = em.get("ezik"), kraen.tekst()
        tekst = re.sub(r"<[^>]+>", " ", tekst[:20000])
    else:
        s = razberi(kraen)
        lang, tekst = s.lang, " ".join(s.tekst)
    kir, lat = len(KIRILICA.findall(tekst)), len(LATINICA.findall(tekst))
    vsichko = kir + lat
    azbuka = None if vsichko < 20 else ("кирилица" if kir / vsichko >= 0.5 else "латиница")
    broyach = {"kirilica": kir, "latinica": lat, "azbuka": azbuka}
    kod = (lang or "").split("-")[0].lower() or None
    if kod is None:
        return _r(NEYASNO, "няма lang; преобладава %s" % (azbuka or "—"), lang=None, ezik=None, **broyach)
    ochakvana = "кирилица" if kod in cfg["kirilski_ezici"] else "латиница"
    if azbuka and azbuka != ochakvana:
        return _r(NEYASNO, "lang=%s, но текстът е на %s" % (lang, azbuka), lang=lang, ezik=kod, **broyach)
    return _r(DA, "lang=%s%s" % (lang, ", потвърдено от азбуката" if azbuka else ""), lang=lang, ezik=kod, **broyach)


# ─────────── 6. Вид съдържание ───────────

def vid_sadarzhanie(cfg, verigi):
    kraen = verigi[-1]
    url = kraen.url if not kraen.greshka else verigi[0].url
    segmenti = [s for s in urllib.parse.urlsplit(url).path.lower().split("/") if s]
    meta = razberi(kraen).meta if kraen.ok else {}
    og = meta.get("og:type", "").lower()
    for pr in cfg["vid_sadarzhanie"]:
        for pat in pr.get("patishta", []):
            if any(s == pat or s.startswith(pat + "-") or s.startswith(pat + ".") for s in segmenti):
                return _r(DA, "%s (по пътя: /%s)" % (pr["ime"], pat), vid=pr["vid"], ime=pr["ime"])
    for pr in cfg["vid_sadarzhanie"]:
        for m in pr.get("meta", []):
            if og == m or m in meta:
                return _r(DA, "%s (по мета: %s)" % (pr["ime"], m), vid=pr["vid"], ime=pr["ime"])
    return _r(NEYASNO, "нито пътят, нито мета съвпадат с правило от config", vid=None)


# ─────────── 7. Ешелон ───────────

def eshelon(cfg, zapis, dom):
    """От вида. Машината никога не вдига ешелон: взима по-ниския от вида и записания."""
    ot_vida = config.eshelon(cfg, zapis["vid"])
    e = config.po_nisak(ot_vida, zapis.get("eshelon"))
    ime = cfg["eshelon_imena"].get(e, e)
    if e == "parvichen" and dom["rezultat"] != DA:
        return _r(NEYASNO, "%s по вид — но само при потвърден официален домейн" % ime, eshelon=e)
    return _r(DA, "%s (по вид „%s“)" % (ime, cfg["vidove"][zapis["vid"]].get("ime", zapis["vid"])), eshelon=e)


# ─────────── всичко заедно ───────────

def validirai(cfg, zapis, m):
    """→ (проверки, пречки). Мрежата `m` записва всяка заявка в m.zayavki."""
    robots = Robots(m)
    verigi = m.sledvai(zapis["url"], robots.pozvoleno)
    org = config.organizaciya(cfg, zapis.get("organizaciya")) if zapis.get("organizaciya") else None
    p = {}
    p["domeyn"] = domeyn(cfg, zapis, verigi, m, robots)
    p["zhiv"] = zhiv(zapis, verigi)
    p["emisiya"] = emisiya(cfg, verigi, m, robots, org)
    p["razresheniya"] = razresheniya(cfg, zapis, verigi, m, robots)
    p["ezik"] = ezik(cfg, verigi, p["emisiya"])
    p["vid_sadarzhanie"] = vid_sadarzhanie(cfg, verigi)
    p["eshelon"] = eshelon(cfg, zapis, p["domeyn"])
    prechki = ["%s: %s" % (IMENA[k], p[k]["belezhka"]) for k in PRECHKI if p[k]["rezultat"] == NE]
    kraen = verigi[-1]
    if not kraen.ok and p["zhiv"]["rezultat"] != NE:
        # каквото не е прочетено, не е валидирано: остава кандидат, дори домейнът да е потвърден
        p["zhiv"]["neprochetena"] = True
        prechki.append("%s: %s" % (IMENA["zhiv"], ZASHTITA if kraen.status in (401, 403) else NEPROCHETENA))
    return p, prechki


IMENA = {"domeyn": "официален домейн", "zhiv": "жив и HTTPS", "emisiya": "емисия", "razresheniya": "разрешения",
         "ezik": "език", "vid_sadarzhanie": "вид съдържание", "eshelon": "ешелон"}


def sravni(predishni, novi):
    """Повторна проверка на одобрен източник: какво се е влошило спрямо предишните доказателства."""
    if not predishni:
        return []
    prichini = []
    pe, ne = predishni.get("emisiya", {}), novi.get("emisiya", {})
    if pe.get("rezultat") == DA and ne.get("rezultat") != DA:
        prichini.append("изчезнала емисия (беше %s)" % pe.get("url"))
    ph, nh = predishni.get("domeyn", {}).get("kraen_host"), novi.get("domeyn", {}).get("kraen_host")
    if ph and nh and ph != nh:
        prichini.append("нов домейн: %s → %s" % (ph, nh))
    st = novi.get("zhiv", {}).get("status")
    if st in (404, 410):
        prichini.append("страницата връща %d" % st)
    elif novi.get("zhiv", {}).get("rezultat") == NE and predishni.get("zhiv", {}).get("rezultat") == DA:
        prichini.append("страницата вече не отговаря: %s" % novi["zhiv"]["belezhka"])
    elif novi.get("zhiv", {}).get("neprochetena") and not predishni.get("zhiv", {}).get("neprochetena"):
        prichini.append("страницата вече не се чете: %s — нужна ръчна проверка или друг канал"
                        % novi["zhiv"]["belezhka"])
    pt = predishni.get("razresheniya", {}).get("tdm", {}).get("rezervirano")
    nt = novi.get("razresheniya", {}).get("tdm", {}).get("rezervirano")
    if nt and not pt:
        prichini.append("нова TDM забрана: %s" % "; ".join(novi["razresheniya"]["tdm"]["signali"]))
    pr, nr = predishni.get("razresheniya", {}).get("robots", {}), novi.get("razresheniya", {}).get("robots", {})
    if pr.get("pozvoleno") and nr.get("pozvoleno") is False:
        prichini.append("robots.txt вече не позволява")
    return prichini
