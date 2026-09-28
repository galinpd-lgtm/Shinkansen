/** @jest-environment jsdom */
// Лентата: редът от Z7b, чист български, никакъв HTML от страницата или сървъра.
const { OCAKVANO, procheti, LNA } = require('./pomoshtni');
const path = require('path');
const fs = require('fs');
const D = require('../src/dvigatel.js');
const { narisuvay } = require('../src/panel.js');

const NASTROYKI = { prag: 5.0, moduli: { pohvati: true, vaprosi: true, istoriya: true } };
function zapisZa(ime, dop) {
  const s = OCAKVANO.sluchai.find((x) => x.ime === ime);
  return Object.assign({ status: 'gotovo', zaglavie: 'Заглавие', izvor: 'правила', rez: D.ocenka(s.tekst, 'https://example.org/a') }, dop || {});
}
function risuvay(zapis, n) {
  document.body.innerHTML = '<main id="lenta"></main>';
  const kade = document.getElementById('lenta');
  narisuvay(document, kade, zapis, n || NASTROYKI);
  return kade;
}

test('редът: оси → увереност/покритие/човек → похвати → обща оценка най-долу', () => {
  const k = risuvay(zapisZa('stranica_2.txt'));
  const h2 = [...k.querySelectorAll('h2')].map((h) => h.textContent);
  expect(h2).toEqual(['Профил на доверие', 'Колко сме сигурни', 'Открити похвати']);
  expect(k.lastElementChild.className).toBe('obshta');
  expect(k.lastElementChild.textContent).toMatch(/^Обща оценка: \d+\.\d \/ 10 — .+Решение на филтъра: /);
  const t = k.textContent;
  expect(t.indexOf('Увереност:')).toBeLessThan(t.indexOf('Открит похват'));
});

test('седемте оси с „правила“ и 10-те въпроса', () => {
  const k = risuvay(zapisZa('stranica_1.txt'));
  expect(k.querySelectorAll('.os')).toHaveLength(7);
  [...k.querySelectorAll('.os-merki')].forEach((m) => expect(m.textContent).toBe('правила'));
  const vaprosi = k.querySelectorAll('.os[data-os="7"] .vaprosi li');
  expect(vaprosi).toHaveLength(10);
  expect([...vaprosi].filter((li) => li.textContent.includes('не може да се определи без модел'))).toHaveLength(2);
  expect(k.textContent).toContain('Увереност: ниска');
  expect(k.textContent).toMatch(/Покритие с доказателства: \d+ от \d+ твърдения .*— груба мярка/);
  expect(k.textContent).toContain('Гледал човек: не.');
});

test('похватите — с откъса и обяснението', () => {
  const k = risuvay(zapisZa('stranica_2.txt'));
  const p = [...k.querySelectorAll('.pohvat')];
  expect(p.length).toBeGreaterThan(0);
  p.forEach((b) => {
    expect(b.querySelector('.pohvat-ime').textContent).toMatch(/^Открит похват: /);
    expect(b.querySelector('.otkas').textContent).toMatch(/^„.+“$/);
    expect(b.querySelector('.obyasnenie').textContent).toContain('Вижте откъса.');
  });
});

test('предупреждение под прага; модулите се изключват', () => {
  const z2 = zapisZa('stranica_2.txt');
  const prag = z2.rez.profil.obshta_ocenka + 0.1;
  let k = risuvay(z2, { prag: prag, moduli: NASTROYKI.moduli });
  expect(k.querySelector('.vnimanie').textContent).toContain('под прага от ' + prag.toFixed(1));
  k = risuvay(z2, { prag: z2.rez.profil.obshta_ocenka, moduli: NASTROYKI.moduli });
  expect(k.querySelector('.vnimanie')).toBeNull();
  k = risuvay(zapisZa('stranica_2.txt'), { prag: 5.0, moduli: { pohvati: false, vaprosi: false } });
  expect(k.querySelector('.pohvat')).toBeNull();
  expect(k.querySelector('.vaprosi')).toBeNull();
});

test('пълна оценка: „модел“ и разликата с правилата', () => {
  const z = zapisZa('stranica_1.txt', { izvor: 'пълна оценка' });
  z.rez.profil.osi['2'] = Object.assign({}, z.rez.profil.osi['2'], { izmereno_s: 'модел', pravila: 7.5, razlika: 1.5 });
  const k = risuvay(z);
  expect(k.querySelector('.rezhim').textContent).toBe('пълна оценка');
  expect(k.querySelector('.os[data-os="2"] .os-merki').textContent).toBe('модел');
  expect(k.querySelector('.os[data-os="2"]').textContent).toContain('По правилата: 7.5 (разлика 1.5)');
});

test('нищо от страницата не става HTML', () => {
  const z = zapisZa('stranica_2.txt', { zaglavie: '<img src=x onerror="alert(1)">Заглавие' });
  z.rez.pohvati[0].otkas = '<script>alert(1)</script>';
  const k = risuvay(z);
  expect(k.querySelector('img')).toBeNull();
  expect(k.querySelector('script')).toBeNull();
  expect(k.textContent).toContain('<img src=x onerror="alert(1)">Заглавие');
});

test('състояния: празно, работи, грешка', () => {
  expect(risuvay(null).textContent).toContain('Натиснете иконата');
  expect(risuvay({ status: 'raboti' }).textContent).toBe('Анализирам статията…');
  expect(risuvay({ status: 'greshka', greshka: 'Няма текст.' }).querySelector('.greshka').textContent).toBe('Няма текст.');
});

test('чист български и никога „лъжа“ във видимите текстове', () => {
  const zabraneni = /\b(score|flag|sidebar|side panel|panel)\b|лъж|фалшив\w*\s+новин/i;
  const faylove = ['src/panel.html', 'src/options.html', '_locales/bg/messages.json'];
  faylove.forEach((f) => {
    const html = procheti(LNA, f).replace(/<[^>]+>/g, ' ').replace(/"(ime|opisanie|deystvie|message)"/g, '');
    expect([f, zabraneni.test(html.replace(/\b(class|id|href|src|rel|type|for|lang|name|content|charset)=\S+/g, ''))]).toEqual([f, false]);
  });
  for (const s of OCAKVANO.sluchai) {
    const t = risuvay(zapisZa(s.ime)).textContent;
    expect([s.ime, zabraneni.test(t)]).toEqual([s.ime, false]);
  }
});
