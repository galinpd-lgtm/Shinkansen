// Живо небе — двигател. ES модул без зависимости и без build стъпка.
//
//   <script type="module" src="core/zhivo-nebe.js"></script>
//   <zhivo-nebe src="forecast.json" lang="bg"></zhivo-nebe>
//
// Чете forecast.json по schema/forecast.schema.md (версия 2). Ако файлът липсва, е празен
// или е по-стар от 3 часа — тегли директно от Open-Meteo (трите модела) и го казва видимо.
// Визията е само през CSS custom properties (--zn-*), за да се вгражда в чужд сайт.
// Чистите функции са изнесени (export), за да се тестват с `node --test` без браузър.

export const SCHEMA_VERSION = '2';
export const MAX_AGE_H = 3;
export const RISK_LEVELS = ['low', 'medium', 'high'];
export const SCENES = ['clear', 'clouds', 'rain', 'storm', 'heat', 'snow'];
// Същите прагове като в config/city.example.json. Трябват само за резервния режим и за
// сцената „сега“ — рискът на дните и събитията идва готов от агента.
export const DEFAULT_THRESHOLDS = {
  high: { precip_pct: 70, gust_kmh: 50, temp_c: 35, thunder: true },
  medium: { precip_pct: 40, wind_kmh: 35, temp_c: 33 },
};
export const OM_MODELS = ['icon_seamless', 'gfs_seamless', 'ecmwf_ifs025'];
const RISK_FIELDS = ['precip_pct', 'wind_kmh', 'gust_kmh', 'temp_c', 'thunder'];
const NUM_FIELDS = ['temp_c', 'precip_pct', 'wind_kmh', 'gust_kmh', 'cloud_pct'];
const SPREAD_FIELDS = { spread_temp: 'temp_c', spread_precip: 'precip_pct', spread_wind: 'wind_kmh' };
const HOUR_MS = 3600e3;

// ------------------------------------------------------------------ сметки (като в agent/fetch.py)

export function median(vals) {
  const v = vals.filter((x) => x != null).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

/** До кое ниво (0/1/2) стига една величина в един час; null, ако я няма. */
export function fieldLevel(r, f, th) {
  const v = r[f];
  if (v == null) return null;
  for (const [lvl, level] of [[2, th.high || {}], [1, th.medium || {}]]) {
    if (f === 'thunder') {
      if (level.thunder && v) return lvl;
    } else if (f in level && v >= level[f]) {
      return lvl;
    }
  }
  return 0;
}

export function riskOf(recs, th, fields = RISK_FIELDS) {
  let best = 0;
  for (const r of recs) for (const f of fields) {
    const l = fieldLevel(r, f, th);
    if (l != null && l > best) best = l;
  }
  return best;
}

/** Колко източника сами стигат ПОНЕ до риска на деня; гласуват само тези, които дават
 *  величината, определила риска. Връща [съгласни, допуснати до гласуване]. */
export function dayAgreement(level, merged, perSource, th) {
  const drivers = level ? RISK_FIELDS.filter((f) => riskOf(merged, th, [f]) === level) : RISK_FIELDS;
  let agree = 0, eligible = 0;
  for (const recs of perSource) {
    const has = drivers.filter((f) => recs.some((r) => r[f] != null));
    if (!recs.length || !has.length) continue;
    eligible += 1;
    const own = riskOf(recs, th, has);
    if (level ? own >= level : own === 0) agree += 1;
  }
  return [agree, eligible];
}

export function confidenceOf(agree, eligible) {
  if (agree <= 1) return 'low';
  if (agree >= 3 && agree >= 0.6 * eligible) return 'high';
  return 'medium';
}

/** Сцена по приоритет: буря, сняг, дъжд, жега, облаци, ясно. */
export function sceneOf(recs, th = DEFAULT_THRESHOLDS) {
  if (!recs.length) return null;
  const med = th.medium || {}, high = th.high || {};
  const gustHigh = high.gust_kmh ?? Infinity;
  if (recs.some((r) => r.thunder || (r.gust_kmh != null && r.gust_kmh >= gustHigh))) return 'storm';
  const wet = recs.filter((r) => r.precip_pct != null && r.precip_pct >= (med.precip_pct ?? 40));
  // в forecast.json няма флаг за сняг — тогава го познаваме по температурата
  const snowy = (r) => (r.snow != null ? r.snow : r.temp_c != null && r.temp_c <= 1);
  if (wet.length && wet.some(snowy)) return 'snow';
  if (wet.length) return 'rain';
  if (recs.some((r) => r.temp_c != null && r.temp_c >= (med.temp_c ?? 33))) return 'heat';
  const clouds = recs.map((r) => r.cloud_pct).filter((x) => x != null);
  if (clouds.length && clouds.reduce((a, b) => a + b, 0) / clouds.length >= 60) return 'clouds';
  return 'clear';
}

/** Годен ли е forecast.json. Връща {ok, reason}; reason: missing | version | empty | stale. */
export function checkForecast(fc, now, maxAgeH = MAX_AGE_H) {
  if (!fc || typeof fc !== 'object') return { ok: false, reason: 'missing' };
  if (String(fc.schema_version) !== SCHEMA_VERSION) return { ok: false, reason: 'version' };
  if (!Array.isArray(fc.hours) || !fc.hours.length || !(fc.sources_ok || []).length) {
    return { ok: false, reason: 'empty' };
  }
  const age = now - Date.parse(fc.generated_at);
  if (!(age <= maxAgeH * HOUR_MS)) return { ok: false, reason: 'stale' };
  return { ok: true, reason: null };
}

/** Височина на слънцето в градуси (приближение, точно до ~1°). */
export function sunElevation(date, lat, lon) {
  const rad = Math.PI / 180;
  const d = date.getTime() / 86400e3 - 10957.5; // дни от J2000.0
  const g = (357.529 + 0.98560028 * d) * rad;
  const q = 280.459 + 0.98564736 * d;
  const L = (q + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * rad;
  const e = (23.439 - 0.00000036 * d) * rad;
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L)) / rad;
  const dec = Math.asin(Math.sin(e) * Math.sin(L));
  const gmst = (18.697374558 + 24.06570982441908 * d) % 24;
  const ha = (gmst * 15 + lon - ra) * rad;
  return Math.asin(Math.sin(lat * rad) * Math.sin(dec) + Math.cos(lat * rad) * Math.cos(dec) * Math.cos(ha)) / rad;
}

export function isDaylight(date, lat, lon) {
  return sunElevation(date, lat, lon) > -0.833; // изгрев/залез с пречупването
}

// ------------------------------------------------------------------ резервен режим: Open-Meteo

export function openMeteoUrl(lat, lon) {
  const q = new URLSearchParams({
    latitude: lat, longitude: lon, models: OM_MODELS.join(','), timezone: 'auto', forecast_days: 3,
    hourly: 'temperature_2m,precipitation_probability,wind_speed_10m,wind_gusts_10m,cloud_cover,weather_code',
  });
  return `https://api.open-meteo.com/v1/forecast?${q}`;
}

function isoWithOffset(localNoZone, offsetSec) {
  const sign = offsetSec < 0 ? '-' : '+';
  const a = Math.abs(offsetSec);
  const hh = String(Math.floor(a / 3600)).padStart(2, '0');
  const mm = String(Math.floor((a % 3600) / 60)).padStart(2, '0');
  return `${localNoZone}${sign}${hh}:${mm}`;
}

/** Отговор на Open-Meteo с три модела → обект във формата на forecast.json v2 (+ mode: 'fallback').
 *  Всяка величина — само от моделите, които я дават; риск, съгласие и увереност — като агента. */
export function fromOpenMeteo(data, { thresholds = DEFAULT_THRESHOLDS, events = [], city = '', now = Date.now(),
  before_h = 1, after_h = 3 } = {}) {
  const h = data.hourly;
  const off = data.utc_offset_seconds || 0;
  const col = (name, m) => h[`${name}_${m}`] || (OM_MODELS.length === 1 ? h[name] : null) || [];
  const perModel = {};
  for (const m of OM_MODELS) {
    const temp = col('temperature_2m', m), prob = col('precipitation_probability', m);
    const wind = col('wind_speed_10m', m), gust = col('wind_gusts_10m', m);
    const cloud = col('cloud_cover', m), code = col('weather_code', m);
    const recs = {};
    h.time.forEach((t, i) => {
      const r = { temp_c: temp[i] ?? null, precip_pct: prob[i] ?? null, wind_kmh: wind[i] ?? null,
        gust_kmh: gust[i] ?? null, cloud_pct: cloud[i] ?? null,
        thunder: [95, 96, 99].includes(code[i]), snow: [71, 73, 75, 77, 85, 86].includes(code[i]) };
      // модел участва в час само ако има поне една собствена стойност
      if (NUM_FIELDS.some((f) => r[f] != null)) recs[t] = r;
    });
    if (Object.keys(recs).length) perModel[m] = recs;
  }
  const models = Object.keys(perModel);
  const hours = h.time.filter((t) => models.some((m) => perModel[m][t])).map((t) => {
    const recs = models.map((m) => perModel[m][t]).filter(Boolean);
    const out = { t: isoWithOffset(t, off) };
    for (const f of NUM_FIELDS) out[f] = median(recs.map((r) => r[f]));
    const need = Math.max(1, Math.ceil(recs.length / 3));
    out.thunder = recs.filter((r) => r.thunder).length >= need;
    out.snow = recs.filter((r) => r.snow).length >= need;
    for (const [k, f] of Object.entries(SPREAD_FIELDS)) {
      const v = recs.map((r) => r[f]).filter((x) => x != null);
      out[k] = v.length >= 2 ? Math.round((Math.max(...v) - Math.min(...v)) * 10) / 10 : null;
    }
    out._local = t;
    return out;
  });
  const byDay = new Map();
  for (const hr of hours) {
    const d = hr.t.slice(0, 10);
    if (!byDay.has(d)) byDay.set(d, []);
    byDay.get(d).push(hr);
  }
  const days = [...byDay].map(([date, hs]) => {
    const level = riskOf(hs, thresholds);
    const per = models.map((m) => hs.map((hr) => perModel[m][hr._local]).filter(Boolean));
    const [agree, eligible] = dayAgreement(level, hs, per, thresholds);
    return { date, risk: RISK_LEVELS[level], agreement: agree, confidence: confidenceOf(agree, eligible) };
  });
  for (const hr of hours) delete hr._local;
  const evs = events.map((ev) => {
    const t0 = Date.parse(ev.start);
    const from = Math.floor((t0 - before_h * HOUR_MS) / HOUR_MS) * HOUR_MS, to = t0 + after_h * HOUR_MS;
    const recs = hours.filter((hr) => { const x = Date.parse(hr.t); return x >= from && x < to; });
    return { title: ev.title, start: ev.start, risk: recs.length ? RISK_LEVELS[riskOf(recs, thresholds)] : null,
      scene: recs.length ? sceneOf(recs, thresholds) : null, _end: to };
  }).filter((e) => e._end > now).map(({ _end, ...e }) => e);
  return {
    schema_version: SCHEMA_VERSION, generated_at: new Date(now).toISOString(), city,
    lat: data.latitude, lon: data.longitude,
    sources_ok: models.map((m) => `open-meteo:${m}`), sources_failed: [],
    hours, days, events: evs, summary: '', mode: 'fallback',
  };
}

// ------------------------------------------------------------------ какво да покажем

export function nextHours(fc, now, n = 24) {
  const from = Math.floor(now / HOUR_MS) * HOUR_MS;
  return fc.hours.filter((h) => Date.parse(h.t) >= from).slice(0, n);
}

/** Фокус на сцената: най-близкото предстоящо събитие (до края на прозореца му) или „сега“. */
export function pickFocus(fc, now, th = DEFAULT_THRESHOLDS, after_h = 3) {
  const upcoming = (fc.events || [])
    .filter((e) => Date.parse(e.start) + after_h * HOUR_MS > now)
    .sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
  const ev = upcoming[0] || null;
  if (ev && ev.scene) return { kind: 'event', event: ev, scene: ev.scene, at: new Date(Date.parse(ev.start)) };
  const soon = nextHours(fc, now, 3);
  return { kind: 'now', event: ev, scene: sceneOf(soon, th) || 'clear', at: new Date(now) };
}

// ------------------------------------------------------------------ текстове

const T = {
  bg: {
    scene: { clear: 'ясно', clouds: 'облачно', rain: 'дъжд', storm: 'буря', heat: 'жега', snow: 'сняг' },
    risk: { low: 'нисък', medium: 'среден', high: 'висок' },
    conf: { low: 'ниска', medium: 'средна', high: 'висока' },
    wd: ['нд', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'],
    now: 'Сега', next24: 'Следващите 24 часа', legend: '°C · вероятност за валеж · пориви km/h (или среден вятър, ако няма пориви)', days: 'Дни', events: 'Прояви',
    noEvents: 'Няма предстоящи прояви в конфигурацията.',
    beyond: 'още извън хоризонта на прогнозата',
    risk_: 'риск', confidence: 'увереност', agree: (n) => `${n} изт.`,
    weak: 'само един източник — не се ескалира',
    updated: 'Обновено', ago: (m) => (m < 1 ? 'току-що' : m < 60 ? `преди ${m} мин` : `преди ${Math.round(m / 60)} ч`),
    sources: 'източници', failed: 'без данни от',
    fb: {
      missing: 'файлът с прогнозата липсва', version: 'файлът е по друга версия на схемата',
      empty: 'агентът не е получил данни', stale: 'файлът е по-стар от 3 часа',
    },
    fallback: (why) => `Резервен режим: ${why}, затова прогнозата е директно от Open-Meteo (3 модела). MET Norway и 7Timer не участват.`,
    staleOnly: (why) => `Внимание: ${why}, а резервният източник не отговаря. Показва се последната налична прогноза.`,
    error: 'В момента няма прогноза — нито файлът, нито резервният източник отговарят.',
    loading: 'Зареждане на прогнозата…',
    nextEvent: (e, when, risk, scene) => `Следваща проява: „${e}“ на ${when} — риск ${risk}, ${scene}.`,
    nextEventBeyond: (e, when) => `Следваща проява: „${e}“ на ${when} — още извън хоризонта на прогнозата.`,
    riskyDays: (list) => `Внимание: ${list}.`,
    calm: (n, unsure) => `Без ${unsure ? 'потвърдени ' : ''}рискови дни в следващите ${n} дни.`,
    trafficLabel: (r) => `Риск: ${r}`, unknown: 'няма оценка',
    nowScene: 'сега', at: 'от', thunder: 'гръмотевици', gust: 'пориви', wind: 'вятър', rain: 'валеж',
  },
  en: {
    scene: { clear: 'clear', clouds: 'cloudy', rain: 'rain', storm: 'storm', heat: 'heat', snow: 'snow' },
    risk: { low: 'low', medium: 'medium', high: 'high' },
    conf: { low: 'low', medium: 'medium', high: 'high' },
    wd: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    now: 'Now', next24: 'Next 24 hours', legend: '°C · chance of precipitation · gusts km/h (or mean wind if no gusts)', days: 'Days', events: 'Events',
    noEvents: 'No upcoming events in the configuration.',
    beyond: 'not yet within the forecast range',
    risk_: 'risk', confidence: 'confidence', agree: (n) => `${n} src.`,
    weak: 'single source only — not escalated',
    updated: 'Updated', ago: (m) => (m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`),
    sources: 'sources', failed: 'no data from',
    fb: {
      missing: 'the forecast file is missing', version: 'the file uses another schema version',
      empty: 'the agent received no data', stale: 'the file is older than 3 hours',
    },
    fallback: (why) => `Fallback mode: ${why}, so the forecast comes straight from Open-Meteo (3 models). MET Norway and 7Timer are not included.`,
    staleOnly: (why) => `Warning: ${why} and the fallback source is not responding. Showing the last available forecast.`,
    error: 'No forecast right now — neither the file nor the fallback source responds.',
    loading: 'Loading the forecast…',
    nextEvent: (e, when, risk, scene) => `Next event: “${e}” on ${when} — ${risk} risk, ${scene}.`,
    nextEventBeyond: (e, when) => `Next event: “${e}” on ${when} — not yet within the forecast range.`,
    riskyDays: (list) => `Watch: ${list}.`,
    calm: (n, unsure) => `No ${unsure ? 'confirmed ' : ''}risky days in the next ${n} days.`,
    trafficLabel: (r) => `Risk: ${r}`, unknown: 'no rating',
    nowScene: 'now', at: 'at', thunder: 'thunder', gust: 'gusts', wind: 'wind', rain: 'precip.',
  },
};

export function texts(lang) { return T[lang] || T.bg; }

const ddmm = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
const hhmm = (iso) => iso.slice(11, 16);
const weekday = (date, tx) => { const [y, m, d] = date.split('-').map(Number); return tx.wd[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]; };

/** Кратък текст по правила — на езика на страницата, и в резервния режим. */
export function summaryText(fc, focus, lang = 'bg') {
  const tx = texts(lang);
  const parts = [];
  const ev = focus.event;
  if (ev) {
    const when = `${ddmm(ev.start)} ${tx.at} ${hhmm(ev.start)}`;
    parts.push(ev.risk ? tx.nextEvent(ev.title, when, tx.risk[ev.risk], tx.scene[ev.scene])
      : tx.nextEventBeyond(ev.title, when));
  }
  const days = fc.days || [];
  const risky = days.filter((d) => d.risk !== 'low' && d.confidence !== 'low');
  if (risky.length) parts.push(tx.riskyDays(risky.map((d) => `${ddmm(d.date)} (${tx.risk[d.risk]})`).join(', ')));
  else if (days.length) parts.push(tx.calm(days.length, days.some((d) => d.risk !== 'low')));
  return parts.join(' ');
}

// ------------------------------------------------------------------ небето (Canvas)

function rand(a, b) { return a + Math.random() * (b - a); }

class Sky {
  constructor(canvas, host) {
    this.c = canvas; this.ctx = canvas.getContext('2d'); this.host = host;
    this.scene = 'clear'; this.day = true; this.t = 0; this.raf = 0; this.flash = 0;
    this.reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => this.resize()) : null;
    this.ro?.observe(canvas);
    this.onVis = () => (document.hidden ? this.stop() : this.start());
    document.addEventListener('visibilitychange', this.onVis);
  }

  resize() {
    const r = this.c.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = Math.max(1, r.width); this.h = Math.max(1, r.height);
    this.c.width = Math.round(this.w * dpr); this.c.height = Math.round(this.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.seed();
    if (this.reduced) this.frame();
  }

  set(scene, day) { this.scene = scene; this.day = day; this.seed(); this.start(); }

  seed() {
    const w = this.w || 600, h = this.h || 240;
    const many = { rain: 120, storm: 220, snow: 90 }[this.scene] || 0;
    this.drops = Array.from({ length: many }, () => ({ x: rand(0, w), y: rand(0, h), v: rand(0.6, 1), r: rand(1, 3) }));
    this.stars = Array.from({ length: 70 }, () => ({ x: rand(0, w), y: rand(0, h * 0.7), p: rand(0, 6.3) }));
    const nClouds = { clear: 0, heat: 0, clouds: 6, rain: 5, storm: 5, snow: 4 }[this.scene];
    this.clouds = Array.from({ length: nClouds }, (_, i) => ({ x: (i / nClouds) * w * 1.2 - 60, y: rand(10, h * 0.45), s: rand(0.7, 1.3), v: rand(0.08, 0.2) }));
  }

  start() {
    if (this.raf || !this.w) return;
    if (this.reduced) { this.frame(); return; }
    const loop = () => { this.t += 1; this.frame(); this.raf = requestAnimationFrame(loop); };
    this.raf = requestAnimationFrame(loop);
  }

  stop() { cancelAnimationFrame(this.raf); this.raf = 0; }

  destroy() { this.stop(); this.ro?.disconnect(); document.removeEventListener('visibilitychange', this.onVis); }

  color(name, fallback) {
    return getComputedStyle(this.host).getPropertyValue(name).trim() || fallback;
  }

  frame() {
    const { ctx, w, h, t } = this;
    if (!w) return;
    ctx.clearRect(0, 0, w, h);
    const particle = this.color('--zn-particle', 'rgba(255,255,255,.75)');
    const sc = this.scene;
    if (!this.day && (sc === 'clear' || sc === 'heat' || sc === 'clouds')) this.drawStars(particle);
    if (sc === 'clear' || sc === 'heat') this.day ? this.drawSun(sc === 'heat') : this.drawMoon();
    if (sc === 'heat' && this.day) this.drawShimmer();
    if (this.clouds.length) this.drawClouds(sc === 'rain' || sc === 'storm');
    if (sc === 'rain' || sc === 'storm') this.drawRain(particle, sc === 'storm');
    if (sc === 'snow') this.drawSnow(particle);
    if (sc === 'storm') this.drawLightning();
  }

  drawSun(hot) {
    const { ctx, w, h } = this;
    const x = w * 0.8, y = h * 0.32, r = hot ? 38 : 30;
    const g = ctx.createRadialGradient(x, y, r * 0.3, x, y, r * (hot ? 4 : 3));
    g.addColorStop(0, hot ? 'rgba(255,236,170,.95)' : 'rgba(255,248,210,.95)');
    g.addColorStop(0.25, hot ? 'rgba(255,190,90,.45)' : 'rgba(255,240,190,.35)');
    g.addColorStop(1, 'rgba(255,220,150,0)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = hot ? '#fff1c4' : '#fffbe8';
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  }

  drawMoon() {
    const { ctx, w, h } = this;
    const x = w * 0.8, y = h * 0.3;
    const g = ctx.createRadialGradient(x, y, 10, x, y, 80);
    g.addColorStop(0, 'rgba(230,236,255,.35)'); g.addColorStop(1, 'rgba(230,236,255,0)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#eef1fa'; ctx.beginPath(); ctx.arc(x, y, 18, 0, Math.PI * 2); ctx.fill();
  }

  drawStars(color) {
    const { ctx, t } = this;
    ctx.fillStyle = color;
    for (const s of this.stars) {
      ctx.globalAlpha = 0.35 + 0.35 * Math.sin(s.p + t * 0.03);
      ctx.fillRect(s.x, s.y, 1.5, 1.5);
    }
    ctx.globalAlpha = 1;
  }

  drawShimmer() {
    const { ctx, w, h, t } = this;
    ctx.strokeStyle = 'rgba(255,255,255,.18)'; ctx.lineWidth = 2;
    for (let k = 0; k < 5; k++) {
      const y0 = h * (0.62 + k * 0.08);
      ctx.beginPath();
      for (let x = 0; x <= w; x += 8) {
        const y = y0 + Math.sin(x * 0.03 + t * 0.05 + k) * 3;
        x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke();
    }
  }

  drawClouds(dark) {
    const { ctx, w } = this;
    ctx.fillStyle = dark ? (this.day ? 'rgba(70,80,95,.55)' : 'rgba(40,46,58,.7)')
      : (this.day ? 'rgba(255,255,255,.55)' : 'rgba(150,160,180,.22)');
    for (const c of this.clouds) {
      if (!this.reduced) c.x += c.v;
      if (c.x > w + 120) c.x = -160;
      const s = c.s;
      ctx.beginPath();
      for (const [dx, dy, r] of [[0, 0, 28], [30, -14, 34], [64, 0, 28], [34, 8, 30], [-24, 8, 20]]) {
        ctx.moveTo(c.x + dx * s + r * s, c.y + dy * s);
        ctx.arc(c.x + dx * s, c.y + dy * s, r * s, 0, Math.PI * 2);
      }
      ctx.fill();
    }
  }

  drawRain(color, heavy) {
    const { ctx, w, h } = this;
    ctx.strokeStyle = color; ctx.lineWidth = heavy ? 1.4 : 1; ctx.globalAlpha = 0.6;
    ctx.beginPath();
    for (const d of this.drops) {
      if (!this.reduced) { d.y += (heavy ? 14 : 9) * d.v; d.x -= (heavy ? 3 : 1.5) * d.v; }
      if (d.y > h) { d.y = -20; d.x = rand(0, w + 40); }
      const len = (heavy ? 18 : 12) * d.v;
      ctx.moveTo(d.x, d.y); ctx.lineTo(d.x - len * 0.2, d.y + len);
    }
    ctx.stroke(); ctx.globalAlpha = 1;
  }

  drawSnow(color) {
    const { ctx, w, h, t } = this;
    ctx.fillStyle = color;
    for (const d of this.drops) {
      if (!this.reduced) { d.y += 0.8 * d.v; d.x += Math.sin(t * 0.02 + d.r * 3) * 0.4; }
      if (d.y > h) { d.y = -5; d.x = rand(0, w); }
      ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2); ctx.fill();
    }
  }

  drawLightning() {
    const { ctx, w, h } = this;
    if (!this.reduced && this.flash <= 0 && Math.random() < 0.006) {
      this.flash = 1;
      this.bolt = [[rand(w * 0.2, w * 0.8), 0]];
      while (this.bolt.at(-1)[1] < h * 0.8) {
        const [x, y] = this.bolt.at(-1);
        this.bolt.push([x + rand(-25, 25), y + rand(15, 35)]);
      }
    }
    if (this.flash > 0) {
      ctx.fillStyle = `rgba(255,255,255,${0.35 * this.flash})`; ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = `rgba(255,255,240,${this.flash})`; ctx.lineWidth = 2;
      ctx.beginPath(); this.bolt.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke();
      this.flash -= 0.06;
    }
  }
}

// ------------------------------------------------------------------ уеб компонентът

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (v, d = 0) => (v == null ? '—' : Number(v).toFixed(d));

const STYLE = `
:host {
  display: block; container-type: inline-size;
  font-family: var(--zn-font, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif);
  color: var(--zn-fg, #1d232b);
  --_card: var(--zn-card, #ffffff);
  --_border: var(--zn-border, rgba(0,0,0,.1));
  --_muted: var(--zn-muted, #5f6b78);
  --_accent: var(--zn-accent, #2f6fbd);
  --_radius: var(--zn-radius, 14px);
  --_low: var(--zn-risk-low, #2e9d5b);
  --_medium: var(--zn-risk-medium, #e0a100);
  --_high: var(--zn-risk-high, #d2402f);
  --_none: var(--zn-risk-none, #9aa4af);
  --_top: #4a90d9; --_bottom: #bfe0f7;
}
:host([data-scene="clear"][data-daylight="night"]) { --_top: #0b1530; --_bottom: #24345f; }
:host([data-scene="clouds"][data-daylight="day"])  { --_top: #7d8ea3; --_bottom: #cdd6df; }
:host([data-scene="clouds"][data-daylight="night"]){ --_top: #161c28; --_bottom: #333d50; }
:host([data-scene="rain"][data-daylight="day"])    { --_top: #4d5b6a; --_bottom: #8e9aa7; }
:host([data-scene="rain"][data-daylight="night"])  { --_top: #10151d; --_bottom: #28323f; }
:host([data-scene="storm"][data-daylight="day"])   { --_top: #2a303b; --_bottom: #59616e; }
:host([data-scene="storm"][data-daylight="night"]) { --_top: #06080d; --_bottom: #1c212c; }
:host([data-scene="heat"][data-daylight="day"])    { --_top: #e8893a; --_bottom: #fbdca0; }
:host([data-scene="heat"][data-daylight="night"])  { --_top: #2d1a2a; --_bottom: #6a3a3a; }
:host([data-scene="snow"][data-daylight="day"])    { --_top: #9fb0c2; --_bottom: #e9eef4; }
:host([data-scene="snow"][data-daylight="night"])  { --_top: #19212f; --_bottom: #3b4759; }
* { box-sizing: border-box; }
.zn { background: var(--zn-bg, transparent); border-radius: var(--_radius); }
.sky {
  position: relative; overflow: hidden; border-radius: var(--_radius);
  height: var(--zn-sky-height, 260px);
  background: linear-gradient(180deg, var(--zn-sky-top, var(--_top)), var(--zn-sky-bottom, var(--_bottom)));
  transition: background .8s;
}
canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
.sky-text {
  position: absolute; inset: auto 0 0 0; padding: 18px 20px; display: flex; gap: 16px;
  align-items: flex-end; justify-content: space-between;
  color: var(--zn-sky-fg, #fff); text-shadow: 0 1px 3px rgba(0,0,0,.45);
  /* тъмно преливане под текста — да се чете и върху светло небе (жега, сняг) */
  background: linear-gradient(180deg, transparent, var(--zn-sky-scrim, rgba(0,0,0,.38)));
  padding-top: 48px;
}
.sky-text h2 { margin: 0; font-size: 1.5rem; line-height: 1.15; font-weight: 650; }
.sky-text p { margin: 4px 0 0; opacity: .95; }
.light {
  display: grid; gap: 6px; padding: 8px; border-radius: 999px; flex: none;
  background: rgba(0,0,0,.45); box-shadow: 0 2px 8px rgba(0,0,0,.25);
}
.light i { width: 18px; height: 18px; border-radius: 50%; background: rgba(255,255,255,.14); display: block; }
.light[data-risk="high"] .r, .light[data-risk="medium"] .y, .light[data-risk="low"] .g { box-shadow: 0 0 10px currentColor; }
.light[data-risk="high"] .r { background: var(--_high); color: var(--_high); }
.light[data-risk="medium"] .y { background: var(--_medium); color: var(--_medium); }
.light[data-risk="low"] .g { background: var(--_low); color: var(--_low); }
.notice {
  margin: 12px 0 0; padding: 10px 14px; border-radius: calc(var(--_radius) * .6);
  background: var(--zn-warn-bg, #fff4d6); color: var(--zn-warn-fg, #5a4300);
  border: 1px solid var(--zn-warn-border, #f0d48a); font-size: .92rem;
}
.summary { margin: 14px 2px 0; font-size: 1rem; }
section { margin-top: 14px; background: var(--_card); border: 1px solid var(--_border); border-radius: var(--_radius); padding: 14px; }
h3 { margin: 0 0 10px; font-size: .8rem; letter-spacing: .06em; text-transform: uppercase; color: var(--_muted); font-weight: 600; }
.hours { display: flex; gap: 4px; overflow-x: auto; padding-bottom: 6px; scrollbar-width: thin; }
.hour { flex: 0 0 52px; text-align: center; font-size: .82rem; display: grid; gap: 3px; justify-items: center; }
.hour b { font-size: .95rem; }
.hour .t { color: var(--_muted); }
.bar { width: 10px; height: 36px; border-radius: 5px; background: var(--_border); position: relative; overflow: hidden; }
.bar span { position: absolute; inset: auto 0 0 0; background: var(--_accent); }
.hour[data-risk="medium"] b { color: var(--_medium); }
.hour[data-risk="high"] b { color: var(--_high); }
.bolt { color: var(--_high); font-weight: 700; }
ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
li { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.dot { width: 12px; height: 12px; border-radius: 50%; flex: none; background: var(--_none); }
.dot[data-risk="low"] { background: var(--_low); }
.dot[data-risk="medium"] { background: var(--_medium); }
.dot[data-risk="high"] { background: var(--_high); }
.weak { opacity: .6; }
.muted { color: var(--_muted); font-size: .88rem; }
.date { min-width: 5.6em; font-variant-numeric: tabular-nums; }
.legend { margin: 6px 0 0; font-size: .78rem; }
.foot { margin: 12px 2px 0; font-size: .82rem; color: var(--_muted); }
@container (max-width: 480px) {
  .sky-text h2 { font-size: 1.2rem; }
  .sky-text { padding: 14px; }
}
`;

function defineElement() {
  class ZhivoNebe extends HTMLElement {
    static get observedAttributes() { return ['src', 'lang', 'now']; }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' }).innerHTML = `<style>${STYLE}</style>
        <div class="zn" part="root">
          <div class="sky" part="sky"><canvas aria-hidden="true"></canvas><div class="sky-text"></div></div>
          <div class="notice" part="notice" role="status" hidden></div>
          <p class="summary" part="summary"></p>
          <div class="panels"></div>
          <p class="foot" part="footer"></p>
        </div>`;
      this.$ = (s) => this.shadowRoot.querySelector(s);
      this.fc = null;
    }

    connectedCallback() {
      this.sky = new Sky(this.$('canvas'), this);
      this.$('.summary').textContent = texts(this.lang_).loading;
      this.load();
      this.timer = setInterval(() => this.load(), 30 * 60e3); // презареждане на 30 мин
    }

    disconnectedCallback() { clearInterval(this.timer); this.sky?.destroy(); }

    attributeChangedCallback(name, old, val) {
      if (!this.isConnected || old === val) return;
      if (name === 'lang' && this.fc) this.render(); else this.load();
    }

    get lang_() { return (this.getAttribute('lang') || document.documentElement.lang || 'bg').slice(0, 2); }

    now() { const n = this.getAttribute('now'); return n ? Date.parse(n) : Date.now(); }

    num(name, fallback) { const v = parseFloat(this.getAttribute(name)); return Number.isFinite(v) ? v : fallback; }

    thresholds() {
      try { return JSON.parse(this.getAttribute('thresholds')) || DEFAULT_THRESHOLDS; } catch { return DEFAULT_THRESHOLDS; }
    }

    async load() {
      // ако докато чакаме мрежата започне ново зареждане, този резултат е остарял
      const seq = (this.seq = (this.seq || 0) + 1);
      const stale = () => seq !== this.seq;
      const now = this.now();
      let file = null;
      const src = this.getAttribute('src');
      if (src) {
        try {
          const r = await fetch(src, { cache: 'no-store' });
          if (r.ok) file = await r.json();
        } catch { /* няма файл — минаваме на резервния режим */ }
      }
      if (stale()) return;
      const check = checkForecast(file, now, this.num('max-age-h', MAX_AGE_H));
      if (check.ok) { this.fc = { ...file, mode: 'file' }; this.render(); return; }

      const lat = this.num('lat', file?.lat), lon = this.num('lon', file?.lon);
      try {
        if (lat == null || lon == null) throw new Error('няма координати');
        const r = await fetch(openMeteoUrl(lat, lon));
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        if (stale()) return;
        this.fc = fromOpenMeteo(data, {
          thresholds: this.thresholds(), events: file?.events || [], now,
          city: this.getAttribute('city') || file?.city || '',
          before_h: this.num('before-h', 1), after_h: this.num('after-h', 3),
        });
      } catch {
        if (stale()) return;
        this.fc = file?.hours?.length ? { ...file, mode: 'stale' } : { mode: 'error', hours: [], days: [], events: [] };
      }
      this.fc.reason = check.reason;
      this.render();
    }

    render() {
      const fc = this.fc, tx = texts(this.lang_), now = this.now(), th = this.thresholds();
      this.dataset.mode = fc.mode;
      const notice = this.$('.notice');
      notice.hidden = fc.mode === 'file';
      if (fc.mode === 'fallback') notice.textContent = tx.fallback(tx.fb[fc.reason]);
      if (fc.mode === 'stale') notice.textContent = tx.staleOnly(tx.fb[fc.reason]);
      if (fc.mode === 'error') {
        notice.textContent = tx.error;
        this.dataset.scene = 'clouds'; this.dataset.daylight = 'day';
        this.sky.set('clouds', true);
        this.$('.sky-text').innerHTML = `<div><h2>${esc(this.getAttribute('city') || '')}</h2></div>`;
        this.$('.summary').textContent = ''; this.$('.panels').innerHTML = ''; this.$('.foot').textContent = '';
        return;
      }

      const focus = pickFocus(fc, now, th, this.num('after-h', 3));
      const day = fc.lat != null ? isDaylight(focus.at, fc.lat, fc.lon) : true;
      this.dataset.scene = focus.scene; this.dataset.daylight = day ? 'day' : 'night';
      this.sky.set(focus.scene, day);

      const ev = focus.kind === 'event' ? focus.event : null;
      const risk = ev ? ev.risk : null;
      const title = ev ? esc(ev.title) : tx.now;
      const sub = ev ? `${ddmm(ev.start)} ${tx.at} ${hhmm(ev.start)} · ${tx.scene[ev.scene]}`
        : `${tx.scene[focus.scene]}`;
      this.$('.sky-text').innerHTML = `
        <div><p>${esc(fc.city)}</p><h2>${title}</h2><p>${esc(sub)}</p></div>
        ${ev ? this.light(risk, tx) : ''}`;
      this.$('.summary').textContent = summaryText(fc, focus, this.lang_);

      const hrs = nextHours(fc, now, 24).map((h) => {
        const lvl = RISK_LEVELS[riskOf([h], th)];
        const tip = `${hhmm(h.t)} · ${fmt(h.temp_c, 1)} °C · ${tx.rain} ${fmt(h.precip_pct)} % · ${tx.wind} ${fmt(h.wind_kmh)} · ${tx.gust} ${fmt(h.gust_kmh)} km/h`
          + (h.spread_temp != null ? ` · ±${h.spread_temp} °C` : '');
        return `<div class="hour" data-risk="${lvl}" title="${esc(tip)}">
          <span class="t">${hhmm(h.t)}</span><b>${fmt(h.temp_c)}°</b>
          <span class="bar" aria-label="${tx.rain} ${fmt(h.precip_pct)} %"><span style="height:${h.precip_pct ?? 0}%"></span></span>
          <span class="muted">${fmt(h.precip_pct)}%</span>
          <span class="muted">${fmt(h.gust_kmh ?? h.wind_kmh)}</span>
          ${h.thunder ? `<span class="bolt" title="${tx.thunder}">ϟ</span>` : ''}
        </div>`;
      }).join('');

      const days = (fc.days || []).map((d) => {
        const weak = d.risk !== 'low' && d.confidence === 'low';
        return `<li class="${weak ? 'weak' : ''}"><span class="dot" data-risk="${d.risk}"></span>
          <span class="date">${weekday(d.date, tx)} ${ddmm(d.date)}</span>
          <span>${tx.risk_} ${tx.risk[d.risk]}</span>
          <span class="muted">${tx.confidence} ${tx.conf[d.confidence] || '—'} · ${tx.agree(d.agreement)}</span>
          ${weak ? `<span class="muted">${tx.weak}</span>` : ''}</li>`;
      }).join('');

      const evs = (fc.events || []).filter((e) => Date.parse(e.start) + this.num('after-h', 3) * HOUR_MS > now);
      const evHtml = evs.length ? `<ul>${evs.map((e) => `<li>${this.light(e.risk, tx, true)}
          <span class="date">${ddmm(e.start)} ${hhmm(e.start)}</span><b>${esc(e.title)}</b>
          <span class="muted">${e.risk ? `${tx.risk_} ${tx.risk[e.risk]} · ${tx.scene[e.scene]}` : tx.beyond}</span></li>`).join('')}</ul>`
        : `<p class="muted">${tx.noEvents}</p>`;

      this.$('.panels').innerHTML = `
        <section part="hours"><h3>${tx.next24}</h3><div class="hours">${hrs}</div><p class="muted legend">${tx.legend}</p></section>
        <section part="days"><h3>${tx.days}</h3><ul>${days}</ul></section>
        <section part="events"><h3>${tx.events}</h3>${evHtml}</section>`;

      const mins = Math.max(0, Math.round((now - Date.parse(fc.generated_at)) / 60e3));
      const failed = (fc.sources_failed || []).length ? ` · ${tx.failed}: ${fc.sources_failed.join(', ')}` : '';
      this.$('.foot').textContent = `${tx.updated}: ${tx.ago(mins)} · ${tx.sources}: `
        + `${(fc.sources_ok || []).join(', ')}${failed}`;
    }

    light(risk, tx, small = false) {
      const label = tx.trafficLabel(risk ? tx.risk[risk] : tx.unknown);
      if (small) return `<span class="dot" data-risk="${risk || 'none'}" role="img" aria-label="${esc(label)}"></span>`;
      return `<div class="light" data-risk="${risk || 'none'}" role="img" aria-label="${esc(label)}" part="traffic-light">
        <i class="r"></i><i class="y"></i><i class="g"></i></div>`;
    }
  }
  if (!customElements.get('zhivo-nebe')) customElements.define('zhivo-nebe', ZhivoNebe);
}

// в браузъра регистрираме елемента; в Node (тестовете) — само чистите функции
if (typeof customElements !== 'undefined' && typeof HTMLElement !== 'undefined') defineElement();
