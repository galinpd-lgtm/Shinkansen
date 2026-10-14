#!/usr/bin/env python3
"""pdf-redact — истинско заличаване на лични данни в PDF и одит за фалшиво заличаване.

    pdf_redact.py audit  ВХОД.pdf [--json] [--pdfcraft ПЪТ]
    pdf_redact.py redact ВХОД.pdf ИЗХОД.pdf [--egn] [--lnch] [--iban] [--phone] [--email]
                         [--covered] [--find ТЕКСТ]… [--words-file ФАЙЛ] [--keep-hidden]
                         [--dry-run] [--force] [--pdfcraft ПЪТ]

Двигателят е PdfCraft (`pdfcraft-cli mcp`, Apache-2.0/MIT, github.com/storytold/pdfcraft):
той маха съдържанието под отметките за постоянно и сам проверява, че нищо не е останало.
Този помощник намира българските данни (ЕГН и ЛНЧ с контролна цифра, IBAN с mod 97,
телефони, имейли), подава ги на двигателя и проверява изхода отново.

Пазене: входът само се чете; изходът е нов файл и се записва САМО ако повторната проверка
мине. На екрана и в дневника — само бройки и страници, никога самите данни.
Само стандартна библиотека на Python 3 (+ pdfcraft-cli).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

EXIT_FAIL, EXIT_USAGE, EXIT_MISSING, EXIT_FINDINGS = 1, 2, 3, 4
ENGINE_URL = "https://getartcraft.com/apps/pdfcraft"
HIDDEN_ALL = ["metadata", "attachments", "comments", "form-fields", "hidden-text",
              "hidden-layers", "bookmarks", "links-actions-scripts", "private-data"]
KINDS = ("egn", "lnch", "iban", "phone", "email")
KIND_BG = {"egn": "ЕГН", "lnch": "ЛНЧ", "iban": "IBAN", "phone": "телефон", "email": "имейл",
           "find": "зададен текст", "covered": "покрит текст"}


def write_summary(text):
    path = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


# ---------- разпознаване (чиста логика, без двигател) ----------

def egn_valid(s):
    """ЕГН: 10 цифри, истинска дата (месец +20 за 1800-те, +40 за 2000-те), контролна цифра."""
    if not re.fullmatch(r"\d{10}", s):
        return False
    yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
    if 1 <= mm <= 12:
        year = 1900 + yy
    elif 21 <= mm <= 32:
        year, mm = 1800 + yy, mm - 20
    elif 41 <= mm <= 52:
        year, mm = 2000 + yy, mm - 40
    else:
        return False
    days = [31, 29 if (year % 4 == 0 and (year % 100 or year % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mm - 1]
    if not 1 <= dd <= days:
        return False
    w = (2, 4, 8, 5, 10, 9, 7, 3, 6)
    c = sum(int(d) * k for d, k in zip(s, w)) % 11
    return (0 if c == 10 else c) == int(s[9])


def lnch_valid(s):
    """ЛНЧ: 10 цифри, тегла 21,19,17,13,11,9,7,3,1, mod 10."""
    if not re.fullmatch(r"\d{10}", s) or len(set(s)) == 1:     # 0000000000 и пр. — не
        return False
    w = (21, 19, 17, 13, 11, 9, 7, 3, 1)
    return sum(int(d) * k for d, k in zip(s, w)) % 10 == int(s[9])


def iban_valid(s):
    s = re.sub(r"\s+", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    if s.startswith("BG") and len(s) != 22:
        return False
    n = "".join(str(int(ch, 36)) for ch in s[4:] + s[:4])
    return int(n) % 97 == 1


RE_TEN = re.compile(r"(?<![\d])\d{10}(?![\d])")
RE_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Български телефони: +359 / 00359 / 0, после 8–9 цифри с интервали, тирета, точки или скоби.
RE_PHONE = re.compile(r"(?<![\w+])(?:\+359|00359|0)[\s\-./()]*[2-9](?:[\s\-./()]*\d){7,8}(?!\d)")


def find_sensitive(text, kinds):
    """→ [(вид, низ)] — всяко съвпадение в текста, без повторения, по реда на поява."""
    out, seen = [], set()

    def add(kind, s):
        if (kind, s) not in seen:
            seen.add((kind, s))
            out.append((kind, s))
    if "egn" in kinds or "lnch" in kinds:
        for m in RE_TEN.finditer(text):
            s = m.group(0)
            if "egn" in kinds and egn_valid(s):
                add("egn", s)
            elif "lnch" in kinds and lnch_valid(s):
                add("lnch", s)
    if "iban" in kinds:
        for m in RE_IBAN.finditer(text):
            if iban_valid(m.group(0)):
                add("iban", m.group(0))
    if "email" in kinds:
        for m in RE_EMAIL.finditer(text):
            add("email", m.group(0))
    if "phone" in kinds:
        for m in RE_PHONE.finditer(text):
            add("phone", m.group(0).strip())
    return out


def norm(s):
    return re.sub(r"\s+", "", s).lower()


# ---------- двигателят: pdfcraft-cli mcp ----------

class EngineError(Exception):
    pass


def find_engine(explicit=None):
    for c in (explicit, os.environ.get("PDFCRAFT_CLI"), shutil.which("pdfcraft-cli")):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


class Engine:
    """Минимален MCP клиент по stdio към `pdfcraft-cli mcp`."""

    def __init__(self, exe, root, timeout=180):
        self.p = subprocess.Popen([exe, "mcp", "--root", root], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                  encoding="utf-8")
        self.n = 0
        self._timer = threading.Timer(timeout, self.p.kill)
        self._timer.daemon = True
        self._timer.start()
        self._req("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "shinkansen-pdf-redact", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        try:
            self.p.stdin.write(json.dumps(msg) + "\n")
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):
            raise EngineError("двигателят спря")

    def _req(self, method, params):
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise EngineError("двигателят спря (или изтече времето)")
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("id") == self.n:
                if "error" in r:
                    raise EngineError("%s: %s" % (method, r["error"].get("message")))
                return r.get("result")

    def call(self, tool, **args):
        res = self._req("tools/call", {"name": tool, "arguments": args}) or {}
        txt = "".join(c.get("text", "") for c in res.get("content", []) if isinstance(c, dict))
        if res.get("isError"):
            raise EngineError("%s: %s" % (tool, txt[:300]))
        if "structuredContent" in res:
            return res["structuredContent"]
        try:
            return json.loads(txt)
        except ValueError:
            return txt

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=20)
            self.p.stdout.close()
        except Exception:
            self.p.kill()
        self._timer.cancel()


def page_texts(eng, doc, pages):
    """→ {страница: текст}. text_extract връща текста на страниците, разделени с form feed."""
    out = {}
    for i in range(1, pages + 1):
        r = eng.call("text_extract", doc=doc, pages=[i])
        if isinstance(r, dict):
            t = r.get("text")
            if t is None and isinstance(r.get("pages"), list) and r["pages"]:
                t = r["pages"][0].get("text", "")
        else:
            t = r
        out[i] = t or ""
    return out


def inspect(eng, path):
    """Одит на един файл → dict с находките (без данни от съдържанието, освен броя)."""
    d = eng.call("doc_open", path=path)
    doc, pages = d["doc"], d.get("pages", 0)
    audit = eng.call("doc_audit_redactions", doc=doc)
    hidden = eng.call("doc_hidden_info", doc=doc)
    texts = page_texts(eng, doc, pages)
    return doc, pages, audit, hidden, texts


def hidden_counts(hidden):
    """doc_hidden_info → {категория: брой>0}; приема и списък, и речник."""
    out = {}
    items = hidden.get("categories", hidden) if isinstance(hidden, dict) else hidden
    if isinstance(items, dict):
        for k, v in items.items():
            n = v.get("count", 0) if isinstance(v, dict) else v
            if isinstance(n, int) and n > 0:
                out[k] = n
    elif isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and it.get("count", 0) > 0:
                out[it.get("category") or it.get("name")] = it["count"]
    return out


def textless(texts):
    return [p for p, t in texts.items() if not t.strip()]


# ---------- команди ----------

def cmd_audit(a, exe):
    root = os.path.dirname(os.path.abspath(a.pdf))
    eng = Engine(exe, root)
    try:
        _, pages, audit, hidden, texts = inspect(eng, os.path.abspath(a.pdf))
    finally:
        eng.close()
    findings = audit.get("findings", []) if isinstance(audit, dict) else []
    kinds = {}
    for f in findings:
        kinds.setdefault(f.get("kind", "?"), []).append(f.get("page"))
    found = find_sensitive("\n".join(texts.values()), KINDS)
    per = {}
    for k, _ in found:
        per[k] = per.get(k, 0) + 1
    rep = {"file": os.path.basename(a.pdf), "pages": pages,
           "faux_redactions": {k: sorted(set(v)) for k, v in kinds.items()},
           "sensitive_counts": per, "hidden": hidden_counts(hidden),
           "pages_without_text": textless(texts)}
    bad = bool(findings or per or rep["pages_without_text"])
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("%s: %d стр." % (rep["file"], pages))
        if kinds:
            for k, v in rep["faux_redactions"].items():
                print("  ✗ фалшиво заличаване (%s): стр. %s" % (k, ", ".join(map(str, v))))
        else:
            print("  ✓ няма фалшиво заличаване")
        if per:
            print("  ✗ четими лични данни: " + ", ".join("%s × %d" % (KIND_BG[k], n) for k, n in per.items()))
        else:
            print("  ✓ няма четими ЕГН/ЛНЧ/IBAN/телефони/имейли")
        if rep["hidden"]:
            print("  • скрита информация: " + ", ".join("%s × %d" % kv for kv in rep["hidden"].items()))
        if rep["pages_without_text"]:
            print("  ! без текстов слой (скан?) — търсенето е сляпо, гледай на око: стр. %s"
                  % ", ".join(map(str, rep["pages_without_text"])))
    write_summary("%d стр. · фалшиви %d · данни %d · без текст %d" % (
        pages, len(findings), sum(per.values()), len(rep["pages_without_text"])))
    return EXIT_FINDINGS if bad else 0


def cmd_redact(a, exe):
    kinds = [k for k in KINDS if getattr(a, k)]
    words = list(a.find or [])
    if a.words_file:
        with open(a.words_file, encoding="utf-8") as f:
            words += [w.strip() for w in f if w.strip() and not w.startswith("#")]
    covered = a.covered
    if not kinds and not words and not covered:      # нищо зададено → всичко българско
        kinds, covered = list(KINDS), True

    src = os.path.abspath(a.pdf)
    tmpdir = tempfile.mkdtemp(prefix="_pdf_redact_")
    work = os.path.join(tmpdir, "work.pdf")
    shutil.copyfile(src, work)
    out_tmp = os.path.join(tmpdir, "out.pdf")
    eng = Engine(exe, tmpdir)
    try:
        d = eng.call("doc_open", path=work)
        doc, pages = d["doc"], d.get("pages", 0)
        removed = {}
        if not a.keep_hidden:
            removed = hidden_counts(eng.call("doc_hidden_info", doc=doc))
            eng.call("doc_remove_hidden", doc=doc, categories=HIDDEN_ALL)
        texts = page_texts(eng, doc, pages)         # след изравняване на формите
        found = find_sensitive("\n".join(texts.values()), kinds)
        marks = {}
        targets = [s for _, s in found] + words
        for k, _ in found:
            marks[k] = marks.get(k, 0) + 1
        if words:
            marks["find"] = len(words)
        boxes = []                                   # (стр., [x0,y0,x1,y1] горе-вляво)
        for t in set(targets):
            boxes += rects_in(eng.call("text_find", doc=doc, query=t, limit=500))
        cov_pages = []
        if covered:
            audit = eng.call("doc_audit_redactions", doc=doc)
            for f in audit.get("findings", []):
                if f.get("kind") == "covered-text" and f.get("rect") and f.get("page"):
                    cov_pages.append(f["page"])
                    box = to_top_left(f["rect"], page_height(eng, doc, f["page"]))
                    boxes.append((f["page"], box))
                    eng.call("redact_mark", doc=doc, page=f["page"], rect=box)
            if cov_pages:
                marks["covered"] = len(cov_pages)
        if targets:
            eng.call("redact_mark", doc=doc, words=sorted(set(targets), key=len, reverse=True))
        summary = ", ".join("%s × %d" % (KIND_BG[k], n) for k, n in marks.items()) or "нищо"
        if a.dry_run:
            print("суха проба: %s · %d стр. · за заличаване: %s" % (os.path.basename(src), pages, summary))
            if removed:
                print("  скрита информация за махане: " + ", ".join("%s × %d" % kv for kv in removed.items()))
            write_summary("суха проба · " + summary)
            return EXIT_FINDINGS if marks else 0
        if marks:
            eng.call("redact_apply", doc=doc)
        eng.call("doc_save", doc=doc, path=out_tmp, full=True)

        # повторна проверка върху записания файл
        d2 = eng.call("doc_open", path=out_tmp)
        texts2 = page_texts(eng, d2["doc"], d2.get("pages", 0))
        left_text = norm("\n".join(texts2.values()))
        leaks = [t for t in targets if norm(t) and norm(t) in left_text]
        again = find_sensitive("\n".join(texts2.values()), kinds)
        audit2 = eng.call("doc_audit_redactions", doc=d2["doc"])
        faux2 = [f for f in audit2.get("findings", [])
                 if not ours(f, boxes, page_height(eng, d2["doc"], f.get("page") or 1))]
    finally:
        eng.close()

    if leaks or again or faux2:
        print("✗ проверката след заличаване НЕ мина — изход не е записан "
              "(остават: зададени %d, разпознати %d, фалшиви полета %d)"
              % (len(leaks), len(again), len(faux2)), file=sys.stderr)
        write_summary("проверката не мина")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return EXIT_FAIL
    shutil.move(out_tmp, a.out)
    shutil.rmtree(tmpdir, ignore_errors=True)
    blind = textless(texts)
    print("%s → %s: %d стр. · заличено: %s%s" % (
        os.path.basename(src), a.out, pages, summary,
        " · махната скрита информация: " + ", ".join(removed) if removed else ""))
    print("  ✓ повторна проверка: нищо от заличеното не се чете, няма фалшиви полета")
    if blind:
        print("  ! без текстов слой (скан?) — там нищо не е търсено, гледай на око: стр. %s"
              % ", ".join(map(str, blind)))
    write_summary("заличено: %s%s" % (summary, " · без текст %d стр." % len(blind) if blind else ""))
    return EXIT_FINDINGS if blind else 0


def is_rect(v):
    return isinstance(v, list) and len(v) == 4 and all(isinstance(x, (int, float)) for x in v)


def rects_in(obj):
    """Всички правоъгълници [x0, y0, x1, y1] (с „page“ от най-близкия родител) в отговор на двигателя."""
    out = []

    def walk(o, page):
        if isinstance(o, dict):
            page = o.get("page", page)
            for k, v in o.items():
                if "rect" in k and isinstance(v, list):
                    if is_rect(v):
                        out.append((page, list(v)))
                    elif all(is_rect(x) for x in v):         # "rects": [[…], […]]
                        out.extend((page, list(x)) for x in v)
                    else:
                        walk(v, page)
                else:
                    walk(v, page)
        elif isinstance(o, list):
            for x in o:
                walk(x, page)
    walk(obj, None)
    return [(p, r) for p, r in out if p]


def overlaps(a, b, pad=2.0):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def ours(finding, boxes, height):
    """Находка от одита, която е просто наше черно поле (одитът брои цял ред)."""
    r = to_top_left(finding.get("rect") or [0, 0, 0, 0], height)
    return any(p == finding.get("page") and overlaps(r, b) for p, b in boxes)


_heights = {}


def page_height(eng, doc, page):
    """Височина на страницата в точки — от doc_info → pages[].height."""
    key = (doc, page)
    if key not in _heights:
        info = eng.call("doc_info", doc=doc)
        h = None
        for p in (info.get("pages") or []) if isinstance(info, dict) else []:
            if isinstance(p, dict) and p.get("page") == page:
                h = p.get("height")
        if not h:
            raise EngineError("не знам височината на стр. %s — координатите биха били грешни" % page)
        _heights[key] = h
    return _heights[key]


def to_top_left(rect, height):
    """Одитът дава правоъгълника в координати на PDF (начало долу вляво);
    redact_mark иска начало горе вляво. Без височина — връща го както е."""
    if not height:
        return rect
    x0, y0, x1, y1 = rect
    return [x0, height - max(y0, y1), x1, height - min(y0, y1)]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Истинско заличаване и одит на PDF (двигател PdfCraft).")
    ap.add_argument("--pdfcraft", help="път до pdfcraft-cli (иначе $PDFCRAFT_CLI или PATH)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    au = sub.add_parser("audit", help="само проверява; входът не се пипа")
    au.add_argument("pdf")
    au.add_argument("--json", action="store_true")
    rd = sub.add_parser("redact", help="заличава в нов файл и проверява отново")
    rd.add_argument("pdf")
    rd.add_argument("out")
    for k in KINDS:
        rd.add_argument("--" + k, action="store_true", help="заличи %s" % KIND_BG[k])
    rd.add_argument("--covered", action="store_true", help="заличи текста под фалшиви черни полета")
    rd.add_argument("--find", action="append", metavar="ТЕКСТ", help="точен текст (може много пъти)")
    rd.add_argument("--words-file", help="файл с по един текст на ред (# — коментар)")
    rd.add_argument("--keep-hidden", action="store_true", help="не махай скритата информация")
    rd.add_argument("--dry-run", action="store_true", help="само покажи какво би заличил")
    rd.add_argument("--force", action="store_true", help="презапиши съществуващ изход")
    a = ap.parse_args(argv)

    if not os.path.isfile(a.pdf):
        ap.error("няма такъв PDF файл")
    if a.cmd == "redact":
        if os.path.exists(a.out) and not a.force:
            ap.error("изходът съществува — добави --force, за да го презапишеш")
        if os.path.realpath(a.out) == os.path.realpath(a.pdf):
            ap.error("изходът не може да е самият вход — оригиналът не се пипа")
        if a.words_file and not os.path.isfile(a.words_file):
            ap.error("няма такъв файл с думи")
    exe = find_engine(a.pdfcraft)
    if not exe:
        print("липсва pdfcraft-cli — свали изданието за твоята машина от %s и подай пътя с "
              "--pdfcraft или PDFCRAFT_CLI" % ENGINE_URL, file=sys.stderr)
        write_summary("липсва двигател")
        return EXIT_MISSING
    try:
        return cmd_audit(a, exe) if a.cmd == "audit" else cmd_redact(a, exe)
    except EngineError as e:
        print("двигателят отказа: %s" % e, file=sys.stderr)
        write_summary("двигателят отказа")
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
