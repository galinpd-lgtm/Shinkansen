"""Малък HTTP само на 127.0.0.1 за разширението (Z9): POST /ocenka.

Тяло: {"tekst": "...", "iztochnik": "example.org", "avtor": "...", "bez_model": false}
Отговор: 200 + JSON на оценката · 503 при заета машина, недостъпна или липсваща врата · 400 при грешен вход · 502 при грешка на модела.
Сървърът не тегли адреси — разширението праща текста, който вече е на екрана.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .model import GreshkaModel, Model
from .ocenka import ocenka
from .vrata import VrataNeBezopasno

HOST = "127.0.0.1"
MAKS_BAYTA = 1_000_000


def napravi_handler(cfg, bez_model=False, model_fabrika=None):
    fabrika = model_fabrika or (lambda: Model(cfg))

    class H(BaseHTTPRequestHandler):
        server_version = "doverie"

        def log_message(self, *a):  # без дневник на заявките — в тях е чужд текст
            pass

        def _otg(self, kod, danni):
            b = json.dumps(danni, ensure_ascii=False).encode("utf-8")
            self.send_response(kod)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path == "/zdrave":
                return self._otg(200, {"ok": True})
            self._otg(404, {"greshka": "няма такъв адрес"})

        def do_POST(self):
            if self.path != "/ocenka":
                return self._otg(404, {"greshka": "няма такъв адрес"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAKS_BAYTA:
                return self._otg(400, {"greshka": "липсва тяло или е твърде голямо"})
            try:
                vh = json.loads(self.rfile.read(n).decode("utf-8"))
                tekst = vh["tekst"]
                if not isinstance(tekst, str) or not tekst.strip():
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                return self._otg(400, {"greshka": "очаква се JSON с поле „tekst“"})
            model = None if (bez_model or vh.get("bez_model")) else fabrika()
            try:
                rez = ocenka(tekst, cfg, model=model, iztochnik=vh.get("iztochnik"), avtor=vh.get("avtor"))
            except VrataNeBezopasno as e:
                return self._otg(503, {"greshka": "не е безопасно сега — опитай по-късно (%s)" % e})
            except GreshkaModel as e:
                return self._otg(502, {"greshka": str(e)})
            self._otg(200, rez)

    return H


def pusni(cfg, port, bez_model=False):
    srv = ThreadingHTTPServer((HOST, port), napravi_handler(cfg, bez_model))
    print("doverie: слуша на http://%s:%d/ocenka" % (HOST, port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
