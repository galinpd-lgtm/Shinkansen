// Двигателят на ЛНА: профилът на доверие само с правилата — същото като `python -m doverie ocenka --bez-model`.
// Логиката повтаря apps/doverie ред по ред; изразите, праговете и таблиците идват от pravila.js (генериран).
// Тест (dvigatel.test.js) сравнява резултата с изхода на самия doverie за всички примерни текстове.
(function (g) {
  'use strict';
  var P = (typeof module !== 'undefined' && module.exports) ? require('./pravila.js') : g.PRAVILA;

  // ─────────── изразите ───────────
  function kompiliray(par) { return { s: new RegExp(par[0], par[1]), g: new RegExp(par[0], par[1] + 'g') }; }
  var R = {};
  Object.keys(P.izrazi).forEach(function (k) { R[k] = kompiliray(P.izrazi[k]); });
  var DILEMA = P.spisaci.DILEMA.map(kompiliray);
  var ANONIMEN = P.spisaci.ANONIMEN.map(kompiliray);
  var CIFRA = /\p{Nd}/u;

  function vsichki(re, t) { re.g.lastIndex = 0; return Array.from(t.matchAll(re.g)); }
  function ima(re, t) { return re.s.test(t); }

  // ─────────── числа като в Python ───────────
  // Python закръгля точната двоична стойност с „половинка към четно“; toFixed в JS — „половинка нагоре“.
  function pyFixed(x, n) {
    var s = Math.abs(x).toFixed(n + 40);
    var tochka = s.indexOf('.');
    var opashka = s.slice(tochka + 1 + n);
    if (/^50*$/.test(opashka)) { // точно равенство — към четно
      var glava = s.slice(0, tochka + 1 + n);
      var cifri = glava.replace('.', '');
      var posledna = parseInt(cifri[cifri.length - 1], 10);
      var r = posledna % 2 === 0 ? glava : Math.abs(x).toFixed(n); // toFixed при равенство взима по-голямото
      if (n === 0) r = r.replace(/\.$/, '');
      return (x < 0 && Number(r) !== 0 ? '-' : '') + r;
    }
    return (x < 0 && Number(Math.abs(x).toFixed(n)) !== 0 ? '-' : '') + Math.abs(x).toFixed(n);
  }
  function pyRound(x, n) { return Number(pyFixed(x, n)); }

  // Десетично число като BigInt с мащаб — за Decimal(str(x)) от doverie.
  function desetichno(x) {
    var s = String(x);
    if (/e/i.test(s)) s = x.toFixed(20).replace(/0+$/, '');
    var neg = s[0] === '-'; if (neg) s = s.slice(1);
    var ch = s.split('.'); var drob = ch[1] || '';
    return { m: BigInt((neg ? '-' : '') + ch[0] + drob), e: drob.length };
  }
  function kamMashtab(d, e) { return d.m * (10n ** BigInt(e - d.e)); }
  function zakragli1(m, e) { // m / 10^e → 1 знак, половинката нагоре (ROUND_HALF_UP, от нулата)
    var neg = m < 0n; if (neg) m = -m;
    var del = 10n ** BigInt(e - 1);
    var q = m / del, ost = m % del;
    if (ost * 2n >= del) q += 1n;
    var r = Number(q) / 10;
    return neg ? -r : r;
  }
  function okragli(x) { var d = desetichno(x); if (d.e <= 1) return Number(x); return zakragli1(d.m, d.e); }
  function ogranichi(x) { return Math.max(0, Math.min(10, x)); }

  // ─────────── текст ───────────
  function normalizirai(t) { return (t || '').replace(/\s+/gu, ' ').trim(); }
  function izrecheniya(t) {
    return vsichki(R.IZR, normalizirai(t)).map(function (m) { return m[0].trim(); }).filter(Boolean);
  }
  function dumi(t) { return vsichki(R.DUMA, (t || '').toLowerCase()).map(function (m) { return m[0]; }); }
  function izrechenieOkolo(t, poz) {
    var nachalo = Math.max.apply(null, ['.', '!', '?', '…'].map(function (z) {
      return poz === 0 ? -1 : t.lastIndexOf(z, poz - 1);
    })) + 1;
    var kraishta = ['.', '!', '?', '…'].map(function (z) { return t.indexOf(z, poz); })
      .filter(function (i) { return i !== -1; });
    var kraj = kraishta.length ? Math.min.apply(null, kraishta) + 1 : t.length;
    return t.slice(nachalo, kraj).trim();
  }
  function dumiNaIzrechenie(s) { var t = s.trim(); return t ? t.split(/\s+/u) : []; }
  function kapitalizirai(s) { return s ? s[0].toUpperCase() + s.slice(1).toLowerCase() : s; }

  // ─────────── похватите по правила ───────────
  function zapis(kluch, otkas, obyasnenie, veroyatnost) {
    var p = P.pohvati[kluch];
    var z = { kluch: kluch, ime: p.ime, nakazanie: p.nakazanie, otkas: otkas, obyasnenie: obyasnenie };
    if (veroyatnost !== undefined) z.veroyatnost = veroyatnost;
    return z;
  }

  // „не всички“, „няма опасност“ … — като pohvati.otricano в doverie
  function otricano(t, nachalo, kraj, sled) {
    var izr = Math.max.apply(null, ['.', '!', '?', '…'].map(function (z) {
      return nachalo === 0 ? -1 : t.lastIndexOf(z, nachalo - 1);
    })) + 1;
    var chasti = t.slice(izr, nachalo).replace(R.VYARNO_CHE.g, 'вярно че').split(R.PREKASVA.g);
    if (ima(R.OTRICANIE_PREDI, chasti[chasti.length - 1])) return true;
    if (!sled || kraj === undefined) return false;
    var m = t.slice(kraj, kraj + 20).match(R.OTRICANIE_SLED.s);
    return !!(m && m.index === 0);
  }

  // Първото неотречено съвпадение — по реда на шаблоните.
  function parvo(t, sabl) {
    for (var i = 0; i < sabl.length; i++) {
      var sp = vsichki(sabl[i], t);
      for (var j = 0; j < sp.length; j++) if (!otricano(t, sp[j].index)) return sp[j];
    }
    return null;
  }

  function aiVeroyatnost(t) {
    var izr = izrecheniya(t);
    if (izr.length < 6) return 0.0;
    var dalj = izr.map(function (s) { return dumiNaIzrechenie(s).length; });
    var n = dalj.length, suma = 0, kv = 0;
    dalj.forEach(function (x) { suma += x; kv += x * x; });
    var sr = suma / n;
    var dispersiya = (n * kv - suma * suma) / (n * n); // точно в цели числа, после деление
    var cv = sr ? Math.sqrt(dispersiya) / sr : 1.0;
    var ednoobrazie = Math.min(1.0, Math.max(0.0, (0.40 - cv) / 0.30));
    var nachala = izr.filter(function (s) { return dumiNaIzrechenie(s).length; })
      .map(function (s) { return dumiNaIzrechenie(s)[0].toLowerCase(); });
    var povtoreni = nachala.filter(function (x) {
      return nachala.filter(function (y) { return y === x; }).length > 1;
    }).length / nachala.length;
    return pyRound(0.7 * ednoobrazie + 0.3 * povtoreni, 2);
  }

  function poPravila(tekst) {
    var t = normalizirai(tekst), nam = [];
    var strah = vsichki(R.STRAH, t).filter(function (m) {
      return !otricano(t, m.index, m.index + m[0].length, true);
    });
    if (strah.length >= 2) {
      nam.push(zapis('appeal_to_fear', izrechenieOkolo(t, strah[0].index),
        'Текстът натрупва думи за опасност и заплаха (' + strah.length + ' пъти).'));
    }
    var m = parvo(t, DILEMA);
    if (m) {
      nam.push(zapis('false_dichotomy', m[0],
        'Представени са само два изхода или един-единствен, без други възможности.'));
    }
    var nameren = false;
    for (var j = 0; j < ANONIMEN.length && !nameren; j++) {
      var sp = vsichki(ANONIMEN[j], t);
      for (var k = 0; k < sp.length; k++) {
        if (!ima(R.CITAT, izrechenieOkolo(t, sp[k].index))) {
          nam.push(zapis('anonymous_authority', sp[k][0],
            'Позоваване на експерти или изследвания, без да е посочено кои.'));
          nameren = true;
          break;
        }
      }
    }
    var mt = parvo(t, [R.TALPA]);
    if (mt) {
      nam.push(zapis('bandwagon', mt[0], 'Твърдението се опира на това, че „всички“ мислят така, а не на данни.'));
    }
    var v = aiVeroyatnost(t);
    if (v >= P.reshenie.ai_flag_ot) {
      nam.push(zapis('ai_generated', izrecheniya(t)[0],
        'Вероятно машинно генериран текст: изреченията са необичайно еднообразни.', v));
    }
    return nam;
  }

  // ─────────── осите ───────────
  function domain(iztochnik) {
    if (!iztochnik) return null;
    var s = String(iztochnik).trim().toLowerCase(), host;
    try { host = new URL(s.indexOf('//') !== -1 ? s : 'http://' + s).hostname; } catch (e) { host = s; }
    return host.indexOf('www.') === 0 ? host.slice(4) : host;
  }

  // В браузъра няма регистър на източниците: ос 1 е неутрална за всички сайтове.
  // Частният регистър се ползва само в пълната оценка от doverie serve на GX10.
  function reputaciya() {
    return [P.reputaciya_v_brauzara.ocenka, P.reputaciya_v_brauzara.zashto];
  }

  function tvardeniya(tekst) {
    var tv = izrecheniya(tekst).filter(function (s) { return ima(R.TVARDENIE, s); });
    return [tv.length, tv.filter(function (s) { return ima(R.IZTOCHNIK, s); }).length];
  }

  function proverimost(tekst) {
    var r = tvardeniya(tekst), n = r[0], s = r[1];
    if (!n) return [5.0, 'Няма ясни фактически твърдения за проверка.'];
    var oc = 10.0 * s / n;
    if (s === 0) return [oc, 'Липсва посочен източник за нито едно от ' + n + ' твърдения.'];
    return [oc, s + ' от ' + n + ' твърдения имат посочен източник или документ.'];
  }

  function prozrachnost(tekst) {
    var t = normalizirai(tekst);
    var im = vsichki(R.IMENUVAN, t).length, an = vsichki(R.ANONIMEN_OS, t).length;
    if (im + an === 0) return [3.0, 'Не са посочени източници — нито именувани, нито анонимни.'];
    return [10.0 * im / (im + an), 'Именувани източници: ' + im + ', анонимни: ' + an + '.'];
  }

  function originalnost() { return [10.0, 'Няма вече видени текстове за сравнение.']; } // без памет в браузъра

  function obshtestvenInteres(tekst) {
    var t = normalizirai(tekst);
    var razl = function (re) {
      var s = {}; vsichki(re, t).forEach(function (m) { s[m[0].toLowerCase()] = 1; }); return Object.keys(s).length;
    };
    var i = razl(R.INTERES), r = razl(R.REKLAMA);
    var oc = ogranichi(4.0 + 1.0 * i - 2.5 * r);
    if (r) return [oc, 'Текстът има белези на реклама или PR (' + r + ').'];
    if (i) return [oc, 'Засяга хора, пари, права или услуги (' + i + ' различни белега).'];
    return [oc, 'Не личи да засяга хора, пари, права или услуги.'];
  }

  function manipulaciya(pohvati) {
    var suma = pohvati.reduce(function (a, p) { return a + p.nakazanie; }, 0);
    var oc = ogranichi(10.0 - suma);
    if (!pohvati.length) return [oc, 'Не са открити манипулативни похвати.'];
    return [oc, 'Открити похвати: ' + pohvati.length + ' (наказание −' + pyFixed(suma, 1) + ').'];
  }

  var O = P.otgovori, TOCHKI = {};
  TOCHKI[O.DA] = 1.0; TOCHKI[O.CHASTICHNO] = 0.5; TOCHKI[O.NE] = 0.0;

  function vaprosiEvristika(t) {
    var im = vsichki(R.IMENUVAN, t).length, an = vsichki(R.ANONIMEN_OS, t).length, nd = dumi(t).length;
    return {
      koy: ima(R.KOY, t) ? O.DA : O.NE,
      kakvo: nd >= 25 ? O.DA : (nd >= 10 ? O.CHASTICHNO : O.NE),
      koga: ima(R.KOGA, t) ? O.DA : O.NE,
      kade: ima(R.KADE, t) ? O.DA : O.NE,
      zashto: ima(R.ZASHTO, t) ? O.DA : O.NE,
      kak: ima(R.KAK, t) ? O.DA : O.NE,
      kolko: CIFRA.test(t) ? (ima(R.SPRYAMO, t) ? O.DA : O.CHASTICHNO) : O.NE,
      koy_kazva: im ? O.DA : (an ? O.CHASTICHNO : O.NE)
      // „чута ли е другата страна“ и „какво значи за читателя“ не се гадаят по думи
    };
  }

  function palnota(tekst) {
    var ev = vaprosiEvristika(normalizirai(tekst));
    var otg = P.palnota_vaprosi.map(function (v) {
      return { kluch: v.kluch, vapros: v.vapros, otgovor: Object.prototype.hasOwnProperty.call(ev, v.kluch) ? ev[v.kluch] : O.NEOPREDELIMO };
    });
    var opr = otg.filter(function (o) { return o.otgovor in TOCHKI; });
    var oc = opr.length ? 10.0 * opr.reduce(function (a, o) { return a + TOCHKI[o.otgovor]; }, 0) / opr.length : 0.0;
    var spisak = function (x) { return otg.filter(function (o) { return o.otgovor === x; }).map(function (o) { return o.vapros; }); };
    var r = [];
    if (spisak(O.NE).length) r.push('липсва: ' + spisak(O.NE).join(', '));
    if (spisak(O.CHASTICHNO).length) r.push('частично: ' + spisak(O.CHASTICHNO).join(', '));
    if (spisak(O.NEOPREDELIMO).length) r.push('не може да се определи без модел: ' + spisak(O.NEOPREDELIMO).join(', '));
    var za = r.length ? kapitalizirai(r.join('; ')) + '.' : 'Отговорени са всички въпроси.';
    return [oc, za, otg];
  }

  // ─────────── сума, решение, увереност ───────────
  function krayna(osi) {
    var chleni = osi.map(function (o) {
      var w = desetichno(o.teglo), s = desetichno(o.ocenka);
      return { m: w.m * s.m, e: w.e + s.e };
    });
    var e = Math.max.apply(null, chleni.map(function (c) { return c.e; }).concat([1]));
    var suma = chleni.reduce(function (a, c) { return a + kamMashtab(c, e); }, 0n);
    return zakragli1(suma, e);
  }

  function poDumi(oc) {
    for (var i = 0; i < P.po_dumi.length; i++) if (oc >= P.po_dumi[i][0]) return P.po_dumi[i][1];
    return P.po_dumi[P.po_dumi.length - 1][1];
  }

  var IMENA_RESHENIE = { PROPUSNI: 'ПРОПУСНИ', PREDUPREDI: 'ПРЕДУПРЕДИ', KARANTINA: 'КАРАНТИНА' };

  function reshi(kr, pohvati, osi) {
    var r = P.reshenie;
    var prozr = osi.filter(function (o) { return o.kluch === 'prozrachnost'; })[0];
    prozr = prozr ? prozr.ocenka : 10.0;
    var ai = pohvati.filter(function (p) { return p.kluch === 'ai_generated'; })
      .reduce(function (a, p) { return Math.max(a, p.veroyatnost || 0); }, 0.0);
    var anon = pohvati.some(function (p) { return p.kluch === 'anonymous_authority'; });
    var prichini = [], kod;
    if (kr < r.karantina_pod) prichini.push('оценката ' + pyFixed(kr, 1) + ' е под ' + pyFixed(r.karantina_pod, 1));
    if (ai >= r.ai_karantina_ot) prichini.push('вероятно машинно генериран текст (' + pyFixed(ai, 2) + ')');
    if (anon && prozr <= r.bez_iztochnici_do) prichini.push('критичен флаг: анонимен авторитет и липсват посочени източници');
    if (prichini.length) kod = 'KARANTINA';
    else if (kr >= r.propusni_ot && !pohvati.length) {
      kod = 'PROPUSNI';
      prichini.push('оценка ' + pyFixed(kr, 1) + ' и няма открити похвати');
    } else {
      kod = 'PREDUPREDI';
      if (kr < r.propusni_ot) {
        prichini.push('оценката ' + pyFixed(kr, 1) + ' е между ' + pyFixed(r.karantina_pod, 1) + ' и ' + pyFixed(r.propusni_ot, 1));
      }
      if (pohvati.length) prichini.push('открити похвати: ' + pohvati.length);
    }
    return { kod: kod, ime: IMENA_RESHENIE[kod], prichini: prichini };
  }

  function uverenost(nDumi, pokritie, neopredelimi) {
    // без модел увереността е винаги ниска (т. 3 от Z7b) — тук е само клонът „ниска“
    var u = P.uverenost, niski = ['без модел — само правила и евристики'];
    if (nDumi < u.niska_pod_dumi) niski.push('текстът е под ' + u.niska_pod_dumi + ' думи (' + nDumi + ')');
    if (pokritie.tvardenia < u.niska_pod_tvardeniya) {
      niski.push('под ' + u.niska_pod_tvardeniya + ' твърдения (' + pokritie.tvardenia + ')');
    }
    if (neopredelimi) niski.push(neopredelimi + ' от въпросите за пълнота не могат да се определят без модел');
    return { nivo: 'ниска', prichini: niski };
  }

  // ─────────── главният вход ───────────
  function ocenka(tekst, iztochnik) {
    tekst = tekst || '';
    var namereni = poPravila(tekst);
    namereni.sort(function (a, b) { return P.red_pohvati.indexOf(a.kluch) - P.red_pohvati.indexOf(b.kluch); });
    var belezhki = [];

    var sme = {};
    sme.reputaciya = reputaciya();
    sme.originalnost = originalnost();
    sme.manipulaciya = manipulaciya(namereni);
    sme.proverimost = proverimost(tekst);
    sme.prozrachnost = prozrachnost(tekst);
    sme.obshtestven_interes = obshtestvenInteres(tekst);
    var p7 = palnota(tekst);
    sme.palnota = [p7[0], p7[1]];
    var vaprosi = p7[2];
    var tv = tvardeniya(tekst);
    var pokritie = { tvardenia: tv[0], s_iztochnik: tv[1], grubo: true,
      kak: 'груба мярка без модел: изречения с число или цитат; с източник — тези с атрибуция' };
    var neopredelimi = vaprosi.filter(function (v) { return v.otgovor === O.NEOPREDELIMO; }).length;
    if (neopredelimi) {
      belezhki.push('Контекстна пълнота: ' + neopredelimi + ' от ' + vaprosi.length + ' въпроса не могат да се определят без модел — ' +
        'оста е смятана от останалите ' + (vaprosi.length - neopredelimi) + ' и мащабирана до 10.');
    }
    pokritie.dyal = pokritie.tvardenia ? pyRound(pokritie.s_iztochnik / pokritie.tvardenia, 2) : null;

    var osi = P.osi.map(function (o) {
      return { kluch: o.kluch, ime: o.ime, teglo: o.teglo, ocenka: okragli(ogranichi(sme[o.kluch][0])), zashto: sme[o.kluch][1] };
    });
    var kr = krayna(osi), pd = poDumi(kr);
    var profilOsi = {};
    osi.forEach(function (o, i) {
      var z = { kluch: o.kluch, ime: o.ime, ocenka: o.ocenka, zashto: o.zashto, izmereno_s: 'правила' };
      if (o.kluch === 'palnota') z.vaprosi = vaprosi;
      profilOsi[String(i + 1)] = z;
    });
    return {
      profil: {
        osi: profilOsi,
        uverenost: uverenost(dumi(tekst).length, pokritie, neopredelimi),
        pokritie_s_dokazatelstva: pokritie,
        chovek: P.chovek[0],
        obshta_ocenka: kr,
        po_dumi: pd
      },
      rezhim: 'bez-model',
      izmereno_v: 'браузъра',
      iztochnik: { domain: domain(iztochnik) },
      pohvati: namereni,
      neprovereni_pohvati: P.samo_model.slice(),
      krayna_ocenka: kr,
      po_dumi: pd,
      reshenie: reshi(kr, namereni, osi),
      belezhki: belezhki
    };
  }

  var API = { ocenka: ocenka, poPravila: poPravila, normalizirai: normalizirai, izrecheniya: izrecheniya,
    pyFixed: pyFixed, okragli: okragli, krayna: krayna, PRAVILA: P };
  if (typeof module !== 'undefined' && module.exports) module.exports = API; else g.DVIGATEL = API;
})(typeof self !== 'undefined' ? self : this);
