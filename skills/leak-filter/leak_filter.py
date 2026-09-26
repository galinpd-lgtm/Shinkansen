#!/usr/bin/env python3
"""leak-filter — търси изтичания в папка и в ЦЯЛАТА git история. Никога не поправя сам.

    leak_filter.py [ПАПКА] [--words ФАЙЛ] [--no-history] [--json]

Търси: IP адреси (без документационните и локалните), домашни пътища, ключове и
токени, плюс думи от списък във файл ИЗВЪН репото (едно на ред, # за коментар).

В историята се четат всички добавени редове от всички commit-и във всички клонове
(`git log --all -p`) — изтрито в по-нов commit пак е публично, ако е било качено.

Ред, който съдържа „leak-filter: ignore“, се пропуска (за нарочни примери).
Код на изход: 0 — чисто · 4 — има находки · 2 — грешна употреба.
"""
import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys

IGNORE_MARK = "leak-filter: ignore"
MAX_FILE_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "_site", "out"}

# Адреси, които не са изтичане: документационни, локални, служебни
SAFE_NETS = [ipaddress.ip_network(n) for n in (
    "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24",   # документация (RFC 5737)
    "127.0.0.0/8", "0.0.0.0/32", "255.255.255.255/32",
)]
# Домашни папки-заместители, които не издават човек
SAFE_HOMES = {"user", "username", "you", "your-name", "yourname", "me", "example", "runner", "name"}

IPV4 = re.compile(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(?![\d.]*\d)")
HOME = re.compile(r"(?:/home/|/Users/|[A-Za-z]:\\\\?Users\\\\?)([A-Za-z0-9._-]+)")
SECRETS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY")),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("url-password", re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]{3,}@")),
    ("assigned-secret", re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|token)\b"
        r"\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']")),
]


def write_summary(text):
    path = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def mask(s):
    """Показва само началото на намереното — отчетът сам не бива да изтича."""
    s = s.strip()
    return s if len(s) <= 6 else s[:4] + "…" + "*" * min(6, len(s) - 4)


def load_words(path):
    words = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            w = line.split("#", 1)[0].strip()
            if w:
                words.append(w)
    return words


def compile_words(words):
    if not words:
        return None
    # граници на дума и за кирилица: не буква/цифра от двете страни
    alt = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))
    return re.compile(r"(?<![\w])(?:%s)(?![\w])" % alt, re.I)


def scan_line(line, words_rx=None):
    """Един ред → [(вид, намерено)]."""
    if IGNORE_MARK in line:
        return []
    hits = []
    for m in IPV4.finditer(line):
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue                      # 999.1.1.1 — не е адрес (напр. версия)
        if not any(ip in n for n in SAFE_NETS):
            hits.append(("ip", m.group(1)))
    for m in HOME.finditer(line):
        if m.group(1).lower() not in SAFE_HOMES and not m.group(1).startswith("$"):
            hits.append(("home-path", m.group(0)))
    for kind, rx in SECRETS:
        for m in rx.finditer(line):
            hits.append((kind, m.group(0)))
    if words_rx:
        for m in words_rx.finditer(line):
            hits.append(("word", m.group(0)))
    return hits


def is_binary(data):
    return b"\0" in data[:8192]


def scan_tree(root, words_rx=None):
    """Текущите файлове в папката. → [{"where": "tree", "file", "line", "kind", "match"}]."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            path = os.path.join(dirpath, fn)
            try:
                if os.path.islink(path) or os.path.getsize(path) > MAX_FILE_BYTES:
                    continue
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if is_binary(data):
                continue
            rel = os.path.relpath(path, root)
            for no, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
                for kind, match in scan_line(line, words_rx):
                    found.append({"where": "tree", "file": rel, "line": no, "kind": kind,
                                  "match": mask(match) if kind not in ("home-path",) else match})
    return found


def git_root(path):
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def parse_git_log(text, words_rx=None):
    """Изход от `git log --all -p -U0 --format=@@commit %H` → находки в добавените редове."""
    found = []
    commit = path = None
    line_no = 0
    for raw in text.splitlines():
        if raw.startswith("@@commit "):
            commit = raw.split()[1][:12]
            path = None
            continue
        if raw.startswith("+++ "):
            p = raw[4:]
            path = None if p == "/dev/null" else re.sub(r"^b/", "", p)
            continue
        if raw.startswith("@@ "):
            m = re.match(r"^@@ -\S+ \+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++") and path:
            for kind, match in scan_line(raw[1:], words_rx):
                found.append({"where": "history", "commit": commit, "file": path, "line": line_no,
                              "kind": kind, "match": mask(match) if kind != "home-path" else match})
            line_no += 1
    return found


def scan_history(repo, words_rx=None):
    r = subprocess.run(["git", "-C", repo, "log", "--all", "-p", "-U0", "--no-color", "--no-ext-diff",
                        "--no-renames", "--format=@@commit %H"],
                       capture_output=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError("git log: " + r.stderr.decode("utf-8", "replace").strip())
    return parse_git_log(r.stdout.decode("utf-8", "replace"), words_rx)


def dedupe_history(hist):
    """Една находка (файл, вид, намерено) се показва веднъж — с най-стария commit, в който е влязла."""
    seen = {}
    for h in hist:                      # git log е от новия към стария → последният е най-старият
        seen[(h["file"], h["kind"], h["match"])] = h
    return sorted(seen.values(), key=lambda h: (h["file"], h["line"]))


def inside(child, parent):
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    return child == parent or child.startswith(parent + os.sep)


def report(tree, hist, warnings):
    lines = []
    for w in warnings:
        lines.append("! " + w)
    for f in tree:
        lines.append("%s:%d  %-15s %s" % (f["file"], f["line"], f["kind"], f["match"]))
    for f in hist:
        lines.append("%s:%d  %-15s %s  (история, commit %s)" % (
            f["file"], f["line"], f["kind"], f["match"], f["commit"]))
    if tree or hist:
        lines.append("НАМЕРЕНО: %d в папката, %d в историята. Нищо не е поправено." % (len(tree), len(hist)))
    else:
        lines.append("ЧИСТО.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Търси изтичания в папка и в цялата git история.")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--words", help="файл с думи (извън репото), по една на ред")
    ap.add_argument("--no-history", action="store_true", help="без git историята")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.path):
        ap.error("няма такава папка")
    warnings = []
    words_rx = None
    if a.words:
        if not os.path.isfile(a.words):
            ap.error("няма файл с думи")
        words_rx = compile_words(load_words(a.words))
        repo = git_root(a.path) or a.path
        if inside(a.words, repo):
            warnings.append("списъкът с думи е вътре в репото — сам е изтичане; дръж го извън него")
    tree = scan_tree(a.path, words_rx)
    hist = []
    repo = git_root(a.path)
    if not a.no_history:
        if repo:
            hist = dedupe_history(scan_history(repo, words_rx))
        else:
            warnings.append("не е git хранилище — историята не е проверена")
    if a.json:
        print(json.dumps({"clean": not (tree or hist), "tree": tree, "history": hist,
                          "warnings": warnings}, ensure_ascii=False, indent=2))
    else:
        print(report(tree, hist, warnings))
    write_summary("чисто" if not (tree or hist) else "намерено: %d папка, %d история" % (len(tree), len(hist)))
    return 4 if (tree or hist) else 0


if __name__ == "__main__":
    sys.exit(main())
