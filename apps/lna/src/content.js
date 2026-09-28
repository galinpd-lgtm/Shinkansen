// Вкарва се в страницата само след натискане на иконата (activeTab). Не праща нищо никъде:
// връща заглавието и текста на статията на фоновия скрипт и спира.
// Ред на търсене: <article> (най-текстовият) → <main> → най-големият блок с <p>.
(function (g) {
  'use strict';

  var SHUM = 'script,style,noscript,template,nav,aside,footer,form,iframe,button,select,svg,figure,' +
    '[role="navigation"],[role="complementary"],[role="banner"],[role="contentinfo"],[aria-hidden="true"],[hidden]';
  var BLOKOVE = 'h1,h2,h3,h4,p,li,blockquote,pre';
  var MIN_ZNACI = 40; // по-кратки блокове в „най-големия блок“ не се броят

  function chist(t) { return (t || '').replace(/\s+/g, ' ').trim(); }

  function tekstNaP(el) {
    var n = 0;
    el.querySelectorAll('p').forEach(function (p) { n += chist(p.textContent).length; });
    return n;
  }

  function naySilen(elementi) {
    var nay = null, max = 0;
    elementi.forEach(function (el) {
      var n = tekstNaP(el);
      if (n > max) { max = n; nay = el; }
    });
    return nay;
  }

  function nameriKoren(doc) {
    var articles = Array.from(doc.querySelectorAll('article'));
    var a = naySilen(articles);
    if (a && tekstNaP(a) >= MIN_ZNACI) return a;
    var main = doc.querySelector('main, [role="main"]');
    if (main && tekstNaP(main) >= MIN_ZNACI) return main;
    // най-големият блок: родителят с най-много текст в преките си <p>
    var roditeli = new Map();
    doc.querySelectorAll('p').forEach(function (p) {
      if (p.closest(SHUM)) return;
      var r = p.parentElement;
      var n = chist(p.textContent).length;
      if (r && n >= MIN_ZNACI) roditeli.set(r, (roditeli.get(r) || 0) + n);
    });
    var nay = null, max = 0;
    roditeli.forEach(function (n, r) { if (n > max) { max = n; nay = r; } });
    return nay || doc.body;
  }

  function izvlechi(doc) {
    var koren = nameriKoren(doc);
    var kopie = koren.cloneNode(true);
    kopie.querySelectorAll(SHUM).forEach(function (el) { el.remove(); });
    // коментарите и „още по темата“ не са част от статията
    kopie.querySelectorAll('.komentari, .comments, #comments, .related, .reklama, .ad, [data-reklama]')
      .forEach(function (el) { el.remove(); });

    var h1 = koren.querySelector('h1') || doc.querySelector('h1');
    var zaglavie = chist(h1 ? h1.textContent : doc.title);
    var chasti = [];
    kopie.querySelectorAll(BLOKOVE).forEach(function (el) {
      if (el.querySelector(BLOKOVE)) return; // само най-вътрешните блокове — без повторения
      var t = chist(el.textContent);
      if (t && t !== zaglavie) chasti.push(t);
    });
    if (!chasti.length) {
      var ves = chist(kopie.textContent);
      if (ves) chasti.push(ves);
    }
    var tekst = (zaglavie ? zaglavie + '\n\n' : '') + chasti.join('\n\n');
    return {
      zaglavie: zaglavie,
      tekst: tekst,
      url: (doc.location && doc.location.href) || '',
      znaci: tekst.length
    };
  }

  var API = { izvlechi: izvlechi, nameriKoren: nameriKoren };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = API;
  } else {
    g.LNA_IZVLECHI = API;
  }
})(typeof window !== 'undefined' ? window : this);

// Стойността на последния израз е резултатът на chrome.scripting.executeScript.
(typeof module !== 'undefined' && module.exports) ? undefined : window.LNA_IZVLECHI.izvlechi(document);
