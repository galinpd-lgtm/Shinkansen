"""python -m doverie ocenka --tekst file.txt | --url … [--bez-model] [--format json|tekst] [--zapazi]
python -m doverie proveri --zapis <N> --ot <роля> [--baza filtar.sqlite]   # запис от радара (основният случай)
python -m doverie proveri --id <id> --ot <роля>                             # самостоятелна оценка от --zapazi
python -m doverie serve [--port 8765]

Кодове на изход: 0 готово · 4 не е безопасно сега — машината е заета/гореща, вратата не отговаря или няма
gate_url (моделът не е викан; опитай по-късно) · 1 грешка · 2 грешна употреба.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone

from . import VERSIYA
from .config import GreshkaConfig, zaredi
from .model import GreshkaModel, Model
from .ocenka import CHOVEK, ocenka, otchet
from .tekst import ot_html
from .vrata import VrataGreshka, VrataLipsva, VrataNeBezopasno, VrataZaeta

IZHOD_OK, IZHOD_GRESHKA, IZHOD_ZAETO = 0, 1, 4


def izteghli(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "doverie/%s" % VERSIYA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        surovo = r.read(2_000_000)
        kodirovka = r.headers.get_content_charset() or "utf-8"
        vid = r.headers.get_content_type()
    t = surovo.decode(kodirovka, "replace")
    return ot_html(t) if "html" in vid else t


def dnevnik(ok, obobshtenie):
    """Ред в $SHINKANSEN_RUNS/doverie.jsonl — без нищо от входа. Под диспечера — във файла му."""
    sf = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if sf:
        with open(sf, "w", encoding="utf-8") as f:
            f.write(obobshtenie)
        return
    runs = os.environ.get("SHINKANSEN_RUNS")
    if not runs:
        return
    os.makedirs(runs, exist_ok=True)
    zap = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "helper": "doverie",
           "ok": bool(ok), "summary": obobshtenie[:200]}
    with open(os.path.join(runs, "doverie.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(zap, ensure_ascii=False) + "\n")


def parser():
    p = argparse.ArgumentParser(prog="python -m doverie", description="Оценка на достоверността на текст.")
    sub = p.add_subparsers(dest="komanda", required=True)
    o = sub.add_parser("ocenka", help="оценява един текст")
    vh = o.add_mutually_exclusive_group(required=True)
    vh.add_argument("--tekst", help="файл с текста (- за стандартния вход)")
    vh.add_argument("--url", help="адрес на статията")
    o.add_argument("--iztochnik", help="домейн на източника, ако не е ясен от --url (напр. example.org)")
    o.add_argument("--avtor", help="автор — пази се в изхода, не се оценява")
    o.add_argument("--bez-model", action="store_true", help="само правила и евристики, без Ollama")
    o.add_argument("--config", help="път до config.json")
    o.add_argument("--pamet", help="файл с видени текстове за оста „оригиналност“ (замества config)")
    o.add_argument("--zapomni", action="store_true", help="добави текста в паметта след оценката")
    o.add_argument("--format", choices=("json", "tekst"), default="json")
    o.add_argument("--zapazi", action="store_true", help="запази резултата в архива (config „arhiv“) по неговото id")
    o.add_argument("--arhiv", help="папката на архива (замества config)")
    pr = sub.add_parser("proveri", help="отбелязва оценка като „проверено от човек“")
    koya = pr.add_mutually_exclusive_group(required=True)
    koya.add_argument("--zapis", type=int, help="номер на записа в базата на филтъра (радарът)")
    koya.add_argument("--id", help="id на самостоятелна оценка, запазена с ocenka --zapazi")
    pr.add_argument("--ot", required=True, help="роля от config „proverka_roli“ — ролята, не името")
    pr.add_argument("--config", help="път до config.json")
    pr.add_argument("--arhiv", help="папката на архива (замества config)")
    pr.add_argument("--baza", help="базата на филтъра filtar.sqlite (замества config „filtar_baza“)")
    s = sub.add_parser("serve", help="HTTP на 127.0.0.1: POST /ocenka")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--config", help="път до config.json")
    s.add_argument("--bez-model", action="store_true", help="сървърът никога не вика модела")
    return p


def _ocenka(a):
    cfg = zaredi(a.config)
    if a.pamet:
        cfg["pamet"] = a.pamet
    if a.url:
        tekst = izteghli(a.url)
        iztochnik = a.iztochnik or a.url
    elif a.tekst == "-":
        tekst, iztochnik = sys.stdin.read(), a.iztochnik
    else:
        with open(a.tekst, encoding="utf-8") as f:
            tekst = f.read()
        iztochnik = a.iztochnik
    if not tekst.strip():
        raise ValueError("празен текст")
    model = None if a.bez_model else Model(cfg)
    rez = ocenka(tekst, cfg, model=model, iztochnik=iztochnik, avtor=a.avtor, zapomni=a.zapomni)
    if a.zapazi:
        path = os.path.join(_arhiv(a, cfg), "%s.json" % rez["id"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rez, f, ensure_ascii=False, indent=2)
        print("запазено: %s" % path, file=sys.stderr)
    return rez


def _arhiv(a, cfg):
    papka = a.arhiv or cfg.get("arhiv")
    if not papka:
        raise ValueError("няма архив — задай „arhiv“ в конфигурацията или --arhiv")
    os.makedirs(papka, exist_ok=True)
    return papka


def proveri(a):
    """→ код. Само роля от config („методист“, „редактор“…), никога име на човек."""
    cfg = zaredi(a.config)
    roli = cfg.get("proverka_roli") or []
    if a.ot not in roli:
        print("грешка: ролята трябва да е една от: %s (ролята, не името)" % ", ".join(roli), file=sys.stderr)
        return 2
    pregled = {"rolya": a.ot, "data": datetime.now(timezone.utc).date().isoformat()}
    if a.zapis is not None:
        return _proveri_zapis(a, cfg, pregled)
    if not re.fullmatch(r"[0-9a-f]{16}", a.id):
        print("грешка: id е 16 знака от 0-9 и a-f", file=sys.stderr)
        return 2
    path = os.path.join(_arhiv(a, cfg), "%s.json" % a.id)
    with open(path, encoding="utf-8") as f:
        rez = json.load(f)
    rez["profil"]["chovek"] = CHOVEK[2]
    rez["profil"]["pregled"] = pregled
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rez, f, ensure_ascii=False, indent=2)
    print("%s: %s (%s)" % (a.id, CHOVEK[2], a.ot))
    return 0


def _proveri_zapis(a, cfg, pregled):
    """Записът от радара: профилът в колоната doverie на базата на филтъра. Базата трябва да съществува."""
    path = a.baza or cfg.get("filtar_baza")
    if not path:
        raise ValueError("няма база на филтъра — задай „filtar_baza“ в конфигурацията или --baza")
    if not os.path.exists(path):
        raise ValueError("няма такава база: %s" % path)
    b = sqlite3.connect("file:%s?mode=rw" % path, uri=True)
    try:
        r = b.execute("SELECT doverie FROM zapisi WHERE id=?", (a.zapis,)).fetchone()
        if r is None:
            raise ValueError("в базата няма запис %d" % a.zapis)
        if not r[0]:
            raise ValueError("запис %d няма оценка на Z7 (отпаднал е преди нея)" % a.zapis)
        dov = json.loads(r[0])
        pr = dov.setdefault("profil", {})
        pr["chovek"] = CHOVEK[2]
        pr["pregled"] = pregled
        b.execute("UPDATE zapisi SET doverie=? WHERE id=?", (json.dumps(dov, ensure_ascii=False), a.zapis))
        b.commit()
    finally:
        b.close()
    print("запис %d: %s (%s)" % (a.zapis, CHOVEK[2], a.ot))
    return 0


def main(argv=None):
    a = parser().parse_args(argv)
    if a.komanda == "proveri":
        try:
            kod = proveri(a)
        except (GreshkaConfig, OSError, ValueError, KeyError) as e:
            print("грешка: %s" % e, file=sys.stderr)
            kod = 1
        dnevnik(kod == 0, "проверка · exit %d" % kod)
        return kod
    if a.komanda == "serve":
        from .serve import pusni
        try:
            return pusni(zaredi(a.config), a.port, bez_model=a.bez_model)
        except GreshkaConfig as e:
            print("грешка: %s" % e, file=sys.stderr)
            return IZHOD_GRESHKA

    t0 = time.monotonic()
    try:
        rez = _ocenka(a)
    except VrataNeBezopasno as e:
        vid = {VrataZaeta: "заето", VrataGreshka: "вратата не отговаря", VrataLipsva: "няма врата"}[type(e)]
        print("%s: %s. Моделът не е викан — опитай по-късно." % (vid, e), file=sys.stderr)
        dnevnik(True, "%s · exit 4" % vid)
        return IZHOD_ZAETO
    except (GreshkaModel, GreshkaConfig, OSError, ValueError) as e:
        print("грешка: %s" % e, file=sys.stderr)
        dnevnik(False, "грешка · exit 1")
        return IZHOD_GRESHKA
    if a.format == "tekst":
        print(otchet(rez))
    else:
        print(json.dumps(rez, ensure_ascii=False, indent=2))
    dnevnik(True, "%.1f · %s · %s · %d похвата · exit 0 · %.1fs" % (
        rez["krayna_ocenka"], rez["reshenie"]["ime"], rez["rezhim"], len(rez["pohvati"]), time.monotonic() - t0))
    return IZHOD_OK
