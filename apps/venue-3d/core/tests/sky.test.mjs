// Небето: слънцето срещу независимо изчислен еталон, изборът на час и сцена, светлините.
//   node --test core/tests/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  sunPosition, sunVector, refraction, daylight, pickMoment, hourFor, sceneFromHour, eventChoices,
  forecastUsable, skyLook, julianCentury,
} from '../sky.js';

const REF = JSON.parse(readFileSync(new URL('./fixtures/sun.reference.json', import.meta.url), 'utf8'));
const angDiff = (a, b) => Math.abs(((a - b + 540) % 360) - 180);

test('слънцето съвпада с еталона (PyEphem) до 0,02° по височина и азимут', () => {
  assert.ok(REF.cases.length >= 10);
  for (const c of REF.cases) {
    const p = sunPosition(new Date(c.utc), c.lat, c.lon);
    assert.ok(Math.abs(p.geometric - c.elevation) < 0.02, `${c.name}: височина ${p.geometric} ≠ ${c.elevation}`);
    // близо до зенита азимутът е неустойчив по природа — там допускаме повече
    const tol = c.elevation > 85 ? 0.2 : 0.02;
    assert.ok(angDiff(p.azimuth, c.azimuth) < tol, `${c.name}: азимут ${p.azimuth} ≠ ${c.azimuth}`);
  }
});

test('известни стойности: J2000, слънцестоенията, пладне', () => {
  assert.equal(julianCentury(new Date('2000-01-01T12:00:00Z')), 0);
  // деклинацията на слънцестоенето е колкото наклона на земната ос, ~23,44°
  assert.ok(Math.abs(sunPosition(new Date('2026-06-21T09:00:00Z'), 0, 0).decl - 23.44) < 0.02);
  assert.ok(Math.abs(sunPosition(new Date('2026-12-21T15:00:00Z'), 0, 0).decl + 23.44) < 0.02);
  // на равноденствие по пладне: височина = 90° − ширина, слънцето е на юг (северно полукълбо).
  // Слънчевото пладне на 27,92° и. д.: 12:00 − 27,92·4 мин + уравнението на времето (~7 мин) ≈ 10:16 UTC
  const noon = sunPosition(new Date('2026-03-20T10:16:00Z'), 43.21, 27.92);
  assert.ok(Math.abs(noon.geometric - (90 - 43.21)) < 0.6, String(noon.geometric));
  assert.ok(angDiff(noon.azimuth, 180) < 3, String(noon.azimuth));
  // сутрин на изток, вечер на запад
  assert.ok(angDiff(sunPosition(new Date('2026-03-20T04:30:00Z'), 43.21, 27.92).azimuth, 90) < 25);
  assert.ok(angDiff(sunPosition(new Date('2026-03-20T15:30:00Z'), 43.21, 27.92).azimuth, 270) < 25);
  // южно полукълбо: по пладне слънцето е на север
  assert.ok(angDiff(sunPosition(new Date('2026-06-21T02:00:00Z'), -33.87, 151.21).azimuth, 0) < 10);
});

test('рефракцията вдига слънцето около хоризонта с ~0,5°, високо — почти нищо', () => {
  assert.ok(Math.abs(refraction(0) - 0.482) < 0.01);
  assert.ok(refraction(45) < 0.02);
  assert.equal(refraction(89), 0);
  const p = sunPosition(new Date('2026-09-26T16:05:00Z'), 43.21, 27.92);
  assert.ok(p.elevation > p.geometric);
});

test('посоката към слънцето и north_deg: сенките отиват на обратната страна', () => {
  const r = (v) => v.map((x) => Math.round(x * 1000) / 1000);
  // слънце от изток, ниско: вектор към +x на плана (при north_deg 0)
  assert.deepEqual(r(sunVector(90, 0, 0)), [1, 0, 0]);
  // слънце на юг, 30° високо
  assert.deepEqual(r(sunVector(180, 30, 0)), [0, -0.866, 0.5]);
  // ако истинският север е на 90° от оста y на плана, слънцето от изток идва от −y на плана
  assert.deepEqual(r(sunVector(90, 0, 90)), [0, -1, 0]);
  // единичен вектор
  const v = sunVector(237, 12, 33);
  assert.ok(Math.abs(Math.hypot(...v) - 1) < 1e-9);
});

test('ден, здрач, нощ', () => {
  assert.equal(daylight(10), 'day');
  assert.equal(daylight(-3), 'twilight');
  assert.equal(daylight(-12), 'night');
});

const FORECAST = {
  schema_version: '2', lat: 43.21, lon: 27.92,
  hours: [
    { t: '2026-06-20T19:00+03:00', temp_c: 24, precip_pct: 10, cloud_pct: 20, thunder: false },
    { t: '2026-06-20T20:00+03:00', temp_c: 22, precip_pct: 70, cloud_pct: 90, thunder: false },
    { t: '2026-06-20T21:00+03:00', temp_c: 21, precip_pct: 80, cloud_pct: 95, thunder: true },
  ],
  events: [
    { title: 'Вечер', title_en: 'Evening', start: '2026-06-20T20:30+03:00', risk: 'high', scene: 'rain' },
    { title: 'Далеч', start: '2026-07-30T20:55+03:00', risk: null, scene: null },
    { title: 'Без сцена', start: '2026-06-20T19:10+03:00', risk: 'low', scene: null },
    { title: 'Счупено', start: 'не е време' },
  ],
};

test('проявата: часът ѝ, сцената, слънцето', () => {
  const m = pickMoment(FORECAST, 0);
  assert.equal(m.scene, 'rain');
  assert.equal(m.hour.t, '2026-06-20T20:00+03:00');             // 20:30 → най-близкият час (равенство → първият)
  assert.equal(m.date.toISOString(), '2026-06-20T17:30:00.000Z');
  assert.ok(m.sun.elevation > 0 && m.sun.elevation < 12);          // юни, 20:30 във Варна: слънцето е ниско
  assert.ok(angDiff(m.sun.azimuth, 300) < 10);                      // на северозапад
  assert.equal(m.light, 'day');
  // извън хоризонта: няма час, няма сцена — но слънцето пак се смята
  const far = pickMoment(FORECAST, 1);
  assert.equal(far.hour, null);
  assert.equal(far.scene, null);
  assert.equal(far.light, 'twilight');
  // без собствена сцена — от часа
  assert.equal(pickMoment(FORECAST, 2).scene, 'clear');
  // счупените прояви се пропускат, извън списъка → null
  assert.equal(pickMoment(FORECAST, 3), null);
  assert.deepEqual(eventChoices(FORECAST, 'en').map((c) => c.title), ['Evening', 'Далеч', 'Без сцена']);
});

test('негоден forecast.json — няма небе, няма грешка', () => {
  for (const f of [null, {}, { schema_version: '1', lat: 1, lon: 1, events: FORECAST.events },
    { schema_version: '2', lat: null, lon: 2, events: FORECAST.events }, 'текст']) {
    assert.equal(forecastUsable(f), false);
    assert.equal(pickMoment(f, 0), null);
    assert.deepEqual(eventChoices(f), []);
  }
  assert.equal(pickMoment({ ...FORECAST, events: [] }, 0), null);
});

test('сцена от часа и най-близкият час', () => {
  assert.equal(sceneFromHour({ thunder: true, precip_pct: 0 }), 'storm');
  assert.equal(sceneFromHour({ precip_pct: 60, cloud_pct: 100 }), 'rain');
  assert.equal(sceneFromHour({ temp_c: 34, cloud_pct: 0 }), 'heat');
  assert.equal(sceneFromHour({ temp_c: 20, cloud_pct: 70 }), 'clouds');
  assert.equal(sceneFromHour({ temp_c: 20, cloud_pct: 10 }), 'clear');
  assert.equal(sceneFromHour({}), null);
  assert.equal(hourFor(FORECAST.hours, new Date('2026-06-20T21:40+03:00')).t, '2026-06-20T21:00+03:00');
  assert.equal(hourFor(FORECAST.hours, new Date('2026-06-21T01:00+03:00')), null);   // над 90 минути
});

test('светлините: нощ без слънце, буря по-тъмна от ясно, валеж и светкавици', () => {
  const lum = (h) => { const n = parseInt(h.slice(1), 16); return (n >> 16) + ((n >> 8) & 255) + (n & 255); };
  const noon = skyLook('clear', 60), night = skyLook('clear', -20), dusk = skyLook('clear', 1);
  assert.equal(night.sunIntensity, 0);
  assert.ok(noon.sunIntensity > 2);
  assert.ok(lum(night.skyTop) < lum(noon.skyTop));
  assert.ok(lum(skyLook('storm', 60).skyTop) < lum(noon.skyTop));
  assert.ok(skyLook('storm', 60).sunIntensity < skyLook('clouds', 60).sunIntensity);
  assert.ok(skyLook('clouds', 60).sunIntensity < noon.sunIntensity);
  // на залез долу небето е по-топло (повече червено от синьо)
  const b = parseInt(dusk.skyBottom.slice(1), 16);
  assert.ok((b >> 16) > (b & 255));
  assert.equal(skyLook('rain', 30).precip, 'rain');
  assert.equal(skyLook('snow', 30).precip, 'snow');
  assert.equal(skyLook('clear', 30).precip, null);
  assert.equal(skyLook('storm', 30).lightning, true);
  assert.deepEqual(skyLook('непозната', 30), skyLook('clear', 30));   // непозната сцена — като ясно
  assert.ok(skyLook('heat', 40).haze > skyLook('clear', 40).haze);
});
