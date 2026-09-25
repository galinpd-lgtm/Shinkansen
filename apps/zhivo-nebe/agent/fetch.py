#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Живо небе — агентът, който пише forecast.json.

Тегли прогнозата от няколко безплатни източника без ключ (Open-Meteo с три модела,
MET Norway, 7Timer), привежда ги към общ часов формат, смята медиана и разминаване,
дневен риск и риск/сцена за всяка проява от конфигурацията.
Договорът за изхода: schema/forecast.schema.md. Само стандартната библиотека.

Пускане:  python3 agent/fetch.py [път/до/city.json] [--out път/до/forecast.json]
"""
import argparse
import json
import math
import os
import socket
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(APP_DIR, "config", "city.example.json")
REPO_URL = "https://github.com/galinpd-lgtm/Shinkansen"
# MET Norway изисква User-Agent, който идентифицира приложението и дава връзка за контакт
USER_AGENT = f"Shinkansen-zhivo-nebe/1.0 (+{REPO_URL})"

SCHEMA_VERSION = "2"
FORECAST_DAYS = 7            # колко дни напред пазим в hours[]/days[]
HTTP_TIMEOUT = 20            # секунди за една заявка
ATTEMPTS = 3                 # опити на източник
BACKOFF_S = 2.0              # изчакване 2 s, после 4 s
UTC = timezone.utc

FIELDS = ("temp_c", "precip_pct", "wind_kmh", "gust_kmh", "cloud_pct")
# разминаване по величина (max − min в мерната ѝ единица): изходно поле → величина
SPREAD_FIELDS = {"spread_temp": "temp_c", "spread_precip": "precip_pct", "spread_wind": "wind_kmh"}
RISK_LEVELS = ("low", "medium", "high")

DEFAULT_SOURCES = ["open-meteo:icon_seamless", "open-meteo:gfs_seamless",
                   "open-meteo:ecmwf_ifs025", "met-norway", "7timer"]


class SourceError(Exception):
    """Източникът не отговори или отговорът е негоден."""


# ---------------------------------------------------------------- мрежа

def http_get(url):
    """Една GET заявка; връща суровите байтове. Подменя се в тестовете."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return r.read()


def fetch_json(url, fetcher, sleep):
    """Тегли и разчита JSON с повторни опити (503/429, таймаут, мрежа, лош JSON).
    Други 4xx не се повтарят — заявката е грешна и повторът няма да помогне."""
    last = "неизвестна грешка"
    for i in range(ATTEMPTS):
        try:
            raw = fetcher(url)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code != 429 and e.code < 500:
                break
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            last = f"мрежа: {getattr(e, 'reason', e)}"
        except (ValueError, UnicodeDecodeError):  # JSONDecodeError е ValueError
            last = "лош JSON"
        if i < ATTEMPTS - 1:
            sleep(BACKOFF_S * 2 ** i)
    raise SourceError(last)


# ---------------------------------------------------------------- общи помощници

def rec(temp_c=None, precip_pct=None, gust_kmh=None, cloud_pct=None, thunder=False, snow=False,
        wind_kmh=None):
    """Един час от един източник в общия формат. wind_kmh е среден вятър, gust_kmh — порив."""
    return {"temp_c": temp_c, "precip_pct": precip_pct, "wind_kmh": wind_kmh, "gust_kmh": gust_kmh,
            "cloud_pct": cloud_pct, "thunder": bool(thunder), "snow": bool(snow)}


def num(x):
    return None if x is None else float(x)


# ---------------------------------------------------------------- източници

THUNDER_WMO = {95, 96, 99}
SNOW_WMO = {71, 73, 75, 77, 85, 86}


def fetch_open_meteo(cfg, model, fetcher, sleep):
    """Open-Meteo, един модел на заявка — всеки модел е отделен източник и пада отделно."""
    q = urllib.parse.urlencode({
        "latitude": cfg["lat"], "longitude": cfg["lon"],
        "hourly": "temperature_2m,precipitation_probability,wind_speed_10m,"
                  "wind_gusts_10m,cloud_cover,weather_code",
        "models": model, "timezone": "GMT", "forecast_days": FORECAST_DAYS + 1,
    })
    data = fetch_json(f"https://api.open-meteo.com/v1/forecast?{q}", fetcher, sleep)
    return parse_open_meteo(data, model)


def parse_open_meteo(data, model):
    h = data["hourly"]
    times = h["time"]

    def col(name):
        # при един модел ключът е без суфикс; при няколко — с `_<модел>`
        return h.get(name) or h.get(f"{name}_{model}") or [None] * len(times)

    temp, prob = col("temperature_2m"), col("precipitation_probability")
    wind, gust = col("wind_speed_10m"), col("wind_gusts_10m")
    cloud, code = col("cloud_cover"), col("weather_code")
    out = {}
    for i, t in enumerate(times):
        dt = datetime.fromisoformat(t).replace(tzinfo=UTC)
        c = code[i]
        # ECMWF често няма вероятност за валеж — остава null, не я измисляме
        out[dt] = rec(num(temp[i]), num(prob[i]), num(gust[i]), num(cloud[i]),
                      thunder=c in THUNDER_WMO, snow=c in SNOW_WMO, wind_kmh=num(wind[i]))
    return out


def fetch_met_norway(cfg, fetcher, sleep):
    """MET Norway locationforecast 2.0 (complete). Времената са в UTC.
    Извън Северна Европа няма вероятност за валеж и пориви — тогава полетата са null."""
    # условията им: координати с най-много 4 знака след десетичната запетая
    q = urllib.parse.urlencode({"lat": round(cfg["lat"], 4), "lon": round(cfg["lon"], 4)})
    data = fetch_json(f"https://api.met.no/weatherapi/locationforecast/2.0/complete?{q}",
                      fetcher, sleep)
    return parse_met_norway(data)


def parse_met_norway(data):
    """Само часовете, за които MET има собствена стойност. След ~2,5 дни стъпката е
    6 часа — междинните часове остават без MET (без пренасяне и без интерполация)."""
    out = {}
    for ts in data["properties"]["timeseries"]:
        dt = datetime.fromisoformat(ts["time"].replace("Z", "+00:00")).astimezone(UTC)
        d = ts["data"]
        inst = d["instant"]["details"]
        nxt = d.get("next_1_hours") or d.get("next_6_hours")
        if not nxt:
            continue
        sym = nxt.get("summary", {}).get("symbol_code", "")
        det = nxt.get("details", {})
        # само истинска вероятност; precipitation_amount (mm) не е вероятност
        p = det.get("probability_of_precipitation")
        # само истински порив; средният вятър (wind_speed) не се подменя като порив
        g = inst.get("wind_speed_of_gust")
        w = inst.get("wind_speed")
        out[dt] = rec(
            num(inst.get("air_temperature")), num(p),
            None if g is None else g * 3.6,  # m/s → km/h
            num(inst.get("cloud_area_fraction")),
            thunder="thunder" in sym, snow=("snow" in sym or "sleet" in sym),
            wind_kmh=None if w is None else w * 3.6)  # m/s → km/h
    return out


# 7Timer дава класове, не стойности: cloudcover 1–9 → представителен процент
CLOUD_7T = {1: 3, 2: 12, 3: 25, 4: 37, 5: 50, 6: 62, 7: 75, 8: 87, 9: 97}
# wind10m.speed 1–8 → среда на класа в km/h (класове в m/s: <0,3 · 0,3–3,4 · 3,4–8 · 8–10,8 ·
# 10,8–17,2 · 17,2–24,5 · 24,5–32,6 · >32,6); за последния клас — долната граница
WIND_7T_KMH = {1: 0.5, 2: 6.7, 3: 20.5, 4: 33.8, 5: 50.4, 6: 75.1, 7: 102.8, 8: 117.4}


def fetch_7timer(cfg, fetcher, sleep):
    """7Timer, продукт civil — 3-часови стъпки; времето е init (UTC) + timepoint часа.
    Няма вероятност за валеж и пориви (prec_amount е код 0–9); средният вятър е клас 1–8.
    Дава температура, среден вятър, облачност, гръмотевица и сняг."""
    q = urllib.parse.urlencode({"lon": cfg["lon"], "lat": cfg["lat"], "ac": 0,
                                "unit": "metric", "output": "json", "tzshift": 0})
    data = fetch_json(f"https://www.7timer.info/bin/civil.php?{q}", fetcher, sleep)
    return parse_7timer(data)


def parse_7timer(data):
    """Само часовете init + timepoint (на всеки 3 часа). init е в UTC, затова заявката е с
    tzshift=0; към местно време се минава чак на изхода. Междинните часове остават без 7Timer."""
    init = datetime.strptime(str(data["init"]), "%Y%m%d%H").replace(tzinfo=UTC)
    out = {}
    for s in data["dataseries"]:
        dt = init + timedelta(hours=int(s["timepoint"]))
        weather = s.get("weather", "")
        wind = s.get("wind10m") or {}
        out[dt] = rec(
            num(s.get("temp2m")), None, None, num(CLOUD_7T.get(s.get("cloudcover"))),
            thunder="ts" in weather, snow=(s.get("prec_type") == "snow" or "snow" in weather),
            wind_kmh=WIND_7T_KMH.get(wind.get("speed")))
    return out


def source_fn(name):
    """Име от конфигурацията → функция, която връща {utc_час: запис}."""
    if name.startswith("open-meteo:"):
        model = name.split(":", 1)[1]
        return lambda cfg, f, s: fetch_open_meteo(cfg, model, f, s)
    return {"met-norway": fetch_met_norway, "7timer": fetch_7timer}.get(name)


def collect(cfg, fetcher, sleep, log):
    """Пуска всички източници. Паднал източник се записва и агентът продължава."""
    ok, failed = {}, []
    for name in cfg.get("sources") or DEFAULT_SOURCES:
        fn = source_fn(name)
        try:
            if fn is None:
                raise SourceError("непознат източник")
            data = fn(cfg, fetcher, sleep)
            if not data:
                raise SourceError("празен отговор")
            ok[name] = data
            log(f"OK   {name}: {len(data)} часа")
        except SourceError as e:
            failed.append(name)
            log(f"ПАДНА {name}: {e}")
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            failed.append(name)
            log(f"ПАДНА {name}: неочакван формат ({e.__class__.__name__}: {e})")
    return ok, failed


# ---------------------------------------------------------------- смятане

def combine_hour(recs):
    """Медиана по полетата, гласуване за гръмотевица/сняг, разминаване по величина.
    Всяка величина — само от източниците, които я дават."""
    out = {}
    for f in FIELDS:
        vals = [r[f] for r in recs if r[f] is not None]
        out[f] = statistics.median(vals) if vals else None
    for key, f in SPREAD_FIELDS.items():
        vals = [r[f] for r in recs if r[f] is not None]
        # при по-малко от два източника разминаването е неизвестно, не нулево
        out[key] = round(max(vals) - min(vals), 1) if len(vals) >= 2 else None
    # гръмотевица/сняг: поне една трета от източниците за този час (минимум един)
    need = max(1, math.ceil(len(recs) / 3))
    out["thunder"] = sum(r["thunder"] for r in recs) >= need
    out["snow"] = sum(r["snow"] for r in recs) >= need
    return out


# кои величини влизат в риска решават праговете: medium.wind_kmh (среден вятър), high.gust_kmh (порив)
RISK_FIELDS = ("precip_pct", "wind_kmh", "gust_kmh", "temp_c", "thunder")


def field_level(r, f, th):
    """До кое ниво (0/1/2) стига една величина в един час; None, ако източникът не я дава."""
    v = r.get(f)
    if v is None:
        return None
    for lvl, level in ((2, th.get("high", {})), (1, th.get("medium", {}))):
        if f == "thunder":
            if level.get("thunder") and v:
                return lvl
        elif f in level and v >= level[f]:
            return lvl
    return 0


def risk_of(recs, th, fields=RISK_FIELDS):
    """0/1/2 = low/medium/high за група часове по праговете от конфигурацията."""
    levels = [field_level(r, f, th) for r in recs for f in fields]
    return max((x for x in levels if x is not None), default=0)


def gives(recs, f):
    return any(r.get(f) is not None for r in recs)


def day_agreement(level, merged, per_source, th):
    """Колко източника сами стигат ПОНЕ до риска на деня (за нисък ден — колко казват „нисък“).
    Броим само източниците, които реално дават величината, определила риска:
    ако денят е „висок“ заради вероятност за валеж, MET и 7Timer не гласуват.
    Връща (съгласни, допуснати до гласуване)."""
    if level:
        drivers = tuple(f for f in RISK_FIELDS if risk_of(merged, th, (f,)) == level)
    else:
        drivers = RISK_FIELDS
    agree = eligible = 0
    for recs in per_source:
        has = tuple(f for f in drivers if gives(recs, f))
        if not recs or not has:
            continue
        eligible += 1
        own = risk_of(recs, th, has)
        agree += own >= level if level else own == 0
    return agree, eligible


def confidence_of(agree, eligible):
    """Доколко да вярваме на дневния риск. Риск от един източник не се ескалира —
    остава по стойността си, но е с ниска увереност и не влиза в summary."""
    if agree <= 1:
        return "low"
    if agree >= 3 and agree >= 0.6 * eligible:
        return "high"
    return "medium"


def scene_of(recs, th):
    """Сцена за прозореца на проявата — по приоритет: буря, сняг, дъжд, жега, облаци, ясно."""
    med = th.get("medium", {})
    high = th.get("high", {})
    if any(r["thunder"] for r in recs) or any(
            r["gust_kmh"] is not None and r["gust_kmh"] >= high.get("gust_kmh", 1e9) for r in recs):
        return "storm"
    wet = [r for r in recs if r["precip_pct"] is not None and r["precip_pct"] >= med.get("precip_pct", 40)]
    if wet and any(r["snow"] for r in wet):
        return "snow"
    if wet:
        return "rain"
    if any(r["temp_c"] is not None and r["temp_c"] >= med.get("temp_c", 33) for r in recs):
        return "heat"
    clouds = [r["cloud_pct"] for r in recs if r["cloud_pct"] is not None]
    if clouds and statistics.mean(clouds) >= 60:
        return "clouds"
    return "clear"


def local_iso(dt, tz):
    return dt.astimezone(tz).isoformat(timespec="minutes")


def build_forecast(cfg, fetcher=http_get, sleep=time.sleep, now=None, log=None):
    """Цялото изчисление; връща речник точно по schema/forecast.schema.md."""
    log = log or (lambda m: print(m, file=sys.stderr))
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    now = (now or datetime.now(UTC)).astimezone(UTC)
    th = cfg.get("thresholds", {})

    ok, failed = collect(cfg, fetcher, sleep, log)

    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(days=FORECAST_DAYS)
    all_hours = sorted({dt for s in ok.values() for dt in s if start <= dt < end})
    combined = {dt: combine_hour([s[dt] for s in ok.values() if dt in s]) for dt in all_hours}

    hours = [{
        "t": local_iso(dt, tz),
        "temp_c": None if r["temp_c"] is None else round(r["temp_c"], 1),
        "precip_pct": None if r["precip_pct"] is None else round(r["precip_pct"]),
        "wind_kmh": None if r["wind_kmh"] is None else round(r["wind_kmh"]),
        "gust_kmh": None if r["gust_kmh"] is None else round(r["gust_kmh"]),
        "cloud_pct": None if r["cloud_pct"] is None else round(r["cloud_pct"]),
        "thunder": r["thunder"],
        "spread_temp": r["spread_temp"],
        "spread_precip": r["spread_precip"],
        "spread_wind": r["spread_wind"],
    } for dt, r in combined.items()]

    # дни по местно време; agreement = колко източника сами стигат до същия риск
    by_day = {}
    for dt in all_hours:
        by_day.setdefault(dt.astimezone(tz).date(), []).append(dt)
    days, voters = [], []
    for d, dts in sorted(by_day.items()):
        merged = [combined[dt] for dt in dts]
        level = risk_of(merged, th)
        per_source = [[s[dt] for dt in dts if dt in s] for s in ok.values()]
        agree, eligible = day_agreement(level, merged, per_source, th)
        days.append({"date": d.isoformat(), "risk": RISK_LEVELS[level], "agreement": agree,
                     "confidence": confidence_of(agree, eligible)})
        voters.append(eligible)

    win = cfg.get("event_window", {})
    before, after = win.get("before_h", 1), win.get("after_h", 3)
    events = []
    for ev in cfg.get("events", []):
        t0 = datetime.fromisoformat(f"{ev['date']}T{ev.get('start', '00:00')}").replace(tzinfo=tz)
        w_start = (t0 - timedelta(hours=before)).astimezone(UTC).replace(minute=0)
        w_end = t0.astimezone(UTC) + timedelta(hours=after)
        if w_end <= now:
            continue  # отминала проява
        recs = [combined[dt] for dt in all_hours if w_start <= dt < w_end]
        events.append({
            "title": ev.get("title", ""),
            "start": local_iso(t0, tz),
            # извън хоризонта на прогнозата → null, сайтът показва „още няма прогноза“
            "risk": RISK_LEVELS[risk_of(recs, th)] if recs else None,
            "scene": scene_of(recs, th) if recs else None,
        })
    events.sort(key=lambda e: e["start"])

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.astimezone(tz).isoformat(timespec="seconds"),
        "city": cfg.get("city", ""),
        "lat": cfg.get("lat"),
        "lon": cfg.get("lon"),
        "sources_ok": list(ok),
        "sources_failed": failed,
        "hours": hours,
        "days": days,
        "events": events,
        "summary": summarize(cfg, days, voters, events, list(ok), failed),
    }


# ---------------------------------------------------------------- текст по правила

RISK_BG = {"low": "нисък", "medium": "среден", "high": "висок"}
SCENE_BG = {"clear": "ясно", "clouds": "облачно", "rain": "дъжд", "storm": "буря",
            "heat": "жега", "snow": "сняг"}


def ddmm(iso_date):
    return f"{iso_date[8:10]}.{iso_date[5:7]}"


def summarize(cfg, days, voters, events, ok, failed):
    """Едно до три изречения, сглобени по правила — без езиков модел."""
    place = ", ".join(x for x in (cfg.get("city"), cfg.get("venue")) if x)
    if not ok:
        return (f"{place}: няма данни от нито един източник "
                f"— сайтът ползва резервната прогноза.")
    parts = []
    if events:
        e = events[0]
        when = f"{ddmm(e['start'][:10])} от {e['start'][11:16]}"
        if e["risk"] is None:
            parts.append(f"Следваща проява: „{e['title']}“ на {when} — още извън хоризонта на прогнозата.")
        else:
            parts.append(f"Следваща проява: „{e['title']}“ на {when} — риск {RISK_BG[e['risk']]}, "
                         f"{SCENE_BG[e['scene']]}.")
    # само рисковите дни, на които може да се вярва (увереност поне medium)
    risky = [(d, n) for d, n in zip(days, voters)
             if d["risk"] != "low" and d["confidence"] != "low"]
    if risky:
        parts.append(f"{place}: внимание — " + ", ".join(
            f"{ddmm(d['date'])} ({RISK_BG[d['risk']]}, {d['agreement']}/{n} източника)"
            for d, n in risky) + ".")
    else:
        unsure = any(d["risk"] != "low" for d in days)  # има риск, но само от един източник
        parts.append(f"{place}: без {'потвърдени ' if unsure else ''}рискови дни "
                     f"в следващите {len(days)} дни.")
    if failed:
        parts.append("Без данни от: " + ", ".join(failed) + ".")
    return " ".join(parts)


# ---------------------------------------------------------------- вход/изход

def load_config(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(obj, path):
    """Пише атомарно — сайтът никога не чете наполовина записан файл."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


DEBUG_COLS = ("temp_c", "precip_pct", "wind_kmh", "gust_kmh", "cloud_pct", "thunder")


def parse_local_hour(text, tz):
    """„2026-09-30T14“ или „2026-09-30T14:00“ (местно време) → час в UTC."""
    for fmt in ("%Y-%m-%dT%H", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            pass
    raise ValueError(f"непознат формат на час: {text!r} (очаква се 2026-09-30T14)")


def debug_hour(cfg, ok, failed, dt):
    """Таблица за един час: стойностите на всеки източник поотделно, после медианата
    и разминаването. Източник без собствена стойност за часа не участва."""
    tz = ZoneInfo(cfg.get("timezone", "UTC"))

    def cell(v):
        if v is None:
            return "—"
        if isinstance(v, bool):
            return "да" if v else "не"
        return f"{v:.1f}"

    w = max([len(n) for n in list(ok) + failed] + [len("медиана")])
    lines = [f"Час {local_iso(dt, tz)} ({dt.strftime('%H:%M')} UTC) — {cfg.get('city', '')}",
             " " * w + "".join(f"{c:>12}" for c in DEBUG_COLS)]
    present = []
    for name, data in ok.items():
        r = data.get(dt)
        if r is None:
            lines.append(f"{name:<{w}}  няма собствена стойност за този час — не участва")
        else:
            present.append(r)
            lines.append(f"{name:<{w}}" + "".join(f"{cell(r[c]):>12}" for c in DEBUG_COLS))
    for name in failed:
        lines.append(f"{name:<{w}}  паднал източник")
    if not present:
        lines.append("Нито един източник няма стойност за този час.")
        return "\n".join(lines)
    m = combine_hour(present)
    lines.append(f"{'медиана':<{w}}" + "".join(f"{cell(m[c]):>12}" for c in DEBUG_COLS))
    lines.append(f"участват {len(present)} от {len(ok)} · " + " · ".join(
        f"{k} {cell(m[k])}" for k in SPREAD_FIELDS) +
        f" · риск за часа {RISK_LEVELS[risk_of([m], cfg.get('thresholds', {}))]}")
    return "\n".join(lines)


def main(argv=None, fetcher=http_get, sleep=time.sleep, now=None):
    ap = argparse.ArgumentParser(description="Живо небе: прогноза от няколко източника → forecast.json")
    ap.add_argument("config", nargs="?", default=DEFAULT_CONFIG, help="конфигурация на град (JSON)")
    ap.add_argument("--out", help="къде да се запише forecast.json (по подразбиране: `output` от конфигурацията)")
    ap.add_argument("--debug-hour", metavar="ГГГГ-ММ-ДДTЧЧ",
                    help="само печата стойностите на всеки източник за този местен час; не пише файл")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.debug_hour:
        tz = ZoneInfo(cfg.get("timezone", "UTC"))
        try:
            dt = parse_local_hour(args.debug_hour, tz)
        except ValueError as e:
            ap.error(str(e))
        ok, failed = collect(cfg, fetcher, sleep, lambda m: print(m, file=sys.stderr))
        print(debug_hour(cfg, ok, failed, dt))
        return 0 if ok else 1
    out = args.out or cfg.get("output") or "forecast.json"
    fc = build_forecast(cfg, fetcher=fetcher, sleep=sleep, now=now)
    write_json(fc, out)
    print(f"OK -> {out} | източници: {len(fc['sources_ok'])} работят, "
          f"{len(fc['sources_failed'])} паднали | часове: {len(fc['hours'])}", file=sys.stderr)
    # 1 = нито един източник; файлът пак е записан, за да го види сайтът
    return 0 if fc["sources_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
