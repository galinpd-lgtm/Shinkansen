// Тестове без браузър и без зависимости:  node --test core/tests/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, statSync, readdirSync } from 'node:fs';
import {
  parseVenue, planToThree, cameraPosition, viewForPoint, clampTarget, hiddenNodes, hotspotShown,
  sortHotspots, localText, KINDS, DEFAULT_CAMERA, explodeOffsets, formatElevation, fitDistance,
} from '../venue-data.js';
import { buildParts, summary, isClosedManifold, saddleHeight } from '../skeleton-geometry.js';

const read = (p) => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const VENUE = read('../../site/venue.json');
const SKELETON = read('../../blender/skeleton.example.json');
const SUMMARY = read('./fixtures/parts.summary.json');

test('примерният venue.json е годен', () => {
  const { venue, errors, warnings } = parseVenue(VENUE);
  assert.deepEqual(errors, []);
  assert.deepEqual(warnings, []);
  assert.equal(venue.hotspots.length, 9);
  assert.equal(venue.hotspots.filter((h) => h.kind.endsWith('entrance')).length, 5);
  assert.deepEqual(venue.levels.map((l) => l.id), ['level_0', 'level_1', 'level_2']);
  assert.deepEqual(venue.levels[1].nodes, ['level_1']); // без nodes — възелът е id на нивото
});

test('всяко ниво и всеки вход от venue.json има възел в скелета', () => {
  const { venue } = parseVenue(VENUE);
  const names = new Set(buildParts(SKELETON).parts.map((p) => p.name));
  for (const l of venue.levels) for (const n of l.nodes) assert.ok(names.has(n), n);
  for (const n of venue.roof_nodes) assert.ok(names.has(n), n);
  for (const h of venue.hotspots) if (h.node) assert.ok(names.has(h.node), h.node);
});

test('лош venue.json: не хвърля, събира грешките', () => {
  assert.deepEqual(parseVenue(null).errors, ['venue: трябва да е JSON обект']);
  assert.equal(parseVenue([]).venue, null);
  const { venue, errors } = parseVenue({
    name: 'Само низ',
    levels: [{ id: 'l0' }, { id: 'l0' }, { id: 'Ниво' }],
    hotspots: [
      { id: 'a', kind: 'entrance', name: { bg: 'А' }, position: [0, 0, 0] },
      { id: 'a', kind: 'entrance', name: { bg: 'Б' }, position: [0, 0, 0] },
      { id: 'c', kind: 'door', name: { bg: 'В' }, position: [0, 0, 0] },
      { id: 'd', kind: 'info', name: {}, position: [0, 0] },
      { id: 'e', kind: 'info', name: 'Д', position: [0, 0, 0], level: 'l9' },
    ],
    camera: { distance: 'далеч', min_distance: 500, max_distance: 100, zoom: 3 },
    north_deg: 'север',
  });
  assert.equal(venue.name.bg, 'Само низ');
  assert.deepEqual(venue.hotspots.map((h) => h.id), ['a']);
  const has = (s) => assert.ok(errors.some((e) => e.includes(s)), `${s} ∉ ${errors.join(' | ')}`);
  has('трябва `model`');
  has('levels[1].id: повтаря се');
  has('levels[2].id');
  has('hotspots[1].id: повтаря се');
  has('hotspots[2].kind');
  has('hotspots[3].name');
  has('hotspots[3].position');
  has('hotspots[4].level: няма ниво "l9"');
  has('camera.distance: трябва да е число');
  has('0 < min_distance < max_distance');
  has('north_deg');
  assert.equal(venue.camera.min_distance, DEFAULT_CAMERA.min_distance);
});

test('текстове на два езика с падане към другия', () => {
  assert.equal(localText({ bg: 'Вход', en: 'Entrance' }, 'en'), 'Entrance');
  assert.equal(localText({ bg: 'Вход' }, 'en'), 'Вход');
  assert.equal(localText({ en: 'Entrance' }, 'bg'), 'Entrance');
  assert.equal(localText(null, 'bg'), '');
});

test('координати: план → three.js (Y нагоре)', () => {
  assert.deepEqual(planToThree([1, 2, 3]), [1, 3, -2]);
});

test('камерата: компасна посока и височина', () => {
  const [x, y, z] = cameraPosition([0, 0, 0], 100, 90, 0); // от изток, на хоризонта
  assert.ok(Math.abs(x - 100) < 1e-9 && Math.abs(y) < 1e-9 && Math.abs(z) < 1e-9);
  const top = cameraPosition([0, 0, 0], 100, 0, 90);
  assert.ok(Math.abs(top[2] - 100) < 1e-9);
  // изгледът към северния вход е откъм север, отвън
  const v = viewForPoint([0, 50, 2]);
  assert.ok(v.position[1] > 50);
});

test('целта не слиза под земята и не бяга далеч', () => {
  assert.deepEqual(clampTarget([0, 0, -5], 100, 40), [0, 0, 0]);
  const [x, y] = clampTarget([300, 400, 10], 100, 40);
  assert.ok(Math.abs(Math.hypot(x, y) - 100) < 1e-9);
  assert.equal(clampTarget([0, 0, 90], 100, 40)[2], 40);
});

test('„отвори сградата“ крие покрива и нивата над избраното', () => {
  const { venue } = parseVenue(VENUE);
  assert.deepEqual([...hiddenNodes(venue, false, 'level_0')], []);
  assert.deepEqual([...hiddenNodes(venue, true, 'level_0')].sort(), ['level_1', 'level_2', 'roof']);
  assert.deepEqual([...hiddenNodes(venue, true, 'level_2')], ['roof']);
  const info = venue.hotspots.find((h) => h.id === 'info');
  assert.equal(hotspotShown(venue, info, true, 'level_0'), false);
  assert.equal(hotspotShown(venue, info, true, 'level_1'), true);
  assert.equal(hotspotShown(venue, info, false, 'level_0'), true);
});

test('списъкът: входовете първи, после по вид и име', () => {
  const { venue } = parseVenue(VENUE);
  const kinds = sortHotspots(venue.hotspots, 'bg').map((h) => h.kind);
  assert.deepEqual(kinds, [...kinds].sort((a, b) => KINDS.indexOf(a) - KINDS.indexOf(b)));
  assert.equal(kinds[0], 'entrance');
});

test('временният модел: същата геометрия като Blender скрипта (Python)', () => {
  const { parts, doors } = buildParts(SKELETON);
  const js = summary(parts);
  assert.deepEqual(Object.keys(js), Object.keys(SUMMARY));
  for (const [name, want] of Object.entries(SUMMARY)) {
    const got = js[name];
    assert.equal(got.verts, want.verts, name);
    assert.equal(got.faces, want.faces, name);
    for (let k = 0; k < 3; k++) {
      assert.ok(Math.abs(got.min[k] - want.min[k]) < 2e-3, `${name} min ${k}`);
      assert.ok(Math.abs(got.max[k] - want.max[k]) < 2e-3, `${name} max ${k}`);
    }
  }
  assert.equal(doors.length, SKELETON.entrances.length);
});

test('временният модел: затворени тела; седло с ръб по X високо, по Y ниско', () => {
  const { parts, doors } = buildParts(SKELETON);
  for (const p of [...parts, ...doors]) assert.ok(isClosedManifold(p.verts, p.faces), p.name || p.entrance);
  assert.equal(saddleHeight(46, 0, 46, 12, 3, 7.5), 12);
  assert.equal(saddleHeight(0, 46, 46, 12, 3, 7.5), 3);
  const roof = parts.find((p) => p.name === 'roof');
  const top = Math.max(...roof.verts.map((v) => v[2]));
  assert.ok(Math.abs(top - (18 + 12)) < 1e-9);
});

test('временният модел: и другите покриви', () => {
  for (const type of ['dome', 'cone', 'flat']) {
    const sk = { ...SKELETON, roof: { type, height: 9, overhang: 1.5 } };
    const roof = buildParts(sk).parts.find((p) => p.name === 'roof');
    assert.ok(isClosedManifold(roof.verts, roof.faces), type);
  }
});

test('модел и страница заедно под 5 MB', () => {
  const root = new URL('../../', import.meta.url);
  const size = (rel) => {
    const u = new URL(rel, root);
    const st = statSync(u);
    if (!st.isDirectory()) return st.size;
    return readdirSync(u).reduce((s, f) => s + size(`${rel}/${f}`), 0);
  };
  const total = size('site') + size('core/venue-3d.js') + size('core/venue-data.js')
    + size('core/skeleton-geometry.js') + size('vendor/three') + size('models/arena.example.glb')
    + size('blender/skeleton.example.json');
  assert.ok(total < 5 * 1024 * 1024, `${(total / 1024 / 1024).toFixed(2)} MB`);
});

test('разглобен изглед: нивата се раздалечават, покривът е най-отгоре', () => {
  assert.deepEqual(explodeOffsets(3, 10, 1), { levels: [0, 10, 20], roof: 30 });
  assert.deepEqual(explodeOffsets(3, 10, 0), { levels: [0, 0, 0], roof: 0 });
  assert.deepEqual(explodeOffsets(3, 10, 0.5), { levels: [0, 5, 10], roof: 15 });
  const { venue, errors } = parseVenue({ ...VENUE, explode: { gap: 14 } });
  assert.deepEqual(errors, []);
  assert.equal(venue.explode.gap, 14);
  assert.ok(parseVenue({ ...VENUE, explode: { gap: -1 } }).errors.some((e) => e.startsWith('explode.gap')));
  assert.equal(parseVenue(VENUE).venue.explode.gap, 12);
});

test('кота: като на чертеж', () => {
  assert.equal(formatElevation(0, 'bg'), '±0,00');
  assert.equal(formatElevation(6, 'bg'), '+6,00');
  assert.equal(formatElevation(12.345, 'en'), '+12.35 m');
  assert.equal(formatElevation(-3, 'bg'), '−3,00');
  const { venue, errors } = parseVenue({ ...VENUE, levels: [{ id: 'level_0', elevation: 'нула' }] });
  assert.ok(errors.some((e) => e.includes('elevation')));
  assert.equal(venue.levels[0].elevation, null);
});

test('разстояние за побиране в кадъра: тесният екран иска повече', () => {
  const wide = fitDistance(50, 42, 16 / 9), tall = fitDistance(50, 42, 9 / 16);
  assert.ok(tall > wide * 1.5);
  // при квадратен кадър и fov 90°: радиус / sin(45°)
  assert.ok(Math.abs(fitDistance(10, 90, 1, 1) - 10 / Math.sin(Math.PI / 4)) < 1e-9);
});
