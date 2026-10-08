"""Общо за тестовете: пътищата, config-ът от примера, измислената база и пускане на main(). Нула мрежа.

Всички адреси са на example.com, example.org и example.net. Ключът за подписване е измислен и е само тук.
"""
import contextlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
CFG_PAT = os.path.join(APP, "config.example.json")
sys.path.insert(0, APP)

from misii import cli, config  # noqa: E402

CFG = config.zaredi(CFG_PAT)
DATA = "2026-10-09"
RAYON = "primer-grad-centar"
KLYUCH = "izmislen-klyuch-samo-za-testovete-0123456789"  # leak-filter: ignore


def fix(ime):
    with open(os.path.join(FIX, ime), encoding="utf-8") as f:
        return json.load(f)


def hod(komanda, *argv):
    """Пуска main() с config-а от примера → (код, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        kod = cli.main([komanda, "--config", CFG_PAT] + list(argv))
    return kod, out.getvalue(), err.getvalue()
