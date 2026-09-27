"""Седемте слоя. Слоеве 1–6 се пускат от `filtriray` върху всеки нов запис; слой 7 (издание) — от `chernova`.

Решение за всеки запис: ПРОПУСНИ / ПРЕДУПРЕДИ / КАРАНТИНА / ОТКАЗ / ПРОПУСНАТ, и ред в firewall_log.
Нищо не се трие: отпадналото остава в архива с причината.
"""
import re
from datetime import datetime, timedelta

from . import baza
from .dov import GreshkaModel, GreshkaSadarzhanie, dumi, ocenka, osi, pohvati
from .sabirach import domain
from .vreden import Propusni

PROPUSNI, PREDUPREDI, KARANTINA, OTKAZ, PROPUSNAT = "ПРОПУСНИ", "ПРЕДУПРЕДИ", "КАРАНТИНА", "ОТКАЗ", "ПРОПУСНАТ"
OT_DOVERIE = {"PROPUSNI": PROPUSNI, "PREDUPREDI": PREDUPREDI, "KARANTINA": KARANTINA}
TIPOVE_ZA_PUBLIKUVANE = (PROPUSNI, PREDUPREDI)

_KIRILICA = re.compile(r"[Ѐ-ӿ]")
_BUKVA = re.compile(r"[^\W\d_]", re.UNICODE)


class Krai(Exception):
    """Записът е решен на този слой."""

    def __init__(self, sloy, reshenie, prichina, ocenka=None):
        super().__init__(prichina)
        self.sloy, self.reshenie, self.prichina, self.ocenka = sloy, reshenie, prichina, ocenka


# ─────────── слой 1: техническа проверка ───────────

def sloy1(z, cfg):
    c = cfg["sloy1"]
    if not z["url_kanon"]:
        raise Krai(1, OTKAZ, "невалиден адрес")
    if z["http_status"] not in (None, 200):
        raise Krai(1, OTKAZ, "отговор %s, не 200" % z["http_status"])
    if (z["tip"] or "") not in c["tipove"]:
        raise Krai(1, OTKAZ, "непознат тип „%s“" % z["tip"])
    if len((z["tekst"] or "").strip()) <= c["min_znaci"]:
        raise Krai(1, OTKAZ, "текстът е до %d знака" % c["min_znaci"])


# ─────────── слой 2: дубликати ───────────

def sloy2(b, z, cfg, sega):
    c = cfg["sloy2"]
    r = b.execute("SELECT id FROM zapisi WHERE url_hash=? AND id<>? AND sastoyanie='obraboten' ORDER BY id LIMIT 1",
                  (z["url_hash"], z["id"])).fetchone()
    if r:
        raise Krai(2, PROPUSNAT, "дубликат на запис %d (същият адрес)" % r["id"])
    sh = osi.shingli(z["tekst"])
    ot = (sega - timedelta(days=c["dni"])).isoformat(timespec="seconds")
    for r in b.execute("SELECT id, shingli FROM zapisi WHERE sastoyanie='obraboten' AND shingli IS NOT NULL "
                       "AND id<>? AND obraboteno>=? ORDER BY id", (z["id"], ot)):
        s = osi.jaccard(sh, set(baza.jl(r["shingli"], [])))
        if s > c["prag_pochti"]:
            raise Krai(2, PROPUSNAT, "почти дубликат на запис %d (сходство %.2f)" % (r["id"], s))
    return sh


# ─────────── слой 3: съдържание ───────────

def dyal_kirilica(t):
    bukvi = _BUKVA.findall(t or "")
    return (len([x for x in bukvi if _KIRILICA.match(x)]) / len(bukvi)) if bukvi else 0.0


def _klasificiray(b, kl, tekst, sega, belezhki):
    """→ (опасно, категория) или None, ако слоят е пропуснат за този запис (ред в дневника)."""
    den = sega.date().isoformat()
    if kl.oblachen:
        if kl.granica is not None and baza.broyach(b, den, "vreden_oblak") >= kl.granica:
            belezhki.append((3, "класификатор", "дневният таван от %d заявки към облака е изчерпан — слоят е "
                                                "пропуснат" % kl.granica))
            return None
        try:
            kl.proveri_nastroyka()
        except Propusni as e:
            belezhki.append((3, "класификатор", str(e)))
            return None
        baza.uveli(b, den, "vreden_oblak")
        b.commit()  # заявката се брои, дори записът да не завърши в този ход
        try:
            return kl.e_opasno(tekst)
        except (GreshkaModel, Propusni) as e:  # облакът: грешката не спира статията
            belezhki.append((3, "класификатор", "%s — слоят е пропуснат" % e))
            return None
    try:
        return kl.e_opasno(tekst)
    except Propusni as e:
        belezhki.append((3, "класификатор", str(e)))
    except GreshkaSadarzhanie as e:
        belezhki.append((3, "класификатор", "%s — слоят е пропуснат за този запис" % e))
    return None


def sloy3(b, z, cfg, klasifikator, belezhki, sega):
    c = cfg["sloy3"]
    oficialen = z["izvor_vid"] in c["vidove_oficialni"]
    prag = c["min_dumi_oficialen"] if oficialen else c["min_dumi"]
    n = len(dumi(z["tekst"]))
    if n < prag:
        raise Krai(3, OTKAZ, "%d думи — под прага от %d%s" % (n, prag, " (официален източник)" if oficialen else ""))
    if (z["ezik"] or "bg") == "bg":
        d = dyal_kirilica(z["tekst"])
        if d < c["min_kirilica_bg"]:
            raise Krai(3, OTKAZ, "източникът е на български, а текстът е %.0f%% на кирилица" % (100 * d))
    malki = (z["tekst"] or "").lower()
    for m in c["platena_stena"]:
        if m.lower() in malki:
            raise Krai(3, OTKAZ, "платена стена („%s“)" % m)
    zagl = (z["zaglavie"] or "").lower()
    for m in c.get("reklama", []):
        if m.lower() in malki or m.lower() in zagl:
            raise Krai(3, OTKAZ, "реклама или PR („%s“)" % m)
    if klasifikator is not None and klasifikator.vklyuchen:
        otg = _klasificiray(b, klasifikator, z["tekst"], sega, belezhki)
        if otg is None:
            return
        opasno, kat = otg
        if opasno:
            raise Krai(3, KARANTINA, "класификаторът за вредно съдържание: опасно%s" % (" (%s)" % kat if kat else ""))


# ─────────── слой 4: бърза и пълна оценка (Z7) ───────────

def barza(z, rep):
    """Оси 1, 3 и 6 на Z7 (репутация, прозрачност, свобода от манипулация) — средно, без модел."""
    pr, _ = osi.prozrachnost(z["tekst"])
    ma, _ = osi.manipulaciya(pohvati.po_pravila(z["tekst"]))
    return osi.okragli((rep + pr + ma) / 3.0)


def dcfg_za(dcfg, z, rep):
    """Конфигурация на Z7, в която регистърът има само този източник с измерената му репутация."""
    c = dict(dcfg)
    c["registar_iztochnici"] = [{"domain": domain(z["url"]) or "-", "ime": z["izvor_ime"] or z["izvor"],
                                 "rep_score": rep}]
    c["rep_neizvesten"] = rep
    c["pamet"] = None
    return c


# ─────────── слой 5: репутация на източника ───────────

def preizchisli(b, cfg, sega, vinagi=False):
    """Средното от последните 30 дни; последните 7 тежат двойно. Без данни — остава, каквато е.

    Пуска се, ако са минали preizchisli_sled_dni от последното (седмично). → брой обновени.
    """
    c = cfg["sloy5"]
    ot = sega - timedelta(days=c["dni"])
    skoro = sega - timedelta(days=c["posledni_dni"])
    n = 0
    for izv in b.execute("SELECT * FROM izvori").fetchall():
        if not vinagi and izv["preizchislena"] and \
                sega - datetime.fromisoformat(izv["preizchislena"]) < timedelta(days=c["preizchisli_sled_dni"]):
            continue
        suma = teglo = 0.0
        for r in b.execute("SELECT ocenka, obraboteno FROM zapisi WHERE izvor=? AND ocenka IS NOT NULL "
                           "AND obraboteno>=?", (izv["id"], ot.isoformat(timespec="seconds"))):
            t = c["teglo_posledni"] if datetime.fromisoformat(r["obraboteno"]) >= skoro else 1.0
            suma += t * r["ocenka"]
            teglo += t
        nova = osi.okragli(suma / teglo) if teglo else izv["rep_score"]
        b.execute("UPDATE izvori SET rep_score=?, preizchislena=? WHERE id=?",
                  (nova, sega.isoformat(timespec="seconds"), izv["id"]))
        n += 1
    return n


# ─────────── слой 6: обогатяване ───────────

def _shablon(duma):
    tochno = duma.upper() == duma  # „AI“, „NIS2“, „3D“ — само с главни букви
    return re.compile(r"(?<!\w)%s(?!\w)" % re.escape(duma), 0 if tochno else re.IGNORECASE)


def obogati(z, cfg, organizacii):
    """Рубрика: тази с най-много съвпадения (равенство → по-малкият номер). По-дългите изрази се броят
    първи и „изяждат“ текста си — „AI Act“ не се брои и като „AI“."""
    tekst = "%s %s" % (z["zaglavie"] or "", z["tekst"] or "")
    dumi_ = sorted(((d, r["nomer"]) for r in cfg["rubriki"] for d in r["dumi"]), key=lambda x: -len(x[0]))
    zaeti, broy, temi = [], {}, []
    for d, nomer in dumi_:
        for m in _shablon(d).finditer(tekst):
            if any(m.start() < k and a < m.end() for a, k in zaeti):
                continue
            zaeti.append((m.start(), m.end()))
            broy[nomer] = broy.get(nomer, 0) + 1
            temi.append(d)
    nay, nay_broy = None, 0
    for rub in cfg["rubriki"]:
        if broy.get(rub["nomer"], 0) > nay_broy:
            nay, nay_broy = rub["nomer"], broy[rub["nomer"]]
    orgs = []
    for o in organizacii or []:
        if any(_shablon(ime).search(tekst) for ime in [o["ime"]] + list(o.get("sinonimi") or [])):
            orgs.append(o["ime"])
    vidyani, temi_u = set(), []
    for t in temi:
        if t.lower() not in vidyani:
            vidyani.add(t.lower())
            temi_u.append(t)
    return nay, orgs, temi_u[:5]


# ─────────── слоеве 1–6 за един запис ───────────

def obraboti(b, z, cfg, dcfg, sega, model=None, klasifikator=None, organizacii=None):
    """→ dict с полетата за запис и списък редове за дневника. VrataNeBezopasno се пропуска нагоре."""
    belezhki = []
    pol = {"shingli": None, "barza": None, "ocenka": None, "po_dumi": None, "doverie": None,
           "rubrika": None, "organizacii": None, "temi": None}
    try:
        sloy1(z, cfg)
        sh = sloy2(b, z, cfg, sega)
        pol["shingli"] = sorted(sh)
        sloy3(b, z, cfg, klasifikator, belezhki, sega)

        izv = baza.izvor(b, z["izvor"], z["izvor_ime"], z["izvor_vid"], cfg["sloy5"]["nachalna"])
        rep = izv["rep_score"]
        pol["barza"] = barza(z, rep)
        if pol["barza"] < cfg["sloy4"]["barz_prag"]:
            raise Krai(4, OTKAZ, "бърза оценка %.1f под %.1f" % (pol["barza"], cfg["sloy4"]["barz_prag"]), pol["barza"])
        if rep < cfg["sloy5"]["karantina_pod"]:
            # преди пълната оценка — да не се вика моделът за източник, който и без това е в карантина
            raise Krai(5, KARANTINA, "репутацията на източника е %.1f — под %.1f" % (rep, cfg["sloy5"]["karantina_pod"]),
                       pol["barza"])
        rez = ocenka(z["tekst"], dcfg_za(dcfg, z, rep), model=model, iztochnik=z["url"], vidyani=[])
        pol["ocenka"], pol["po_dumi"] = rez["krayna_ocenka"], rez["po_dumi"]
        pol["doverie"] = {"rezhim": rez["rezhim"], "reshenie": rez["reshenie"],
                          "osi": [{"kluch": o["kluch"], "ocenka": o["ocenka"]} for o in rez["osi"]],
                          "pohvati": [{"ime": p["ime"], "otkas": p["otkas"]} for p in rez["pohvati"]],
                          "za_chitatelya": rez["sintez"]["za_chitatelya"],
                          "profil": {"uverenost": rez["profil"]["uverenost"],
                                     "pokritie_s_dokazatelstva": rez["profil"]["pokritie_s_dokazatelstva"],
                                     "chovek": rez["profil"]["chovek"]}}
        reshenie = OT_DOVERIE[rez["reshenie"]["kod"]]
        prichina = "Z7: %s" % "; ".join(rez["reshenie"]["prichini"])
        if reshenie == KARANTINA:
            raise Krai(4, KARANTINA, prichina, pol["ocenka"])

        pol["rubrika"], pol["organizacii"], pol["temi"] = obogati(z, cfg, organizacii)
        if reshenie == PREDUPREDI:
            belezhki.append((4, PREDUPREDI, prichina))
        krai = Krai(6, reshenie, "премина слоевете 1–6" + ("" if pol["rubrika"] else " (извън рубриките)"),
                    pol["ocenka"])
    except Krai as k:
        krai = k
    return krai, pol, belezhki


def filtriray(b, cfg, dcfg, sega, model=None, klasifikator=None, organizacii=None):
    """Всички нови записи по реда на събиране. Всеки запис се пише в една транзакция: ако вратата спре
    хода (VrataNeBezopasno), текущият запис остава нов и следващото пускане продължава от него."""
    preizchisli(b, cfg, sega)
    b.commit()
    otchet = {}
    for z in b.execute("SELECT * FROM zapisi WHERE sastoyanie='nov' ORDER BY id").fetchall():
        krai, pol, belezhki = obraboti(b, z, cfg, dcfg, sega, model, klasifikator, organizacii)
        vreme = sega.isoformat(timespec="seconds")
        for sloy, reshenie, prichina in belezhki:
            baza.log(b, vreme, sloy, reshenie, prichina, z["id"], z["izvor"], pol["ocenka"])
        baza.log(b, vreme, krai.sloy, krai.reshenie, krai.prichina, z["id"], z["izvor"], krai.ocenka)
        b.execute("UPDATE zapisi SET sastoyanie='obraboten', reshenie=?, sloy=?, prichina=?, barza=?, ocenka=?, "
                  "po_dumi=?, doverie=?, rubrika=?, organizacii=?, temi=?, shingli=?, obraboteno=? WHERE id=?",
                  (krai.reshenie, krai.sloy, krai.prichina, pol["barza"], pol["ocenka"], pol["po_dumi"],
                   baza.jd(pol["doverie"]), pol["rubrika"], baza.jd(pol["organizacii"]), baza.jd(pol["temi"]),
                   baza.jd(pol["shingli"]), vreme, z["id"]))
        b.commit()
        otchet[krai.reshenie] = otchet.get(krai.reshenie, 0) + 1
    return otchet

