// venue-3d — състоянието на входовете и точките в момента (отворен, опашка, затворен) от status.json.
// Чисти функции, без three.js и без браузър; тестват се с `node --test core/tests/`.
//
//   {
//     "schema_version": "1",
//     "updated": "2026-11-03T18:00:00+02:00",      // кога е записано — задължително, с часова зона
//     "max_age_min": 30,                            // след толкова минути данните са остарели (по подразбиране 30)
//     "hotspots": {
//       "north": { "state": "open" },
//       "east":  { "state": "busy", "note": { "bg": "Опашка около 10 минути.", "en": "About a 10-minute queue." } },
//       "south": { "state": "closed", "updated": "2026-11-03T17:40:00+02:00" }
//     }
//   }
//
// `updated` на точка (по избор) е кога е проверена тя; без него важи общият. Така обновяването на един вход
// не прави пресни и другите — формата за входа (php/vhod.php) пише час на всяка точка.
// Остарелите данни не се показват като състояние: „отворен“ от вчера е по-лошо от нищо.
// "max_age_min": null — без срок; само за неподвижен пример (демото), не за истинска сграда.

export const STATUS_SCHEMA = '1';
export const STATES = ['open', 'busy', 'closed'];
export const DEFAULT_MAX_AGE_MIN = 30;
const ISO_WITH_ZONE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/;

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

function parseNote(v) {
  if (typeof v === 'string') return v.trim() ? { bg: v } : null;
  if (!isObj(v)) return null;
  const out = {};
  for (const k of ['bg', 'en']) if (typeof v[k] === 'string' && v[k].trim()) out[k] = v[k];
  return out.bg || out.en ? out : null;
}

/**
 * Проверява status.json спрямо точките от venue.json. Не хвърля: връща {status, errors, warnings}.
 * status е null, когато файлът не става за нищо (без `updated` с часова зона — тогава не може да се каже колко е стар).
 */
export function parseStatus(raw, hotspotIds = []) {
  const errors = [], warnings = [];
  if (!isObj(raw)) return { status: null, errors: ['status: трябва да е JSON обект'], warnings };
  if (raw.schema_version != null && String(raw.schema_version) !== STATUS_SCHEMA) {
    warnings.push(`status.schema_version: очаква се "${STATUS_SCHEMA}", дадено "${raw.schema_version}"`);
  }
  const updated = typeof raw.updated === 'string' && ISO_WITH_ZONE.test(raw.updated) ? Date.parse(raw.updated) : NaN;
  if (!Number.isFinite(updated)) {
    errors.push('status.updated: трябва ISO време с часова зона (напр. 2026-11-03T18:00:00+02:00)');
    return { status: null, errors, warnings };
  }
  let maxAge = DEFAULT_MAX_AGE_MIN;
  if (raw.max_age_min === null) maxAge = null;
  else if (raw.max_age_min !== undefined) {
    if (typeof raw.max_age_min === 'number' && raw.max_age_min > 0) maxAge = raw.max_age_min;
    else errors.push('status.max_age_min: трябва число > 0 (минути) или null (без срок, само за пример)');
  }
  const known = new Set(hotspotIds);
  const states = new Map();
  const list = isObj(raw.hotspots) ? raw.hotspots : {};
  if (!isObj(raw.hotspots)) errors.push('status.hotspots: трябва обект {id на точка: {state, note}}');
  for (const [id, v] of Object.entries(list)) {
    const where = `status.hotspots.${id}`;
    if (!known.has(id)) { errors.push(`${where}: няма такава точка във venue.json`); continue; }
    if (!isObj(v) || !STATES.includes(v.state)) { errors.push(`${where}.state: едно от ${STATES.join(', ')}`); continue; }
    const note = v.note != null ? parseNote(v.note) : null;
    if (v.note != null && !note) warnings.push(`${where}.note: трябва текст (bg и/или en) — пропуска се`);
    let own = updated;
    if (v.updated != null) {
      own = typeof v.updated === 'string' && ISO_WITH_ZONE.test(v.updated) ? Date.parse(v.updated) : NaN;
      if (!Number.isFinite(own)) { errors.push(`${where}.updated: трябва ISO време с часова зона`); continue; }
    }
    states.set(id, { state: v.state, note, updated: own, updatedIso: v.updated ?? raw.updated });
  }
  return { status: { updated, updatedIso: raw.updated, maxAgeMin: maxAge, states }, errors, warnings };
}

function age(at, maxAgeMin, now) {
  const ageMin = (now - at) / 60000;
  // малко напред във времето (разминаване на часовниците) се приема; много напред — не
  return { fresh: ageMin > -5 && (maxAgeMin === null || ageMin <= maxAgeMin), ageMin };
}

/** Колко минути са минали от последния запис във файла и пресен ли е той към момента `now` (ms). */
export function statusAge(status, now = Date.now()) {
  if (!status) return { fresh: false, ageMin: null };
  return age(status.updated, status.maxAgeMin, now);
}

/** Състоянието на точка, ако е проверена в срока (по своя час, иначе по общия); иначе null. */
export function stateOf(status, id, now = Date.now()) {
  const st = status?.states.get(id);
  if (!st || !age(st.updated, status.maxAgeMin, now).fresh) return null;
  return st;
}

/** Точките със записано, но остаряло състояние — за бележката под сцената. */
export function staleIds(status, now = Date.now()) {
  if (!status) return [];
  return [...status.states].filter(([, st]) => !age(st.updated, status.maxAgeMin, now).fresh).map(([id]) => id);
}
