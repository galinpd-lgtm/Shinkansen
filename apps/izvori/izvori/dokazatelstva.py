"""Доказателствата: `dokazatelstva/<id>/<дата>.json`. Само се добавя — нищо не се презаписва.

Втора проверка в същия ден отива в `<дата>-2.json`, `<дата>-3.json` и т.н. (файлът се отваря с „x“).
"""
import json
import os
import re

IME = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(\d+))?\.json$")


def papka(osnova, izvor_id):
    return os.path.join(osnova, izvor_id)


def zapishi(osnova, izvor_id, den, dok):
    d = papka(osnova, izvor_id)
    os.makedirs(d, exist_ok=True)
    n = 1
    while True:
        ime = "%s.json" % den if n == 1 else "%s-%d.json" % (den, n)
        pat = os.path.join(d, ime)
        try:
            with open(pat, "x", encoding="utf-8") as f:
                json.dump(dok, f, ensure_ascii=False, indent=2)
                f.write("\n")
            return pat
        except FileExistsError:
            n += 1


def spisak(osnova, izvor_id):
    """Файловете на източника по ред на записване."""
    d = papka(osnova, izvor_id)
    if not os.path.isdir(d):
        return []
    imena = []
    for ime in os.listdir(d):
        m = IME.match(ime)
        if m:
            imena.append(((m.group(1), int(m.group(2) or 1)), ime))
    return [os.path.join(d, ime) for _, ime in sorted(imena)]


def posledno(osnova, izvor_id):
    fayl = spisak(osnova, izvor_id)
    if not fayl:
        return None
    with open(fayl[-1], encoding="utf-8") as f:
        return json.load(f)
