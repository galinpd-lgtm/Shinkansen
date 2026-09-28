// Изпитание в истински Chromium: зарежда разширението, проверява, че тръгва без грешки, и прави снимки на лентата.
//
//   NODE_PATH=$(npm root -g) node scripts/izpitay_v_chromium.mjs [--snimki store/snimki]
//
// Натискането на иконата не може да се автоматизира (това е целта на activeTab), затова скриптът повтаря същия
// път на ръка: content.js в страницата → двигателят във фоновия скрипт на разширението → лентата (panel.html).
// Страниците са измислените от tests/fixtures/stranici. Нищо не се праща навън.
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const LNA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const SNIMKI = argv.includes('--snimki') ? path.resolve(argv[argv.indexOf('--snimki') + 1]) : null;
const IZPALNIM = process.env.CHROMIUM_PATH || undefined;

const greshki = [];
const ctx = await chromium.launchPersistentContext('', {
  channel: 'chromium',
  headless: true,
  executablePath: IZPALNIM,
  viewport: { width: 400, height: 900 },
  deviceScaleFactor: 2,
  locale: 'bg-BG',
  args: [`--disable-extensions-except=${LNA}`, `--load-extension=${LNA}`]
});
ctx.on('weberror', (e) => greshki.push('страница: ' + e.error().message));

let [sw] = ctx.serviceWorkers();
if (!sw) sw = await ctx.waitForEvent('serviceworker', { timeout: 10000 });
const id = sw.url().split('/')[2];
console.log('разширението е заредено:', id);

// фоновият скрипт: правилата и двигателят са заредени, събитието на иконата е закачено
const bgOk = await sw.evaluate(() => typeof DVIGATEL === 'object' && typeof LOGIKA === 'object' &&
  typeof chrome.action.onClicked.hasListeners === 'function' && chrome.action.onClicked.hasListeners());
if (!bgOk) greshki.push('фоновият скрипт не е готов');

const content = fs.readFileSync(path.join(LNA, 'src', 'content.js'), 'utf8');
const rezultati = [];
for (const n of [1, 2, 3, 4, 5]) {
  const page = await ctx.newPage();
  page.on('pageerror', (e) => greshki.push(`stranica_${n}: ${e.message}`));
  await page.goto('file://' + path.join(LNA, 'tests', 'fixtures', 'stranici', `stranica_${n}.html`));
  const t0 = Date.now();
  const izvl = await page.evaluate(content);           // точно файлът, който executeScript вкарва
  const zapis = await sw.evaluate(([i, u]) => {         // двигателят във фоновия скрипт
    const t = performance.now();
    const rez = DVIGATEL.ocenka(i.tekst, u);
    return { status: 'gotovo', vreme: Date.now(), url: u, zaglavie: i.zaglavie, izvor: 'правила', rez, ms: performance.now() - t };
  }, [izvl, `https://example.org/stranica_${n}`]);
  const obshto = Date.now() - t0;
  rezultati.push({ n, zapis, obshto });
  console.log(`stranica_${n}: ${zapis.rez.profil.obshta_ocenka} ${zapis.rez.reshenie.ime}, похвати: ${zapis.rez.pohvati.length}, ` +
    `двигател ${zapis.ms.toFixed(1)} ms, общо ${obshto} ms`);
  if (obshto >= 1000) greshki.push(`stranica_${n}: ${obshto} ms — над 1 секунда`);
  await page.close();
}

// лентата в самото разширение
const panel = await ctx.newPage();
panel.on('pageerror', (e) => greshki.push('лента: ' + e.message));
panel.on('console', (m) => { if (m.type() === 'error') greshki.push('лента: ' + m.text()); });
await panel.goto(`chrome-extension://${id}/src/panel.html`);
await panel.waitForSelector('.prazno');   // лентата е тръгнала сама и чака натискане
await panel.waitForTimeout(200);
for (const { n, zapis } of rezultati) {
  await panel.evaluate((z) => LNA_PANEL.narisuvay(document, document.getElementById('lenta'), z,
    { prag: 5.0, moduli: { pohvati: true, vaprosi: true, istoriya: true } }), zapis);
  const osi = await panel.locator('.os').count();
  if (osi !== 7) greshki.push(`лента stranica_${n}: ${osi} оси`);
  if (SNIMKI && [2, 3, 4].includes(n)) {
    fs.mkdirSync(SNIMKI, { recursive: true });
    const f = path.join(SNIMKI, `lenta_stranica_${n}.png`);
    await panel.screenshot({ path: f, fullPage: true });
    console.log('снимка:', path.relative(process.cwd(), f));
  }
}
// настройките се отварят без грешки
const opcii = await ctx.newPage();
opcii.on('pageerror', (e) => greshki.push('настройки: ' + e.message));
await opcii.goto(`chrome-extension://${id}/src/options.html`);
await opcii.waitForTimeout(300);
if ((await opcii.inputValue('#adres')) !== '') greshki.push('адресът по подразбиране не е празен');

await ctx.close();
if (greshki.length) { console.log('ГРЕШКИ:\n  ' + greshki.join('\n  ')); process.exit(1); }
console.log('наред: разширението се зарежда без грешки; 5 страници, всяка под 1 секунда');
