// venue-3d — сграда, която се върти в браузъра, с входовете и точките ѝ.
// ES модул; three.js е вграден в ../vendor/three (без CDN).
//
//   <script type="module" src="core/venue-3d.js"></script>
//   <venue-3d src="venue.json" lang="bg"></venue-3d>
//
// Зарежда model.glb; ако липсва — строи временен модел от skeleton.json (същата геометрия като Blender скрипта).
// Визията е само през CSS custom properties (--v3d-*).

import * as THREE from '../vendor/three/build/three.module.js';
import { OrbitControls } from '../vendor/three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from '../vendor/three/examples/jsm/loaders/GLTFLoader.js';
import {
  parseVenue, localText, planToThree, cameraPosition, clampTarget, hiddenNodes, hotspotShown,
  sortHotspots, resolveUrl, easeInOutCubic, bearingVector, explodeOffsets, formatElevation, fitDistance,
} from './venue-data.js';
import { buildParts } from './skeleton-geometry.js';

const T = {
  bg: {
    kind: { entrance: 'Вход', accessible_entrance: 'Достъпен вход', ticket_office: 'Каса', parking: 'Паркинг', transit_stop: 'Спирка', info: 'Информация' },
    list: 'Входове и точки', home: 'Начален изглед', open: 'Отвори сградата', level: 'Ниво',
    explode: 'Разглобен изглед', whole: 'Цялата сграда', close: 'Затвори', north: 'С', northLabel: 'Посока север',
    loading: 'Зареждане на модела…', noWebgl: 'Браузърът не може да покаже 3D (няма WebGL). Списъкът с входовете работи.',
    temp: 'Временен модел: model.glb липсва, сградата е построена от параметрите в skeleton.json.',
    broken: 'venue.json не може да се прочете.', noModel: 'Няма нито model.glb, нито skeleton.json за тази сграда.',
    elevation: 'кота', levelOf: 'Ниво',
  },
  en: {
    kind: { entrance: 'Entrance', accessible_entrance: 'Step-free entrance', ticket_office: 'Box office', parking: 'Car park', transit_stop: 'Stop', info: 'Information' },
    list: 'Entrances and points', home: 'Home view', open: 'Open the building', level: 'Level',
    explode: 'Exploded view', whole: 'Whole building', close: 'Close', north: 'N', northLabel: 'North',
    loading: 'Loading the model…', noWebgl: 'This browser cannot show 3D (no WebGL). The list of entrances still works.',
    temp: 'Temporary model: model.glb is missing, the building is built from the numbers in skeleton.json.',
    broken: 'venue.json cannot be read.', noModel: 'There is neither a model.glb nor a skeleton.json for this building.',
    elevation: 'elevation', levelOf: 'Level',
  },
};
// знак за вида точка — само текст, без изображения
const GLYPH = { entrance: '→', accessible_entrance: '♿', ticket_office: '▤', parking: 'P', transit_stop: '⇄', info: 'i' };
const PIN_VAR = {
  entrance: '--v3d-pin-entrance', accessible_entrance: '--v3d-pin-accessible', ticket_office: '--v3d-pin-service',
  info: '--v3d-pin-service', parking: '--v3d-pin-transport', transit_stop: '--v3d-pin-transport',
};
const MATERIAL_VAR = {
  building: ['--v3d-building', '#b9bec6'], roof: ['--v3d-roof', '#72849b'], pylon: ['--v3d-pylon', '#dcdfe3'],
  wing: ['--v3d-wing', '#a7adb5'], accent: ['--v3d-entrance', '#d9772b'], door: ['--v3d-door', '#2b3038'],
};
const FADED = 0.14;
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const v3 = (p) => new THREE.Vector3(...planToThree(p));

const STYLE = `
:host {
  display: block; container-type: inline-size;
  font-family: var(--v3d-font, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif);
  color: var(--v3d-fg, #1d232b);
  --_panel: var(--v3d-panel, #ffffff); --_border: var(--v3d-border, rgba(20,30,40,.14));
  --_muted: var(--v3d-muted, #5f6b78); --_accent: var(--v3d-accent, #2f6fbd); --_radius: var(--v3d-radius, 14px);
}
* { box-sizing: border-box; }
.root { display: grid; grid-template-columns: 1fr minmax(220px, 280px); gap: 12px; }
@container (max-width: 720px) { .root { grid-template-columns: 1fr; } }
.stage {
  position: relative; height: var(--v3d-height, 560px); overflow: hidden; border-radius: var(--_radius);
  background: var(--v3d-bg, linear-gradient(180deg, #dfe8f1, #f4f6f8)); border: 1px solid var(--_border);
  touch-action: none;
}
canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; outline: none; }
.pins, .tags { position: absolute; inset: 0; pointer-events: none; }
.pin {
  position: absolute; left: 0; top: 0; pointer-events: auto; transform: translate(-50%, -100%);
  display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px 3px 3px; border-radius: 999px;
  font: inherit; font-size: .8rem; cursor: pointer; white-space: nowrap;
  background: var(--v3d-pin-bg, rgba(255,255,255,.95)); color: var(--v3d-pin-fg, #1d232b);
  border: 1px solid var(--_border); box-shadow: 0 2px 6px rgba(0,0,0,.18);
  transition: opacity .2s;
}
.pin i {
  font-style: normal; width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center;
  color: #fff; font-weight: 700; font-size: .8rem; background: var(--_pin, var(--_accent));
}
.pin[hidden] { display: none; }
.pin.occluded { opacity: 0; pointer-events: none; }
.pin[aria-pressed="true"] { outline: 2px solid var(--_accent); outline-offset: 1px; }
.pin:focus-visible, button:focus-visible, select:focus-visible { outline: 2px solid var(--_accent); outline-offset: 2px; }
.tag {
  position: absolute; left: 0; top: 0; pointer-events: auto; transform: translate(0, -50%); cursor: pointer;
  font: inherit; font-size: .8rem; padding: 4px 10px; border-radius: 8px; white-space: nowrap;
  background: var(--_panel); color: inherit; border: 1px solid var(--_border); border-left: 3px solid var(--_accent);
}
.tag small { color: var(--_muted); margin-left: 6px; }
.tag[aria-pressed="true"] { background: var(--_accent); color: #fff; }
.tag[aria-pressed="true"] small { color: inherit; opacity: .85; }
.toolbar {
  position: absolute; left: 10px; top: 10px; right: 64px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
}
.toolbar button, .toolbar label, .toolbar select, .card button {
  font: inherit; font-size: .85rem; padding: 6px 10px; border-radius: 8px; cursor: pointer;
  background: var(--_panel); color: inherit; border: 1px solid var(--_border);
}
.toolbar label { display: inline-flex; gap: 6px; align-items: center; }
.toolbar [aria-pressed="true"] { background: var(--_accent); color: #fff; }
.compass {
  position: absolute; right: 10px; top: 10px; width: 44px; height: 44px; border-radius: 50%;
  background: var(--_panel); border: 1px solid var(--_border); display: grid; place-items: center;
}
.compass .needle { position: absolute; inset: 4px; transition: transform .1s linear; }
.compass .needle::before {
  content: ""; position: absolute; left: 50%; top: 2px; transform: translateX(-50%);
  border: 6px solid transparent; border-bottom: 14px solid var(--v3d-north, #d2402f);
}
.compass b { font-size: .7rem; margin-top: 14px; }
.status {
  position: absolute; left: 10px; bottom: 10px; right: 10px; padding: 8px 12px; border-radius: 8px; font-size: .85rem;
  background: var(--v3d-warn-bg, #fff4d6); color: var(--v3d-warn-fg, #5a4300); border: 1px solid var(--v3d-warn-border, #f0d48a);
}
.card {
  position: absolute; right: 10px; bottom: 10px; width: min(320px, calc(100% - 20px)); padding: 14px;
  background: var(--_panel); border: 1px solid var(--_border); border-radius: var(--_radius); box-shadow: 0 6px 18px rgba(0,0,0,.18);
}
.card h3 { margin: 0 0 4px; font-size: 1.05rem; }
.card p { margin: 6px 0 10px; }
.card .meta { color: var(--_muted); font-size: .85rem; }
nav {
  background: var(--_panel); border: 1px solid var(--_border); border-radius: var(--_radius); padding: 12px;
  max-height: var(--v3d-height, 560px); overflow: auto;
}
nav h3 { margin: 0 0 8px; font-size: .8rem; letter-spacing: .06em; text-transform: uppercase; color: var(--_muted); }
nav ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
nav button {
  width: 100%; text-align: left; display: flex; gap: 8px; align-items: center; font: inherit; font-size: .9rem;
  padding: 7px 8px; border-radius: 8px; border: 1px solid transparent; background: transparent; color: inherit; cursor: pointer;
}
nav button:hover, nav button[aria-current="true"] { border-color: var(--_border); background: rgba(127,127,127,.08); }
nav button i { font-style: normal; width: 20px; height: 20px; border-radius: 50%; flex: none; display: grid; place-items: center;
  color: #fff; font-size: .72rem; font-weight: 700; background: var(--_pin, var(--_accent)); }
nav small { color: var(--_muted); display: block; font-size: .78rem; }
[hidden] { display: none !important; }
`;

function defineElement() {
  class Venue3D extends HTMLElement {
    static get observedAttributes() { return ['src', 'lang']; }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' }).innerHTML = `<style>${STYLE}</style>
        <div class="root" part="root">
          <div class="stage" part="stage">
            <canvas tabindex="0"></canvas>
            <div class="tags" part="level-tags"></div>
            <div class="pins" part="pins"></div>
            <div class="toolbar" part="toolbar">
              <button type="button" data-act="home"></button>
              <button type="button" data-act="explode" aria-pressed="false"></button>
              <select data-act="level" aria-label=""></select>
              <label><input type="checkbox" data-act="open"> <span></span></label>
            </div>
            <div class="compass" part="compass" role="img"><span class="needle"></span><b></b></div>
            <div class="status" part="status" role="status" hidden></div>
            <div class="card" part="card" role="dialog" aria-live="polite" hidden></div>
          </div>
          <nav part="list"><h3></h3><ul></ul></nav>
        </div>`;
      this.$ = (s) => this.shadowRoot.querySelector(s);
      this.reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
      this.state = { open: false, level: null, selected: null, explode: 0, exploded: false, focus: null };
      this.anims = [];
    }

    get lang_() { return (this.getAttribute('lang') || document.documentElement.lang || 'bg').slice(0, 2) === 'en' ? 'en' : 'bg'; }
    get tx() { return T[this.lang_]; }

    connectedCallback() {
      this.bindUi();
      this.load();
    }

    disconnectedCallback() {
      cancelAnimationFrame(this.raf);
      this.ro?.disconnect();
      this.controls?.dispose();
      this.renderer?.dispose();
    }

    attributeChangedCallback(name, old, val) {
      if (!this.isConnected || old === val) return;
      if (name === 'lang') this.renderTexts(); else this.load();
    }

    // ---------------------------------------------------------------- зареждане

    async load() {
      const src = this.getAttribute('src');
      this.setStatus(this.tx.loading);
      let raw = null;
      try { raw = await (await fetch(src, { cache: 'no-cache' })).json(); } catch { /* по-долу */ }
      const { venue, errors, warnings } = parseVenue(raw);
      for (const m of [...errors, ...warnings]) console.warn(`venue-3d: ${m}`);
      if (!venue) { this.setStatus(this.tx.broken); return; }
      this.venue = venue;
      this.base = new URL(src, document.baseURI).href;
      this.state.level = venue.levels.length ? venue.levels[venue.levels.length - 1].id : null;
      this.renderTexts();
      if (!this.initScene()) { this.setStatus(this.tx.noWebgl); return; }

      let root = null;
      this.source = null;
      if (venue.model) {
        try {
          root = (await new GLTFLoader().loadAsync(resolveUrl(venue.model, this.base))).scene;
          this.source = 'glb';
        } catch { /* няма модел — временен от скелета */ }
      }
      if (!root && venue.skeleton) {
        try {
          const sk = typeof venue.skeleton === 'string'
            ? await (await fetch(resolveUrl(venue.skeleton, this.base))).json() : venue.skeleton;
          root = this.buildFromSkeleton(sk);
          this.source = 'skeleton';
        } catch (e) { console.warn('venue-3d: skeleton', e); }
      }
      if (!root) { this.setStatus(this.tx.noModel); return; }
      this.setModel(root);
      this.setStatus(this.source === 'skeleton' ? this.tx.temp : '');
      this.goHome(true);
    }

    setStatus(text) {
      const s = this.$('.status');
      s.textContent = text || '';
      s.hidden = !text;
    }

    // ---------------------------------------------------------------- сцена

    initScene() {
      if (this.renderer) return true;
      const canvas = this.$('canvas');
      try {
        this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
      } catch { return false; }
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(42, 1, 0.5, 4000);
      this.scene.add(new THREE.HemisphereLight(0xffffff, 0x6b7480, 1.6));
      const sun = new THREE.DirectionalLight(0xffffff, 2.2);
      sun.position.set(120, 220, 90);
      this.scene.add(sun);
      this.ground = new THREE.Mesh(new THREE.CircleGeometry(900, 72), new THREE.MeshStandardMaterial({ color: this.cssColor('--v3d-ground', '#dfe3e6') }));
      this.ground.rotation.x = -Math.PI / 2;
      this.ground.position.y = -0.03;
      this.scene.add(this.ground);

      const cam = this.venue.camera;
      const c = this.controls = new OrbitControls(this.camera, canvas);
      c.enableDamping = !this.reduced;
      c.dampingFactor = 0.08;
      c.screenSpacePanning = false;                         // местене по земята, не по екрана
      c.minDistance = cam.min_distance;
      c.maxDistance = cam.max_distance;
      c.maxPolarAngle = Math.PI / 2 - (cam.min_elevation_deg * Math.PI) / 180;  // не под земята
      c.minPolarAngle = 0.05;
      c.addEventListener('change', () => { this.clampControls(); this.dirty = true; });
      c.listenToKeyEvents(canvas);                          // стрелките местят, когато платното е на фокус

      this.raycaster = new THREE.Raycaster();
      canvas.addEventListener('pointerdown', (e) => { this.down = [e.clientX, e.clientY]; });
      canvas.addEventListener('pointerup', (e) => this.onPointerUp(e));
      this.ro = new ResizeObserver(() => this.resize());
      this.ro.observe(this.$('.stage'));
      this.resize();
      const tick = (now) => { this.raf = requestAnimationFrame(tick); this.frame(now); };
      this.raf = requestAnimationFrame(tick);
      return true;
    }

    cssColor(name, fallback) {
      return new THREE.Color(getComputedStyle(this).getPropertyValue(name).trim() || fallback);
    }

    resize() {
      const r = this.$('.stage').getBoundingClientRect();
      if (!r.width || !r.height) return;
      this.renderer.setSize(r.width, r.height, false);
      this.camera.aspect = r.width / r.height;
      this.camera.updateProjectionMatrix();
      this.dirty = true;
    }

    /** Временният модел: същите възли и имена като glb-то от Blender скрипта. */
    buildFromSkeleton(sk) {
      const { parts, doors } = buildParts(sk);
      const mats = {};
      const mat = (key) => (mats[key] ||= new THREE.MeshStandardMaterial({
        color: this.cssColor(...MATERIAL_VAR[key]), roughness: 0.85, flatShading: true,
      }));
      const mesh = (g, material) => {
        const pos = [];
        const index = [];
        for (const v of g.verts) pos.push(...planToThree(v));
        for (const f of g.faces) for (let i = 1; i < f.length - 1; i++) index.push(f[0], f[i], f[i + 1]);
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
        geo.setIndex(index);
        geo.computeVertexNormals();
        return new THREE.Mesh(geo, material);
      };
      const root = new THREE.Group();
      root.name = 'venue';
      for (const p of parts) {
        let obj = mesh(p, mat(p.material));
        if (p.kind === 'entrance') {
          const group = new THREE.Group();
          group.add(obj);
          const door = doors.find((d) => d.entrance === p.name);
          if (door) group.add(mesh(door, mat('door')));
          obj = group;
        }
        obj.name = p.name;
        obj.userData = { kind: p.kind, level: p.level };
        root.add(obj);
      }
      return root;
    }

    setModel(root) {
      if (this.model) this.scene.remove(this.model);
      this.model = root;
      this.scene.add(root);
      // всеки меш със собствен материал, за да може да избледнява поотделно
      root.traverse((o) => {
        if (o.isMesh) o.material = Array.isArray(o.material) ? o.material.map((m) => m.clone()) : o.material.clone();
        o.userData.baseY = o.position.y;
      });
      const levelOf = new Map();          // обект → id на ниво (по nodes в venue.json и по extras.level)
      this.levelObjects = this.venue.levels.map((lv) => {
        const set = new Set();
        for (const n of lv.nodes) { const o = root.getObjectByName(n); if (o) set.add(o); }
        root.traverse((o) => { if (o !== root && o.userData?.level === lv.id && o.parent === root) set.add(o); });
        for (const o of set) levelOf.set(o, lv.id);
        return [...set];
      });
      this.roofObjects = this.venue.roof_nodes.map((n) => root.getObjectByName(n)).filter(Boolean);
      this.otherObjects = root.children.filter((o) => !levelOf.has(o) && !this.roofObjects.includes(o));
      this.levelOf = levelOf;
      // коти и височина на нивата от самия модел (или от venue.json)
      this.levelInfo = this.venue.levels.map((lv, i) => {
        // котата и височината — от възела със същото име (самото ниво), иначе от възлите му
        const box = new THREE.Box3();
        const own = root.getObjectByName(lv.id);
        if (own) box.expandByObject(own);
        else for (const n of lv.nodes) { const o = root.getObjectByName(n); if (o) box.expandByObject(o); }
        const ok = !box.isEmpty();
        return {
          elevation: lv.elevation ?? (ok ? box.min.y : 0),
          height: ok ? box.max.y - box.min.y : 4,
          radius: ok ? Math.max(box.max.x - box.min.x, box.max.z - box.min.z) / 2 : 30,
          center: ok ? box.getCenter(new THREE.Vector3()) : new THREE.Vector3(),
        };
      });
      const all = new THREE.Box3().setFromObject(root);
      this.bounds = all;
      this.gap = this.venue.explode.gap ?? Math.max(4, ...this.levelInfo.map((l) => l.height)) * 1.2;
      this.buildPins();
      this.renderTags();
      this.applyVisibility();
    }

    // ---------------------------------------------------------------- кадър

    frame(now) {
      let changed = this.dirty;
      this.dirty = false;
      if (this.anims.length) {
        this.anims = this.anims.filter((a) => {
          const t = Math.min(1, (now - a.start) / a.dur);
          a.step(easeInOutCubic(t));
          return t < 1;
        });
        changed = true;
      }
      if (this.controls?.update()) changed = true;
      if (!changed || !this.model) return;
      this.renderer.render(this.scene, this.camera);
      this.updateOverlay();
    }

    animate(dur, step) {
      if (this.reduced || dur <= 0) { step(1); this.dirty = true; return; }
      this.anims.push({ start: performance.now(), dur, step });
    }

    clampControls() {
      const t = this.controls.target;
      const maxH = this.bounds ? this.bounds.max.y + this.gap * (this.venue.levels.length + 1) : 100;
      // целта в плана: x = x, y = −z, z = y
      const [x, y, z] = clampTarget([t.x, -t.z, t.y], this.venue.camera.max_target_radius, maxH);
      t.set(x, z, -y);
    }

    /** Плавно към изглед: цел и позиция в координатите на three.js. */
    flyTo(target, position, dur = 900) {
      const t0 = this.controls.target.clone(), p0 = this.camera.position.clone();
      this.animate(dur, (k) => {
        this.controls.target.lerpVectors(t0, target, k);
        this.camera.position.lerpVectors(p0, position, k);
        this.camera.lookAt(this.controls.target);
      });
    }

    /** Разстояние, от което се вижда сфера с този радиус при текущите пропорции на екрана. */
    fit(radius) {
      const c = this.venue.camera;
      return Math.min(c.max_distance, fitDistance(radius, this.camera.fov, this.camera.aspect));
    }

    goHome(instant = false) {
      const c = this.venue.camera;
      // на тесен (вертикален) екран камерата се отдръпва, за да се побере цялата сграда
      const size = this.bounds ? this.bounds.getBoundingSphere(new THREE.Sphere()).radius : 0;
      const dist = Math.max(c.distance, this.camera.aspect < 1 ? this.fit(size) : 0);
      const target = v3(c.target), pos = v3(cameraPosition(c.target, dist, c.azimuth_deg, c.elevation_deg));
      if (instant) {
        this.controls.target.copy(target);
        this.camera.position.copy(pos);
        this.camera.lookAt(target);
        this.dirty = true;
      } else this.flyTo(target, pos);
    }

    /** Текущият ъгъл на камерата по компас — за да се запази при полет към точка или ниво. */
    cameraBearing() {
      const d = this.camera.position.clone().sub(this.controls.target);
      return (Math.atan2(d.x, -d.z) * 180) / Math.PI;
    }

    // ---------------------------------------------------------------- видимост: отваряне, разглобяване, фокус

    offsetFor(obj) {
      const { levels, roof } = explodeOffsets(this.venue.levels.length, this.gap, this.state.explode);
      if (this.roofObjects.includes(obj)) return roof;
      const id = this.levelOf.get(obj);
      const i = this.venue.levels.findIndex((l) => l.id === id);
      return i >= 0 ? levels[i] : 0;
    }

    levelOffset(levelId) {
      const i = this.venue.levels.findIndex((l) => l.id === levelId);
      return i < 0 ? 0 : explodeOffsets(this.venue.levels.length, this.gap, this.state.explode).levels[i];
    }

    applyVisibility() {
      if (!this.model) return;
      const s = this.state;
      const openMode = s.open && !s.exploded;
      const hidden = hiddenNodes(this.venue, openMode, s.level);       // покривът и възлите на нивата отгоре
      const idx = this.venue.levels.findIndex((l) => l.id === s.level);
      const levelHidden = (id) => openMode && idx >= 0 && this.venue.levels.findIndex((l) => l.id === id) > idx;
      for (const o of this.model.children) {
        const lvl = this.levelOf.get(o);
        o.visible = !hidden.has(o.name) && !(lvl && levelHidden(lvl));
        o.position.y = o.userData.baseY + this.offsetFor(o);
        // избледняване: при фокус — всичко извън нивото; в разглобен изглед — пилоните и околното
        const faded = s.focus ? lvl !== s.focus : (s.explode > 0 && this.otherObjects.includes(o));
        o.traverse((m) => {
          if (!m.isMesh) return;
          for (const mat of [].concat(m.material)) {
            mat.transparent = faded;
            mat.opacity = faded ? FADED : 1;
            mat.depthWrite = !faded;
          }
        });
      }
      this.dirty = true;
    }

    setExploded(on) {
      const s = this.state;
      s.exploded = on;
      if (on) s.open = false;
      if (!on) s.focus = null;
      const from = s.explode, to = on ? 1 : 0;
      this.animate(800, (k) => { s.explode = from + (to - from) * k; this.applyVisibility(); });
      if (on) {
        // камерата се отдръпва, за да се вижда цялата купчина нива
        const top = (this.bounds?.max.y ?? 30) + this.gap * this.venue.levels.length;
        const radius = Math.max(...this.levelInfo.map((l) => l.radius)) + 24;   // + място за етикетите
        const target = v3([0, 0, top / 2]);
        this.flyTo(target, v3(cameraPosition([0, 0, top / 2], this.fit(Math.hypot(radius, top / 2)), this.cameraBearing(), 22)));
      } else this.goHome();
      this.renderTexts();
    }

    focusLevel(id) {
      const s = this.state;
      if (!s.exploded) this.setExploded(true);
      s.focus = s.focus === id ? null : id;
      // картата на точка от друго ниво се затваря
      const sel = this.venue.hotspots.find((h) => h.id === s.selected);
      if (s.focus && sel && sel.level !== s.focus) this.closeCard();
      this.applyVisibility();
      this.renderTexts();
      if (!s.focus) return;
      const i = this.venue.levels.findIndex((l) => l.id === id);
      const info = this.levelInfo[i];
      const y = info.elevation + info.height / 2 + explodeOffsets(this.venue.levels.length, this.gap, 1).levels[i];
      const target = new THREE.Vector3(info.center.x, y, info.center.z);
      const plan = [target.x, -target.z, target.y];
      this.flyTo(target, v3(cameraPosition(plan, Math.max(40, this.fit(info.radius + 20)), this.cameraBearing(), 38)));
    }

    // ---------------------------------------------------------------- точки

    buildPins() {
      const pins = this.$('.pins');
      pins.innerHTML = '';
      this.pinEls = new Map();
      for (const h of this.venue.hotspots) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'pin';
        b.dataset.id = h.id;
        b.setAttribute('aria-pressed', 'false');
        b.style.setProperty('--_pin', `var(${PIN_VAR[h.kind]}, var(--_accent))`);
        b.addEventListener('click', () => this.select(h.id));
        pins.append(b);
        this.pinEls.set(h.id, b);
      }
      this.renderPinTexts();
    }

    hotspotWorld(h) {
      const p = v3(h.position);
      if (h.level) p.y += this.levelOffset(h.level);
      return p;
    }

    hotspotVisible(h) {
      const s = this.state;
      if (!hotspotShown(this.venue, h, s.open && !s.exploded, s.level)) return false;
      if (s.focus) return h.level === s.focus;
      return true;
    }

    updateOverlay() {
      const r = this.$('.stage').getBoundingClientRect();
      const w = r.width, hgt = r.height;
      const blockers = [];
      this.model.traverse((o) => {
        if (!o.isMesh) return;
        let vis = true;
        for (let p = o; p; p = p.parent) if (!p.visible) { vis = false; break; }
        if (vis && [].concat(o.material)[0].opacity > 0.5) blockers.push(o);
      });
      const camPos = this.camera.position;
      for (const h of this.venue.hotspots) {
        const el = this.pinEls.get(h.id);
        if (!this.hotspotVisible(h)) { el.hidden = true; continue; }
        const wp = this.hotspotWorld(h);
        const sp = wp.clone().project(this.camera);
        if (sp.z > 1 || sp.z < -1) { el.hidden = true; continue; }
        el.hidden = false;
        el.style.transform = `translate(${((sp.x + 1) / 2) * w}px, ${((1 - sp.y) / 2) * hgt}px) translate(-50%, -100%)`;
        // скрита зад сградата: лъч от камерата до точката пресича нещо по-близо
        const dir = wp.clone().sub(camPos);
        const dist = dir.length();
        this.raycaster.set(camPos, dir.normalize());
        this.raycaster.far = dist - 1.5;
        el.classList.toggle('occluded', this.raycaster.intersectObjects(blockers, false).length > 0);
      }
      // компасът: къде е северът на екрана
      const t = this.controls.target;
      const [bx, by] = bearingVector(this.venue.north_deg);
      const a = t.clone().project(this.camera), b = t.clone().add(v3([bx * 10, by * 10, 0])).project(this.camera);
      const deg = (Math.atan2(b.x - a.x, (b.y - a.y) * (hgt / w)) * 180) / Math.PI;
      this.$('.needle').style.transform = `rotate(${deg}deg)`;
      this.updateTags(w, hgt);
    }

    select(id, fromList = false) {
      const h = this.venue.hotspots.find((x) => x.id === id);
      if (!h) return;
      const s = this.state;
      s.selected = id;
      if (s.exploded && h.level && s.focus !== h.level) { s.focus = h.level; this.applyVisibility(); }
      // точка вътре в сградата: отваряме я до нейното ниво
      if (!s.exploded && h.inside && h.level) { s.open = true; s.level = h.level; this.applyVisibility(); }
      if (s.focus && !h.level) { s.focus = null; this.applyVisibility(); }
      this.renderTexts();
      this.showCard(h);
      if (!this.renderer) return;
      const wp = this.hotspotWorld(h);
      const plan = [wp.x, -wp.z, wp.y];
      const outward = Math.hypot(plan[0], plan[1]) > 1 ? (Math.atan2(plan[0], plan[1]) * 180) / Math.PI : this.cameraBearing();
      this.flyTo(wp, v3(cameraPosition(plan, 48, outward, 30)));
      if (fromList) this.pinEls.get(id)?.focus({ preventScroll: true });
    }

    showCard(h) {
      const tx = this.tx, card = this.$('.card');
      const lv = this.venue.levels.find((l) => l.id === h.level);
      card.innerHTML = `<h3>${esc(localText(h.name, this.lang_))}</h3>
        <div class="meta">${esc(tx.kind[h.kind])}${lv ? ` · ${esc(localText(lv.name, this.lang_))}` : ''}</div>
        ${h.description ? `<p>${esc(localText(h.description, this.lang_))}</p>` : ''}
        <button type="button" data-act="close">${tx.close}</button>`;
      card.hidden = false;
      card.querySelector('[data-act=close]').addEventListener('click', () => this.closeCard());
    }

    closeCard() {
      this.$('.card').hidden = true;
      this.state.selected = null;
      this.renderTexts();
    }

    onPointerUp(e) {
      if (!this.down || Math.hypot(e.clientX - this.down[0], e.clientY - this.down[1]) > 5 || !this.model) return;
      const r = this.$('canvas').getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      this.raycaster.far = Infinity;
      this.raycaster.setFromCamera(ndc, this.camera);
      const hit = this.raycaster.intersectObject(this.model, true).find((x) => {
        for (let p = x.object; p; p = p.parent) if (!p.visible) return false;
        return true;
      });
      if (!hit) return;
      let o = hit.object;
      while (o.parent && o.parent !== this.model) o = o.parent;
      const lvl = this.levelOf.get(o);
      // в разглобен изглед кликът върху ниво го избира
      if (this.state.exploded && lvl) this.focusLevel(lvl);
    }

    // ---------------------------------------------------------------- етикети на нивата (разглобен изглед)

    renderTags() {
      const box = this.$('.tags');
      box.innerHTML = '';
      this.tagEls = this.venue.levels.map((lv) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'tag';
        b.addEventListener('click', () => this.focusLevel(lv.id));
        box.append(b);
        return b;
      });
      this.renderTagTexts();
    }

    updateTags(w, h) {
      const show = this.state.explode > 0.02;
      const right = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
      this.venue.levels.forEach((lv, i) => {
        const el = this.tagEls[i];
        el.hidden = !show;
        if (!show) return;
        const info = this.levelInfo[i];
        const p = info.center.clone();
        p.y = info.elevation + info.height / 2 + this.levelOffset(lv.id);
        p.addScaledVector(right, info.radius + 6);
        const sp = p.project(this.camera);
        // етикетът не излиза извън десния ръб на сцената
        const x = Math.min(((sp.x + 1) / 2) * w, w - el.offsetWidth - 8);
        el.style.transform = `translate(${Math.max(8, x)}px, ${((1 - sp.y) / 2) * h}px) translate(0, -50%)`;
        el.style.opacity = String(Math.min(1, this.state.explode * 1.5));
      });
    }

    // ---------------------------------------------------------------- интерфейс

    bindUi() {
      const q = (a) => this.$(`[data-act=${a}]`);
      q('home').addEventListener('click', () => {
        if (this.state.exploded) this.setExploded(false); else this.goHome();
      });
      q('explode').addEventListener('click', () => this.setExploded(!this.state.exploded));
      q('level').addEventListener('change', (e) => { this.state.level = e.target.value; this.applyVisibility(); this.renderTexts(); });
      q('open').addEventListener('change', (e) => {
        if (this.state.exploded) this.setExploded(false);
        this.state.open = e.target.checked;
        this.applyVisibility();
      });
      this.shadowRoot.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') this.closeCard();
        const items = [...this.shadowRoot.querySelectorAll('nav button')];
        const i = items.indexOf(this.shadowRoot.activeElement);
        if (i < 0) return;
        const next = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: items.length - 1 }[e.key];
        if (next != null) { e.preventDefault(); items[(next + items.length) % items.length].focus(); }
      });
    }

    renderTexts() {
      if (!this.venue) return;
      const tx = this.tx, lang = this.lang_, s = this.state;
      const q = (a) => this.$(`[data-act=${a}]`);
      q('home').textContent = s.exploded ? tx.whole : tx.home;
      q('explode').textContent = tx.explode;
      q('explode').setAttribute('aria-pressed', String(s.exploded));
      q('explode').hidden = !this.venue.levels.length;
      const sel = q('level');
      sel.setAttribute('aria-label', tx.level);
      sel.innerHTML = this.venue.levels.map((l) => `<option value="${esc(l.id)}"${l.id === s.level ? ' selected' : ''}>${esc(localText(l.name, lang))}</option>`).join('');
      sel.hidden = !this.venue.levels.length || s.exploded;
      q('open').checked = s.open && !s.exploded;
      q('open').parentElement.hidden = !this.venue.levels.length || s.exploded;
      q('open').nextElementSibling.textContent = tx.open;
      const compass = this.$('.compass');
      compass.setAttribute('aria-label', tx.northLabel);
      compass.querySelector('b').textContent = tx.north;

      this.$('nav h3').textContent = tx.list;
      this.$('nav ul').innerHTML = sortHotspots(this.venue.hotspots, lang).map((h) => {
        const lv = this.venue.levels.find((l) => l.id === h.level);
        return `<li><button type="button" data-id="${esc(h.id)}" aria-current="${h.id === s.selected}" style="--_pin: var(${PIN_VAR[h.kind]}, var(--_accent))">
          <i aria-hidden="true">${GLYPH[h.kind]}</i><span>${esc(localText(h.name, lang))}
          <small>${esc(tx.kind[h.kind])}${lv ? ` · ${esc(localText(lv.name, lang))}` : ''}</small></span></button></li>`;
      }).join('');
      this.$('nav ul').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => this.select(b.dataset.id)));
      this.renderPinTexts();
      this.renderTagTexts();
      if (s.selected) this.showCard(this.venue.hotspots.find((h) => h.id === s.selected));
      if (this.source === 'skeleton') this.setStatus(tx.temp);
    }

    renderPinTexts() {
      if (!this.pinEls) return;
      for (const h of this.venue.hotspots) {
        const b = this.pinEls.get(h.id);
        const name = localText(h.name, this.lang_);
        b.innerHTML = `<i aria-hidden="true">${GLYPH[h.kind]}</i><span>${esc(name)}</span>`;
        b.setAttribute('aria-label', `${this.tx.kind[h.kind]}: ${name}`);
        b.setAttribute('aria-pressed', String(h.id === this.state.selected));
      }
    }

    renderTagTexts() {
      if (!this.tagEls || !this.levelInfo) return;
      this.venue.levels.forEach((lv, i) => {
        const el = this.tagEls[i];
        el.innerHTML = `${esc(localText(lv.name, this.lang_))}<small>${this.tx.elevation} ${formatElevation(this.levelInfo[i].elevation, this.lang_)}</small>`;
        el.setAttribute('aria-pressed', String(this.state.focus === lv.id));
      });
    }
  }
  if (!customElements.get('venue-3d')) customElements.define('venue-3d', Venue3D);
}

if (typeof customElements !== 'undefined' && typeof HTMLElement !== 'undefined') defineElement();

