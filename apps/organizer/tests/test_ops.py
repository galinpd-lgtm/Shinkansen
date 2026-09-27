"""Тестове на package и qa — без мрежа. qa с PHP се пропуска, ако няма php; без браузър (--no-shots).

    cd apps/organizer && python3 -m unittest discover -s tests -v
"""
import copy
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
import ops  # noqa: E402
import organizer  # noqa: E402

EXAMPLE = os.path.join(APP, "examples", "intensive")
DAY = date(2026, 9, 27)


def site_with(files):
    d = tempfile.mkdtemp()
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
        with open(os.path.join(d, rel), "w", encoding="utf-8") as f:
            f.write(text)
    return d


class Package(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out)

    def test_deterministic_and_verifiable(self):
        a = site_with({"index.html": "<p>1</p>", "assets/s.css": "a{}"})
        b = site_with({"assets/s.css": "a{}", "index.html": "<p>1</p>"})   # същото, друг ред на създаване
        ra = ops.package(a, self.out, name="ev", today=DAY)
        rb = ops.package(b, os.path.join(self.out, "b"), name="ev", today=DAY)
        self.assertEqual(ra["sha256"], rb["sha256"])
        self.assertTrue(os.path.basename(ra["tgz"]).startswith("ev_2026-09-27_"))
        with open(ra["tgz"] + ".sha256") as f:
            self.assertEqual(f.read().split()[0], ops.sha256_file(ra["tgz"]))
        with tarfile.open(ra["tgz"]) as t:
            self.assertEqual(sorted(t.getnames()), ["assets/s.css", "index.html"])
            self.assertTrue(all(m.mtime == 0 and m.uid == 0 for m in t.getmembers()))

    def test_never_overwrites_and_reports_diff(self):
        old = site_with({"index.html": "1", "tema-12.html": "стара", "stara.html": "x"})
        r1 = ops.package(old, self.out, name="ev", today=DAY)
        again = ops.package(old, self.out, name="ev", today=DAY)
        self.assertTrue(again["existed"])
        new = site_with({"index.html": "1", "tema-12.html": "нова", "nova.html": "y"})
        r2 = ops.package(new, self.out, name="ev", prev=r1["tgz"], today=DAY)
        self.assertEqual(r2["diff"], {"added": ["nova.html"], "removed": ["stara.html"], "changed": ["tema-12.html"]})
        self.assertTrue(os.path.exists(r1["tgz"]))                      # предишният пакет е непокътнат
        with open(r2["tgz"][:-4] + ".diff.txt", encoding="utf-8") as f:
            self.assertIn("сменен  tema-12.html", f.read())

    def test_cli(self):
        a = site_with({"index.html": "1"})
        self.assertEqual(organizer.main(["package", a, self.out]), 0)
        self.assertEqual(organizer.main(["package", os.path.join(a, "nyama"), self.out]), 1)


@unittest.skipUnless(shutil.which("php"), "няма php")
class Qa(unittest.TestCase):
    def test_example_passes(self):
        with tempfile.TemporaryDirectory() as rep:
            path, failed = ops.qa(EXAMPLE, rep, shots=False, build=organizer.build)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertEqual(failed, 0, text)
            for needle in ("лични полета само в _kontakt", "износ в CSV", "непозната опция се отхвърля",
                           "износът без заключена папка отказва"):
                self.assertIn(needle, text)

    def test_build_failure_is_reported(self):
        src = tempfile.mkdtemp()
        shutil.copytree(EXAMPLE, src, dirs_exist_ok=True)
        with open(os.path.join(src, "event.json"), encoding="utf-8") as f:
            ev = json.load(f)
        ev["tagline"] = "Виж [тук](nyama.html)."
        with open(os.path.join(src, "event.json"), "w", encoding="utf-8") as f:
            json.dump(ev, f, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as rep:
            path, failed = ops.qa(src, rep, shots=False, build=organizer.build)
            self.assertEqual(failed, 1)
            with open(path, encoding="utf-8") as f:
                self.assertIn("nyama.html", f.read())
        shutil.rmtree(src)

    def test_sample_answer_is_valid(self):
        spec = organizer.forms_spec(organizer.load(EXAMPLE)[0])
        for form in spec["forms"].values():
            ans = ops.sample_answer(form)
            self.assertTrue(all(f["id"] in ans for f in form["fields"]))


if __name__ == "__main__":
    unittest.main()
