"""Тестове без мрежа. Рендерът се изпитва само ако има pymupdf и Pillow; иначе се пропуска.

    python3 -m unittest discover -s skills/pdf-contact-sheet/tests -v
"""
import builtins
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pdf_contact_sheet as pcs  # noqa: E402

try:
    import pymupdf  # noqa: F401
    from PIL import Image  # noqa: F401
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


class Layout(unittest.TestCase):
    def test_grid(self):
        self.assertEqual(pcs.grid_layout(0), (0, 0))
        self.assertEqual(pcs.grid_layout(1), (1, 1))
        self.assertEqual(pcs.grid_layout(12, cols=4), (4, 3))
        self.assertEqual(pcs.grid_layout(3, cols=10), (3, 1))
        cols, rows = pcs.grid_layout(11)
        self.assertGreaterEqual(cols * rows, 11)
        self.assertGreater(cols, rows)                 # широка мрежа за екран
        cols, rows = pcs.grid_layout(200)
        self.assertLess(cols * rows - 200, cols)       # без празен последен ред

    def test_cell_origin(self):
        self.assertEqual(pcs.cell_origin(0, 3, 100, 150), (pcs.PAD, pcs.PAD))
        self.assertEqual(pcs.cell_origin(4, 3, 100, 150),
                         (pcs.PAD + 110, pcs.PAD + 160))


class MissingDeps(unittest.TestCase):
    def test_clear_error_exit_3(self):
        real = builtins.__import__

        def fake(name, *a, **k):
            if name in ("pymupdf", "fitz", "PIL") or name.startswith("PIL."):
                raise ImportError(name)
            return real(name, *a, **k)
        err = io.StringIO()
        with mock.patch("builtins.__import__", fake), redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                pcs.load_deps()
        self.assertEqual(cm.exception.code, 3)
        self.assertIn("pip install pymupdf pillow", err.getvalue())


class Args(unittest.TestCase):
    def test_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "a.pdf")
            out = os.path.join(d, "a.png")
            for p in (pdf, out):
                with open(p, "wb") as f:
                    f.write(b"x")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                pcs.main([pdf, out])
            self.assertEqual(cm.exception.code, 2)
            with open(out, "rb") as f:
                self.assertEqual(f.read(), b"x")


@unittest.skipUnless(HAVE_DEPS, "няма pymupdf/Pillow")
class Render(unittest.TestCase):
    def test_sheet(self):
        import pymupdf
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            doc = pymupdf.open()
            for i in range(5):
                doc.new_page(width=200, height=300)
            doc.new_page(width=300, height=200)     # хоризонтална
            doc.save(pdf)
            out = os.path.join(d, "s.png")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(pcs.main([pdf, out, "--cols", "3", "--thumb", "100"]), 0)
            img = Image.open(out)
            cell_h = 150 + pcs.LABEL_H
            self.assertEqual(img.size, (pcs.PAD + 3 * (100 + pcs.PAD), pcs.PAD + 2 * (cell_h + pcs.PAD)))
            info = pcs.build(pdf, out, max_pages=2, thumb=100)
            self.assertEqual((info["pages"], info["shown"]), (6, 2))


if __name__ == "__main__":
    unittest.main()
