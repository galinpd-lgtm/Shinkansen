#!/usr/bin/env python3
"""weather-now — „вали ли сега“: текущото време от няколко безплатни източника + METAR.

    weather_now.py --lat 43.2 --lon 27.9 [--icao XXXX] [--json]

Източници (без ключове):
  open-meteo  — current (температура, валеж, код на времето)
  met-no      — MET Norway locationforecast: моментни стойности + следващия час
  metar       — aviationweather.gov: последният METAR на летището по ICAO код

Изход: кратък текст (по подразбиране) или JSON (--json). Само чете.
"""
import argparse
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "shinkansen-weather-now/1.0 (+https://github.com/galinpd-lgtm/Shinkansen)"
TIMEOUT = 10

# Кодове на времето по WMO (Open-Meteo) → вид валеж
WMO_PRECIP = {
    51: "drizzle", 53: "drizzle", 55: "drizzle", 56: "drizzle", 57: "drizzle",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow",
    80: "rain", 81: "rain", 82: "rain", 85: "snow", 86: "snow",
    95: "thunder", 96: "thunder", 99: "thunder",
}

# Явления в METAR, които значат валеж на летището (VC = наблизо, не на самото летище)
METAR_PRECIP = {"DZ": "drizzle", "RA": "rain", "SN": "snow", "SG": "snow", "PL": "rain",
                "GR": "hail", "GS": "hail", "UP": "rain", "IC": "snow"}


def write_summary(text):
    """Кратко обобщение за дневника на диспечера — без входни данни."""
    path = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


# ─────────────────────────── разбор (чисти функции) ───────────────────────────

def parse_open_meteo(data):
    cur = data.get("current") or {}
    code = cur.get("weather_code")
    precip = cur.get("precipitation")
    kind = WMO_PRECIP.get(code)
    raining = bool(kind) or bool(precip and precip > 0)
    return {"source": "open-meteo", "raining": raining, "kind": kind or ("rain" if raining else None),
            "precip_mm": precip, "temp_c": cur.get("temperature_2m"),
            "wind_kmh": cur.get("wind_speed_10m"), "time": cur.get("time")}


def parse_met_no(data):
    ts = ((data.get("properties") or {}).get("timeseries") or [])
    if not ts:
        raise ValueError("празен timeseries")
    first = ts[0]
    d = first.get("data") or {}
    inst = (d.get("instant") or {}).get("details") or {}
    nxt = d.get("next_1_hours") or {}
    sym = (nxt.get("summary") or {}).get("symbol_code", "") or ""
    amount = (nxt.get("details") or {}).get("precipitation_amount")
    kind = None
    for word, k in (("thunder", "thunder"), ("sleet", "snow"), ("snow", "snow"),
                    ("drizzle", "drizzle"), ("rain", "rain")):
        if word in sym:
            kind = k
            break
    raining = bool(kind) or bool(amount and amount > 0)
    wind = inst.get("wind_speed")
    return {"source": "met-no", "raining": raining, "kind": kind or ("rain" if raining else None),
            "precip_mm": amount, "temp_c": inst.get("air_temperature"),
            "wind_kmh": round(wind * 3.6, 1) if wind is not None else None,
            "time": first.get("time"), "symbol": sym or None}


def parse_metar_weather(raw):
    """Валежни явления от суров METAR. → (вали ли на летището, вид, гръмотевица, наблизо)."""
    body = re.split(r"\s(?:TEMPO|BECMG|NOSIG|RMK)\b", " " + raw)[0]
    raining, kind, thunder, vicinity = False, None, False, False
    for tok in body.split():
        m = re.match(r"^([+-]|VC)?(MI|PR|BC|DR|BL|SH|TS|FZ)*((?:DZ|RA|SN|SG|PL|GR|GS|UP|IC)+)?$", tok)
        if not m or tok in ("", "-", "+"):
            continue
        if "TS" in tok:
            thunder = True
        if not m.group(3):
            if m.group(1) == "VC":          # VCSH, VCTS — нещо наблизо, не на летището
                vicinity = True
            continue
        if m.group(1) == "VC":
            vicinity = True
            continue
        raining = True
        kind = kind or METAR_PRECIP.get(m.group(3)[:2])
    if thunder and raining:
        kind = "thunder"
    return raining, kind, thunder, vicinity


def parse_metar(data):
    if not data:
        raise ValueError("няма METAR за това летище")
    m = data[0] if isinstance(data, list) else data
    raw = m.get("rawOb") or ""
    raining, kind, thunder, vicinity = parse_metar_weather(raw)
    wspd = m.get("wspd")
    return {"source": "metar", "raining": raining, "kind": kind, "thunder": thunder,
            "vicinity": vicinity, "temp_c": m.get("temp"),
            "wind_kmh": round(wspd * 1.852, 1) if isinstance(wspd, (int, float)) else None,
            "station": m.get("icaoId"), "raw": raw, "time": m.get("reportTime")}


def verdict(results):
    """Общ отговор от успешните източници."""
    ok = [r for r in results if "error" not in r]
    if not ok:
        return {"raining": None, "agree": None, "text": "няма данни — всички източници паднаха"}
    yes = [r["source"] for r in ok if r["raining"]]
    if len(yes) == len(ok):
        text = "вали (%s)" % ", ".join(yes)
    elif yes:
        text = "може би вали: %s — да, %s — не" % (
            ", ".join(yes), ", ".join(r["source"] for r in ok if not r["raining"]))
    else:
        text = "не вали"
        if any(r.get("vicinity") for r in ok):
            text += " (METAR: валеж наблизо)"
    # мнозинство; при равенство — неясно (None)
    raining = True if len(yes) * 2 > len(ok) else (None if len(yes) * 2 == len(ok) else False)
    return {"raining": raining, "agree": len(yes) in (0, len(ok)),
            "yes": len(yes), "of": len(ok), "text": text}


# ─────────────────────────── теглене ───────────────────────────

def fetch_all(lat, lon, icao=None, get=http_get_json):
    jobs = [
        ("open-meteo", "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
            "latitude": lat, "longitude": lon, "timezone": "auto",
            "current": "temperature_2m,precipitation,weather_code,wind_speed_10m"}), parse_open_meteo),
        ("met-no", "https://api.met.no/weatherapi/locationforecast/2.0/compact?" + urllib.parse.urlencode({
            "lat": round(lat, 4), "lon": round(lon, 4)}), parse_met_no),
    ]
    if icao:
        jobs.append(("metar", "https://aviationweather.gov/api/data/metar?" + urllib.parse.urlencode({
            "ids": icao.upper(), "format": "json"}), parse_metar))
    out = []
    for name, url, parse in jobs:
        try:
            out.append(parse(get(url)))
        except urllib.error.HTTPError as e:
            out.append({"source": name, "error": "HTTP %d" % e.code})
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            out.append({"source": name, "error": "мрежа: %s" % getattr(e, "reason", e)})
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
            out.append({"source": name, "error": "лош отговор: %s" % e})
    return out


def text_report(results, v):
    lines = ["Вали ли сега: " + v["text"]]
    for r in results:
        if "error" in r:
            lines.append("  %-10s грешка: %s" % (r["source"], r["error"]))
            continue
        bits = ["вали" if r["raining"] else "сухо"]
        if r.get("kind") and r["raining"]:
            bits[0] += " (%s)" % r["kind"]
        if r.get("temp_c") is not None:
            bits.append("%.1f °C" % r["temp_c"])
        if r.get("precip_mm") is not None:
            bits.append("%.1f mm" % r["precip_mm"])
        if r.get("wind_kmh") is not None:
            bits.append("вятър %.0f km/h" % r["wind_kmh"])
        lines.append("  %-10s %s" % (r["source"], " · ".join(bits)))
        if r.get("raw"):
            lines.append("             " + r["raw"])
    return "\n".join(lines)


def main(argv=None, get=http_get_json):
    ap = argparse.ArgumentParser(description="Вали ли сега — няколко източника + METAR.")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--icao", help="ICAO код на най-близкото летище (4 букви)")
    ap.add_argument("--json", action="store_true", help="изход като JSON")
    a = ap.parse_args(argv)
    if not (-90 <= a.lat <= 90 and -180 <= a.lon <= 180):
        ap.error("координатите са извън обхват")
    if a.icao and not re.match(r"^[A-Za-z0-9]{4}$", a.icao):
        ap.error("ICAO кодът е 4 знака")
    results = fetch_all(a.lat, a.lon, a.icao, get=get)
    v = verdict(results)
    if a.json:
        print(json.dumps({"verdict": v, "sources": results}, ensure_ascii=False, indent=2))
    else:
        print(text_report(results, v))
    ok = [r for r in results if "error" not in r]
    state = {True: "вали", False: "сухо", None: "неясно" if ok else "без данни"}[v["raining"]]
    write_summary("%s · %d/%d източника" % (state,
        len(ok), len(results)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
