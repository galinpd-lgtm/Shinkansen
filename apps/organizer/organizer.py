#!/usr/bin/env python3
"""Организатор на събития: event.json → проверка, готовност, сайт с въпросници и прожекция.

    python3 organizer.py new ПАПКА                 # ново събитие от примерния шаблон
    python3 organizer.py check ПАПКА               # грешки и какво още липсва
    python3 organizer.py build ПАПКА ИЗХОД [--demo]

ПАПКА съдържа event.json и people.json. Истинските събития стоят извън репото; тук е само моделът
и измислен пример (examples/intensive). Само стандартна библиотека на Python 3.

Изходът е статичен сайт плюс PHP за въпросниците (api/) и за износа в CSV (export/).
Докато publish.indexable е false, всяка страница носи noindex, а .htaccess добавя X-Robots-Tag.
--demo сглобява без изпращане на въпросниците (за преглед и за GitHub Pages).

Код на изход: 0 — готово · 1 — грешки в event.json · 2 — грешни аргументи.
"""
import argparse
import html
import json
import os
import re
import shutil
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "examples", "intensive")

FIELD_TYPES = {"single", "multi", "text", "textarea", "email", "consent"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
FONT_RE = re.compile(r"^[\w\s,'\"-]+$")
RESERVED_SLUGS = {"index", "programa", "razpisanie", "api", "export", "assets"}
MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли", "август",
          "септември", "октомври", "ноември", "декември"]


# ---------- четене ----------

def load(folder):
    with open(os.path.join(folder, "event.json"), encoding="utf-8") as f:
        event = json.load(f)
    people_path = os.path.join(folder, "people.json")
    people = {"speakers": [], "partners": [], "placeholders": {}}
    if os.path.exists(people_path):
        with open(people_path, encoding="utf-8") as f:
            people.update(json.load(f))
    return event, people


def topic_page(n):
    return "tema-%02d.html" % n


def resolve_options(field, event):
    """options_from: "topics" → „1. Заглавие“ за всяка тема; иначе options както са."""
    if field.get("options_from") == "topics":
        return ["%d. %s" % (t["n"], t["title"]) for t in event.get("topics", [])]
    return list(field.get("options", []))


# ---------- проверка ----------

def check(event, people):
    """Връща (грешки, липси). Грешките спират сглобяването; липсите са списък „какво още“."""
    err, todo = [], []

    def need(obj, key, where):
        if not isinstance(obj, dict) or not obj.get(key):
            err.append("%s: липсва „%s“" % (where, key))
            return False
        return True

    for key in ("slug", "title"):
        need(event, key, "събитие")
    if event.get("slug") and not SLUG_RE.match(event["slug"]):
        err.append("slug: само малки латински букви, цифри и тире")
    need(event.get("brand"), "name", "brand")

    theme = event.get("theme", {})
    for key in ("accent", "ink", "paper"):
        if key in theme and not COLOR_RE.match(str(theme[key])):
            err.append("theme.%s: цвят във вида #rrggbb" % key)
    for key in ("font_display", "font_body"):
        if key in theme and not FONT_RE.match(str(theme[key])):
            err.append("theme.%s: само имена на шрифтове" % key)
    fonts_css = theme.get("fonts_css")
    if fonts_css and not str(fonts_css).startswith("https://fonts.googleapis.com/"):
        err.append("theme.fonts_css: само от fonts.googleapis.com (или null)")

    d = event.get("dates", {})
    parsed = {}
    for key in ("from", "to"):
        try:
            parsed[key] = date.fromisoformat(d[key])
        except (KeyError, TypeError, ValueError):
            err.append("dates.%s: дата във вида ГГГГ-ММ-ДД" % key)
    if len(parsed) == 2 and parsed["to"] < parsed["from"]:
        err.append("dates: „to“ е преди „from“")

    roles = event.get("lab_roles", [])
    role_ids = [r.get("id") for r in roles]
    if len(set(role_ids)) != len(role_ids):
        err.append("lab_roles: повтарящ се id")
    for r in roles:
        if not r.get("id") or not ID_RE.match(r["id"]) or not r.get("label"):
            err.append("lab_roles: всяка роля иска id (латиница) и label")

    topics = event.get("topics", [])
    nums = [t.get("n") for t in topics]
    if not topics:
        todo.append("теми: няма нито една")
    if len(set(nums)) != len(nums):
        err.append("topics: повтарящ се номер n")
    for t in topics:
        where = "тема %s" % t.get("n")
        if not isinstance(t.get("n"), int) or t["n"] < 1:
            err.append("%s: n е цяло число от 1 нагоре" % where)
        need(t, "title", where)
        for rid in t.get("lab", {}):
            if rid not in role_ids:
                err.append("%s: лабораторията ползва непозната роля „%s“" % (where, rid))
        missing = [r for r in role_ids if not t.get("lab", {}).get(r)]
        if missing and role_ids:
            todo.append("%s: лабораторията е празна за %s" % (where, ", ".join(missing)))
        if not t.get("demo"):
            todo.append("%s: няма „Демо на живо“" % where)

    days = event.get("schedule", [])
    if not days:
        todo.append("разписание: празно")
    for day in days:
        where = "разписание %s" % day.get("date")
        try:
            dd = date.fromisoformat(day.get("date", ""))
            if len(parsed) == 2 and not parsed["from"] <= dd <= parsed["to"]:
                err.append("%s: денят е извън dates" % where)
        except (TypeError, ValueError):
            err.append("%s: дата във вида ГГГГ-ММ-ДД" % where)
        prev = None
        for s in day.get("slots", []):
            for key in ("from", "to"):
                if not TIME_RE.match(str(s.get(key, ""))):
                    err.append("%s: час „%s“ във вида ЧЧ:ММ" % (where, s.get(key)))
            if TIME_RE.match(str(s.get("from", ""))) and TIME_RE.match(str(s.get("to", ""))):
                if s["to"] <= s["from"]:
                    err.append("%s: %s–%s свършва преди да започне" % (where, s["from"], s["to"]))
                if prev and s["from"] < prev:
                    err.append("%s: %s се застъпва с предишния час" % (where, s["from"]))
                prev = s["to"]
            for n in s.get("topics", []):
                if n not in nums:
                    err.append("%s: сочи несъществуваща тема %s" % (where, n))
    in_schedule = {n for day in days for s in day.get("slots", []) for n in s.get("topics", [])}
    for n in nums:
        if days and n not in in_schedule:
            todo.append("тема %s: не е в разписанието" % n)

    forms = event.get("forms", [])
    ids, slugs = set(), set()
    for f in forms:
        where = "въпросник %s" % f.get("id")
        if not f.get("id") or not ID_RE.match(f["id"]):
            err.append("%s: id на латиница" % where)
        if not f.get("slug") or not SLUG_RE.match(f["slug"]) or f["slug"] in RESERVED_SLUGS \
                or re.match(r"^tema-\d+$", f["slug"]):
            err.append("%s: slug е зает или невалиден" % where)
        if f.get("id") in ids or f.get("slug") in slugs:
            err.append("%s: повтарящ се id или slug" % where)
        ids.add(f.get("id"))
        slugs.add(f.get("slug"))
        fids = set()
        for fld in f.get("fields", []):
            fw = "%s/%s" % (where, fld.get("id"))
            if not fld.get("id") or not ID_RE.match(fld["id"]) or fld["id"] in fids:
                err.append("%s: id на латиница и без повторение" % fw)
            fids.add(fld.get("id"))
            if fld.get("type") not in FIELD_TYPES:
                err.append("%s: непознат тип „%s“" % (fw, fld.get("type")))
            if not fld.get("label"):
                err.append("%s: липсва label" % fw)
            if fld.get("type") in ("single", "multi") and not resolve_options(fld, event):
                err.append("%s: няма опции" % fw)
        for fld in f.get("fields", []):
            for other in fld.get("required_if", []):
                if other not in fids:
                    err.append("%s/%s: required_if сочи липсващо поле „%s“" % (where, fld.get("id"), other))
    cta = event.get("cta", {})
    if cta.get("form") and cta["form"] not in ids:
        err.append("cta.form: няма въпросник „%s“" % cta["form"])

    for kind, label in (("speakers", "лектори"), ("partners", "партньори")):
        for i, p in enumerate(people.get(kind, [])):
            if not isinstance(p, dict) or not p.get("name"):
                err.append("people.%s[%d]: липсва name" % (kind, i))
            for key in ("photo", "link"):
                v = (p or {}).get(key) if isinstance(p, dict) else None
                if v and not re.match(r"^(https://|[\w./-]+$)", v):
                    err.append("people.%s[%d].%s: https:// адрес или относителен път" % (kind, i, key))
        if not people.get(kind):
            todo.append("%s: няма нито един — показват се празни профили" % label)

    forbid = event.get("publish", {}).get("forbid_text", [])
    if not isinstance(forbid, list) or not all(isinstance(x, str) and x.strip() for x in forbid):
        err.append("publish.forbid_text: списък от непразни низове")

    if not event.get("publish", {}).get("indexable"):
        todo.append("публикуване: скрито от търсачките (publish.indexable = false, чака „go“)")
    elif not event.get("publish", {}).get("base_url"):
        todo.append("публикуване: без publish.base_url няма sitemap.xml")
    return err, todo


# ---------- HTML ----------

def esc(s):
    return html.escape(str(s), quote=True)


def md(text):
    """Малко markdown в ред: **удебелено** и [текст](https://…). Всичко друго се екранира."""
    out = html.escape(str(text), quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"\[([^\]]+)\]\((https://[^)\s\"]+|[\w./#-]+)\)",
                 lambda m: '<a href="%s">%s</a>' % (m.group(2).replace('"', "%22"), m.group(1)), out)
    return out


def human_date(iso):
    d = date.fromisoformat(iso)
    return "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)


def date_label(event):
    d = event.get("dates", {})
    if d.get("label"):
        return d["label"]
    if d.get("from") == d.get("to"):
        return human_date(d["from"])
    return "%s – %s" % (human_date(d["from"]), human_date(d["to"]))


def theme_css(theme):
    t = {"accent": "#3a7be8", "ink": "#15151a", "paper": "#faf8f4",
         "font_display": "Georgia, serif", "font_body": "system-ui, sans-serif"}
    t.update({k: v for k, v in theme.items() if v})
    return (":root{--accent:%(accent)s;--ink:%(ink)s;--paper:%(paper)s;"
            "--font-display:%(font_display)s;--font-body:%(font_body)s}" % t)


def page(event, name, title, body, demo, current=None, extra_scripts=()):
    theme = event.get("theme", {})
    indexable = bool(event.get("publish", {}).get("indexable"))
    robots = "index, follow" if indexable else "noindex, nofollow"
    fonts = ""
    if theme.get("fonts_css"):
        fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
                 '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
                 '<link rel="stylesheet" href="%s">' % esc(theme["fonts_css"]))
    canon = ""
    base = event.get("publish", {}).get("base_url")
    if indexable and base:
        canon = '<link rel="canonical" href="%s">' % esc(base.rstrip("/") + "/" + ("" if name == "index.html" else name))
    nav = [("programa.html", "Програмата"), ("razpisanie.html", "Разписание")]
    cta = event.get("cta", {})
    form = next((f for f in event.get("forms", []) if f["id"] == cta.get("form")), None)
    if form:
        nav.append((form["slug"] + ".html", cta.get("label") or form["title"]))
    nav_html = "".join('<a href="%s"%s>%s</a>' % (h, ' aria-current="page"' if h == current else "", esc(l))
                       for h, l in nav)
    brand = event["brand"]
    ribbon = '<div class="ribbon">%s</div>' % esc(brand["ribbon"]) if brand.get("ribbon") else ""
    legal = esc(brand.get("legal") or brand["name"])
    scripts = "".join('<script src="assets/%s" defer></script>' % s for s in ("present.js",) + tuple(extra_scripts))
    full_title = title if name == "index.html" else "%s · %s" % (title, event["title"])
    return """<!doctype html>
<html lang="%(lang)s">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<meta name="robots" content="%(robots)s">
%(canon)s%(fonts)s
<style>%(css)s</style>
<link rel="stylesheet" href="assets/style.css">
</head>
<body%(demo)s>
%(ribbon)s
<header class="top"><a class="brand" href="index.html">%(brand)s</a><nav>%(nav)s</nav></header>
<main>
%(body)s
</main>
<footer class="foot"><span>%(legal)s · %(event)s · %(dates)s</span>
<button type="button" class="present-toggle" data-present-toggle title="Прожекция: P · стрелки · Esc">Прожекция (P)</button></footer>
%(scripts)s
</body>
</html>
""" % {"lang": esc(event.get("lang", "bg")), "title": esc(full_title), "desc": esc(event.get("description", event.get("tagline", ""))),
       "robots": robots, "canon": canon, "fonts": fonts, "css": theme_css(theme),
       "demo": ' data-demo="1"' if demo else "", "ribbon": ribbon, "brand": esc(brand["name"]), "nav": nav_html,
       "body": body, "legal": legal, "event": esc(event["title"]), "dates": esc(date_label(event)), "scripts": scripts}


def block(inner, cls="", label=None):
    aria = ' aria-label="%s"' % esc(label) if label else ""
    return '<section class="block %s" data-slide%s>\n<div class="wrap">\n%s\n</div>\n</section>' % (cls, aria, inner)


def cards(items, cls="cards"):
    return '<div class="%s">%s</div>' % (cls, "".join(
        '<article class="card"><h3>%s</h3>%s</article>' % (
            esc(i["title"]), '<p>%s</p>' % md(i["text"]) if i.get("text") else "") for i in items))


def cta_button(event, cls="btn"):
    cta = event.get("cta", {})
    form = next((f for f in event.get("forms", []) if f["id"] == cta.get("form")), None)
    if not form:
        return ""
    return '<a class="%s" href="%s.html">%s</a>' % (cls, esc(form["slug"]), esc(cta.get("label") or form["title"]))


def people_block(event, people, kind, title):
    """Статични профили (работят и без JS); assets/people.js ги опреснява от people.json в движение."""
    count = max(len(people.get(kind, [])), int(people.get("placeholders", {}).get(kind, 0)))
    items = []
    for i in range(count):
        p = people.get(kind, [])[i] if i < len(people.get(kind, [])) else None
        items.append(person_card(p, kind))
    return block('<h2>%s</h2>\n<div class="people" data-people="%s">%s</div>' % (esc(title), kind, "".join(items)),
                 "people-block", title)


def person_card(p, kind):
    if not p:
        return ('<article class="person empty"><div class="avatar" aria-hidden="true"></div>'
                '<h3>%s</h3><p class="muted">Предстои</p></article>' % ("Лектор" if kind == "speakers" else "Партньор"))
    photo = '<img class="avatar" src="%s" alt="" loading="lazy">' % esc(p["photo"]) if p.get("photo") \
        else '<div class="avatar" aria-hidden="true"></div>'
    name = esc(p["name"])
    if p.get("link"):
        name = '<a href="%s" rel="noopener">%s</a>' % (esc(p["link"]), name)
    return '<article class="person">%s<h3>%s</h3>%s%s</article>' % (
        photo, name, '<p class="role">%s</p>' % esc(p["role"]) if p.get("role") else "",
        '<p>%s</p>' % md(p["bio"]) if p.get("bio") else "")


def home(event, people, demo):
    place = event.get("place", {})
    hero = ('<p class="kicker">%s · %s</p>\n<h1>%s</h1>\n<p class="lead">%s</p>\n'
            '<p class="meta">%s</p>\n<p class="actions">%s <a class="btn ghost" href="programa.html">Програмата</a></p>') % (
        esc(date_label(event)), esc(place.get("name", "")), esc(event["title"]), md(event.get("tagline", "")),
        esc(" · ".join(x for x in (place.get("seats"), place.get("note")) if x)), cta_button(event))
    parts = [block(hero, "hero", event["title"])]
    why = event.get("home", {}).get("why")
    if why:
        parts.append(block("<h2>Защо така</h2>\n" + cards(why), "", "Защо така"))
    roles = event.get("lab_roles", [])
    if roles:
        parts.append(block("<h2>За кого</h2>\n" + cards([{"title": r["label"], "text": r.get("text", "")} for r in roles],
                                                          "cards four"), "", "За кого"))
    topics = event.get("topics", [])
    if topics:
        tiles = "".join('<a class="topic" href="%s"><span class="n">%02d</span><b>%s</b><span>%s</span></a>' % (
            topic_page(t["n"]), t["n"], esc(t["title"]), esc(t.get("summary", ""))) for t in topics)
        parts.append(block('<h2>Темите</h2>\n<div class="topics">%s</div>' % tiles, "", "Темите"))
    days = event.get("schedule", [])
    if days:
        tiles = "".join('<article class="card"><h3>%s</h3><p class="muted">%s</p><p>%s</p></article>' % (
            esc(day.get("label", "")), esc(human_date(day["date"])),
            esc(" · ".join(s["title"] for s in day.get("slots", [])))) for day in days)
        parts.append(block('<h2>Дните</h2>\n<div class="cards">%s</div>\n<p><a href="razpisanie.html">Разписанието по часове →</a></p>'
                           % tiles, "", "Дните"))
    parts.append(people_block(event, people, "speakers", "Лектори"))
    parts.append(people_block(event, people, "partners", "Партньори"))
    if cta_button(event):
        parts.append(block('<h2>%s</h2>\n<p class="lead">%s</p>\n<p>%s</p>' % (
            esc(event.get("cta", {}).get("label", "")), esc(place.get("seats", "")), cta_button(event)), "cta", "Записване"))
    return page(event, "index.html", event["title"], "\n".join(parts), demo, extra_scripts=("people.js",))


def programa(event, demo):
    rows = "".join('<li><a href="%s"><span class="n">%02d</span> <b>%s</b></a><p>%s</p></li>' % (
        topic_page(t["n"]), t["n"], esc(t["title"]), esc(t.get("summary", ""))) for t in event.get("topics", []))
    body = block('<p class="kicker">%s</p>\n<h1>Програмата</h1>\n<ol class="toc">%s</ol>' % (esc(date_label(event)), rows),
                 "", "Програмата")
    return page(event, "programa.html", "Програмата", body, demo, current="programa.html")


def topic(event, t, demo):
    topics = event.get("topics", [])
    idx = topics.index(t)
    parts = [block('<p class="kicker">Тема %d от %d</p>\n<h1>%s</h1>\n<p class="lead">%s</p>' % (
        t["n"], len(topics), esc(t["title"]), md(t.get("summary", ""))), "hero small", t["title"])]
    if t.get("goals"):
        parts.append(block('<h2>Какво ще можеш</h2>\n<ul class="ticks">%s</ul>' % "".join(
            "<li>%s</li>" % md(g) for g in t["goals"]), "", "Какво ще можеш"))
    for s in t.get("sections", []):
        parts.append(block('<h2>%s</h2>\n%s%s' % (esc(s["title"]), '<p class="lead">%s</p>' % md(s["intro"]) if s.get("intro") else "",
                                                cards(s.get("items", []))), "", s["title"]))
    roles = event.get("lab_roles", [])
    if roles:
        cols = "".join('<article class="lab-col"><h3>%s</h3><ul>%s</ul></article>' % (
            esc(r["label"]), "".join("<li>%s</li>" % md(x) for x in t.get("lab", {}).get(r["id"], []))
            or '<li class="muted">Предстои</li>') for r in roles)
        parts.append(block('<h2>Лаборатория</h2>\n<div class="lab" style="--cols:%d">%s</div>' % (len(roles), cols),
                           "lab-block", "Лаборатория"))
    if t.get("demo"):
        dm = t["demo"]
        parts.append(block('<h2>%s</h2>\n<ol class="steps">%s</ol>' % (esc(dm.get("title", "Демо на живо")), "".join(
            "<li>%s</li>" % md(x) for x in dm.get("steps", []))), "demo", "Демо на живо"))
    nav = []
    if idx > 0:
        nav.append('<a href="%s">← %s</a>' % (topic_page(topics[idx - 1]["n"]), esc(topics[idx - 1]["title"])))
    nav.append('<a href="programa.html">Всички теми</a>')
    if idx < len(topics) - 1:
        nav.append('<a href="%s">%s →</a>' % (topic_page(topics[idx + 1]["n"]), esc(topics[idx + 1]["title"])))
    parts.append('<nav class="pager">%s</nav>' % "".join(nav))
    return page(event, topic_page(t["n"]), "Тема %d: %s" % (t["n"], t["title"]), "\n".join(parts), demo,
                current="programa.html")


def razpisanie(event, demo):
    by_n = {t["n"]: t for t in event.get("topics", [])}
    parts = [block('<p class="kicker">%s · %s</p>\n<h1>Разписание</h1>' % (
        esc(date_label(event)), esc(event.get("place", {}).get("name", ""))), "hero small", "Разписание")]
    for day in event.get("schedule", []):
        rows = []
        for s in day.get("slots", []):
            links = " ".join('<a href="%s">Тема %d: %s</a>' % (topic_page(n), n, esc(by_n[n]["title"]))
                             for n in s.get("topics", []) if n in by_n)
            rows.append('<tr><td class="time">%s–%s</td><td><b>%s</b>%s</td></tr>' % (
                esc(s["from"]), esc(s["to"]), esc(s["title"]), "<br>" + links if links else ""))
        parts.append(block('<h2>%s <span class="muted">%s</span></h2>\n<table class="slots">%s</table>' % (
            esc(day.get("label", "")), esc(human_date(day["date"])), "".join(rows)), "", day.get("label")))
    return page(event, "razpisanie.html", "Разписание", "\n".join(parts), demo, current="razpisanie.html")


def form_field(fld, event):
    fid, req = fld["id"], fld.get("required")
    star = ' <span class="req" aria-hidden="true">*</span>' if req else ""
    help_ = '<p class="help">%s</p>' % md(fld["help"]) if fld.get("help") else ""
    r = " required" if req else ""
    t = fld["type"]
    if t in ("single", "multi"):
        kind = "radio" if t == "single" else "checkbox"
        name = fid if t == "single" else fid + "[]"
        opts = resolve_options(fld, event)
        items = "".join('<label class="opt"><input type="%s" name="%s" value="%s"%s> %s</label>' % (
            kind, name, esc(o), r if t == "single" and i == 0 else "", esc(o)) for i, o in enumerate(opts))
        if fld.get("other"):
            items += ('<label class="opt other"><input type="%s" name="%s" value="__other"> Друго: '
                      '<input type="text" name="%s__other" maxlength="200" aria-label="Друго"></label>' % (kind, name, fid))
        maxn = ' data-max="%d"' % fld["max"] if t == "multi" and fld.get("max") else ""
        hint = '<p class="help">До %d отговора.</p>' % fld["max"] if maxn else ""
        return '<fieldset class="field" data-field="%s"%s><legend>%s%s</legend>%s%s%s</fieldset>' % (
            fid, maxn, esc(fld["label"]), star, help_, hint, items)
    if t == "consent":
        dep = ' data-required-if="%s"' % esc(",".join(fld.get("required_if", []))) if fld.get("required_if") else ""
        return '<div class="field consent"%s><label class="opt"><input type="checkbox" name="%s" value="1"%s> %s%s</label>%s</div>' % (
            dep, fid, r, md(fld["label"]), star, help_)
    maxlen = int(fld.get("max_length", 254 if t == "email" else 2000))
    if t == "textarea":
        ctl = '<textarea id="f-%s" name="%s" rows="4" maxlength="%d"%s></textarea>' % (fid, fid, maxlen, r)
    else:
        ctl = '<input id="f-%s" type="%s" name="%s" maxlength="%d"%s%s>' % (
            fid, "email" if t == "email" else "text", fid, maxlen, r, ' autocomplete="email"' if t == "email" else "")
    return '<div class="field"><label for="f-%s">%s%s</label>%s%s</div>' % (fid, esc(fld["label"]), star, help_, ctl)


def form_page(event, f, demo):
    fields = "\n".join(form_field(x, event) for x in f.get("fields", []))
    note = ('<p class="notice">Демо: въпросникът не се изпраща.</p>' if demo else "")
    body = block('<p class="kicker">%s</p>\n<h1>%s</h1>\n<p class="lead">%s</p>\n%s'
                 '<form class="survey" method="post" action="api/submit.php" data-form="%s" novalidate>\n'
                 '<input type="hidden" name="_form" value="%s">\n'
                 '<div class="hp" aria-hidden="true"><label>Не попълвай<input type="text" name="_hp" tabindex="-1" autocomplete="off"></label></div>\n'
                 '<input type="hidden" name="_t" value="">\n%s\n'
                 '<p><button class="btn" type="submit">Изпрати</button></p>\n<p class="status" role="status" aria-live="polite"></p>\n'
                 '</form>' % (esc(event["title"]), esc(f["title"]), md(f.get("intro", "")), note, esc(f["id"]), esc(f["id"]), fields),
                 "form-block", f["title"])
    return page(event, f["slug"] + ".html", f["title"], body, demo, current=f["slug"] + ".html", extra_scripts=("forms.js",))


# ---------- сглобяване ----------

def forms_spec(event):
    """Какво приема api/submit.php: само тези полета, типове и опции. Нищо друго не се записва."""
    out = {"event": event["slug"], "forms": {}}
    for f in event.get("forms", []):
        fields = []
        for x in f.get("fields", []):
            spec = {"id": x["id"], "type": x["type"], "label": x["label"], "required": bool(x.get("required"))}
            if x["type"] in ("single", "multi"):
                spec["options"] = resolve_options(x, event)
                spec["other"] = bool(x.get("other"))
            if x["type"] == "multi" and x.get("max"):
                spec["max"] = int(x["max"])
            if x["type"] in ("text", "textarea", "email"):
                spec["max_length"] = int(x.get("max_length", 254 if x["type"] == "email" else 2000))
            if x.get("required_if"):
                spec["required_if"] = list(x["required_if"])
            fields.append(spec)
        out["forms"][f["id"]] = {"title": f["title"], "slug": f["slug"], "fields": fields}
    return out


HTACCESS = """# Сглобено от Shinkansen организатор. Подпапката наследява .htaccess на public_html — провери го първо.
Options -Indexes
<IfModule mod_headers.c>
%(robots)s  Header always set X-Content-Type-Options "nosniff"
  Header always set Referrer-Policy "strict-origin-when-cross-origin"
</IfModule>
<FilesMatch "^(forms\\.json|lib\\.php)$">
  Require all denied
</FilesMatch>
"""


def build(folder, out, demo=False):
    event, people = load(folder)
    errors, todo = check(event, people)
    if errors:
        raise ValueError("\n".join(errors))
    os.makedirs(out, exist_ok=True)
    written = []

    def write(rel, text):
        path = os.path.join(out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        written.append(rel)

    write("index.html", home(event, people, demo))
    write("programa.html", programa(event, demo))
    for t in event.get("topics", []):
        write(topic_page(t["n"]), topic(event, t, demo))
    write("razpisanie.html", razpisanie(event, demo))
    for f in event.get("forms", []):
        write(f["slug"] + ".html", form_page(event, f, demo))
    write("people.json", json.dumps({k: people.get(k, []) for k in ("speakers", "partners", "placeholders")},
                                    ensure_ascii=False, indent=2) + "\n")
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    for name in sorted(os.listdir(os.path.join(HERE, "assets"))):
        shutil.copyfile(os.path.join(HERE, "assets", name), os.path.join(out, "assets", name))
        written.append("assets/" + name)
    indexable = bool(event.get("publish", {}).get("indexable"))
    if not demo and event.get("forms"):
        write("api/forms.json", json.dumps(forms_spec(event), ensure_ascii=False, indent=1) + "\n")
        for name in ("lib.php", "submit.php"):
            with open(os.path.join(HERE, "php", name), encoding="utf-8") as f:
                write("api/" + name, f.read())
        with open(os.path.join(HERE, "php", "export.php"), encoding="utf-8") as f:
            write("export/index.php", f.read())
    write(".htaccess", HTACCESS % {"robots": "" if indexable else '  Header always set X-Robots-Tag "noindex, nofollow"\n'})
    base = event.get("publish", {}).get("base_url")
    if indexable and base:
        pages = [p for p in written if p.endswith(".html")]
        write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n'
              % "".join("  <url><loc>%s</loc></url>\n" % esc(base.rstrip("/") + "/" + ("" if p == "index.html" else p)) for p in pages))
    hits = forbidden_hits(out, written, event.get("publish", {}).get("forbid_text", []))
    if hits:
        raise ValueError("\n".join("забранен текст „%s“ в %s" % (t, rel) for rel, t in hits))
    return written, todo


def forbidden_hits(out, written, forbid):
    """Стари дати и имена, които не бива да останат никъде в сглобеното (publish.forbid_text)."""
    hits = []
    for rel in written:
        with open(os.path.join(out, rel), encoding="utf-8") as f:
            text = f.read()
        for t in forbid:
            if t in text or html.escape(t) in text:
                hits.append((rel, t))
    return hits


def cmd_new(dest):
    if os.path.exists(os.path.join(dest, "event.json")):
        print("%s: вече има event.json — нищо не пипам" % dest, file=sys.stderr)
        return 2
    os.makedirs(dest, exist_ok=True)
    for name in ("event.json", "people.json"):
        shutil.copyfile(os.path.join(EXAMPLE, name), os.path.join(dest, name))
    print("ново събитие: %s (event.json, people.json от примера — смени slug, заглавие, дати)" % dest)
    return 0


def report(errors, todo):
    for e in errors:
        print("ГРЕШКА  " + e)
    for t in todo:
        print("липсва  " + t)
    if not errors and not todo:
        print("готово: няма грешки и липси")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="organizer.py", description="Организатор на събития: event.json → сайт.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("new").add_argument("folder")
    sub.add_parser("check").add_argument("folder")
    b = sub.add_parser("build")
    b.add_argument("folder")
    b.add_argument("out")
    b.add_argument("--demo", action="store_true", help="без изпращане на въпросниците и без PHP")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if args.cmd == "new":
        return cmd_new(args.folder)
    try:
        event, people = load(args.folder)
    except (OSError, ValueError) as e:
        print("не мога да прочета %s: %s" % (args.folder, e), file=sys.stderr)
        return 1
    errors, todo = check(event, people)
    if args.cmd == "check":
        report(errors, todo)
        return 1 if errors else 0
    if errors:
        report(errors, [])
        return 1
    try:
        written, todo = build(args.folder, args.out, demo=args.demo)
    except ValueError as e:
        report(str(e).splitlines(), [])
        return 1
    print("%d файла в %s%s" % (len(written), args.out, " (демо)" if args.demo else ""))
    report([], todo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
