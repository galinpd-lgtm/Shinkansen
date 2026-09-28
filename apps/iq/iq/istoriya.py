"""Историята на изчисленията и `promeni.log`. Пише само в собствената папка на IQ (papka_danni).

При влошаване на машинната степен спрямо предишното изчисление се добавя ред в `promeni.log`.
Нищо не се изпраща — редът е за четене от човек.
"""
import json
import os

from . import stepen as st
from .tekstove import chislo


def _posledna(path, kanal):
    if not os.path.exists(path):
        return None
    posl = None
    with open(path, encoding="utf-8") as f:
        for red in f:
            try:
                z = json.loads(red)
            except ValueError:
                continue
            if z.get("kanal") == kanal:
                posl = z
    return posl


def zapishi(papka, kanal, ch, mashinna, izchisleno, cfg):
    """Добавя изчислението в istoriya.jsonl. → редът за promeni.log или None, ако няма влошаване."""
    os.makedirs(papka, exist_ok=True)
    ist = os.path.join(papka, "istoriya.jsonl")
    predishna = _posledna(ist, kanal)
    zap = {"kanal": kanal, "izchisleno": izchisleno, "do": ch["period"]["do"], "stepen": mashinna["kod"],
           "sredna": ch["sredna"], "zapisi": ch["zapisi"]}
    with open(ist, "a", encoding="utf-8") as f:
        f.write(json.dumps(zap, ensure_ascii=False) + "\n")
    if predishna is None or st.rang(mashinna["kod"], cfg) >= st.rang(predishna["stepen"], cfg):
        return None
    red = "%s · %s · %s → %s · средна %s (беше %s) · записи %d · %s" % (
        izchisleno, kanal, predishna["stepen"], mashinna["kod"], chislo(ch["sredna"]), chislo(predishna.get("sredna")),
        ch["zapisi"], "; ".join(mashinna["prichini"]) or "—")
    with open(os.path.join(papka, "promeni.log"), "a", encoding="utf-8") as f:
        f.write(red + "\n")
    return red
