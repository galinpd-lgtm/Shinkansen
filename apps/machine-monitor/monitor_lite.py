#!/usr/bin/env python3
"""Олекотен монитор на Linux машина — само чете, нищо не управлява.

    python3 monitor_lite.py config.json

Отговаря на въпроса „как е машината и има ли задачи в момента“:
  /             — една HTML страница (тъмна, без CDN), опреснява се от /api/now
  /api/now      — JSON: температури, CPU, памет, диск, RAID, паднали услуги, задачи
  /api/history  — последните N минути (в паметта, по подразбиране 30)

Само стандартна библиотека на Python 3. Адреси, имена и пътища идват от
конфигурацията — в кода няма нито един конкретен.
"""
import collections
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULTS = {
    "name": None,              # None → името на машината (hostname)
    "listen": "127.0.0.1",     # по подразбиране само локално
    "port": 8190,
    "sample_seconds": 10,
    "history_minutes": 30,
    "mounts": ["/"],
    "systemd": True,           # търси ли паднали systemd услуги
    "tasks": {"processes": [], "logs": []},
}

# Регулярен израз по подразбиране за време в ред от лог: 2026-09-26 03:14:15 или 2026-09-26T03:14:15
ISO_TIME = r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
LOG_TAIL_BYTES = 1024 * 1024   # от лога четем само последния мегабайт


# ─────────────────────────── конфигурация ───────────────────────────

def load_config(path, section="monitor", defaults=None):
    """Чете JSON; ако има раздел `section`, взима него. Липсващите ключове идват от defaults."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw.get(section), dict):
        raw = raw[section]
    cfg = dict(defaults if defaults is not None else DEFAULTS)
    cfg.update(raw)
    return cfg


# ─────────────────────────── четци (чисти функции) ───────────────────────────

def read_text(path, default=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def parse_thermal(base="/sys/class/thermal"):
    """Температури по зони от /sys/class/thermal/thermal_zone*/{type,temp}. Празен списък, ако няма."""
    zones = []
    for d in sorted(glob.glob(os.path.join(base, "thermal_zone*")),
                    key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0)):
        raw = read_text(os.path.join(d, "temp"))
        if raw is None:
            continue
        try:
            milli = int(raw.strip())
        except ValueError:
            continue
        ztype = (read_text(os.path.join(d, "type"), "") or "").strip() or os.path.basename(d)
        zones.append({"zone": os.path.basename(d), "type": ztype, "c": round(milli / 1000.0, 1)})
    return zones


def parse_mdstat(text):
    """Разбор на /proc/mdstat → списък от масиви.

    Всеки масив: name, state (active/inactive), level, devices, members, up, degraded,
    readonly и по желание sync (дейност: recovery/resync/check…, процент).
    """
    if not text:
        return []
    arrays = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"^(md\S+)\s*:\s*(\S+)\s*(.*)$", line)
        if m:
            name, state, rest = m.groups()
            words = rest.split()
            readonly = False
            if words and words[0].startswith("(") and "read-only" in words[0]:
                readonly = True
                words = words[1:]
            level = words[0] if words and not re.search(r"\[\d+\]", words[0]) else None
            devs = [w for w in words if re.search(r"\[\d+\]", w)]
            cur = {
                "name": name, "state": state, "level": level,
                "devices": [re.sub(r"\[\d+\].*$", "", d) for d in devs],
                "failed": [re.sub(r"\[\d+\].*$", "", d) for d in devs if "(F)" in d],
                "members": None, "up": None, "degraded": False,
                "readonly": readonly, "sync": None,
            }
            arrays.append(cur)
            continue
        if cur is None:
            continue
        m = re.search(r"\[(\d+)/(\d+)\]\s*\[([U_]+)\]", line)
        if m:
            cur["members"], cur["up"] = int(m.group(1)), int(m.group(2))
            cur["degraded"] = "_" in m.group(3) or cur["up"] < cur["members"]
            continue
        m = re.search(r"(recovery|resync|reshape|check|repair)\s*=\s*([\d.]+)%", line)
        if m:
            cur["sync"] = {"action": m.group(1), "percent": float(m.group(2))}
            fin = re.search(r"finish=([\d.]+)min", line)
            if fin:
                cur["sync"]["finish_min"] = float(fin.group(1))
            continue
        m = re.search(r"(resync|recovery)\s*=\s*(DELAYED|PENDING)", line)
        if m:
            cur["sync"] = {"action": m.group(1), "percent": None, "pending": True}
        if not line.strip():
            cur = None
    for a in arrays:
        if a["state"] != "active" or a["failed"]:
            a["degraded"] = True
    return arrays


def parse_cpu_times(text):
    """/proc/stat → {"cpu": (busy, total), "cpu0": (...), ...}."""
    out = {}
    for line in (text or "").splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        vals = [int(x) for x in parts[1:9]]
        vals += [0] * (8 - len(vals))
        idle = vals[3] + vals[4]            # idle + iowait
        total = sum(vals)                   # guest е вече включено в user
        out[parts[0]] = (total - idle, total)
    return out


def cpu_percent(prev, cur):
    """Процент натоварване между две снимки на /proc/stat. → (общо, [по ядра])."""
    def pct(key):
        if key not in prev or key not in cur:
            return None
        db = cur[key][0] - prev[key][0]
        dt = cur[key][1] - prev[key][1]
        return round(100.0 * db / dt, 1) if dt > 0 else 0.0
    cores = sorted((k for k in cur if k != "cpu"), key=lambda k: int(k[3:]))
    return pct("cpu"), [pct(k) for k in cores]


def parse_meminfo(text):
    """/proc/meminfo → памет и swap в байтове."""
    kb = {}
    for line in (text or "").splitlines():
        m = re.match(r"^(\w+):\s+(\d+)", line)
        if m:
            kb[m.group(1)] = int(m.group(2)) * 1024
    total = kb.get("MemTotal", 0)
    avail = kb.get("MemAvailable", kb.get("MemFree", 0))
    stotal = kb.get("SwapTotal", 0)
    sfree = kb.get("SwapFree", 0)

    def block(t, used):
        return {"total": t, "used": used, "free": t - used,
                "percent": round(100.0 * used / t, 1) if t else 0.0}
    mem = block(total, total - avail)
    mem["available"] = avail
    return mem, block(stotal, stotal - sfree)


def disk_usage(mounts):
    out = []
    for mnt in mounts:
        try:
            u = shutil.disk_usage(mnt)
            out.append({"mount": mnt, "total": u.total, "used": u.used, "free": u.free,
                        "percent": round(100.0 * u.used / u.total, 1) if u.total else 0.0})
        except OSError as e:
            out.append({"mount": mnt, "error": e.strerror or str(e)})
    return out


def failed_units():
    """Паднали systemd услуги чрез `systemctl --failed` (само четене). None, ако няма systemd."""
    if not shutil.which("systemctl"):
        return None
    try:
        r = subprocess.run(["systemctl", "--failed", "--no-legend", "--plain", "--no-pager"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode not in (0, 1):
        return None
    return [ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()]


# ─────────────────────────── задачи ───────────────────────────

def compile_process_rules(rules):
    """[{"name":..., "pattern": regex}] → [(name, compiled)]. Лош шаблон → ValueError с името му."""
    out = []
    for r in rules or []:
        try:
            out.append((r.get("name") or r["pattern"], re.compile(r["pattern"])))
        except re.error as e:
            raise ValueError("лош шаблон за процес %r: %s" % (r.get("name"), e))
    return out


def process_elapsed(stat_text, uptime_s, clk_tck):
    """Колко секунди върви процес — от поле 22 (starttime) на /proc/<pid>/stat."""
    # името (поле 2) е в скоби и може да съдържа интервали — делим след последната ')'
    after = stat_text[stat_text.rfind(")") + 2:].split()
    start_ticks = int(after[19])          # поле 22 → индекс 19 след полета 1 и 2
    return max(0.0, uptime_s - start_ticks / float(clk_tck))


def scan_processes(rules, proc="/proc", self_pid=None, clk_tck=None):
    """Кои от наблюдаваните процеси вървят сега. Съпоставя шаблона с целия команден ред.

    Връща [{"name", "pid", "elapsed_s"}]. Самият команден ред не се показва — може да носи пътища.
    """
    if not rules:
        return []
    self_pid = os.getpid() if self_pid is None else self_pid
    clk_tck = clk_tck or os.sysconf("SC_CLK_TCK")
    try:
        uptime_s = float(read_text(os.path.join(proc, "uptime"), "0").split()[0])
    except (ValueError, IndexError):
        uptime_s = 0.0
    found = []
    for entry in os.listdir(proc):
        if not entry.isdigit() or int(entry) == self_pid:
            continue
        try:
            with open(os.path.join(proc, entry, "cmdline"), "rb") as f:
                raw = f.read()
        except OSError:
            continue                      # процесът е свършил или няма права
        cmd = raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()
        if not cmd:
            continue                      # нишка на ядрото
        for name, rx in rules:
            if rx.search(cmd):
                elapsed = None
                stat = read_text(os.path.join(proc, entry, "stat"))
                if stat:
                    try:
                        elapsed = round(process_elapsed(stat, uptime_s, clk_tck))
                    except (ValueError, IndexError):
                        pass
                found.append({"name": name, "pid": int(entry), "elapsed_s": elapsed})
                break
    found.sort(key=lambda p: (p["name"], p["pid"]))
    return found


def parse_line_time(line, time_regex=ISO_TIME, time_format=None):
    """Време от ред на лог → epoch (местно време) или None."""
    m = re.search(time_regex, line)
    if not m:
        return None
    s = m.group(1) if m.groups() else m.group(0)
    try:
        if time_format:
            dt = datetime.strptime(s, time_format)
            if dt.year == 1900:           # формат без година (напр. syslog) → тази година
                dt = dt.replace(year=datetime.now().year)
        else:
            dt = datetime.fromisoformat(s.replace(" ", "T", 1))
    except ValueError:
        return None
    return dt.timestamp()


def last_success(text, success_regex, time_regex=ISO_TIME, time_format=None):
    """Последният ред, който съвпада с шаблона за успех → (време epoch или None, намерен ли е).

    Ако редът няма време, търсим назад най-близкия ред с време (обичайно за
    многоредови логове: „--- начало 03:00“ … „OK“).
    """
    rx = re.compile(success_regex)
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if rx.search(lines[i]):
            for j in range(i, -1, -1):
                t = parse_line_time(lines[j], time_regex, time_format)
                if t is not None:
                    return t, True
            return None, True
    return None, False


def read_tail(path, limit=LOG_TAIL_BYTES):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - limit))
        data = f.read()
    if size > limit:                      # първият ред може да е отрязан
        data = data.split(b"\n", 1)[-1]
    return data.decode("utf-8", "replace")


def check_logs(rules, now=None):
    now = time.time() if now is None else now
    out = []
    for r in rules or []:
        item = {"name": r.get("name") or os.path.basename(r["path"]),
                "last_success": None, "ago_s": None, "found": False, "error": None}
        try:
            text = read_tail(r["path"])
            t, found = last_success(text, r["success"], r.get("time_regex", ISO_TIME),
                                    r.get("time_format"))
            if found and t is None:
                # редът за успех няма време → времето на последна промяна на файла
                t = os.path.getmtime(r["path"])
            item["found"] = found
            if t is not None:
                item["last_success"] = t
                item["ago_s"] = round(now - t)
        except OSError as e:
            item["error"] = e.strerror or str(e)
        except re.error as e:
            item["error"] = "лош шаблон: %s" % e
        out.append(item)
    return out


def tasks_summary(running, logs):
    """Общ отговор: има ли задача сега и кога е минала последната успешна."""
    times = [l["last_success"] for l in logs if l.get("last_success")]
    return {"busy": bool(running), "last_success": max(times) if times else None}


# ─────────────────────────── снимка и история ───────────────────────────

class Sampler:
    """Нишка, която на всеки sample_seconds прави снимка и пази история в deque."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg.get("name") or socket.gethostname()
        self.rules = compile_process_rules(cfg.get("tasks", {}).get("processes"))
        self.log_rules = cfg.get("tasks", {}).get("logs") or []
        n = max(1, int(cfg["history_minutes"] * 60 / cfg["sample_seconds"]))
        self.history = collections.deque(maxlen=n)
        self.lock = threading.Lock()
        self.prev_cpu = parse_cpu_times(read_text("/proc/stat"))
        self.now = None

    def snapshot(self):
        cur_cpu = parse_cpu_times(read_text("/proc/stat"))
        total, cores = cpu_percent(self.prev_cpu, cur_cpu)
        self.prev_cpu = cur_cpu
        mem, swap = parse_meminfo(read_text("/proc/meminfo"))
        load = [float(x) for x in (read_text("/proc/loadavg", "0 0 0") or "0 0 0").split()[:3]]
        mdstat = read_text("/proc/mdstat")
        running = scan_processes(self.rules)
        logs = check_logs(self.log_rules)
        return {
            "kind": "machine",
            "name": self.name,
            "time": time.time(),
            "uptime_s": round(float((read_text("/proc/uptime", "0") or "0").split()[0])),
            "load": load,
            "cpu": {"total": total, "cores": cores},
            "memory": mem,
            "swap": swap,
            "temps": parse_thermal(),
            "disks": disk_usage(self.cfg.get("mounts") or []),
            "raid": parse_mdstat(mdstat) if mdstat is not None else None,
            "failed_units": failed_units() if self.cfg.get("systemd", True) else None,
            "tasks": {"running": running, "logs": logs, "summary": tasks_summary(running, logs)},
        }

    def tick(self):
        try:
            snap = self.snapshot()
        except Exception as e:            # падането се показва, не се мълчи
            snap = {"kind": "machine", "name": self.name, "time": time.time(),
                    "error": "%s: %s" % (type(e).__name__, e)}
        with self.lock:
            self.now = snap
            self.history.append(history_point(snap))

    def run(self):
        while True:
            time.sleep(self.cfg["sample_seconds"])
            self.tick()

    def start(self):
        time.sleep(0.5)                    # кратък интервал за първия процент CPU
        self.tick()
        threading.Thread(target=self.run, daemon=True).start()

    def get_now(self):
        with self.lock:
            return self.now

    def get_history(self):
        with self.lock:
            return list(self.history)


def history_point(snap):
    """Компактна точка за историята."""
    temps = [t["c"] for t in snap.get("temps") or []]
    return {
        "t": round(snap["time"]),
        "cpu": (snap.get("cpu") or {}).get("total"),
        "mem": (snap.get("memory") or {}).get("percent"),
        "load1": (snap.get("load") or [None])[0],
        "temp": max(temps) if temps else None,
        "busy": ((snap.get("tasks") or {}).get("summary") or {}).get("busy"),
        "up": (snap.get("device") or {}).get("reachable"),
    }


# ─────────────────────────── HTTP ───────────────────────────

def make_handler(source):
    """source има get_now() и get_history(). Приема само GET — нищо не се променя."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "monitor-lite"

        def _send(self, code, body, ctype):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/now":
                self._send(200, json.dumps(source.get_now()), "application/json")
            elif path == "/api/history":
                self._send(200, json.dumps(source.get_history()), "application/json")
            elif path in ("/", "/index.html"):
                self._send(200, PAGE, "text/html; charset=utf-8")
            else:
                self._send(404, '{"error":"not found"}', "application/json")

        do_HEAD = do_GET

        def log_message(self, *args):     # без шум в журнала за всяка заявка
            pass

    return Handler


def serve(cfg, source):
    httpd = ThreadingHTTPServer((cfg["listen"], int(cfg["port"])), make_handler(source))
    print("monitor-lite: http://%s:%s/ (read-only)" % (cfg["listen"], cfg["port"]), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


# Страницата: една, тъмна, без външни ресурси. Показва каквото има в /api/now —
# същата страница служи и за проба на устройство (probe_device.py).
PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>monitor</title>
<style>
:root{--bg:#080D16;--p:#101825;--p2:#16202E;--ink:#E6ECF3;--i2:#94A3B4;--i3:#5C6B7C;--ln:#1E2A3A;--mint:#2FCFBF;--warn:#E8A93C}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 8px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px;margin-bottom:16px}
h1{font-size:22px;margin:0;font-weight:600}
.sub{color:var(--i2)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--i3);margin-right:6px}
.dot.ok{background:var(--mint)}.dot.bad{background:var(--warn)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.card{background:var(--p);border:1px solid var(--ln);border-radius:10px;padding:14px}
.card.wide{grid-column:1/-1}
.card h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--i3);margin:0 0 10px;font-weight:600}
.row{display:flex;justify-content:space-between;gap:10px;padding:3px 0}
.row .k{color:var(--i2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .v{font-variant-numeric:tabular-nums;white-space:nowrap}
.big{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}
.bar{height:6px;background:var(--p2);border-radius:3px;overflow:hidden;margin:3px 0 8px}
.bar i{display:block;height:100%;background:var(--mint)}
.bar i.hot{background:var(--warn)}
.cores{display:grid;grid-template-columns:repeat(auto-fill,minmax(38px,1fr));gap:4px}
.core{background:var(--p2);border-radius:4px;height:34px;position:relative;overflow:hidden}
.core i{position:absolute;left:0;right:0;bottom:0;background:var(--mint);opacity:.75}
.core i.hot{background:var(--warn)}
.core span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:11px}
.warn{color:var(--warn)}.ok{color:var(--mint)}.muted{color:var(--i3)}
.answer{font-size:17px;margin-bottom:8px}
svg{display:block;width:100%;height:60px}
footer{text-align:center;color:var(--i3);font-size:12px;padding:18px 0 24px}
</style></head><body><main>
<header><h1 id="name">…</h1><span class="sub" id="meta"></span></header>
<div id="err" class="card wide warn" hidden></div>
<div class="grid" id="grid"></div>
</main>
<footer>read-only · controls nothing</footer>
<script>
"use strict";
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pct=v=>v==null?"–":v.toFixed(1)+"%";
function bytes(n){if(n==null)return"–";const u=["B","KB","MB","GB","TB","PB"];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return n.toFixed(i?1:0)+" "+u[i]}
function dur(s){if(s==null)return"–";s=Math.round(s);if(s<60)return s+"s";const m=Math.floor(s/60);if(m<60)return m+"m";const h=Math.floor(m/60);if(h<48)return h+"h "+(m%60)+"m";return Math.floor(h/24)+"d "+(h%24)+"h"}
function ago(s){return s==null?"never seen":dur(s)+" ago"}
const bar=(v,hot)=>`<div class="bar"><i class="${v>=hot?"hot":""}" style="width:${Math.min(100,v||0)}%"></i></div>`;
const row=(k,v,cls="")=>`<div class="row"><span class="k">${esc(k)}</span><span class="v ${cls}">${v}</span></div>`;
const card=(t,body,wide)=>`<section class="card${wide?" wide":""}"><h2>${esc(t)}</h2>${body}</section>`;
let hist=[];
function spark(key,max){
  const pts=hist.map(h=>h[key]).filter(v=>v!=null);
  if(pts.length<2)return"";
  const top=max||Math.max(1,...pts),w=300,h=60;
  const d=pts.map((v,i)=>`${(i/(pts.length-1)*w).toFixed(1)},${(h-2-(v/top)*(h-4)).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${d}" fill="none" stroke="var(--mint)" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
}
function tasksCard(t,now){
  if(!t)return"";
  const s=t.summary||{};let b="";
  const since=s.last_success?now-s.last_success:null;
  b+=`<div class="answer">${s.busy?'<span class="dot bad"></span>Task running now':'<span class="dot ok"></span>Idle — nothing running'}`+
     ` <span class="sub">· last success ${ago(since)}</span></div>`;
  if(t.source)b+=row("source",esc(t.source.name||"")+(t.source.ok?"":" — unreachable"),t.source.ok?"":"warn");
  for(const p of t.running||[])b+=row(p.name+" (pid "+p.pid+")","running "+dur(p.elapsed_s),"warn");
  for(const l of t.logs||[]){
    const v=l.error?esc(l.error):(l.found?ago(l.ago_s):"no success line yet");
    b+=row(l.name,v,l.error||!l.found?"warn":"");
  }
  return card("Tasks",b,true);
}
function render(d){
  $("#err").hidden=!d.error;if(d.error)$("#err").textContent=d.error;
  document.title=(d.name||"monitor")+" · monitor";
  $("#name").textContent=d.name||"?";
  const now=d.time||Date.now()/1000;
  let meta=[];
  if(d.uptime_s!=null)meta.push("up "+dur(d.uptime_s));
  if(d.load)meta.push("load "+d.load.map(x=>x.toFixed(2)).join(" "));
  meta.push("updated "+new Date(now*1000).toLocaleTimeString());
  $("#meta").textContent=meta.join(" · ");
  let h=tasksCard(d.tasks,now);
  const dev=d.device;
  if(dev){
    let b=row("reachable",dev.reachable?'<span class="dot ok"></span>yes':'<span class="dot bad"></span>no',dev.reachable?"":"warn");
    if(dev.ping)b+=row("ping",dev.ping.ok?(dev.ping.ms!=null?dev.ping.ms.toFixed(1)+" ms":"ok"):"no reply",dev.ping.ok?"":"warn");
    for(const p of dev.ports||[])b+=row("tcp "+p.port,p.open?"open":"closed",p.open?"ok":"warn");
    b+=spark("up",1);
    h+=card("Device",b);
  }
  if(d.cpu&&d.cpu.cores){
    let b=`<div class="big">${pct(d.cpu.total)}</div><div class="cores">`;
    d.cpu.cores.forEach((c,i)=>{b+=`<div class="core" title="cpu${i}"><i class="${c>=90?"hot":""}" style="height:${c||0}%"></i><span>${c==null?"–":Math.round(c)}</span></div>`});
    h+=card("CPU",b+"</div>"+spark("cpu",100));
  }
  if(d.memory){
    let b=row("memory",bytes(d.memory.used)+" / "+bytes(d.memory.total)+" · "+pct(d.memory.percent))+bar(d.memory.percent,90);
    if(d.swap)b+=row("swap",d.swap.total?bytes(d.swap.used)+" / "+bytes(d.swap.total)+" · "+pct(d.swap.percent):"none")+(d.swap.total?bar(d.swap.percent,50):"");
    h+=card("Memory",b+spark("mem",100));
  }
  if(d.temps&&d.temps.length){
    let b="";for(const t of d.temps)b+=row(t.type,t.c.toFixed(1)+" °C",t.c>=80?"warn":"");
    h+=card("Temperature",b+spark("temp"));
  }
  if(d.disks&&d.disks.length){
    let b="";for(const k of d.disks){
      if(k.error){b+=row(k.mount,esc(k.error),"warn");continue}
      b+=row(k.mount,bytes(k.free)+" free · "+pct(k.percent))+bar(k.percent,90);
    }
    h+=card("Disks",b);
  }
  if(d.raid&&d.raid.length){
    let b="";for(const a of d.raid){
      let v=a.degraded?"DEGRADED":"ok";
      if(a.members!=null)v+=` [${a.up}/${a.members}]`;
      if(a.sync)v+=" · "+a.sync.action+(a.sync.percent!=null?" "+a.sync.percent+"%":" pending");
      b+=row(a.name+" "+(a.level||""),v,a.degraded?"warn":"ok");
    }
    h+=card("RAID (mdadm)",b);
  }
  if(d.failed_units){
    h+=card("Failed services",d.failed_units.length?d.failed_units.map(u=>row(u,"failed","warn")).join(""):'<span class="ok">none</span>');
  }
  $("#grid").innerHTML=h;
}
async function tick(){
  try{const r=await fetch("api/now",{cache:"no-store"});const d=await r.json();if(d)render(d)}
  catch(e){$("#err").hidden=false;$("#err").textContent="monitor unreachable: "+e}
}
async function history(){try{hist=await (await fetch("api/history",{cache:"no-store"})).json()}catch(e){}}
history().then(tick);setInterval(tick,5000);setInterval(history,30000);
</script></body></html>
"""


def main(argv):
    if len(argv) < 2:
        print("употреба: monitor_lite.py config.json", file=sys.stderr)
        return 2
    cfg = load_config(argv[1])
    sampler = Sampler(cfg)
    sampler.start()
    serve(cfg, sampler)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
