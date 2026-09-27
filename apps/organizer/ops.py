"""Операциите около сглобения сайт: пакет за качване и проверка A5 с една команда.

    organizer.py package САЙТ ПАПКА [--prev ПРЕДИШЕН]   # tgz + SHA-256 + списък + разлика
    organizer.py qa СЪБИТИЕ ОТЧЕТ [--no-shots]          # сглобяване, PHP на живо, снимки, отчет

Само стандартна библиотека; qa ползва php (ако го има) и node + playwright (ако ги има) —
липсващото се отбелязва в отчета като „пропуснато“, не като минато.
"""
import csv
import gzip
import hashlib
import io
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------- package ----------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(site):
    """{път: (sha256, размер)} за всеки файл в сайта, подредени по път."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(site):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, site).replace(os.sep, "/")
            out[rel] = (sha256_file(full), os.path.getsize(full))
    return dict(sorted(out.items()))


def manifest_text(m):
    return "".join("%s  %9d  %s\n" % (h, size, rel) for rel, (h, size) in m.items())


def read_manifest(path):
    """Предишен пакет: .manifest.txt, .tgz (до него трябва .manifest.txt) или папка."""
    if os.path.isdir(path):
        return manifest(path)
    if path.endswith(".tgz"):
        path = path[:-4] + ".manifest.txt"
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split(None, 2)
            if len(parts) == 3:
                out[parts[2]] = (parts[0], int(parts[1]))
    return out


def diff(old, new):
    added = [p for p in new if p not in old]
    removed = [p for p in old if p not in new]
    changed = [p for p in new if p in old and new[p][0] != old[p][0]]
    return {"added": added, "removed": removed, "changed": changed}


def diff_text(d):
    if not any(d.values()):
        return "без разлика спрямо предишния пакет\n"
    lines = []
    for key, label in (("changed", "сменен"), ("added", "нов"), ("removed", "махнат")):
        lines += ["%-7s %s" % (label, p) for p in d[key]]
    return "\n".join(lines) + "\n"


def package(site, out_dir, name=None, prev=None, today=None):
    """Детерминиран tgz (сортирани пътища, mtime 0, собственик 0) + .sha256 + .manifest.txt (+ .diff.txt).
    Нищо не презаписва: ако пакетът със същото съдържание вече го има, само го посочва."""
    if not os.path.isdir(site):
        raise ValueError("няма папка %s" % site)
    m = manifest(site)
    if not m:
        raise ValueError("%s е празна" % site)
    whole = hashlib.sha256(manifest_text(m).encode()).hexdigest()
    name = name or os.path.basename(os.path.abspath(site))
    base = "%s_%s_%s" % (name, (today or date.today()).isoformat(), whole[:8])
    os.makedirs(out_dir, exist_ok=True)
    tgz = os.path.join(out_dir, base + ".tgz")
    result = {"tgz": tgz, "files": len(m), "bytes": sum(s for _, s in m.values()), "diff": None, "existed": False}
    if os.path.exists(tgz):
        result["existed"] = True
    else:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for rel in m:
                info = tar.gettarinfo(os.path.join(site, rel), arcname=rel)
                info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
                info.mode = 0o644
                with open(os.path.join(site, rel), "rb") as f:
                    tar.addfile(info, f)
        with open(tgz, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                gz.write(buf.getvalue())
        with open(tgz[:-4] + ".manifest.txt", "w", encoding="utf-8") as f:
            f.write(manifest_text(m))
        with open(tgz + ".sha256", "w", encoding="utf-8") as f:
            f.write("%s  %s\n" % (sha256_file(tgz), os.path.basename(tgz)))
    if prev:
        d = diff(read_manifest(prev), m)
        result["diff"] = d
        with open(tgz[:-4] + ".diff.txt", "w", encoding="utf-8") as f:
            f.write(diff_text(d))
    result["sha256"] = sha256_file(tgz)
    return result


# ---------- qa ----------

ROUTER = """<?php
// Само за qa: за admin/ слагаме REMOTE_USER, както би го сложил сървърът след вход с парола.
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
if (strpos($path, '/admin/') !== false) {
    if (isset($_SERVER['HTTP_X_QA_LOCKED'])) { $_SERVER['REMOTE_USER'] = 'qa'; }
    chdir(__DIR__ . '/admin');
    require __DIR__ . '/admin/export.php';
    return true;
}
return false;
"""


def sample_answer(form):
    """Верен отговор по спецификацията от api/forms.json: всяко поле попълнено (и личните — за да ги проверим)."""
    ans = {"_form": None, "_t": "9"}
    for f in form["fields"]:
        t = f["type"]
        if t == "single":
            ans[f["id"]] = f["options"][0]
        elif t == "multi":
            ans[f["id"]] = f["options"][:1]
        elif t == "email":
            ans[f["id"]] = "qa@example.org"
        elif t == "consent":
            ans[f["id"]] = "1"
        else:
            ans[f["id"]] = "QA проба"[: int(f.get("max_length", 2000))]
    return ans


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http(url, data=None, headers=None):
    h = dict(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8-sig", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8-sig", "replace")


def php_checks(site, php):
    """Въпросниците на живо: вграденият сървър на PHP + SQLite вместо MySQL. Връща [(проверка, ок, бележка)]."""
    res = []
    spec_path = os.path.join(site, "api", "forms.json")
    if not os.path.exists(spec_path):
        return [("въпросници", None, "няма api/ — сайтът е без въпросници или е сглобен с --demo")]
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    tmp = tempfile.mkdtemp(prefix="organizer-qa-")
    db = os.path.join(tmp, "qa.sqlite")
    cfg = os.path.join(tmp, "cfg.php")
    with open(cfg, "w") as f:
        f.write("<?php return ['db' => ['dsn' => 'sqlite:%s'], 'auto_create' => true, 'salt' => 'qa'];" % db)
    router = os.path.join(site, "_qa_router.php")
    with open(router, "w") as f:
        f.write(ROUTER)
    port = _free_port()
    proc = subprocess.Popen([php, "-S", "127.0.0.1:%d" % port, "_qa_router.php"], cwd=site,
                            env=dict(os.environ, ORGANIZER_CONFIG=cfg),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d/" % port
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        code, _ = _http(base + "api/submit.php")
        res.append(("submit.php приема само POST", code == 405, "код %d" % code))
        for fid, form in spec["forms"].items():
            ans = sample_answer(form)
            ans["_form"] = fid
            code, body = _http(base + "api/submit.php", ans)
            ok = code == 200 and '"ok":true' in body.replace(" ", "")
            res.append(("„%s“: изпращане" % form["title"], ok, "код %d" % code))
            bad = dict(ans, **{form["fields"][0]["id"]: "__не_е_опция__"}) if form["fields"][0]["type"] == "single" else None
            if bad:
                code, _ = _http(base + "api/submit.php", bad)
                res.append(("„%s“: непозната опция се отхвърля" % form["title"], code == 422, "код %d" % code))
            code, _ = _http(base + "api/submit.php", dict(ans, _hp="bot"))
            res.append(("„%s“: капанът за ботове не записва" % form["title"], code == 200, "код %d" % code))
            personal = [f["id"] for f in form["fields"] if f.get("personal")]
            con = sqlite3.connect(db)
            rows = [json.loads(r[0]) for r in con.execute("SELECT answers FROM `%s`" % form["table"])]
            leak = [k for r in rows for k in personal if k in r]
            res.append(("„%s“: лични полета само в _kontakt" % form["title"], bool(rows) and not leak,
                        "%d отговор(а); в отговорите: %s" % (len(rows), ", ".join(leak) or "нищо лично")))
            if personal:
                n = con.execute("SELECT COUNT(*) FROM `%s`" % form["contact_table"]).fetchone()[0]
                res.append(("„%s“: ред в _kontakt" % form["title"], n == 1, "%d ред(а)" % n))
            con.close()
            code, text = _http(base + "admin/export.php?form=" + urllib.parse.quote(fid), headers={"X-QA-Locked": "1"})
            n_rows = len(list(csv.reader(io.StringIO(text)))) - 1 if code == 200 else -1
            res.append(("„%s“: износ в CSV" % form["title"], n_rows == 1, "код %d, %d ред(а)" % (code, max(n_rows, 0))))
        code, _ = _http(base + "admin/export.php")
        res.append(("износът без заключена папка отказва", code == 403, "код %d" % code))
    finally:
        proc.terminate()
        proc.wait(5)
        os.remove(router)
        shutil.rmtree(tmp, ignore_errors=True)
    return res


SHOTS_JS = r"""
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const [root, outDir, widths] = [process.argv[2], process.argv[3], process.argv[4].split(',').map(Number)];
const types = {'.css':'text/css','.js':'text/javascript','.json':'application/json','.png':'image/png','.jpg':'image/jpeg',
               '.svg':'image/svg+xml','.woff2':'font/woff2','.html':'text/html; charset=utf-8'};
const srv = http.createServer((q, r) => { let p = path.join(root, decodeURIComponent(q.url.split('?')[0]));
  if (p.endsWith('/')) p += 'index.html';
  fs.readFile(p, (e, d) => { if (e) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, {'Content-Type': types[path.extname(p)] || 'application/octet-stream'}); r.end(d); }); });
srv.listen(0, '127.0.0.1', async () => {
  const port = srv.address().port, out = [];
  const b = await chromium.launch(process.env.ORGANIZER_CHROMIUM ? { executablePath: process.env.ORGANIZER_CHROMIUM } : {});
  for (const f of fs.readdirSync(root).filter(x => x.endsWith('.html')).sort()) for (const w of widths) {
    const p = await b.newPage({ viewport: { width: w, height: 900 } }); const errs = [], missing = [];
    p.on('pageerror', e => errs.push(String(e)));
    p.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('favicon.ico')) missing.push(r.url().split(':' + port)[1]); });
    await p.goto(`http://127.0.0.1:${port}/${f}`); await p.evaluate(() => document.fonts.ready);
    await p.evaluate(() => Promise.all([...document.images].map(i => { i.loading = 'eager';   // lazy под екрана
      return i.complete ? 0 : new Promise(ok => { i.onload = i.onerror = ok; setTimeout(ok, 5000); }); })));
    const over = await p.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    const broken = await p.evaluate(() => [...document.images].filter(i => i.complete && !i.naturalWidth).map(i => i.getAttribute('src')));
    const shot = `${f.replace('.html', '')}_${w}.png`; await p.screenshot({ path: path.join(outDir, shot), fullPage: true });
    out.push({ page: f, width: w, overflow: Math.max(0, over), errors: errs, missing, broken, shot }); await p.close(); }
  await b.close(); srv.close(); console.log(JSON.stringify(out));
});
"""


def browser_checks(site, shots_dir, widths=(360, 1440)):
    node = shutil.which("node")
    if not node:
        return None, "няма node"
    env = dict(os.environ)
    try:
        groot = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=20).stdout.strip()
        env["NODE_PATH"] = os.pathsep.join(x for x in (env.get("NODE_PATH"), groot) if x)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if subprocess.run([node, "-e", "require.resolve('playwright')"], env=env, capture_output=True).returncode:
        return None, "няма playwright за node"
    if not env.get("ORGANIZER_CHROMIUM") and os.path.exists("/opt/pw-browsers/chromium"):
        env["ORGANIZER_CHROMIUM"] = "/opt/pw-browsers/chromium"
    os.makedirs(shots_dir, exist_ok=True)
    js = os.path.join(tempfile.mkdtemp(prefix="organizer-shots-"), "shots.js")
    with open(js, "w") as f:
        f.write(SHOTS_JS)
    r = subprocess.run([node, js, site, shots_dir, ",".join(map(str, widths))], env=env,
                       capture_output=True, text=True, timeout=600)
    if r.returncode:
        return None, "браузърът падна: " + (r.stderr.strip().splitlines() or ["?"])[-1]
    return json.loads(r.stdout.strip().splitlines()[-1]), None


def qa(folder, report_dir, shots=True, build=None):
    """A5 с една команда. Връща (път до отчета, брой неуспешни)."""
    build = build or __import__("organizer").build
    os.makedirs(report_dir, exist_ok=True)
    site = tempfile.mkdtemp(prefix="organizer-qa-site-")
    rows = []
    try:
        written, todo = build(folder, site)
        rows.append(("сглобяване: 0 счупени връзки, 0 забранени текстове", True, "%d файла" % len(written)))
    except ValueError as e:
        rows.append(("сглобяване", False, str(e).replace("\n", "; ")))
        written, todo = [], []
    if written:
        php = shutil.which("php")
        rows += php_checks(site, php) if php else [("въпросници (PHP)", None, "пропуснато: няма php")]
        if shots:
            results, why = browser_checks(site, os.path.join(report_dir, "snimki"))
            if results is None:
                rows.append(("екран 360 и 1440 px", None, "пропуснато: " + why))
            else:
                for r in results:
                    probs = []
                    if r["overflow"]:
                        probs.append("излиза вдясно с %d px" % r["overflow"])
                    if r["errors"]:
                        probs.append("грешки в JS: %d" % len(r["errors"]))
                    if r["missing"] or r["broken"]:
                        probs.append("липсващи: %s" % ", ".join(sorted(set(r["missing"] + r["broken"]))))
                    rows.append(("%s @ %d px" % (r["page"], r["width"]), not probs,
                                 "; ".join(probs) or "снимка: snimki/%s" % r["shot"]))
    failed = sum(1 for _, ok, _ in rows if ok is False)
    skipped = sum(1 for _, ok, _ in rows if ok is None)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mark = {True: "✓", False: "✗", None: "–"}
    lines = ["# Проверка A5 · %s" % os.path.basename(os.path.abspath(folder)), "",
             "%s · %d проверки · **%d неуспешни** · %d пропуснати" % (stamp, len(rows), failed, skipped), "",
             "| | Проверка | Бележка |", "|---|---|---|"]
    lines += ["| %s | %s | %s |" % (mark[ok], name.replace("|", "\\|"), note.replace("|", "\\|")) for name, ok, note in rows]
    if todo:
        lines += ["", "## Липси от check (не спират)", ""] + ["- " + t for t in todo]
    path = os.path.join(report_dir, "qa_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    shutil.rmtree(site, ignore_errors=True)
    return path, failed


# ---------- fill: съдържание от Markdown файлове с JSON блокове ----------

import re as _re

HEADING_RE = _re.compile(r"^##\s+(?:(\d+)\.\s*)?(.+?)\s*$")
FENCE_RE = _re.compile(r"^```json\s*$")


def md_blocks(text):
    """[{num, title, blocks: [json текст, …]}] — по раздел „## N. …“, JSON блоковете в него поред."""
    sections, cur, buf, inside = [], None, [], False
    for line in text.splitlines():
        if inside:
            if line.strip() == "```":
                cur["blocks"].append("\n".join(buf))
                inside, buf = False, []
            else:
                buf.append(line)
            continue
        m = HEADING_RE.match(line)
        if m:
            cur = {"num": m.group(1), "title": m.group(2), "blocks": []}
            sections.append(cur)
        elif FENCE_RE.match(line.strip()) and cur is not None:
            inside = True
    return sections


def find_block(sections, block, index=0):
    """block: номерът на раздела („2“) или част от заглавието му; index — кой JSON блок в раздела (от 0)."""
    key = str(block)
    hits = [s for s in sections if s["num"] == key] or [s for s in sections if key in s["title"]]
    if len(hits) != 1:
        raise ValueError("раздел „%s“: %s" % (block, "няма такъв" if not hits else "повече от един"))
    if index >= len(hits[0]["blocks"]):
        raise ValueError("раздел „%s“: няма JSON блок №%d" % (block, index + 1))
    return json.loads(hits[0]["blocks"][index])


SEG_RE = _re.compile(r"^([^\[\]]+)?((?:\[[^\]]+\])*)$")


def _parse_path(path):
    """„topics[n=3].demo.steps“ → [("topics", None), (None, ("n", "3")), ("demo", None), ("steps", None)]."""
    out = []
    for seg in path.split("."):
        m = SEG_RE.match(seg)
        if not m:
            raise ValueError("път „%s“: не разбирам „%s“" % (path, seg))
        if m.group(1):
            out.append(("key", m.group(1)))
        for sel in _re.findall(r"\[([^\]]+)\]", m.group(2) or ""):
            if "=" in sel:
                k, v = sel.split("=", 1)
                out.append(("where", (k.strip(), v.strip())))
            else:
                out.append(("idx", int(sel)))
    return out


def _step(node, step, create):
    kind, arg = step
    if kind == "key":
        if not isinstance(node, dict):
            raise ValueError("„%s“ не е обект" % arg)
        if arg not in node:
            if not create:
                raise ValueError("няма „%s“" % arg)
            node[arg] = {}
        return node, arg
    if not isinstance(node, list):
        raise ValueError("очаквах списък пред [%s]" % (arg,))
    if kind == "idx":
        if not -len(node) <= arg < len(node):
            raise ValueError("няма елемент [%d]" % arg)
        return node, arg
    k, v = arg
    hits = [i for i, el in enumerate(node) if isinstance(el, dict) and str(el.get(k)) == v]
    if len(hits) != 1:
        raise ValueError("[%s=%s]: %s" % (k, v, "няма такъв" if not hits else "повече от един"))
    return node, hits[0]


def apply_op(doc, target, value, mode="set", at=None, key=None):
    """Вливане на стойност в doc по път. Режими: set, merge, append, extend, insert, upsert.
    append/extend/insert не добавят второ копие на същия елемент — второ пускане не дублира."""
    steps = _parse_path(target)
    node = doc
    for step in steps[:-1]:
        parent, k = _step(node, step, create=True)
        node = parent[k]
    parent, k = _step(node, steps[-1], create=mode not in ("merge",))
    cur = parent[k] if not (isinstance(parent, dict) and k not in parent) else None
    if mode == "set":
        parent[k] = value
    elif mode == "merge":
        if not isinstance(cur, dict) or not isinstance(value, dict):
            raise ValueError("%s: merge иска обект към обект" % target)
        cur.update(value)
    elif mode in ("append", "extend", "insert", "upsert"):
        if cur in (None, {}):
            parent[k] = cur = []
        if not isinstance(cur, list):
            raise ValueError("%s: %s иска списък" % (target, mode))
        items = value if mode == "extend" else [value]
        if mode == "upsert":
            if not key:
                raise ValueError("%s: upsert иска key" % target)
            for it in items:
                hit = [i for i, el in enumerate(cur) if isinstance(el, dict) and el.get(key) == it.get(key)]
                if hit:
                    cur[hit[0]] = it
                else:
                    cur.append(it)
        else:
            pos = len(cur) if at is None or mode != "insert" else at
            for it in items:
                if it in cur:
                    continue
                cur.insert(pos, it)
                pos += 1
    else:
        raise ValueError("%s: непознат режим „%s“" % (target, mode))


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, "%s.%s" % (prefix, k) if prefix else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, "%s[%d]" % (prefix, i)))
        if not obj:
            out[prefix] = []
    else:
        out[prefix] = obj
    return out


def key_diff(before, after):
    a, b = flatten(before), flatten(after)
    return {"added": sorted(k for k in b if k not in a), "removed": sorted(k for k in a if k not in b),
            "changed": sorted(k for k in b if k in a and a[k] != b[k])}


def _src_path(folder, file):
    p = os.path.expanduser(file)
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(folder, p))


def fill(folder, dry_run=False, now=None):
    """Изпълнява event.json → sources: [{file, block, index?, pick?, target, mode?, at?, key?, map?}].
    map: true — стойността е {ключ: стойност}, а target съдържа {key} (напр. topics[n={key}].demo.steps).
    Връща (разлика, дневник). Без dry_run записва event.json (старият → event.json.orig_ДАТА[-N])."""
    ev_path = os.path.join(folder, "event.json")
    with open(ev_path, encoding="utf-8") as f:
        event = json.load(f)
    before = json.loads(json.dumps(event))
    log = []
    cache = {}
    for i, src in enumerate(event.get("sources", [])):
        where = "sources[%d]" % i
        path = _src_path(folder, src["file"])
        if path not in cache:
            with open(path, encoding="utf-8") as f:
                cache[path] = md_blocks(f.read())
        value = find_block(cache[path], src["block"], int(src.get("index", 0)))
        if src.get("pick"):
            value = value[src["pick"]]
        targets = [(src["target"], value)]
        if src.get("map"):
            if not isinstance(value, dict) or "{key}" not in src["target"]:
                raise ValueError("%s: map иска обект и {key} в target" % where)
            targets = [(src["target"].replace("{key}", str(k)), v) for k, v in value.items()]
        for target, v in targets:
            try:
                apply_op(event, target, v, src.get("mode", "set"), src.get("at"), src.get("key"))
            except ValueError as e:
                raise ValueError("%s (%s#%s → %s): %s" % (where, src["file"], src["block"], target, e))
        log.append("%s#%s%s → %s (%s)" % (src["file"], src["block"],
                                          "[%s]" % src["index"] if src.get("index") else "",
                                          src["target"], src.get("mode", "set")))
    d = key_diff(before, event)
    if not dry_run and any(d.values()):
        save_event(folder, event, "fill", log, d, now)
    return d, log


def save_event(folder, event, what, log, d, now=None):
    """Записва event.json: старото → event.json.orig_ДАТА[-N] (нищо не се презаписва) + ред в decisions.md."""
    ev_path = os.path.join(folder, "event.json")
    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    backup, n = ev_path + ".orig_" + stamp, 1
    while os.path.exists(backup):
        n += 1
        backup = "%s.orig_%s-%d" % (ev_path, stamp, n)
    shutil.copyfile(ev_path, backup)
    with open(ev_path, "w", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(os.path.join(folder, "decisions.md"), "a", encoding="utf-8") as f:
        f.write("\n## %s · %s\n\n" % ((now or datetime.now()).strftime("%Y-%m-%d %H:%M"), what))
        f.write("".join("- %s\n" % x for x in log))
        f.write("- промени: %d нови, %d сменени, %d махнати ключа; старото: %s\n" % (
            len(d["added"]), len(d["changed"]), len(d["removed"]), os.path.basename(backup)))
    return backup


def check_sources(folder, event):
    """За check: всеки източник да съществува и блокът му да се намира. Връща списък с грешки."""
    err = []
    for i, src in enumerate(event.get("sources", [])):
        where = "sources[%d]" % i
        if not isinstance(src, dict) or not all(src.get(k) not in (None, "") for k in ("file", "block", "target")):
            err.append("%s: иска file, block и target" % where)
            continue
        path = _src_path(folder, src["file"])
        try:
            with open(path, encoding="utf-8") as f:
                find_block(md_blocks(f.read()), src["block"], int(src.get("index", 0)))
            _parse_path(src["target"].replace("{key}", "0"))
        except OSError:
            err.append("%s: няма файл %s" % (where, src["file"]))
        except (ValueError, KeyError) as e:
            err.append("%s: %s" % (where, e))
    return err


# ---------- demo-import: резултатите от пробата на демата ----------

STATUS = {"ok": "ok", "pass": "ok", "passed": "ok", "минало": "ok", "fail": "fail", "failed": "fail",
          "error": "fail", "skip": "skip", "skipped": "skip"}
LINE_RE = _re.compile(r"\bt(?:ema)?[ _-]?0*(\d{1,2})\b[^A-Za-zА-Яа-я0-9]{0,6}(OK|PASS(?:ED)?|FAIL(?:ED)?|ERROR|SKIP(?:PED)?)\b"
                      r"(?:.*?\b(\d+(?:[.,]\d+)?)\s*(?:s|sec|сек)\b)?(?:.*?\b(\d{2,3}(?:[.,]\d)?)\s*°?C\b)?", _re.I)
REDACT = [
    (_re.compile(r"\b[\w.-]+@[\w.-]+\b"), "…"),                                  # потребител@машина, имейл
    (_re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "…"),                    # IPv4 и порт
    (_re.compile(r"\b(?:localhost|127\.0\.0\.1)(?::\d+)?\b", _re.I), "…"),
    (_re.compile(r"(?<![\w/]):\d{2,5}\b"), ""),                                    # самостоятелен порт :11435
    (_re.compile(r"(?:~|/(?:home|root|opt|mnt|srv|var|tmp|Users))/[^\s,;)“”\"']+"), "…"),   # пътища
    (_re.compile(r"\b[A-Za-z]:\\[^\s,;)“”\"']+"), "…"),                              # C:\…
    (_re.compile(r"\b(?:PID|pid)[ =:#]*\d+\b"), ""),
    (_re.compile(r"https?://[^\s)“”\"']+"), "…"),
]


def redact(text, words=()):
    for rx, rep in REDACT:
        text = rx.sub(rep, text)
    for w in words:
        if w:
            text = _re.sub(_re.escape(w), "…", text, flags=_re.I)
    return _re.sub(r"\s{2,}", " ", text).strip()


def parse_results(path):
    """Договорът: JSON [{topic, status, seconds?, date?, max_temp_c?, note?}] (или {"results": […]}).
    Иначе — лог с редове като „t03 OK 75.2 s … 66 °C“. Връща {n: {…}}."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    out = {}
    try:
        data = json.loads(text)
        items = data.get("results", data) if isinstance(data, dict) else data
        for it in items:
            st = STATUS.get(str(it.get("status", "")).lower())
            if st and int(it["topic"]) > 0:
                out[int(it["topic"])] = {k: it[k] for k in ("seconds", "date", "max_temp_c", "note") if it.get(k) is not None}
                out[int(it["topic"])]["status"] = st
        return out
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    for line in text.splitlines():
        m = LINE_RE.search(line)
        if not m:
            continue
        r = {"status": STATUS[m.group(2).lower()]}
        if m.group(3):
            r["seconds"] = float(m.group(3).replace(",", "."))
        if m.group(4):
            r["max_temp_c"] = float(m.group(4).replace(",", "."))
        out[int(m.group(1))] = r
    return out


def demo_import(folder, results_path, words_path=None, when=None, dry_run=False, now=None):
    """Слага topics[n].demo.results = {status, seconds, date, max_temp_c, note} по номер на тема; бележките минават
    през филтъра. Теми без демо (demo: false) и непознати номера се прескачат. Връща (разлика, дневник)."""
    words = []
    if words_path:
        with open(os.path.expanduser(words_path), encoding="utf-8") as f:
            words = [w.strip() for w in f if w.strip() and not w.startswith("#")]
    res = parse_results(results_path)
    with open(os.path.join(folder, "event.json"), encoding="utf-8") as f:
        event = json.load(f)
    before = json.loads(json.dumps(event))
    by_n = {t.get("n"): t for t in event.get("topics", [])}
    log, skipped = [], []
    for n, r in sorted(res.items()):
        t = by_n.get(n)
        if not t or t.get("demo") is False:
            skipped.append(n)
            continue
        r = dict(r)
        if r.get("note"):
            r["note"] = redact(str(r["note"]), words)
        r.setdefault("date", (when or (now or datetime.now()).date().isoformat()))
        if not isinstance(t.get("demo"), dict):
            t["demo"] = {"title": "Демо на живо", "steps": []}
        t["demo"]["results"] = r
        log.append("тема %d: %s%s" % (n, r["status"], " · %.1f s" % r["seconds"] if "seconds" in r else ""))
    if skipped:
        log.append("прескочени: %s (няма такава тема или е без демо)" % ", ".join(map(str, skipped)))
    d = key_diff(before, event)
    if not dry_run and any(d.values()):
        save_event(folder, event, "demo-import · %s" % os.path.basename(results_path), log, d, now)
    return d, log


# ---------- feedback: обобщение на отговорите ----------

def _fetch_csv(url):
    user, pw = os.environ.get("ORGANIZER_ADMIN_USER"), os.environ.get("ORGANIZER_ADMIN_PASS")
    if not (user and pw):
        raise ValueError("за --url трябват ORGANIZER_ADMIN_USER и ORGANIZER_ADMIN_PASS (паролата на admin/)")
    import base64
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + base64.b64encode(
        ("%s:%s" % (user, pw)).encode()).decode()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8-sig")


def feedback(csv_text, form):
    """Обобщение в Markdown по спецификацията на въпросника (api/forms.json → forms[id]).
    Личните полета (personal) не влизат — нито имена, нито имейли, нито броят им по човек."""
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return "# %s\n\nНяма отговори.\n" % form["title"]
    head, data = rows[0], rows[1:]
    col = {h: i for i, h in enumerate(head)}
    lines = ["# Обратна връзка · %s" % form["title"], "", "**%d отговора**" % len(data)]
    if data:
        dates = sorted(r[1][:10] for r in data if len(r) > 1 and r[1])
        if dates:
            lines[-1] += " · от %s до %s" % (dates[0], dates[-1])
    for f in form["fields"]:
        if f.get("personal") or f["label"] not in col:
            continue
        vals = [r[col[f["label"]]].strip() for r in data if len(r) > col[f["label"]]]
        vals = [v[1:] if v.startswith("'") and v[1:2] in "=+-@" else v for v in vals]     # обезвредените клетки
        filled = [v for v in vals if v]
        lines += ["", "## %s" % f["label"], ""]
        if not filled:
            lines.append("_няма отговори_")
            continue
        if f["type"] in ("single", "multi"):
            counts = {}
            for v in filled:
                for item in (v.split("; ") if f["type"] == "multi" else [v]):
                    counts[item] = counts.get(item, 0) + 1
            order = [o for o in f.get("options", []) if o in counts] + sorted(k for k in counts if k not in f.get("options", []))
            lines += ["| Отговор | Брой |", "|---|---|"] + ["| %s | %d |" % (k.replace("|", "\\|"), counts[k]) for k in order]
        else:
            lines += ["- " + v.replace("\n", " ") for v in filled]
    return "\n".join(lines) + "\n"
