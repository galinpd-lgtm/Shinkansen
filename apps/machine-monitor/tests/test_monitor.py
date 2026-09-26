"""Тестове на четците — без root, без мрежа, върху измислени файлове.

    cd apps/machine-monitor && python3 -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import monitor_lite as ml  # noqa: E402
import probe_device as pd  # noqa: E402


MDSTAT_OK = """Personalities : [raid1] [linear] [multipath] [raid0] [raid6] [raid5] [raid4] [raid10]
md0 : active raid1 sdb1[1] sda1[0]
      976630464 blocks super 1.2 [2/2] [UU]
      bitmap: 0/8 pages [0KB], 65536KB chunk

unused devices: <none>
"""

MDSTAT_DEGRADED = """Personalities : [raid1] [raid5]
md1 : active raid1 sdc1[2](F) sdd1[1]
      488254464 blocks super 1.2 [2/1] [_U]

md2 : active raid5 sde1[3] sdf1[1] sdg1[0]
      1953260544 blocks super 1.2 level 5, 512k chunk, algorithm 2 [3/2] [UU_]
      [==>..................]  recovery = 12.6% (123456/976630272) finish=85.3min speed=160000K/sec

md3 : inactive sdh1[0](S)
      976630464 blocks super 1.2

md4 : active (auto-read-only) raid1 sdi1[0] sdj1[1]
      1000 blocks [2/2] [UU]
      \tresync=PENDING

unused devices: <none>
"""


class Mdstat(unittest.TestCase):
    def test_healthy_mirror(self):
        [a] = ml.parse_mdstat(MDSTAT_OK)
        self.assertEqual(a["name"], "md0")
        self.assertEqual(a["level"], "raid1")
        self.assertEqual(a["devices"], ["sdb1", "sda1"])
        self.assertEqual((a["members"], a["up"]), (2, 2))
        self.assertFalse(a["degraded"])
        self.assertIsNone(a["sync"])

    def test_degraded_failed_recovery_inactive(self):
        arrays = {a["name"]: a for a in ml.parse_mdstat(MDSTAT_DEGRADED)}
        self.assertEqual(sorted(arrays), ["md1", "md2", "md3", "md4"])
        self.assertTrue(arrays["md1"]["degraded"])
        self.assertEqual(arrays["md1"]["failed"], ["sdc1"])
        md2 = arrays["md2"]
        self.assertEqual(md2["level"], "raid5")
        self.assertTrue(md2["degraded"])
        self.assertEqual(md2["sync"]["action"], "recovery")
        self.assertAlmostEqual(md2["sync"]["percent"], 12.6)
        self.assertAlmostEqual(md2["sync"]["finish_min"], 85.3)
        self.assertEqual(arrays["md3"]["state"], "inactive")
        self.assertIsNone(arrays["md3"]["level"])
        self.assertTrue(arrays["md3"]["degraded"])
        md4 = arrays["md4"]
        self.assertTrue(md4["readonly"])
        self.assertEqual(md4["level"], "raid1")
        self.assertFalse(md4["degraded"])
        self.assertTrue(md4["sync"]["pending"])

    def test_empty(self):
        self.assertEqual(ml.parse_mdstat(""), [])
        self.assertEqual(ml.parse_mdstat(None), [])
        self.assertEqual(ml.parse_mdstat("Personalities : \nunused devices: <none>\n"), [])


class Thermal(unittest.TestCase):
    def test_zones_sorted_numerically_and_bad_skipped(self):
        with tempfile.TemporaryDirectory() as base:
            def zone(n, ztype, temp):
                d = os.path.join(base, "thermal_zone%d" % n)
                os.makedirs(d)
                if ztype is not None:
                    with open(os.path.join(d, "type"), "w") as f:
                        f.write(ztype + "\n")
                if temp is not None:
                    with open(os.path.join(d, "temp"), "w") as f:
                        f.write(temp + "\n")
            zone(10, "x86_pkg_temp", "61500")
            zone(2, "acpitz", "27800")
            zone(3, None, "40000")         # без type → името на зоната
            zone(4, "broken", "N/A")      # неразбираемо → пропуска се
            zone(5, "empty", None)        # без temp → пропуска се
            os.makedirs(os.path.join(base, "cooling_device0"))
            zones = ml.parse_thermal(base)
        self.assertEqual([z["zone"] for z in zones], ["thermal_zone2", "thermal_zone3", "thermal_zone10"])
        self.assertEqual(zones[0], {"zone": "thermal_zone2", "type": "acpitz", "c": 27.8})
        self.assertEqual(zones[1]["type"], "thermal_zone3")
        self.assertEqual(zones[2]["c"], 61.5)

    def test_missing_base(self):
        self.assertEqual(ml.parse_thermal("/nonexistent/thermal"), [])


def fake_stat(pid, comm, start_ticks):
    # 52 полета като в истински /proc/<pid>/stat; поле 22 е starttime
    fields = ["S", "1"] + ["0"] * 17 + [str(start_ticks)] + ["0"] * 30
    return "%d (%s) %s\n" % (pid, comm, " ".join(fields))


class Tasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proc = self.tmp.name
        with open(os.path.join(self.proc, "uptime"), "w") as f:
            f.write("1000.00 3000.00\n")

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, pid, argv, start_ticks=0, comm=None):
        d = os.path.join(self.proc, str(pid))
        os.makedirs(d)
        with open(os.path.join(d, "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in argv) + (b"\0" if argv else b""))
        with open(os.path.join(d, "stat"), "w") as f:
            f.write(fake_stat(pid, comm or os.path.basename(argv[0]) if argv else "kthread", start_ticks))

    def test_patterns_match_exe_and_script(self):
        self.add(100, ["/usr/bin/rsync", "-a", "/src/", "/dst/"], start_ticks=40000)   # 400 s от старта
        self.add(101, ["/bin/bash", "/opt/example-backup.sh", "--nightly"], start_ticks=90000,
                 comm="bash (x) y")          # скоби и интервали в името
        self.add(102, ["/usr/bin/vim", "rsync-notes.txt"])                          # не е rsync
        self.add(103, [])                                                            # нишка на ядрото
        self.add(104, ["/usr/bin/rsync", "--server"], start_ticks=0)                 # самият монитор
        os.makedirs(os.path.join(self.proc, "self"))
        rules = ml.compile_process_rules([
            {"name": "rsync", "pattern": r"(^|/)rsync( |$)"},
            {"name": "backup", "pattern": r"example-backup\.sh"},
        ])
        found = ml.scan_processes(rules, proc=self.proc, self_pid=104, clk_tck=100)
        self.assertEqual(found, [
            {"name": "backup", "pid": 101, "elapsed_s": 100},
            {"name": "rsync", "pid": 100, "elapsed_s": 600},
        ])

    def test_agent_prompt_is_not_a_running_task(self):
        # Случай от изпитването на живо: процес на Claude Code, в чийто аргумент е текстът на задачата
        # с думата „benchmark“, излизаше като „бенчмаркът върви 3,4 ч“.
        self.add(200, ["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js", "-p",
                       "run the benchmark and report the results"], start_ticks=0)
        self.add(201, ["claude", "--resume", "benchmark"], start_ticks=0)
        self.add(202, ["/usr/bin/python3", "-u", "/opt/example/benchmark.py", "--runs", "5"],
                 start_ticks=88000)
        self.add(203, ["/usr/local/bin/benchmark", "--all"], start_ticks=99000)
        default = ml.compile_process_rules([{"name": "benchmark", "pattern": r"^benchmark(\.py)?$"}])
        found = ml.scan_processes(default, proc=self.proc, self_pid=0, clk_tck=100)
        self.assertEqual([p["pid"] for p in found], [202, 203])

        exe = ml.compile_process_rules([{"name": "b", "pattern": "^benchmark$", "match": "exe"}])
        self.assertEqual([p["pid"] for p in ml.scan_processes(exe, proc=self.proc, self_pid=0)], [203])

        # "cmdline" пази старото, широко поведение — и хваща агента
        wide = ml.compile_process_rules([{"name": "b", "pattern": "benchmark", "match": "cmdline"}])
        self.assertEqual([p["pid"] for p in ml.scan_processes(wide, proc=self.proc, self_pid=0)],
                         [200, 201, 202, 203])

    def test_match_targets(self):
        self.assertEqual(ml.match_targets(["/bin/bash", "/opt/x/run-backup.sh", "--now"], "script"),
                         ["bash", "run-backup.sh"])
        self.assertEqual(ml.match_targets(["/usr/bin/rsync", "-a", "src/", "dst/"], "exe"), ["rsync"])
        self.assertEqual(ml.match_targets(["claude", "-p", "бенчмарк сега"], "script"), ["claude"])
        self.assertEqual(ml.match_targets(["claude", "benchmark"], "script"), ["claude"])
        self.assertEqual(ml.match_targets(["a", "b c"], "cmdline"), ["a b c"])

    def test_unknown_match_mode(self):
        with self.assertRaisesRegex(ValueError, "argv"):
            ml.compile_process_rules([{"name": "x", "pattern": "x", "match": "argv"}])

    def test_no_rules_no_scan(self):
        self.assertEqual(ml.scan_processes([], proc="/nonexistent"), [])

    def test_bad_pattern_names_the_rule(self):
        with self.assertRaisesRegex(ValueError, "broken"):
            ml.compile_process_rules([{"name": "broken", "pattern": "("}])

    def test_summary(self):
        s = ml.tasks_summary([{"name": "rsync"}], [{"last_success": 5}, {"last_success": None},
                                                   {"last_success": 9}])
        self.assertEqual(s, {"busy": True, "last_success": 9})
        self.assertEqual(ml.tasks_summary([], []), {"busy": False, "last_success": None})


LOG = """2026-09-24 03:00:01 start
2026-09-24 03:41:12 backup finished OK
2026-09-25 03:00:02 start
2026-09-25 03:12:40 ERROR: target not reachable
2026-09-26T03:00:00 start
some line without time
backup finished OK
2026-09-26 04:00:00 cleanup
"""


def local(s):
    return datetime.fromisoformat(s).timestamp()


class Logs(unittest.TestCase):
    def test_last_success_takes_nearest_time_above(self):
        t, found = ml.last_success(LOG, r"backup finished OK")
        self.assertTrue(found)
        self.assertEqual(t, local("2026-09-26T03:00:00"))

    def test_last_success_with_own_time(self):
        t, found = ml.last_success(LOG.split("2026-09-25 03:00:02")[0], r"finished OK")
        self.assertEqual(t, local("2026-09-24T03:41:12"))

    def test_no_success(self):
        self.assertEqual(ml.last_success("2026-09-26 01:00:00 start\n", "finished OK"), (None, False))
        self.assertEqual(ml.last_success("", "finished OK"), (None, False))

    def test_success_without_any_time(self):
        self.assertEqual(ml.last_success("start\nfinished OK\n", "finished OK"), (None, True))

    def test_syslog_format(self):
        text = "Sep 26 02:10:05 host job: archive complete\n"
        t, found = ml.last_success(text, "archive complete",
                                   r"^(\w{3} +\d+ \d{2}:\d{2}:\d{2})", "%b %d %H:%M:%S")
        dt = datetime.fromtimestamp(t)
        self.assertEqual((dt.month, dt.day, dt.hour, dt.minute), (9, 26, 2, 10))

    def test_check_logs_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "b.log")
            with open(path, "w") as f:
                f.write(LOG)
            now = local("2026-09-26T05:00:00")
            [item] = ml.check_logs([{"name": "nightly", "path": path, "success": "finished OK"}], now=now)
            self.assertEqual(item["ago_s"], 7200)
            self.assertTrue(item["found"])
            self.assertIsNone(item["error"])

            # редът за успех няма време никъде → времето на файла
            with open(path, "w") as f:
                f.write("start\nfinished OK\n")
            os.utime(path, (now - 60, now - 60))
            [item] = ml.check_logs([{"path": path, "success": "finished OK"}], now=now)
            self.assertEqual((item["name"], item["ago_s"]), ("b.log", 60))

            [missing] = ml.check_logs([{"name": "gone", "path": os.path.join(d, "none.log"),
                                        "success": "x"}], now=now)
            self.assertIsNotNone(missing["error"])
            self.assertIsNone(missing["last_success"])

    def test_tail_drops_cut_first_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "big.log")
            with open(path, "w") as f:
                f.write("x" * 50 + "\n" + "2026-09-26 01:00:00 finished OK\n")
            self.assertEqual(ml.read_tail(path, limit=40), "2026-09-26 01:00:00 finished OK\n")


class ProcReaders(unittest.TestCase):
    def test_cpu_percent(self):
        a = ml.parse_cpu_times("cpu 100 0 100 800 0 0 0 0\ncpu0 50 0 50 400 0\ncpu1 50 0 50 400 0 0 0 0\n")
        b = ml.parse_cpu_times("cpu 200 0 200 1400 200 0 0 0\ncpu0 150 0 50 400 0\ncpu1 50 0 150 1000 200 0 0 0\n")
        total, cores = ml.cpu_percent(a, b)
        self.assertEqual(total, 20.0)
        self.assertEqual(cores, [100.0, 11.1])

    def test_meminfo(self):
        mem, swap = ml.parse_meminfo("MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 250 kB\n"
                                     "SwapTotal: 0 kB\nSwapFree: 0 kB\n")
        self.assertEqual(mem["total"], 1024000)
        self.assertEqual(mem["percent"], 75.0)
        self.assertEqual(swap["percent"], 0.0)

    def test_disk_missing_mount(self):
        [d] = ml.disk_usage(["/nonexistent/mount"])
        self.assertIn("error", d)

    def test_disk_same_filesystem_shown_once(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "data")
            os.makedirs(sub)
            disks = ml.disk_usage([d, sub, "/nonexistent/mount", d])
        self.assertEqual(len(disks), 2)
        self.assertEqual(disks[0]["mount"], d)
        self.assertEqual(disks[0]["mounts"], [d, sub])          # повторът се брои веднъж
        self.assertIn("total", disks[0])
        self.assertIn("error", disks[1])


class Probe(unittest.TestCase):
    REMOTE = {"name": "example-server", "tasks": {
        "running": [{"name": "rsync", "pid": 7, "elapsed_s": 30}, {"name": "other", "pid": 8, "elapsed_s": 1}],
        "logs": [{"name": "nightly backup", "last_success": 1000.0, "ago_s": 5, "found": True, "error": None},
                 {"name": "unrelated", "last_success": 5000.0, "ago_s": 1, "found": True, "error": None}],
    }}

    def test_writer_filtered(self):
        t = pd.writer_tasks({"url": "http://example.invalid/api/now", "processes": ["rsync"],
                             "logs": ["nightly backup"]}, now=4600.0, fetch=lambda url: self.REMOTE)
        self.assertEqual([p["name"] for p in t["running"]], ["rsync"])
        self.assertEqual([l["name"] for l in t["logs"]], ["nightly backup"])
        self.assertEqual(t["logs"][0]["ago_s"], 3600)
        self.assertEqual(t["summary"], {"busy": True, "last_success": 1000.0})
        self.assertEqual(t["source"], {"name": "example-server", "ok": True})

    def test_writer_unreachable_is_reported(self):
        def boom(url):
            raise OSError("connection refused")
        t = pd.writer_tasks({"name": "w", "url": "http://example.invalid/"}, now=0, fetch=boom)
        self.assertFalse(t["source"]["ok"])
        self.assertIn("connection refused", t["source"]["error"])
        self.assertIsNone(t["summary"]["busy"])

    def test_history_point_device(self):
        p = ml.history_point({"time": time.time(), "device": {"reachable": False}})
        self.assertIs(p["up"], False)
        self.assertIsNone(p["cpu"])


class ConfigExample(unittest.TestCase):
    def test_example_loads_and_uses_documentation_addresses(self):
        path = os.path.join(os.path.dirname(HERE), "config.example.json")
        mon = ml.load_config(path)
        probe = ml.load_config(path, section="probe", defaults=pd.DEFAULTS)
        self.assertEqual(mon["port"], 8190)
        ml.compile_process_rules(mon["tasks"]["processes"])
        self.assertTrue(probe["host"].startswith("192.0.2."))
        self.assertIn("//192.0.2.", probe["writer"]["url"])


if __name__ == "__main__":
    unittest.main()
