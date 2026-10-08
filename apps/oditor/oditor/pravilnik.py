"""Правилникът (rulebook v1): снимка на сайта → находки и оценка. Чист модул — без мрежа, без часовник,
без модел. Еднакъв вход → еднаква оценка. Всяка промяна в правилата вдига `RULEBOOK`.

Четири състояния, не да/не:
  има · не_е_намерено · блокирано · непроверено
„Не е намерено на началната страница“ никога не се пише като „липсва“.

Всяка находка носи `dokazatelstvo`: адрес, HTTP код, час и заглавка или селектор/откъс. Находка без
доказателство не излиза навън (`s_dokazatelstvo`). „непроверено“ не твърди нищо за сайта — то носи причина.

Правните сигнали са за юрист — никога присъда „нарушение“.
"""
import re
import urllib.parse
import urllib.robotparser

from . import razbor

RULEBOOK = "v1"

IMA, NE, BLOK, NEPR = "има", "не_е_намерено", "блокирано", "непроверено"
SASTOYANIYA = (IMA, NE, BLOK, NEPR)
BLOK_KODOVE = (401, 403, 429, 503)
MIN_TEKST = 400

AI_BOTOVE = ("GPTBot", "ClaudeBot", "PerplexityBot")

ORG_TIPOVE = {
    "Organization", "LocalBusiness", "Place", "EventVenue", "Corporation", "NGO", "GovernmentOrganization",
    "EducationalOrganization", "PerformingGroup", "SportsOrganization", "MusicVenue", "PerformingArtsTheater",
    "StadiumOrArena", "CivicStructure", "Museum", "Library", "MovieTheater", "Restaurant", "Hotel",
    "LodgingBusiness", "Store", "ProfessionalService", "TouristAttraction", "SportsActivityLocation",
}
EVENT_STATUSI = {"EventScheduled", "EventPostponed", "EventCancelled", "EventMovedOnline", "EventRescheduled"}
DUMI_OTLOZHENO = ("отложен", "отложено", "отложена", "отменен", "отменено", "отменена", "postponed", "cancelled",
                  "canceled", "rescheduled", "нова дата")

EZICI_PATISHTA = ("bg", "en", "de", "ru", "ro", "tr", "fr", "it", "es", "el", "uk", "sr", "mk", "pl", "cs", "nl")
EZICI_TEKST = {"en", "eng", "english", "bg", "бг", "български", "deutsch", "de", "русский", "ru", "română", "ro",
               "türkçe", "tr", "français", "fr", "italiano", "español", "ελληνικά", "українська"}
RODNI = ("bg",)

TRAKERI = (
    ("Google Tag Manager", ("googletagmanager.com",)),
    ("Google Analytics", ("google-analytics.com", "gtag(")),
    ("Meta Pixel", ("connect.facebook.net", "fbq(")),
    ("Hotjar", ("static.hotjar.com", "hotjar")),
    ("Microsoft Clarity", ("clarity.ms",)),
    ("Yandex Metrica", ("mc.yandex.ru", "ym(")),
    ("TikTok Pixel", ("analytics.tiktok.com",)),
    ("LinkedIn Insight", ("snap.licdn.com",)),
)
CMP = (
    ("Cookiebot", ("cookiebot.com",)), ("OneTrust", ("onetrust.com", "cookielaw.org")),
    ("CookieYes", ("cookieyes.com",)), ("Complianz", ("complianz",)), ("iubenda", ("iubenda.com",)),
    ("Usercentrics", ("usercentrics.eu",)), ("Cookie Notice", ("cookie-notice",)),
)
CMS = (
    ("WordPress", ("wp-content/", "wp-includes/")), ("Joomla", ("/media/jui/", "joomla")),
    ("Drupal", ("drupal.settings", "/sites/default/files/")), ("Wix", ("static.wixstatic.com", "wix.com")),
    ("Shopify", ("cdn.shopify.com",)), ("Squarespace", ("squarespace.com",)), ("Tilda", ("tildacdn.com",)),
    ("Webflow", ("webflow.com",)), ("1C-Bitrix", ("/bitrix/",)),
)
POLITIKI = (
    ("poveritelnost", "поверителност", ("поверителност", "лични данни", "защита на данните", "privacy", "gdpr")),
    ("biskvitki", "бисквитки", ("бисквитки", "cookie")),
    ("obshti_usloviya", "общи условия", ("общи условия", "условия за ползване", "terms")),
)
DOSTAPNOST = ("достъпност", "accessibility")
BANNER_DUMI = ("бисквитк", "cookie")
PRIEMAM = ("приемам", "приеми", "съгласен", "разбрах", "accept", "agree", "allow all", "ok")
OBSHTI_ADRESI = ("info", "office", "contact", "contacts", "kontakt", "kontakti", "hello", "sales", "support",
                 "admin", "reception", "booking", "bookings", "reservations", "rezervacii", "press", "media",
                 "marketing", "tickets", "bilet", "bileti", "kasa", "secretary", "sekretar", "mail", "post",
                 "zapitvaniya", "obshtina", "dpo", "gdpr", "privacy", "accounting", "hr", "jobs", "careers")
EIK_RE = re.compile(r"(?:ЕИК|ЕИК/БУЛСТАТ|БУЛСТАТ|EIK|UIC|Булстат)\s*[:№]?\s*(?:BG)?\s*(\d{9}(?:\d{4})?)\b",
                    re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


# ─────────── помощни ───────────

def dok(z, **kw):
    """Доказателство от запис на заявка: адрес, код, час + заглавка или селектор/откъс."""
    d = {"url": z.get("url"), "status": z.get("status"), "t": z.get("t")}
    if z.get("izvor"):
        d["izvor"] = z["izvor"]
    for k, v in kw.items():
        if v is not None:
            d[k] = v if not isinstance(v, str) else v[:300]
    return d


def signal(kod, ime, sastoyanie, dokazatelstva=(), **kw):
    assert sastoyanie in SASTOYANIYA, sastoyanie
    s = {"kod": kod, "ime": ime, "sastoyanie": sastoyanie, "dokazatelstvo": [d for d in dokazatelstva if d]}
    s.update({k: v for k, v in kw.items() if v is not None})
    return s


def s_dokazatelstvo(s):
    """Може ли находката да излезе навън. „непроверено“ — само с причина; всичко друго — само с доказателство."""
    if s["sastoyanie"] == NEPR:
        return bool(s.get("prichina"))
    return any(d.get("url") and d.get("t") for d in s.get("dokazatelstvo") or [])


def _kraen(veriga):
    return veriga[-1] if veriga else None


def _chetimo(z):
    return bool(z) and not z.get("greshka") and z.get("status") == 200


def _nedostapno(z):
    """Защо съдържанието не е прочетено → (състояние, причина)."""
    if not z:
        return NEPR, "началната страница не е поискана"
    g = z.get("greshka") or ""
    if g.startswith("robots"):
        return NEPR, "robots.txt не пуска нашия обхождащ (или не е ясно какво пуска) — уважено, нищо не е теглено"
    if g:
        return NEPR, "няма отговор: %s" % g
    if z.get("status") in BLOK_KODOVE:
        return BLOK, "сървърът отказа (HTTP %s) — защита, не повреда" % z["status"]
    return NEPR, "HTTP %s — съдържанието не е прочетено" % z.get("status")


def _otkas(tekst, i, n=160):
    a = max(0, i - n // 2)
    return re.sub(r"\s+", " ", tekst[a:a + n]).strip()


def _tarsi(tekst, dumi):
    nisko = tekst.lower()
    for d in dumi:
        i = nisko.find(d.lower())
        if i >= 0:
            return d, i
    return None, -1


class Izvor:
    """Едно прочетено HTML: от обикновената заявка или от браузъра."""

    def __init__(self, z, html, brauzar=False):
        self.z = dict(z)
        if brauzar:
            self.z["izvor"] = "браузър (JavaScript)"
        self.brauzar = brauzar
        self.html = html or ""
        self.r = razbor.razberi(self.html)
        self.obekti = razbor.json_ld_obekti(self.r)


# ─────────── сигналите от HTML (всеки връща signal) ───────────

def _org_tip(iz):
    for o in iz.obekti:
        t = [x for x in razbor.tipove(o) if x in ORG_TIPOVE]
        if t:
            return signal("org_tip", "schema.org организация/място", IMA,
                          [dok(iz.z, selektor='script[type="application/ld+json"]', otkas='"@type": "%s"' % t[0])],
                          stoynost=t[0])
    bel = "JSON-LD без тип организация/място" if iz.obekti else "няма JSON-LD"
    if iz.r["json_ld_greshki"]:
        bel += " (%d неразбираеми блока JSON-LD)" % iz.r["json_ld_greshki"]
    return signal("org_tip", "schema.org организация/място", NE, [dok(iz.z, selektor='script[type="application/ld+json"]')],
                  belezhka=bel + " на тази страница")


def _e_sabitie(o):
    return any(t == "Event" or t.endswith("Event") for t in razbor.tipove(o))


def _sabitiya(iz):
    sab = [o for o in iz.obekti if _e_sabitie(o)]
    if not sab:
        return None
    problemi = []
    for o in sab:
        ime = str(o.get("name") or "(без име)")
        st = str(o.get("eventStatus") or "").split("/")[-1]
        if not st:
            problemi.append("„%s“: няма eventStatus" % ime)
        elif st not in EVENT_STATUSI:
            problemi.append("„%s“: непознат eventStatus „%s“" % (ime, st))
        else:
            tekst = (ime + " " + str(o.get("description") or "")).lower()
            dyma, _ = _tarsi(tekst, DUMI_OTLOZHENO)
            if dyma and st == "EventScheduled":
                problemi.append("„%s“: eventStatus е EventScheduled, а в описанието пише „%s“" % (ime, dyma))
        if not o.get("startDate"):
            problemi.append("„%s“: няма startDate" % ime)
        if not o.get("offers"):
            problemi.append("„%s“: няма offers" % ime)
    d = [dok(iz.z, selektor='script[type="application/ld+json"] Event', otkas="%d събития" % len(sab))]
    if problemi:
        return signal("sabitiya", "Event (статус, дата, offers)", NE, d, problemi=problemi,
                      belezhka="непълни или противоречиви данни за събития")
    return signal("sabitiya", "Event (статус, дата, offers)", IMA, d, stoynost="%d събития" % len(sab))


def _hreflang(iz):
    for l in iz.r["link_tagove"]:
        if "alternate" in l["rel"] and l["hreflang"]:
            return signal("hreflang", "hreflang", IMA, [dok(iz.z, selektor='link[rel=alternate][hreflang="%s"]'
                                                            % l["hreflang"], otkas=l["href"])])
    for a in iz.r["vrazki"]:
        if a["hreflang"]:
            return signal("hreflang", "hreflang", IMA, [dok(iz.z, selektor='a[hreflang="%s"]' % a["hreflang"],
                                                            otkas=a["href"])])
    return signal("hreflang", "hreflang", NE, [dok(iz.z, selektor="link[hreflang], a[hreflang]")])


def _ezikova_vrazka(iz):
    for a in iz.r["vrazki"]:
        href, tekst = a["href"].strip(), a["tekst"].strip().lower()
        try:
            p = urllib.parse.urlsplit(href)
        except ValueError:
            continue
        parvo = p.path.strip("/").split("/")[0].lower() if p.path else ""
        q = urllib.parse.parse_qs(p.query)
        if (parvo in EZICI_PATISHTA and (p.path.rstrip("/").count("/") <= 1)) or "lang" in q or tekst in EZICI_TEKST:
            return signal("ezikova_vrazka", "връзка към езикова версия", IMA,
                          [dok(iz.z, selektor='a[href="%s"]' % href, otkas=a["tekst"])])
    return signal("ezikova_vrazka", "връзка към езикова версия", NE, [dok(iz.z, selektor="a[href]")])


def ezik_na_stranicata(iz):
    lang = (iz.r["lang"] or "").split("-")[0].lower()
    if lang:
        return lang, "html[lang]"
    t = iz.r["vidim_tekst"]
    kir = len(re.findall(r"[А-Яа-яЁёЪъЬь]", t))
    lat = len(re.findall(r"[A-Za-z]", t))
    if kir + lat < 50:
        return None, None
    return ("bg" if kir > lat else "en"), "брояч на кирилица/латиница"


def _chuzhd_ezik(iz):
    lang, kak = ezik_na_stranicata(iz)
    if lang and lang not in RODNI:
        return signal("chuzhd_ezik", "сайт на чужд език", IMA, [dok(iz.z, selektor=kak, otkas=lang)], stoynost=lang)
    return signal("chuzhd_ezik", "сайт на чужд език", NE, [dok(iz.z, selektor=kak or "html[lang]", otkas=lang)],
                  stoynost=lang)


def _kontakt_mashinno(iz):
    for o in iz.obekti:
        for k in ("telephone", "address"):
            if o.get(k):
                v = o[k]
                otk = v if isinstance(v, str) else (v.get("streetAddress") if isinstance(v, dict) else None)
                return signal("kontakt_mashinno", "адрес/телефон в машинно четим вид", IMA,
                              [dok(iz.z, selektor='JSON-LD "%s"' % k, otkas=str(otk or k))])
    for a in iz.r["vrazki"]:
        if a["href"].lower().startswith("tel:"):
            return signal("kontakt_mashinno", "адрес/телефон в машинно четим вид", IMA,
                          [dok(iz.z, selektor='a[href^="tel:"]', otkas=a["href"])])
    if iz.r["adres_tag"]:
        return signal("kontakt_mashinno", "адрес/телефон в машинно четим вид", IMA,
                      [dok(iz.z, selektor="address", otkas=iz.r["adres_tag"][0])])
    return signal("kontakt_mashinno", "адрес/телефон в машинно четим вид", NE,
                  [dok(iz.z, selektor='JSON-LD telephone/address, a[href^="tel:"], address')])


def _cifri(s):
    return re.sub(r"\D", "", s or "")


def _norm(s):
    return re.sub(r"[\s\.,;:\"'„“”«»()-]+", " ", (s or "").lower()).strip()


def _registar(iz, dosie):
    if not dosie:
        return signal("registar", "съвпада с регистъра", NEPR, prichina="няма досие за този сайт")
    tekst = iz.r["vidim_tekst"] + " " + " ".join(a["href"] for a in iz.r["vrazki"])
    tel = _cifri(dosie.get("telefon"))[-9:]
    if tel and len(tel) == 9 and tel in _cifri(tekst):
        return signal("registar", "съвпада с регистъра", IMA, [dok(iz.z, selektor="видим текст", otkas="телефон …" + tel[-4:])])
    adres = _norm(dosie.get("adres"))
    if adres and adres in _norm(tekst):
        return signal("registar", "съвпада с регистъра", IMA, [dok(iz.z, selektor="видим текст", otkas=dosie["adres"])])
    return signal("registar", "съвпада с регистъра", NE, [dok(iz.z, selektor="видим текст")],
                  belezhka="телефонът и адресът от досието не са намерени на страницата")


def _title(iz):
    t = iz.r["title"]
    return signal("title", "title", IMA if t else NE, [dok(iz.z, selektor="title", otkas=t)])


def _description(iz):
    t = (iz.r["description"] or "").strip()
    return signal("description", "meta description", IMA if t else NE,
                  [dok(iz.z, selektor='meta[name="description"]', otkas=t)])


def _h1(iz):
    t = next((h for h in iz.r["h1"] if h), "")
    return signal("h1", "H1", IMA if t else NE, [dok(iz.z, selektor="h1", otkas=t)])


def _viewport(iz):
    t = iz.r["viewport"]
    return signal("viewport", "viewport", IMA if t else NE, [dok(iz.z, selektor='meta[name="viewport"]', otkas=t)])


def _cms(iz):
    if iz.r["generator"]:
        return signal("cms", "CMS", IMA, [dok(iz.z, selektor='meta[name="generator"]', otkas=iz.r["generator"])],
                      stoynost=iz.r["generator"])
    nisko = iz.html.lower()
    for ime, markeri in CMS:
        m, i = _tarsi(nisko, markeri)
        if m:
            return signal("cms", "CMS", IMA, [dok(iz.z, selektor="HTML", otkas=_otkas(iz.html, i, 80))], stoynost=ime)
    return signal("cms", "CMS", NE, [dok(iz.z, selektor='meta[name="generator"], обичайни пътища')])


def _politiki(iz):
    izhod = []
    for kod, ime, dumi in POLITIKI:
        nam = None
        for a in iz.r["vrazki"]:
            if _tarsi(a["tekst"] + " " + a["href"], dumi)[0]:
                nam = a
                break
        if nam:
            izhod.append(signal("politika_" + kod, "връзка: " + ime, IMA,
                                [dok(iz.z, selektor='a[href="%s"]' % nam["href"], otkas=nam["tekst"])],
                                href=nam["href"]))
        else:
            izhod.append(signal("politika_" + kod, "връзка: " + ime, NE, [dok(iz.z, selektor="a[href]")]))
    return izhod


def _trakeri(iz):
    kod = iz.html
    namereni, d = [], []
    for ime, markeri in TRAKERI:
        m, i = _tarsi(kod, markeri)
        if m:
            namereni.append(ime)
            d.append(dok(iz.z, selektor="script", otkas=_otkas(kod, i, 100)))
    if namereni:
        return signal("trakeri", "тракери в кода", IMA, d, stoynost=namereni)
    return signal("trakeri", "тракери в кода", NE, [dok(iz.z, selektor="script")])


def _banner(iz, br):
    kod = iz.html
    for ime, markeri in CMP:
        m, i = _tarsi(kod, markeri)
        if m:
            return signal("banner", "банер за бисквитки", IMA, [dok(iz.z, selektor="script", otkas=_otkas(kod, i, 100))],
                          stoynost=ime)
    tekst = iz.r["vidim_tekst"]
    d, i = _tarsi(tekst, BANNER_DUMI)
    if d and any(_tarsi(b, PRIEMAM)[0] for b in iz.r["butoni"]):
        return signal("banner", "банер за бисквитки", IMA, [dok(iz.z, selektor="button", otkas=_otkas(tekst, i))])
    if br and br.get("banner") is True:
        return signal("banner", "банер за бисквитки", IMA, [dok(dict(br, izvor="браузър (JavaScript)"),
                                                                 selektor="видим банер")])
    return signal("banner", "банер за бисквитки", NE, [dok(iz.z, selektor="script, button")],
                  belezhka="не е видян в HTML без JavaScript" if not (br and br.get("izpolzvan")) else None)


def _otkaz_buton(br):
    if br and br.get("izpolzvan") and br.get("status") == 200 and br.get("banner") is False:
        return signal("otkaz_buton", "бутон за отказ в банера", NEPR, prichina="браузърът не видя банер")
    if not br or not br.get("izpolzvan") or br.get("otkaz_buton") is None:
        return signal("otkaz_buton", "бутон за отказ в банера", NEPR,
                      prichina="вижда се само с браузър — %s" % ((br or {}).get("zashto") or "браузърът не е пускан"))
    z = dict(br, izvor="браузър (JavaScript)")
    if br["otkaz_buton"]:
        return signal("otkaz_buton", "бутон за отказ в банера", IMA, [dok(z, selektor="button", otkas=br.get("otkaz_tekst"))])
    return signal("otkaz_buton", "бутон за отказ в банера", NE, [dok(z, selektor="button")])


def _eik(iz):
    m = EIK_RE.search(iz.r["vidim_tekst"])
    if m:
        return signal("eik", "ЕИК на страницата", IMA, [dok(iz.z, selektor="видим текст", otkas=m.group(0))],
                      stoynost=m.group(1))
    return signal("eik", "ЕИК на страницата", NE, [dok(iz.z, selektor="видим текст")])


def _dostapnost(iz):
    for a in iz.r["vrazki"]:
        if _tarsi(a["tekst"] + " " + a["href"], DOSTAPNOST)[0]:
            return signal("dostapnost", "декларация за достъпност", IMA,
                          [dok(iz.z, selektor='a[href="%s"]' % a["href"], otkas=a["tekst"])])
    return signal("dostapnost", "декларация за достъпност", NE, [dok(iz.z, selektor="a[href]")])


def obshti_adresi(iz):
    """Само общи фирмени адреси (info@, office@ …). Лични имейли не се пазят — само се броят."""
    vsichki = set(EMAIL_RE.findall(iz.r["vidim_tekst"] + " " + " ".join(a["href"] for a in iz.r["vrazki"])))
    obshti = sorted(e.lower() for e in vsichki if e.split("@")[0].lower() in OBSHTI_ADRESI)
    return obshti, len(vsichki) - len(obshti)


# ─────────── сливане: без JavaScript, после с браузър ───────────

def _slei(f, st, br, *a):
    """Първо HTML без JavaScript. Ако там няма, а браузърът го вижда — „има“, отбелязано „само с JavaScript“."""
    s = f(st, *a) if st else None
    if s is not None and s["sastoyanie"] == IMA:
        return s
    if br:
        b = f(br, *a)
        if b is not None and b["sastoyanie"] == IMA:
            b["samo_s_js"] = True
            return b
        if s is None:
            return b
    return s


def _stalb(kod, ime, signali, rezhim="vsichki", nezadalzhitelni=()):
    """Стълб: 1 точка само при „има“. rezhim „vsichki“ — всички задължителни; „edin“ — стига един.
    Незадължителните се броят само ако са проверени. Иначе състоянието е най-тежкото: блокирано > не_е_намерено > непроверено."""
    signali = [s for s in signali if s is not None]
    zad = [s for s in signali if s["kod"] not in nezadalzhitelni]
    nez = [s for s in signali if s["kod"] in nezadalzhitelni and s["sastoyanie"] != NEPR]
    broeni = zad + nez
    st = [s["sastoyanie"] for s in broeni]
    if rezhim == "edin":
        if IMA in st:
            sast = IMA
        else:
            sast = next((x for x in (BLOK, NEPR, NE) if x in st), NE)
    elif broeni and all(x == IMA for x in st):
        sast = IMA
    else:
        sast = next((x for x in (BLOK, NE, NEPR) if x in st), NEPR)
    return {"kod": kod, "ime": ime, "sastoyanie": sast, "tochka": 1 if sast == IMA else 0, "signali": signali}


def _nedostapen_signal(kod, ime, z, sast, prichina):
    if sast == BLOK:
        return signal(kod, ime, BLOK, [dok(z)], belezhka=prichina)
    return signal(kod, ime, NEPR, prichina=prichina)


# ─────────── главното ───────────

def _robots(snimka, kraen_url):
    z = snimka.get("robots")
    if not z:
        return None, "robots.txt не е поискан"
    if z.get("greshka"):
        return None, "robots.txt без отговор: %s" % z["greshka"]
    s = z.get("status") or 0
    if 400 <= s < 500:
        return "vsichko", "robots.txt: HTTP %d — нищо не е забранено (RFC 9309)" % s
    if s != 200:
        return None, "robots.txt: HTTP %d — не е ясно какво е позволено" % s
    rp = urllib.robotparser.RobotFileParser()
    rp.parse((z.get("tyalo") or "").splitlines())
    return rp, None


def _ai_robots(snimka, kraen_url):
    z = snimka.get("robots")
    rp, bel = _robots(snimka, kraen_url)
    if rp is None:
        return signal("ai_robots", "robots.txt пуска AI ботовете", NEPR, prichina=bel)
    if rp == "vsichko":
        return signal("ai_robots", "robots.txt пуска AI ботовете", IMA, [dok(z)], belezhka=bel)
    url = kraen_url or snimka["url"]
    sprenati = [b for b in AI_BOTOVE if not rp.can_fetch(b, url)]
    if sprenati:
        return signal("ai_robots", "robots.txt пуска AI ботовете", BLOK,
                      [dok(z, selektor="User-agent", otkas=", ".join(sprenati))], stoynost=sprenati,
                      belezhka="robots.txt моли тези ботове да не влизат — това е предпочитание, не контрол на достъпа")
    return signal("ai_robots", "robots.txt пуска AI ботовете", IMA, [dok(z, selektor="robots.txt", otkas=", ".join(AI_BOTOVE))])


def _ai_ua(snimka):
    proby = snimka.get("ai_ua")
    if not proby:
        return signal("ai_ua_200", "200 за AI ботове", NEPR,
                      prichina="не е пробвано — по подразбиране не се представяме с чужд UA")
    kodove = {b: z.get("status") for b, z in proby.items()}
    d = [dok(z, otkas=b) for b, z in proby.items()]
    if all(k == 200 for k in kodove.values()):
        return signal("ai_ua_200", "200 за AI ботове", IMA, d, stoynost=kodove)
    if any(k in BLOK_KODOVE for k in kodove.values()):
        return signal("ai_ua_200", "200 за AI ботове", BLOK, d, stoynost=kodove)
    return signal("ai_ua_200", "200 за AI ботове", NE, d, stoynost=kodove)


def _zaglavka(kod, ime, z, zagl):
    if not _chetimo(z):
        return None
    v = z["zaglavki"].get(zagl)
    return signal(kod, ime, IMA if v else NE, [dok(z, zaglavka="%s: %s" % (zagl, v) if v else zagl)])


def _llms(snimka):
    z = snimka.get("llms")
    if not z:
        return signal("llms_txt", "llms.txt", NEPR, prichina="не е поискан")
    if z.get("greshka"):
        return signal("llms_txt", "llms.txt", NEPR, prichina=_nedostapno(z)[1])
    if z["status"] in BLOK_KODOVE:
        return signal("llms_txt", "llms.txt", BLOK, [dok(z)])
    if z["status"] != 200:
        return signal("llms_txt", "llms.txt", NE, [dok(z)])
    ct = (z["zaglavki"].get("content-type") or "").lower()
    tyalo = (z.get("tyalo") or "").lstrip()
    if "html" in ct or tyalo.startswith("<") or not tyalo:
        return signal("llms_txt", "llms.txt", NE, [dok(z, zaglavka="content-type: %s" % ct)],
                      belezhka="отговорът е HTML или празен — вероятно страница за грешка с код 200")
    return signal("llms_txt", "llms.txt", IMA, [dok(z, otkas=tyalo[:80])])


def oceni(snimka):
    """Снимка → резултат. Снимката: url, robots, glavna (верига), llms, brauzar, ai_ua, dosie (по желание)."""
    veriga = snimka.get("glavna") or []
    z = _kraen(veriga)
    br = snimka.get("brauzar")
    kraen_url = z["url"] if z else snimka["url"]

    st = Izvor(z, z.get("tyalo")) if _chetimo(z) else None
    bi = Izvor(dict(br, url=br.get("url") or kraen_url), br.get("html"), brauzar=True) \
        if br and br.get("izpolzvan") and br.get("status") == 200 and br.get("html") else None
    if st is None and bi is None:
        sast_n, prichina_n = _nedostapno(z)
    else:
        sast_n, prichina_n = None, None

    def html_signal(f, kod, ime, *a):
        if sast_n:
            return _nedostapen_signal(kod, ime, z, sast_n, prichina_n)
        return _slei(f, st, bi, *a)

    # Достъп
    if z and not z.get("greshka"):
        https = signal("https", "HTTPS", IMA if kraen_url.lower().startswith("https://") else NE,
                       [dok(x) for x in veriga])
        kod = z["status"]
        if kod == 200:
            s200 = signal("status_200", "200 за обикновен UA", IMA, [dok(z)])
        elif kod in BLOK_KODOVE:
            s200 = signal("status_200", "200 за обикновен UA", BLOK, [dok(z)], belezhka=_nedostapno(z)[1])
        else:
            s200 = signal("status_200", "200 за обикновен UA", NE, [dok(z)], stoynost=kod)
    else:
        prich = _nedostapno(z)[1]
        https = signal("https", "HTTPS", NEPR, prichina=prich)
        s200 = signal("status_200", "200 за обикновен UA", NEPR, prichina=prich)
    if st:
        n = len(st.r["vidim_tekst"])
        if n >= MIN_TEKST:
            tekst = signal("tekst", "≥400 знака видим текст", IMA, [dok(z, selektor="body", otkas="%d знака" % n)],
                           stoynost=n)
        else:
            dop = " (с JavaScript: %d)" % len(bi.r["vidim_tekst"]) if bi else ""
            tekst = signal("tekst", "≥400 знака видим текст", NE, [dok(z, selektor="body", otkas="%d знака" % n)]
                           + ([dok(bi.z, selektor="body", otkas="%d знака" % len(bi.r["vidim_tekst"]))] if bi else []),
                           stoynost=n, belezhka="без JavaScript се виждат %d знака%s — ботовете без JavaScript "
                                                "виждат толкова" % (n, dop))
    elif sast_n or not z or z.get("greshka") or z.get("status") != 200:
        s, p = _nedostapno(z)
        tekst = _nedostapen_signal("tekst", "≥400 знака видим текст", z, s, p)
    else:
        tekst = signal("tekst", "≥400 знака видим текст", NEPR, prichina="няма HTML")
    dostap = _stalb("dostap", "Достъп", [https, s200, _ai_robots(snimka, kraen_url), _ai_ua(snimka), tekst],
                    nezadalzhitelni=("ai_ua_200",))

    struktura = _stalb("struktura", "Структура", [html_signal(_org_tip, "org_tip", "schema.org организация/място"),
                                                  None if sast_n else _slei(_sabitiya, st, bi)])
    ezici = _stalb("ezici", "Езици", [html_signal(_hreflang, "hreflang", "hreflang"),
                                      html_signal(_ezikova_vrazka, "ezikova_vrazka", "връзка към езикова версия"),
                                      html_signal(_chuzhd_ezik, "chuzhd_ezik", "сайт на чужд език")], rezhim="edin")
    dosie = snimka.get("dosie")
    reg = _nedostapen_signal("registar", "съвпада с регистъра", z, sast_n, prichina_n) if sast_n \
        else _slei(_registar, st, bi, dosie)
    sashtnost = _stalb("sashtnost", "Същност",
                       [html_signal(_kontakt_mashinno, "kontakt_mashinno", "адрес/телефон в машинно четим вид"), reg],
                       rezhim="edin")
    otgovori = _stalb("otgovori", "Отговори", [html_signal(_title, "title", "title"),
                                               html_signal(_description, "description", "meta description"),
                                               html_signal(_h1, "h1", "H1")])
    stalbove = [dostap, struktura, ezici, sashtnost, otgovori]

    dopalnitelno = [x for x in (
        _zaglavka("hsts", "HSTS", z, "strict-transport-security") if kraen_url.startswith("https://") else None,
        _zaglavka("csp", "CSP", z, "content-security-policy"),
        _zaglavka("xfo", "X-Frame-Options", z, "x-frame-options"),
        _zaglavka("xcto", "X-Content-Type-Options", z, "x-content-type-options"),
        html_signal(_viewport, "viewport", "viewport"),
        signal("razmer", "размер", IMA, [dok(z)], stoynost=z["razmer"]) if _chetimo(z) else None,
        html_signal(_cms, "cms", "CMS"),
        _llms(snimka),
    ) if x is not None]

    if sast_n:
        pravni = [_nedostapen_signal("pravni", "правни сигнали", z, sast_n, prichina_n)]
        adresi, skriti = [], 0
    else:
        osnova = st or bi
        pravni = []
        for i, _ in enumerate(POLITIKI):
            pravni.append(_slei(lambda iz: _politiki(iz)[i], st, bi))
        pravni += [_slei(_banner, st, bi, br), _otkaz_buton(br), _slei(_trakeri, st, bi), _slei(_eik, st, bi),
                   _slei(_dostapnost, st, bi)]
        adresi, skriti = obshti_adresi(osnova)

    brauzar = None
    if br:
        brauzar = {k: br.get(k) for k in ("izpolzvan", "prichina", "zashto", "status", "url", "t") if br.get(k) is not None}
        brauzar["sastoyanie"] = IMA if br.get("izpolzvan") else NEPR
    return {
        "rulebook": RULEBOOK,
        "url": snimka["url"],
        "kraen_url": kraen_url,
        "zayavki": snimka.get("broy_zayavki"),
        "brauzar": brauzar,
        "stalbove": stalbove,
        "tochki": sum(s["tochka"] for s in stalbove),
        "ot": len(stalbove),
        "dopalnitelno": dopalnitelno,
        "pravni_signali": pravni,
        "pravni_belezhka": "Сигнали за юрист, видени отвън. Не са присъда и не значат „нарушение“.",
        "obshti_adresi": adresi,
        "drugi_adresi_ne_se_pazyat": skriti,
    }
