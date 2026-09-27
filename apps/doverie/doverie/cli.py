"""python -m doverie ocenka --tekst file.txt | --url … [--bez-model] [--format json|tekst]
python -m doverie serve [--port 8765]

Кодове на изход: 0 готово · 4 машината е заета/горещо (моделът не е викан) · 1 грешка · 2 грешна употреба.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

from . import VERSIYA
from .config import GreshkaConfig, zaredi
from .model import GreshkaModel, Model
from .ocenka import ocenka, otchet
from .tekst import ot_html
from .vrata import VrataGreshka, VrataZaeta

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
    if model is not None and not cfg.get("gate_url"):
        print("внимание: няма gate_url — моделът се вика без топлинна врата", file=sys.stderr)
    return ocenka(tekst, cfg, model=model, iztochnik=iztochnik, avtor=a.avtor, zapomni=a.zapomni)


def main(argv=None):
    a = parser().parse_args(argv)
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
    except VrataZaeta as e:
        print("заето: %s" % e, file=sys.stderr)
        dnevnik(True, "заето · exit 4")
        return IZHOD_ZAETO
    except (VrataGreshka, GreshkaModel, GreshkaConfig, OSError, ValueError) as e:
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
