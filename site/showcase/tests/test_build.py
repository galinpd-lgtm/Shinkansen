"""Тестове на витрината — без мрежа, без браузър.

    python3 -m unittest discover -s site/showcase/tests -v
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import build  # noqa: E402

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


class RealBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path, cls.skills = build.build(cls.tmp.name, commit="0123456789abcdef", now=NOW)
        with open(cls.path, encoding="utf-8") as f:
            cls.html = f.read()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_skill_in_catalogue_with_level_and_both_languages(self):
        names = sorted(os.path.basename(os.path.dirname(p)) for p in
                       __import__("glob").glob(os.path.join(build.ROOT, "skills", "*", "SKILL.md")))
        self.assertEqual(sorted(s["dir"] for s in self.skills), names)
        for s in self.skills:
            card = re.search(r'<article class="skill[^"]*">.*?<code>%s</code>.*?</article>' % re.escape(s["dir"]),
                             self.html, re.S)
            self.assertTrue(card, s["dir"])
            block = card.group(0)
            self.assertIn('<span lang="bg">%s</span>' % s["level"], block)
            self.assertIn('<span lang="en">%s</span>' % build.LEVEL_EN[s["level"]], block)
            self.assertIn('<p lang="bg">', block)
            self.assertIn('<p lang="en">', block)
            self.assertIn("/skills/%s/SKILL.md" % s["dir"], block)

    def test_protocol_and_lessons_from_sources(self):
        with open(os.path.join(build.ROOT, "PROTOCOL.md"), encoding="utf-8") as f:
            rules = build.numbered_list(f.read())
        self.assertEqual(len(rules), 7)
        self.assertIn("<b>Облачна сесия пише, локалната машина изпитва, човек слива.</b>", self.html)
        self.assertIn("A cloud session writes, the local machine tests, a person merges.", self.html)
        self.assertEqual(self.html.count("<ol lang="), 4)

    def test_no_external_resources(self):
        # нищо не се зарежда отвън: без <script src>, без <link rel=stylesheet>, без <img>, без @import/url(http)
        self.assertNotRegex(self.html, r"<script[^>]+src=")
        self.assertNotRegex(self.html, r"<link[^>]+stylesheet")
        self.assertNotRegex(self.html, r"<img\b")
        self.assertNotRegex(self.html, r"url\(\s*['\"]?https?:")
        self.assertNotIn("@import", self.html)
        # външни адреси има само във връзки (href) към изходния код
        for url in re.findall(r"https?://[^\"'<>\s)]+", self.html):
            self.assertTrue(url.startswith(build.REPO_URL), url)

    def test_filled_and_stamped(self):
        self.assertNotRegex(self.html, r"\{\{[A-Z_]+\}\}")
        self.assertIn("2026-09-26 12:00 UTC", self.html)
        self.assertIn("/commit/0123456789abcdef", self.html)
        self.assertIn('href="../3d/"', self.html)
        self.assertIn('href="../"', self.html)


class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_translation_count_must_match(self):
        with open(os.path.join(build.HERE, "en.json"), encoding="utf-8") as f:
            en = json.load(f)
        en["protocol"] = en["protocol"][:-1]
        fake = os.path.join(self.tmp.name, "showcase")
        shutil.copytree(build.HERE, fake, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        with open(os.path.join(fake, "en.json"), "w", encoding="utf-8") as f:
            json.dump(en, f)
        with mock.patch.object(build, "HERE", fake), self.assertRaisesRegex(ValueError, "protocol: 7 .* 6"):
            build.build(os.path.join(self.tmp.name, "out"), now=NOW)

    def test_missing_english_description_falls_back(self):
        html = build.skill_cards([{"dir": "x-y", "level": "действа", "description": "Само **български**.",
                                   "metadata": {}}], build.REPO_URL)
        self.assertIn("(Bulgarian only)", html)
        self.assertIn("<b>български</b>", html)
        self.assertIn('class="skill lvl-act"', html)

    def test_inline_md_escapes(self):
        self.assertEqual(build.inline_md("<script>x</script> **a** `b` [c](d.md)"),
                         '&lt;script&gt;x&lt;/script&gt; <b>a</b> <code>b</code> <a href="d.md">c</a>')

    def test_numbered_list_section(self):
        md = "# T\n1. едно\n## Уроци\n1. а\n2. б\n## Друго\n1. не\n"
        self.assertEqual(build.numbered_list(md, "## Уроци"), ["а", "б"])
        with self.assertRaises(ValueError):
            build.numbered_list(md, "## Липсва")


if __name__ == "__main__":
    unittest.main()
