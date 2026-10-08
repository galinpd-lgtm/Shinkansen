"""Браузър с JavaScript (Playwright) — само като втори опит и само ако е инсталиран.

Пуска се, когато без JavaScript се виждат под 400 знака, при отказ 401/403/429/503 или при изтекло време
(и по изричен флаг — за бутона за отказ в банера). Използването се отбелязва в резултата. UA е нашият.
Ако Playwright липсва, резултатът казва „непроверено“ — нищо не се измисля.
"""
from datetime import datetime, timezone

OTKAZ = ("отказ", "откажи", "отхвърл", "не приемам", "само необходим", "само задължител", "reject", "decline", "deny",
         "refuse", "only necessary", "necessary only", "only essential")

_JS = r"""
(otkaz) => {
  const vidim = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const kandidati = [...document.querySelectorAll('[id],[class],[role=dialog],[aria-modal]')].filter(el => {
    const ime = ((el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '')).toLowerCase();
    const t = (el.innerText || '').toLowerCase();
    return vidim(el) && (/cookie|consent|gdpr|cmp|biskvit/.test(ime) || /бисквитк|cookie/.test(t)) && t.length < 3000;
  });
  if (!kandidati.length) return {banner: false, otkaz: false, tekst: null};
  for (const k of kandidati) {
    for (const b of k.querySelectorAll('button, a, [role=button], input[type=button], input[type=submit]')) {
      const t = ((b.innerText || b.value || '') + '').trim();
      if (vidim(b) && otkaz.some(o => t.toLowerCase().includes(o))) return {banner: true, otkaz: true, tekst: t};
    }
  }
  return {banner: true, otkaz: false, tekst: null};
}
"""


def nalichen():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def zaredi(url, ua, timeout_s):
    """→ речник за снимката. Грешка в браузъра → izpolzvan True, status None, zashto."""
    from playwright.sync_api import sync_playwright
    t = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            ctx = b.new_context(user_agent=ua)
            s = ctx.new_page()
            try:
                otg = s.goto(url, timeout=timeout_s * 1000, wait_until="networkidle")
            except Exception as e:
                return {"izpolzvan": True, "status": None, "url": url, "t": t, "zashto": "браузърът: %s" % e}
            ban = s.evaluate(_JS, list(OTKAZ))
            return {"izpolzvan": True, "status": otg.status if otg else None, "url": s.url, "t": t,
                    "html": s.content(), "banner": ban["banner"], "otkaz_buton": ban["otkaz"] if ban["banner"] else None,
                    "otkaz_tekst": ban["tekst"]}
        finally:
            b.close()
