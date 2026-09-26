#!/usr/bin/env python3
"""Проба за мрежово устройство, на което не може да върви код (напр. NAS) — само чете.

    python3 probe_device.py config.json

Отвън проверява: отговаря ли на ping, отворени ли са TCP портовете от конфигурацията.
По желание чете раздел "tasks" от /api/now на друга машина (тази, която пише бекъпа
към устройството) — за да каже „в момента някой пише в него / последен бекъп преди Х часа“.

Сервира същия формат /api/now, /api/history и същата страница като monitor_lite.py.
"""
import collections
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import monitor_lite as ml

DEFAULTS = {
    "name": "device",
    "host": None,              # адрес на устройството — задължителен
    "listen": "127.0.0.1",
    "port": 8191,
    "sample_seconds": 30,
    "history_minutes": 30,
    "ports": [],               # напр. [445]
    "ping": True,
    "timeout_seconds": 2,
    "writer": None,            # {"name":..., "url": "http://…/api/now", "processes": [...], "logs": [...]}
}


def ping(host, timeout=2):
    """Един ping. → {"ok": bool, "ms": float|None} или None, ако няма команда ping."""
    exe = shutil.which("ping")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-c", "1", "-W", str(int(max(1, timeout))), host],
                           capture_output=True, text=True, timeout=timeout + 2)
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "ms": None}
    m = re.search(r"time[=<]([\d.]+)\s*ms", r.stdout)
    return {"ok": r.returncode == 0, "ms": float(m.group(1)) if m else None}


def tcp_open(host, port, timeout=2):
    """Само отваря и затваря връзка — нищо не изпраща."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def filter_tasks(tasks, processes=None, logs=None):
    """Оставя само задачите, свързани с устройството (по име). Празен списък = всички."""
    tasks = tasks or {}
    running = [p for p in tasks.get("running") or [] if not processes or p.get("name") in processes]
    lg = [l for l in tasks.get("logs") or [] if not logs or l.get("name") in logs]
    return {"running": running, "logs": lg, "summary": ml.tasks_summary(running, lg)}


def writer_tasks(writer, now, fetch=None, timeout=5):
    """Чете tasks от /api/now на пишещата машина. fetch(url) → dict (подменя се в тестовете)."""
    name = writer.get("name") or "writer"
    fetch = fetch or (lambda url: json.load(urllib.request.urlopen(url, timeout=timeout)))
    try:
        remote = fetch(writer["url"])
    except Exception as e:                # недостъпна машина се показва, не се мълчи
        return {"running": [], "logs": [], "summary": {"busy": None, "last_success": None},
                "source": {"name": name, "ok": False, "error": "%s: %s" % (type(e).__name__, e)}}
    t = filter_tasks(remote.get("tasks"), writer.get("processes"), writer.get("logs"))
    # ago_s се смята наново спрямо нашия часовник
    for l in t["logs"]:
        if l.get("last_success"):
            l["ago_s"] = round(now - l["last_success"])
    t["source"] = {"name": remote.get("name") or name, "ok": True}
    return t


class Probe:
    def __init__(self, cfg):
        if not cfg.get("host"):
            raise ValueError("липсва \"host\" в конфигурацията на пробата")
        self.cfg = cfg
        n = max(1, int(cfg["history_minutes"] * 60 / cfg["sample_seconds"]))
        self.history = collections.deque(maxlen=n)
        self.lock = threading.Lock()
        self.now = None

    def snapshot(self):
        c = self.cfg
        to = c["timeout_seconds"]
        p = ping(c["host"], to) if c.get("ping", True) else None
        ports = [{"port": int(port), "open": tcp_open(c["host"], port, to)} for port in c.get("ports") or []]
        reachable = bool((p and p["ok"]) or any(x["open"] for x in ports))
        now = time.time()
        snap = {
            "kind": "device",
            "name": c["name"],
            "time": now,
            "device": {"host": c["host"], "reachable": reachable, "ping": p, "ports": ports},
        }
        if c.get("writer"):
            snap["tasks"] = writer_tasks(c["writer"], now, timeout=max(to, 5))
        return snap

    def tick(self):
        try:
            snap = self.snapshot()
        except Exception as e:
            snap = {"kind": "device", "name": self.cfg["name"], "time": time.time(),
                    "error": "%s: %s" % (type(e).__name__, e)}
        with self.lock:
            self.now = snap
            self.history.append(ml.history_point(snap))

    def run(self):
        while True:
            time.sleep(self.cfg["sample_seconds"])
            self.tick()

    def start(self):
        self.tick()
        threading.Thread(target=self.run, daemon=True).start()

    def get_now(self):
        with self.lock:
            return self.now

    def get_history(self):
        with self.lock:
            return list(self.history)


def main(argv):
    if len(argv) < 2:
        print("употреба: probe_device.py config.json", file=sys.stderr)
        return 2
    cfg = ml.load_config(argv[1], section="probe", defaults=DEFAULTS)
    probe = Probe(cfg)
    probe.start()
    ml.serve(cfg, probe)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
