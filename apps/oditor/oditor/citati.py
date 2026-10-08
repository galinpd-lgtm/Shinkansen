"""Проверка на цитатите: моделът предлага, кодът търси цитата дословно в текста след нормализиране.

Ненамерен цитат → непотвърдено. Цитат, който само обявява темата (заглавие, съдържание, въведение
„в тази политика ще намерите …“), не се брои — първият опит показа точно тази слабост.
"""
import re
import unicodedata

OBYAVA = ("ще намерите", "ще научите", "тази политика описва", "настоящата политика описва", "политиката описва",
          "в тази политика", "в настоящата политика", "в следващите раздели", "следните раздели",
          "this policy describes", "this policy explains", "this policy sets out", "you will find",
          "table of contents", "the following sections", "in this policy")

_ZAMENI = {"„": '"', "“": '"', "”": '"', "«": '"', "»": '"', "’": "'", "‘": "'", "–": "-", "—": "-", " ": " "}


def normalizirai(s):
    s = unicodedata.normalize("NFKC", s or "")
    for a, b in _ZAMENI.items():
        s = s.replace(a, b)
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def dumi(s):
    return len(normalizirai(s).split())


def proveri(citat, tekst, min_dumi=6, zaglaviya=(), obyava=OBYAVA):
    """→ (потвърден: bool, причина или None)."""
    n = normalizirai(citat)
    if not n:
        return False, "няма цитат"
    if len(n.split()) < min_dumi:
        return False, "цитатът е под %d думи" % min_dumi
    if n not in normalizirai(tekst):
        return False, "цитатът не е намерен дословно в текста"
    for z in zaglaviya:
        nz = normalizirai(z)
        if nz and n in nz:
            return False, "цитатът е заглавие или ред от съдържанието — само обявява темата"
    for o in obyava:
        if normalizirai(o) in n:
            return False, "цитатът само обявява темата („%s“)" % o
    return True, None
