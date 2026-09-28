// Настройките: празен адрес не иска разрешения; адрес иска достъп само до себе си.
const { falshivChrome } = require('./pomoshtni');
const O = require('../src/options.js');
const L = require('../src/logika.js');

const MODULI = { pohvati: true, vaprosi: true, istoriya: true };

test('празен адрес — без разрешения, само правила', async () => {
  const chrome = falshivChrome();
  const t = await O.zapazi(chrome, { adres: '  ', prag: '5', moduli: MODULI });
  expect(t).toContain('нищо не напуска браузъра');
  expect(chrome._vikaniya.permissions).toEqual([]);
  expect((await L.nastroyki(chrome)).adres).toBe('');
});

test('адрес — иска достъп само до този адрес', async () => {
  const chrome = falshivChrome();
  await O.zapazi(chrome, { adres: 'http://127.0.0.1:8765/', prag: 6.5, moduli: MODULI });
  expect(chrome._vikaniya.permissions).toEqual([{ origins: ['http://127.0.0.1:8765/*'] }]);
  const n = await L.nastroyki(chrome);
  expect(n.adres).toBe('http://127.0.0.1:8765');
  expect(n.prag).toBe(6.5);
});

test('отказано разрешение — нищо не се записва', async () => {
  const chrome = falshivChrome();
  chrome._razreshi = false;
  await expect(O.zapazi(chrome, { adres: 'http://192.0.2.10:8765', prag: 5, moduli: MODULI })).rejects.toThrow('Нищо не е записано');
  expect((await chrome.storage.local.get('nastroyki')).nastroyki).toBeUndefined();
});

test.each([['ftp://example.org', 'http://'], ['не е адрес', 'не е валиден'], ['http://127.0.0.1:8765/?x=1', 'без „?“']])(
  'грешен адрес %p', async (adres, duma) => {
    await expect(O.zapazi(falshivChrome(), { adres, prag: 5, moduli: MODULI })).rejects.toThrow(duma);
  });

test('прагът е от 0 до 10', async () => {
  await expect(O.zapazi(falshivChrome(), { adres: '', prag: 11, moduli: MODULI })).rejects.toThrow('от 0 до 10');
});
