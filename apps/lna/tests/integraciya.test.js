// Пълната оценка срещу истинския `python -m doverie serve` на 127.0.0.1 (без модел — пътят е същият).
const { spawn } = require('child_process');
const net = require('net');
const path = require('path');
const { LNA, OCAKVANO } = require('./pomoshtni');
const L = require('../src/logika.js');
const { narisuvay } = require('../src/panel.js');
const { JSDOM } = require('jsdom');

let sarvar, port;
const nodeFetch = globalThis.fetch;

function svobodenPort() {
  return new Promise((ok) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => ok(p)); }); });
}

beforeAll(async () => {
  port = await svobodenPort();
  sarvar = spawn('python3', ['-m', 'doverie', 'serve', '--bez-model', '--port', String(port)],
    { cwd: path.join(LNA, '..', 'doverie'), stdio: 'ignore' });
  for (let i = 0; i < 50; i++) {
    try { const r = await nodeFetch(`http://127.0.0.1:${port}/zdrave`); if (r.ok) return; } catch (e) { /* още не */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error('doverie serve не тръгна');
}, 15000);

afterAll(() => { if (sarvar) sarvar.kill(); });

test('с въведен адрес — пълният профил от doverie serve, 7 оси', async () => {
  const tekst = OCAKVANO.sluchai.find((s) => s.ime === 'stranica_4.txt').tekst;
  const rez = await L.palnaOcenka(`http://127.0.0.1:${port}`, tekst, 'https://example.org/b', (...a) => nodeFetch(...a));
  expect(Object.keys(rez.profil.osi)).toHaveLength(7);
  expect(rez.profil.osi['7'].vaprosi).toHaveLength(10);
  expect(rez.izmereno_v).toBe('пълна оценка');
  const { document } = new JSDOM('<main id="lenta"></main>').window;
  const k = document.getElementById('lenta');
  narisuvay(document, k, { status: 'gotovo', zaglavie: 'Нова програма', izvor: 'пълна оценка', rez },
    { prag: 5, moduli: { pohvati: true, vaprosi: true } });
  expect(k.querySelectorAll('.os')).toHaveLength(7);
  expect(k.querySelector('.rezhim').textContent).toBe('пълна оценка');
}, 15000);
