/** @jest-environment jsdom */
// Извличане от 5 измислени страници: <article>, <main>, без семантика, няколко <article>, реклама вътре в статията.
const path = require('path');
const { FIX, OCAKVANO, procheti } = require('./pomoshtni');
const { izvlechi } = require('../src/content.js');
const D = require('../src/dvigatel.js');

const SHUM = ['Реклама', 'Коментари', 'Читател', 'проследяване', 'Меню', 'Начало', 'Спонсорирано', 'Снимка:',
  'Всички права запазени', 'Най-четени', 'Условия за ползване', 'Друга новина'];
const norm = (t) => t.replace(/\s+/g, ' ').trim();

function zaredi(n) {
  document.documentElement.innerHTML = procheti(FIX, 'stranici', `stranica_${n}.html`)
    .replace(/^<!doctype html>\s*/i, '').replace(/^<html[^>]*>/i, '').replace(/<\/html>\s*$/i, '');
  return izvlechi(document);
}

describe.each([1, 2, 3, 4, 5])('страница %i', (n) => {
  const tekst = procheti(FIX, 'tekstove', `stranica_${n}.txt`);
  test('текстът на статията — целият и само той', () => {
    const r = zaredi(n);
    expect(norm(r.tekst)).toBe(norm(tekst));
    SHUM.forEach((s) => expect(r.tekst).not.toContain(s));
    expect(r.zaglavie).toBe(tekst.split('\n')[0]);
  });
  test('двигателят върху извлеченото дава похватите на doverie', () => {
    const r = zaredi(n);
    const s = OCAKVANO.sluchai.find((x) => x.ime === `stranica_${n}.txt`);
    const kl = (xs) => xs.map((p) => [p.kluch, p.otkas]);
    expect(kl(D.ocenka(r.tekst, null).pohvati)).toEqual(kl(s.pohvati));
  });
});

test('страница без статия дава малко текст — лентата ще каже, че няма какво да анализира', () => {
  document.body.innerHTML = '<nav><a>Начало</a></nav><div><span>Здравейте</span></div>';
  expect(izvlechi(document).tekst.length).toBeLessThan(80);
});
