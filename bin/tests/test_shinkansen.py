"""Тестове на диспечера и на формата на всички скилове — без мрежа.

    python3 -m unittest discover -s bin/tests -v
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest import mock

BIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BIN)
SCRIPT = os.path.join(BIN, "shinkansen")

loader = importlib.machinery.SourceFileLoader("shinkansen", SCRIPT)
spec = importlib.util.spec_from_loader("shinkansen", loader)
sk = importlib.util.module_from_spec(spec)
loader.exec_module(sk)

SECTIONS = ("Какво иска", "Какво връща", "Ниво", "Къде тече", "Пример")


def make_skill(base, name, level="чете", body_py="print('hi')\n", desc="Прави нещо."):
    d = os.path.join(base, name)
    os.makedirs(d)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: %s\ndescription: %s\n---\n\n# %s\n\n## Ниво\n%s — обяснение\n" % (name, desc, name, level))
    with open(os.path.join(d, name.replace("-", "_") + ".py"), "w") as f:
        f.write(body_py)


class Parse(unittest.TestCase):
    def test_frontmatter_and_level(self):
        info = sk.parse_skill_md('---\nname: x-y\ndescription: "Кога: винаги."\n---\n# t\n\n## Ниво\n**чернови** — пише файл\n')
        self.assertEqual((info["name"], info["description"], info["level"]), ("x-y", "Кога: винаги.", "чернови"))
        self.assertIsNone(sk.parse_skill_md("без frontmatter")["name"])

    def test_one_line(self):
        self.assertEqual(sk.one_line("a\n b\t c"), "a b c")
        self.assertEqual(len(sk.one_line("x" * 500)), sk.SUMMARY_MAX)


class Dispatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skills = os.path.join(self.tmp.name, "skills")
        self.runs = os.path.join(self.tmp.name, "runs")
        os.makedirs(self.skills)
        make_skill(self.skills, "echo-args", body_py=(
            "import os, sys\nprint(' '.join(sys.argv[1:]))\n"
            "p = os.environ.get('SHINKANSEN_SUMMARY_FILE')\n"
            "open(p, 'w').write('2 неща')\n"))
        make_skill(self.skills, "finds", level="чете", body_py="import sys\nsys.exit(4)\n")
        make_skill(self.skills, "crashes", body_py="raise RuntimeError('секретен вход')\n")
        os.makedirs(os.path.join(self.skills, "Bad_Name"))
        os.makedirs(os.path.join(self.skills, "no-md"))

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, runs=True):
        env = dict(os.environ, SHINKANSEN_SKILLS=self.skills)
        env.pop("SHINKANSEN_RUNS", None)
        if runs:
            env["SHINKANSEN_RUNS"] = self.runs
        return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, env=env)

    def runs_of(self, name):
        with open(os.path.join(self.runs, name + ".jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_list(self):
        r = self.cli("list")
        self.assertEqual(r.returncode, 0)
        names = [ln.split()[0] for ln in r.stdout.splitlines()]
        self.assertEqual(names, ["crashes", "echo-args", "finds"])      # без Bad_Name и no-md
        self.assertIn("[чете]", r.stdout)

    def test_show(self):
        r = self.cli("show", "finds")
        self.assertTrue(r.stdout.startswith("---\nname: finds"))

    def test_run_passes_args_and_logs_summary(self):
        r = self.cli("run", "echo-args", "a", "b c")
        self.assertEqual((r.returncode, r.stdout), (0, "a b c\n"))
        [rec] = self.runs_of("echo-args")
        self.assertEqual(set(rec), {"t", "helper", "ok", "summary"})
        self.assertEqual((rec["helper"], rec["ok"]), ("echo-args", True))
        self.assertTrue(rec["summary"].startswith("2 неща · exit 0"))
        self.assertNotIn("b c", rec["summary"])                      # нищо от входа
        datetime.fromisoformat(rec["t"])

    def test_findings_ok_crash_not_ok(self):
        self.assertEqual(self.cli("run", "finds").returncode, 4)
        self.assertEqual(self.cli("run", "crashes", "парола123").returncode, 1)
        self.assertTrue(self.runs_of("finds")[0]["ok"])
        crash = self.runs_of("crashes")[0]
        self.assertFalse(crash["ok"])
        self.assertNotIn("секретен", crash["summary"])                # stderr не влиза в дневника
        self.assertNotIn("парола", crash["summary"])

    def test_appends(self):
        self.cli("run", "finds")
        self.cli("run", "finds")
        self.assertEqual(len(self.runs_of("finds")), 2)

    def test_no_runs_env_no_log(self):
        self.cli("run", "finds", runs=False)
        self.assertFalse(os.path.exists(self.runs))

    def test_unknown_and_traversal(self):
        for name in ("nope", "../skills", "Bad_Name", ""):
            r = self.cli("run", name)
            self.assertEqual(r.returncode, 2, name)
        self.assertFalse(os.path.exists(self.runs))

    def test_log_run_direct(self):
        rec = sk.log_run("x", True, "ред\nвтори", runs_dir=self.runs,
                         now=datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(rec, {"t": "2026-09-26T10:00:00+00:00", "helper": "x", "ok": True, "summary": "ред втори"})
        self.assertIsNone(sk.log_run("x", True, "s", runs_dir=""))


class RealSkills(unittest.TestCase):
    """Всеки скил в skills/ е по формата — и Claude Code може да го зареди."""

    def test_format(self):
        skills = sk.find_skills(os.path.join(ROOT, "skills"))
        self.assertGreaterEqual(len(skills), 6)
        for s in skills:
            with self.subTest(s["dir"]):
                self.assertEqual(s["name"], s["dir"])                     # името е като папката
                self.assertRegex(s["name"], r"^[a-z0-9-]{1,64}$")
                self.assertTrue(0 < len(s["description"]) <= 1024)
                self.assertIn(s["level"], sk.LEVELS)
                for sec in SECTIONS:
                    self.assertRegex(s["body"], r"(?m)^## %s\s*$" % re.escape(sec))
                self.assertTrue(os.path.isfile(s["entry"]), s["entry"])
                tests = os.path.join(s["path"], "tests")
                self.assertTrue(any(f.startswith("test_") for f in os.listdir(tests)))

    def test_list_real(self):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"SHINKANSEN_SKILLS": os.path.join(ROOT, "skills")}), redirect_stdout(buf):
            self.assertEqual(sk.cmd_list(), 0)
        self.assertIn("leak-filter", buf.getvalue())

    def test_claude_code_link(self):
        link = os.path.join(ROOT, ".claude", "skills")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.path.realpath(link), os.path.realpath(os.path.join(ROOT, "skills")))


if __name__ == "__main__":
    unittest.main()
