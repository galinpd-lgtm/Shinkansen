#!/usr/bin/env python3
"""pazach — пазач: чете готови състояния, вика само при промяна.

    pazach.py --config ФАЙЛ --once        # един ход (systemd таймер на 15 мин)
    pazach.py --config ФАЙЛ --digest      # ход + сутрешна сводка и изтичащото до 14 дни
    ... [--dry-run]                       # без webhook: известията само се отпечатват

Проверки (в конфигурацията, извън репото):
  monitor     — /api/now на monitor_lite.py или probe_device.py: не отговаря → rip;
                температура, диск над праг; RAID degraded; паднали услуги; задача над N часа;
                последен успех по-стар от N часа; устройство недостъпно
  status_json — JSON от адрес или файл, прост път до поле + праг (стойност или възраст)
  expiry      — дата → предупреждение N дни преди, тревога M дни преди, изтекло

Нива: ok · warn · crit · rip (трябва да е жив, а мълчи) · off (нарочно спрян, "enabled": false).

Всеки ход:
  - пише обобщен status.json атомарно: {"generated","overall","counts","items":[{"level","name","msg","link"}]}
  - пази състоянието на всяка проверка (state файл) и праща известие към webhook само при смяна
    на нивото и при възстановяване: {"level","check","message","since"}. Неуспешно известие се
    опитва пак при следващия ход — не се губи и не се повтаря след успех.
  - добавя ред в $SHINKANSEN_RUNS/pazach.jsonl (когато не е пуснат през bin/shinkansen — тогава
    реда го пише диспечерът).

Код на изход: 0 — всичко ok · 4 — има warn/crit/rip · 1 — известие не можа да се изпрати
или конфигурацията е счупена · 2 — грешна употреба.
"""
import argparse
import json
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

LEVELS = ("ok", "warn", "crit", "rip", "off")
SEVERITY = {"off": -1, "ok": 0, "warn": 1, "crit": 2, "rip": 3}
USER_AGENT = "shinkansen-pazach/1.0"
DIGEST_EXPIRY_DAYS = 14

MONITOR_DEFAULTS = {
    "temp_warn_c": 80, "temp_crit_c": 90,
    "disk_warn_percent": 85, "disk_crit_percent": 95,
    "task_max_hours": 6,             # задача, която върви по-дълго → warn
    "success_max_hours": None,       # последен успешен ред по-стар → warn (None — не се проверява)
    "stale_seconds": 300,            # снимката на монитора е по-стара → rip (мониторът е заседнал)
    "raid": True, "failed_units": True,
}


# ─────────────────────────── общи ───────────────────────────

def now_iso(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).isoformat(timespec="seconds")


def expand(path):
    return os.path.expanduser(os.path.expandvars(path)) if path else path


def http_get_json(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post_json(url, payload, timeout, headers=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    h = {"User-Agent": USER_AGENT, "Content-Type": "application/json; charset=utf-8"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def atomic_write_json(path, obj):
    """Пише във временен файл до целевия и го подменя наведнъж — четецът никога не вижда половин файл."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".%s." % os.path.basename(path), dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def worst(levels):
    levels = [l for l in levels if l != "off"]
    return max(levels, key=SEVERITY.get) if levels else "ok"


def fmt_hours(seconds):
    h = seconds / 3600.0
    return "%.0f мин" % (seconds / 60) if h < 1 else ("%.1f ч" % h if h < 48 else "%.0f дни" % (h / 24))


# ─────────────────────────── проверки ───────────────────────────

class Unreachable(Exception):
    """Източникът не отговаря — за пазача това е rip, не crit."""


def load_source(check, fetch, timeout):
    """JSON от "url" или "path". Недостъпен → Unreachable."""
    try:
        if check.get("url"):
            return fetch(check["url"], timeout)
        with open(expand(check["path"]), encoding="utf-8") as f:
            return json.load(f)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise Unreachable(getattr(e, "reason", None) or e.__class__.__name__)
    except ValueError:
        raise Unreachable("лош JSON")


def check_monitor(check, fetch, now, timeout):
    """→ (ниво, съобщение). Събира всички нередности; нивото е най-тежкото."""
    c = dict(MONITOR_DEFAULTS, **check)
    try:
        d = load_source(check, fetch, timeout)
    except Unreachable as e:
        return "rip", "не отговаря (%s)" % e
    if not isinstance(d, dict):
        return "crit", "неочакван отговор"
    issues = []                                      # [(ниво, текст)]
    if d.get("error"):
        issues.append(("crit", "мониторът докладва грешка: %s" % d["error"]))
    t = d.get("time")
    if isinstance(t, (int, float)) and c["stale_seconds"] and now - t > c["stale_seconds"]:
        issues.append(("rip", "данните са от преди %s" % fmt_hours(now - t)))
    temps = [x.get("c") for x in d.get("temps") or [] if isinstance(x.get("c"), (int, float))]
    if temps:
        m = max(temps)
        if m >= c["temp_crit_c"]:
            issues.append(("crit", "температура %.0f°C" % m))
        elif m >= c["temp_warn_c"]:
            issues.append(("warn", "температура %.0f°C" % m))
    for k in d.get("disks") or []:
        label = " · ".join(k.get("mounts") or [k.get("mount", "?")])
        if k.get("error"):
            issues.append(("warn", "диск %s: %s" % (label, k["error"])))
        elif isinstance(k.get("percent"), (int, float)):
            if k["percent"] >= c["disk_crit_percent"]:
                issues.append(("crit", "диск %s %.0f%%" % (label, k["percent"])))
            elif k["percent"] >= c["disk_warn_percent"]:
                issues.append(("warn", "диск %s %.0f%%" % (label, k["percent"])))
    if c["raid"]:
        for a in d.get("raid") or []:
            if a.get("degraded"):
                issues.append(("crit", "RAID %s degraded" % a.get("name", "?")))
    if c["failed_units"] and d.get("failed_units"):
        u = d["failed_units"]
        issues.append(("warn", "паднали услуги: %s%s" % (", ".join(u[:3]), " +%d" % (len(u) - 3) if len(u) > 3 else "")))
    tasks = d.get("tasks") or {}
    if c["task_max_hours"]:
        for p in tasks.get("running") or []:
            if isinstance(p.get("elapsed_s"), (int, float)) and p["elapsed_s"] > c["task_max_hours"] * 3600:
                issues.append(("warn", "%s върви %s" % (p.get("name", "задача"), fmt_hours(p["elapsed_s"]))))
    if c["success_max_hours"]:
        for l in tasks.get("logs") or []:
            ts = l.get("last_success")
            if not ts:
                issues.append(("warn", "%s: няма успешен ход" % l.get("name", "лог")))
            elif now - ts > c["success_max_hours"] * 3600:
                issues.append(("warn", "%s: последен успех преди %s" % (l.get("name", "лог"), fmt_hours(now - ts))))
    src = tasks.get("source")
    if isinstance(src, dict) and src.get("ok") is False:
        issues.append(("warn", "не чете задачите от %s" % src.get("name", "пишещата машина")))
    dev = d.get("device")
    if isinstance(dev, dict):                       # проба за устройство (probe_device.py)
        if dev.get("reachable") is False:
            issues.append(("rip", "устройството не отговаря"))
        closed = [str(p["port"]) for p in dev.get("ports") or [] if p.get("open") is False]
        if closed and dev.get("reachable"):
            issues.append(("warn", "затворени портове: %s" % ", ".join(closed)))
    if issues:
        level = worst([i[0] for i in issues])
        ordered = sorted(issues, key=lambda i: -SEVERITY[i[0]])
        return level, "; ".join(i[1] for i in ordered)
    parts = []
    if temps:
        parts.append("%.0f°C" % max(temps))
    disks = [k["percent"] for k in d.get("disks") or [] if isinstance(k.get("percent"), (int, float))]
    if disks:
        parts.append("диск до %.0f%%" % max(disks))
    if tasks.get("running"):
        parts.append("задачи: %d" % len(tasks["running"]))
    if isinstance(dev, dict):
        parts.append("отговаря")
    return "ok", " · ".join(parts) or "наред"


def get_path(obj, path):
    """Прост път до поле: "tasks.summary.last_success", "items.0.level". Липсва → KeyError."""
    cur = obj
    for part in str(path).split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(part)
    return cur


def to_epoch(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.astimezone()                           # без зона → местно време
    return dt.timestamp()


def check_status_json(check, fetch, now, timeout):
    """Прагове (всеки по желание): expect, warn_above, crit_above, warn_below, crit_below,
    warn_age_hours, crit_age_hours (полето е време: epoch или ISO)."""
    try:
        d = load_source(check, fetch, timeout)
    except Unreachable as e:
        return "rip", "не отговаря (%s)" % e
    field = check["field"]
    try:
        v = get_path(d, field)
    except (KeyError, IndexError, ValueError, TypeError):
        return "crit", "липсва поле %s" % field
    label = check.get("label") or field
    if "expect" in check:
        if v != check["expect"]:
            return check.get("expect_level", "crit"), "%s = %s (очаква се %s)" % (label, v, check["expect"])
        return "ok", "%s = %s" % (label, v)
    if "warn_age_hours" in check or "crit_age_hours" in check:
        if v in (None, ""):
            return "crit", "%s: няма стойност" % label
        try:
            age = now - to_epoch(v)
        except (ValueError, TypeError):
            return "crit", "%s: не е време (%s)" % (label, v)
        text = "%s преди %s" % (label, fmt_hours(max(0, age)))
        if "crit_age_hours" in check and age > check["crit_age_hours"] * 3600:
            return "crit", text
        if "warn_age_hours" in check and age > check["warn_age_hours"] * 3600:
            return "warn", text
        return "ok", text
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "crit", "%s не е число (%s)" % (label, v)
    unit = check.get("unit", "")
    text = "%s %g%s" % (label, v, unit)
    if "crit_above" in check and v > check["crit_above"]:
        return "crit", text
    if "crit_below" in check and v < check["crit_below"]:
        return "crit", text
    if "warn_above" in check and v > check["warn_above"]:
        return "warn", text
    if "warn_below" in check and v < check["warn_below"]:
        return "warn", text
    return "ok", text


def days_left(check, today):
    return (date.fromisoformat(check["date"]) - today).days


def check_expiry(check, today):
    what = check.get("what") or check["name"]
    try:
        left = days_left(check, today)
    except (KeyError, ValueError):
        return "crit", "невалидна дата: %s" % check.get("date")
    warn_days, crit_days = check.get("warn_days", 30), check.get("crit_days", 7)
    if left < 0:
        return "crit", "%s изтече преди %d дни (%s)" % (what, -left, check["date"])
    if left == 0:
        return "crit", "%s изтича днес" % what
    text = "%s изтича след %d дни (%s)" % (what, left, check["date"])
    if left <= crit_days:
        return "crit", text
    if left <= warn_days:
        return "warn", text
    return "ok", text


def run_check(check, fetch, now, today, timeout):
    """Една проверка → (ниво, съобщение). Изключение в проверката е crit, не мълчание."""
    if check.get("enabled", True) is False:
        return "off", check.get("off_reason", "нарочно спрян")
    try:
        kind = check["type"]
        if kind == "monitor":
            return check_monitor(check, fetch, now, check.get("timeout", timeout))
        if kind == "status_json":
            return check_status_json(check, fetch, now, check.get("timeout", timeout))
        if kind == "expiry":
            return check_expiry(check, today)
        return "crit", "непознат тип проверка: %s" % kind
    except Exception as e:                           # noqa: BLE001 — пазачът не пада заради една проверка
        return "crit", "проверката падна: %s: %s" % (type(e).__name__, e)


# ─────────────────────────── състояние и известия ───────────────────────────

def baseline(level):
    """Спрямо какво се сравнява за известие: off и „никога не виждан“ се броят като ok."""
    return "ok" if level in (None, "off") else level


def update_state(state, name, level, message, now):
    """Обновява записа на проверката. → записът. since се мени само при смяна на нивото."""
    rec = state.get(name)
    if not rec or rec.get("level") != level:
        rec = {"level": level, "since": now_iso(now), "message": message,
               "notified": rec.get("notified") if rec else None}
        state[name] = rec
    rec["message"] = message
    if level == "off":
        rec["notified"] = "ok"                       # нарочно спрян — без известие; при връщане сравняваме с ok
    return rec


def pending_notice(name, rec):
    """Известие, ако нивото е различно от последното изпратено. Иначе None."""
    if rec["level"] == "off":
        return None
    if baseline(rec["level"]) == baseline(rec.get("notified")):
        return None
    msg = rec["message"]
    if rec["level"] == "ok":
        msg = "възстановено: " + msg
    return {"level": rec["level"], "check": name, "message": msg, "since": rec["since"]}


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def build_status(results, now):
    """results: [(проверка, ниво, съобщение)] → status.json точно във формата на лентата."""
    counts = {l: 0 for l in LEVELS}
    items = []
    for check, level, msg in results:
        counts[level] += 1
        items.append({"level": level, "name": check["name"], "msg": msg, "link": check.get("link")})
    w = worst([r[1] for r in results])
    overall = "crit" if w in ("crit", "rip") else w
    return {"generated": now_iso(now), "overall": overall, "counts": counts, "items": items}


def digest_text(results, checks, today, days=DIGEST_EXPIRY_DAYS):
    """Сутрешна сводка: не-ok проверките, изтичащото до days дни, броят на наредените."""
    lines = []
    bad = [(c, l, m) for c, l, m in results if l not in ("ok", "off")]
    for c, l, m in sorted(bad, key=lambda r: -SEVERITY[r[1]]):
        lines.append("%s %s: %s" % (l.upper(), c["name"], m))
    soon = []
    for c in checks:
        if c.get("type") == "expiry" and c.get("enabled", True) is not False:
            try:
                left = days_left(c, today)
            except (KeyError, ValueError):
                continue
            if left <= days:
                soon.append((left, "%s — %s (%s)" % (c.get("what") or c["name"],
                                                      "изтекло" if left < 0 else "след %d дни" % left, c["date"])))
    if soon:
        lines.append("Изтича до %d дни:" % days)
        lines += ["  " + s for _, s in sorted(soon)]
    ok = sum(1 for _, l, _ in results if l == "ok")
    off = sum(1 for _, l, _ in results if l == "off")
    lines.append("Наред: %d от %d%s." % (ok, len(results) - off, (", спрени: %d" % off) if off else ""))
    return "\n".join(lines)


def log_run(ok, summary, now):
    """Ред в $SHINKANSEN_RUNS/pazach.jsonl. Под диспечера — обобщението отива при него."""
    sf = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if sf:
        with open(sf, "w", encoding="utf-8") as f:
            f.write(summary)
        return
    runs = os.environ.get("SHINKANSEN_RUNS")
    if not runs:
        return
    os.makedirs(runs, exist_ok=True)
    rec = {"t": now_iso(now), "helper": "pazach", "ok": bool(ok), "summary": summary[:200]}
    with open(os.path.join(runs, "pazach.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ─────────────────────────── ход ───────────────────────────

def validate_config(cfg):
    errors = []
    if not isinstance(cfg.get("checks"), list) or not cfg["checks"]:
        errors.append("няма checks")
        return errors
    names = set()
    for i, c in enumerate(cfg["checks"]):
        n = c.get("name")
        if not n:
            errors.append("проверка %d без name" % i)
        elif n in names:
            errors.append("повторено име: %s" % n)
        names.add(n)
        t = c.get("type")
        if t in ("monitor", "status_json") and not (c.get("url") or c.get("path")):
            errors.append("%s: нужен е url или path" % n)
        if t == "status_json" and not c.get("field"):
            errors.append("%s: нужно е field" % n)
        if t == "expiry" and not c.get("date"):
            errors.append("%s: нужна е date" % n)
    if not cfg.get("status_file"):
        errors.append("няма status_file")
    if not cfg.get("state_file"):
        errors.append("няма state_file")
    return errors


def run(cfg, digest=False, dry_run=False, fetch=http_get_json, post=http_post_json, now=None, today=None,
        out=sys.stdout):
    """Един ход. → (код на изход, обобщение)."""
    now = time.time() if now is None else now
    today = today or datetime.fromtimestamp(now).date()
    timeout = cfg.get("timeout_seconds", 5)
    state_path, status_path = expand(cfg["state_file"]), expand(cfg["status_file"])
    state = load_state(state_path)
    checks = cfg["checks"]
    results = []
    notices = []
    for c in checks:
        level, msg = run_check(c, fetch, now, today, timeout)
        results.append((c, level, msg))
        n = pending_notice(c["name"], update_state(state, c["name"], level, msg, now))
        if n:
            notices.append(n)
    # проверки, махнати от конфигурацията, се забравят
    for name in [k for k in state if k not in {c["name"] for c in checks}]:
        del state[name]

    hook = cfg.get("webhook") or {}
    send_failed = 0

    def send(payload):
        if dry_run or not hook.get("url"):
            if payload["check"] != "digest":         # сводката вече е отпечатана като текст
                print("→ %s" % json.dumps(payload, ensure_ascii=False), file=out)
            return True
        try:
            post(hook["url"], payload, hook.get("timeout", 10), hook.get("headers"))
            return True
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            print("! известието за %s не мина: %s" % (payload["check"], getattr(e, "reason", e)), file=sys.stderr)
            return False

    for n in notices:
        if send(n):
            state[n["check"]]["notified"] = n["level"]
        else:
            send_failed += 1                          # notified остава старото → опит пак следващия ход

    status = build_status(results, now)
    if digest:
        text = digest_text(results, checks, today, cfg.get("digest_expiry_days", DIGEST_EXPIRY_DAYS))
        print(text, file=out)
        if not send({"level": status["overall"], "check": "digest", "message": text, "since": status["generated"]}):
            send_failed += 1

    atomic_write_json(status_path, status)
    atomic_write_json(state_path, state)

    c = status["counts"]
    summary = "%s · ok %d, warn %d, crit %d, rip %d, off %d · известия %d%s" % (
        status["overall"], c["ok"], c["warn"], c["crit"], c["rip"], c["off"], len(notices),
        (", неизпратени %d" % send_failed) if send_failed else "")
    if digest:
        summary = "сводка · " + summary
    if send_failed:
        return 1, summary
    return (4 if status["overall"] != "ok" else 0), summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="Пазач: чете готови състояния, вика само при промяна.")
    ap.add_argument("--config", required=True, help="JSON конфигурация (извън репото)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="един ход")
    mode.add_argument("--digest", action="store_true", help="ход + сутрешна сводка")
    ap.add_argument("--dry-run", action="store_true", help="без webhook — известията се отпечатват")
    a = ap.parse_args(argv)
    now = time.time()
    try:
        with open(expand(a.config), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        print("конфигурацията не се чете: %s" % e, file=sys.stderr)
        log_run(False, "счупена конфигурация", now)
        return 1
    errors = validate_config(cfg)
    if errors:
        print("конфигурация: " + "; ".join(errors), file=sys.stderr)
        log_run(False, "счупена конфигурация", now)
        return 1
    code, summary = run(cfg, digest=a.digest, dry_run=a.dry_run, now=now)
    if not a.digest:
        print(summary)
    log_run(code in (0, 4), summary, now)
    return code


if __name__ == "__main__":
    sys.exit(main())
