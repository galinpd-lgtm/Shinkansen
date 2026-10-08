"""Клиент към Ollama /api/chat: stream=false, format=json, temperature 0. Моделът само предлага — кодът проверява.

Ролите (ARCHITECTURE.md, решение от 08.10.2026): rabotnik — Gemma 4; pazach — nemotron-3-super (само JSON с
английски кодове); visok_risk — Mistral-Small-4. Без китайски модели, без gpt-oss. Имената са в config.

Топлинна врата: преди всяко викане GET <gate_url>. Без gate_url, при „заето“ или без отговор моделът
не се вика — съответната част остава „непроверено“. Вратата никога не се заобикаля.
"""
import json
import urllib.error
import urllib.request

ZAETO = {"busy", "hot", "zaeto", "заето", "горещо"}


class GreshkaModel(Exception):
    """Моделът не е викан или не върна нужния JSON. Частта остава „непроверено“."""


def http_post(url, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace") if e.fp else ""


def http_get(url, timeout):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def izvadi_json(s):
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
    raise GreshkaModel("моделът не върна JSON")


class Model:
    def __init__(self, cfg_model, post=None, get=None):
        self.cfg = cfg_model or {}
        self._post = post or http_post
        self._get = get or http_get
        self.vikaniya = 0

    def ima(self, rolya):
        return bool((self.cfg.get(rolya) or {}).get("ime")) and bool(self.cfg.get("ollama_url"))

    def ime(self, rolya):
        return (self.cfg.get(rolya) or {}).get("ime")

    def _vrata(self):
        url = self.cfg.get("gate_url")
        if not url:
            raise GreshkaModel("няма gate_url — без топлинна врата моделът не се вика")
        try:
            status, tyalo = self._get(url, 5)
        except Exception as e:
            raise GreshkaModel("вратата не отговаря: %s" % e)
        if status in (429, 503):
            raise GreshkaModel("машината е заета")
        if status != 200:
            raise GreshkaModel("вратата върна код %s" % status)
        t = (tyalo or "").strip()
        try:
            d = json.loads(t)
        except ValueError:
            d = t
        if isinstance(d, dict):
            if d.get("busy") is True or str(d.get("state", d.get("status", ""))).lower() in ZAETO:
                raise GreshkaModel("машината е заета")
        elif str(d).lower() in ZAETO:
            raise GreshkaModel("машината е заета")

    def chat(self, rolya, sistema, potrebitel):
        if not self.ima(rolya):
            raise GreshkaModel("ролята „%s“ няма модел в config" % rolya)
        self._vrata()
        body = {"model": self.ime(rolya), "stream": False, "format": "json", "options": {"temperature": 0},
                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": potrebitel}]}
        self.vikaniya += 1
        try:
            status, tyalo = self._post(self.cfg["ollama_url"].rstrip("/") + "/api/chat", body,
                                       self.cfg.get("taymaut_s", 180))
        except Exception as e:
            raise GreshkaModel("Ollama не отговаря: %s" % e)
        if status != 200:
            raise GreshkaModel("Ollama върна код %s" % status)
        try:
            sadarzhanie = json.loads(tyalo)["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise GreshkaModel("неразбираем отговор от Ollama")
        d = izvadi_json(sadarzhanie)
        if not isinstance(d, dict):
            raise GreshkaModel("моделът не върна JSON обект")
        return d
