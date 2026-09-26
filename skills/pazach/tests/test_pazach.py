"""Тестове без мрежа: смяна, без повторение, възстановяване, прагове, изтичане, rip/off, status.json.

    python3 -m unittest discover -s skills/pazach/tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pazach as pz  # noqa: E402

NOW = 1_790_000_000.0
TODAY = date(2026, 9, 26)
MON = "http://192.0.2.10:8190/api/now"


def snap(**over):
    # "fresh" — World го подменя с времето на хода, както би го дал жив монитор
    d = {"kind": "machine", "name": "example-server", "time": "fresh",
         "temps": [{"zone": "z0", "type": "cpu", "c": 45.0}],
         "disks": [{"mount": "/", "mounts": ["/", "/data"], "percent": 40.0}],
         "raid": [{"name": "md0", "degraded": False}], "failed_units": [],
         "tasks": {"running": [], "logs": [{"name": "nightly", "last_success": NOW - 3600}]}}
    d.update(over)
    return d


class World:
    """Подменя мрежата: отговорите по адрес и записаните известия."""

    def __init__(self):
        self.responses = {}
        self.sent = []
        self.post_fails = False
        self.now = NOW

    def fetch(self, url, timeout):
        r = self.responses.get(url)
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise urllib.error.URLError("connection refused")
        if isinstance(r, dict) and r.get("time") == "fresh":
            r = dict(r, time=self.now - 5)
        return r

    def post(self, url, payload, timeout, headers=None):
        if self.post_fails:
            raise urllib.error.URLError("hook down")
        self.sent.append(payload)
        return 200


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = World()
        self.cfg = {
            "status_file": os.path.join(self.tmp.name, "out", "status.json"),
            "state_file": os.path.join(self.tmp.name, "state.json"),
            "webhook": {"url": "http://192.0.2.40:8080/hook"},
            "checks": [{"name": "srv", "type": "monitor", "url": MON, "link": "http://192.0.2.10:8190/"}],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def tick(self, now=NOW, digest=False, today=TODAY):
        self.w.now = now
        return pz.run(self.cfg, digest=digest, fetch=self.w.fetch, post=self.w.post, now=now, today=today,
                      out=io.StringIO())

    def status(self):
        with open(self.cfg["status_file"]) as f:
            return json.load(f)


class Notifications(Base):
    def test_change_no_repeat_recovery(self):
        self.w.responses[MON] = snap()
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.w.sent, [])                           # първо ok — тишина

        self.w.responses[MON] = snap(raid=[{"name": "md0", "degraded": True}])
        self.assertEqual(self.tick(NOW + 900)[0], 4)
        self.assertEqual(len(self.w.sent), 1)
        n = self.w.sent[0]
        self.assertEqual(set(n), {"level", "check", "message", "since"})
        self.assertEqual((n["level"], n["check"]), ("crit", "srv"))
        self.assertIn("RAID md0 degraded", n["message"])

        self.w.responses[MON] = snap(raid=[{"name": "md0", "degraded": True}], temps=[{"c": 50.0}])
        self.tick(NOW + 1800)
        self.assertEqual(len(self.w.sent), 1)                       # същото ниво — без повторение

        self.w.responses[MON] = snap()
        self.tick(NOW + 2700)
        self.assertEqual(len(self.w.sent), 2)
        rec = self.w.sent[1]
        self.assertEqual(rec["level"], "ok")
        self.assertTrue(rec["message"].startswith("възстановено"))
        self.tick(NOW + 3600)
        self.assertEqual(len(self.w.sent), 2)

    def test_since_is_when_level_began(self):
        self.w.responses[MON] = snap(failed_units=["example.service"])
        self.tick(NOW)
        self.tick(NOW + 900)
        with open(self.cfg["state_file"]) as f:
            st = json.load(f)
        self.assertEqual(st["srv"]["since"], pz.now_iso(NOW))
        self.assertEqual(self.w.sent[0]["since"], pz.now_iso(NOW))

    def test_failed_webhook_retries_once_delivered(self):
        self.w.responses[MON] = snap(raid=[{"name": "md0", "degraded": True}])
        self.w.post_fails = True
        code, summary = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("неизпратени 1", summary)
        self.w.post_fails = False
        self.tick(NOW + 900)
        self.assertEqual(len(self.w.sent), 1)                       # изпратено при следващия ход
        self.tick(NOW + 1800)
        self.assertEqual(len(self.w.sent), 1)

    def test_escalation_warn_to_crit_notifies(self):
        self.w.responses[MON] = snap(temps=[{"c": 82.0}])
        self.tick()
        self.w.responses[MON] = snap(temps=[{"c": 93.0}])
        self.tick(NOW + 900)
        self.assertEqual([n["level"] for n in self.w.sent], ["warn", "crit"])


class RipOff(Base):
    def test_rip_when_silent(self):
        code, _ = self.tick()                                       # няма отговор
        self.assertEqual(code, 4)
        st = self.status()
        self.assertEqual(st["items"][0]["level"], "rip")
        self.assertEqual(st["overall"], "crit")                      # rip → crit в общото
        self.assertEqual(self.w.sent[0]["level"], "rip")

    def test_rip_when_monitor_stale(self):
        self.w.responses[MON] = snap(time=NOW - 3600)
        self.tick()
        self.assertEqual(self.status()["items"][0]["level"], "rip")

    def test_off_is_silent_and_not_counted_in_overall(self):
        self.cfg["checks"].append({"name": "old", "type": "monitor", "url": "http://192.0.2.13/", "enabled": False})
        self.w.responses[MON] = snap()
        self.assertEqual(self.tick()[0], 0)
        st = self.status()
        self.assertEqual(st["overall"], "ok")
        self.assertEqual(st["counts"]["off"], 1)
        self.assertEqual(self.w.sent, [])

    def test_turning_off_while_crit_then_on(self):
        self.tick()                                                 # rip → известие
        self.cfg["checks"][0]["enabled"] = False
        self.tick(NOW + 900)
        self.assertEqual(len(self.w.sent), 1)                       # спирането не вика
        self.cfg["checks"][0]["enabled"] = True
        self.tick(NOW + 1800)
        self.assertEqual([n["level"] for n in self.w.sent], ["rip", "rip"])  # пак мълчи → пак вика

    def test_device_probe(self):
        self.w.responses[MON] = {"kind": "device", "name": "nas", "time": "fresh",
                                 "device": {"reachable": False, "ports": [{"port": 445, "open": False}]}}
        self.tick()
        self.assertEqual(self.status()["items"][0]["level"], "rip")
        self.w.responses[MON] = {"kind": "device", "name": "nas", "time": "fresh",
                                 "device": {"reachable": True, "ports": [{"port": 445, "open": False}]},
                                 "tasks": {"running": [], "logs": [], "source": {"name": "w", "ok": False}}}
        self.tick(NOW + 900)
        item = self.status()["items"][0]
        self.assertEqual(item["level"], "warn")
        self.assertIn("445", item["msg"])
        self.assertIn("не чете задачите", item["msg"])


class Thresholds(unittest.TestCase):
    def mon(self, d, **cfg):
        c = dict({"name": "m", "type": "monitor", "url": MON}, **cfg)
        if d.get("time") == "fresh":
            d = dict(d, time=NOW - 5)
        return pz.check_monitor(c, lambda u, t: d, NOW, 5)

    def test_monitor(self):
        self.assertEqual(self.mon(snap())[0], "ok")
        self.assertEqual(self.mon(snap(temps=[{"c": 80.0}]))[0], "warn")
        self.assertEqual(self.mon(snap(temps=[{"c": 91.0}]))[0], "crit")
        self.assertEqual(self.mon(snap(temps=[{"c": 70.0}]), temp_warn_c=65)[0], "warn")
        lvl, msg = self.mon(snap(disks=[{"mount": "/", "mounts": ["/", "/data"], "percent": 96.0}]))
        self.assertEqual(lvl, "crit")
        self.assertIn("/ · /data", msg)
        self.assertEqual(self.mon(snap(disks=[{"mount": "/x", "error": "No such file"}]))[0], "warn")
        self.assertEqual(self.mon(snap(failed_units=["a.service"]))[0], "warn")
        self.assertEqual(self.mon(snap(failed_units=["a.service"]), failed_units=False)[0], "ok")
        long_task = {"running": [{"name": "rsync", "elapsed_s": 7 * 3600}], "logs": []}
        lvl, msg = self.mon(snap(tasks=long_task))
        self.assertEqual(lvl, "warn")
        self.assertIn("rsync върви 7.0 ч", msg)
        self.assertEqual(self.mon(snap(tasks=long_task), task_max_hours=8)[0], "ok")
        old = {"running": [], "logs": [{"name": "nightly", "last_success": NOW - 30 * 3600}]}
        self.assertEqual(self.mon(snap(tasks=old))[0], "ok")        # success_max_hours не е зададено
        self.assertEqual(self.mon(snap(tasks=old), success_max_hours=26)[0], "warn")

    def test_worst_wins_and_listed_first(self):
        lvl, msg = self.mon(snap(temps=[{"c": 82.0}], raid=[{"name": "md1", "degraded": True}]))
        self.assertEqual(lvl, "crit")
        self.assertTrue(msg.startswith("RAID md1"))

    def sj(self, data, **cfg):
        c = dict({"name": "s", "type": "status_json", "url": "http://192.0.2.12/s.json"}, **cfg)
        return pz.check_status_json(c, lambda u, t: data, NOW, 5)

    def test_status_json(self):
        d = {"queue": {"pending": 60}, "items": [{"level": "ok"}], "generated": pz.now_iso(NOW - 4 * 3600)}
        self.assertEqual(self.sj(d, field="queue.pending", warn_above=50, crit_above=200)[0], "warn")
        self.assertEqual(self.sj(d, field="queue.pending", warn_above=100)[0], "ok")
        self.assertEqual(self.sj(d, field="queue.pending", crit_below=100)[0], "crit")
        self.assertEqual(self.sj(d, field="items.0.level", expect="ok")[0], "ok")
        self.assertEqual(self.sj(d, field="items.0.level", expect="green")[0], "crit")
        self.assertEqual(self.sj(d, field="generated", warn_age_hours=3, crit_age_hours=12)[0], "warn")
        self.assertEqual(self.sj(d, field="generated", warn_age_hours=5)[0], "ok")
        self.assertEqual(self.sj({"t": NOW - 13 * 3600}, field="t", crit_age_hours=12)[0], "crit")
        lvl, msg = self.sj(d, field="queue.missing", warn_above=1)
        self.assertEqual(lvl, "crit")
        self.assertIn("липсва поле", msg)

    def test_status_json_from_file_and_missing_file_is_rip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            with open(p, "w") as f:
                json.dump({"x": 5}, f)
            c = {"name": "f", "type": "status_json", "path": p, "field": "x", "warn_above": 3}
            self.assertEqual(pz.check_status_json(c, None, NOW, 5)[0], "warn")
            c["path"] = os.path.join(d, "none.json")
            self.assertEqual(pz.check_status_json(c, None, NOW, 5)[0], "rip")

    def test_get_path(self):
        self.assertEqual(pz.get_path({"a": [{"b": 3}]}, "a.0.b"), 3)
        with self.assertRaises((KeyError, IndexError)):
            pz.get_path({"a": []}, "a.0")


class Expiry(unittest.TestCase):
    def ex(self, d, **cfg):
        return pz.check_expiry(dict({"name": "cert", "date": d}, **cfg), TODAY)

    def test_levels(self):
        self.assertEqual(self.ex("2027-01-01")[0], "ok")
        self.assertEqual(self.ex("2026-10-20")[0], "warn")          # 24 дни, праг 30
        lvl, msg = self.ex("2026-10-01")
        self.assertEqual(lvl, "crit")                               # 5 дни, праг 7
        self.assertIn("след 5 дни", msg)
        self.assertEqual(self.ex("2026-09-26")[0], "crit")
        self.assertIn("изтече преди 3 дни", self.ex("2026-09-23")[1])
        self.assertEqual(self.ex("2026-11-20", warn_days=60)[0], "warn")
        self.assertEqual(self.ex("not-a-date")[0], "crit")


class StatusAndDigest(Base):
    def test_status_format_exact(self):
        self.cfg["checks"].append({"name": "cert", "type": "expiry", "date": "2026-10-20"})
        self.w.responses[MON] = snap()
        self.tick()
        st = self.status()
        self.assertEqual(list(st), ["generated", "overall", "counts", "items"])
        self.assertEqual(st["overall"], "warn")
        self.assertEqual(st["counts"], {"ok": 1, "warn": 1, "crit": 0, "rip": 0, "off": 0})
        for item in st["items"]:
            self.assertEqual(list(item), ["level", "name", "msg", "link"])
        self.assertEqual(st["items"][0]["link"], "http://192.0.2.10:8190/")
        self.assertIsNone(st["items"][1]["link"])
        self.assertEqual(st["generated"], pz.now_iso(NOW))
        # атомарно: не остават временни файлове
        self.assertEqual(os.listdir(os.path.dirname(self.cfg["status_file"])), ["status.json"])

    def test_broken_check_is_crit_not_silence(self):
        self.cfg["checks"].append({"name": "odd", "type": "nope"})
        self.cfg["checks"].append({"name": "boom", "type": "status_json", "url": "x", "field": "a",
                                   "warn_above": "not-a-number"})
        self.w.responses[MON] = snap()
        self.w.responses["x"] = {"a": 5}
        self.tick()
        levels = {i["name"]: i["level"] for i in self.status()["items"]}
        self.assertEqual(levels["odd"], "crit")
        self.assertEqual(levels["boom"], "crit")

    def test_digest(self):
        self.cfg["checks"] += [
            {"name": "cert", "type": "expiry", "what": "сертификатът", "date": "2026-10-05"},
            {"name": "domain", "type": "expiry", "what": "домейнът", "date": "2026-12-01"},
            {"name": "old", "type": "expiry", "date": "2026-09-30", "enabled": False},
        ]
        self.w.responses[MON] = snap(failed_units=["x.service"])
        self.tick(digest=True)
        digest = [n for n in self.w.sent if n["check"] == "digest"]
        self.assertEqual(len(digest), 1)
        text = digest[0]["message"]
        self.assertIn("WARN srv: паднали услуги", text)
        self.assertIn("сертификатът — след 9 дни", text)
        self.assertNotIn("домейнът", text)                          # след 66 дни — не е в сводката
        self.assertNotIn("old", text)                               # спряна
        self.assertIn("Наред: 1 от 3, спрени: 1.", text)

    def test_removed_check_forgotten(self):
        self.tick()
        self.cfg["checks"] = [{"name": "cert", "type": "expiry", "date": "2027-01-01"}]
        self.tick(NOW + 900)
        with open(self.cfg["state_file"]) as f:
            self.assertEqual(list(json.load(f)), ["cert"])


class Cli(unittest.TestCase):
    def test_runs_log_and_bad_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {"status_file": os.path.join(d, "status.json"), "state_file": os.path.join(d, "st.json"),
                   "checks": [{"name": "cert", "type": "expiry", "date": "2099-01-01"}]}
            p = os.path.join(d, "cfg.json")
            with open(p, "w") as f:
                json.dump(cfg, f)
            runs = os.path.join(d, "runs")
            env = {"SHINKANSEN_RUNS": runs}
            with mock.patch.dict(os.environ, env), mock.patch("sys.stdout", io.StringIO()):
                os.environ.pop("SHINKANSEN_SUMMARY_FILE", None)
                self.assertEqual(pz.main(["--config", p, "--once"]), 0)
            with open(os.path.join(runs, "pazach.jsonl")) as f:
                rec = json.loads(f.readline())
            self.assertEqual(set(rec), {"t", "helper", "ok", "summary"})
            self.assertEqual((rec["helper"], rec["ok"]), ("pazach", True))

            with open(p, "w") as f:
                json.dump({"checks": [{"type": "expiry"}]}, f)
            with mock.patch.dict(os.environ, env), mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(pz.main(["--config", p, "--once"]), 1)

    def test_validate(self):
        errs = pz.validate_config({"status_file": "s", "state_file": "t", "checks": [
            {"name": "a", "type": "monitor"}, {"name": "a", "type": "expiry"},
            {"name": "b", "type": "status_json", "url": "u"}]})
        self.assertEqual(len(errs), 4)

    def test_example_config_valid(self):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.example.json")
        with open(p) as f:
            cfg = json.load(f)
        self.assertEqual(pz.validate_config(cfg), [])
        for c in cfg["checks"]:
            for key in ("url", "link"):
                if key in c:
                    self.assertIn("//192.0.2.", c[key])


if __name__ == "__main__":
    unittest.main()
