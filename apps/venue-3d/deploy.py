"""Страницата на една сграда — сглобяване, пакет и качване в cPanel.

    python3 apps/venue-3d/deploy.py build СГРАДА ИЗХОД [--form]      # папка за качване
    python3 apps/venue-3d/deploy.py package ИЗХОД --out ПАКЕТИ          # детерминиран .tgz и .zip, всеки с .sha256
    python3 apps/venue-3d/deploy.py deploy ПАКЕТ.tgz --config ~/.config/venue3d/deploy.json   # само план
    python3 apps/venue-3d/deploy.py deploy ПАКЕТ.tgz --config … --go [--htaccess-ok]
    (или ПАКЕТ.zip направо — за хостинг, чийто cPanel не разархивира .tgz, напр. SuperHosting;
     при .tgz, който не се разархивира, качването само минава на .zip до него)

СГРАДА е папка извън репото: venue.json и файловете, към които той сочи (model.glb, skeleton.json).
Влиза само това — нищо друго от папката не стига до сървъра.

Пакетът и качването са тези на организатора (apps/organizer: ops.package, deploy.deploy) — същият
cPanel клиент, същата карта: старата папка се преименува на _ARHIV_…, нищо не се трие, проверка отвън.
Config за качването — същият формат (виж apps/organizer/deploy.py); токенът — в token_file или CPANEL_TOKEN.

Отгоре за сградата:
  - status.json (каквото са записали хората на входа) се пренася от старата папка в новата —
    иначе всяко качване би го изтривало;
  - формата за входа (vhod/) се проверява отвън: отговаря ли и има ли config с ПИН-овете
    (~/venue3d_config.php — прави се на сървъра, не идва с пакета).
Код на изход: 0 · 1 грешка · 2 аргументи.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ORGANIZER = os.path.join(os.path.dirname(HERE), "organizer")
sys.path.insert(0, ORGANIZER)
import ops  # noqa: E402  (apps/organizer/ops.py)


def _load_organizer_deploy():
    # по път и под свое име: този файл също се казва deploy.py, а `import deploy` би върнал него
    spec = importlib.util.spec_from_file_location("organizer_deploy", os.path.join(ORGANIZER, "deploy.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


org_deploy = _load_organizer_deploy()

MODEL_MAX = 5 * 1024 * 1024
ID = re.compile(r"^[a-z0-9_]{1,40}$")
TAG = '<venue-3d src="venue.json"></venue-3d>'
FORM_FILES = ("vhod.php", "lib.php", ".htaccess")
ROOT_HTACCESS = """# Сграда в 3D: без списък на папките; status.json — винаги пресен (пише го формата за входа)
Options -Indexes
<IfModule mod_headers.c>
  <Files "status.json">
    Header set Cache-Control "no-store"
  </Files>
</IfModule>
"""


def _rel_file(folder, rel, what, errors):
    """Път от venue.json → файл в папката на сградата (без абсолютни пътища и „..“)."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in rel.replace("\\", "/").split("/") \
            or "://" in rel:
        errors.append(f"{what}: трябва относителен път в папката на сградата, дадено {rel!r}")
        return None
    path = os.path.join(folder, rel)
    if not os.path.isfile(path):
        errors.append(f"{what}: няма файл {rel}")
        return None
    return rel


def check_building(folder):
    """Проверка на папката на сградата преди сглобяване. → (venue, файлове за копиране, errors, warnings)."""
    errors, warnings = [], []
    try:
        with open(os.path.join(folder, "venue.json"), encoding="utf-8") as f:
            venue = json.load(f)
    except (OSError, ValueError) as e:
        return None, [], [f"venue.json: {e}"], warnings
    if not isinstance(venue, dict):
        return None, [], ["venue.json: трябва JSON обект"], warnings
    files = ["venue.json"]
    if venue.get("model"):
        rel = _rel_file(folder, venue["model"], "model", errors)
        if rel:
            files.append(rel)
            size = os.path.getsize(os.path.join(folder, rel))
            if size > MODEL_MAX:
                warnings.append(f"model: {size / 1048576:.1f} MB — над 5 MB; мини го през blender/prepare_glb.py")
    if isinstance(venue.get("skeleton"), str):
        rel = _rel_file(folder, venue["skeleton"], "skeleton", errors)
        if rel:
            files.append(rel)
    if len(files) == 1 and not isinstance(venue.get("skeleton"), dict):
        errors.append("venue.json: няма нито model, нито skeleton — няма какво да се покаже")
    ids = [h.get("id") for h in venue.get("hotspots", []) if isinstance(h, dict)]
    bad = [i for i in ids if not isinstance(i, str) or not ID.match(i)]
    if bad:
        errors.append(f"hotspots: негодни id {bad} (трябва [a-z0-9_])")
    if len(set(ids)) != len(ids):
        errors.append("hotspots: повтарящи се id")
    if "north_deg" in venue and venue["north_deg"] is None:
        warnings.append("north_deg: null — северът не е потвърден (без компас, слънце и сенки)")
    return venue, files, errors, warnings


HIDDEN_META = '<meta name="robots" content="noindex, nofollow">'
HIDDEN_HTACCESS = """
# --hidden: само за който има връзката — търсачките не индексират нищо от папката
<IfModule mod_headers.c>
  Header set X-Robots-Tag "noindex, nofollow"
</IfModule>
"""


def build(folder, out, form=False, refresh=60, hidden=False):
    """Сглобява папката за качване. Не пипа съществуваща непразна папка."""
    venue, files, errors, warnings = check_building(folder)
    if errors:
        raise ValueError("; ".join(errors))
    if os.path.isdir(out) and os.listdir(out):
        raise ValueError(f"{out} не е празна — дай нова папка")
    with open(os.path.join(HERE, "site", "sgrada.html"), encoding="utf-8") as f:
        page = f.read()
    if page.count(TAG) != 1:
        raise ValueError("site/sgrada.html: не намирам <venue-3d src=\"venue.json\"> — сменен ли е шаблонът?")
    if form:
        page = page.replace(TAG, f'<venue-3d src="venue.json" status="status.json" refresh="{int(refresh)}"></venue-3d>')
    if hidden:
        # и в страницата, и в заглавката: качването после проверява отвън, че страницата е с noindex
        page = page.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  ' + HIDDEN_META, 1)
        if HIDDEN_META not in page:
            raise ValueError("site/sgrada.html: няма <meta charset=\"utf-8\"> — не мога да сложа noindex")
    os.makedirs(os.path.join(out, "core"), exist_ok=True)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    for name in sorted(os.listdir(os.path.join(HERE, "core"))):
        if name.endswith(".js"):
            shutil.copy(os.path.join(HERE, "core", name), os.path.join(out, "core", name))
    shutil.copytree(os.path.join(HERE, "vendor", "three"), os.path.join(out, "vendor", "three"))
    for rel in files:
        dest = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy(os.path.join(folder, rel), dest)
    with open(os.path.join(out, ".htaccess"), "w", encoding="utf-8") as f:
        f.write(ROOT_HTACCESS + (HIDDEN_HTACCESS if hidden else ""))
    if form:
        os.makedirs(os.path.join(out, "vhod"))
        for name in FORM_FILES:
            shutil.copy(os.path.join(HERE, "php", name), os.path.join(out, "vhod", name))
    return {"files": files, "warnings": warnings, "form": form, "hidden": hidden}


def after_deploy(pkg_names, cfg, client, archive, log=print, get=None):
    """Стъпките за сградата след качването на организатора. → [(стъпка, ок|None, бележка)]."""
    get = get or org_deploy._get
    steps = []

    def step(name, ok, note=""):
        steps.append((name, ok, note))
        log("%s %s%s" % ({True: "✓", False: "✗", None: "·"}[ok], name, " — " + note if note else ""))
        return ok

    root, d = cfg["public_html"].strip("/"), cfg["dir"]
    new = "%s/%s" % (root, d)
    old = "%s/%s" % (root, archive) if archive else None
    try:
        here = client.list(new)
        if "status.json" in here:
            step("status.json", True, "вече има нов запис от формата — не го пипам")
        elif old and "status.json" in client.list(old):
            client.save(new, "status.json", client.read(old, "status.json"))
            step("status.json пренесен от " + archive, True)
        else:
            step("status.json", None, "още няма — ще се появи с първия запис от формата")
    except org_deploy.CpanelError as e:
        step("status.json", False, str(e))

    base = cfg["site_url"].rstrip("/") + "/"
    cb = "?cb=%d" % int(time.time())
    code, body = get(base + "venue.json" + cb)
    try:
        json.loads(body)
        ok = code == 200
    except ValueError:
        ok = False
    step("venue.json отвън", ok, "код %d" % code)

    if "vhod/vhod.php" in pkg_names:
        code, body = get(base + "vhod/vhod.php" + cb)
        if code == 200 and 'name="pin"' in body:
            step("формата за входа", True, base + "vhod/vhod.php")
        elif "не е настроена" in body or "Няма venue.json" in body:
            step("формата за входа", False, "няма config или пътищата в него не са на тази папка — "
                 "~/venue3d_config.php по php/config.sample.php (venue_json и status_json в %s/)" % new)
        else:
            step("формата за входа", False, "код %d" % code)
        code, _ = get(base + "vhod/lib.php" + cb)
        step("vhod/lib.php не се вика отвън", code in (403, 404) or None,
             "код %d%s" % (code, "" if code in (403, 404) else " — .htaccess не действа? провери на сървъра"))
    return steps


def deploy(pkg, cfg, go=False, htaccess_ok=False, client=None, now=None, log=print, wait=lambda s: time.sleep(s),
           get=None):
    """Качването на организатора (без тестов отговор) + стъпките за сградата."""
    now = now or datetime.now()
    cp = client or org_deploy.Cpanel(cfg["cpanel"], cfg["user"], cfg["_token"])
    root = cfg["public_html"].strip("/")
    try:
        existed = cfg["dir"] in cp.list(root)
    except org_deploy.CpanelError:
        existed = False   # стъпката „връзка с cPanel“ по-долу казва грешката
    # редовете на организатора за въпросниците (тестов отговор, износ) нямат място при сградата
    foreign = ("тестов отговор", "износът", "admin/")
    mine = lambda text: not any(f in text for f in foreign)  # noqa: E731
    steps = org_deploy.deploy(pkg, cfg, go=go, htaccess_ok=htaccess_ok, test_answer=False, client=cp, now=now,
                              log=lambda line: log(line) if mine(line) else None, wait=wait)
    steps = [st for st in steps if mine(st[0])]
    if not go or any(ok is False for _, ok, _ in steps):
        if not go:
            log("· след качването: status.json се пренася от старата папка; проверка на формата за входа")
        return steps
    archive = "_ARHIV_%s_%s" % (cfg["dir"], now.strftime("%Y-%m-%d_%H%M")) if existed else None
    return steps + after_deploy(set(ops.archive_names(pkg)), cfg, cp, archive, log=log, get=get)


def main(argv=None):
    p = argparse.ArgumentParser(prog="deploy.py", description="Страницата на една сграда: сглобяване, пакет, качване.")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="папка за качване от папката на сградата")
    b.add_argument("building")
    b.add_argument("out")
    b.add_argument("--form", action="store_true", help="с формата за входа (vhod/) и status=\"status.json\"")
    b.add_argument("--refresh", type=int, default=60, help="колко често страницата чете status.json, секунди")
    b.add_argument("--hidden", action="store_true", help="само с връзка: noindex в страницата и в заглавките")
    k = sub.add_parser("package", help="детерминиран .tgz и .zip, всеки с .sha256 (както организатора)")
    k.add_argument("site")
    k.add_argument("--out", required=True)
    k.add_argument("--name", default="sgrada")
    k.add_argument("--prev", help="предишният .manifest.txt — за списък на разликите")
    u = sub.add_parser("deploy", help="качване в cPanel (без --go — само план)")
    u.add_argument("package")
    u.add_argument("--config", required=True)
    u.add_argument("--go", action="store_true")
    u.add_argument("--htaccess-ok", action="store_true")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0

    if args.cmd == "build":
        try:
            r = build(args.building, args.out, form=args.form, refresh=args.refresh, hidden=args.hidden)
        except (OSError, ValueError) as e:
            print("build: %s" % e, file=sys.stderr)
            return 1
        for w in r["warnings"]:
            print("WARNING " + w)
        print("OK %s: %s%s%s" % (args.out, ", ".join(r["files"]), " + формата за входа (vhod/)" if r["form"] else "",
                                 " · само с връзка (noindex)" if r["hidden"] else ""))
        return 0
    if args.cmd == "package":
        try:
            r = ops.package(args.site, args.out, name=args.name, prev=args.prev)
        except (OSError, ValueError) as e:
            print("package: %s" % e, file=sys.stderr)
            return 1
        print("%s %s (%d файла, %.2f MB)\n   и %s" % ("вече го има:" if r["existed"] else "OK", r["tgz"], r["files"],
                                                   r["bytes"] / 1048576, r["zip"]))
        return 0
    try:
        cfg = org_deploy.load_config(args.config)
    except (OSError, ValueError) as e:
        print("deploy: %s" % e, file=sys.stderr)
        return 1
    steps = deploy(args.package, cfg, go=args.go, htaccess_ok=args.htaccess_ok)
    return 1 if any(ok is False for _, ok, _ in steps) else 0


if __name__ == "__main__":
    sys.exit(main())
