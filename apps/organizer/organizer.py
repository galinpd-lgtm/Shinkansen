#!/usr/bin/env python3
"""Организатор на събития: event.json → проверка, готовност, сайт с въпросници и прожекция.

    python3 organizer.py new ПАПКА                 # ново събитие от примерния шаблон
    python3 organizer.py check ПАПКА               # грешки, липси и всички „[ЧАКА …]“
    python3 organizer.py build ПАПКА ИЗХОД [--demo]
    python3 organizer.py package САЙТ ПАПКА [--prev ПРЕДИШЕН]   # за качване: tgz, SHA-256, разлика
    python3 organizer.py qa ПАПКА ОТЧЕТ [--no-shots]            # A5 с една команда

ПАПКА съдържа event.json, data/ (лектори и партньори — по един запис на човек) и по желание
assets/ (лого, локални шрифтове), което се копира в изхода. Истинските събития стоят извън
репото; тук е само моделът и измислен пример (examples/intensive). Само стандартна библиотека.

Изходът е статичен сайт плюс PHP за въпросниците (api/), износ в CSV (admin/) и sql/schema.sql.
Докато publish.indexable е false, всяка страница носи noindex, а .htaccess добавя X-Robots-Tag.
След сглобяването се проверяват вътрешните връзки и забранените текстове (publish.forbid_*).
--demo сглобява без PHP и без изпращане на въпросниците (за преглед и за GitHub Pages).

Код на изход: 0 — готово · 1 — грешки · 2 — грешни аргументи.
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
TABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,50}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
FONT_RE = re.compile(r"^[\w\s,'\"-]+$")
LOCAL_RE = re.compile(r"^[\w][\w./-]*$")
URL_RE = re.compile(r"^(https://|[\w][\w./#-]*$)")
FIXED_PAGES = {"index", "programa", "razpisanie", "lektori", "organizatori", "privacy"}
RESERVED_SLUGS = FIXED_PAGES | {"api", "admin", "assets", "data", "sql"}
MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли", "август",
          "септември", "октомври", "ноември", "декември"]
DEFAULT_THEME = {"accent": "#3a7be8", "ink": "#15151a", "paper": "#faf8f4",
                 "font_display": "Georgia, serif", "font_body": "system-ui, sans-serif"}


# ---------- четене ----------

def people_files(event):
    p = event.get("people", {})
    return {"speakers": p.get("speakers_file", "data/lektori.json"),
            "partners": p.get("partners_file", "data/partnyori.json")}


def load(folder):
    with open(os.path.join(folder, "event.json"), encoding="utf-8") as f:
        event = json.load(f)
    people = {}
    for kind, rel in people_files(event).items():
        path = os.path.join(folder, rel)
        people[kind] = []
        if LOCAL_RE.match(rel) and ".." not in rel and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                people[kind] = json.load(f)
    return event, people


def topic_page(t):
    """tema-01.html или tema-01-softuer.html, ако темата има slug."""
    return "tema-%02d%s.html" % (t["n"], "-" + t["slug"] if t.get("slug") else "")


def resolve_options(field, event):
    """options_from: "topics" → „1. Заглавие“ за всяка тема; иначе options както са."""
    if field.get("options_from") == "topics":
        return ["%d. %s" % (t["n"], t["title"]) for t in event.get("topics", [])]
    return list(field.get("options", []))


def form_table(event, f):
    return f.get("table") or "%s_%s" % (event["slug"].replace("-", "_"), f["id"])


def rate_table(event):
    return event.get("server", {}).get("rate_table") or "%s_rate" % event["slug"].replace("-", "_")


def pending(obj, marker, path="event"):
    """Всички текстове с маркера (напр. „[ЧАКА“) — с пътя до тях, за доклада."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += pending(v, marker, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += pending(v, marker, "%s[%d]" % (path, i))
    elif isinstance(obj, str) and marker in obj and not path.endswith(".pending_marker"):
        out.append((path, obj))
    return out


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
    logo = event.get("brand", {}).get("logo")
    if logo and (not LOCAL_RE.match(logo) or ".." in logo):
        err.append("brand.logo: относителен път в папката на събитието (напр. assets/logo.svg)")

    theme = event.get("theme", {})
    for key in ("accent", "accent_text", "on_accent", "ink", "paper", "hero_bg", "hero_ink"):
        if key in theme and not COLOR_RE.match(str(theme[key])):
            err.append("theme.%s: цвят във вида #rrggbb" % key)
    for key in ("font_display", "font_body", "font_mono", "font_brand"):
        if key in theme and not FONT_RE.match(str(theme[key])):
            err.append("theme.%s: само имена на шрифтове" % key)
    fonts_css = theme.get("fonts_css")
    if fonts_css and not str(fonts_css).startswith("https://fonts.googleapis.com/"):
        err.append("theme.fonts_css: само от fonts.googleapis.com (или null)")
    for s in theme.get("stylesheets", []):
        if not LOCAL_RE.match(s) or ".." in s:
            err.append("theme.stylesheets: само локални файлове (напр. assets/fonts/fonts.css)")

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
            continue
        need(t, "title", where)
        if t.get("slug") and not SLUG_RE.match(t["slug"]):
            err.append("%s: slug само с малки латински букви, цифри и тире" % where)
        lab = t.get("lab", {})
        if lab is False:
            pass    # темата няма лаборатория по замисъл (напр. защитата) — не е липса
        elif not isinstance(lab, dict):
            err.append("%s: lab е {роля: [задачи]} или false" % where)
        else:
            for rid in lab:
                if rid not in role_ids:
                    err.append("%s: лабораторията ползва непозната роля „%s“" % (where, rid))
            missing = [r for r in role_ids if not lab.get(r)]
            if missing and role_ids:
                todo.append("%s: лабораторията е празна за %s" % (where, ", ".join(missing)))
        if not t.get("demo") and t.get("demo") is not False:     # false — без демо по замисъл
            todo.append("%s: няма „Демо на живо“" % where)
        for s in t.get("sections", []):
            tbl = s.get("table")
            if tbl and any(len(row) != len(tbl.get("head", [])) for row in tbl.get("rows", [])):
                err.append("%s/%s: всеки ред на таблицата иска толкова клетки, колкото има head"
                           % (where, s.get("title")))

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
            times_ok = True
            for key in ("from", "to"):
                v = str(s.get(key, ""))
                if v and not TIME_RE.match(v):
                    err.append("%s: час „%s“ във вида ЧЧ:ММ" % (where, v))
                    times_ok = False
                elif not v:
                    times_ok = False
            if not s.get("from") and not s.get("to"):
                todo.append("%s: „%s“ е без час" % (where, s.get("title")))
            if times_ok:
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

    img_lists = [("home.sections[%d]" % i, x.get("images")) for i, x in enumerate(event.get("home", {}).get("sections", []))]
    for t in topics:
        if isinstance(t.get("demo"), dict):
            img_lists.append(("тема %s/демо" % t.get("n"), t["demo"].get("images")))
        img_lists += [("тема %s/%s" % (t.get("n"), x.get("title")), x.get("images")) for x in t.get("sections", [])]
    for where, imgs in img_lists:
        if imgs is None:
            continue
        if not isinstance(imgs, list):
            err.append("%s: images е списък" % where)
            continue
        for k, im in enumerate(imgs):
            if not isinstance(im, dict) or not im.get("src") or not LOCAL_RE.match(im["src"]) or ".." in im["src"]:
                err.append("%s: images[%d].src — относителен път в папката на събитието (assets/…)" % (where, k))
            elif not str(im.get("alt", "")).strip():
                err.append("%s: images[%d] (%s) — липсва alt: с думи какво има на кадъра" % (where, k, im["src"]))

    forms = event.get("forms", [])
    ids, slugs, tables = set(), set(), set()
    for f in forms:
        where = "въпросник %s" % f.get("id")
        if not f.get("id") or not ID_RE.match(f["id"]):
            err.append("%s: id на латиница" % where)
            continue
        if not f.get("slug") or not SLUG_RE.match(f["slug"]) or f["slug"] in RESERVED_SLUGS \
                or f["slug"].startswith("tema-"):
            err.append("%s: slug е зает или невалиден" % where)
        if f.get("id") in ids or f.get("slug") in slugs:
            err.append("%s: повтарящ се id или slug" % where)
        ids.add(f.get("id"))
        slugs.add(f.get("slug"))
        if event.get("slug"):
            tbl = form_table(event, f)
            if not TABLE_RE.match(tbl) or tbl in tables:
                err.append("%s: таблица „%s“ — латиница, цифри, _ и без повторение" % (where, tbl))
            tables.add(tbl)
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
            looks = re.search(r"(?i)^(ime|name|familiya|telefon|phone|adres)|\b(име|фамилия|телефон|адрес)\b",
                              "%s %s" % (fld.get("id", ""), fld.get("label", "")))
            if looks and fld.get("type") in ("text", "textarea") and not is_personal(fld):
                todo.append("%s/%s: изглежда лично — сложи \"personal\": true, за да се пази отделно от отговорите"
                            % (where, fld.get("id")))
            for other in fld.get("required_if", []):
                if other not in fids:
                    err.append("%s/%s: required_if сочи липсващо поле „%s“" % (where, fld.get("id"), other))
    cta = event.get("cta", {})
    if cta.get("form") and cta["form"] not in ids:
        err.append("cta.form: няма въпросник „%s“" % cta["form"])
    if event.get("slug") and rate_table(event) in tables:
        err.append("server.rate_table: съвпада с таблица на въпросник")
    cfg = event.get("server", {}).get("config_file")
    if cfg and (not re.match(r"^[\w.][\w./-]*$", cfg) or ".." in cfg):
        err.append("server.config_file: път спрямо папката над public_html, без „..“")

    for kind, label in (("speakers", "лектори"), ("partners", "партньори")):
        rel = people_files(event)[kind]
        if not LOCAL_RE.match(rel) or ".." in rel or not rel.endswith(".json"):
            err.append("people.%s_file: относителен .json път" % kind)
        lst = people.get(kind, [])
        if not isinstance(lst, list):
            err.append("%s: трябва да е списък — един запис на човек" % rel)
            continue
        for i, p in enumerate(lst):
            if not isinstance(p, dict) or not (p.get("name") or p.get("slot")):
                err.append("%s[%d]: иска name (потвърден) или slot (за какво търсим човек)" % (rel, i))
                continue
            for key in ("photo", "link"):
                v = p.get(key)
                if v and (not URL_RE.match(v) or ".." in v):
                    err.append("%s[%d].%s: https:// адрес или относителен път" % (rel, i, key))
        confirmed = [p for p in lst if isinstance(p, dict) and p.get("name")]
        if not confirmed:
            todo.append("%s: няма потвърден — показват се празни профили" % label)

    pub = event.get("publish", {})
    forbid = pub.get("forbid_text", [])
    if not isinstance(forbid, list) or not all(isinstance(x, str) and x.strip() for x in forbid):
        err.append("publish.forbid_text: списък от непразни низове")
    for rx in pub.get("forbid_regex", []):
        try:
            re.compile(rx)
        except (re.error, TypeError):
            err.append("publish.forbid_regex: невалиден израз „%s“" % rx)

    marker = pub.get("pending_marker", "[ЧАКА")
    waits = pending(event, marker) + pending(people, marker, "data")
    if waits:
        todo.append("%s: %d места чакат отговор (виж по-долу)" % (marker, len(waits)))
    if not pub.get("indexable"):
        todo.append("публикуване: скрито от търсачките (publish.indexable = false, чака „go“)")
    elif not pub.get("base_url"):
        todo.append("публикуване: без publish.base_url няма sitemap.xml")
    return err, todo


# ---------- HTML ----------

def esc(s):
    return html.escape(str(s), quote=True)


def md(text):
    """Малко markdown в ред: **удебелено** и [текст](https://… или страница.html). Всичко друго се екранира."""
    out = html.escape(str(text), quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"\[([^\]]+)\]\((https://[^)\s\"]+|[\w][\w./#-]*)\)",
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
    t = dict(DEFAULT_THEME)
    t.update({k: v for k, v in theme.items() if isinstance(v, str) and v})
    t.setdefault("hero_bg", t["ink"])
    t.setdefault("hero_ink", t["paper"])
    t.setdefault("font_mono", "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace")
    t.setdefault("font_brand", t["font_display"])
    t.setdefault("accent_text", t["accent"])   # по-тъмен оттенък за дребен текст, когато акцентът е светъл
    t.setdefault("on_accent", "#ffffff")       # текстът върху бутоните
    return (":root{--accent:%(accent)s;--accent-text:%(accent_text)s;--on-accent:%(on_accent)s;--ink:%(ink)s;--paper:%(paper)s;"
            "--hero-bg:%(hero_bg)s;--hero-ink:%(hero_ink)s;--font-display:%(font_display)s;--font-body:%(font_body)s;"
            "--font-mono:%(font_mono)s;--font-brand:%(font_brand)s}" % t)


def page_order(event):
    """Редът на прожекцията през страниците: начало → програма → темите → разписание."""
    return ["index.html", "programa.html"] + [topic_page(t) for t in event.get("topics", [])] + ["razpisanie.html"]


def main_form(event):
    cta = event.get("cta", {})
    return next((f for f in event.get("forms", []) if f["id"] == cta.get("form")), None)


def page(event, name, title, body, demo, current=None, extra_scripts=(), description=None):
    theme = event.get("theme", {})
    pub = event.get("publish", {})
    indexable = bool(pub.get("indexable"))
    robots = "index, follow" if indexable else "noindex, nofollow"
    head = []
    if theme.get("fonts_css"):
        head.append('<link rel="preconnect" href="https://fonts.googleapis.com">'
                    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
                    '<link rel="stylesheet" href="%s">' % esc(theme["fonts_css"]))
    for s in theme.get("stylesheets", []):
        head.append('<link rel="stylesheet" href="%s">' % esc(s))
    base = pub.get("base_url")
    if indexable and base:
        head.append('<link rel="canonical" href="%s">' % esc(base.rstrip("/") + "/" + ("" if name == "index.html" else name)))
    order = page_order(event)
    if name in order:
        k = order.index(name)
        if k > 0:
            head.append('<link rel="prev" href="%s">' % order[k - 1])
        if k < len(order) - 1:
            head.append('<link rel="next" href="%s">' % order[k + 1])
    nav = [("programa.html", "Програмата"), ("razpisanie.html", "Разписание"),
           ("lektori.html", "Лектори"), ("organizatori.html", "Организатори")]
    form = main_form(event)
    if form:
        nav.append((form["slug"] + ".html", event.get("cta", {}).get("label") or form["title"]))
    for f in event.get("forms", []):                 # forms[].nav: true — още формуляри в менюто
        if f.get("nav") and f is not form:
            nav.append((f["slug"] + ".html", f.get("nav_label") or f["title"]))
    nav_html = "".join('<a href="%s"%s>%s</a>' % (h, ' aria-current="page"' if h == current else "", esc(l))
                       for h, l in nav)
    brand = event["brand"]
    ribbon = '<div class="ribbon">%s</div>' % md(brand["ribbon"]) if brand.get("ribbon") else ""
    mark = '<img class="logo" src="%s" alt="%s">' % (esc(brand["logo"]), esc(brand["name"])) if brand.get("logo") \
        else esc(brand["name"])
    legal = esc(brand.get("legal") or brand["name"])
    privacy = ' · <a href="privacy.html">Поверителност</a>' if event.get("privacy") else ""
    scripts = "".join('<script src="assets/%s" defer></script>' % s for s in ("present.js",) + tuple(extra_scripts))
    full_title = title if name == "index.html" else "%s · %s" % (title, event["title"])
    desc = description or event.get("description") or event.get("tagline", "")
    return """<!doctype html>
<html lang="%(lang)s">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<meta name="robots" content="%(robots)s">
<meta name="referrer" content="strict-origin-when-cross-origin">
%(head)s
<style>%(css)s</style>
<link rel="stylesheet" href="assets/style.css">
</head>
<body%(demo)s>
%(ribbon)s
<header class="top"><a class="brand" href="index.html">%(mark)s</a><nav>%(nav)s</nav></header>
<main>
%(body)s
</main>
<footer class="foot"><span>%(legal)s · %(event)s · %(dates)s%(privacy)s</span>
<button type="button" class="present-toggle" data-present-toggle title="Прожекция: P · стрелки · Esc">Прожекция (P)</button></footer>
%(scripts)s
</body>
</html>
""" % {"lang": esc(event.get("lang", "bg")), "title": esc(full_title), "desc": esc("%s · %s" % (desc, date_label(event))),
       "robots": robots, "head": "\n".join(head), "css": theme_css(theme),
       "demo": ' data-demo="1"' if demo else "", "ribbon": ribbon, "mark": mark, "nav": nav_html,
       "body": body, "legal": legal, "event": esc(event["title"]), "dates": esc(date_label(event)),
       "privacy": privacy, "scripts": scripts}


def block(inner, cls="", label=None):
    aria = ' aria-label="%s"' % esc(label) if label else ""
    return '<section class="block %s" data-slide%s>\n<div class="wrap">\n%s\n</div>\n</section>' % (cls, aria, inner)


def cards(items, cls="cards"):
    return '<div class="%s">%s</div>' % (cls, "".join(
        '<article class="card"><h3>%s</h3>%s</article>' % (
            esc(i["title"]), '<p>%s</p>' % md(i["text"]) if i.get("text") else "") for i in items))


def table(tbl):
    head = "".join("<th>%s</th>" % md(h) for h in tbl.get("head", []))
    rows = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % md(c) for c in row) for row in tbl.get("rows", []))
    return '<div class="table-wrap"><table class="grid"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (head, rows)


def images_grid(imgs):
    """Малка решетка от кадри: всеки води към пълния файл; alt е задължителен (check), lazy зареждане."""
    if not imgs:
        return ""
    return '<div class="shots">%s</div>' % "".join(
        '<figure><a href="%s"><img src="%s" alt="%s" loading="lazy"></a>%s</figure>' % (
            esc(i["src"]), esc(i["src"]), esc(i["alt"]),
            '<figcaption>%s</figcaption>' % md(i["caption"]) if i.get("caption") else "") for i in imgs)


def section(s, cls=""):
    """Раздел: заглавие, увод, карти, таблица, списък, кадри — в този ред, каквото има."""
    parts = ['<h2>%s</h2>' % esc(s["title"])]
    if s.get("intro"):
        parts.append('<p class="lead">%s</p>' % md(s["intro"]))
    if s.get("items"):
        parts.append(cards(s["items"]))
    if s.get("table"):
        parts.append(table(s["table"]))
    if s.get("list"):
        parts.append('<ul class="ticks">%s</ul>' % "".join("<li>%s</li>" % md(x) for x in s["list"]))
    if s.get("images"):
        parts.append(images_grid(s["images"]))
    return block("\n".join(parts), s.get("cls", cls), s["title"])


def cta_button(event, cls="btn"):
    form = main_form(event)
    if not form:
        return ""
    return '<a class="%s" href="%s.html">%s</a>' % (cls, esc(form["slug"]), esc(event.get("cta", {}).get("label") or form["title"]))


def hero(kicker, title, lead="", extra=""):
    return block('<p class="kicker">%s</p>\n<h1>%s</h1>\n%s%s' % (
        esc(kicker), esc(title), '<p class="lead">%s</p>\n' % md(lead) if lead else "", extra), "hero small", title)


# ---------- страниците ----------

def home(event, demo):
    place = event.get("place", {})
    top = ('<p class="kicker">%s · %s</p>\n<h1>%s</h1>\n<p class="lead">%s</p>\n'
           '<p class="meta">%s</p>\n%s<p class="actions">%s <a class="btn ghost" href="programa.html">Програмата</a></p>') % (
        esc(date_label(event)), esc(place.get("name", "")), esc(event["title"]), md(event.get("tagline", "")),
        esc(" · ".join(x for x in (place.get("seats"), place.get("note")) if x)),
        '<p class="hero-note">%s</p>\n' % md(event["home"]["hero_note"]) if event.get("home", {}).get("hero_note") else "",
        cta_button(event))
    parts = [block(top, "hero", event["title"])]
    stats = event.get("home", {}).get("stats", [])
    if stats:
        parts.append(block('<div class="stats">%s</div>' % "".join(
            '<div class="stat"><b>%s</b><span>%s</span></div>' % (esc(x["value"]), md(x.get("label", ""))) for x in stats),
            "stats-block", "Накратко"))
    roles = event.get("lab_roles", [])
    if roles:
        parts.append(block("<h2>За кого</h2>\n" + cards([{"title": r["label"], "text": r.get("text", "")} for r in roles],
                                                          "cards four"), "", "За кого"))
    for s in event.get("home", {}).get("sections", []):
        parts.append(section(s))
    topics = event.get("topics", [])
    if topics:
        tiles = "".join('<a class="topic" href="%s"><span class="n">%02d</span><b>%s</b><span>%s</span></a>' % (
            topic_page(t), t["n"], esc(t["title"]), esc(t.get("question") or t.get("summary", ""))) for t in topics)
        parts.append(block('<h2>Темите</h2>\n<div class="topics">%s</div>' % tiles, "", "Темите"))
    days = event.get("schedule", [])
    if days:
        tiles = "".join('<article class="card"><h3>%s</h3><p class="muted">%s</p><p>%s</p></article>' % (
            esc(day.get("label", "")), esc(human_date(day["date"])),
            esc(" · ".join(s["title"] for s in day.get("slots", [])))) for day in days)
        parts.append(block('<h2>Дните</h2>\n<div class="cards">%s</div>\n<p><a href="razpisanie.html">Разписанието по часове →</a></p>'
                           % tiles, "", "Дните"))
    if cta_button(event):
        parts.append(block('<h2>%s</h2>\n<p class="lead">%s</p>\n<p>%s</p>' % (
            esc(event.get("cta", {}).get("label", "")), esc(place.get("seats", "")), cta_button(event)), "cta", "Записване"))
    return page(event, "index.html", event["title"], "\n".join(parts), demo)


def programa(event, demo):
    tiles = "".join('<a class="topic" href="%s"><span class="n">%02d</span><b>%s</b><span>%s</span></a>' % (
        topic_page(t), t["n"], esc(t["title"]), esc(t.get("question") or t.get("summary", "")))
        for t in event.get("topics", []))
    body = hero(date_label(event), "Програмата", event.get("program_intro", "")) + "\n" + \
        block('<div class="topics">%s</div>' % tiles, "", "Темите")
    return page(event, "programa.html", "Програмата", body, demo, current="programa.html")


def topic(event, t, demo):
    topics = event.get("topics", [])
    idx = topics.index(t)
    lead = t.get("question") or t.get("summary", "")
    parts = [hero("Тема %d от %d" % (t["n"], len(topics)), t["title"], lead,
                  '<p class="meta">%s</p>' % md(t["summary"]) if t.get("question") and t.get("summary") else "")]
    if t.get("goals"):
        parts.append(block('<h2>Какво ще можеш</h2>\n<ul class="ticks">%s</ul>' % "".join(
            "<li>%s</li>" % md(g) for g in t["goals"]), "", "Какво ще можеш"))
    if t.get("concepts"):
        parts.append(block('<h2>Понятията</h2>\n<dl class="concepts">%s</dl>' % "".join(
            "<div><dt>%s</dt><dd>%s</dd></div>" % (esc(c["term"]), md(c.get("text", ""))) for c in t["concepts"]),
            "", "Понятията"))
    for s in t.get("sections", []):
        parts.append(section(s))
    if t.get("demo"):
        dm = t["demo"]
        parts.append(block('<h2>%s</h2>\n%s<ol class="steps">%s</ol>' % (
            esc(dm.get("title", "Демо на живо")), '<p class="lead">%s</p>' % md(dm["intro"]) if dm.get("intro") else "",
            "".join("<li>%s</li>" % md(x) for x in dm.get("steps", []))) + images_grid(dm.get("images")),
            "demo", "Демо на живо"))
    roles = event.get("lab_roles", [])
    if roles and t.get("lab") is not False:
        cols = "".join('<article class="lab-col"><h3>%s</h3><ul>%s</ul></article>' % (
            esc(r["label"]), "".join("<li>%s</li>" % md(x) for x in t.get("lab", {}).get(r["id"], []))
            or '<li class="muted">Предстои</li>') for r in roles)
        parts.append(block('<h2>Лаборатория</h2>\n<div class="lab" style="--cols:%d">%s</div>' % (len(roles), cols),
                           "lab-block", "Лаборатория"))
    if t.get("takeaways"):
        parts.append(block('<h2>Какво отнасяш вкъщи</h2>\n<ul class="ticks">%s</ul>' % "".join(
            "<li>%s</li>" % md(x) for x in t["takeaways"]), "", "Какво отнасяш вкъщи"))
    src = t.get("source") or {}
    if str(src.get("text", "")).strip(" -–—"):    # празен текст или само тире — блокът не се показва
        parts.append(block('<h2>%s</h2>\n<p class="lead">%s</p>' % (esc(src.get("title", "Изходник")), md(src.get("text", ""))),
                           "source", "Изходник"))
    nav = []
    if idx > 0:
        nav.append('<a href="%s" rel="prev">← %s</a>' % (topic_page(topics[idx - 1]), esc(topics[idx - 1]["title"])))
    nav.append('<a href="programa.html">Всички теми</a>')
    if idx < len(topics) - 1:
        nav.append('<a href="%s" rel="next">%s →</a>' % (topic_page(topics[idx + 1]), esc(topics[idx + 1]["title"])))
    parts.append('<nav class="pager">%s</nav>' % "".join(nav))
    return page(event, topic_page(t), "Тема %d: %s" % (t["n"], t["title"]), "\n".join(parts), demo,
                current="programa.html", description="Тема %d: %s. %s" % (t["n"], t["title"], lead))


def razpisanie(event, demo):
    by_n = {t["n"]: t for t in event.get("topics", [])}
    parts = [hero("%s · %s" % (date_label(event), event.get("place", {}).get("name", "")), "Разписание",
                  event.get("schedule_intro", ""))]
    for day in event.get("schedule", []):
        rows = []
        for s in day.get("slots", []):
            links = " · ".join('<a href="%s">Тема %d: %s</a>' % (topic_page(by_n[n]), n, esc(by_n[n]["title"]))
                               for n in s.get("topics", []) if n in by_n)
            when = "%s–%s" % (s["from"], s["to"]) if s.get("from") and s.get("to") else (s.get("time") or "")
            rows.append('<tr%s><td class="time">%s</td><td><b>%s</b>%s</td></tr>' % (
                ' class="pause"' if s.get("pause") else "", md(when), esc(s["title"]), "<br>" + links if links else ""))
        parts.append(block('<h2>%s <span class="muted">%s</span></h2>\n%s<table class="slots">%s</table>' % (
            esc(day.get("label", "")), esc(human_date(day["date"])),
            '<p class="lead">%s</p>' % md(day["intro"]) if day.get("intro") else "", "".join(rows)), "", day.get("label")))
    return page(event, "razpisanie.html", "Разписание", "\n".join(parts), demo, current="razpisanie.html")


def person_card(p, kind):
    who = "Лектор" if kind == "speakers" else "Партньор"
    if not p or not p.get("name"):
        slot = (p or {}).get("slot")
        return ('<article class="person empty"><div class="avatar" aria-hidden="true"></div>'
                '<h3>%s</h3><p class="muted">очаква потвърждение</p></article>' % (
                    esc("%s · %s" % (who, slot)) if slot else who))
    photo = '<img class="avatar" src="%s" alt="%s" loading="lazy">' % (esc(p["photo"]), esc(p["name"])) if p.get("photo") \
        else '<div class="avatar" aria-hidden="true"></div>'
    name = esc(p["name"])
    if p.get("link"):
        name = '<a href="%s" rel="noopener">%s</a>' % (esc(p["link"]), name)
    return '<article class="person">%s<h3>%s</h3>%s%s</article>' % (
        photo, name, '<p class="role">%s</p>' % esc(p["role"]) if p.get("role") else "",
        '<p>%s</p>' % md(p["bio"]) if p.get("bio") else "")


def people_grid(event, people, kind):
    """Статични профили (работят и без JS); assets/people.js ги опреснява от data/*.json в движение."""
    lst = [p for p in people.get(kind, []) if isinstance(p, dict)]
    minimum = int(event.get("people", {}).get("placeholders", {}).get(kind, 0))
    lst += [None] * max(0, minimum - len(lst))
    return '<div class="people" data-people="%s" data-min="%d">%s</div>' % (
        esc(people_files(event)[kind]), minimum, "".join(person_card(p, kind) for p in lst))


def lektori(event, people, demo):
    intro = event.get("people", {}).get("speakers_intro", "")
    body = hero(event["title"], "Лектори", intro) + "\n" + block(people_grid(event, people, "speakers"), "people-block", "Лектори")
    return page(event, "lektori.html", "Лектори", body, demo, current="lektori.html", extra_scripts=("people.js",))


def organizatori(event, people, demo):
    orgs = event.get("organizers", [])
    cards_html = "".join('<article class="card org">%s%s<h3>%s</h3>%s</article>' % (
        '<p class="kicker">%s</p>' % esc(o["role"]) if o.get("role") else "",
        '<img class="org-logo" src="%s" alt="%s">' % (esc(o["logo"]), esc(o["name"])) if o.get("logo") else "",
        '<a href="%s" rel="noopener">%s</a>' % (esc(o["link"]), esc(o["name"])) if o.get("link") else esc(o["name"]),
        '<p>%s</p>' % md(o["text"]) if o.get("text") else "") for o in orgs)
    parts = [hero(event["title"], "Организатори", event.get("people", {}).get("organizers_intro", ""))]
    if orgs:
        title = "Организатор" if len(orgs) == 1 else "Организаторите"
        parts.append(block('<h2>%s</h2>\n<div class="cards">%s</div>' % (title, cards_html), "", title))
    parts.append(block('<h2>Партньори</h2>\n' + people_grid(event, people, "partners"), "people-block", "Партньори"))
    return page(event, "organizatori.html", "Организатори", "\n".join(parts), demo, current="organizatori.html",
                extra_scripts=("people.js",))


def privacy(event, demo):
    pv = event["privacy"]
    parts = [hero(event["title"], pv.get("title", "Поверителност"), pv.get("intro", ""))]
    for b in pv.get("blocks", []):
        parts.append(section(b))
    return page(event, "privacy.html", pv.get("title", "Поверителност"), "\n".join(parts), demo)


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
            items += ('<label class="opt other"><input type="%s" name="%s" value="__other"> %s: '
                      '<input type="text" name="%s__other" maxlength="200" aria-label="%s"></label>' % (
                          kind, name, esc(fld.get("other_label", "Друго")), fid, esc(fld.get("other_label", "Друго"))))
        maxn = ' data-max="%d"' % fld["max"] if t == "multi" and fld.get("max") else ""
        hint = '<p class="help">До %d отговора.</p>' % fld["max"] if maxn else ""
        return '<fieldset class="field" data-field="%s"%s><legend>%s%s</legend>%s%s%s</fieldset>' % (
            fid, maxn, esc(fld["label"]), star, help_, hint, items)
    if t == "consent":
        dep = ' data-required-if="%s"' % esc(",".join(fld.get("required_if", []))) if fld.get("required_if") else ""
        return '<div class="field consent"%s><label class="opt"><input type="checkbox" name="%s" value="1"%s> <span>%s%s</span></label>%s</div>' % (
            dep, fid, r, md(fld["label"]), star, help_)
    maxlen = int(fld.get("max_length", 254 if t == "email" else 2000))
    count = '<p class="help count" data-count-for="f-%s">до %d знака</p>' % (fid, maxlen) if t == "textarea" else ""
    if t == "textarea":
        ctl = '<textarea id="f-%s" name="%s" rows="4" maxlength="%d"%s></textarea>' % (fid, fid, maxlen, r)
    else:
        ctl = '<input id="f-%s" type="%s" name="%s" maxlength="%d"%s%s>' % (
            fid, "email" if t == "email" else "text", fid, maxlen, r, ' autocomplete="email"' if t == "email" else "")
    return '<div class="field"><label for="f-%s">%s%s</label>%s%s%s</div>' % (fid, esc(fld["label"]), star, help_, ctl, count)


def form_page(event, f, demo):
    rows = []
    for x in f.get("fields", []):
        if x.get("group"):
            rows.append('<h2 class="group">%s</h2>' % esc(x["group"]))
        rows.append(form_field(x, event))
    note = '<p class="notice">Демо: въпросникът не се изпраща.</p>' if demo else ""
    body = block('<p class="kicker">%s · %s</p>\n<h1>%s</h1>\n<p class="lead">%s</p>\n%s'
                 '<form class="survey" method="post" action="api/submit.php" data-form="%s" novalidate>\n'
                 '<input type="hidden" name="_form" value="%s">\n'
                 '<div class="hp" aria-hidden="true"><label>Не попълвай<input type="text" name="_hp" tabindex="-1" autocomplete="off"></label></div>\n'
                 '<input type="hidden" name="_t" value="">\n%s\n'
                 '<p><button class="btn" type="submit">Изпрати</button></p>\n<p class="status" role="status" aria-live="polite"></p>\n'
                 '</form>' % (esc(event["title"]), esc(date_label(event)), esc(f["title"]), md(f.get("intro", "")), note,
                              esc(f["id"]), esc(f["id"]), "\n".join(rows)),
                 "form-block", f["title"])
    return page(event, f["slug"] + ".html", f["title"], body, demo, current=f["slug"] + ".html",
                extra_scripts=("forms.js",), description="%s: %s" % (f["title"], f.get("intro", "")))


# ---------- сървърът: какво се приема и в коя таблица ----------

def forms_spec(event):
    """Какво приема api/submit.php: само тези полета, типове и опции. Нищо друго не се записва."""
    srv = event.get("server", {})
    out = {"event": event["slug"], "config_file": srv.get("config_file") or ".organizer/%s.php" % event["slug"],
           "rate_table": rate_table(event), "rate_limit_per_hour": int(srv.get("rate_limit_per_hour", 10)),
           "forms": {}}
    for f in event.get("forms", []):
        fields = []
        for x in f.get("fields", []):
            spec = {"id": x["id"], "type": x["type"], "label": x["label"], "required": bool(x.get("required")),
                    "personal": is_personal(x)}
            if x["type"] in ("single", "multi"):
                spec["options"] = resolve_options(x, event)
                spec["other"] = bool(x.get("other"))
                spec["other_label"] = x.get("other_label", "Друго")
            if x["type"] == "multi" and x.get("max"):
                spec["max"] = int(x["max"])
            if x["type"] in ("text", "textarea", "email"):
                spec["max_length"] = int(x.get("max_length", 254 if x["type"] == "email" else 2000))
            if x.get("required_if"):
                spec["required_if"] = list(x["required_if"])
            fields.append(spec)
        out["forms"][f["id"]] = {"title": f["title"], "slug": f["slug"], "table": form_table(event, f),
                                 "contact_table": form_table(event, f) + "_kontakt", "fields": fields}
    return out


def is_personal(field):
    """Сочи ли полето към човек: имейл и съгласие винаги, другото — с "personal": true (напр. име, телефон)."""
    return field.get("type") in ("email", "consent") or bool(field.get("personal"))


def schema_sql(event):
    """sql/schema.sql — пуска го човек (phpMyAdmin); сайтът сам не създава таблици на живо."""
    lines = ["-- Сглобено от Shinkansen организатор за „%s“. Пуска се веднъж в базата (phpMyAdmin → SQL)." % event["slug"],
             "-- Отговорите са JSON в колона answers: само полетата от api/forms.json, без личните.", ""]
    for f in event.get("forms", []):
        lines.append("-- %s" % f["title"].replace("\n", " "))
        lines.append("CREATE TABLE IF NOT EXISTS `%s` (\n"
                     "  id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,\n"
                     "  created_at DATETIME NOT NULL,\n"
                     "  answers MEDIUMTEXT NOT NULL\n"
                     ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;\n" % form_table(event, f))
        if any(is_personal(x) for x in f.get("fields", [])):
            lines.append("-- Личните полета (%s) — отделно от отговорите, за да се трият поотделно:\n"
                         "--   DELETE FROM `%s_kontakt` WHERE response_id = <№ от износа>;"
                         % (", ".join(x["id"] for x in f["fields"] if is_personal(x)), form_table(event, f)))
            lines.append("CREATE TABLE IF NOT EXISTS `%s_kontakt` (\n"
                         "  response_id INT UNSIGNED NOT NULL PRIMARY KEY,\n"
                         "  created_at DATETIME NOT NULL,\n"
                         "  data MEDIUMTEXT NOT NULL\n"
                         ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;\n" % form_table(event, f))
    lines.append("-- Ограничение на изпращанията: HMAC на IP адреса (не самият адрес), пази се един час.")
    lines.append("CREATE TABLE IF NOT EXISTS `%s` (\n"
                 "  ip_hash CHAR(64) NOT NULL,\n"
                 "  created_at DATETIME NOT NULL,\n"
                 "  KEY ip_time (ip_hash, created_at)\n"
                 ") ENGINE=InnoDB DEFAULT CHARSET=ascii;\n" % rate_table(event))
    return "\n".join(lines)


HTACCESS = """# Сглобено от Shinkansen организатор. Подпапката наследява .htaccess на public_html — провери го първо.
Options -Indexes
<IfModule mod_headers.c>
%(robots)s  Header always set X-Content-Type-Options "nosniff"
  Header always set Referrer-Policy "strict-origin-when-cross-origin"
</IfModule>
<FilesMatch "^(forms\\.json|lib\\.php|schema\\.sql|config\\.sample\\.php)$">
  Require all denied
</FilesMatch>
"""


# ---------- проверки след сглобяването ----------

HREF_RE = re.compile(r'\b(?:href|src)="([^"]+)"')


def broken_links(out, written):
    """Вътрешните href/src, които не сочат към файл в изхода. Външните (https:, mailto:) не се пипат."""
    files = set(written)
    bad = []
    for rel in written:
        if not rel.endswith(".html"):
            continue
        with open(os.path.join(out, rel), encoding="utf-8") as f:
            text = f.read()
        for target in HREF_RE.findall(text):
            target = html.unescape(target)
            if re.match(r"^(https?:|mailto:|tel:|#|javascript:)", target) or target.startswith("//"):
                continue
            path = target.split("#")[0].split("?")[0]
            if not path:
                continue
            path = os.path.normpath(os.path.join(os.path.dirname(rel), path)).replace(os.sep, "/")
            if path.endswith("/"):
                path += "index.html"
            if path not in files:
                bad.append((rel, target))
    return bad


def forbidden_hits(out, written, forbid, forbid_regex=()):
    """Стари дати и имена, които не бива да останат никъде в сглобеното (publish.forbid_*)."""
    hits = []
    rx = [re.compile(r) for r in forbid_regex]
    for rel in written:
        if rel.endswith((".png", ".jpg", ".jpeg", ".webp", ".woff", ".woff2", ".ico", ".gif")):
            continue
        with open(os.path.join(out, rel), encoding="utf-8", errors="replace") as f:
            text = f.read()
        plain = html.unescape(text)
        for t in forbid:
            if t in plain:
                hits.append((rel, t))
        for r in rx:
            m = r.search(plain)
            if m:
                hits.append((rel, "%s → „%s“" % (r.pattern, m.group(0))))
    return hits


# ---------- сглобяване ----------

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

    def copy_tree(src, dest_rel):
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                rel = os.path.join(dest_rel, os.path.relpath(os.path.join(dirpath, name), src)).replace(os.sep, "/")
                os.makedirs(os.path.dirname(os.path.join(out, rel)), exist_ok=True)
                shutil.copyfile(os.path.join(dirpath, name), os.path.join(out, rel))
                if rel not in written:
                    written.append(rel)

    copy_tree(os.path.join(HERE, "assets"), "assets")
    if os.path.isdir(os.path.join(folder, "assets")):
        copy_tree(os.path.join(folder, "assets"), "assets")   # лого, локални шрифтове — на събитието

    write("index.html", home(event, demo))
    write("programa.html", programa(event, demo))
    for t in event.get("topics", []):
        write(topic_page(t), topic(event, t, demo))
    write("razpisanie.html", razpisanie(event, demo))
    write("lektori.html", lektori(event, people, demo))
    write("organizatori.html", organizatori(event, people, demo))
    if event.get("privacy"):
        write("privacy.html", privacy(event, demo))
    for f in event.get("forms", []):
        write(f["slug"] + ".html", form_page(event, f, demo))
    for kind, rel in people_files(event).items():
        write(rel, json.dumps(people.get(kind, []), ensure_ascii=False, indent=1) + "\n")

    indexable = bool(event.get("publish", {}).get("indexable"))
    if not demo and event.get("forms"):
        write("api/forms.json", json.dumps(forms_spec(event), ensure_ascii=False, indent=1) + "\n")
        for name in ("lib.php", "submit.php"):
            with open(os.path.join(HERE, "php", name), encoding="utf-8") as f:
                write("api/" + name, f.read())
        with open(os.path.join(HERE, "php", "export.php"), encoding="utf-8") as f:
            write("admin/export.php", f.read())
        write("sql/schema.sql", schema_sql(event))
        with open(os.path.join(HERE, "php", "config.sample.php"), encoding="utf-8") as f:
            write("sql/config.sample.php", f.read())
        write("sql/.htaccess", "Require all denied\n")
    write(".htaccess", HTACCESS % {"robots": "" if indexable else '  Header always set X-Robots-Tag "noindex, nofollow"\n'})
    base = event.get("publish", {}).get("base_url")
    if indexable and base:
        pages = [p for p in written if p.endswith(".html")]
        write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n'
              % "".join("  <url><loc>%s</loc></url>\n" % esc(base.rstrip("/") + "/" + ("" if p == "index.html" else p)) for p in pages))

    problems = ["счупена връзка в %s: %s" % hit for hit in broken_links(out, written)]
    pub = event.get("publish", {})
    problems += ["забранен текст „%s“ в %s" % (t, rel)
                 for rel, t in forbidden_hits(out, written, pub.get("forbid_text", []), pub.get("forbid_regex", []))]
    if problems:
        raise ValueError("\n".join(problems))
    return written, todo


def cmd_new(dest):
    if os.path.exists(os.path.join(dest, "event.json")):
        print("%s: вече има event.json — нищо не пипам" % dest, file=sys.stderr)
        return 2
    for dirpath, _, filenames in os.walk(EXAMPLE):
        for name in filenames:
            src = os.path.join(dirpath, name)
            dst = os.path.join(dest, os.path.relpath(src, EXAMPLE))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
    print("ново събитие: %s (копие на примера — смени slug, заглавие, дати)" % dest)
    return 0


def report(errors, todo, waits=()):
    for e in errors:
        print("ГРЕШКА  " + e)
    for t in todo:
        print("липсва  " + t)
    for path, text in waits:
        print("чака    %s: %s" % (path, text if len(text) <= 90 else text[:87] + "…"))
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
    pk = sub.add_parser("package", help="tgz + SHA-256 + списък на файловете + разлика спрямо предишния")
    pk.add_argument("site")
    pk.add_argument("out")
    pk.add_argument("--prev", help="предишен пакет (.tgz / .manifest.txt) или папка")
    pk.add_argument("--name", help="начало на името на пакета (по подразбиране — името на папката)")
    q = sub.add_parser("qa", help="проверка A5: сглобяване, въпросниците на живо (PHP + SQLite), 360/1440 px")
    q.add_argument("folder")
    q.add_argument("report")
    q.add_argument("--no-shots", action="store_true", help="без браузъра")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if args.cmd == "new":
        return cmd_new(args.folder)
    if args.cmd == "package":
        import ops
        try:
            r = ops.package(args.site, args.out, name=args.name, prev=args.prev)
        except (OSError, ValueError) as e:
            print("пакет: %s" % e, file=sys.stderr)
            return 1
        print("%s%s · %d файла · %d байта" % (r["tgz"], " (вече го има — същото съдържание)" if r["existed"] else "",
                                            r["files"], r["bytes"]))
        print("sha256 %s" % r["sha256"])
        if r["diff"] is not None:
            import ops as _o
            print(_o.diff_text(r["diff"]), end="")
        return 0
    if args.cmd == "qa":
        import ops
        path, failed = ops.qa(args.folder, args.report, shots=not args.no_shots, build=build)
        print("отчет: %s · %s" % (path, "всичко минава" if not failed else "%d неуспешни" % failed))
        return 1 if failed else 0
    try:
        event, people = load(args.folder)
    except (OSError, ValueError) as e:
        print("не мога да прочета %s: %s" % (args.folder, e), file=sys.stderr)
        return 1
    errors, todo = check(event, people)
    marker = event.get("publish", {}).get("pending_marker", "[ЧАКА")
    waits = pending(event, marker) + pending(people, marker, "data")
    if args.cmd == "check":
        report(errors, todo, waits)
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
    report([], todo, waits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
