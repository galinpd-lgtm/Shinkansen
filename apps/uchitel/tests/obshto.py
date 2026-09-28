"""Общо за тестовете: пътища, канонът-пример, пускане на командата и отпечатък на папка. Нула мрежа."""
import contextlib
import copy
import hashlib
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from uchitel import cli  # noqa: E402
from uchitel.kanon import zaredi, znak_data_uri  # noqa: E402

KANON_PAT = os.path.join(APP, "kanon.example.json")
PRIMERI = os.path.join(APP, "primeri", "akademia")
KANON = zaredi(KANON_PAT)
ZNAK = znak_data_uri(KANON)


def kanon():
    return copy.deepcopy(KANON)


def procheti(rel, koren=PRIMERI):
    with open(os.path.join(koren, rel), encoding="utf-8") as f:
        return f.read()


def pusni(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        kod = cli.main(list(argv))
    return kod, out.getvalue(), err.getvalue()


def otpechatak_papka(koren):
    """{относителен път: (sha256, mtime_ns)} за всичко в папката — за „входът не е пипан“."""
    r = {}
    for papka, _pp, imena in os.walk(koren):
        for ime in imena:
            a = os.path.join(papka, ime)
            with open(a, "rb") as f:
                r[os.path.relpath(a, koren)] = (hashlib.sha256(f.read()).hexdigest(), os.stat(a).st_mtime_ns)
    return r


class VremennaPapka:
    """Временна папка с копие на примерите (за тестове, които добавят свои файлове)."""

    def __enter__(self):
        self.koren = tempfile.mkdtemp(prefix="uchitel-test-")
        self.vhod = os.path.join(self.koren, "vhod")
        shutil.copytree(PRIMERI, self.vhod)
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.koren, ignore_errors=True)

    def pat(self, *chasti):
        return os.path.join(self.koren, *chasti)

    def pishi(self, rel, tekst):
        a = os.path.join(self.vhod, rel)
        os.makedirs(os.path.dirname(a), exist_ok=True)
        with open(a, "w", encoding="utf-8", newline="") as f:
            f.write(tekst)
        return a
