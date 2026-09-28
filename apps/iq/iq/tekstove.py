"""Общи текстове: дати по български, проценти, кратки откъси."""
from datetime import date


def den(s):
    d = s if isinstance(s, date) else date.fromisoformat(s)
    return d.strftime("%d.%m.%Y")


def procent(x):
    return "—" if x is None else "%d%%" % round(100 * x)


def chislo(x):
    return "—" if x is None else ("%.1f" % x).replace(".", ",")


def kratko(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def md(s):
    """Екранира знаците, които чупят Markdown таблица или връзка."""
    return (s or "").replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
