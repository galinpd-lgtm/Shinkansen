// Правата: само activeTab, scripting, storage, sidePanel; без <all_urls> и без постоянни права за сайтове.
const fs = require('fs');
const path = require('path');
const { LNA } = require('./pomoshtni');
const m = JSON.parse(fs.readFileSync(path.join(LNA, 'manifest.json'), 'utf8'));

test('Manifest V3 с минимални права', () => {
  expect(m.manifest_version).toBe(3);
  expect(m.permissions.sort()).toEqual(['activeTab', 'scripting', 'sidePanel', 'storage']);
  expect(m.host_permissions).toBeUndefined();
  expect(m.content_scripts).toBeUndefined();
  expect(JSON.stringify(m)).not.toContain('<all_urls>');
});

test('всички файлове от manifest-а съществуват', () => {
  const faylove = [m.background.service_worker, m.side_panel.default_path, m.options_page,
    ...Object.values(m.icons), ...Object.values(m.action.default_icon)];
  faylove.forEach((f) => expect([f, fs.existsSync(path.join(LNA, f))]).toEqual([f, true]));
});

test('българският е основният език', () => {
  expect(m.default_locale).toBe('bg');
  const msg = JSON.parse(fs.readFileSync(path.join(LNA, '_locales', 'bg', 'messages.json'), 'utf8'));
  ['ime', 'opisanie', 'deystvie'].forEach((k) => expect(msg[k].message).toBeTruthy());
});

test('фоновият скрипт зарежда само локални файлове', () => {
  const bg = fs.readFileSync(path.join(LNA, 'src', 'background.js'), 'utf8');
  const imp = bg.match(/importScripts\(([^)]*)\)/)[1];
  imp.split(',').map((x) => x.trim().replace(/['"]/g, '')).forEach((f) => {
    expect(fs.existsSync(path.join(LNA, 'src', f))).toBe(true);
  });
});
