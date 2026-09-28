// Готовност за истинска сграда (Z13): непотвърден север, описание, sgrada.html, цветът от glb, Draco.
//   node --test core/tests/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { parseVenue, northPlan, pageMeta } from '../venue-data.js';
import { GLTFLoader } from '../../vendor/three/examples/jsm/loaders/GLTFLoader.js';

const at = (p) => new URL(p, import.meta.url);
const VENUE = JSON.parse(readFileSync(at('../../site/venue.json'), 'utf8'));

test('north_deg: null → без компас и без слънце, с бележка в реда за състоянието', () => {
  const { venue, errors } = parseVenue({ ...VENUE, north_deg: null });
  assert.deepEqual(errors, []);
  assert.equal(venue.north_deg, null);
  assert.deepEqual(northPlan(venue, 'bg'), { compass: false, sun: false, note: 'север: непотвърден' });
  assert.equal(northPlan(venue, 'en').note, 'north: unconfirmed');
});

test('north_deg: число → компас и слънце както досега; без поле → 0', () => {
  const { venue } = parseVenue({ ...VENUE, north_deg: 17 });
  assert.equal(venue.north_deg, 17);
  assert.deepEqual(northPlan(venue, 'bg'), { compass: true, sun: true, note: '' });
  const { north_deg: _, ...without } = VENUE;
  assert.equal(parseVenue(without).venue.north_deg, 0);
  assert.equal(northPlan(parseVenue(without).venue).compass, true);
  assert.ok(parseVenue({ ...VENUE, north_deg: 'север' }).errors.some((e) => e.startsWith('north_deg')));
});

test('компонентът пита northPlan за компаса, слънцето и сенките', () => {
  const src = readFileSync(at('../venue-3d.js'), 'utf8');
  assert.match(src, /compass\.hidden = !northPlan\(this\.venue\)\.compass/);
  assert.match(src, /const withSun = northPlan\(this\.venue\)\.sun/);
  assert.match(src, /if \(!withSun\) \{[^}]*this\.setShadows\(false\)/s);
  assert.match(src, /console\.warn\('venue-3d: north_deg е null/);
});

test('description: по избор, {bg, en} или низ; заглавие и описание на страницата', () => {
  const { venue, errors } = parseVenue(VENUE);
  assert.deepEqual(errors, []);
  assert.deepEqual(pageMeta(venue, 'bg'), { title: 'Примерна арена', description: venue.description.bg });
  assert.equal(pageMeta(venue, 'en').title, 'Example Arena');
  const { description: _, ...without } = VENUE;
  assert.equal(parseVenue(without).venue.description, null);
  assert.equal(pageMeta(parseVenue(without).venue, 'bg').description, '');
  assert.equal(pageMeta(parseVenue({ ...VENUE, description: 'Само низ' }).venue, 'en').description, 'Само низ');
  assert.ok(parseVenue({ ...VENUE, description: 42 }).errors.some((e) => e.startsWith('description')));
});

test('sgrada.html: само компонентът, имената от venue.json, без текстовете на демото', () => {
  const html = readFileSync(at('../../site/sgrada.html'), 'utf8');
  assert.match(html, /<venue-3d src="venue.json"><\/venue-3d>/);
  assert.match(html, /import \{ parseVenue, pageMeta \} from '\.\/core\/venue-data\.js'/);
  for (const demo of ['измислена', 'made-up', 'Как се ползва', 'README', 'skeleton.json']) {
    assert.ok(!html.includes(demo), demo);
  }
  // демото остава както е
  assert.match(readFileSync(at('../../site/index.html'), 'utf8'), /измислена<\/b> кръгла арена/);
});

test('цветът на възела стига до браузъра: glb от prepare_glb.py през GLTFLoader', async () => {
  const buf = readFileSync(at('../../blender/tests/fixtures/synthetic.prepared.glb'));
  const gltf = await new Promise((ok, fail) => new GLTFLoader()
    .parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), '', ok, fail));
  const colors = {};
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    const node = o.parent === gltf.scene ? o.name : o.parent.name;
    (colors[node] ||= []).push(`#${o.material.color.getHexString()}`);
    assert.equal(o.geometry.attributes.uv, undefined, `${node}: UV`);
  });
  assert.deepEqual(colors.level_0, ['#b9bec6', '#bcbcbf', '#95bcda']);  // правило, Principled, Color Ramp
  assert.deepEqual(colors.roof, ['#aa5959']);
  assert.deepEqual(colors.lamp_post, ['#3a3f47']);
  // нивата се познават и по extras.level (компонентът чете и него)
  assert.equal(gltf.scene.getObjectByName('level_2').userData.level, 'level_2');
});

test('Draco декодерът е вграден (без CDN), с лиценз и версия', () => {
  const dir = '../../vendor/three/examples/jsm/libs/draco/';
  for (const f of ['gltf/draco_wasm_wrapper.js', 'gltf/draco_decoder.wasm', 'LICENSE', 'README.md']) {
    assert.ok(existsSync(at(dir + f)), f);
  }
  assert.match(readFileSync(at(dir + 'LICENSE'), 'utf8'), /Apache License\s+Version 2\.0/);
  assert.match(readFileSync(at('../../vendor/three/VERSION.md'), 'utf8'), /DRACOLoader\.js/);
  const loader = readFileSync(at('../../vendor/three/examples/jsm/loaders/DRACOLoader.js'), 'utf8');
  assert.ok(!/from 'three'/.test(loader));
  const src = readFileSync(at('../venue-3d.js'), 'utf8');
  assert.match(src, /libs\/draco\/gltf\//);
  assert.ok(!/https?:\/\//.test(src.replace(/\/\/.*$/gm, '')), 'без външни адреси в компонента');
});
