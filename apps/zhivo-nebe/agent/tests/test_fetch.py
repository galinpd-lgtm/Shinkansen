# -*- coding: utf-8 -*-
"""Тестове на агента без мрежа: отговорите на източниците са записани в fixtures/.

Пускане (от apps/zhivo-nebe):  python3 -m unittest discover -s agent/tests -v
"""
import io
import json
import os
import socket
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import fetch  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
# 06:00 местно време във Варна в деня на примерната проява
NOW = datetime(2026, 6, 20, 3, 0, tzinfo=timezone.utc)

CONFIG = {
    "city": "Варна",
    "venue": "Летен театър",
    "lat": 43.2141,
    "lon": 27.9147,
    "timezone": "Europe/Sofia",
    "event_window": {"before_h": 1, "after_h": 3},
    "thresholds": {
        "high": {"precip_pct": 70, "gust_kmh": 50, "temp_c": 35, "thunder": True},
        "medium": {"precip_pct": 40, "wind_kmh": 35, "temp_c": 33},
    },
    "sources": fetch.DEFAULT_SOURCES,
    "events": [
        {"date": "2026-06-21", "start": "17:00", "title": "Следобедна проява"},
        {"date": "2026-06-20", "start": "20:30", "title": "Вечерна проява"},
        {"date": "2026-06-10", "start": "20:30", "title": "Отминала проява"},
        {"date": "2026-07-30", "start": "20:30", "title": "Далечна проява"},
    ],
}


def read_fixture(name):
    with open(os.path.join(FIX, name), "rb") as fh:
        return fh.read()


def source_of(url):
    """URL → име на източник, както е в конфигурацията."""
    if "open-meteo.com" in url:
        for m in ("icon_seamless", "gfs_seamless", "ecmwf_ifs025"):
            if f"models={m}" in url:
                return f"open-meteo:{m}"
    if "api.met.no" in url:
        return "met-norway"
    if "7timer.info" in url:
        return "7timer"
    raise AssertionError(f"неочакван URL: {url}")


FIXTURES = {
    "open-meteo:icon_seamless": "open_meteo_icon_seamless.json",
    "open-meteo:gfs_seamless": "open_meteo_gfs_seamless.json",
    "open-meteo:ecmwf_ifs025": "open_meteo_ecmwf_ifs025.json",
    "met-norway": "met_norway.json",
    "7timer": "7timer_civil.json",
}


class FakeNet:
    """Подменя мрежата. `broken` казва как пада даден източник: ексепшън или сурови байтове."""

    def __init__(self, broken=None):
        self.broken = broken or {}
        self.calls = {}
        self.sleeps = []

    def __call__(self, url):
        name = source_of(url)
        self.calls[name] = self.calls.get(name, 0) + 1
        if name in self.broken:
            how = self.broken[name]
            if isinstance(how, bytes):
                return how
            raise how()
        return read_fixture(FIXTURES[name])

    def sleep(self, s):
        self.sleeps.append(s)


def http_503():
    return urllib.error.HTTPError("https://x", 503, "Service Unavailable", {}, io.BytesIO(b""))


def http_404():
    return urllib.error.HTTPError("https://x", 404, "Not Found", {}, io.BytesIO(b""))


def build(net):
    return fetch.build_forecast(CONFIG, fetcher=net, sleep=net.sleep, now=NOW, log=lambda m: None)


class SchemaMixin:
    def assert_schema(self, fc):
        self.assertEqual(set(fc), {"schema_version", "generated_at", "city", "lat", "lon",
                                   "sources_ok", "sources_failed", "hours", "days", "events", "summary"})
        self.assertEqual(fc["schema_version"], "2")
        self.assertEqual(fc["city"], "Варна")
        datetime.fromisoformat(fc["generated_at"])
        for h in fc["hours"]:
            self.assertEqual(set(h), {"t", "temp_c", "precip_pct", "wind_kmh", "gust_kmh", "cloud_pct",
                                      "thunder", "spread_temp", "spread_precip", "spread_wind"})
            self.assertIsInstance(h["thunder"], bool)
        for d in fc["days"]:
            self.assertEqual(set(d), {"date", "risk", "agreement", "confidence"})
            self.assertIn(d["risk"], ("low", "medium", "high"))
            self.assertIn(d["confidence"], ("low", "medium", "high"))
        for e in fc["events"]:
            self.assertEqual(set(e), {"title", "start", "risk", "scene"})
            self.assertIn(e["risk"], ("low", "medium", "high", None))
            self.assertIn(e["scene"], ("clear", "clouds", "rain", "storm", "heat", "snow", None))
        self.assertTrue(fc["summary"])
        json.dumps(fc)  # сериализира се без грешка


class NormalCase(SchemaMixin, unittest.TestCase):
    def setUp(self):
        self.net = FakeNet()
        self.fc = build(self.net)

    def test_schema(self):
        self.assert_schema(self.fc)

    def test_all_sources_ok(self):
        self.assertEqual(self.fc["sources_ok"], fetch.DEFAULT_SOURCES)
        self.assertEqual(self.fc["sources_failed"], [])
        self.assertEqual(self.net.sleeps, [])

    def test_hours_start_now_local(self):
        self.assertEqual(self.fc["hours"][0]["t"], "2026-06-20T06:00+03:00")

    def test_median_and_spread(self):
        h = {x["t"]: x for x in self.fc["hours"]}
        storm = h["2026-06-20T21:00+03:00"]
        self.assertTrue(storm["thunder"])
        self.assertGreaterEqual(storm["precip_pct"], 70)
        self.assertGreaterEqual(storm["gust_kmh"], 50)
        self.assertGreater(storm["spread_temp"], 0)
        self.assertEqual(storm["spread_precip"], 0)   # icon и gfs са съгласни, ECMWF е null
        self.assertIsNotNone(storm["spread_wind"])
        # в края остава само 7Timer — разминаването е неизвестно
        last = self.fc["hours"][-1]
        self.assertEqual((last["spread_temp"], last["spread_precip"], last["spread_wind"]), (None, None, None))

    def test_days(self):
        d = {x["date"]: x for x in self.fc["days"]}
        self.assertEqual(d["2026-06-20"]["risk"], "high")
        self.assertEqual(d["2026-06-20"]["agreement"], 5)
        self.assertEqual(d["2026-06-21"]["risk"], "medium")
        self.assertEqual(d["2026-06-21"]["agreement"], 4)  # 7Timer не вижда жегата
        self.assertEqual(d["2026-06-20"]["confidence"], "high")
        self.assertEqual(d["2026-06-21"]["confidence"], "high")

    def test_events(self):
        ev = {e["title"]: e for e in self.fc["events"]}
        self.assertNotIn("Отминала проява", ev)
        self.assertEqual(ev["Вечерна проява"]["start"], "2026-06-20T20:30+03:00")
        self.assertEqual((ev["Вечерна проява"]["risk"], ev["Вечерна проява"]["scene"]), ("high", "storm"))
        self.assertEqual((ev["Следобедна проява"]["risk"], ev["Следобедна проява"]["scene"]), ("medium", "heat"))
        self.assertEqual((ev["Далечна проява"]["risk"], ev["Далечна проява"]["scene"]), (None, None))
        self.assertEqual(self.fc["events"][0]["title"], "Вечерна проява")  # подредени по време

    def test_summary(self):
        s = self.fc["summary"]
        self.assertIn("Вечерна проява", s)
        self.assertIn("висок", s)
        self.assertNotIn("Без данни от", s)


class RealSamples(unittest.TestCase):
    """Откъси от истински отговори за Варна (25.09.2026)."""

    def test_met_norway_sample(self):
        data = {"properties": {"timeseries": [{"time": "2026-09-25T22:00:00Z", "data": {
            "instant": {"details": {"air_temperature": 15.4, "cloud_area_fraction": 97.7, "wind_speed": 4.1}},
            "next_1_hours": {"summary": {"symbol_code": "partlycloudy_night"},
                             "details": {"precipitation_amount": 0.0}}}}]}}
        out = fetch.parse_met_norway(data)
        (dt, r), = out.items()
        self.assertEqual(dt, datetime(2026, 9, 25, 22, tzinfo=timezone.utc))
        self.assertEqual(r["temp_c"], 15.4)
        self.assertEqual(r["cloud_pct"], 97.7)
        self.assertIsNone(r["precip_pct"])   # няма вероятност за Варна
        self.assertIsNone(r["gust_kmh"])     # средният вятър не е порив
        self.assertFalse(r["thunder"])

    def test_7timer_sample(self):
        data = {"product": "civil", "init": "2026092512", "dataseries": [{
            "timepoint": 3, "cloudcover": 9, "prec_type": "none", "prec_amount": 0, "temp2m": 16,
            "rh2m": "60%", "wind10m": {"direction": "E", "speed": 3}, "weather": "cloudyday"}]}
        out = fetch.parse_7timer(data)
        # init 12 UTC + 3 ч = 15:00 UTC = 18:00 във Варна; без пренасяне към 16 и 17 ч
        self.assertEqual(list(out), [datetime(2026, 9, 25, 15, tzinfo=timezone.utc)])
        self.assertEqual(fetch.local_iso(list(out)[0], ZoneInfo("Europe/Sofia")), "2026-09-25T18:00+03:00")
        r = out[datetime(2026, 9, 25, 15, tzinfo=timezone.utc)]
        self.assertEqual((r["temp_c"], r["cloud_pct"]), (16.0, 97.0))
        self.assertIsNone(r["precip_pct"])
        self.assertIsNone(r["gust_kmh"])
        self.assertFalse(r["thunder"])

    def test_7timer_thunder_by_ts(self):
        data = {"init": "2026092512", "dataseries": [{"timepoint": 3, "cloudcover": 9, "prec_type": "rain",
                                                     "prec_amount": 4, "temp2m": 18, "weather": "tsrainday"}]}
        self.assertTrue(all(r["thunder"] for r in fetch.parse_7timer(data).values()))


class PerQuantitySources(unittest.TestCase):
    """spread и agreement — само върху източниците, които дават величината."""

    TH = CONFIG["thresholds"]

    def test_spread_per_quantity(self):
        recs = [fetch.rec(20, 80, 50, 90, wind_kmh=30), fetch.rec(21, 60, 50, 90, wind_kmh=30),
                fetch.rec(25, None, None, 90, wind_kmh=18), fetch.rec(29, None, None, 90, wind_kmh=None)]
        r = fetch.combine_hour(recs)
        self.assertEqual(r["precip_pct"], 70)
        self.assertEqual(r["spread_temp"], 9.0)      # от четирите източника
        self.assertEqual(r["spread_precip"], 20)     # само от двата, които дават вероятност
        self.assertEqual(r["spread_wind"], 12.0)     # от трите, които дават среден вятър
        one = fetch.combine_hour([fetch.rec(20, 80), fetch.rec(20, None)])
        self.assertEqual(one["spread_temp"], 0.0)
        self.assertIsNone(one["spread_precip"])      # един източник — неизвестно, не 0
        self.assertIsNone(one["spread_wind"])

    def test_agreement_only_among_sources_with_quantity(self):
        # денят е „висок“ само заради вероятност за валеж → гласуват само двата модела на Open-Meteo
        om1 = [fetch.rec(20, 80, 20, 50)]
        om2 = [fetch.rec(20, 30, 20, 50)]
        met = [fetch.rec(20, None, None, 50)]
        timer = [fetch.rec(20, None, None, 50)]
        merged = [fetch.combine_hour([om1[0], om2[0], met[0], timer[0]])]
        merged[0]["precip_pct"] = 80
        level = fetch.risk_of(merged, self.TH)
        self.assertEqual(level, 2)
        self.assertEqual(fetch.day_agreement(level, merged, [om1, om2, met, timer], self.TH), (1, 2))

    def test_low_day_everyone_votes(self):
        per = [[fetch.rec(20, 5, 20, 30)], [fetch.rec(21, None, None, 30)]]
        merged = [fetch.combine_hour([p[0] for p in per])]
        self.assertEqual(fetch.day_agreement(0, merged, per, self.TH), (2, 2))

    def test_normal_case_quantities(self):
        net = FakeNet()
        fc = build(net)
        h = {x["t"]: x for x in fc["hours"]}
        # MET 17:00Z → 20:00 местно; валеж и пориви само от icon/gfs → няма разминаване по тях
        storm = h["2026-06-20T20:00+03:00"]
        self.assertEqual(storm["precip_pct"], 80)
        self.assertEqual(storm["gust_kmh"], 58)
        self.assertIn("5/5", fc["summary"])  # гръмотевицата я дават всички
        self.assertIn("4/5", fc["summary"])  # жегата: 7Timer не е съгласен


def load_example_thresholds():
    with open(os.path.join(fetch.APP_DIR, "config", "city.example.json"), encoding="utf-8") as fh:
        return json.load(fh)["thresholds"]


class WindVsGust(unittest.TestCase):
    """Точка 1: средният риск е по среден вятър, високият — по пориви."""

    TH = load_example_thresholds()

    def test_example_config_splits_wind_and_gust(self):
        self.assertEqual(self.TH["medium"].get("wind_kmh"), 35)
        self.assertNotIn("gust_kmh", self.TH["medium"])
        self.assertEqual(self.TH["high"].get("gust_kmh"), 50)

    def test_gusts_alone_do_not_make_medium(self):
        # обикновен ветровит ден: пориви 45, среден вятър 20 → нисък риск (преди излизаше среден)
        self.assertEqual(fetch.risk_of([fetch.rec(22, 10, 45, 40, wind_kmh=20)], self.TH), 0)

    def test_mean_wind_medium_and_gust_high(self):
        self.assertEqual(fetch.risk_of([fetch.rec(22, 10, 45, 40, wind_kmh=36)], self.TH), 1)
        self.assertEqual(fetch.risk_of([fetch.rec(22, 10, 52, 40, wind_kmh=20)], self.TH), 2)

    def test_wind_from_all_sources(self):
        om = fetch.parse_open_meteo(json.loads(read_fixture("open_meteo_icon_seamless.json")), "icon_seamless")
        met = fetch.parse_met_norway(json.loads(read_fixture("met_norway.json")))
        timer = fetch.parse_7timer(json.loads(read_fixture("7timer_civil.json")))
        t = datetime(2026, 6, 20, 6, tzinfo=timezone.utc)
        self.assertEqual(om[t]["wind_kmh"], 12.4)
        self.assertAlmostEqual(met[t]["wind_kmh"], 3.1 * 3.6)  # m/s → km/h
        self.assertEqual(timer[t]["wind_kmh"], 20.5)           # клас 3 по скалата на 7Timer
        self.assertIsNone(met[t]["gust_kmh"])

    def test_normal_case_calm_day_is_low(self):
        net = FakeNet()
        fc = build(net)
        self.assertEqual({d["date"]: d["risk"] for d in fc["days"]}["2026-06-22"], "low")
        self.assertTrue(all(h["wind_kmh"] is not None for h in fc["hours"]))


def open_meteo_day(precip):
    """Малък отговор на Open-Meteo: 24 спокойни часа, една и съща вероятност за валеж."""
    times = [f"2026-06-20T{h:02d}:00" for h in range(24)]
    return json.dumps({"hourly": {
        "time": times, "temperature_2m": [22.0] * 24, "precipitation_probability": [precip] * 24,
        "wind_speed_10m": [10.0] * 24, "wind_gusts_10m": [20.0] * 24,
        "cloud_cover": [40] * 24, "weather_code": [2] * 24}}).encode()


class Confidence(unittest.TestCase):
    """Точка 3: риск само от един източник не се ескалира и не влиза в summary."""

    def test_levels(self):
        self.assertEqual(fetch.confidence_of(1, 1), "low")
        self.assertEqual(fetch.confidence_of(1, 5), "low")
        self.assertEqual(fetch.confidence_of(2, 2), "medium")
        self.assertEqual(fetch.confidence_of(3, 5), "high")
        self.assertEqual(fetch.confidence_of(3, 6), "medium")

    def test_single_source_risk_is_low_confidence(self):
        # icon казва 80 %, gfs — 0 %: медианата е 40 → среден риск, но само от icon
        answers = {"icon_seamless": open_meteo_day(80), "gfs_seamless": open_meteo_day(0)}

        def net(url):
            return answers[next(m for m in answers if f"models={m}" in url)]

        cfg = dict(CONFIG, sources=["open-meteo:icon_seamless", "open-meteo:gfs_seamless"], events=[])
        fc = fetch.build_forecast(cfg, fetcher=net, sleep=lambda s: None, now=NOW, log=lambda m: None)
        day = {d["date"]: d for d in fc["days"]}["2026-06-20"]
        self.assertEqual(day["risk"], "medium")        # стойността не се пипа
        self.assertEqual(day["confidence"], "low")
        self.assertEqual(day["agreement"], 1)          # само icon стига поне до „среден“
        self.assertNotIn("20.06", fc["summary"])
        self.assertIn("без потвърдени рискови дни", fc["summary"])

    def test_two_sources_agree_is_mentioned(self):
        answers = {"icon_seamless": open_meteo_day(80), "gfs_seamless": open_meteo_day(75)}

        def net(url):
            return answers[next(m for m in answers if f"models={m}" in url)]

        cfg = dict(CONFIG, sources=["open-meteo:icon_seamless", "open-meteo:gfs_seamless"], events=[])
        fc = fetch.build_forecast(cfg, fetcher=net, sleep=lambda s: None, now=NOW, log=lambda m: None)
        day = {d["date"]: d for d in fc["days"]}["2026-06-20"]
        self.assertEqual((day["risk"], day["confidence"]), ("high", "medium"))
        self.assertIn("20.06 (висок, 2/2 източника)", fc["summary"])


# Случаят от GX10, 30.09, 14:00 местно (11:00 UTC): трите модела на Open-Meteo дават
# 17,6 / 22,6 / 20,9 °C; 7Timer има стойности само на 3 часа, MET на този хоризонт — на 6.
DAY = "2026-09-30"
OM_TEMPS = {"icon_seamless": 17.6, "gfs_seamless": 22.6, "ecmwf_ifs025": 20.9}


def om_answer(temp):
    times = [f"{DAY}T{h:02d}:00" for h in range(24)]
    return json.dumps({"hourly": {
        "time": times, "temperature_2m": [temp] * 24, "precipitation_probability": [10] * 24,
        "wind_speed_10m": [10.0] * 24, "wind_gusts_10m": [20.0] * 24,
        "cloud_cover": [40] * 24, "weather_code": [2] * 24}}).encode()


TIMER_ANSWER = json.dumps({"product": "civil", "init": "2026093000", "dataseries": [
    {"timepoint": tp, "cloudcover": 5, "prec_type": "none", "prec_amount": 0, "temp2m": 26,
     "rh2m": "60%", "wind10m": {"direction": "E", "speed": 2}, "weather": "pcloudyday"}
    for tp in (3, 6, 9, 12, 15, 18, 21)]}).encode()

MET_ANSWER = json.dumps({"properties": {"timeseries": [
    {"time": f"{DAY}T{h:02d}:00:00Z", "data": {
        "instant": {"details": {"air_temperature": 14.0, "cloud_area_fraction": 50.0, "wind_speed": 3.0}},
        "next_6_hours": {"summary": {"symbol_code": "cloudy"}, "details": {"precipitation_amount": 0.0}}}}
    for h in (0, 6, 12, 18)]}}).encode()


def sparse_net(url):
    name = source_of(url)
    if name == "7timer":
        return TIMER_ANSWER
    if name == "met-norway":
        return MET_ANSWER
    return om_answer(OM_TEMPS[name.split(":")[1]])


SPARSE_NOW = datetime(2026, 9, 30, 0, tzinfo=timezone.utc)


class SparseSteps(unittest.TestCase):
    """Източник участва само в часовете, за които има собствена стойност."""

    def setUp(self):
        self.fc = fetch.build_forecast(dict(CONFIG, events=[]), fetcher=sparse_net, sleep=lambda s: None,
                                       now=SPARSE_NOW, log=lambda m: None)
        self.h = {x["t"]: x for x in self.fc["hours"]}

    def test_hour_without_3h_source(self):
        # 14:00 местно = 11 UTC: нито 7Timer (9 и 12 UTC), нито MET (6 и 12 UTC) имат стойност
        h = self.h[f"{DAY}T14:00+03:00"]
        self.assertEqual(h["spread_temp"], 5.0)
        self.assertEqual(h["temp_c"], 20.9)

    def test_hour_with_3h_source(self):
        # 15:00 местно = 12 UTC: участват и 7Timer (26), и MET (14)
        h = self.h[f"{DAY}T15:00+03:00"]
        self.assertEqual(h["spread_temp"], 12.0)
        # 12:00 местно = 9 UTC: 7Timer да, MET не
        self.assertEqual(self.h[f"{DAY}T12:00+03:00"]["spread_temp"], 8.4)

    def test_7timer_hours_are_utc(self):
        timer = fetch.parse_7timer(json.loads(TIMER_ANSWER))
        local = [fetch.local_iso(dt, ZoneInfo("Europe/Sofia"))[11:16] for dt in timer]
        self.assertEqual(local, ["06:00", "09:00", "12:00", "15:00", "18:00", "21:00", "00:00"])


class DebugHour(unittest.TestCase):
    def run_debug(self, hour):
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "forecast.json")
            with redirect_stdout(out), redirect_stderr(err):
                code = fetch.main(["--debug-hour", hour, "--out", target], fetcher=sparse_net,
                                  sleep=lambda s: None, now=SPARSE_NOW)
            self.assertFalse(os.path.exists(target))  # режимът само печата
        return code, out.getvalue()

    def test_prints_each_source(self):
        code, text = self.run_debug("2026-09-30T14")
        self.assertEqual(code, 0)
        self.assertIn("2026-09-30T14:00+03:00 (11:00 UTC)", text)
        for v in ("17.6", "22.6", "20.9"):
            self.assertIn(v, text)
        lines = {ln.split()[0]: ln for ln in text.splitlines() if ln.strip()}
        self.assertIn("не участва", lines["7timer"])
        self.assertIn("не участва", lines["met-norway"])
        self.assertIn("участват 3 от 5", text)
        self.assertIn("spread_temp 5.0", text)

    def test_hour_with_all_sources(self):
        _, text = self.run_debug("2026-09-30T15:00")
        self.assertIn("участват 5 от 5", text)
        self.assertIn("26.0", text)
        self.assertIn("spread_temp 12.0", text)

    def test_bad_hour(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fetch.main(["--debug-hour", "30.09 14ч"], fetcher=sparse_net, sleep=lambda s: None)


class OneSourceDown(SchemaMixin, unittest.TestCase):
    def test_503_retries_then_continues(self):
        net = FakeNet(broken={"met-norway": http_503})
        fc = build(net)
        self.assert_schema(fc)
        self.assertEqual(fc["sources_failed"], ["met-norway"])
        self.assertEqual(len(fc["sources_ok"]), 4)
        self.assertEqual(net.calls["met-norway"], fetch.ATTEMPTS)
        self.assertEqual(net.sleeps, [2.0, 4.0])
        self.assertIn("met-norway", fc["summary"])
        ev = {e["title"]: e for e in fc["events"]}
        self.assertEqual(ev["Вечерна проява"]["scene"], "storm")

    def test_timeout(self):
        net = FakeNet(broken={"7timer": socket.timeout})
        fc = build(net)
        self.assertEqual(fc["sources_failed"], ["7timer"])
        self.assertEqual(net.calls["7timer"], fetch.ATTEMPTS)
        # без 7Timer всички останали виждат жегата на 21-ви
        d = {x["date"]: x for x in fc["days"]}
        self.assertEqual(d["2026-06-21"]["agreement"], 4)

    def test_bad_json(self):
        net = FakeNet(broken={"met-norway": read_fixture("met_norway_broken.txt")})
        fc = build(net)
        self.assertEqual(fc["sources_failed"], ["met-norway"])
        self.assertEqual(net.calls["met-norway"], fetch.ATTEMPTS)

    def test_404_is_not_retried(self):
        net = FakeNet(broken={"open-meteo:ecmwf_ifs025": http_404})
        fc = build(net)
        self.assertEqual(fc["sources_failed"], ["open-meteo:ecmwf_ifs025"])
        self.assertEqual(net.calls["open-meteo:ecmwf_ifs025"], 1)

    def test_valid_json_wrong_shape(self):
        net = FakeNet(broken={"7timer": b'{"product": "civil"}'})
        fc = build(net)
        self.assertEqual(fc["sources_failed"], ["7timer"])


class AllSourcesDown(SchemaMixin, unittest.TestCase):
    def setUp(self):
        self.net = FakeNet(broken={n: http_503 for n in FIXTURES})

    def test_forecast_still_valid(self):
        fc = build(self.net)
        self.assert_schema(fc)
        self.assertEqual(fc["sources_ok"], [])
        self.assertEqual(fc["sources_failed"], fetch.DEFAULT_SOURCES)
        self.assertEqual(fc["hours"], [])
        self.assertEqual(fc["days"], [])
        self.assertTrue(all(e["risk"] is None and e["scene"] is None for e in fc["events"]))
        self.assertIn("няма данни", fc["summary"])

    def test_main_writes_file_and_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "city.json")
            out = os.path.join(d, "out", "forecast.json")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump(CONFIG, fh, ensure_ascii=False)
            code = fetch.main([cfg_path, "--out", out], fetcher=self.net, sleep=self.net.sleep, now=NOW)
            self.assertEqual(code, 1)
            with open(out, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["sources_ok"], [])


class MainNormal(unittest.TestCase):
    def test_main_with_example_config(self):
        net = FakeNet()
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "forecast.json")
            code = fetch.main(["--out", out], fetcher=net, sleep=net.sleep, now=NOW)
            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as fh:
                fc = json.load(fh)
            self.assertEqual(fc["city"], "Варна")
            self.assertEqual(fc["events"][0]["scene"], "storm")


if __name__ == "__main__":
    unittest.main()
