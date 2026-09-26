#!/usr/bin/env python3
"""Сглобява публичната витрина: една страница, двуезична, без CDN.

    python3 site/showcase/build.py ИЗХОДНА_ПАПКА [--repo-url URL] [--commit SHA]

Каталогът на помощниците се генерира тук, от skills/*/SKILL.md (име, ниво, описание;
английското — от metadata.description_en). Правилата идват от PROTOCOL.md, уроците — от
docs/STORY.md; английските им версии са в en.json и броят трябва да съвпада, иначе
сглобяването спира (код 1) — за да не се разминат двата езика тихо.
"""
import argparse
import html
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPO_URL = "https://github.com/galinpd-lgtm/Shinkansen"

LEVEL_EN = {"чете": "reads", "чернови": "drafts", "действа": "acts"}
LEVEL_ORDER = {"чете": 0, "чернови": 1, "действа": 2}


def load_dispatcher():
    """Функциите за четене на SKILL.md са в bin/shinkansen — ползваме същите, не копие."""
    path = os.path.join(ROOT, "bin", "shinkansen")
    loader = importlib.machinery.SourceFileLoader("shinkansen_bin", path)
    spec = importlib.util.spec_from_loader("shinkansen_bin", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def inline_md(text):
    """Малко markdown в ред: **удебелено**, `код`, [текст](адрес). Всичко друго се екранира."""
    out = html.escape(text, quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                 lambda m: '<a href="%s">%s</a>' % (html.escape(m.group(2)), m.group(1)), out)
    return out


def numbered_list(md, start_heading=None):
    """Номерираните редове („1. …“) от markdown; по желание само след дадено заглавие."""
    if start_heading:
        i = md.find(start_heading)
        if i < 0:
            raise ValueError("липсва заглавие: %s" % start_heading)
        md = md[i + len(start_heading):]
        nxt = re.search(r"^#{1,6} ", md, re.M)
        md = md[:nxt.start()] if nxt else md
    return [m.group(1).strip() for m in re.finditer(r"^\d+\.\s+(.+)$", md, re.M)]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def skill_cards(skills, repo_url):
    """Картите на каталога. Подредба: по ниво (чете → действа), после по име."""
    cards = []
    for s in sorted(skills, key=lambda s: (LEVEL_ORDER.get(s["level"], 9), s["dir"])):
        level = s["level"] or "?"
        en = s["metadata"].get("description_en")
        desc_en = inline_md(en) if en else '<span class="muted">(Bulgarian only)</span> ' + \
            inline_md(s["description"])
        src = "%s/blob/main/skills/%s/SKILL.md" % (repo_url, s["dir"])
        cards.append(
            '<article class="skill lvl-%(cls)s">\n'
            '  <header><h3><code>%(name)s</code></h3>'
            '<span class="badge"><span lang="bg">%(lvl)s</span><span lang="en">%(lvl_en)s</span></span></header>\n'
            '  <p lang="bg">%(bg)s</p>\n  <p lang="en">%(en)s</p>\n'
            '  <p class="run"><code>bin/shinkansen run %(name)s</code> · <a href="%(src)s">SKILL.md</a></p>\n'
            '</article>' % {
                "cls": {"чете": "read", "чернови": "draft", "действа": "act"}.get(level, "x"),
                "name": html.escape(s["dir"]), "lvl": html.escape(level),
                "lvl_en": LEVEL_EN.get(level, level), "bg": inline_md(s["description"]), "en": desc_en,
                "src": html.escape(src)})
    return "\n".join(cards)


def ol(items_bg, items_en):
    bg = "".join("<li>%s</li>" % inline_md(x) for x in items_bg)
    en = "".join("<li>%s</li>" % inline_md(x) for x in items_en)
    return '<ol lang="bg">%s</ol>\n<ol lang="en">%s</ol>' % (bg, en)


def build(out_dir, repo_url=REPO_URL, commit=None, now=None):
    sk = load_dispatcher()
    skills = sk.find_skills(os.path.join(ROOT, "skills"))
    if not skills:
        raise ValueError("няма скилове в skills/")
    en = json.loads(read(os.path.join(HERE, "en.json")))
    protocol_bg = numbered_list(read(os.path.join(ROOT, "PROTOCOL.md")))
    lessons_bg = numbered_list(read(os.path.join(ROOT, "docs", "STORY.md")), "## Уроците от първата вечер")
    for key, bg in (("protocol", protocol_bg), ("lessons", lessons_bg)):
        if len(bg) != len(en[key]):
            raise ValueError("%s: %d правила на български, %d на английски — обнови site/showcase/en.json"
                             % (key, len(bg), len(en[key])))
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    if commit:
        stamp += ' · <a href="%s/commit/%s"><code>%s</code></a>' % (html.escape(repo_url), html.escape(commit),
                                                                     html.escape(commit[:7]))
    counts = {l: sum(1 for s in skills if s["level"] == l) for l in LEVEL_ORDER}
    page = read(os.path.join(HERE, "template.html"))
    values = {
        "SKILLS": skill_cards(skills, repo_url),
        "SKILL_COUNT": str(len(skills)),
        "COUNT_READ": str(counts["чете"]), "COUNT_DRAFT": str(counts["чернови"]), "COUNT_ACT": str(counts["действа"]),
        "PROTOCOL": ol(protocol_bg, en["protocol"]),
        "LESSONS": ol(lessons_bg, en["lessons"]),
        "REPO": html.escape(repo_url),
        "BUILT": stamp,
    }
    for k, v in values.items():
        page = page.replace("{{%s}}" % k, v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", page)
    if left:
        raise ValueError("непопълнени места в шаблона: %s" % ", ".join(sorted(set(left))))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path, skills


def main(argv=None):
    ap = argparse.ArgumentParser(description="Сглобява витрината на Shinkansen.")
    ap.add_argument("out", help="изходна папка (напр. _site/showcase)")
    ap.add_argument("--repo-url", default=os.environ.get("SHOWCASE_REPO_URL") or REPO_URL)
    ap.add_argument("--commit", default=os.environ.get("GITHUB_SHA"))
    a = ap.parse_args(argv)
    try:
        path, skills = build(a.out, a.repo_url, a.commit)
    except (ValueError, OSError, KeyError) as e:
        print("витрината не е сглобена: %s" % e, file=sys.stderr)
        return 1
    print("%s · %d помощника: %s" % (path, len(skills), ", ".join(s["dir"] for s in skills)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
