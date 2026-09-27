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




class Fill(unittest.TestCase):
    def copy(self):
        d = tempfile.mkdtemp()
        shutil.copytree(EXAMPLE, d, dirs_exist_ok=True)
        self.addCleanup(shutil.rmtree, d)
        return d

    def test_example_is_already_filled(self):
        d, _ = ops.fill(EXAMPLE, dry_run=True)
        self.assertEqual(d, {"added": [], "removed": [], "changed": []})

    def test_source_change_shows_key_diff_and_keeps_backup(self):
        d = self.copy()
        md = os.path.join(d, "izvori", "demota.md")
        with open(md, encoding="utf-8") as f:
            text = f.read()
        with open(md, "w", encoding="utf-8") as f:
            f.write(text.replace("Отговор с цитат.", "Отговор с цитат и отказ."))
        diff, log = ops.fill(d)
        self.assertEqual(diff["changed"], ["home.sections[2].items[1].text"])
        self.assertEqual(diff["added"], [])                           # upsert по заглавие, не второ копие
        self.assertTrue(os.path.exists(os.path.join(d, "event.json.orig_" + date.today().isoformat())))
        with open(os.path.join(d, "decisions.md"), encoding="utf-8") as f:
            self.assertIn("izvori/demota.md#2 → home.sections (upsert)", f.read())
        ops.fill(d)                                                   # нищо ново → нито запис, нито копие
        with open(md, "w", encoding="utf-8") as f:
            f.write(text)
        ops.fill(d)
        backups = [x for x in os.listdir(d) if x.startswith("event.json.orig_")]
        self.assertEqual(len(backups), 2)                             # второто копие не презаписва първото

    def test_errors_reach_check_and_build(self):
        d = self.copy()
        with open(os.path.join(d, "event.json"), encoding="utf-8") as f:
            ev = json.load(f)
        ev["sources"].append({"file": "izvori/nyama.md", "block": "1", "target": "x"})
        ev["sources"].append({"file": "izvori/demota.md", "block": "9", "target": "x"})
        with open(os.path.join(d, "event.json"), "w", encoding="utf-8") as f:
            json.dump(ev, f, ensure_ascii=False)
        errs = ops.check_sources(d, ev)
        self.assertTrue(any("няма файл izvori/nyama.md" in e for e in errs), errs)
        self.assertTrue(any("раздел „9“: няма такъв" in e for e in errs), errs)
        self.assertEqual(organizer.main(["check", d]), 1)

    def test_apply_op_modes(self):
        doc = {"topics": [{"n": 1, "demo": {"steps": ["a"]}}], "home": {"sections": []}}
        ops.apply_op(doc, "topics[n=1].demo.steps", ["b", "a"], "extend")
        self.assertEqual(doc["topics"][0]["demo"]["steps"], ["a", "b"])
        ops.apply_op(doc, "topics[n=1].demo.steps", "z", "insert", at=0)
        ops.apply_op(doc, "topics[n=1].demo.steps", "z", "insert", at=0)
        self.assertEqual(doc["topics"][0]["demo"]["steps"], ["z", "a", "b"])
        ops.apply_op(doc, "topics[0].demo", {"title": "Демо"}, "merge")
        self.assertEqual(doc["topics"][0]["demo"]["title"], "Демо")
        ops.apply_op(doc, "privacy.title", "Поверителност")           # липсващите обекти се създават
        self.assertEqual(doc["privacy"], {"title": "Поверителност"})
        with self.assertRaises(ValueError):
            ops.apply_op(doc, "topics[n=7].demo", {}, "set")
        with self.assertRaises(ValueError):
            ops.apply_op(doc, "home.sections", {"x": 1}, "upsert")    # upsert без key


if __name__ == "__main__":
    unittest.main()
