"""Общо за тестовете: измислена база на филтъра с измислени канали. Нула мрежа, нищо истинско.

Базата се прави със схемата на самия филтър (apps/filtar/filtar/baza.py), за да се хване всяка промяна в нея.
"""
import copy
import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(os.path.dirname(APP), "filtar"))

from filtar import baza  # noqa: E402
from iq import config  # noqa: E402

CFG_PAT = os.path.join(APP, "config.example.json")
CFG = config.zaredi(CFG_PAT)
DO = date(2026, 9, 27)
OSI = ("reputaciya", "proverimost", "prozrachnost", "originalnost", "obshtestven_interes", "manipulaciya", "palnota")

# id, име, оценки (в цикъл), дял с именувани източници, записи с похват, дни история, записи в прозореца
KANALI = [
    ("primeren-glas", "Примерен глас", [9.2, 9.4, 9.1, 9.3], 1.0, 0, 400, 40),
    ("primeren-vestnik", "Примерен вестник", [8.0, 8.2, 7.9, 8.3], 0.85, 1, 200, 40),
    ("primeren-portal", "Примерен портал", [6.5, 6.8, 6.2, 6.9], 0.5, 3, 120, 40),
    ("primeren-byuletin", "Примерен бюлетин", [5.0, 4.8, 5.3, 4.9], 0.3, 12, 120, 40),
    ("primeren-blog", "Примерен блог", [8.0], 1.0, 0, 20, 10),
    ("primeren-sayt", "Примерен сайт", [6.5, 6.8, 6.2, 6.9], 0.5, 3, 120, 40),
]

REGISTAR = [
    {"id": "primeren-glas", "ime": "Примерен глас", "url": "https://example.org/glas/", "saglasie": True},
    {"id": "primeren-vestnik", "ime": "Примерен вестник", "url": "https://example.org/", "saglasie": True},
    {"id": "primeren-portal", "ime": "Примерен портал", "url": "https://example.org/portal/", "saglasie": True},
    {"id": "primeren-byuletin", "ime": "Примерен бюлетин", "url": "https://example.org/byuletin/"},
    {"id": "primeren-blog", "ime": "Примерен блог", "url": "https://example.net/blog/", "saglasie": "да"},
    {"id": "primeren-sayt", "ime": "Примерен сайт", "url": "https://example.net/", "saglasie": True,
     "spryana": {"osnovanie": "Измислено решение за теста.", "rolya": "редакционен съвет", "data": "2026-09-15"}},
]

POHVATI = [("Анонимен авторитет", "Експертите смятат, че промяната е наложителна."),
           ("Апел към страх", "Заплахата е огромна, а опасността расте всеки ден.")]


def cfg():
    return copy.deepcopy(CFG)


def doverie(ocenka, prozrachnost, pohvati):
    osi = [{"kluch": k, "ocenka": prozrachnost if k == "prozrachnost" else ocenka} for k in OSI]
    return {"rezhim": "bez-model", "reshenie": {"kod": "PROPUSNI"}, "osi": osi,
            "pohvati": [{"ime": i, "otkas": o} for i, o in pohvati], "za_chitatelya": "",
            "profil": {"uverenost": {"nivo": "ниска", "prichini": []},
                       "pokritie_s_dokazatelstva": {}, "chovek": "не"}}


def dobavi(b, izvor, ime, den, ocenka, prozrachnost=10.0, pohvati=(), n=[0]):
    n[0] += 1
    b.execute("INSERT INTO zapisi (izvor, izvor_ime, kluch, url, zaglavie, tekst, data, sabrano, sastoyanie, "
              "reshenie, ocenka, doverie) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (izvor, ime, "%s-%d" % (izvor, n[0]), "https://example.org/%s/%d" % (izvor, n[0]),
               "Примерна статия %d" % n[0], "измислен текст", den.isoformat() + "T08:00:00+03:00",
               den.isoformat() + "T09:00:00+00:00", "obraboten", "ПРОПУСНИ", ocenka,
               json.dumps(doverie(ocenka, prozrachnost, pohvati), ensure_ascii=False)))


def napravi_baza(papka, do=DO):
    b = baza.otvori(papka)
    for kid, ime, ocenki, imenuvani, s_pohvat, istoriya, n in KANALI:
        dobavi(b, kid, ime, do - timedelta(days=istoriya - 1), ocenki[0])  # най-старият запис — извън прозореца
        for i in range(n):
            den = do - timedelta(days=i % 28)
            proz = 10.0 if i < round(imenuvani * n) else 3.0
            poh = [POHVATI[i % 2]] if i < s_pohvat else []
            dobavi(b, kid, ime, den, ocenki[i % len(ocenki)], proz, poh)
    # записи без оценка на Z7 (отпаднали на слой 1–3) не влизат в сметката
    b.execute("INSERT INTO zapisi (izvor, izvor_ime, kluch, data, sastoyanie, reshenie) VALUES "
              "('primeren-blog', 'Примерен блог', 'blog-otkaz', ?, 'obraboten', 'ОТКАЗ')", (do.isoformat(),))
    b.commit()
    b.close()


class Papka:
    """Временна папка: danni/filtar.sqlite, kanali.json, iq/ за историята."""

    def __enter__(self):
        self.d = tempfile.mkdtemp()
        self.danni = os.path.join(self.d, "danni")
        self.iq = os.path.join(self.d, "iq")
        self.kanali = os.path.join(self.d, "kanali.json")
        napravi_baza(self.danni)
        with open(self.kanali, "w", encoding="utf-8") as f:
            json.dump(REGISTAR, f, ensure_ascii=False)
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.d)


ZABRANENI = ("дезинформация", "фалшиви новини", "лъжа", "лъже")
