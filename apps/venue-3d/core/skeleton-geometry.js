// venue-3d — временният модел: същата геометрия като blender/venue_geometry.py, пренесена на JS.
// Ползва се, когато model.glb липсва. Без three.js — връща върхове и стени в плана
// (x изток, y север, z нагоре); venue-3d.js ги превръща в меши.
// Съвпадението с Python се проверява в тестовете срещу core/tests/fixtures/parts.summary.json.
// Разлика: тук отворите не се изрязват (няма boolean) — вместо тях се слага тъмен панел на стената.

const TAU = Math.PI * 2;

function circle(r, z, n) {
  const out = [];
  for (let i = 0; i < n; i++) out.push([r * Math.cos((TAU * i) / n), r * Math.sin((TAU * i) / n), z]);
  return out;
}

/** Пресечен конус: радиус r0 при z0, r1 при z1 (цилиндър, когато са равни). */
export function frustum(r0, r1, z0, z1, n) {
  const verts = [...circle(r0, z0, n), ...circle(r1, z1, n), [0, 0, z0], [0, 0, z1]];
  const cb = 2 * n, ct = 2 * n + 1, faces = [];
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    faces.push([i, j, n + j, n + i], [cb, j, i], [ct, n + i, n + j]);
  }
  return { verts, faces };
}

export function ring(rIn, rOut, z0, z1, n) {
  const verts = [...circle(rOut, z0, n), ...circle(rOut, z1, n), ...circle(rIn, z0, n), ...circle(rIn, z1, n)];
  const ob = 0, ot = n, ib = 2 * n, it = 3 * n, faces = [];
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    faces.push([ob + i, ob + j, ot + j, ot + i], [ib + j, ib + i, it + i, it + j],
      [ot + i, ot + j, it + j, it + i], [ob + j, ob + i, ib + i, ib + j]);
  }
  return { verts, faces };
}

/** Кутия с център (cx, cy); width по локалното x, depth по локалното y; bearing завърта локалното +y от север към изток. */
export function box(cx, cy, z0, width, depth, height, bearingDeg = 0) {
  const a = (bearingDeg * Math.PI) / 180, ca = Math.cos(a), sa = Math.sin(a);
  const verts = [];
  for (const z of [z0, z0 + height]) {
    for (const [lx, ly] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
      const x = (lx * width) / 2, y = (ly * depth) / 2;
      verts.push([cx + x * ca + y * sa, cy - x * sa + y * ca, z]);
    }
  }
  const faces = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]];
  return { verts, faces };
}

export function dome(r, z0, height, n, rings = 12) {
  const verts = [], faces = [];
  for (let k = 0; k < rings; k++) {
    const phi = (Math.PI / 2) * (k / rings);
    verts.push(...circle(r * Math.cos(phi), z0 + height * Math.sin(phi), n));
  }
  const apex = verts.length, base = verts.length + 1;
  verts.push([0, 0, z0 + height], [0, 0, z0]);
  for (let k = 0; k < rings - 1; k++) {
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n;
      faces.push([k * n + i, k * n + j, (k + 1) * n + j, (k + 1) * n + i]);
    }
  }
  const top = (rings - 1) * n;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    faces.push([top + i, top + j, apex], [base, j, i]);
  }
  return { verts, faces };
}

export function cone(r, z0, height, n) {
  const verts = [...circle(r, z0, n), [0, 0, z0 + height], [0, 0, z0]];
  const apex = n, base = n + 1, faces = [];
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    faces.push([i, j, apex], [base, j, i]);
  }
  return { verts, faces };
}

/** Хиперболичен параболоид над кръг: hc в центъра, hx по ръба на оста x, hy на оста y. */
export function saddleHeight(x, y, radius, hx, hy, hc) {
  const u = x / radius, v = y / radius;
  return hc + (hx - hc) * u * u + (hy - hc) * v * v;
}

function polarGrid(radius, n, rings, heightFn) {
  const verts = [[0, 0, heightFn(0, 0)]];
  for (let k = 1; k <= rings; k++) {
    for (const [x, y] of circle((radius * k) / rings, 0, n)) verts.push([x, y, heightFn(x, y)]);
  }
  return verts;
}

/** Седловиден покрив: тънка козирка до стрехата + пълнеж от стената до долната ѝ страна (без процеп). */
export function saddleRoof(wallR, z0, n, hx, hy, hc, eaveR, thickness, rings = 10) {
  const verts = [], faces = [];
  const shell = (topFn, bottomFn, radius) => {
    const base = verts.length;
    const top = polarGrid(radius, n, rings, topFn), bottom = polarGrid(radius, n, rings, bottomFn);
    verts.push(...top, ...bottom);
    const t = base, b = base + top.length;
    const at = (k, i) => 1 + (k - 1) * n + (i % n);
    for (let i = 0; i < n; i++) {
      faces.push([t, t + at(1, i), t + at(1, i + 1)], [b, b + at(1, i + 1), b + at(1, i)]);
    }
    for (let k = 1; k < rings; k++) {
      for (let i = 0; i < n; i++) {
        const a0 = at(k, i), a1 = at(k, i + 1), c0 = at(k + 1, i), c1 = at(k + 1, i + 1);
        faces.push([t + a0, t + c0, t + c1, t + a1], [b + a0, b + a1, b + c1, b + c0]);
      }
    }
    for (let i = 0; i < n; i++) {
      const o0 = at(rings, i), o1 = at(rings, i + 1);
      faces.push([b + o0, b + o1, t + o1, t + o0]);
    }
  };
  const surface = (x, y) => z0 + saddleHeight(x, y, eaveR, hx, hy, hc);
  shell(surface, (x, y) => surface(x, y) - thickness, eaveR);
  shell((x, y) => Math.max(surface(x, y) - thickness - 0.02, z0 + 0.02), () => z0, wallR - 0.05);
  return { verts, faces };
}

export function bearingPoint(radius, bearingDeg) {
  const a = (bearingDeg * Math.PI) / 180;
  return [radius * Math.sin(a), radius * Math.cos(a)];
}

/**
 * Скелет → възли, както в Python: [{name, kind, level, material, verts, faces}],
 * плюс doors: тъмните панели на входовете (само тук, вместо изрязания отвор).
 */
export function buildParts(sk) {
  const n = sk.segments ?? 64;
  const drum = sk.drum, r = drum.radius, topR = drum.top_radius ?? r;
  const radiusAt = (z) => r + (topR - r) * Math.min(Math.max(z / drum.height, 0), 1);
  const parts = [], doors = [];
  const add = (name, kind, level, material, g) => parts.push({ name, kind, level, material, ...g });

  for (const lv of sk.levels) {
    const z0 = lv.z, z1 = lv.z + lv.height;
    add(lv.id, 'level', lv.id, 'building', frustum(radiusAt(z0), radiusAt(z1), z0, z1, n));
  }
  const ringSpec = sk.ring;
  if (ringSpec) add('ring', 'ring', sk.levels[0].id, 'building', ring(ringSpec.inner_radius, ringSpec.outer_radius, 0, ringSpec.height, n));

  const roof = sk.roof;
  if (roof) {
    const rr = roof.eave_radius ?? topR + (roof.overhang ?? 0);
    const z0 = drum.height;
    let g;
    if (roof.type === 'saddle') g = saddleRoof(topR, z0, n, roof.edge_height_x, roof.edge_height_y, roof.center_height, rr, roof.thickness ?? 0.6);
    else if (roof.type === 'dome') g = dome(rr, z0, roof.height, n);
    else if (roof.type === 'cone') g = cone(rr, z0, roof.height, n);
    else g = frustum(rr, rr, z0, z0 + Math.max(roof.height ?? 0.6, 0.2), n);
    add('roof', 'roof', null, 'roof', g);
  }

  const pylons = sk.pylons;
  if (pylons && pylons.count) {
    const step = 360 / pylons.count;
    for (let i = 0; i < pylons.count; i++) {
      const b = (pylons.start_angle_deg ?? 0) + i * step;
      const [cx, cy] = bearingPoint(pylons.radius, b);
      add(`pylon_${String(i + 1).padStart(2, '0')}`, 'pylon', null, 'pylon', box(cx, cy, 0, pylons.width, pylons.depth, pylons.height, b));
    }
  }

  for (const w of sk.wings || []) {
    add(`wing_${w.id}`, 'wing', sk.levels[0].id, 'wing', box(w.x, w.y, 0, w.width, w.depth, w.height, w.rotation_deg ?? 0));
  }

  const levels = Object.fromEntries(sk.levels.map((l) => [l.id, l]));
  for (const e of sk.entrances || []) {
    const z0 = levels[e.level].z;
    let cx, cy, facing;
    if (e.angle_deg != null) {
      facing = e.angle_deg;
      const wallOut = Math.max(radiusAt(z0), radiusAt(z0 + e.height));
      const onRing = ringSpec && z0 < ringSpec.height;
      const outer = Math.max(wallOut, onRing ? ringSpec.outer_radius : 0);
      [cx, cy] = bearingPoint(outer, facing);
    } else {
      [cx, cy] = e.position;
      facing = e.facing_deg;
    }
    const [ox, oy] = bearingPoint(1, facing);
    add(`entrance_${e.id}`, 'entrance', e.level, 'accent', box(cx + ox, cy + oy, z0 + e.height, e.width + 1, 2.2, 0.4, facing));
    const [dx, dy] = bearingPoint(0.1, facing);
    doors.push({ entrance: `entrance_${e.id}`, ...box(cx + dx, cy + dy, z0, e.width, 0.4, e.height, facing) });
  }
  return { parts, doors };
}

/** Същото като summary() в Python: брой върхове/стени и граници на всеки възел. */
export function summary(parts) {
  const out = {};
  for (const p of parts) {
    const min = [0, 1, 2].map((k) => Math.min(...p.verts.map((v) => v[k])));
    const max = [0, 1, 2].map((k) => Math.max(...p.verts.map((v) => v[k])));
    out[p.name] = { verts: p.verts.length, faces: p.faces.length, min, max };
  }
  return out;
}

/** Затворено тяло с последователен ред на стените: всеки насочен ръб веднъж, обратният му — веднъж. */
export function isClosedManifold(verts, faces) {
  const seen = new Map();
  for (const f of faces) {
    for (let i = 0; i < f.length; i++) {
      const key = `${f[i]},${f[(i + 1) % f.length]}`;
      seen.set(key, (seen.get(key) || 0) + 1);
    }
  }
  for (const [key, c] of seen) {
    const [a, b] = key.split(',');
    if (c !== 1 || seen.get(`${b},${a}`) !== 1) return false;
  }
  return true;
}
