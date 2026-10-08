"""Частната база: един JSON файл на проверка в `rezultati/<id>.json`. Нищо не се презаписва.

Записът пази снимката (заявките с телата им), резултата от правилника, политиката и изпита — така всяка
находка може да се проследи до доказателството си. Папката е в .gitignore и живее само на машината.
"""
import json
import os
import re


class GreshkaBaza(Exception):
    pass


def _slug(host):
    return re.sub(r"[^a-z0-9.-]+", "-", (host or "sayt").lower()).strip("-") or "sayt"


def nov_id(papka, den, host):
    osnova = "%s-%s" % (den.replace("-", ""), _slug(host))
    n = 1
    while os.path.exists(os.path.join(papka, "%s-%d.json" % (osnova, n))):
        n += 1
    return "%s-%d" % (osnova, n)


def zapishi(papka, zapis):
    os.makedirs(papka, exist_ok=True)
    pat = os.path.join(papka, zapis["id"] + ".json")
    if os.path.exists(pat):
        raise GreshkaBaza("%s вече съществува — нищо не се презаписва" % pat)
    with open(pat, "x", encoding="utf-8") as f:
        json.dump(zapis, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return pat


def zaredi(papka, rid):
    if not re.fullmatch(r"[A-Za-z0-9.-]+", rid or ""):
        raise GreshkaBaza("непознат id „%s“" % rid)
    pat = os.path.join(papka, rid + ".json")
    try:
        with open(pat, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise GreshkaBaza("няма проверка с id „%s“ в %s" % (rid, papka))
    except ValueError as e:
        raise GreshkaBaza("%s е неразбираем: %s" % (pat, e))
