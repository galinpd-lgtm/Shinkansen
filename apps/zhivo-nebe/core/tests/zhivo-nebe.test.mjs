// Тестове на двигателя без браузър и без зависимости:  node --test core/tests/
// Проверяват чистите функции; рисуването се проверява ръчно (виж README).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  median, riskOf, sceneOf, checkForecast, sunElevation, isDaylight, fromOpenMeteo,
  pickFocus, nextHours, summaryText, dayAgreement, confidenceOf, openMeteoUrl, DEFAULT_THRESHOLDS,
} from '../zhivo-nebe.js';

// forecast.json, записан от agent/fetch.py върху записаните отговори на агента
const SAMPLE = JSON.parse(readFileSync(new URL('./fixtures/forecast.sample.json', import.meta.url), 'utf8'));
const SAMPLE_NOW = Date.parse('2026-06-20T06:00:00+03:00');
const TH = DEFAULT_THRESHOLDS;
const H = 3600e3;

test('медиана пропуска липсващото', () => {
  assert.equal(median([3, null, 1, 2]), 2);
  assert.equal(median([1, 2, 3, 4]), 2.5);
  assert.equal(median([null]), null);
});

test('праговете: среден вятър за среден риск, пориви за висок', () => {
  assert.equal(riskOf([{ gust_kmh: 45, wind_kmh: 20 }], TH), 0);
  assert.equal(riskOf([{ gust_kmh: 45, wind_kmh: 36 }], TH), 1);
  assert.equal(riskOf([{ gust_kmh: 52, wind_kmh: 20 }], TH), 2);
  assert.equal(riskOf([{ thunder: true }], TH), 2);
  assert.equal(riskOf([{ temp_c: 33.5 }], TH), 1);
});

test('сцени по приоритет', () => {
  assert.equal(sceneOf([{ thunder: true, precip_pct: 90 }]), 'storm');
  assert.equal(sceneOf([{ gust_kmh: 60 }]), 'storm');
  assert.equal(sceneOf([{ precip_pct: 80, temp_c: 0 }]), 'snow');
  assert.equal(sceneOf([{ precip_pct: 80, temp_c: 12 }]), 'rain');
  assert.equal(sceneOf([{ temp_c: 34, precip_pct: 5 }]), 'heat');
  assert.equal(sceneOf([{ cloud_pct: 80, temp_c: 20 }]), 'clouds');
  assert.equal(sceneOf([{ cloud_pct: 10, temp_c: 20 }]), 'clear');
  assert.equal(sceneOf([]), null);
});

test('agreement: поне до риска, само източниците с величината', () => {
  const merged = [{ precip_pct: 80 }];
  const per = [[{ precip_pct: 80 }], [{ precip_pct: 30 }], [{ temp_c: 20, precip_pct: null }]];
  assert.deepEqual(dayAgreement(2, merged, per, TH), [1, 2]);
  assert.equal(confidenceOf(1, 2), 'low');
  assert.equal(confidenceOf(2, 2), 'medium');
  assert.equal(confidenceOf(4, 5), 'high');
});

test('годност на forecast.json: липсва, версия, празен, стар, годен', () => {
  assert.equal(checkForecast(null, SAMPLE_NOW).reason, 'missing');
  assert.equal(checkForecast({ ...SAMPLE, schema_version: '1' }, SAMPLE_NOW).reason, 'version');
  assert.equal(checkForecast({ ...SAMPLE, hours: [], sources_ok: [] }, SAMPLE_NOW).reason, 'empty');
  assert.equal(checkForecast(SAMPLE, SAMPLE_NOW + 3 * H).ok, true);
  assert.equal(checkForecast(SAMPLE, SAMPLE_NOW + 3 * H + 60e3).reason, 'stale');
  assert.equal(checkForecast({ ...SAMPLE, generated_at: 'глупост' }, SAMPLE_NOW).reason, 'stale');
});

test('ден и нощ по слънцето във Варна', () => {
  const noon = new Date('2026-06-20T13:00:00+03:00');
  assert.ok(sunElevation(noon, 43.21, 27.91) > 60);
  assert.equal(isDaylight(new Date('2026-06-20T23:00:00+03:00'), 43.21, 27.91), false);
  assert.equal(isDaylight(new Date('2026-06-20T20:30:00+03:00'), 43.21, 27.91), true); // лятна вечер, още светло
  assert.equal(isDaylight(new Date('2026-12-20T17:30:00+02:00'), 43.21, 27.91), false);
});

test('фокус: най-близката проява от файла на агента', () => {
  const f = pickFocus(SAMPLE, SAMPLE_NOW);
  assert.equal(f.kind, 'event');
  assert.equal(f.event.title, 'Вечерна проява');
  assert.equal(f.scene, 'storm');
  // след края на прозореца на първата проява фокусът минава на следващата
  const later = pickFocus(SAMPLE, Date.parse('2026-06-20T23:40:00+03:00'));
  assert.equal(later.event.title, 'Следобедна проява');
  assert.equal(later.scene, 'heat');
});

test('фокус без сцена за проявата → времето сега', () => {
  const fc = { ...SAMPLE, events: [{ title: 'Далечна', start: '2026-07-30T20:30+03:00', risk: null, scene: null }] };
  const f = pickFocus(fc, SAMPLE_NOW);
  assert.equal(f.kind, 'now');
  assert.equal(f.event.title, 'Далечна');
  assert.ok(['clear', 'clouds', 'rain', 'storm', 'heat', 'snow'].includes(f.scene));
});

test('следващите 24 часа започват от текущия час', () => {
  const hrs = nextHours(SAMPLE, SAMPLE_NOW + 30 * 60e3);
  assert.equal(hrs.length, 24);
  assert.equal(hrs[0].t, '2026-06-20T06:00+03:00');
});

test('обобщение: само дни с увереност поне medium; двуезично', () => {
  const fc = { ...SAMPLE, days: [
    { date: '2026-06-20', risk: 'high', agreement: 5, confidence: 'high' },
    { date: '2026-06-21', risk: 'medium', agreement: 1, confidence: 'low' },
  ] };
  const f = pickFocus(fc, SAMPLE_NOW);
  const bg = summaryText(fc, f, 'bg');
  assert.match(bg, /„Вечерна проява“ на 20\.06 от 20:30 — риск висок, буря/);
  assert.match(bg, /20\.06 \(висок\)/);
  assert.doesNotMatch(bg, /21\.06/);
  assert.match(summaryText(fc, f, 'en'), /Next event: “Вечерна проява” on 20\.06 at 20:30 — high risk, storm/);
  const calm = { ...fc, days: [fc.days[1]] };
  assert.match(summaryText(calm, { event: null }, 'bg'), /Без потвърдени рискови дни/);
});

// Отговор на Open-Meteo с три модела (ключовете са с наставка на модела)
function omMulti() {
  const time = Array.from({ length: 48 }, (_, i) => {
    const d = new Date(Date.UTC(2026, 5, 20, i));
    return d.toISOString().slice(0, 13) + ':00';
  });
  const n = time.length;
  const hourly = { time };
  const put = (name, m, fn) => { hourly[`${name}_${m}`] = time.map((_, i) => fn(i)); };
  const storm = (i) => i >= 20 && i <= 22;
  for (const [m, dt] of [['icon_seamless', 0], ['gfs_seamless', 1], ['ecmwf_ifs025', -1]]) {
    put('temperature_2m', m, () => 24 + dt);
    put('precipitation_probability', m, (i) => (m === 'ecmwf_ifs025' ? null : storm(i) ? 80 : 5));
    put('wind_speed_10m', m, () => 12);
    put('wind_gusts_10m', m, (i) => (storm(i) ? 58 : 22));
    put('cloud_cover', m, () => 30);
    put('weather_code', m, (i) => (storm(i) ? 95 : 1));
  }
  assert.equal(hourly.time.length, n);
  // времената са местни (timezone=auto), отместването идва отделно
  return { latitude: 43.22, longitude: 27.92, utc_offset_seconds: 10800, hourly };
}

test('резервен режим: медиана, spread и риск от трите модела', () => {
  const fb = fromOpenMeteo(omMulti(), {
    now: Date.parse('2026-06-20T06:00+03:00'),
    events: [
      { title: 'Вечер', start: '2026-06-20T20:30+03:00' },
      { title: 'Минала', start: '2026-06-19T20:30+03:00' },
    ],
  });
  assert.equal(fb.mode, 'fallback');
  assert.equal(fb.schema_version, '2');
  assert.deepEqual(fb.sources_ok, ['open-meteo:icon_seamless', 'open-meteo:gfs_seamless', 'open-meteo:ecmwf_ifs025']);
  const h = Object.fromEntries(fb.hours.map((x) => [x.t, x]));
  const s = h['2026-06-20T21:00+03:00'];
  assert.equal(s.temp_c, 24);
  assert.equal(s.spread_temp, 2);
  assert.equal(s.precip_pct, 80);
  assert.equal(s.spread_precip, 0);   // ECMWF няма вероятност — не участва
  assert.equal(s.thunder, true);
  const day = fb.days.find((d) => d.date === '2026-06-20');
  assert.equal(day.risk, 'high');
  assert.equal(day.agreement, 3);
  assert.equal(day.confidence, 'high');
  assert.deepEqual(fb.events.map((e) => [e.title, e.risk, e.scene]), [['Вечер', 'high', 'storm']]);
});

test('адресът за резервния режим е без ключ, с трите модела', () => {
  const u = new URL(openMeteoUrl(43.2141, 27.9147));
  assert.equal(u.hostname, 'api.open-meteo.com');
  assert.equal(u.searchParams.get('models'), 'icon_seamless,gfs_seamless,ecmwf_ifs025');
  assert.ok(!/key/i.test(u.search));
});
