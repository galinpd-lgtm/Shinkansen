"""Качване на сглобения пакет в cPanel — по картата A6, без да се трие нищо.

    organizer.py deploy ПАКЕТ.tgz --config ~/.config/organizer/deploy.json            # само план
    organizer.py deploy ПАКЕТ.tgz --config … --go [--htaccess-ok] [--no-test-answer]

Config (извън репото — адреси, потребител и токен не влизат нито тук, нито в event.json):
    {"cpanel": "https://сървър:2083", "user": "…", "token_file": "~/.config/organizer/cpanel.token",
     "public_html": "public_html", "dir": "ai-start", "site_url": "https://домейн/ai-start/"}
Токенът: cPanel → Manage API Tokens; файлът съдържа само него. Може и в CPANEL_TOKEN.
За износа след качването (по желание): ORGANIZER_ADMIN_USER / ORGANIZER_ADMIN_PASS — паролата на admin/.

Стъпки (A6): SHA-256 на пакета → .htaccess на public_html (пренасочванията се наследяват) →
съществуваща папка се преименува на _ARHIV_<папка>_<време> → качване в _ARHIV_uploads/ →
разархивиране в новата папка → маркер файл → проверка отвън с ?cb= → всички страници 200 и noindex →
тестов отговор → износ. Нищо не се трие.
"""
import base64
import json
import os
import re
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

import ops


class CpanelError(RuntimeError):
    pass


class Cpanel:
    """Минимален клиент: UAPI Fileman (list, get_file_content, upload_files, save_file_content)
    и API2 Fileman (mkdir, fileop rename/extract). Токенът е само в заглавката Authorization."""

    def __init__(self, base, user, token, opener=None):
        self.base, self.user = base.rstrip("/"), user
        self._auth = "cpanel %s:%s" % (user, token)
        self.opener = opener or urllib.request.build_opener()

    def _req(self, path, params=None, data=None, headers=None):
        url = "%s%s" % (self.base, path)
        if params:
            url += "?" + urllib.parse.urlencode(params)
        h = {"Authorization": self._auth}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h)
        try:
            with self.opener.open(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise CpanelError("%s → HTTP %d" % (path, e.code))
        except urllib.error.URLError as e:
            raise CpanelError("%s → %s" % (path, e.reason))
        try:
            return json.loads(body)
        except ValueError:
            raise CpanelError("%s → не е JSON (грешен адрес или токен?)" % path)

    def uapi(self, module, func, params=None, data=None, headers=None):
        j = self._req("/execute/%s/%s" % (module, func), params, data, headers)
        if not j.get("status"):
            raise CpanelError("%s::%s: %s" % (module, func, "; ".join(j.get("errors") or ["неуспех"])))
        return j.get("data")

    def api2(self, module, func, params):
        p = {"cpanel_jsonapi_user": self.user, "cpanel_jsonapi_apiversion": 2,
             "cpanel_jsonapi_module": module, "cpanel_jsonapi_func": func}
        p.update(params)
        j = self._req("/json-api/cpanel", p)
        res = (j.get("cpanelresult") or {})
        if res.get("error") or (res.get("event") or {}).get("result") == 0:
            raise CpanelError("%s::%s: %s" % (module, func, res.get("error") or "неуспех"))
        data = res.get("data") or []
        bad = [d for d in data if isinstance(d, dict) and d.get("result") == 0]
        if bad:
            raise CpanelError("%s::%s: %s" % (module, func, bad[0].get("reason") or "неуспех"))
        return data

    def list(self, d):
        return {x["file"]: x.get("type") for x in (self.uapi("Fileman", "list_files", {"dir": d, "types": "dir|file",
                                                                                      "include_hash": 0}) or [])}

    def read(self, d, name):
        return (self.uapi("Fileman", "get_file_content", {"dir": d, "file": name}) or {}).get("content", "")

    def mkdir(self, parent, name):
        self.api2("Fileman", "mkdir", {"path": parent, "name": name})

    def rename(self, src, dst):
        self.api2("Fileman", "fileop", {"op": "rename", "sourcefiles": src, "destfiles": dst})

    def extract(self, archive, dest):
        self.api2("Fileman", "fileop", {"op": "extract", "sourcefiles": archive, "destfiles": dest})

    def save(self, d, name, content):
        self.uapi("Fileman", "save_file_content", data=urllib.parse.urlencode(
            {"dir": d, "file": name, "content": content}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"})

    def upload(self, d, path):
        boundary = uuid.uuid4().hex
        with open(path, "rb") as f:
            payload = f.read()
        parts = [("dir", d), ("overwrite", "0")]
        body = b"".join(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode()
                        for k, v in parts)
        body += ("--%s\r\nContent-Disposition: form-data; name=\"file-1\"; filename=\"%s\"\r\n"
                 "Content-Type: application/gzip\r\n\r\n" % (boundary, os.path.basename(path))).encode()
        body += payload + ("\r\n--%s--\r\n" % boundary).encode()
        data = self.uapi("Fileman", "upload_files", data=body,
                         headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
        if data and data.get("failed"):
            raise CpanelError("upload_files: %s" % data.get("uploads"))


def load_config(path):
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        cfg = json.load(f)
    for k in ("cpanel", "user", "public_html", "dir", "site_url"):
        if not cfg.get(k):
            raise ValueError("deploy config: липсва „%s“" % k)
    if not re.match(r"^[\w.-]+$", cfg["dir"]) or cfg["dir"].startswith("."):
        raise ValueError("deploy config: dir е едно име на папка (напр. ai-start)")
    token = os.environ.get("CPANEL_TOKEN")
    if not token and cfg.get("token_file"):
        with open(os.path.expanduser(cfg["token_file"]), encoding="utf-8") as f:
            token = f.read().strip()
    if not token:
        raise ValueError("няма токен: token_file в config или CPANEL_TOKEN")
    cfg["_token"] = token
    return cfg


REWRITE_RE = re.compile(r"^\s*(RewriteRule|RewriteCond|Redirect\w*|ErrorDocument|AuthType|Require|Deny|Header)\b.*$",
                        re.M | re.I)


def _get(url, headers=None, data=None, opener=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with (opener or urllib.request.build_opener()).open(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8-sig", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8-sig", "replace")
    except urllib.error.URLError as e:
        return 0, str(e.reason)


def deploy(pkg, cfg, go=False, htaccess_ok=False, test_answer=True, client=None, now=None, log=print,
           wait=lambda s: time.sleep(s)):
    """Връща списък [(стъпка, ок|None, бележка)]; ок None = само план / пропуснато. Нищо не трие."""
    steps = []

    def step(name, ok, note=""):
        steps.append((name, ok, note))
        log("%s %s%s" % ({True: "✓", False: "✗", None: "·"}[ok], name, " — " + note if note else ""))
        return ok

    sha_file = pkg + ".sha256"
    if not os.path.exists(sha_file):
        step("SHA-256 на пакета", False, "няма %s — направи пакета с organizer.py package" % os.path.basename(sha_file))
        return steps
    with open(sha_file, encoding="utf-8") as f:
        want = f.read().split()[0]
    if not step("SHA-256 на пакета", ops.sha256_file(pkg) == want, want[:16] + "…"):
        return steps
    with tarfile.open(pkg) as t:
        names = t.getnames()
    pages = sorted(n for n in names if n.endswith(".html") and "/" not in n)
    if any(n.startswith("/") or ".." in n.split("/") for n in names):
        step("пътищата в пакета", False, "абсолютен път или „..“ — отказвам")
        return steps

    cp = client or Cpanel(cfg["cpanel"], cfg["user"], cfg["_token"])
    root, d = cfg["public_html"].strip("/"), cfg["dir"]
    try:
        listing = cp.list(root)
    except CpanelError as e:
        step("връзка с cPanel", False, str(e))
        return steps
    step("връзка с cPanel", True, "%d неща в %s" % (len(listing), root))

    rules = []
    if ".htaccess" in listing:
        rules = [m.group(0).strip() for m in REWRITE_RE.finditer(cp.read(root, ".htaccess"))]
    note = "няма правила" if not rules else "%d правила — наследяват се от %s/: %s" % (
        len(rules), d, " | ".join(rules[:6]) + (" …" if len(rules) > 6 else ""))
    if rules and not htaccess_ok:
        step(".htaccess на %s" % root, None if not go else False,
             note + (" · прочети ги и пусни с --htaccess-ok" if go else ""))
        if go:
            return steps
    else:
        step(".htaccess на %s" % root, True, note)

    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M")
    archive_name = "_ARHIV_%s_%s" % (d, stamp)
    exists = d in listing
    plan = []
    if exists:
        plan.append("преименувам %s/%s → %s/%s (старото остава)" % (root, d, root, archive_name))
    plan += ["качвам %s в %s/_ARHIV_uploads/" % (os.path.basename(pkg), root),
             "разархивирам в %s/%s (%d файла, %d страници)" % (root, d, len(names), len(pages)),
             "маркер _marker_%s.txt и проверка отвън: %s…?cb=…" % (want[:8], cfg["site_url"]),
             "всички %d страници → 200 (и noindex, ако пакетът е скрит)" % len(pages),
             "тестов отговор" if test_answer else "без тестов отговор (--no-test-answer)",
             "износът: с парола от ORGANIZER_ADMIN_* или проверка, че admin/ иска вход"]
    if not go:
        for p in plan:
            step("план: " + p, None)
        step("нищо не е качено", None, "за качване: --go")
        return steps

    try:
        if exists:
            cp.rename("%s/%s" % (root, d), "%s/%s" % (root, archive_name))
            step("старата папка → %s" % archive_name, True)
        if "_ARHIV_uploads" not in listing:
            cp.mkdir(root, "_ARHIV_uploads")
        cp.upload("%s/_ARHIV_uploads" % root, pkg)
        step("качен пакет", True, os.path.basename(pkg))
        cp.mkdir(root, d)
        cp.extract("%s/_ARHIV_uploads/%s" % (root, os.path.basename(pkg)), "%s/%s" % (root, d))
        got = cp.list("%s/%s" % (root, d))
        missing = [p for p in pages if p not in got]
        if not step("разархивиран в %s/%s" % (root, d), not missing, "липсват: " + ", ".join(missing) if missing else
                    "%d неща" % len(got)):
            return steps
        marker = "_marker_%s.txt" % want[:8]
        cp.save("%s/%s" % (root, d), marker, want)
    except CpanelError as e:
        step("cPanel", False, str(e))
        return steps

    base = cfg["site_url"].rstrip("/") + "/"
    cb = str(int(time.time()))
    ok = False
    for attempt in range(5):
        code, body = _get(base + marker + "?cb=" + cb + str(attempt))
        ok = code == 200 and body.strip() == want
        if ok:
            break
        wait(3)
    if not step("маркерът се вижда отвън", ok, "код %d" % code):
        return steps
    with tarfile.open(pkg) as t:
        hidden = 'content="noindex' in t.extractfile("index.html").read().decode("utf-8", "replace") \
            if "index.html" in names else False
    bad = []
    for p in pages:
        code, body = _get(base + p + "?cb=" + cb)
        if code != 200 or (hidden and 'content="noindex' not in body):
            bad.append("%s (%d%s)" % (p, code, ", без noindex" if code == 200 else ""))
    step("всички страници 200" + (" и noindex" if hidden else ""), not bad,
         ", ".join(bad) if bad else "%d страници" % len(pages))

    if test_answer and "api/forms.json" in names:
        with tarfile.open(pkg) as t:
            spec = json.load(t.extractfile("api/forms.json"))
        fid, form = next(iter(spec["forms"].items()))
        ans = ops.sample_answer(form)
        ans["_form"] = fid
        code, body = _get(base + "api/submit.php", {"Content-Type": "application/json"}, json.dumps(ans).encode())
        step("тестов отговор („%s“)" % form["title"], code == 200 and '"ok":true' in body.replace(" ", ""),
             "код %d · в износа е с текст „QA проба“" % code)
        user, pw = os.environ.get("ORGANIZER_ADMIN_USER"), os.environ.get("ORGANIZER_ADMIN_PASS")
        if user and pw:
            auth = "Basic " + base64.b64encode(("%s:%s" % (user, pw)).encode()).decode()
            code, text = _get(base + "admin/export.php?form=" + urllib.parse.quote(fid), {"Authorization": auth})
            step("износ в CSV", code == 200 and "QA проба" in text, "код %d" % code)
        else:
            code, _ = _get(base + "admin/export.php")
            step("admin/ иска вход", code == 401, "код %d%s" % (code, "" if code == 401 else
                 " · ЗАКЛЮЧИ admin/ СЕГА: cPanel → Directory Privacy" if code == 403 else ""))
    return steps
