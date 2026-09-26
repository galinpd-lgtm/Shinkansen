"""Тестове без мрежа: разбор на отговорите и общия отговор.

    python3 -m unittest discover -s skills/weather-now/tests -v
"""
import io
import json
import os
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import weather_now as wn  # noqa: E402

OPEN_METEO_RAIN = {"current": {"time": "2026-09-26T10:00", "temperature_2m": 14.2,
                               "precipitation": 1.4, "weather_code": 63, "wind_speed_10m": 18.0}}
OPEN_METEO_DRY = {"current": {"time": "2026-09-26T10:00", "temperature_2m": 21.0,
                              "precipitation": 0.0, "weather_code": 2, "wind_speed_10m": 9.0}}
MET_NO = {"properties": {"timeseries": [{"time": "2026-09-26T10:00:00Z", "data": {
    "instant": {"details": {"air_temperature": 14.0, "wind_speed": 5.0}},
    "next_1_hours": {"summary": {"symbol_code": "lightrainshowers_day"},
                     "details": {"precipitation_amount": 0.6}}}}]}}
METAR = [{"icaoId": "XXXX", "rawOb": "XXXX 261030Z 09012KT 5000 -SHRA BKN020CB 14/12 Q1012",
          "temp": 14, "wspd": 12, "reportTime": "2026-09-26T10:30:00Z"}]


class Metar(unittest.TestCase):
    def w(self, raw):
        return wn.parse_metar_weather(raw)

    def test_rain_kinds(self):
        self.assertEqual(self.w("XXXX 261030Z 09012KT 5000 -SHRA BKN020 14/12 Q1012")[:2], (True, "rain"))
        self.assertEqual(self.w("XXXX 261030Z 00000KT 2000 +TSRA FEW010CB 18/17 Q1008")[:3],
                         (True, "thunder", True))
        self.assertEqual(self.w("XXXX 261030Z 27005KT 3000 -DZ BR OVC004 09/09 Q1020")[:2], (True, "drizzle"))
        self.assertEqual(self.w("XXXX 261030Z 36010KT 1500 SN OVC008 M02/M03 Q1025")[:2], (True, "snow"))
        self.assertEqual(self.w("XXXX 261030Z 36010KT 3000 RASN OVC008 01/00 Q1025")[0], True)

    def test_dry_and_vicinity(self):
        self.assertEqual(self.w("XXXX 261030Z 09005KT CAVOK 21/12 Q1016"), (False, None, False, False))
        r = self.w("XXXX 261030Z 09005KT 9999 VCSH FEW030CB 21/12 Q1016")
        self.assertEqual((r[0], r[3]), (False, True))
        r = self.w("XXXX 261030Z 09005KT 9999 VCTS SCT030CB 21/12 Q1016")
        self.assertEqual((r[0], r[2], r[3]), (False, True, True))

    def test_trend_and_remarks_ignored(self):
        # валежът е само в прогнозата TEMPO и в бележките — сега не вали
        self.assertFalse(self.w("XXXX 261030Z 09005KT 9999 FEW030 21/12 Q1016 TEMPO 4000 SHRA")[0])
        self.assertFalse(self.w("XXXX 261030Z 09005KT 9999 FEW030 21/12 Q1016 RMK RAE05")[0])
        self.assertFalse(self.w("XXXX 261030Z 09005KT 9999 RERA FEW030 21/12 Q1016")[0])   # скорошен дъжд

    def test_parse_metar(self):
        r = wn.parse_metar(METAR)
        self.assertTrue(r["raining"])
        self.assertEqual(r["station"], "XXXX")
        self.assertAlmostEqual(r["wind_kmh"], 22.2)
        with self.assertRaises(ValueError):
            wn.parse_metar([])


class Sources(unittest.TestCase):
    def test_open_meteo(self):
        r = wn.parse_open_meteo(OPEN_METEO_RAIN)
        self.assertEqual((r["raining"], r["kind"], r["precip_mm"]), (True, "rain", 1.4))
        self.assertFalse(wn.parse_open_meteo(OPEN_METEO_DRY)["raining"])

    def test_met_no(self):
        r = wn.parse_met_no(MET_NO)
        self.assertEqual((r["raining"], r["kind"]), (True, "rain"))
        self.assertEqual(r["wind_kmh"], 18.0)
        with self.assertRaises(ValueError):
            wn.parse_met_no({"properties": {"timeseries": []}})


class Verdict(unittest.TestCase):
    def test_majority_tie_and_none(self):
        self.assertIs(wn.verdict([{"source": "a", "raining": True}, {"source": "b", "raining": True}])["raining"], True)
        self.assertIs(wn.verdict([{"source": "a", "raining": True}, {"source": "b", "raining": False}])["raining"], None)
        v = wn.verdict([{"source": "a", "raining": False}, {"source": "b", "error": "HTTP 503"}])
        self.assertEqual((v["raining"], v["of"]), (False, 1))
        self.assertIsNone(wn.verdict([{"source": "a", "error": "x"}])["raining"])


class Main(unittest.TestCase):
    def fake_get(self, url):
        if "open-meteo" in url:
            return OPEN_METEO_RAIN
        if "met.no" in url:
            return MET_NO
        if "aviationweather" in url:
            self.assertIn("ids=XXXX", url)
            return METAR
        raise AssertionError(url)

    def test_json_all_sources(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = wn.main(["--lat", "43.2", "--lon", "27.9", "--icao", "xxxx", "--json"], get=self.fake_get)
        out = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(out["verdict"]["raining"], True)
        self.assertEqual([s["source"] for s in out["sources"]], ["open-meteo", "met-no", "metar"])

    def test_failed_source_is_visible(self):
        def get(url):
            if "met.no" in url:
                raise urllib.error.HTTPError(url, 503, "busy", {}, None)
            return OPEN_METEO_DRY
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = wn.main(["--lat", "43.2", "--lon", "27.9"], get=get)
        self.assertEqual(code, 0)
        self.assertIn("не вали", buf.getvalue())
        self.assertIn("HTTP 503", buf.getvalue())

    def test_all_failed_exit_1(self):
        def get(url):
            raise urllib.error.URLError("no route")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(wn.main(["--lat", "0", "--lon", "0"], get=get), 1)


if __name__ == "__main__":
    unittest.main()
