"""Обхождането на един сайт → снимка за правилника.

По подразбиране 3 заявки: robots.txt, началната страница, llms.txt (+ пренасочванията и robots.txt на нов хост,
ако началната пренасочва към друг). robots.txt се спазва за нашия UA (RFC 9309: 4xx → позволено; 5xx или
без отговор → нищо не се тегли). robots.txt е предпочитание на обхождащия, не контрол на достъпа.

Браузърът е втори опит: малко текст, отказ 401/403/429/503 или изтекло време. Пробата с UA на AI ботовете
е само ако `proba_s_ai_ua` е включено — и тогава UA казва честно, че е проба от oditor.
"""
import urllib.parse
import urllib.robotparser

from . import VERSIYA, brauzar, razbor
from .mrezha import user_agent
from .pravilnik import AI_BOTOVE, BLOK_KODOVE, MIN_TEKST


class Izklyuchen(Exception):
    """Сайтът е поискал да не бъде проверяван — не се изпраща нито една заявка."""


def _koren(url):
    p = urllib.parse.urlsplit(url)
    return "%s://%s" % (p.scheme, p.netloc)


class Robots:
    """robots.txt на всеки хост — веднъж, кеширан."""

    def __init__(self, m, ua_ime):
        self.m, self.ua_ime, self.zapisi, self.rp = m, ua_ime, {}, {}

    def zapis(self, url):
        k = _koren(url)
        if k not in self.zapisi:
            z = self.m.vzemi(k + "/robots.txt")
            self.zapisi[k] = z
            if z["greshka"] or (z["status"] or 0) >= 500 or (z["status"] in (None,)):
                self.rp[k] = False                       # не е ясно → нищо не се тегли
            elif z["status"] != 200:
                self.rp[k] = True                        # 4xx → позволено
            else:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse((z["tyalo"] or "").splitlines())
                self.rp[k] = rp
        return self.zapisi[k]

    def pozvoleno(self, url):
        self.zapis(url)
        rp = self.rp[_koren(url)]
        if isinstance(rp, bool):
            return rp
        return rp.can_fetch(self.ua_ime, url)


def _tryabva_brauzar(z):
    if not z:
        return None
    if z.get("greshka", "") and "изтекло време" in z["greshka"]:
        return "изтекло време"
    if z.get("status") in BLOK_KODOVE:
        return "отказ HTTP %s" % z["status"]
    if z.get("status") == 200 and not z.get("greshka"):
        n = len(razbor.razberi(z.get("tyalo")).get("vidim_tekst"))
        if n < MIN_TEKST:
            return "малко текст без JavaScript (%d знака)" % n
    return None


def snimai(cfg, url, m, brauzar_fabrika=None, nalozhi_brauzar=False):
    """→ снимка (речник) за `pravilnik.oceni`."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    from .config import dosie, izklyuchen
    if izklyuchen(cfg, host):
        raise Izklyuchen("%s е поискал да не бъде проверяван (izklyucheni в config)" % host)
    robots = Robots(m, cfg["user_agent_ime"])
    m.robots = robots   # за следващи заявки в същата проверка (политиката) — без повторно теглене
    robots.zapis(url)
    veriga = m.sledvai(url, pozvoleno=robots.pozvoleno)
    kraen = veriga[-1]
    sn = {"url": url, "versiya": VERSIYA, "ua": m.ua, "robots": robots.zapis(kraen["url"]), "glavna": veriga,
          "dosie": dosie(cfg, host)}
    if len(robots.zapisi) > 1:
        sn["robots_drugi"] = [z for k, z in robots.zapisi.items() if z is not sn["robots"]]
    if not (kraen.get("greshka") or "").startswith("robots"):
        llms = _koren(kraen["url"]) + "/llms.txt"
        if robots.pozvoleno(llms):
            sn["llms"] = m.vzemi(llms)
        prichina = _tryabva_brauzar(kraen) or ("изрично поискан" if nalozhi_brauzar else None)
        if prichina:
            sn["brauzar"] = _brauzar(cfg, kraen["url"], m.ua, prichina, brauzar_fabrika)
        if cfg.get("proba_s_ai_ua") and kraen.get("status") == 200:
            sn["ai_ua"] = {b: m.vzemi(kraen["url"], ua="%s (проба от %s)" % (b, user_agent(cfg))) for b in AI_BOTOVE}
    sn["broy_zayavki"] = m.broy
    return sn


def _brauzar(cfg, url, ua, prichina, fabrika):
    b = cfg.get("brauzar") or {}
    if not b.get("vklyuchen", True):
        return {"izpolzvan": False, "prichina": prichina, "zashto": "изключен в config"}
    if fabrika is None:
        if not brauzar.nalichen():
            return {"izpolzvan": False, "prichina": prichina, "zashto": "Playwright не е инсталиран"}
        fabrika = brauzar.zaredi
    try:
        r = fabrika(url, ua, int(b.get("taymaut_s", 30)))
    except Exception as e:  # браузърът е по желание: падането му не спира проверката, а се записва
        return {"izpolzvan": False, "prichina": prichina, "zashto": "браузърът падна: %s" % e}
    r["prichina"] = prichina
    return r
