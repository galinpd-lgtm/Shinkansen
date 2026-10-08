"""Разбор на HTML само със стандартната библиотека. Чист: еднакъв вход → еднакъв изход.

Връща речник с всичко, което правилникът гледа: език, заглавие, описание, H1, връзки, скриптове, JSON-LD,
видимия текст (без script/style/noscript/template/svg) и заглавията и съдържанието (за политиките).
"""
import json
import re
from html.parser import HTMLParser

SKRITI = {"script", "style", "noscript", "template", "svg", "head"}
PRAZNI = {"br", "hr", "img", "input", "meta", "link", "source", "area", "base", "col", "embed", "param", "track",
          "wbr"}
BLOKOVI = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer", "nav",
           "td", "th", "tr", "address", "main", "aside", "ul", "ol", "table", "br", "button", "form"}


def _sbij(s):
    return re.sub(r"\s+", " ", s or "").strip()


class _Razbor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.d = {"lang": None, "title": None, "description": None, "viewport": None, "generator": None,
                  "meta": {}, "h1": [], "zaglaviya": [], "vrazki": [], "link_tagove": [], "skriptove": [],
                  "inline_skriptove": [], "json_ld": [], "json_ld_greshki": 0, "adres_tag": [], "butoni": []}
        self.stek = []
        self.skrito = 0
        self.tekst = []
        self._sabira = None   # (таг, атрибути, буфер) за title/h*/a/script/address/button
        self._title = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html" and a.get("lang"):
            self.d["lang"] = a["lang"].strip()
        elif tag == "meta":
            ime = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if ime:
                self.d["meta"][ime] = a.get("content", "")
            if ime == "description":
                self.d["description"] = a.get("content", "")
            elif ime == "viewport":
                self.d["viewport"] = a.get("content", "")
            elif ime == "generator":
                self.d["generator"] = a.get("content", "")
        elif tag == "link":
            self.d["link_tagove"].append({"rel": a.get("rel", "").lower(), "href": a.get("href", ""),
                                          "hreflang": a.get("hreflang", ""), "type": a.get("type", "")})
        elif tag == "script":
            if a.get("src"):
                self.d["skriptove"].append(a["src"])
        if tag in BLOKOVI:
            self.tekst.append("\n")
        if tag in PRAZNI:
            return
        self.stek.append(tag)
        if tag in SKRITI:
            self.skrito += 1
        if tag in ("title", "h1", "h2", "h3", "h4", "h5", "h6", "a", "script", "address", "button") \
                and self._sabira is None:
            self._sabira = (tag, a, [])

    def handle_endtag(self, tag):
        if tag in PRAZNI or tag not in self.stek:
            return
        while self.stek:
            t = self.stek.pop()
            if t in SKRITI:
                self.skrito -= 1
            if t == tag:
                break
        if tag in BLOKOVI:
            self.tekst.append("\n")
        if self._sabira and self._sabira[0] == tag:
            t, a, buf = self._sabira
            self._sabira = None
            s = "".join(buf)
            if t == "title":
                self.d["title"] = _sbij(s)
            elif t in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.d["zaglaviya"].append({"tag": t, "tekst": _sbij(s)})
                if t == "h1":
                    self.d["h1"].append(_sbij(s))
            elif t == "a":
                self.d["vrazki"].append({"href": a.get("href", ""), "tekst": _sbij(s), "hreflang": a.get("hreflang", ""),
                                         "rel": a.get("rel", "")})
            elif t == "script":
                if a.get("type", "").lower() == "application/ld+json":
                    try:
                        self.d["json_ld"].append(json.loads(s))
                    except ValueError:
                        self.d["json_ld_greshki"] += 1
                elif not a.get("src"):
                    self.d["inline_skriptove"].append(s)
            elif t == "address":
                self.d["adres_tag"].append(_sbij(s))
            elif t == "button":
                self.d["butoni"].append(_sbij(s))

    def handle_data(self, data):
        if self._sabira:
            self._sabira[2].append(data)
        if not self.skrito:
            self.tekst.append(data)


def razberi(html):
    p = _Razbor()
    try:
        p.feed(html or "")
        p.close()
    except Exception:  # счупен HTML не спира проверката — каквото е прочетено, остава
        pass
    d = p.d
    redove = [_sbij(r) for r in "".join(p.tekst).split("\n")]
    d["redove"] = [r for r in redove if r]
    d["vidim_tekst"] = " ".join(d["redove"])
    return d


def json_ld_obekti(d):
    """Всички обекти от JSON-LD, разгънати (списъци и @graph)."""
    izhod = []

    def obhodi(x):
        if isinstance(x, list):
            for y in x:
                obhodi(y)
        elif isinstance(x, dict):
            izhod.append(x)
            if "@graph" in x:
                obhodi(x["@graph"])
    obhodi(d["json_ld"])
    return izhod


def tipove(obekt):
    t = obekt.get("@type")
    if isinstance(t, str):
        t = [t]
    return [str(x).split("/")[-1] for x in (t or [])]
