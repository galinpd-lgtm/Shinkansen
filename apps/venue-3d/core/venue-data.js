// venue-3d — данните: парсване и проверка на venue.json и чисти сметки без three.js и без браузър.
// Тестват се с `node --test core/tests/`.
//
// Координати в venue.json (както в skeleton.json): план в метри — x на изток, y на север, z нагоре.
// three.js (и glTF) е с Y нагоре: точка (x, y, z) от плана става (x, z, −y).

export const SCHEMA_VERSION = '1';
// подредбата е и подредбата в списъка
export const KINDS = ['entrance', 'accessible_entrance', 'ticket_office', 'parking', 'transit_stop', 'info'];
export const DEFAULT_CAMERA = {
  target: [0, 0, 8], distance: 170, azimuth_deg: 210, elevation_deg: 30,
  min_distance: 20, max_distance: 450, max_target_radius: 150, min_elevation_deg: 4,
};
const ID = /^[a-z0-9_]{1,40}$/;

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

/** Текст на два езика: низ → {bg: низ}; обект → само bg/en като низове. */
function parseText(v) {
  if (typeof v === 'string') return { bg: v };
  if (!isObj(v)) return null;
  const out = {};
  for (const k of ['bg', 'en']) if (typeof v[k] === 'string' && v[k].trim()) out[k] = v[k];
  return out.bg || out.en ? out : null;
}

/** Текстът на езика на страницата; без превод — другия език. */
export function localText(t, lang) {
  if (!t) return '';
  return t[lang] || t.bg || t.en || '';
}

/**
 * Проверява venue.json. Не хвърля: връща {venue, errors, warnings}.
 * venue е null само ако файлът изобщо не може да се ползва; негодните точки се изпускат с грешка.
 */
export function parseVenue(raw) {
  const errors = [], warnings = [];
  if (!isObj(raw)) return { venue: null, errors: ['venue: трябва да е JSON обект'], warnings };
  if (raw.schema_version != null && String(raw.schema_version) !== SCHEMA_VERSION) {
    warnings.push(`schema_version: очаква се "${SCHEMA_VERSION}", дадено "${raw.schema_version}"`);
  }

  const name = parseText(raw.name) || { bg: '' };
  const model = typeof raw.model === 'string' && raw.model ? raw.model : null;
  const skeleton = isObj(raw.skeleton) || (typeof raw.skeleton === 'string' && raw.skeleton) ? raw.skeleton : null;
  if (!model && !skeleton) errors.push('venue: трябва `model` (път до .glb) или `skeleton` (обект или път) — иначе няма какво да се покаже');

  let north = 0;
  if (raw.north_deg != null) {
    if (isNum(raw.north_deg)) north = raw.north_deg;
    else errors.push('north_deg: трябва да е число');
  }

  const camera = { ...DEFAULT_CAMERA };
  if (raw.camera != null) {
    if (!isObj(raw.camera)) errors.push('camera: трябва да е обект');
    else {
      for (const [k, v] of Object.entries(raw.camera)) {
        if (!(k in DEFAULT_CAMERA)) { warnings.push(`camera.${k}: непознато поле`); continue; }
        if (k === 'target') {
          if (Array.isArray(v) && v.length === 3 && v.every(isNum)) camera.target = v;
          else errors.push('camera.target: трябва [x, y, z]');
        } else if (isNum(v)) camera[k] = v;
        else errors.push(`camera.${k}: трябва да е число`);
      }
      if (camera.min_distance <= 0 || camera.min_distance >= camera.max_distance) {
        errors.push('camera: трябва 0 < min_distance < max_distance');
        camera.min_distance = DEFAULT_CAMERA.min_distance; camera.max_distance = DEFAULT_CAMERA.max_distance;
      }
      camera.distance = Math.min(Math.max(camera.distance, camera.min_distance), camera.max_distance);
    }
  }

  const roofNodes = Array.isArray(raw.roof_nodes) ? raw.roof_nodes.filter((s) => typeof s === 'string') : ['roof'];

  const levels = [];
  const levelIds = new Set();
  (Array.isArray(raw.levels) ? raw.levels : []).forEach((lv, i) => {
    const where = `levels[${i}]`;
    if (!isObj(lv) || typeof lv.id !== 'string' || !ID.test(lv.id)) { errors.push(`${where}.id: трябва [a-z0-9_]`); return; }
    if (levelIds.has(lv.id)) { errors.push(`${where}.id: повтаря се "${lv.id}"`); return; }
    levelIds.add(lv.id);
    const nodes = Array.isArray(lv.nodes) && lv.nodes.length ? lv.nodes.filter((s) => typeof s === 'string') : [lv.id];
    let elevation = null;
    if (lv.elevation != null) {
      if (isNum(lv.elevation)) elevation = lv.elevation;
      else errors.push(`${where}.elevation: трябва да е число (кота в метри)`);
    }
    levels.push({ id: lv.id, name: parseText(lv.name) || { bg: lv.id }, nodes, elevation });
  });

  const hotspots = [];
  const ids = new Set();
  (Array.isArray(raw.hotspots) ? raw.hotspots : []).forEach((h, i) => {
    const where = `hotspots[${i}]`;
    const problems = [];
    if (!isObj(h)) { errors.push(`${where}: трябва да е обект`); return; }
    if (typeof h.id !== 'string' || !ID.test(h.id)) problems.push('id: трябва [a-z0-9_]');
    else if (ids.has(h.id)) problems.push(`id: повтаря се "${h.id}"`);
    if (!KINDS.includes(h.kind)) problems.push(`kind: едно от ${KINDS.join(', ')}`);
    const hname = parseText(h.name);
    if (!hname) problems.push('name: трябва текст (bg и/или en)');
    if (!(Array.isArray(h.position) && h.position.length === 3 && h.position.every(isNum))) problems.push('position: трябва [x, y, z]');
    if (h.level != null && !levelIds.has(h.level)) problems.push(`level: няма ниво "${h.level}"`);
    if (problems.length) { for (const p of problems) errors.push(`${where}.${p}`); return; }
    ids.add(h.id);
    hotspots.push({
      id: h.id, kind: h.kind, name: hname, description: parseText(h.description),
      position: h.position, level: h.level ?? null, inside: h.inside === true,
      node: typeof h.node === 'string' ? h.node : null,
    });
  });

  // разглобен изглед: разстояние между нивата (м); null → по височината на нивата
  let explode = { gap: null };
  if (raw.explode != null) {
    if (isObj(raw.explode) && (raw.explode.gap == null || (isNum(raw.explode.gap) && raw.explode.gap > 0))) {
      explode = { gap: raw.explode.gap ?? null };
    } else errors.push('explode.gap: трябва число > 0 (метри между нивата)');
  }

  return {
    venue: { name, model, skeleton, north_deg: north, camera, roof_nodes: roofNodes, levels, hotspots, explode },
    errors, warnings,
  };
}

// ------------------------------------------------------------------ сметки

/** Точка от плана (x изток, y север, z нагоре) → three.js (Y нагоре). */
export function planToThree([x, y, z]) { return [x, z, -y]; }

/** Посока по компас (градуси от север по часовника) → единичен вектор в плана. */
export function bearingVector(deg) {
  const a = (deg * Math.PI) / 180;
  return [Math.sin(a), Math.cos(a)];
}

/** Къде е камерата в плана: от целта към посока `azimuth` (компас), на `distance`, вдигната на `elevation`. */
export function cameraPosition(target, distance, azimuthDeg, elevationDeg) {
  const [bx, by] = bearingVector(azimuthDeg);
  const e = (elevationDeg * Math.PI) / 180;
  const flat = distance * Math.cos(e);
  return [target[0] + bx * flat, target[1] + by * flat, target[2] + distance * Math.sin(e)];
}

/** Изглед към точка: камерата застава навън от центъра на сградата, към точката, малко отгоре. */
export function viewForPoint(point, { distance = 45, elevation_deg = 28, fallbackAzimuth = 210 } = {}) {
  const [x, y] = point;
  const azimuth = Math.hypot(x, y) > 1 ? (Math.atan2(x, y) * 180) / Math.PI : fallbackAzimuth;
  return { target: point, position: cameraPosition(point, distance, azimuth, elevation_deg) };
}

/** Целта на камерата не излиза под земята и не се отдалечава от сградата повече от `maxRadius`. */
export function clampTarget([x, y, z], maxRadius, maxHeight) {
  const r = Math.hypot(x, y);
  const k = r > maxRadius ? maxRadius / r : 1;
  return [x * k, y * k, Math.min(Math.max(z, 0), maxHeight)];
}

/** Кои възли да се скрият при „отвори сградата“ на ниво `levelId`: покривът и нивата над него. */
export function hiddenNodes(venue, open, levelId) {
  const hidden = new Set();
  if (!open) return hidden;
  const idx = venue.levels.findIndex((l) => l.id === levelId);
  for (const n of venue.roof_nodes) hidden.add(n);
  venue.levels.forEach((l, i) => { if (idx >= 0 && i > idx) l.nodes.forEach((n) => hidden.add(n)); });
  return hidden;
}

/** Видима ли е точката при текущото отваряне (не е на скрито ниво). */
export function hotspotShown(venue, h, open, levelId) {
  if (!open || !h.level) return true;
  const idx = venue.levels.findIndex((l) => l.id === levelId);
  const hi = venue.levels.findIndex((l) => l.id === h.level);
  return idx < 0 || hi <= idx;
}

/** Точките по вид (в реда на KINDS), после по име. */
export function sortHotspots(list, lang = 'bg') {
  return [...list].sort((a, b) => KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind)
    || localText(a.name, lang).localeCompare(localText(b.name, lang)));
}

/** Относителен път спрямо адреса на venue.json. */
export function resolveUrl(path, base) {
  try { return new URL(path, base).href; } catch { return path; }
}

export function easeInOutCubic(t) { return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2; }

/**
 * Разглобен изглед: отместване нагоре на всяко ниво (по реда в venue.json) и на покрива,
 * при напредък t от 0 (цяла сграда) до 1 (разглобена). Покривът е над най-горното ниво.
 */
export function explodeOffsets(levelCount, gap, t = 1) {
  const levels = Array.from({ length: levelCount }, (_, i) => i * gap * t);
  return { levels, roof: levelCount * gap * t };
}

/** Кота като на чертеж: +6,00 (bg) / +6.00 m (en); нулата е ±0,00. */
export function formatElevation(z, lang = 'bg') {
  const v = Math.round(z * 100) / 100;
  const sign = Math.abs(v) < 0.005 ? '±' : v > 0 ? '+' : '−';
  const num = Math.abs(v).toFixed(2);
  return lang === 'en' ? `${sign}${num} m` : `${sign}${num.replace('.', ',')}`;
}

/** Разстояние, от което сфера с радиус `radius` се побира в кадъра и по двете оси (fov е вертикалният, в градуси). */
export function fitDistance(radius, fovDeg, aspect, margin = 1.1) {
  const v = (fovDeg * Math.PI) / 180;
  const h = 2 * Math.atan(Math.tan(v / 2) * aspect);
  return (radius * margin) / Math.sin(Math.min(v, h) / 2);
}
