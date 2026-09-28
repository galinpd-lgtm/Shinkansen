"""Генерира src/pravila.js и tests/fixtures/ocakvano.json от apps/doverie — един източник на истината.

    python3 scripts/gen_pravila.py            # пише двата файла
    python3 scripts/gen_pravila.py --proveri  # само проверява, че са в синхрон (изход 1, ако не са)

pravila.js носи регулярните изрази на Z7, преведени към JavaScript, таблицата на похватите и нужната част
от конфигурацията (тегла, прагове, 10-те въпроса). ocakvano.json е изходът на `doverie --bez-model` за
текстовете в tests/fixtures/tekstove/ и за примерите на Z7 — JS двигателят трябва да даде същото.
"""
import json
import os
import re
import sys

LNA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOVERIE = os.path.join(os.path.dirname(LNA), "doverie")
sys.path.insert(0, DOVERIE)

from doverie import VERSIYA, osi, pohvati, tekst  # noqa: E402
from doverie.config import OSI_KLUCHOVE, zaredi  # noqa: E402
from doverie.ocenka import CHOVEK, ocenka  # noqa: E402

CEL_JS = os.path.join(LNA, "src", "pravila.js")
CEL_OCAKVANO = os.path.join(LNA, "tests", "fixtures", "ocakvano.json")
TEKSTOVE = os.path.join(LNA, "tests", "fixtures", "tekstove")

# ─────────── превод на регулярен израз: Python (re, Unicode) → JavaScript (флаг u) ───────────

DUMA = r"\p{L}\p{N}_"  # \w в Python за str: букви, цифри, долна черта
GRANICA = "(?:(?<=[%s])(?![%s])|(?<![%s])(?=[%s]))" % ((DUMA,) * 4)  # \b в Python с Unicode
SINTAKSIS = set("^$\\.*+?()[]{}|/")
KLASOVE = set("dDsSwWbBntrfv")


class GreshkaPrevod(Exception):
    pass


def js_izraz(izraz):
    """→ (source, flags). \\b и \\w стават Unicode-осъзнати; (?i:…) се разгъва до [аА]…; флагът u винаги."""
    p, fl = izraz.pattern, izraz.flags
    out, i, klas, stek = [], 0, False, []
    ci = lambda: any(stek)  # noqa: E731
    while i < len(p):
        c = p[i]
        if c == "\\":
            n = p[i + 1]
            i += 2
            if n == "b" and not klas:
                out.append(GRANICA)
            elif n == "w":
                out.append(DUMA if klas else "[%s]" % DUMA)
            elif n in "dD":  # \d в Python хваща всички десетични цифри, в JS — само ASCII
                out.append("\\p{Nd}" if n == "d" else "\\P{Nd}")
            elif n in KLASOVE:
                out.append("\\" + n)
            elif n in SINTAKSIS or (n == "-" and klas):
                out.append("\\" + n)
            else:
                out.append(n)  # напр. \" — в режим u ненужното екраниране е грешка
            continue
        if klas:
            if c == "]":
                klas = False
                out.append(c)
            elif ci() and c.lower() != c.upper():
                if i + 1 < len(p) and p[i + 1] == "-" and i + 2 < len(p) and p[i + 2] != "]":
                    raise GreshkaPrevod("диапазон в (?i:…) не се поддържа: %s" % p)
                out.append(c.lower() + c.upper())
            else:
                out.append(c)
            i += 1
            continue
        if c == "[":
            klas = True
            out.append(c)
            if i + 1 < len(p) and p[i + 1] == "^":
                out.append("^")
                i += 1
            i += 1
            continue
        if c == "(":
            if p.startswith("(?i:", i):
                stek.append(True)
                out.append("(?:")
                i += 4
                continue
            stek.append(False)
            out.append(c)
            i += 1
            continue
        if c == ")":
            if not stek:
                raise GreshkaPrevod("неочаквана „)“: %s" % p)
            stek.pop()
            out.append(c)
            i += 1
            continue
        if c.lower() != c.upper() and ci() and not (fl & re.IGNORECASE):
            out.append("[%s%s]" % (c.lower(), c.upper()))
        else:
            out.append(c)
        i += 1
    if klas or stek:
        raise GreshkaPrevod("незатворена група или клас: %s" % p)
    return "".join(out), "u" + ("i" if fl & re.IGNORECASE else "")


IZRAZI = {
    # tekst.py
    "IZR": tekst._IZR, "DUMA": tekst._DUMA,
    # pohvati.py
    "STRAH": pohvati.STRAH, "CITAT": pohvati.CITAT, "TALPA": pohvati.TALPA,
    "OTRICANIE_PREDI": pohvati.OTRICANIE_PREDI, "OTRICANIE_SLED": pohvati.OTRICANIE_SLED,
    "VYARNO_CHE": pohvati.VYARNO_CHE, "PREKASVA": pohvati.PREKASVA,
    # osi.py
    "TVARDENIE": osi.TVARDENIE, "IZTOCHNIK": osi.IZTOCHNIK, "IMENUVAN": osi.IMENUVAN, "ANONIMEN_OS": osi.ANONIMEN,
    "INTERES": osi.INTERES, "REKLAMA": osi.REKLAMA, "KOGA": osi.KOGA, "KADE": osi.KADE, "ZASHTO": osi.ZASHTO,
    "KAK": osi.KAK, "SPRYAMO": osi.SPRYAMO, "KOY": osi.KOY,
}
SPISACI = {"DILEMA": pohvati.DILEMA, "ANONIMEN": pohvati.ANONIMEN}


def pravila(cfg):
    return {
        "izvor": "apps/doverie %s — генерирано от scripts/gen_pravila.py, не се пипа на ръка" % VERSIYA,
        "versiya_doverie": VERSIYA,
        "izrazi": {k: js_izraz(v) for k, v in IZRAZI.items()},
        "spisaci": {k: [js_izraz(x) for x in v] for k, v in SPISACI.items()},
        "pohvati": {k: {"ime": v[0], "nakazanie": v[1], "kak": v[2], "opisanie": v[3]} for k, v in pohvati.POHVATI.items()},
        "red_pohvati": list(pohvati.POHVATI),
        "samo_model": list(pohvati.SAMO_MODEL),
        "osi": [{"kluch": k, "ime": osi.IMENA[k], "teglo": cfg["tegla"][k]} for k in OSI_KLUCHOVE],
        "s_model": list(osi.S_MODEL),
        "po_dumi": cfg["po_dumi"],
        "reshenie": cfg["reshenie"],
        "uverenost": cfg["uverenost"],
        "palnota_vaprosi": cfg["palnota_vaprosi"],
        "rep_neizvesten": cfg.get("rep_neizvesten", 5.0),
        "registar_iztochnici": cfg.get("registar_iztochnici") or [],
        "otgovori": {"DA": osi.DA, "CHASTICHNO": osi.CHASTICHNO, "NE": osi.NE, "NEOPREDELIMO": osi.NEOPREDELIMO},
        "chovek": list(CHOVEK),
    }


def js_fayl(d):
    return ("// ГЕНЕРИРАН ФАЙЛ — не се пипа на ръка. Източник: apps/doverie; команда: python3 scripts/gen_pravila.py\n"
            "(function (g) {\n  var PRAVILA = %s;\n"
            "  if (typeof module !== 'undefined' && module.exports) { module.exports = PRAVILA; } else { g.PRAVILA = PRAVILA; }\n"
            "})(typeof self !== 'undefined' ? self : this);\n") % json.dumps(d, ensure_ascii=False, indent=2).replace(
                "\n", "\n  ")


# ─────────── очакваният изход ───────────

def tekstove():
    """(име, текст): примерите на Z7 и текстовете на измислените страници."""
    t = []
    for ime in sorted(os.listdir(os.path.join(DOVERIE, "tests"))):
        if re.fullmatch(r"primer_\d+\.txt", ime):
            with open(os.path.join(DOVERIE, "tests", ime), encoding="utf-8") as f:
                t.append(("doverie/" + ime, f.read()))
    if os.path.isdir(TEKSTOVE):
        for ime in sorted(os.listdir(TEKSTOVE)):
            if ime.endswith(".txt"):
                with open(os.path.join(TEKSTOVE, ime), encoding="utf-8") as f:
                    t.append((ime, f.read()))
    return t


def ocakvano(cfg):
    sluchai = []
    for ime, t in tekstove():
        rez = ocenka(t, cfg)
        norm = tekst.normalizirai(t)
        sluchai.append({
            "ime": ime,
            "tekst": t,
            "profil": rez["profil"],
            "pohvati": rez["pohvati"],
            "neprovereni_pohvati": rez["neprovereni_pohvati"],
            "reshenie": rez["reshenie"],
            "belezhki": rez["belezhki"],
            # всеки израз поотделно: къде хваща в нормализирания текст (за откриване на разминаване)
            "savpadeniya": {k: [[m.start(), m.end()] for m in v.finditer(norm)] for k, v in IZRAZI.items()},
        })
    return {"izvor": "apps/doverie %s --bez-model" % VERSIYA, "sluchai": sluchai}


def main(argv):
    cfg = zaredi(os.path.join(DOVERIE, "config.example.json"))
    cfg["pamet"] = None
    js = js_fayl(pravila(cfg))
    oc = json.dumps(ocakvano(cfg), ensure_ascii=False, indent=1) + "\n"
    if "--proveri" in argv:
        greshki = []
        for path, novo in ((CEL_JS, js), (CEL_OCAKVANO, oc)):
            try:
                with open(path, encoding="utf-8") as f:
                    if f.read() != novo:
                        greshki.append(path)
            except OSError:
                greshki.append(path)
        for g in greshki:
            print("не е в синхрон с apps/doverie: %s — пусни python3 scripts/gen_pravila.py" % os.path.relpath(g, LNA))
        return 1 if greshki else 0
    for path, novo in ((CEL_JS, js), (CEL_OCAKVANO, oc)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(novo)
        print("записан: %s" % os.path.relpath(path, LNA))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
