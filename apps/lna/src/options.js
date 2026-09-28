// Настройките: адрес за пълна оценка (празно = само правила), праг, модули, история.
// При адрес Chrome пита потребителя за достъп само до този адрес (optional_host_permissions) — нищо предварително.
(function (g) {
  'use strict';
  var L = (typeof module !== 'undefined' && module.exports) ? require('./logika.js') : g.LOGIKA;

  function zapazi(chrome, stoynosti) {
    // → Promise<съобщение>; грешка → Error с текст на български
    var adres = (stoynosti.adres || '').trim();
    var prag = Number(stoynosti.prag);
    if (!(prag >= 0 && prag <= 10)) return Promise.reject(new Error('Прагът е число от 0 до 10.'));
    var nastroyki = { adres: '', prag: prag, moduli: stoynosti.moduli };
    var razreshenie = Promise.resolve(true);
    if (adres) {
      var norm;
      try { norm = L.proveriAdres(adres); } catch (e) { return Promise.reject(e); }
      nastroyki.adres = norm;
      razreshenie = chrome.permissions.request({ origins: [new URL(norm).origin + '/*'] });
    }
    return razreshenie.then(function (ok) {
      if (!ok) throw new Error('Без разрешение за този адрес пълната оценка не може да работи. Нищо не е записано.');
      return chrome.storage.local.set({ nastroyki: nastroyki });
    }).then(function () {
      return adres ? 'Записано. При натискане на иконата текстът на статията ще се праща към ' + nastroyki.adres + '.'
        : 'Записано. Без адрес — само правилата в браузъра, нищо не напуска браузъра.';
    });
  }

  function start(chrome, doc) {
    var $ = function (id) { return doc.getElementById(id); };
    function pokazhiIstoriyata() {
      chrome.storage.local.get('istoriya').then(function (d) {
        var ol = $('istoriya');
        while (ol.firstChild) ol.removeChild(ol.firstChild);
        var ist = d.istoriya || [];
        if (!ist.length) { var p = doc.createElement('li'); p.textContent = 'Няма запазени анализи.'; ol.appendChild(p); }
        ist.slice(0, 20).forEach(function (r) {
          var li = doc.createElement('li');
          li.textContent = new Date(r.vreme).toLocaleString('bg-BG') + ' — ' + (r.zaglavie || r.url) + ' · ' +
            (typeof r.obshta === 'number' ? r.obshta.toFixed(1) : '—') + ' (' + r.po_dumi + '), увереност: ' + r.uverenost;
          ol.appendChild(li);
        });
      });
    }
    L.nastroyki(chrome).then(function (n) {
      $('adres').value = n.adres;
      $('prag').value = n.prag;
      $('m-pohvati').checked = n.moduli.pohvati;
      $('m-vaprosi').checked = n.moduli.vaprosi;
      $('m-istoriya').checked = n.moduli.istoriya;
    });
    $('primer').addEventListener('click', function () { $('adres').value = 'http://127.0.0.1:8765'; });
    $('zapazi').addEventListener('click', function () {
      var s = $('sastoyanie');
      zapazi(chrome, {
        adres: $('adres').value, prag: $('prag').value,
        moduli: { pohvati: $('m-pohvati').checked, vaprosi: $('m-vaprosi').checked, istoriya: $('m-istoriya').checked }
      }).then(function (t) { s.className = 'sastoyanie'; s.textContent = t; },
        function (e) { s.className = 'sastoyanie greshka'; s.textContent = e.message; });
    });
    $('iztriy').addEventListener('click', function () {
      L.iztriyIstoriyata(chrome).then(pokazhiIstoriyata).then(function () {
        $('sastoyanie').className = 'sastoyanie';
        $('sastoyanie').textContent = 'Историята и кешът са изтрити.';
      });
    });
    pokazhiIstoriyata();
  }

  var API = { zapazi: zapazi, start: start };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  else if (typeof chrome !== 'undefined' && chrome.storage && g.document) start(chrome, g.document);
})(typeof window !== 'undefined' ? window : this);
