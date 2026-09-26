// Небе над сградата — чисти функции, без three.js и без DOM (тестват се в node).
//
//   sunPosition(date, lat, lon)      — азимут и височина на слънцето (собствена реализация, NOAA/Meeus)
//   sunVector(az, el, north_deg)     — посока към слънцето в координатите на плана
//   pickMoment(forecast, eventIndex) — проявата, часът ѝ от hours[] и сцената
//   skyLook(scene, elevation, hour)  — цветове на небето и сила на светлините
//
// Точност на слънцето: около 0,01° за годините 1900–2100 (алгоритъмът на NOAA по Meeus);
// тестовете сверяват срещу независимо изчислени стойности в tests/fixtures/sun.reference.json.

import { bearingVector } from './venue-data.js';

const RAD = Math.PI / 180;
const DEG = 180 / Math.PI;
const SCENES = ['clear', 'clouds', 'rain', 'storm', 'heat', 'snow'];

// ------------------------------------------------------------------ слънце

/** Юлианско столетие от J2000.0 за момент (Date, UTC). */
export function julianCentury(date) {
  const jd = date.getTime() / 86400000 + 2440587.5;
  return (jd - 2451545) / 36525;
}

/** Деклинация (°) и уравнение на времето (минути) за юлианско столетие T. */
export function solarCoordinates(T) {
  const L0 = (280.46646 + T * (36000.76983 + T * 0.0003032)) % 360;        // средна дължина
  const M = 357.52911 + T * (35999.05029 - 0.0001537 * T);                  // средна аномалия
  const e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T);             // ексцентрицитет на орбитата
  const C = Math.sin(M * RAD) * (1.914602 - T * (0.004817 + 0.000014 * T))
    + Math.sin(2 * M * RAD) * (0.019993 - 0.000101 * T)
    + Math.sin(3 * M * RAD) * 0.000289;                                     // уравнение на центъра
  const trueLong = L0 + C;
  const omega = 125.04 - 1934.136 * T;
  const lambda = trueLong - 0.00569 - 0.00478 * Math.sin(omega * RAD);      // видима дължина
  const eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60;
  const eps = eps0 + 0.00256 * Math.cos(omega * RAD);                       // наклон на еклиптиката
  const decl = Math.asin(Math.sin(eps * RAD) * Math.sin(lambda * RAD)) * DEG;
  const y = Math.tan((eps / 2) * RAD) ** 2;
  const eqTime = 4 * DEG * (y * Math.sin(2 * L0 * RAD) - 2 * e * Math.sin(M * RAD)
    + 4 * e * y * Math.sin(M * RAD) * Math.cos(2 * L0 * RAD)
    - 0.5 * y * y * Math.sin(4 * L0 * RAD) - 1.25 * e * e * Math.sin(2 * M * RAD));
  return { decl, eqTime };
}

/** Атмосферна рефракция (°) при видима височина около elevation (формулата на NOAA). */
export function refraction(elevation) {
  if (elevation > 85) return 0;
  const te = Math.tan(elevation * RAD);
  let r;
  if (elevation > 5) r = 58.1 / te - 0.07 / te ** 3 + 0.000086 / te ** 5;
  else if (elevation > -0.575) r = 1735 + elevation * (-518.2 + elevation * (103.4 + elevation * (-12.79 + elevation * 0.711)));
  else r = -20.772 / te;
  return r / 3600;
}

/**
 * Положение на слънцето за момент и място.
 * @param {Date} date  — момент (часовата зона е в самия Date)
 * @param {number} lat — ширина, градуси (север +)
 * @param {number} lon — дължина, градуси (изток +)
 * @returns {{azimuth: number, elevation: number, geometric: number, decl: number}}
 *   azimuth — от север по часовника (0…360); elevation — видима, с рефракцията; geometric — без нея.
 */
export function sunPosition(date, lat, lon) {
  const T = julianCentury(date);
  const { decl, eqTime } = solarCoordinates(T);
  const utcMin = date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60 + date.getUTCMilliseconds() / 60000;
  let tst = (utcMin + eqTime + 4 * lon) % 1440;                             // истинско слънчево време, минути
  if (tst < 0) tst += 1440;
  const ha = tst / 4 < 0 ? tst / 4 + 180 : tst / 4 - 180;                   // часови ъгъл
  const cosZ = Math.sin(lat * RAD) * Math.sin(decl * RAD) + Math.cos(lat * RAD) * Math.cos(decl * RAD) * Math.cos(ha * RAD);
  const zenith = Math.acos(Math.min(1, Math.max(-1, cosZ))) * DEG;
  const geometric = 90 - zenith;
  // азимут от север по часовника
  const sinZ = Math.sin(zenith * RAD);
  let azimuth;
  if (sinZ < 1e-9) azimuth = lat > decl ? 180 : 0;                          // слънцето точно в зенита
  else {
    const cosAz = (Math.sin(lat * RAD) * cosZ - Math.sin(decl * RAD)) / (Math.cos(lat * RAD) * sinZ);
    const a = Math.acos(Math.min(1, Math.max(-1, cosAz))) * DEG;
    azimuth = ha > 0 ? (a + 180) % 360 : (540 - a) % 360;
  }
  return { azimuth, elevation: geometric + refraction(geometric), geometric, decl };
}

/**
 * Посока към слънцето в плана (x изток на плана, y север на плана, z нагоре), единичен вектор.
 * north_deg — накъде е истинският север спрямо оста y на плана (по часовника), както в venue.json.
 */
export function sunVector(azimuth, elevation, northDeg = 0) {
  const [bx, by] = bearingVector(northDeg + azimuth);
  const e = elevation * RAD;
  return [bx * Math.cos(e), by * Math.cos(e), Math.sin(e)];
}

/** Ден / здрач / нощ по височината на слънцето (граждански здрач: до −6°). */
export function daylight(elevation) {
  if (elevation >= 0) return 'day';
  if (elevation >= -6) return 'twilight';
  return 'night';
}

// ------------------------------------------------------------------ forecast.json

/** Годен ли е forecast.json за небето: версия 2, с координати. */
export function forecastUsable(f) {
  return !!f && typeof f === 'object' && String(f.schema_version) === '2'
    && Number.isFinite(f.lat) && Number.isFinite(f.lon);
}

/** Сцена от часа, когато проявата няма своя (напр. извън хоризонта, но часът го има). */
export function sceneFromHour(h) {
  if (!h) return null;
  if (h.thunder) return 'storm';
  if (h.precip_pct != null && h.precip_pct >= 50) return 'rain';
  if (h.temp_c != null && h.temp_c >= 32) return 'heat';
  if (h.cloud_pct != null && h.cloud_pct >= 60) return 'clouds';
  if (h.cloud_pct != null || h.temp_c != null) return 'clear';
  return null;
}

/** Часът от hours[], в който попада моментът (до 90 минути разлика), иначе null. */
export function hourFor(hours, date) {
  let best = null, bestDiff = Infinity;
  for (const h of hours || []) {
    const t = Date.parse(h.t);
    if (!Number.isFinite(t)) continue;
    const d = Math.abs(t - date.getTime());
    if (d < bestDiff) { best = h; bestDiff = d; }
  }
  return bestDiff <= 90 * 60000 ? best : null;
}

/**
 * Проявата и всичко за небето в нейния час.
 * → { event, date, hour, scene, sun: {azimuth, elevation}, light: 'day'|'twilight'|'night' } или null.
 */
export function pickMoment(forecast, index = 0) {
  if (!forecastUsable(forecast)) return null;
  const events = (forecast.events || []).filter((e) => Number.isFinite(Date.parse(e?.start)));
  const event = events[index] || null;
  if (!event) return null;
  const date = new Date(Date.parse(event.start));
  const hour = hourFor(forecast.hours, date);
  const scene = SCENES.includes(event.scene) ? event.scene : sceneFromHour(hour);
  const sun = sunPosition(date, forecast.lat, forecast.lon);
  return { event, date, hour, scene, sun, light: daylight(sun.elevation) };
}

/** Проявите за избор: заглавие по езика и час. */
export function eventChoices(forecast, lang = 'bg') {
  if (!forecastUsable(forecast)) return [];
  return (forecast.events || []).filter((e) => Number.isFinite(Date.parse(e?.start))).map((e, i) => ({
    index: i,
    title: (lang === 'en' && e.title_en) || e.title || '',
    start: e.start,
  }));
}

// ------------------------------------------------------------------ как изглежда

const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
const hex = (c) => '#' + c.map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('');
const clamp01 = (x) => Math.max(0, Math.min(1, x));

// небе при ясен ден: горе, долу (хоризонт)
const CLEAR_DAY = [[92, 150, 214], [214, 232, 246]];
const NIGHT = [[10, 16, 32], [30, 40, 62]];
const DUSK_LOW = [238, 150, 96];
// какво прави времето с небето: сиво (0–1), тъмно (0–1), топъл оттенък (0–1)
const WEATHER = {
  clear: { grey: 0, dark: 0, warm: 0, sun: 1, precip: 0 },
  clouds: { grey: 0.65, dark: 0.15, warm: 0, sun: 0.35, precip: 0 },
  rain: { grey: 0.85, dark: 0.35, warm: 0, sun: 0.12, precip: 1 },
  storm: { grey: 0.95, dark: 0.6, warm: 0, sun: 0.05, precip: 1.6 },
  heat: { grey: 0.1, dark: 0, warm: 0.6, sun: 1.15, precip: 0 },
  snow: { grey: 0.75, dark: 0.1, warm: 0, sun: 0.3, precip: 0.8 },
};

/**
 * Небето и светлините за сцена и височина на слънцето.
 * → { skyTop, skyBottom (цветове #rrggbb), sunIntensity, sunColor, hemiIntensity, precip ('rain'|'snow'|null),
 *     precipAmount (0–2), lightning (bool), haze (0–1) }
 */
export function skyLook(scene, elevation) {
  const w = WEATHER[scene] || WEATHER.clear;
  // 0 — нощ (под −6°), 1 — пълен ден (над 10°), между тях — здрач
  const day = clamp01((elevation + 6) / 16);
  const low = elevation < 8 && elevation > -6 ? 1 - Math.abs(elevation - 1) / 7 : 0;   // златният час
  let top = mix(NIGHT[0], CLEAR_DAY[0], day);
  let bottom = mix(NIGHT[1], CLEAR_DAY[1], day);
  bottom = mix(bottom, DUSK_LOW, clamp01(low) * (1 - w.grey) * 0.8);
  // облаците сивеят небето — денем силно, нощем почти не се виждат
  top = mix(top, [128, 136, 146], w.grey * day);
  bottom = mix(bottom, [168, 174, 182], w.grey * day);
  top = mix(top, [0, 0, 0], w.dark * 0.5);
  bottom = mix(bottom, [0, 0, 0], w.dark * 0.45);
  if (w.warm) bottom = mix(bottom, [250, 214, 160], w.warm * day);
  const sunUp = clamp01((elevation + 0.8) / 6);                              // слънцето изгрява плавно
  const sunColor = mix([255, 170, 110], [255, 250, 240], clamp01(elevation / 25));
  return {
    skyTop: hex(top),
    skyBottom: hex(bottom),
    sunIntensity: +(2.6 * sunUp * w.sun).toFixed(3),
    sunColor: hex(w.warm ? mix(sunColor, [255, 222, 170], w.warm) : sunColor),
    hemiIntensity: +(0.25 + 1.35 * day * (1 - w.dark * 0.5)).toFixed(3),
    precip: w.precip ? (scene === 'snow' ? 'snow' : 'rain') : null,
    precipAmount: w.precip,
    lightning: scene === 'storm',
    haze: scene === 'heat' ? 0.35 : w.grey * 0.3,
  };
}

export { SCENES };
