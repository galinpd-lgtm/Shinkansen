"""По желание: класификатор за вредно съдържание (слой 3). Изключен по подразбиране.

Два режима, едно и също API (Ollama /api/chat), различават се само адресът и ключът:
  lokalen  — Ollama на GX10 (lokalen_url);
  oblachen — облакът на Ollama (oblachen_url + kluch; ключът е само в частния config.json на GX10).
Вика се само през топлинната врата на Z7. Мери само вредност — не достоверност и не полезност.
Без ключ в облачен режим слоят се пропуска с ред в дневника.
"""
import json

from .dov import GreshkaModel, GreshkaSadarzhanie, Vrata, izvadi_json

SISTEMA = ("Ти си класификатор за безопасност на съдържание. Решаваш само дали текстът е опасен "
           "(подбужда към насилие, самонараняване, тероризъм, експлоатация на деца и подобни). "
           "Не оценяваш дали е верен или полезен. Върни само JSON.")
PROMPT = ('Опасен ли е този публичен текст? Върни {"opasno": true или false, "kategoriya": "една дума или празно"}.'
          "\n\nТЕКСТ:\n<<<\n%s\n>>>")


class Propusni(Exception):
    """Слоят не може да се пусне (напр. няма ключ) — пропуска се с ред в дневника."""


class Klasifikator:
    def __init__(self, vcfg, gate_url, post=None, vrata=None):
        self.rezhim = vcfg.get("rezhim", "izklyuchen")
        self.model = vcfg.get("model")
        if self.rezhim == "lokalen":
            self.url, self.kluch = vcfg.get("lokalen_url"), None
        elif self.rezhim == "oblachen":
            self.url, self.kluch = vcfg.get("oblachen_url"), vcfg.get("kluch")
        else:
            self.url = self.kluch = None
        self.vrata = vrata if vrata is not None else Vrata(gate_url)
        self._post = post or http_post
        self.vikaniya = 0

    @property
    def vklyuchen(self):
        return self.rezhim in ("lokalen", "oblachen")

    def proveri_nastroyka(self):
        if self.rezhim == "oblachen" and not self.kluch:
            raise Propusni("класификаторът е в облачен режим, но няма ключ — слоят е пропуснат")
        if not self.url:
            raise Propusni("класификаторът няма адрес — слоят е пропуснат")

    def e_opasno(self, tekst):
        """→ (опасно?, категория). Вдига VrataNeBezopasno, GreshkaModel или Propusni."""
        self.proveri_nastroyka()
        body = {"model": self.model, "stream": False, "format": "json", "options": {"temperature": 0},
                "messages": [{"role": "system", "content": SISTEMA},
                             {"role": "user", "content": PROMPT % tekst[:8000]}]}
        zaglavki = {"Content-Type": "application/json"}
        if self.kluch:
            zaglavki["Authorization"] = "Bearer " + self.kluch
        self.vrata.proveri()
        self.vikaniya += 1
        try:
            status, tyalo = self._post(self.url.rstrip("/") + "/api/chat", body, zaglavki, 60)
        except Exception as e:
            raise GreshkaModel("класификаторът не отговаря: %s" % e)
        if status != 200:
            raise GreshkaModel("класификаторът върна код %d" % status)
        try:
            sad = json.loads(tyalo)["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise GreshkaModel("неочакван отговор от класификатора")
        try:
            d = izvadi_json(sad)
            return bool(d.get("opasno")), str(d.get("kategoriya") or "")
        except (GreshkaSadarzhanie, AttributeError):
            # модели за безопасност често отговарят с една дума: safe / unsafe
            dumi = sad.strip().lower()
            if dumi.startswith("unsafe"):
                return True, ""
            if dumi.startswith("safe"):
                return False, ""
            raise GreshkaSadarzhanie("класификаторът не върна разбираем отговор")


def http_post(url, body, zaglavki, timeout):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=zaglavki)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
