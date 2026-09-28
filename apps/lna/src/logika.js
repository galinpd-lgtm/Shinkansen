// Логиката на фоновия скрипт — отделно от chrome.* събитията, за да се изпитва с подменени chrome и fetch.
//
// Поверителност:
//  - анализът тръгва само при натискане на иконата (или на „Анализирай отново“ в лентата);
//  - без адрес за пълна оценка нищо не напуска браузъра — единственото мрежово викане е в palnaOcenka;
//  - с адрес се праща само текстът на текущата статия и адресът ѝ, само към този адрес;
//  - историята и настройките стоят в chrome.storage.local, кешът на резултатите — там, до 1 час.
(function (g) {
  'use strict';
  var D = (typeof module !== 'undefined' && module.exports) ? require('./dvigatel.js') : g.DVIGATEL;

  var PO_PODRAZBIRANE = {
    adres: '',            // празно = само правилата в браузъра
    prag: 5.0,            // под него лентата показва предупреждение
    moduli: { pohvati: true, vaprosi: true, istoriya: true }
  };
  var KESH_MS = 60 * 60 * 1000;
  var MAKS_ISTORIYA = 100;
  var MAKS_KESH = 100;
  var TAYMAUT_MS = 120 * 1000;

  function nastroyki(chrome) {
    return chrome.storage.local.get('nastroyki').then(function (d) {
      var n = d.nastroyki || {};
      return {
        adres: typeof n.adres === 'string' ? n.adres.trim() : PO_PODRAZBIRANE.adres,
        prag: typeof n.prag === 'number' ? n.prag : PO_PODRAZBIRANE.prag,
        moduli: Object.assign({}, PO_PODRAZBIRANE.moduli, n.moduli || {})
      };
    });
  }

  function proveriAdres(adres) {
    // → нормализиран адрес без наклонена черта накрая, или грешка на български
    var u;
    try { u = new URL(adres); } catch (e) { throw new Error('Адресът не е валиден. Пример: http://127.0.0.1:8765'); }
    if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new Error('Адресът трябва да започва с http:// или https://');
    if (u.search || u.hash) throw new Error('Адресът е само сървърът, без „?“ и „#“.');
    return u.origin + u.pathname.replace(/\/+$/, '');
  }

  function stranicaStava(url) { return /^https?:\/\//i.test(url || ''); }

  // Единственото място с мрежа. Вика се само ако потребителят е въвел адрес.
  function palnaOcenka(adres, tekst, url, fetchFn) {
    var kontrol = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var t = kontrol ? setTimeout(function () { kontrol.abort(); }, TAYMAUT_MS) : null;
    return fetchFn(proveriAdres(adres) + '/ocenka', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tekst: tekst, iztochnik: url }),
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
      signal: kontrol ? kontrol.signal : undefined
    }).then(function (r) {
      if (r.status === 503) throw new Error('машината е заета — опитайте по-късно');
      if (!r.ok) throw new Error('пълната оценка върна код ' + r.status);
      return r.json();
    }).then(function (rez) {
      if (!rez || !rez.profil || !rez.profil.osi) throw new Error('отговорът не е профил на доверие (нужен е Z7 0.2+)');
      rez.izmereno_v = 'пълна оценка';
      return rez;
    }).finally(function () { if (t) clearTimeout(t); });
  }

  function klyuchKesh(url, adres) { return (adres || 'правила') + ' ' + url; }

  function otKesha(chrome, klyuch, sega) {
    return chrome.storage.local.get('kesh').then(function (d) {
      var z = (d.kesh || {})[klyuch];
      return z && sega - z.vreme < KESH_MS ? z : null;
    });
  }

  function vKesha(chrome, klyuch, zapis, sega) {
    return chrome.storage.local.get('kesh').then(function (d) {
      var kesh = d.kesh || {};
      kesh[klyuch] = zapis;
      var klyuchove = Object.keys(kesh).filter(function (k) { return sega - kesh[k].vreme < KESH_MS; })
        .sort(function (a, b) { return kesh[b].vreme - kesh[a].vreme; }).slice(0, MAKS_KESH);
      var nov = {};
      klyuchove.forEach(function (k) { nov[k] = kesh[k]; });
      return chrome.storage.local.set({ kesh: nov });
    });
  }

  function vIstoriyata(chrome, zapis) {
    // само кратко обобщение — без текста на статията
    var red = {
      vreme: zapis.vreme, url: zapis.url, zaglavie: zapis.zaglavie, izvor: zapis.izvor,
      obshta: zapis.rez.profil.obshta_ocenka, po_dumi: zapis.rez.profil.po_dumi,
      uverenost: zapis.rez.profil.uverenost.nivo, reshenie: zapis.rez.reshenie && zapis.rez.reshenie.ime
    };
    return chrome.storage.local.get('istoriya').then(function (d) {
      var ist = [red].concat(d.istoriya || []).slice(0, MAKS_ISTORIYA);
      return chrome.storage.local.set({ istoriya: ist });
    });
  }

  function pokazhi(chrome, tabId, zapis) {
    var o = {};
    o['tab_' + tabId] = zapis;
    return chrome.storage.session.set(o);
  }

  // Главният ход: извличане → (кеш) → правила или пълна оценка → лентата, кешът и историята.
  function analiziray(o) {
    var chrome = o.chrome, tab = o.tab, fetchFn = o.fetchFn, sega = o.sega || Date.now();
    if (!tab || !stranicaStava(tab.url)) {
      return pokazhi(chrome, tab && tab.id, { status: 'greshka', vreme: sega,
        greshka: 'Тази страница не може да се анализира — само статии на http:// или https://.' });
    }
    var n, zapis;
    return pokazhi(chrome, tab.id, { status: 'raboti', vreme: sega, url: tab.url })
      .then(function () { return nastroyki(chrome); })
      .then(function (nn) {
        n = nn;
        return o.bezKesh ? null : otKesha(chrome, klyuchKesh(tab.url, n.adres), sega);
      })
      .then(function (ot) {
        if (ot) return Object.assign({}, ot, { ot_kesha: true });
        return chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['src/content.js'] })
          .then(function (rezultati) {
            var st = rezultati && rezultati[0] && rezultati[0].result;
            if (!st || !st.tekst || st.tekst.length < 80) {
              throw new Error('На тази страница не намерих текст на статия.');
            }
            var t0 = Date.now();
            var lokalen = D.ocenka(st.tekst, tab.url);
            var mestno = { status: 'gotovo', vreme: sega, url: tab.url, zaglavie: st.zaglavie,
              izvor: 'правила', rez: lokalen, ms: Date.now() - t0 };
            if (!n.adres) return mestno;
            return palnaOcenka(n.adres, st.tekst, tab.url, fetchFn).then(function (palna) {
              return { status: 'gotovo', vreme: sega, url: tab.url, zaglavie: st.zaglavie, izvor: 'пълна оценка', rez: palna };
            }, function (e) {
              mestno.belezhka = 'Пълната оценка не отговори (' + e.message + ') — показана е оценката само с правилата.';
              return mestno;
            });
          })
          .then(function (z) {
            return vKesha(chrome, klyuchKesh(tab.url, n.adres), z, sega).then(function () { return z; });
          });
      })
      .then(function (z) {
        zapis = z;
        return n.moduli.istoriya && !z.ot_kesha ? vIstoriyata(chrome, z) : null;
      })
      .then(function () { return pokazhi(chrome, tab.id, zapis); })
      .catch(function (e) {
        return pokazhi(chrome, tab.id, { status: 'greshka', vreme: sega, url: tab.url, greshka: e.message });
      });
  }

  function iztriyIstoriyata(chrome) { return chrome.storage.local.remove(['istoriya', 'kesh']); }

  var API = {
    PO_PODRAZBIRANE: PO_PODRAZBIRANE, KESH_MS: KESH_MS, MAKS_ISTORIYA: MAKS_ISTORIYA,
    nastroyki: nastroyki, proveriAdres: proveriAdres, palnaOcenka: palnaOcenka,
    analiziray: analiziray, iztriyIstoriyata: iztriyIstoriyata
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API; else g.LOGIKA = API;
})(typeof self !== 'undefined' ? self : this);
