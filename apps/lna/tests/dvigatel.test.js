// Двигателят в браузъра дава същото като `python -m doverie ocenka --bez-model` — за всеки примерен текст.
const D = require('../src/dvigatel.js');
const P = require('../src/pravila.js');
const { OCAKVANO } = require('./pomoshtni');

describe('същото като apps/doverie', () => {
  test.each(OCAKVANO.sluchai.map((s) => [s.ime, s]))('%s', (_ime, s) => {
    const r = D.ocenka(s.tekst, null);
    expect(r.profil).toEqual(s.profil);
    expect(r.pohvati).toEqual(s.pohvati);
    expect(r.neprovereni_pohvati).toEqual(s.neprovereni_pohvati);
    expect(r.reshenie).toEqual(s.reshenie);
    expect(r.belezhki).toEqual(s.belezhki);
  });

  test.each(OCAKVANO.sluchai.map((s) => [s.ime, s]))('всеки израз хваща същото: %s', (_ime, s) => {
    const t = D.normalizirai(s.tekst);
    for (const [k, spans] of Object.entries(s.savpadeniya)) {
      const [src, fl] = P.izrazi[k];
      const js = [...t.matchAll(new RegExp(src, fl + 'g'))].map((m) => [m.index, m.index + m[0].length]);
      expect([k, js]).toEqual([k, spans]);
    }
  });
});

describe('профилът', () => {
  const s = OCAKVANO.sluchai.find((x) => x.ime === 'stranica_1.txt');
  const r = D.ocenka(s.tekst, 'https://www.example.org/novini/1');

  test('първо профилът, общата оценка е последна в него', () => {
    expect(Object.keys(r)[0]).toBe('profil');
    expect(Object.keys(r.profil)).toEqual(['osi', 'uverenost', 'pokritie_s_dokazatelstva', 'chovek', 'obshta_ocenka', 'po_dumi']);
  });
  test('7 оси, всички „правила“, ниска увереност', () => {
    expect(Object.keys(r.profil.osi)).toEqual(['1', '2', '3', '4', '5', '6', '7']);
    Object.values(r.profil.osi).forEach((o) => expect(o.izmereno_s).toBe('правила'));
    expect(r.profil.uverenost.nivo).toBe('ниска');
    expect(r.profil.chovek).toBe('не');
  });
  test('двата въпроса за пълнота не се гадаят', () => {
    const neopr = r.profil.osi['7'].vaprosi.filter((v) => v.otgovor === 'не може да се определи без модел');
    expect(neopr.map((v) => v.kluch)).toEqual(['drugata_strana', 'znachenie']);
  });
  test('източникът е домейнът на страницата', () => {
    expect(r.iztochnik.domain).toBe('example.org');
    expect(r.profil.osi['1'].zashto).toContain('Примерен вестник');
  });
});

describe('числата като в Python', () => {
  test.each([[0.125, 2, '0.12'], [0.375, 2, '0.38'], [2.5, 0, '2'], [3.5, 0, '4'], [5.25, 1, '5.2'], [5.35, 1, '5.3'], [1.005, 2, '1.00']])(
    'pyFixed(%p, %p) = %p', (x, n, oc) => expect(D.pyFixed(x, n)).toBe(oc));
  test('okragli е половинка нагоре върху десетичния запис', () => {
    expect(D.okragli(6.25)).toBe(6.3);
    expect(D.okragli(6.35)).toBe(6.4);
    expect(D.okragli(7.5)).toBe(7.5);
  });
  test('претеглената сума е точна (8.45 → 8.5)', () => {
    expect(D.krayna([{ teglo: 0.5, ocenka: 8.1 }, { teglo: 0.5, ocenka: 8.8 }])).toBe(8.5);
  });
});

test('под 1 секунда само с правилата', () => {
  for (const s of OCAKVANO.sluchai) {
    const t0 = performance.now();
    D.ocenka(s.tekst, null);
    expect(performance.now() - t0).toBeLessThan(1000);
  }
});
