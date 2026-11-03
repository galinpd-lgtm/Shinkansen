// Състоянието на входовете (status.json): проверка, остаряване, връзка с компонента.
//   node --test core/tests/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseVenue } from '../venue-data.js';
import { parseStatus, statusAge, stateOf, STATES, DEFAULT_MAX_AGE_MIN } from '../status.js';

const at = (p) => new URL(p, import.meta.url);
const read = (p) => JSON.parse(readFileSync(at(p), 'utf8'));
const IDS = parseVenue(read('../../site/venue.json')).venue.hotspots.map((h) => h.id);
const T0 = Date.parse('2026-11-03T18:00:00+02:00');
const min = (m) => T0 + m * 60000;
const base = (extra = {}) => ({ schema_version: '1', updated: '2026-11-03T18:00:00+02:00', hotspots: { north: { state: 'open' } }, ...extra });

test('примерът от демото е годен и без срок', () => {
  const { status, errors, warnings } = parseStatus(read('../../site/status.json'), IDS);
  assert.deepEqual(errors, []);
  assert.deepEqual(warnings, []);
  assert.equal(status.maxAgeMin, null);
  assert.equal(stateOf(status, 'north', Date.parse('2030-01-01T00:00:00Z')).state, 'busy');  // примерът не остарява
  assert.equal(stateOf(status, 'north', T0).note.en, 'About a 10-minute queue — the east entrance is quieter.');
  assert.equal(stateOf(status, 'parking', T0), null);   // без запис — без състояние
});

test('пресни данни: състоянието се вижда; остарели (над 30 мин.): не', () => {
  const { status } = parseStatus(base(), IDS);
  assert.equal(status.maxAgeMin, DEFAULT_MAX_AGE_MIN);
  assert.equal(stateOf(status, 'north', min(0)).state, 'open');
  assert.equal(stateOf(status, 'north', min(30)).state, 'open');
  assert.equal(stateOf(status, 'north', min(31)), null);
  assert.deepEqual(statusAge(status, min(45)), { fresh: false, ageMin: 45 });
  // свой срок
  const { status: s10 } = parseStatus(base({ max_age_min: 10 }), IDS);
  assert.equal(stateOf(s10, 'north', min(11)), null);
  // часовник леко напред — приема се; запис от бъдещето (над 5 мин.) — не
  assert.equal(stateOf(status, 'north', min(-2)).state, 'open');
  assert.equal(stateOf(status, 'north', min(-10)), null);
  assert.equal(stateOf(null, 'north', min(0)), null);
});

test('без време с часова зона файлът не се ползва — не може да се каже колко е стар', () => {
  for (const updated of [undefined, 'вчера', '2026-11-03T18:00:00', '2026-11-03']) {
    const { status, errors } = parseStatus(base({ updated }), IDS);
    assert.equal(status, null, String(updated));
    assert.ok(errors[0].startsWith('status.updated'));
  }
  assert.ok(parseStatus(base({ updated: '2026-11-03T16:00:00Z' }), IDS).status);
  assert.deepEqual(parseStatus([], IDS).errors, ['status: трябва да е JSON обект']);
});

test('лоши записи се изпускат поотделно, с грешка', () => {
  const { status, errors, warnings } = parseStatus(base({
    max_age_min: -1,
    hotspots: {
      north: { state: 'open', note: 42 },
      east: { state: 'maybe' },
      nowhere: { state: 'open' },
      south: 'closed',
    },
  }), IDS);
  assert.deepEqual([...status.states.keys()], ['north']);
  assert.equal(status.states.get('north').note, null);
  const has = (s) => assert.ok(errors.some((e) => e.includes(s)), `${s} ∉ ${errors.join(' | ')}`);
  has('max_age_min');
  has('hotspots.east.state');
  has('hotspots.nowhere: няма такава точка');
  has('hotspots.south.state');
  assert.ok(warnings.some((w) => w.includes('north.note')));
  assert.equal(status.maxAgeMin, DEFAULT_MAX_AGE_MIN);
  assert.deepEqual(STATES, ['open', 'busy', 'closed']);
});

test('компонентът: атрибутите status и refresh, без състояние при остарели данни', () => {
  const src = readFileSync(at('../venue-3d.js'), 'utf8');
  assert.match(src, /observedAttributes\(\) \{ return \[[^\]]*'status', 'refresh'\]/);
  assert.match(src, /stateFor\(h\) \{ return stateOf\(this\.status, h\.id\); \}/);
  assert.match(src, /clearInterval\(this\.statusTimer\)/);
  assert.match(src, /cache: 'no-store'/);
  assert.match(readFileSync(at('../../site/index.html'), 'utf8'), /status="status\.json"/);
});

test('всеки относителен внос в core/ сочи към файл, който pages.yml копира (core/*.js или vendor/)', () => {
  const wf = readFileSync(at('../../../../.github/workflows/pages.yml'), 'utf8');
  assert.match(wf, /cp core\/\*\.js "\$DEST\/core\/"/);
  assert.match(wf, /cp -r vendor\/three "\$DEST\/vendor\/"/);
  for (const f of ['venue-3d.js', 'venue-data.js', 'status.js', 'sky.js', 'skeleton-geometry.js']) {
    for (const [, spec] of readFileSync(at(`../${f}`), 'utf8').matchAll(/from '(\.[^']+)'/g)) {
      assert.ok(/^\.\/[\w-]+\.js$/.test(spec) || spec.startsWith('../vendor/three/'), `${f}: ${spec}`);
      readFileSync(new URL(spec, at(`../${f}`)));   // хвърля, ако файлът липсва
    }
  }
});
