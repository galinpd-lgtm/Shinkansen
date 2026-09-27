"""Клиент към Ollama /api/chat: stream=false, format=json, think="low", temperature 0, таймаут.

Две роли от конфигурацията: „struktura“ (осите и похватите — само JSON) и „pisach“ (синтез за читателя).
Преди всяко викане пита топлинната врата. Отговорът се връща като dict; неразбираем JSON → GreshkaModel.
"""
import json
import urllib.error
import urllib.request

from .vrata import Vrata


class GreshkaModel(Exception):
    """Ollama не отговаря или връща грешка — оценката спира (изход 1)."""


class GreshkaSadarzhanie(GreshkaModel):
    """Моделът отговори, но не с нужния JSON — за тази ос се ползва евристиката."""


def http_post(url, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace") if e.fp else ""


def izvadi_json(s):
    """JSON от съдържанието на отговора; търпи ограждане с ``` и текст около обекта."""
    s = (s or "").strip()
    try:
        return json.loads(s)
    except ValueError:
        a, b = s.find("{"), s.rfind("}")
        if a != -1 and b > a:
            try:
                return json.loads(s[a:b + 1])
            except ValueError:
                pass
    raise GreshkaSadarzhanie("моделът не върна JSON")


class Model:
    def __init__(self, cfg, vrata=None, post=None):
        self.cfg = cfg
        self.url = cfg["ollama_url"].rstrip("/") + "/api/chat"
        self.timeout = cfg.get("taymaut_s", 120)
        self.vrata = vrata if vrata is not None else Vrata(cfg.get("gate_url"))
        self._post = post or (lambda *a: http_post(*a))
        self.vikaniya = 0

    def chat(self, rolya, sistema, potrebitel):
        m = self.cfg["model"][rolya]
        body = {
            "model": m["ime"],
            "messages": [{"role": "system", "content": sistema},
                         {"role": "user", "content": potrebitel}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        if m.get("think"):
            body["think"] = m["think"]
        self.vrata.proveri()
        self.vikaniya += 1
        try:
            status, tyalo = self._post(self.url, body, self.timeout)
            if status == 400 and "think" in body and "think" in tyalo.lower():
                # моделът не поддържа мислене — същото викане без него (вратата се пита отново)
                body = {k: v for k, v in body.items() if k != "think"}
                self.vrata.proveri()
                status, tyalo = self._post(self.url, body, self.timeout)
        except GreshkaModel:
            raise
        except Exception as e:
            raise GreshkaModel("Ollama не отговаря: %s" % e)
        if status != 200:
            raise GreshkaModel("Ollama върна код %d" % status)
        try:
            sadarzhanie = json.loads(tyalo)["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise GreshkaModel("неочакван отговор от Ollama")
        return izvadi_json(sadarzhanie)
