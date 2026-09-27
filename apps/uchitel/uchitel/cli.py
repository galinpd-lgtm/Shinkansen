"""python -m uchitel proveri      <папка> [--config kanon.json] [--format tekst|json]
python -m uchitel prebrandirai <папка> --izhod <нова_папка> [--go] [--config kanon.json]
python -m uchitel otchet       <папка> [--izhod <папка_за_отчета>] [--config kanon.json]

Кодове на изход: 0 готово, всичко е по канона · 4 има нарушения или файлове „за ръчно“ · 1 грешка ·
2 грешна употреба (няма такава папка, изходът е във входа или вече е пълен).
"""
import argparse
import json
import os
import sys

from . import obhod, otchet, pravila
from .kanon import GreshkaKanon, zaredi, znak_data_uri

IZHOD_OK, IZHOD_GRESHKA, IZHOD_UPOTREBA, IZHOD_NAMERENO = 0, 1, 2, 4


def parser():
    p = argparse.ArgumentParser(prog="python -m uchitel",
                                description="Проверява HTML обученията по канона и ги привежда към него.")
    sub = p.add_subparsers(dest="komanda", required=True)
    pr = sub.add_parser("proveri", help="отчет: всеки файл × всяко правило")
    pr.add_argument("papka")
    pr.add_argument("--config", help="път до kanon.json")
    pr.add_argument("--format", choices=("tekst", "json"), default="tekst")
    pr.add_argument("--kratko", action="store_true", help="без бележките под всеки файл")
    pb = sub.add_parser("prebrandirai", help="лого, шрифтове, етикети → нова папка (с --go)")
    pb.add_argument("papka")
    pb.add_argument("--izhod", required=True, help="нова папка — никога входът")
    pb.add_argument("--go", action="store_true", help="наистина пиши; без него — само отчет и разлика")
    pb.add_argument("--config", help="път до kanon.json")
    pb.add_argument("--redove", type=int, default=60, help="най-много редове разлика на файл (без --go)")
    pb.add_argument("--otchet", help="къде да са отчетите (по подразбиране <изход>.otchet до изхода)")
    ot = sub.add_parser("otchet", help="Markdown + CSV: по папки, по правила, „за ръчно“")
    ot.add_argument("papka")
    ot.add_argument("--izhod", default="uchitel_otchet", help="папка за отчета (извън входа)")
    ot.add_argument("--config", help="път до kanon.json")
    return p


def _json(zapisi):
    r = []
    for _a, z in zapisi:
        r.append({"fail": z.rel, "sastoyanie": z.status, "sha256": z.sha_predi,
                  "pravila": [x.kato_dict() for x in z.rezultati],
                  "za_rachno": [{"pravilo": p, "belezhka": b} for p, b, _z in z.za_rachno()]})
    return json.dumps(r, ensure_ascii=False, indent=2)


def _kod(zapisi):
    for _a, z in zapisi:
        if z.status == obhod.ZA_RACHNO or any(r.status == pravila.NARUSHENIE for r in z.rezultati):
            return IZHOD_NAMERENO
    return IZHOD_OK


def _proveri(a, k):
    zapisi = obhod.obhodi(a.papka, k)
    print(_json(zapisi) if a.format == "json" else otchet.konzola(zapisi, podrobno=not a.kratko))
    return _kod(zapisi)


def _prebrandirai(a, k):
    obhod.proveri_izhod(a.papka, a.izhod)
    papka_otchet = a.otchet or os.path.abspath(a.izhod).rstrip(os.sep) + ".otchet"
    if obhod.e_vatre(papka_otchet, a.papka):
        raise obhod.GreshkaPat("отчетът %s е във входа — отказвам" % papka_otchet)
    zapisi = obhod.obhodi(a.papka, k, znak=znak_data_uri(k))
    print(otchet.konzola(zapisi))
    if not a.go:
        r = otchet.razlika(zapisi, a.redove)
        if r:
            print("\nРазлика (нищо не е записано — пусни с --go):\n" + r)
        else:
            print("\nНяма какво да се промени. Нищо не е записано.")
        return _kod(zapisi)
    obhod.zapishi(a.papka, a.izhod, zapisi)
    imena = otchet.zapishi(papka_otchet, zapisi, "Учител — пребрандиране", a.papka, a.izhod, k["_pat"])
    print("\nЗаписано в %s. Отчет: %s (%s). Входът не е пипан." % (a.izhod, papka_otchet, ", ".join(imena)))
    return IZHOD_NAMERENO if any(z.status == obhod.ZA_RACHNO for _a, z in zapisi) else IZHOD_OK


def _otchet(a, k):
    if obhod.e_vatre(a.izhod, a.papka):
        raise obhod.GreshkaPat("отчетът %s е във входа — отказвам" % a.izhod)
    zapisi = obhod.obhodi(a.papka, k)
    imena = otchet.zapishi(a.izhod, zapisi, "Учител — проверка по канона", a.papka, kanon=k["_pat"])
    print(otchet.obobshtenie(zapisi))
    print("Отчет: %s (%s)" % (a.izhod, ", ".join(imena)))
    return IZHOD_OK


def main(argv=None):
    a = parser().parse_args(argv)
    if not os.path.isdir(a.papka):
        print("грешка: няма такава папка: %s" % a.papka, file=sys.stderr)
        return IZHOD_UPOTREBA
    try:
        k = zaredi(a.config)
        return {"proveri": _proveri, "prebrandirai": _prebrandirai, "otchet": _otchet}[a.komanda](a, k)
    except obhod.GreshkaPat as e:
        print("грешка: %s" % e, file=sys.stderr)
        return IZHOD_UPOTREBA
    except GreshkaKanon as e:
        print("грешка: %s" % e, file=sys.stderr)
        return IZHOD_GRESHKA
