"""Тестове без мрежа. Изпитването с двигателя тече само ако има pdfcraft-cli
($PDFCRAFT_CLI или PATH) и reportlab за синтетичния PDF; иначе се пропуска.

    python3 -m unittest discover -s skills/pdf-redact/tests -v

Всички „лични данни“ тук са измислени: ЕГН и ЛНЧ се сглобяват с контролна цифра,
IBAN — с контролни цифри по mod 97; имейлите са на example.org.
"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pdf_redact as pr  # noqa: E402


def make_egn(prefix9):
    w = (2, 4, 8, 5, 10, 9, 7, 3, 6)
    c = sum(int(d) * k for d, k in zip(prefix9, w)) % 11
    return prefix9 + str(0 if c == 10 else c)


def make_lnch(prefix9):
    w = (21, 19, 17, 13, 11, 9, 7, 3, 1)
    return prefix9 + str(sum(int(d) * k for d, k in zip(prefix9, w)) % 10)


def make_iban(bank_part):
    """BG + контролни цифри + 18 знака (4 букви банка + 14)."""
    s = bank_part + "BG00"
    n = int("".join(str(int(ch, 36)) for ch in s))
    return "BG%02d%s" % (98 - n % 97, bank_part)


EGN = make_egn("750101000")          # 01.01.1975 — измислено
EGN_2000 = make_egn("054515000")     # 15.05.2005 (месец +40)
LNCH = make_lnch("100000000")
IBAN = make_iban("TEST00000000000001")


class Validators(unittest.TestCase):
    def test_egn(self):
        self.assertTrue(pr.egn_valid(EGN))
        self.assertTrue(pr.egn_valid(EGN_2000))
        bad = EGN[:9] + str((int(EGN[9]) + 1) % 10)
        self.assertFalse(pr.egn_valid(bad))
        self.assertFalse(pr.egn_valid("7513010000"))     # месец 13
        self.assertFalse(pr.egn_valid("750230000" + "0"))  # 30 февруари
        self.assertFalse(pr.egn_valid("12345"))

    def test_lnch(self):
        self.assertTrue(pr.lnch_valid(LNCH))
        self.assertFalse(pr.lnch_valid(LNCH[:9] + str((int(LNCH[9]) + 1) % 10)))
        self.assertFalse(pr.lnch_valid("0000000000"))

    def test_iban(self):
        self.assertTrue(pr.iban_valid(IBAN))
        spaced = " ".join(IBAN[i:i + 4] for i in range(0, len(IBAN), 4))
        self.assertTrue(pr.iban_valid(spaced))
        self.assertFalse(pr.iban_valid(IBAN[:-1] + ("2" if IBAN[-1] != "2" else "3")))
        self.assertFalse(pr.iban_valid("BG80"))


class Finder(unittest.TestCase):
    TEXT = ("Лице с ЕГН %s, ЛНЧ %s.\nIBAN: %s\nтел. +359 88 123 4567 и 052/123-456, "
            "имейл ivan.test@example.org. Фактура № 1234567890 (без контролна цифра).")

    def test_finds_all_kinds(self):
        found = pr.find_sensitive(self.TEXT % (EGN, LNCH, IBAN), pr.KINDS)
        kinds = [k for k, _ in found]
        self.assertIn(("egn", EGN), found)
        self.assertIn(("lnch", LNCH), found)
        self.assertIn(("iban", IBAN), found)
        self.assertIn(("email", "ivan.test@example.org"), found)
        self.assertEqual(kinds.count("phone"), 2)

    def test_ignores_random_ten_digits(self):
        found = pr.find_sensitive("Фактура № 1234567890", pr.KINDS)
        self.assertEqual([k for k, _ in found if k in ("egn", "lnch")], [])

    def test_only_requested_kinds(self):
        found = pr.find_sensitive(self.TEXT % (EGN, LNCH, IBAN), ["email"])
        self.assertEqual([k for k, _ in found], ["email"])

    def test_no_duplicates(self):
        found = pr.find_sensitive("%s и пак %s" % (EGN, EGN), ["egn"])
        self.assertEqual(found, [("egn", EGN)])


class Geometry(unittest.TestCase):
    def test_rects_in(self):
        r = {"matches": [{"page": 2, "rects": [[1, 2, 3, 4], [5, 6, 7, 8]]}],
             "findings": [{"page": 1, "rect": [0, 0, 1, 1]}]}
        self.assertEqual(pr.rects_in(r), [(2, [1, 2, 3, 4]), (2, [5, 6, 7, 8]), (1, [0, 0, 1, 1])])

    def test_to_top_left(self):
        self.assertEqual(pr.to_top_left([70, 694, 400, 716], 842), [70, 126, 400, 148])
        self.assertEqual(pr.to_top_left([1, 2, 3, 4], None), [1, 2, 3, 4])


class Args(unittest.TestCase):
    def _files(self, d):
        pdf, out = os.path.join(d, "a.pdf"), os.path.join(d, "b.pdf")
        for p in (pdf, out):
            with open(p, "wb") as f:
                f.write(b"x")
        return pdf, out

    def test_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            pdf, out = self._files(d)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                pr.main(["redact", pdf, out])
            self.assertEqual(cm.exception.code, 2)
            with open(out, "rb") as f:
                self.assertEqual(f.read(), b"x")

    def test_refuses_input_as_output(self):
        with tempfile.TemporaryDirectory() as d:
            pdf, _ = self._files(d)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                pr.main(["redact", pdf, pdf, "--force"])
            self.assertEqual(cm.exception.code, 2)

    def test_missing_engine_exit_3(self):
        with tempfile.TemporaryDirectory() as d:
            pdf, _ = self._files(d)
            err = io.StringIO()
            with mock.patch.object(pr, "find_engine", return_value=None), redirect_stderr(err):
                code = pr.main(["audit", pdf])
            self.assertEqual(code, 3)
            self.assertIn("pdfcraft", err.getvalue())


ENGINE = pr.find_engine()
try:
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    FONT = next((p for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                             "/usr/share/fonts/dejavu/DejaVuSans.ttf") if os.path.isfile(p)), None)
    HAVE_PDF = FONT is not None
except ImportError:
    HAVE_PDF = False


@unittest.skipUnless(ENGINE and HAVE_PDF, "няма pdfcraft-cli или reportlab/DejaVu")
class WithEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pdfmetrics.registerFont(TTFont("DJ", FONT))

    def _pdf(self, path, lines, cover_line=None):
        c = canvas.Canvas(path)
        c.setFont("DJ", 12)
        y = 760
        for i, line in enumerate(lines):
            c.drawString(72, y, line)
            if cover_line == i:
                c.setFillColorRGB(0, 0, 0)
                c.rect(70, y - 5, 450, 18, fill=1, stroke=0)
                c.setFillColorRGB(0, 0, 0)
            y -= 24
        c.setAuthor("Измислен Автор")
        c.showPage()
        c.save()

    def _run(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pr.main(["--pdfcraft", ENGINE] + list(args))
        return code, out.getvalue() + err.getvalue()

    def _text(self, path):
        return subprocess.run([ENGINE, "text", path], capture_output=True, text=True).stdout

    def test_redact_bulgarian_data(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "in.pdf"), os.path.join(d, "out.pdf")
            self._pdf(src, ["Заявител: ЕГН %s" % EGN, "Сметка: %s" % IBAN,
                            "Връзка: ivan.test@example.org, +359 88 123 4567",
                            "Фактура № 1234567890 остава."])
            with open(src, "rb") as f:
                before = f.read()
            code, msg = self._run("redact", src, dst)
            self.assertEqual(code, 0, msg)
            with open(src, "rb") as f:
                self.assertEqual(f.read(), before)                  # входът не е пипнат
            t = self._text(dst)
            for secret in (EGN, IBAN, "ivan.test@example.org", "+359881234567"):
                self.assertNotIn(secret, t.replace(" ", ""))
            self.assertIn("Фактура", t)
            self.assertIn("1234567890", t)                          # не е лично — остава
            for secret in (EGN, IBAN, "example.org"):
                self.assertNotIn(secret, msg)                       # данните не излизат на екрана

    def test_audit_flags_and_redact_fixes_faux(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "faux.pdf"), os.path.join(d, "fixed.pdf")
            self._pdf(src, ["Горе: обикновен текст", "Тайно име: Измислен Човек"], cover_line=1)
            code, msg = self._run("audit", src)
            self.assertEqual(code, 4, msg)
            self.assertIn("фалшиво", msg)
            code, msg = self._run("redact", src, dst, "--covered")
            self.assertEqual(code, 0, msg)
            t = self._text(dst)
            self.assertNotIn("Измислен", t)
            self.assertIn("Горе", t)                               # над полето — остава
            code, msg = self._run("audit", dst)
            self.assertNotIn("✗ фалшиво", msg)

    def test_unrequested_faux_box_blocks_output(self):
        """Фалшиво поле, което не е заявено (без --covered) — изходът не се записва."""
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "mix.pdf"), os.path.join(d, "out.pdf")
            self._pdf(src, ["ЕГН %s" % EGN, "Скрито: Измислен Човек"], cover_line=1)
            code, msg = self._run("redact", src, dst, "--egn")
            self.assertEqual(code, 1, msg)
            self.assertFalse(os.path.exists(dst))
            self.assertIn("НЕ мина", msg)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "in.pdf"), os.path.join(d, "out.pdf")
            self._pdf(src, ["ЕГН %s" % EGN])
            code, msg = self._run("redact", src, dst, "--dry-run")
            self.assertEqual(code, 4, msg)
            self.assertFalse(os.path.exists(dst))
            self.assertIn("ЕГН × 1", msg)

    def test_find_words(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "in.pdf"), os.path.join(d, "out.pdf")
            self._pdf(src, ["Договор с Примерна Фирма ЕООД", "Варна"])
            code, msg = self._run("redact", src, dst, "--find", "Примерна Фирма")
            self.assertEqual(code, 0, msg)
            t = self._text(dst)
            self.assertNotIn("Примерна", t)
            self.assertIn("Варна", t)


if __name__ == "__main__":
    unittest.main()
