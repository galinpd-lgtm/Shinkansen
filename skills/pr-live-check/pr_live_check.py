#!/usr/bin/env python3
"""pr-live-check — изтегля pull request в отделна папка, пуска тестовете, дава отчет до 20 реда.

    pr_live_check.py --pr 12 [--repo .] [--test "КОМАНДА"]... [--live "КОМАНДА"] [--keep]
    pr_live_check.py --ref клон ...

Работната папка е временен клонинг — хранилището, от което се пуска, не се пипа
(нито клонове, нито refs, нито работни файлове). Никога не слива и нищо не качва.

Без --test тестовете се намират сами: всяка папка tests/ с test_*.py →
`python3 -m unittest discover -s tests`; файлове *.test.mjs → `node --test`.
--live пуска още една команда „на живо“ (напр. агентът срещу истински данни) с таймаут.

ВНИМАНИЕ: тестовете и --live изпълняват кода от pull request-а на тази машина.
Пускай само pull request-и, на които вярваш (PROTOCOL.md, т. 1).

Код на изход: 0 — всичко мина · 4 — нещо падна · 2 — грешна употреба · 1 — самата проверка падна.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

MAX_LINES = 20
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "_site"}


def write_summary(text):
    path = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def git(cwd, *args, timeout=600):
    r = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        last = ((r.stderr or r.stdout).strip().splitlines() or ["код %d" % r.returncode])[-1]
        raise RuntimeError("git %s: %s" % (args[0], last))
    return r.stdout.strip()


def checkout(repo, workdir, pr=None, ref=None, remote="origin"):
    """Клонира repo във workdir и превключва на PR/клона от remote. → (sha, заглавие на commit-а)."""
    url = git(repo, "remote", "get-url", remote)
    if not os.path.isabs(url) and "://" not in url and ":" not in url:
        url = os.path.abspath(os.path.join(repo, url))      # относителен път до локално хранилище
    git(repo, "clone", "--quiet", "--no-checkout", repo, workdir)
    if pr is not None:
        git(workdir, "fetch", "--quiet", url, "pull/%d/head" % pr)
    else:
        git(workdir, "fetch", "--quiet", url, ref)
    git(workdir, "checkout", "--quiet", "--detach", "FETCH_HEAD")
    return git(workdir, "rev-parse", "--short=12", "HEAD"), git(workdir, "log", "-1", "--format=%s")


def discover_tests(root):
    """→ [(етикет, команда, папка)] за Python unittest и node --test."""
    found = []
    node_dirs = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel = os.path.relpath(dirpath, root)
        if os.path.basename(dirpath) == "tests" and any(
                f.startswith("test_") and f.endswith(".py") for f in filenames):
            parent = os.path.dirname(dirpath)
            found.append(("unittest " + os.path.relpath(parent, root),
                          [sys.executable, "-m", "unittest", "discover", "-s", "tests"], parent))
        if any(f.endswith(".test.mjs") or f.endswith(".test.js") for f in filenames):
            node_dirs.add(rel)
    for rel in sorted(node_dirs):
        files = sorted(f for f in os.listdir(os.path.join(root, rel))
                       if f.endswith(".test.mjs") or f.endswith(".test.js"))
        found.append(("node " + rel, ["node", "--test"] + files, os.path.join(root, rel)))
    found.sort(key=lambda t: t[0])
    return found


def run_cmd(label, cmd, cwd, timeout):
    """→ {"label", "ok", "code", "secs", "tail"}. Командата е списък или низ за shell."""
    start = time.monotonic()
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True,
                           text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        code, out = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        code = None
        out = ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) \
            + "\n[таймаут след %ds]" % timeout
    except OSError as e:
        code, out = 127, str(e)
    tail = [ln.rstrip() for ln in out.splitlines() if ln.strip()][-4:]
    return {"label": label, "ok": code == 0, "code": code, "secs": time.monotonic() - start, "tail": tail}


def report(title, results, max_lines=MAX_LINES):
    """Отчет до max_lines реда: заглавие, ред на проверка, опашки на падналите, присъда."""
    failed = [r for r in results if not r["ok"]]
    head = [title]
    body = []
    for r in results:
        state = "ok" if r["ok"] else ("ТАЙМАУТ" if r["code"] is None else "ПАДНА (%s)" % r["code"])
        body.append("  %-8s %s  %.1fs" % (state, r["label"], r["secs"]))
    verdict = ("ВСИЧКО МИНА (%d)" % len(results)) if not failed else \
        ("ПАДНАХА %d от %d" % (len(failed), len(results)))
    if not results:
        verdict = "НЯМА ТЕСТОВЕ — нищо не е проверено"
    tails = []
    for r in failed:
        tails += ["  │ %s: %s" % (r["label"], t[:150]) for t in r["tail"]]
    room = max_lines - len(head) - len(body) - 1
    if len(body) > max_lines - 2:                     # твърде много проверки — съкращаваме списъка
        keep = max_lines - 3
        body = body[:keep] + ["  … още %d" % (len(body) - keep)]
        room = 0
    lines = head + body + tails[:max(0, room)] + [verdict]
    return "\n".join(lines[:max_lines])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Изпитай pull request в отделна папка. Никога не слива.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pr", type=int, help="номер на pull request (GitHub: pull/N/head)")
    g.add_argument("--ref", help="клон или ref от отдалеченото хранилище")
    ap.add_argument("--repo", default=".", help="локално хранилище (по подразбиране текущото)")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--test", action="append", help="команда за тестове (може няколко); иначе — сами")
    ap.add_argument("--live", help="команда „на живо“ след тестовете")
    ap.add_argument("--timeout", type=int, default=600, help="секунди на команда")
    ap.add_argument("--keep", action="store_true", help="не трий работната папка")
    a = ap.parse_args(argv)
    if a.pr is not None and a.pr < 1:
        ap.error("номерът на pull request е положително число")
    repo = os.path.abspath(a.repo)
    work = tempfile.mkdtemp(prefix="pr-live-check-")
    try:
        try:
            sha, subject = checkout(repo, os.path.join(work, "src"), a.pr, a.ref, a.remote)
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            print("не можах да изтегля: %s" % e, file=sys.stderr)
            write_summary("изтеглянето падна")
            return 1
        src = os.path.join(work, "src")
        if a.test:
            plan = [("test: " + t, t, src) for t in a.test]
        else:
            plan = discover_tests(src)
        results = [run_cmd(label, cmd, cwd, a.timeout) for label, cmd, cwd in plan]
        if a.live:
            results.append(run_cmd("live: " + a.live, a.live, src, a.timeout))
        what = ("PR #%d" % a.pr) if a.pr is not None else a.ref
        print(report("%s · %s · %s" % (what, sha, subject[:70]), results))
        if a.keep:
            print("работната папка остава: %s" % src)
        failed = sum(1 for r in results if not r["ok"])
        write_summary("%d проверки, %d паднаха" % (len(results), failed) if results else "няма тестове")
        return 4 if failed or not results else 0
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
