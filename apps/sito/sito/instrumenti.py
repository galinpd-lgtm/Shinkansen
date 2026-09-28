"""Външните инструменти: всеки се открива с shutil.which. Липсата им е причина за „неясно“, не грешка.

Никаква облачна услуга: всичко тук се пуска локално, на същата машина.
"""
import os
import shutil
import subprocess
import time

IMENA = ("pdftotext", "pdfinfo", "pdftoppm", "tesseract", "soffice", "qpdf", "gs")


class Neyasno(Exception):
    """Файлът не може да се прочете: няма конвертор, криптиран, повреден, над тавана. Причината е текстът."""


def nameri(ime):
    return shutil.which(ime)


def nalichni(cfg):
    n = {i: bool(nameri(i)) for i in IMENA}
    n["whisper"] = bool(nameri(cfg["whisper"]["komanda"]))
    return n


def ostava(rok):
    return max(1.0, rok - time.monotonic())


def proveri_rok(rok):
    if time.monotonic() > rok:
        raise Neyasno("над тавана за време на файл")


def pusni(argumenti, rok, cwd=None, env=None):
    """Пуска локален инструмент с таван за време. Връща stdout (bytes). Грешка → Neyasno с причина."""
    try:
        r = subprocess.run(argumenti, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                           timeout=ostava(rok), env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Neyasno("%s: над тавана за време на файл" % os.path.basename(argumenti[0]))
    except OSError as e:
        raise Neyasno("%s: %s" % (os.path.basename(argumenti[0]), e))
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise Neyasno("%s: код %d%s" % (os.path.basename(argumenti[0]), r.returncode,
                                        (" — " + err[-1][:200]) if err else ""))
    return r.stdout
