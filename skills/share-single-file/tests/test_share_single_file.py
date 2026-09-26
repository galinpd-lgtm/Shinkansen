"""Тестове без мрежа. esbuild се подменя с прост „сглобяч“; истинският се ползва само ако е наличен.

    python3 -m unittest discover -s skills/share-single-file/tests -v
"""
import base64
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import share_single_file as ssf  # noqa: E402


def fake_bundle(path, kind):
    with open(path, encoding="utf-8") as f:
        return "/*%s*/%s" % (kind, f.read())


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="css/site.css">
<link rel="icon" href="icon.png">
<link rel="stylesheet" href="https://fonts.example.org/x.css">
<script src="js/classic.js"></script>
<script defer src="js/late.js"></script>
<script type="module" src="js/app.js"></script>
<script src="https://cdn.example.org/lib.js"></script>
<script src="missing.js"></script>
</head><body><img alt="logo" src="img/logo.png"><x-view src="venue.json"></x-view></body></html>
"""


class Assemble(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = self.root = os.path.join(self.tmp.name, "site")
        write(os.path.join(r, "index.html"), PAGE)
        write(os.path.join(r, "css/site.css"), "body{color:red}")
        write(os.path.join(r, "icon.png"), b"\x89PNG-icon")
        write(os.path.join(r, "img/logo.png"), b"\x89PNG-logo")
        write(os.path.join(r, "js/classic.js"), "console.log('</script> inside');")
        write(os.path.join(r, "js/late.js"), "window.late=1;")
        write(os.path.join(r, "js/app.js"), "fetch('data/points.csv');")
        write(os.path.join(r, "data/points.csv"), "a,b\n1,2\n")
        write(os.path.join(r, "venue.json"), json.dumps({"model": "model.glb", "other": "../secret.json"}))
        write(os.path.join(r, "model.glb"), b"glTF\x02\x00")
        write(os.path.join(self.tmp.name, "secret.json"), "{}")     # извън папката — не се вгражда
        self.html, self.info = ssf.assemble(os.path.join(r, "index.html"), fake_bundle)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scripts_and_styles_inlined(self):
        h = self.html
        self.assertIn("<style>/*css*/body{color:red}</style>", h)
        self.assertIn("<script>/*iife*/console.log('<\\/script> inside');</script>", h)
        self.assertIn('<script type="module">/*iife*/window.late=1;</script>', h)   # defer → модул
        self.assertIn('<script type="module">/*esm*/fetch(', h)
        self.assertIn('https://cdn.example.org/lib.js', h)            # външното остава
        self.assertIn('https://fonts.example.org/x.css', h)
        self.assertIn('src="missing.js"', h)                          # липсващото остава както е
        self.assertEqual(sorted(self.info["scripts"]), ["js/app.js", "js/classic.js", "js/late.js"])

    def test_assets_as_data_uri(self):
        self.assertIn('href="data:image/png;base64,' + base64.b64encode(b"\x89PNG-icon").decode(), self.html)
        self.assertIn('src="data:image/png;base64,' + base64.b64encode(b"\x89PNG-logo").decode(), self.html)

    def test_data_found_through_chain_and_root_only(self):
        self.assertEqual(sorted(self.info["data"]), ["data/points.csv", "model.glb", "venue.json"])
        shim = re.search(r"const F=(\{.*?\}),M=", self.html).group(1)
        files = json.loads(shim)
        self.assertEqual(base64.b64decode(files["model.glb"][1]), b"glTF\x02\x00")
        self.assertEqual(files["model.glb"][0], "model/gltf-binary")
        self.assertNotIn("secret.json", shim)
        # шимът е първото нещо в <head>, преди всички скриптове
        self.assertLess(self.html.index("share-single-file: вградени данни"), self.html.index("/*iife*/"))


class Helpers(unittest.TestCase):
    def test_attrs_and_local(self):
        self.assertEqual(ssf.parse_attrs(' type="module" src=\'a.js\' defer data-x=1'),
                         {"type": "module", "src": "a.js", "defer": None, "data-x": "1"})
        for url in ("https://x.org/a.js", "//x.org/a.js", "data:text/plain,a", "#top", "mailto:a@b"):
            self.assertFalse(ssf.is_local(url), url)
        self.assertTrue(ssf.is_local("js/a.js"))

    def test_resolve_stays_inside_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "site")
            write(os.path.join(root, "a.json"), "{}")
            write(os.path.join(d, "outside.json"), "{}")
            self.assertEqual(ssf.resolve(root, root, "a.json?v=2"), os.path.realpath(os.path.join(root, "a.json")))
            self.assertIsNone(ssf.resolve(root, root, "../outside.json"))
            self.assertIsNone(ssf.resolve(root, root, "nope.json"))


class Main(unittest.TestCase):
    def test_missing_esbuild_exit_3(self):
        with tempfile.TemporaryDirectory() as d:
            page = os.path.join(d, "index.html")
            write(page, "<html><head></head></html>")
            err = io.StringIO()
            with mock.patch.dict(os.environ, {"SHINKANSEN_ESBUILD": os.path.join(d, "none")}), \
                    redirect_stderr(err):
                self.assertEqual(ssf.main([page, os.path.join(d, "out.html")]), 3)
            self.assertIn("липсва esbuild", err.getvalue())
            self.assertFalse(os.path.exists(os.path.join(d, "out.html")))

    def test_writes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            page = os.path.join(d, "index.html")
            write(page, "<html><head></head><body></body></html>")
            out = os.path.join(d, "out.html")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(ssf.main([page, out], bundler=fake_bundle), 0)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                ssf.main([page, out], bundler=fake_bundle)


@unittest.skipUnless(ssf.find_esbuild(), "няма esbuild")
class RealEsbuild(unittest.TestCase):
    def test_bundles_imports(self):
        with tempfile.TemporaryDirectory() as d:
            write(os.path.join(d, "index.html"),
                  '<html><head><script type="module" src="main.js"></script></head></html>')
            write(os.path.join(d, "main.js"), "import {x} from './dep.js'; document.title = x;")
            write(os.path.join(d, "dep.js"), "export const x = 'from-dep';")
            html, info = ssf.assemble(os.path.join(d, "index.html"), ssf.make_bundler(ssf.find_esbuild()))
            self.assertIn("from-dep", html)
            self.assertNotIn("./dep.js", html)


if __name__ == "__main__":
    unittest.main()
