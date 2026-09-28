// Страничната лента: рисува профила на доверие в реда от Z7b —
// първо 7-те оси, увереността, покритието и „гледал човек“, после похватите, а общата оценка и решението — най-долу и по-малко.
// Всичко идва като текст (textContent) — нищо от страницата или от сървъра не се вмъква като HTML.
(function (g) {
  'use strict';

  var MERKI = { 'правила': 'правила', 'модел': 'модел' };
  var KLAS_OTG = { 'да': 'da', 'частично': 'chastichno', 'не': 'ne' };

  function el(doc, tag, klas, tekst) {
    var e = doc.createElement(tag);
    if (klas) e.className = klas;
    if (tekst !== undefined && tekst !== null) e.textContent = String(tekst);
    return e;
  }

  function chislo(x) { return typeof x === 'number' ? x.toFixed(1) : '—'; }

  function risuvayOs(doc, n, o, moduli) {
    var box = el(doc, 'section', 'os');
    box.dataset.os = n;
    var glava = el(doc, 'div', 'os-glava');
    glava.appendChild(el(doc, 'span', 'os-ime', n + '. ' + o.ime));
    var merki = el(doc, 'span', 'os-merki' + (o.izmereno_s === 'модел' ? ' model' : ''), MERKI[o.izmereno_s] || o.izmereno_s);
    merki.title = o.izmereno_s === 'модел' ? 'Измерено с модела' : 'Измерено с правила (думи и изрази)';
    glava.appendChild(merki);
    glava.appendChild(el(doc, 'span', 'os-ocenka', chislo(o.ocenka)));
    box.appendChild(glava);
    var leta = el(doc, 'div', 'leta');
    var s = el(doc, 'span');
    s.style.width = Math.max(0, Math.min(100, (o.ocenka || 0) * 10)) + '%';
    leta.appendChild(s);
    box.appendChild(leta);
    box.appendChild(el(doc, 'div', 'os-zashto', o.zashto));
    if (typeof o.razlika === 'number') {
      box.appendChild(el(doc, 'div', 'os-zashto', 'По правилата: ' + chislo(o.pravila) + ' (разлика ' + chislo(o.razlika) + ')'));
    }
    if (o.vaprosi && moduli.vaprosi) {
      var ul = el(doc, 'ul', 'vaprosi');
      o.vaprosi.forEach(function (v) {
        var li = el(doc, 'li');
        li.appendChild(el(doc, 'span', 'vapros', v.vapros));
        li.appendChild(el(doc, 'span', 'otg ' + (KLAS_OTG[v.otgovor] || 'neopr'), v.otgovor));
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }
    return box;
  }

  function narisuvay(doc, kade, zapis, nastroyki) {
    nastroyki = nastroyki || { prag: 5.0, moduli: { pohvati: true, vaprosi: true } };
    var moduli = nastroyki.moduli || {};
    while (kade.firstChild) kade.removeChild(kade.firstChild);

    if (!zapis) {
      kade.appendChild(el(doc, 'p', 'prazno', 'Натиснете иконата на ЛНА върху статия, за да видите профила ѝ на доверие.'));
      return;
    }
    if (zapis.status === 'raboti') { kade.appendChild(el(doc, 'p', 'raboti', 'Анализирам статията…')); return; }
    if (zapis.status === 'greshka') { kade.appendChild(el(doc, 'p', 'greshka', zapis.greshka)); return; }

    var rez = zapis.rez, pr = rez.profil;
    kade.appendChild(el(doc, 'h1', null, zapis.zaglavie || 'Без заглавие'));
    var izv = el(doc, 'div', 'izvor');
    izv.appendChild(el(doc, 'span', 'rezhim', zapis.izvor === 'пълна оценка' ? 'пълна оценка' : 'само правила, в браузъра'));
    izv.appendChild(doc.createTextNode(' ' + (rez.iztochnik && rez.iztochnik.domain ? rez.iztochnik.domain : '')));
    if (zapis.ot_kesha) izv.appendChild(doc.createTextNode(' · от кеша'));
    kade.appendChild(izv);

    if (typeof pr.obshta_ocenka === 'number' && pr.obshta_ocenka < nastroyki.prag) {
      kade.appendChild(el(doc, 'div', 'vnimanie',
        'Внимание: оценката е под прага от ' + nastroyki.prag.toFixed(1) + ', който сте задали. Вижте осите и откъсите по-долу.'));
    }
    if (zapis.belezhka) kade.appendChild(el(doc, 'p', 'belezhka', zapis.belezhka));

    // 1. Седемте оси
    kade.appendChild(el(doc, 'h2', null, 'Профил на доверие'));
    Object.keys(pr.osi).sort(function (a, b) { return Number(a) - Number(b); }).forEach(function (n) {
      kade.appendChild(risuvayOs(doc, n, pr.osi[n], moduli));
    });

    // 2. Увереност, покритие, гледал човек
    kade.appendChild(el(doc, 'h2', null, 'Колко сме сигурни'));
    var u = el(doc, 'div', 'uverenost');
    u.appendChild(doc.createTextNode('Увереност: '));
    u.appendChild(el(doc, 'span', 'nivo ' + pr.uverenost.nivo, pr.uverenost.nivo));
    kade.appendChild(u);
    var pri = el(doc, 'ul', 'prichini');
    (pr.uverenost.prichini || []).forEach(function (p) { pri.appendChild(el(doc, 'li', null, p)); });
    kade.appendChild(pri);
    var pk = pr.pokritie_s_dokazatelstva;
    var dyal = pk.dyal === null || pk.dyal === undefined ? '—' : Math.round(pk.dyal * 100) + '%';
    kade.appendChild(el(doc, 'p', 'pokritie', 'Покритие с доказателства: ' + pk.s_iztochnik + ' от ' + pk.tvardenia +
      ' твърдения имат посочен източник (' + dyal + ')' + (pk.grubo ? ' — груба мярка' : '') + '.'));
    kade.appendChild(el(doc, 'p', 'chovek', 'Гледал човек: ' + pr.chovek + '.'));

    // 3. Похватите с откъсите
    if (moduli.pohvati !== false) {
      kade.appendChild(el(doc, 'h2', null, 'Открити похвати'));
      if (!rez.pohvati.length) kade.appendChild(el(doc, 'p', 'belezhka', 'Не са открити похвати по правилата.'));
      rez.pohvati.forEach(function (p) {
        var b = el(doc, 'div', 'pohvat');
        b.appendChild(el(doc, 'div', 'pohvat-ime', 'Открит похват: ' + p.ime));
        b.appendChild(el(doc, 'blockquote', 'otkas', '„' + p.otkas + '“'));
        b.appendChild(el(doc, 'div', 'obyasnenie', p.obyasnenie + ' Вижте откъса.'));
        kade.appendChild(b);
      });
      if (rez.neprovereni_pohvati && rez.neprovereni_pohvati.length) {
        kade.appendChild(el(doc, 'p', 'belezhka', 'Без модел не се проверяват: ' + rez.neprovereni_pohvati.length +
          ' похвата, които изискват разбиране на смисъла (напр. сламен човек, избирателни данни).'));
      }
    }
    (rez.belezhki || []).forEach(function (b) { kade.appendChild(el(doc, 'p', 'belezhka', b)); });

    // 4. Общата оценка и решението — последни и по-малки
    var obshta = el(doc, 'div', 'obshta');
    obshta.appendChild(doc.createTextNode('Обща оценка: '));
    obshta.appendChild(el(doc, 'b', null, chislo(pr.obshta_ocenka) + ' / 10 — ' + pr.po_dumi));
    if (rez.reshenie) {
      obshta.appendChild(el(doc, 'br'));
      obshta.appendChild(doc.createTextNode('Решение на филтъра: ' + rez.reshenie.ime));
    }
    kade.appendChild(obshta);
  }

  function start(chrome, doc) {
    var kade = doc.getElementById('lenta');
    var tabId = null, nastroyki = null;
    function prochetiIRisuvay() {
      if (tabId === null) return;
      Promise.all([chrome.storage.session.get('tab_' + tabId), chrome.storage.local.get('nastroyki')]).then(function (r) {
        var n = r[1].nastroyki || {};
        nastroyki = { prag: typeof n.prag === 'number' ? n.prag : 5.0,
          moduli: Object.assign({ pohvati: true, vaprosi: true, istoriya: true }, n.moduli || {}) };
        narisuvay(doc, kade, r[0]['tab_' + tabId], nastroyki);
      });
    }
    function tekushtRazdel() {
      chrome.tabs.query({ active: true, currentWindow: true }).then(function (t) {
        tabId = t[0] ? t[0].id : null;
        prochetiIRisuvay();
      });
    }
    chrome.storage.onChanged.addListener(function () { prochetiIRisuvay(); });
    chrome.tabs.onActivated.addListener(tekushtRazdel);
    doc.getElementById('otnovo').addEventListener('click', function () {
      if (tabId !== null) chrome.runtime.sendMessage({ vid: 'analiziray', tabId: tabId });
    });
    tekushtRazdel();
  }

  var API = { narisuvay: narisuvay, start: start };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  else {
    g.LNA_PANEL = API;
    if (typeof chrome !== 'undefined' && chrome.storage && g.document) start(chrome, g.document);
  }
})(typeof window !== 'undefined' ? window : this);
