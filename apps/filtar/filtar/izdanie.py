"""Слой 7 и изданието: chernova → odobri → izdanie.

chernova  подбира до 10 записа за деня (правилата в config["izdanie"]) → chernova_<дата>.json + .md.
          Десетте места са само за ПРОПУСНИ. ПРЕДУПРЕДИ отиват във вътрешния раздел „За сведение“ под
          черновата: не заемат място и не се одобряват.
odobri    без --go само показва; с --go пише odobreno_<дата>.json. Нищо не отива на живо без него.
izdanie   от одобрените файлове: radar.json (последните 30 дни), rss.xml, po-den/<дата>.json. Не качва нищо.

Авторско право: публично излизат само заглавие, източник, дата, връзка, кратък цитат (до 2 изречения, с
източника) и нашата оценка. Никога пълният текст и никога чужди снимки. Пълните текстове остават само във
вътрешната база на филтъра.
"""
import email.utils
import glob
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from . import VERSIYA, baza
from .dov import SISTEMA, GreshkaSadarzhanie, chisto, izrecheniya
from .sloeve import TIPOVE_ZA_PUBLIKUVANE

VIDOVE = {"oficialen": "официален", "dokumentaciya": "документация/хранилище", "medija": "медия",
          "obshtnost": "общност", "neizvesten": "неизвестен"}


class GreshkaIzdanie(Exception):
    pass


def rubriki(cfg):
    return {r["nomer"]: r["ime"] for r in cfg["rubriki"]}


# ─────────── слой 7: подбор ───────────

def kandidati(b, cfg, den):
    ic = cfg["izdanie"]
    ot = (den - timedelta(days=ic["okno_dni"] - 1)).isoformat()
    do = den.isoformat()
    return b.execute("SELECT z.*, i.rep_score FROM zapisi z LEFT JOIN izvori i ON i.id=z.izvor "
                     "WHERE z.sastoyanie='obraboten' AND z.reshenie IN (?,?) AND z.odobren IS NULL "
                     "AND ((z.data IS NOT NULL AND substr(z.data,1,10) BETWEEN ? AND ?) "
                     "OR (z.data IS NULL AND substr(z.obraboteno,1,10) BETWEEN ? AND ?)) "
                     "ORDER BY CASE z.reshenie WHEN ? THEN 0 ELSE 1 END, z.ocenka DESC, z.data DESC, z.id",
                     TIPOVE_ZA_PUBLIKUVANE + (ot, do, ot, do, TIPOVE_ZA_PUBLIKUVANE[0])).fetchall()


def podberi(b, cfg, den):
    """→ (подбрани, за сведение, [(запис, причина)] отпаднали на слой 7).

    Местата (maks_na_den) са само за ПРОПУСНИ. ПРЕДУПРЕДИ отиват „за сведение“ — вътрешно, без да заемат място."""
    ic = cfg["izdanie"]
    izbrani, za_svedenie, otpadnali, po_rub, po_izv = [], [], [], {}, {}
    for z in kandidati(b, cfg, den):
        if z["reshenie"] != TIPOVE_ZA_PUBLIKUVANE[0]:
            za_svedenie.append(z)
            otpadnali.append((z, "ПРЕДУПРЕДИ — само за сведение, не заема място в изданието"))
        elif not z["izvor_ime"]:
            otpadnali.append((z, "липсва източник — не се публикува"))
        elif not z["data"]:
            otpadnali.append((z, "липсва дата — не се публикува"))
        elif not z["rubrika"]:
            otpadnali.append((z, "извън шестте рубрики"))
        elif len(izbrani) >= ic["maks_na_den"]:
            otpadnali.append((z, "дневният лимит от %d е запълнен" % ic["maks_na_den"]))
        elif po_rub.get(z["rubrika"], 0) >= ic["maks_na_rubrika"]:
            otpadnali.append((z, "рубриката вече има %d записа" % ic["maks_na_rubrika"]))
        elif po_izv.get(z["izvor"], 0) >= ic["maks_na_izvor"]:
            otpadnali.append((z, "източникът вече има %d записа" % ic["maks_na_izvor"]))
        else:
            izbrani.append(z)
            po_rub[z["rubrika"]] = po_rub.get(z["rubrika"], 0) + 1
            po_izv[z["izvor"]] = po_izv.get(z["izvor"], 0) + 1
    return izbrani, za_svedenie, otpadnali


# ─────────── текстовете (моделът от Z7, през вратата) ───────────

PROMPT = ("Прочети новината и напиши на прост български:\n"
          "- kakvo: 2–3 изречения какво се е случило (само факти от текста);\n"
          "- znachi: 1 изречение какво значи това за малка българска фирма.\n"
          "Не добавяй нищо, което го няма в текста. Не присъждай дали новината е вярна.\n"
          'Върни само JSON: {"kakvo": "...", "znachi": "..."}.\n\nЗАГЛАВИЕ: %s\nТЕКСТ:\n<<<\n%s\n>>>')


def tekstove(model, z):
    """→ (kakvo, znachi). VrataNeBezopasno се пропуска нагоре; неразбираем JSON → празни."""
    try:
        d = model.chat("pisach", SISTEMA, PROMPT % (z["zaglavie"] or "", (z["tekst"] or "")[:6000]))
    except GreshkaSadarzhanie:
        return "", ""
    if not isinstance(d, dict):
        return "", ""
    return chisto(d.get("kakvo")) if d.get("kakvo") else "", chisto(d.get("znachi")) if d.get("znachi") else ""


# ─────────── чернова ───────────

MAKS_CITAT_IZRECHENIYA, MAKS_CITAT_ZNACI = 2, 320


def citat(tekst):
    """Кратък дословен цитат: първите до 2 изречения, не повече от 320 знака (с „…“, ако е отрязан)."""
    izr = izrecheniya(tekst or "")[:MAKS_CITAT_IZRECHENIYA]
    c = " ".join(izr)
    if len(c) > MAKS_CITAT_ZNACI:
        c = c[:MAKS_CITAT_ZNACI].rsplit(" ", 1)[0] + "…"
    return c

CHOVEK_ODOBRENO = "одобрено в сводка"  # Галин е видял записа в черновата, не е проверявал оценката ос по ос


def profil_ot(z):
    """Кратката част от профила на Z7, запазена при филтрирането (или празна за стари записи)."""
    dov = baza.jl(z["doverie"], {}) or {}
    p = dov.get("profil") or {}
    return {"uverenost": (p.get("uverenost") or {}).get("nivo"), "chovek": p.get("chovek", "не"),
            "osi": {o["kluch"]: o["ocenka"] for o in dov.get("osi") or []}}


def zapis_za_radara(z, cfg, nomer, kakvo="", znachi=""):
    rep = z["rep_score"] if z["rep_score"] is not None else cfg["sloy5"]["nachalna"]
    pr = profil_ot(z)
    return {
        "nomer": nomer,
        "id": z["id"],
        "zaglavie": z["zaglavie"],
        "kakvo": kakvo,
        "znachi": znachi,
        "citat": citat(z["tekst"]),
        "rubrika": {"nomer": z["rubrika"], "ime": rubriki(cfg).get(z["rubrika"])},
        "izvor": {"ime": z["izvor_ime"], "vid": z["izvor_vid"], "vid_ime": VIDOVE.get(z["izvor_vid"], z["izvor_vid"]),
                  "doverie": rep},
        "ocenka": z["ocenka"],
        "po_dumi": z["po_dumi"],
        "data": (z["data"] or "")[:10],
        "url": z["url"],
        "reshenie": z["reshenie"],
        "uverenost": pr["uverenost"],
        "chovek": pr["chovek"],
        "osi": pr["osi"],  # вътрешно; публично само с izdanie.publichni_osi
        "organizacii": baza.jl(z["organizacii"], []),
        "temi": baza.jl(z["temi"], []),
    }


def chernova(b, cfg, den, papka, sega, model=None):
    izbrani, za_svedenie, otpadnali = podberi(b, cfg, den)
    zapisi = []
    for i, z in enumerate(izbrani, 1):
        kakvo, znachi = tekstove(model, z) if model is not None else ("", "")
        zapisi.append(zapis_za_radara(z, cfg, i, kakvo, znachi))
    svedenie = [zapis_za_radara(z, cfg, None) for z in za_svedenie]  # без номер — не се одобряват
    vreme = sega.isoformat(timespec="seconds")
    for z, prichina in otpadnali:
        baza.log(b, vreme, 7, "НЕ Е ПОДБРАН", "%s (чернова %s)" % (prichina, den.isoformat()), z["id"], z["izvor"],
                 z["ocenka"])
    b.commit()
    d = {"versiya": VERSIYA, "data": den.isoformat(), "sazdadena": vreme,
         "s_model": model is not None, "zapisi": zapisi,
         "za_svedenie": svedenie,
         "otpadnali_na_sloy7": len(otpadnali) - len(svedenie)}
    os.makedirs(papka, exist_ok=True)
    pj = os.path.join(papka, "chernova_%s.json" % den.isoformat())
    with open(pj, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    with open(os.path.join(papka, "chernova_%s.md" % den.isoformat()), "w", encoding="utf-8") as f:
        f.write(md(d))
    return d, pj


def md(d):
    r = ["# Радар — чернова за %s" % d["data"], ""]
    if not d["s_model"]:
        r += ["> Пуснато без модел: текстовете „какво се случи“ и „какво значи“ са празни.", ""]
    if not d["zapisi"]:
        r.append("Няма подбрани записи.")
    for z in d["zapisi"]:
        r += ["## %d. %s" % (z["nomer"], z["zaglavie"]),
              "",
              "- Рубрика: %s" % z["rubrika"]["ime"],
              "- Източник: %s (%s) · доверие към източника %.1f" % (z["izvor"]["ime"], z["izvor"]["vid_ime"],
                                                                     z["izvor"]["doverie"]),
              "- Оценка на текста: %.1f (%s) · увереност: %s · решение на филтъра: %s" % (
                  z["ocenka"], z["po_dumi"], z["uverenost"] or "—", z["reshenie"]),
              "- Дата: %s · %s" % (z["data"], z["url"]),
              "",
              "Какво се случи: %s" % (z["kakvo"] or "—"),
              "",
              "Какво значи: %s" % (z["znachi"] or "—"),
              "",
              "Цитат: „%s“ — %s" % (z["citat"], z["izvor"]["ime"]),
              ""]
    r += ["---", "Одобряване: `python -m filtar odobri --data %s [--mahni 3,7] --go`" % d["data"], ""]
    if d.get("za_svedenie"):
        r += ["## За сведение (вътрешно — ПРЕДУПРЕДИ, не заемат място и не се одобряват)", ""]
        for z in d["za_svedenie"]:
            r.append("- %s — %s · %s · оценка %.1f (%s), увереност: %s · %s" % (
                z["zaglavie"], z["izvor"]["ime"], z["rubrika"]["ime"] or "без рубрика", z["ocenka"], z["po_dumi"],
                z["uverenost"] or "—", z["url"]))
        r.append("")
    return "\n".join(r)


# ─────────── одобрение ───────────

def odobri(b, papka, den, mahni, go, sega):
    """→ (одобрени записи, махнати, път или None). Без go нищо не се пише — нито файл, нито база."""
    pj = os.path.join(papka, "chernova_%s.json" % den.isoformat())
    try:
        with open(pj, encoding="utf-8") as f:
            ch = json.load(f)
    except OSError:
        raise GreshkaIzdanie("няма чернова за %s (%s)" % (den.isoformat(), pj))
    nomera = {z["nomer"] for z in ch["zapisi"]}
    nepoznati = set(mahni) - nomera
    if nepoznati:
        raise GreshkaIzdanie("в черновата няма номер(а): %s" % ", ".join(map(str, sorted(nepoznati))))
    ostavat = [z for z in ch["zapisi"] if z["nomer"] not in mahni]
    mahnati = [z for z in ch["zapisi"] if z["nomer"] in mahni]
    if not go:
        return ostavat, mahnati, None
    vreme = sega.isoformat(timespec="seconds")
    for z in mahnati:
        baza.log(b, vreme, 7, "МАХНАТ", "махнат при одобрението (%s)" % den.isoformat(), z["id"])
    for z in ostavat:
        z["chovek"] = CHOVEK_ODOBRENO
        red = b.execute("SELECT doverie FROM zapisi WHERE id=?", (z["id"],)).fetchone()
        dov = baza.jl(red["doverie"] if red else None, {}) or {}
        dov.setdefault("profil", {})["chovek"] = CHOVEK_ODOBRENO
        b.execute("UPDATE zapisi SET odobren=?, doverie=? WHERE id=?", (den.isoformat(), baza.jd(dov), z["id"]))
    b.commit()
    izh = os.path.join(papka, "odobreno_%s.json" % den.isoformat())
    with open(izh, "w", encoding="utf-8") as f:
        json.dump({"versiya": VERSIYA, "data": den.isoformat(), "odobreno": vreme, "zapisi": ostavat},
                  f, ensure_ascii=False, indent=2)
    return ostavat, mahnati, izh


# ─────────── издание ───────────

def _odobreni(papka):
    for p in sorted(glob.glob(os.path.join(papka, "odobreno_*.json"))):
        with open(p, encoding="utf-8") as f:
            yield json.load(f)


def _rfc822(den_iso):
    d = datetime.fromisoformat(den_iso).replace(tzinfo=timezone.utc)
    return email.utils.format_datetime(d)


def _chovek_sega(papka):
    """Текущото „гледал човек“ от базата — за да се види и проверка, направена след одобрението."""
    path = os.path.join(papka, "filtar.sqlite")
    if not os.path.exists(path):
        return {}
    b = baza.otvori(papka)
    try:
        return {r["id"]: ((baza.jl(r["doverie"], {}) or {}).get("profil") or {}).get("chovek")
                for r in b.execute("SELECT id, doverie FROM zapisi WHERE odobren IS NOT NULL")}
    finally:
        b.close()


def izdanie(cfg, papka, izhod, dnes):
    """Публично излизат само записи с решение ПРОПУСНИ. Оценките по отделните оси — само ако
    izdanie.publichni_osi е включено (по подразбиране не, докато няма правна проверка)."""
    ic = cfg["izdanie"]
    s_osi = bool(ic.get("publichni_osi", False))
    ot = (dnes - timedelta(days=ic["radar_dni"] - 1)).isoformat()
    dni = [d for d in _odobreni(papka) if ot <= d["data"] <= dnes.isoformat()]
    dni.sort(key=lambda d: d["data"], reverse=True)
    os.makedirs(os.path.join(izhod, "po-den"), exist_ok=True)
    chovek = _chovek_sega(papka)

    vsichki = []
    for d in dni:
        zapisi = [_publichen(dict(z, chovek=chovek.get(z.get("id")) or z.get("chovek", "не")), d["data"], s_osi)
                  for z in d["zapisi"] if z.get("reshenie") == PUBLICHNO]
        with open(os.path.join(izhod, "po-den", "%s.json" % d["data"]), "w", encoding="utf-8") as f:
            json.dump({"data": d["data"], "zapisi": zapisi}, f, ensure_ascii=False, indent=2)
        vsichki += zapisi
    radar = {"zaglavie": ic["zaglavie"], "link": ic["link"], "obnoveno": dnes.isoformat(),
             "dni": [d["data"] for d in dni], "zapisi": vsichki}
    with open(os.path.join(izhod, "radar.json"), "w", encoding="utf-8") as f:
        json.dump(radar, f, ensure_ascii=False, indent=2)
    with open(os.path.join(izhod, "rss.xml"), "wb") as f:
        f.write(rss(ic, vsichki, dnes))
    return {"dni": len(dni), "zapisi": len(vsichki)}


PUBLICHNO = "ПРОПУСНИ"  # публично излиза само това решение


def _publichen(z, den, s_osi=False):
    """Само позволените полета: заглавие, източник, дата, връзка, кратък цитат и нашата оценка
    (обща, увереност, гледал ли е човек, решение). Без пълния текст, без снимки и без вътрешни номера.
    Оценките по оси — само при s_osi."""
    p = {"data": z.get("data") or den, "odobren": den, "zaglavie": z["zaglavie"], "kakvo": z["kakvo"],
         "znachi": z["znachi"], "citat": citat(z.get("citat")), "rubrika": z["rubrika"], "izvor": z["izvor"],
         "ocenka": z["ocenka"], "po_dumi": z["po_dumi"], "uverenost": z.get("uverenost"),
         "chovek": z.get("chovek", "не"), "url": z["url"], "reshenie": z["reshenie"]}
    if s_osi:
        p["osi"] = z.get("osi") or {}
    return p


def rss(ic, zapisi, dnes):
    koren = ET.Element("rss", version="2.0")
    k = ET.SubElement(koren, "channel")
    ET.SubElement(k, "title").text = ic["zaglavie"]
    ET.SubElement(k, "link").text = ic["link"]
    ET.SubElement(k, "description").text = ic["opisanie"]
    ET.SubElement(k, "language").text = "bg"
    ET.SubElement(k, "lastBuildDate").text = _rfc822(dnes.isoformat())
    for z in zapisi:
        it = ET.SubElement(k, "item")
        ET.SubElement(it, "title").text = z["zaglavie"]
        ET.SubElement(it, "link").text = z["url"]
        ET.SubElement(it, "guid", isPermaLink="true").text = z["url"]
        ET.SubElement(it, "pubDate").text = _rfc822(z["odobren"])
        ET.SubElement(it, "category").text = z["rubrika"]["ime"]
        opis = " ".join(x for x in (z["kakvo"], z["znachi"]) if x)
        if z["citat"]:
            opis = ("%s „%s“ — %s." % (opis, z["citat"], z["izvor"]["ime"])).strip()
        ET.SubElement(it, "description").text = "%s (Източник: %s, %s; доверие %.1f; решение: %s)" % (
            opis or z["zaglavie"], z["izvor"]["ime"], z["izvor"]["vid_ime"], z["izvor"]["doverie"], z["reshenie"])
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(koren, encoding="utf-8")

