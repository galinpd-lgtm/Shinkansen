// Поверителност: без адрес за пълна оценка — нула мрежови заявки. С адрес — само текстът, само към него.
const fs = require('fs');
const path = require('path');
const { LNA, OCAKVANO, falshivChrome } = require('./pomoshtni');
const L = require('../src/logika.js');

const STATIYA = OCAKVANO.sluchai.find((s) => s.ime === 'stranica_1.txt').tekst;
const IZVLECHENO = { zaglavie: 'Общината ремонтира три училища през лятото', tekst: STATIYA, url: 'https://example.org/a' };
const TAB = { id: 7, url: 'https://example.org/a' };

let mrezha;
beforeEach(() => {
  mrezha = [];
  // всичко, с което може да се излезе навън
  global.fetch = jest.fn(async (...a) => { mrezha.push(['fetch', a[0]]); throw new Error('мрежа в тест'); });
  global.XMLHttpRequest = jest.fn(() => { mrezha.push(['xhr']); });
  global.WebSocket = jest.fn(() => { mrezha.push(['ws']); });
  global.navigator = { sendBeacon: jest.fn(() => { mrezha.push(['beacon']); }) };
});

test('без адрес → нула заявки', async () => {
  const chrome = falshivChrome(IZVLECHENO);
  const fetchFn = jest.fn();
  await L.analiziray({ chrome, tab: TAB, fetchFn });
  expect(fetchFn).not.toHaveBeenCalled();
  expect(mrezha).toEqual([]);
  const z = (await chrome.storage.session.get('tab_7')).tab_7;
  expect(z.status).toBe('gotovo');
  expect(z.izvor).toBe('правила');
  expect(Object.keys(z.rez.profil.osi)).toHaveLength(7);
});

test('по подразбиране адресът е празен', () => {
  expect(L.PO_PODRAZBIRANE.adres).toBe('');
});

test('анализът е само при натискане: фоновият скрипт не слуша страници и не се пуска сам', () => {
  const bg = fs.readFileSync(path.join(LNA, 'src', 'background.js'), 'utf8');
  expect(bg).toMatch(/chrome\.action\.onClicked\.addListener/);
  expect(bg).not.toMatch(/tabs\.onUpdated|webNavigation|onCompleted|alarms/);
  const m = JSON.parse(fs.readFileSync(path.join(LNA, 'manifest.json'), 'utf8'));
  expect(m.content_scripts).toBeUndefined();
});

test('единственото мрежово викане в кода е в palnaOcenka', () => {
  const src = path.join(LNA, 'src');
  for (const f of fs.readdirSync(src).filter((x) => x.endsWith('.js'))) {
    const t = fs.readFileSync(path.join(src, f), 'utf8');
    expect([f, /XMLHttpRequest|sendBeacon|WebSocket|EventSource|new Image\(|importScripts\(['"]https?:/.test(t)]).toEqual([f, false]);
    const fetchove = (t.match(/fetch(Fn)?\(/g) || []).length;
    if (f === 'logika.js') expect(fetchove).toBe(1);
    else if (f === 'background.js') expect(t).toMatch(/function mreza\(\) \{ return fetch\.apply/);
    else expect([f, fetchove]).toEqual([f, 0]);
  }
});

test('с адрес — само текстът и адресът на статията, само към въведения адрес', async () => {
  const chrome = falshivChrome(IZVLECHENO);
  await chrome.storage.local.set({ nastroyki: { adres: 'http://127.0.0.1:8765', prag: 5, moduli: {} } });
  const profil = { profil: { osi: { 1: {} }, obshta_ocenka: 7, po_dumi: 'Добра', uverenost: { nivo: 'средна' } }, pohvati: [], reshenie: { ime: 'ПРОПУСНИ' } };
  const fetchFn = jest.fn(async () => ({ ok: true, status: 200, json: async () => profil }));
  await L.analiziray({ chrome, tab: TAB, fetchFn });
  expect(fetchFn).toHaveBeenCalledTimes(1);
  const [url, opcii] = fetchFn.mock.calls[0];
  expect(url).toBe('http://127.0.0.1:8765/ocenka');
  expect(JSON.parse(opcii.body)).toEqual({ tekst: STATIYA, iztochnik: 'https://example.org/a' });
  expect(opcii.credentials).toBe('omit');
  expect(opcii.referrerPolicy).toBe('no-referrer');
  const z = (await chrome.storage.session.get('tab_7')).tab_7;
  expect(z.izvor).toBe('пълна оценка');
  expect(mrezha).toEqual([]);
});

test('заета машина или грешка → оценката само с правила и бележка', async () => {
  for (const [otg, duma] of [[{ ok: false, status: 503 }, 'заета'], [{ ok: false, status: 500 }, 'код 500']]) {
    const chrome = falshivChrome(IZVLECHENO);
    await chrome.storage.local.set({ nastroyki: { adres: 'http://127.0.0.1:8765' } });
    await L.analiziray({ chrome, tab: TAB, fetchFn: async () => otg });
    const z = (await chrome.storage.session.get('tab_7')).tab_7;
    expect(z.izvor).toBe('правила');
    expect(z.belezhka).toContain(duma);
  }
});

test('кеш 1 час по адрес на страницата', async () => {
  const chrome = falshivChrome(IZVLECHENO);
  await L.analiziray({ chrome, tab: TAB, fetchFn: jest.fn(), sega: 1000 });
  await L.analiziray({ chrome, tab: TAB, fetchFn: jest.fn(), sega: 1000 + 59 * 60 * 1000 });
  expect(chrome._vikaniya.executeScript).toBe(1);
  expect((await chrome.storage.session.get('tab_7')).tab_7.ot_kesha).toBe(true);
  await L.analiziray({ chrome, tab: TAB, fetchFn: jest.fn(), sega: 1000 + 61 * 60 * 1000 });
  expect(chrome._vikaniya.executeScript).toBe(2);
  await L.analiziray({ chrome, tab: TAB, fetchFn: jest.fn(), sega: 1000 + 62 * 60 * 1000, bezKesh: true });
  expect(chrome._vikaniya.executeScript).toBe(3);
});

test('историята: последните 100, само обобщение, изтрива се', async () => {
  const chrome = falshivChrome(IZVLECHENO);
  for (let i = 0; i < 105; i++) {
    await L.analiziray({ chrome, tab: { id: 1, url: 'https://example.org/' + i }, fetchFn: jest.fn(), sega: 1000 + i });
  }
  const ist = (await chrome.storage.local.get('istoriya')).istoriya;
  expect(ist).toHaveLength(100);
  expect(ist[0].url).toBe('https://example.org/104');
  expect(JSON.stringify(ist)).not.toContain('училища в кварталите');  // без текста на статията
  await L.iztriyIstoriyata(chrome);
  expect(await chrome.storage.local.get(['istoriya', 'kesh'])).toEqual({});
});

test('историята може да се изключи', async () => {
  const chrome = falshivChrome(IZVLECHENO);
  await chrome.storage.local.set({ nastroyki: { moduli: { istoriya: false } } });
  await L.analiziray({ chrome, tab: TAB, fetchFn: jest.fn() });
  expect((await chrome.storage.local.get('istoriya')).istoriya).toBeUndefined();
});

test('страници, които не са статии', async () => {
  let chrome = falshivChrome(IZVLECHENO);
  await L.analiziray({ chrome, tab: { id: 2, url: 'chrome://settings' }, fetchFn: jest.fn() });
  expect((await chrome.storage.session.get('tab_2')).tab_2.greshka).toContain('само статии');
  chrome = falshivChrome({ zaglavie: '', tekst: 'Кратко.' });
  await L.analiziray({ chrome, tab: TAB, fetchFn: jest.fn() });
  expect((await chrome.storage.session.get('tab_7')).tab_7.greshka).toContain('не намерих текст');
});
