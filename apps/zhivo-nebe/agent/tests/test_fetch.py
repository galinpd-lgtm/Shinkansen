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
from datetime import datetime, timezone

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
        "medium": {"precip_pct": 40, "gust_kmh": 35, "temp_c": 33},
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
        self.assertEqual(fc["schema_version"], "1")
        self.assertEqual(fc["city"], "Варна")
        datetime.fromisoformat(fc["generated_at"])
        for h in fc["hours"]:
            self.assertEqual(set(h), {"t", "temp_c", "precip_pct", "gust_kmh", "cloud_pct", "thunder", "spread"})
            self.assertIsInstance(h["thunder"], bool)
        for d in fc["days"]:
            self.assertEqual(set(d), {"date", "risk", "agreement"})
            self.assertIn(d["risk"], ("low", "medium", "high"))
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
        self.assertIsNotNone(storm["spread"])
        self.assertTrue(0 <= storm["spread"] <= 1)
        # в края остава само 7Timer — разминаването е неизвестно
        self.assertIsNone(self.fc["hours"][-1]["spread"])

    def test_days(self):
        d = {x["date"]: x for x in self.fc["days"]}
        self.assertEqual(d["2026-06-20"]["risk"], "high")
        self.assertEqual(d["2026-06-20"]["agreement"], 5)
        self.assertEqual(d["2026-06-21"]["risk"], "medium")
        self.assertEqual(d["2026-06-21"]["agreement"], 4)  # 7Timer не вижда жегата

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
        self.assertEqual(sorted(out), [datetime(2026, 9, 25, h, tzinfo=timezone.utc) for h in (15, 16, 17)])
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

    def test_spread_ignores_missing(self):
        recs = [fetch.rec(20, 80, 50, 90), fetch.rec(21, 80, 50, 90),
                fetch.rec(25, None, None, 90), fetch.rec(29, None, None, 90)]
        r = fetch.combine_hour(recs)
        self.assertEqual(r["precip_pct"], 80)
        self.assertEqual(r["spread"], 0.9)  # от температурата; валежът и поривите са съгласни
        only_temp = fetch.combine_hour([fetch.rec(20, 80), fetch.rec(20, None)])
        self.assertEqual(only_temp["spread"], 0.0)

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
