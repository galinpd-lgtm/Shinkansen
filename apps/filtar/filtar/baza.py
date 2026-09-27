"""SQLite: записите, дневникът на филтъра (firewall_log) и състоянието на източниците."""
import json
import os
import sqlite3

SHEMA = """
CREATE TABLE IF NOT EXISTS zapisi (
    id INTEGER PRIMARY KEY,
    izvor TEXT NOT NULL,            -- id от регистъра или „ruchno:<име>“
    izvor_ime TEXT, izvor_vid TEXT, izvor_url TEXT, ezik TEXT,
    kluch TEXT UNIQUE NOT NULL,     -- източник + guid/адрес: събирачът пише само новото
    url TEXT, url_kanon TEXT, url_hash TEXT,
    zaglavie TEXT, tekst TEXT, data TEXT, sha256 TEXT,   -- копие: SHA-256 на заглавие+текст
    sabrano TEXT, http_status INTEGER, tip TEXT,
    sastoyanie TEXT NOT NULL DEFAULT 'nov',   -- nov → obraboten
    reshenie TEXT, sloy INTEGER, prichina TEXT,
    barza REAL, ocenka REAL, po_dumi TEXT, doverie TEXT,
    rubrika INTEGER, organizacii TEXT, temi TEXT, shingli TEXT,
    obraboteno TEXT, odobren TEXT
);
CREATE INDEX IF NOT EXISTS zapisi_hash ON zapisi(url_hash);
CREATE INDEX IF NOT EXISTS zapisi_sast ON zapisi(sastoyanie);
CREATE TABLE IF NOT EXISTS firewall_log (
    id INTEGER PRIMARY KEY,
    vreme TEXT NOT NULL,
    zapis_id INTEGER, izvor TEXT,
    sloy INTEGER NOT NULL,          -- 0 = събиране (копия, отказано извличане), 1–7 = слоевете
    reshenie TEXT NOT NULL, prichina TEXT NOT NULL, ocenka REAL
);
CREATE TABLE IF NOT EXISTS izvori (
    id TEXT PRIMARY KEY,
    ime TEXT, vid TEXT,
    rep_score REAL NOT NULL,
    preizchislena TEXT, posleden_opit TEXT, posledno_sastoyanie TEXT
);
"""


def otvori(papka):
    os.makedirs(papka, exist_ok=True)
    b = sqlite3.connect(os.path.join(papka, "filtar.sqlite"))
    b.row_factory = sqlite3.Row
    b.executescript(SHEMA)
    return b


def log(b, vreme, sloy, reshenie, prichina, zapis_id=None, izvor=None, ocenka=None):
    b.execute("INSERT INTO firewall_log (vreme, zapis_id, izvor, sloy, reshenie, prichina, ocenka) "
              "VALUES (?,?,?,?,?,?,?)", (vreme, zapis_id, izvor, sloy, reshenie, prichina, ocenka))


def izvor(b, izvor_id, ime=None, vid=None, nachalna=5.0):
    """Редът на източника; създава го с неутралната начална репутация („на никой не вярвам“)."""
    r = b.execute("SELECT * FROM izvori WHERE id=?", (izvor_id,)).fetchone()
    if r is None:
        b.execute("INSERT INTO izvori (id, ime, vid, rep_score) VALUES (?,?,?,?)", (izvor_id, ime, vid, nachalna))
        r = b.execute("SELECT * FROM izvori WHERE id=?", (izvor_id,)).fetchone()
    return r


def jd(x):
    return json.dumps(x, ensure_ascii=False) if x is not None else None


def jl(s, po_podrazbirane=None):
    return json.loads(s) if s else po_podrazbirane
