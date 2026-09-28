"""Обхождане на папката и обработка на един файл. Входът само се чете — никога не се пише в него."""
import hashlib
import os
import shutil

from . import pravila, popravki
from .dom import razbor

PROMENEN, BEZ_PROMYANA, ZA_RACHNO, IZKLYUCHEN, NE_E_HTML = (
    "променен", "без промяна", "за ръчно", "изключен", "не е обучение")
V_KANON, POPRAVIMO = "по канона", "поправимо"   # при проверка, без поправка
VRAZKA = "символна връзка"   # копира се като връзка, не се следва


class GreshkaPat(Exception):
    pass


class Zapis:
    """Един файл: резултатите по правила, отпечатъците преди/след и какво е станало с него."""

    def __init__(self, rel):
        self.rel = rel
        self.papka = rel.split("/")[0] if "/" in rel else "."
        self.rezultati = []
        self.sha_predi = None
        self.sha_sled = None
        self.stapki = []
        self.blokirano = []
        self.status = None
        self.staro = None
        self.novo = None

    def rezultat(self, pravilo):
        for r in self.rezultati:
            if r.pravilo == pravilo:
                return r
        return None

    def za_rachno(self):
        """[(правило, бележка, записан ли е файлът)] — без повторения между правило и блокиране."""
        zapisan = self.status == PROMENEN
        redove, videni = [], set()
        for r in self.rezultati:
            for b in r.za_rachno:
                redove.append((r.pravilo, b, zapisan))
                videni.add(b)
        for pravilo, b in self.blokirano:
            if b not in videni:
                redove.append((pravilo, b, zapisan))
        return redove


def sha(danni):
    return hashlib.sha256(danni).hexdigest()


def e_izklyuchen(rel, izklyuchi):
    chasti = rel.split("/")
    for i in izklyuchi:
        i = i.strip("/").replace("\\", "/")
        if "/" in i:
            if rel == i or rel.startswith(i + "/"):
                return True
        elif i in chasti[:-1]:
            return True
    return False


def failove(koren, k):
    """(абсолютен път, относителен път) за всички файлове и символни връзки по азбучен ред.
    Връзките (и към папки) се връщат като една позиция — не се следват."""
    for papka, podpapki, imena in os.walk(koren):
        podpapki.sort()
        vrazki_papki = [d for d in podpapki if os.path.islink(os.path.join(papka, d))]
        for ime in sorted(imena + vrazki_papki):
            a = os.path.join(papka, ime)
            yield a, os.path.relpath(a, koren).replace(os.sep, "/")


def e_obuchenie(rel, k):
    return os.path.splitext(rel)[1].lower() in [r.lower() for r in k.get("rasshireniya", [".html", ".htm"])]


def obraboti(a, rel, k, znak=None):
    """Проверява файла; ако е даден знак — и го поправя в паметта (нищо не се пише тук)."""
    z = Zapis(rel)
    with open(a, "rb") as f:
        danni = f.read()
    z.sha_predi = sha(danni)
    try:
        html = danni.decode("utf-8")
    except UnicodeDecodeError:
        z.blokirano.append(("файл", "не е UTF-8 — не е четен"))
        z.status = ZA_RACHNO
        return z
    z.staro = html
    doc = razbor(html)
    z.rezultati = pravila.vsichki(doc, k, rel)
    if znak is None:
        z.rezultati.append(pravila.celost_ne_se_prilaga())
        z.status = ZA_RACHNO if z.za_rachno() else (
            V_KANON if all(r.status != pravila.NARUSHENIE for r in z.rezultati) else POPRAVIMO)
        return z
    p = popravki.popravi(html, k, rel, znak)
    z.stapki, z.blokirano = p.stapki, p.blokirano
    celost = pravila.Rezultat("цялост")
    for pravilo, b in p.blokirano:
        if pravilo == "цялост":
            celost.narushenie(b)
    if p.blokirano and celost.status == pravila.OK:
        celost.status = pravila.NE_SE_PRILAGA
    z.rezultati.append(celost)
    if p.novo is None:
        z.status = ZA_RACHNO
        z.sha_sled = z.sha_predi
        z.stapki = []   # нищо не е приложено — файлът се копира както е
    elif p.novo == html:
        z.status = BEZ_PROMYANA
        z.sha_sled = z.sha_predi
    else:
        z.novo = p.novo
        z.sha_sled = sha(p.novo.encode("utf-8"))
        z.status = PROMENEN
    return z


def obhodi(koren, k, znak=None):
    """Всички записи. Изключените и не-HTML файловете се връщат с отпечатък, но без проверка."""
    zapisi = []
    for a, rel in failove(koren, k):
        if os.path.islink(a):
            z = Zapis(rel)
            z.status = VRAZKA
            zapisi.append((a, z))
            continue
        if e_izklyuchen(rel, k.get("izklyuchi", [])) or not e_obuchenie(rel, k):
            z = Zapis(rel)
            z.status = IZKLYUCHEN if e_izklyuchen(rel, k.get("izklyuchi", [])) else NE_E_HTML
            with open(a, "rb") as f:
                z.sha_predi = z.sha_sled = sha(f.read())
            zapisi.append((a, z))
            continue
        zapisi.append((a, obraboti(a, rel, k, znak)))
    return zapisi


def _istinski(p):
    return os.path.realpath(os.path.abspath(p))


def e_vatre(p, koren):
    p, koren = _istinski(p), _istinski(koren)
    return p == koren or p.startswith(koren.rstrip(os.sep) + os.sep)


def proveri_izhod(vhod, izhod):
    """Изходът е нова папка извън входа: не е входът, не е в него и входът не е в него."""
    if e_vatre(izhod, vhod):
        raise GreshkaPat("изходът %s е входът или е вътре във входа — отказвам" % izhod)
    if e_vatre(vhod, izhod):
        raise GreshkaPat("входът е вътре в изхода %s — отказвам" % izhod)
    if os.path.exists(izhod) and (not os.path.isdir(izhod) or os.listdir(izhod)):
        raise GreshkaPat("изходът %s вече съществува и не е празна папка — дай нова" % izhod)


def zapishi(vhod, izhod, zapisi):
    """Пълно копие на входа в нова папка: поправените файлове — новият текст, всичко друго — както е."""
    proveri_izhod(vhod, izhod)
    os.makedirs(izhod, exist_ok=True)
    for papka, podpapki, _imena in os.walk(vhod):   # и празните папки
        for d in podpapki:
            if not os.path.islink(os.path.join(papka, d)):
                os.makedirs(os.path.join(izhod, os.path.relpath(os.path.join(papka, d), vhod)), exist_ok=True)
    for a, z in zapisi:
        cel = os.path.join(izhod, *z.rel.split("/"))
        if not e_vatre(cel, izhod) or e_vatre(cel, vhod):
            raise GreshkaPat("пътят %s излиза извън изхода — спирам" % z.rel)
        os.makedirs(os.path.dirname(cel), exist_ok=True)
        if z.status == VRAZKA:
            os.symlink(os.readlink(a), cel)
        elif z.status == PROMENEN:
            with open(cel, "wb") as f:
                f.write(z.novo.encode("utf-8"))
        else:
            shutil.copy2(a, cel)
