#!/usr/bin/env python3
"""preview-serve — временен статичен сървър за папка; сам спира след N минути.

    preview_serve.py ПАПКА [--host 127.0.0.1] [--port 8000] [--minutes 30]

По подразбиране слуша само на 127.0.0.1. Друг адрес (напр. 0.0.0.0 — цялата мрежа)
трябва да се поиска изрично и помощникът предупреждава. Само GET/HEAD — нищо не се
качва и не се променя. Скрити файлове (.git, .env…) не се сервират.
Единственият помощник, който „действа“: отваря порт за ограничено време.
"""
import argparse
import functools
import html
import io
import ipaddress
import os
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

MAX_MINUTES = 240


def write_summary(text):
    path = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


class Handler(SimpleHTTPRequestHandler):
    """Статичен, само за четене, без скрити файлове и без кеш."""

    def _hidden(self):
        # декодираме преди проверката: %2eenv е .env
        path = urllib.parse.unquote(self.path.split("?", 1)[0].split("#", 1)[0])
        return any(part.startswith(".") for part in path.replace("\\", "/").split("/") if part)

    def do_GET(self):
        if self._hidden():
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if self._hidden():
            self.send_error(404)
            return
        super().do_HEAD()

    def translate_path(self, path):
        # символна връзка към нещо извън папката не се сервира
        full = super().translate_path(path)
        root = os.path.realpath(self.directory)
        real = os.path.realpath(full)
        if real != root and not real.startswith(root + os.sep):
            return os.path.join(root, ".outside")        # скрито име → 404
        return full

    def list_directory(self, path):
        """Прост списък на папката, без скритите файлове."""
        try:
            names = sorted(n for n in os.listdir(path) if not n.startswith("."))
        except OSError:
            self.send_error(404)
            return None
        items = "".join('<li><a href="%s">%s</a></li>' % (
            urllib.parse.quote(n + ("/" if os.path.isdir(os.path.join(path, n)) else "")),
            html.escape(n + ("/" if os.path.isdir(os.path.join(path, n)) else ""))) for n in names)
        body = ('<!doctype html><meta charset="utf-8"><title>preview</title><ul>%s</ul>' % items).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return io.BytesIO(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s %s\n" % (time.strftime("%H:%M:%S"), fmt % args))


def is_loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def start(directory, host="127.0.0.1", port=8000, seconds=1800):
    """Вдига сървъра в нишка. → (сървър, нишка-таймер). Сървърът спира сам след seconds."""
    handler = functools.partial(Handler, directory=os.path.abspath(directory))
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    timer = threading.Timer(seconds, httpd.shutdown)
    timer.daemon = True
    timer.start()
    return httpd, t, timer


def main(argv=None):
    ap = argparse.ArgumentParser(description="Временен статичен сървър, който спира сам.")
    ap.add_argument("directory")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--minutes", type=float, default=30, help="след колко минути да спре (до %d)" % MAX_MINUTES)
    a = ap.parse_args(argv)
    if not os.path.isdir(a.directory):
        ap.error("няма такава папка")
    if not (0 < a.minutes <= MAX_MINUTES):
        ap.error("минутите са между 0 и %d" % MAX_MINUTES)
    if not (0 <= a.port <= 65535):
        ap.error("портът е между 0 и 65535")
    if not is_loopback(a.host):
        print("! слуша на %s — страницата се вижда от мрежата, не само от тази машина" % a.host, file=sys.stderr)
    try:
        httpd, thread, timer = start(a.directory, a.host, a.port, a.minutes * 60)
    except OSError as e:
        print("не мога да слушам на %s:%d — %s" % (a.host, a.port, e.strerror or e), file=sys.stderr)
        write_summary("портът е зает или недостъпен")
        return 1
    host, port = httpd.server_address[:2]
    shown = "[%s]" % host if ":" in host else host
    until = time.strftime("%H:%M", time.localtime(time.time() + a.minutes * 60))
    print("http://%s:%d/  ·  %s  ·  спира в %s (Ctrl+C — по-рано)" % (
        shown, port, os.path.abspath(a.directory), until), flush=True)
    stopped_early = False
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        stopped_early = True
        httpd.shutdown()
    timer.cancel()
    httpd.server_close()
    print("спрян%s." % (" по-рано" if stopped_early else ""))
    write_summary("%s · %g мин" % ("спрян по-рано" if stopped_early else "спря сам", a.minutes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
