#!/usr/bin/env python3
"""share-single-file — HTML страница с локалните ѝ JS/CSS/данни в ЕДИН файл, без сървър.

    share_single_file.py index.html изход.html [--data ФАЙЛ]... [--force]

Какво се вгражда:
  <script src="локален.js">          → esbuild --bundle (ES модулите и импортите им) → вграден <script>
  <link rel="stylesheet" href="…">   → esbuild --bundle за CSS (@import, url() като data:) → <style>
  <img src>, <link rel="icon">       → data: URI
  данни (.json .csv .glb …)          → намират се сами по имената им в HTML/JS/JSON (или --data) и се
                                       подават през fetch() от паметта — страницата ги иска както преди

Нужен е esbuild (SHINKANSEN_ESBUILD, PATH или node_modules/.bin). Без него — ясна грешка, код 3.
Входът само се чете; изходът е нов файл (без --force не презаписва). Вграждат се само файлове
в папката на страницата — нищо извън нея.
"""
import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys

EXIT_MISSING = 3
DATA_EXT = ("json", "geojson", "csv", "tsv", "txt", "xml", "glb", "gltf", "bin", "wasm", "svg",
            "png", "jpg", "jpeg", "webp", "gif", "mp3", "ogg", "wav", "woff2", "woff", "ttf")
TEXT_EXT = ("json", "geojson", "gltf", "csv", "tsv", "txt", "xml", "svg")
ASSET_LOADERS = ["--loader:.%s=dataurl" % e for e in
                 ("png", "jpg", "jpeg", "gif", "webp", "svg", "woff", "woff2", "ttf", "otf", "glb", "wasm")]
REF_RX = re.compile(r"""["'`]([^"'`\s<>()]+\.(?:%s))(?:\?[^"'`\s]*)?["'`]""" % "|".join(DATA_EXT), re.I)
SIZE_WARN = 15 * 1024 * 1024

mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/gltf+json", ".gltf")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/geo+json", ".geojson")


class MissingTool(Exception):
    pass


def write_summary(text):
    path = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def find_esbuild(start_dirs=()):
    env = os.environ.get("SHINKANSEN_ESBUILD")
    if env:
        return env if os.path.isfile(env) and os.access(env, os.X_OK) else None
    found = shutil.which("esbuild")
    if found:
        return found
    for d in list(start_dirs) + [os.getcwd()]:
        d = os.path.abspath(d)
        while True:
            cand = os.path.join(d, "node_modules", ".bin", "esbuild")
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def make_bundler(esbuild):
    """→ bundle(път, вид) → текст. вид: "esm" | "iife" | "css". Подменя се в тестовете."""
    def bundle(path, kind):
        args = [esbuild, path, "--bundle", "--minify", "--log-level=error", "--charset=utf8"] + ASSET_LOADERS
        if kind == "css":
            args.append("--loader:.css=css")
        else:
            args += ["--format=%s" % kind, "--target=es2020"]
        r = subprocess.run(args, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError("esbuild: %s" % (r.stderr.strip() or "код %d" % r.returncode))
        return r.stdout
    return bundle


# ─────────────────────────── HTML ───────────────────────────

ATTR_RX = re.compile(r"""([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?""")


def parse_attrs(s):
    out = {}
    for m in ATTR_RX.finditer(s):
        name = m.group(1).lower()
        val = next((g for g in m.groups()[1:] if g is not None), None)
        out[name] = val
    return out


def is_local(url):
    return bool(url) and not re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", url, re.I)


def resolve(base_dir, root, url):
    """Относителен URL → път във файловата система, само ако е вътре в root и съществува."""
    url = url.split("#", 1)[0].split("?", 1)[0]
    if not is_local(url) or not url:
        return None
    path = os.path.normpath(os.path.join(root if url.startswith("/") else base_dir, url.lstrip("/")))
    real_root = os.path.realpath(root)
    real = os.path.realpath(path)
    if not (real == real_root or real.startswith(real_root + os.sep)) or not os.path.isfile(real):
        return None
    return real


def data_uri(path):
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        return "data:%s;base64,%s" % (ctype, base64.b64encode(f.read()).decode("ascii"))


def safe_inline(text, tag):
    """Вграден код не бива да затваря тага си по-рано."""
    return re.sub(r"</(%s)" % tag, r"<\\/\1", text, flags=re.I)


def fetch_shim(files):
    """Малък скрипт, който отговаря на fetch() за вградените файлове. files: {относителен път: (тип, base64)}."""
    payload = json.dumps({k: list(v) for k, v in sorted(files.items())}, separators=(",", ":"))
    return ("<script>/* share-single-file: вградени данни */(()=>{const F=%s,M=new Map();"
            "for(const k in F)M.set(new URL(k,location.href).href,F[k]);const of=window.fetch&&window.fetch.bind(window);"
            "window.fetch=function(i,o){let u;try{u=new URL(typeof i==='string'?i:(i&&i.url)||String(i),location.href);}"
            "catch(e){return of(i,o)}u.search='';u.hash='';const f=M.get(u.href);if(f){const b=Uint8Array.from(atob(f[1]),c=>c.charCodeAt(0));"
            "return Promise.resolve(new Response(b,{status:200,headers:{'Content-Type':f[0]}}))}"
            "return of?of(i,o):Promise.reject(new TypeError('fetch'))}})();</script>"
            % safe_inline(payload, "script"))


def find_refs(text, base_dir, root):
    """Имената на файлове с данни в текст → {абсолютен път}. Първо спрямо base_dir, после спрямо root."""
    out = set()
    for m in REF_RX.finditer(text):
        p = resolve(base_dir, root, m.group(1)) or resolve(root, root, m.group(1))
        if p:
            out.add(p)
    return out


def assemble(html_path, bundle, extra_data=()):
    """→ (html като текст, отчет {"scripts", "styles", "assets", "data": [...]})."""
    root = os.path.dirname(os.path.abspath(html_path))
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    info = {"scripts": [], "styles": [], "assets": [], "data": []}
    scanned_text = []                                 # (текст, папка, спрямо която се четат имената)

    def script_repl(m):
        attrs = parse_attrs(m.group(1))
        path = resolve(root, root, attrs.get("src"))
        if not path:
            return m.group(0)                          # външен или липсващ — остава както е
        module = (attrs.get("type") or "").lower() == "module"
        # класически скрипт с defer става модул, за да се изпълни пак след разбора на страницата
        code = bundle(path, "esm" if module else "iife")
        scanned_text.append((code, root))            # fetch() в скрипт чете спрямо страницата
        info["scripts"].append(os.path.relpath(path, root))
        typ = ' type="module"' if module or "defer" in attrs else ""
        return "<script%s>%s</script>" % (typ, safe_inline(code, "script"))

    html = re.sub(r"<script\b([^>]*)>\s*</script>",
                  lambda m: script_repl(m) if "src" in parse_attrs(m.group(1)) else m.group(0),
                  html, flags=re.I | re.S)

    def link_repl(m):
        attrs = parse_attrs(m.group(1))
        rel = (attrs.get("rel") or "").lower().split()
        path = resolve(root, root, attrs.get("href"))
        if not path:
            return m.group(0)
        if "stylesheet" in rel:
            css = bundle(path, "css")
            info["styles"].append(os.path.relpath(path, root))
            media = ' media="%s"' % attrs["media"] if attrs.get("media") else ""
            return "<style%s>%s</style>" % (media, safe_inline(css, "style"))
        if "icon" in rel or "apple-touch-icon" in rel or "manifest" in rel:
            info["assets"].append(os.path.relpath(path, root))
            return m.group(0).replace(attrs["href"], data_uri(path), 1)
        return m.group(0)

    html = re.sub(r"<link\b([^>]*)>", link_repl, html, flags=re.I)

    def img_repl(m):
        attrs = parse_attrs(m.group(1))
        path = resolve(root, root, attrs.get("src"))
        if not path:
            return m.group(0)
        info["assets"].append(os.path.relpath(path, root))
        return m.group(0).replace(attrs["src"], data_uri(path), 1)

    html = re.sub(r"<img\b([^>]*)>", img_repl, html, flags=re.I)

    # данни: по имената в HTML (вече с вградени картинки) и в JS; после и в самите данни
    # (venue.json → model.glb) — там спрямо папката на файла с данни
    scanned_text.append((html, root))
    data = set()
    for p in extra_data:
        rp = resolve(root, root, os.path.relpath(os.path.abspath(p), root))
        if not rp:
            raise ValueError("--data трябва да е файл в папката на страницата: %s" % p)
        data.add(rp)
    queue = list(scanned_text)
    while queue:
        text, base = queue.pop()
        for p in find_refs(text, base, root) - data:
            data.add(p)
            if p.lower().endswith(tuple("." + e for e in TEXT_EXT)):
                with open(p, encoding="utf-8", errors="replace") as f:
                    queue.append((f.read(), os.path.dirname(p)))
    files = {}
    for p in sorted(data):
        with open(p, "rb") as f:
            raw = f.read()
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        files[rel] = (mimetypes.guess_type(p)[0] or "application/octet-stream",
                      base64.b64encode(raw).decode("ascii"))
        info["data"].append(rel)
    if files:
        shim = fetch_shim(files)
        m = re.search(r"<head\b[^>]*>", html, re.I)
        html = html[:m.end()] + shim + html[m.end():] if m else shim + html
    return html, info


def main(argv=None, bundler=None):
    ap = argparse.ArgumentParser(description="HTML + локалните му файлове → един файл.")
    ap.add_argument("html")
    ap.add_argument("out")
    ap.add_argument("--data", action="append", default=[], help="още файл с данни за вграждане")
    ap.add_argument("--force", action="store_true", help="презапиши съществуващ изход")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.html):
        ap.error("няма такъв HTML файл")
    if os.path.exists(a.out) and not a.force:
        ap.error("изходът съществува — добави --force, за да го презапишеш")
    if os.path.realpath(a.out) == os.path.realpath(a.html):
        ap.error("изходът не може да е самата страница")
    if bundler is None:
        esbuild = find_esbuild([os.path.dirname(os.path.abspath(a.html))])
        if not esbuild:
            print("липсва esbuild — инсталирай го (напр. `npm i -g esbuild` или `npm i esbuild` в проекта) "
                  "или посочи пътя в SHINKANSEN_ESBUILD", file=sys.stderr)
            write_summary("липсва esbuild")
            return EXIT_MISSING
        bundler = make_bundler(esbuild)
    try:
        html, info = assemble(a.html, bundler, a.data)
    except (RuntimeError, ValueError) as e:
        print(str(e), file=sys.stderr)
        write_summary("сглобяването падна")
        return 1
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    size = os.path.getsize(a.out)
    print("%s → %s · %.1f KB · скриптове %d, стилове %d, картинки %d, данни %d" % (
        os.path.basename(a.html), a.out, size / 1024, len(info["scripts"]), len(info["styles"]),
        len(info["assets"]), len(info["data"])))
    for d in info["data"]:
        print("  данни: " + d)
    if size > SIZE_WARN:
        print("! файлът е над 15 MB — някои места за споделяне няма да го приемат", file=sys.stderr)
    write_summary("%.0f KB · %d скрипта · %d данни" % (size / 1024, len(info["scripts"]), len(info["data"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
