// pravila.js и очакваният изход са генерирани от apps/doverie — тестът пада, ако ядрото се промени без тях.
const { spawnSync } = require('child_process');
const path = require('path');
const { LNA } = require('./pomoshtni');

test('src/pravila.js и tests/fixtures/ocakvano.json са в синхрон с apps/doverie', () => {
  const r = spawnSync('python3', [path.join(LNA, 'scripts', 'gen_pravila.py'), '--proveri'], { encoding: 'utf8' });
  expect(r.error).toBeUndefined();
  expect([r.status, r.stdout + r.stderr]).toEqual([0, '']);
});
