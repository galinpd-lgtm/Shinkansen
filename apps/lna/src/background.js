// Фоновият скрипт (service worker). Само свързва събитията на Chrome с логиката в logika.js.
importScripts('pravila.js', 'dvigatel.js', 'logika.js');

function mreza() { return fetch.apply(self, arguments); }

// Натискане на иконата: отваря лентата и анализира текущия раздел. Нищо не се пуска само.
chrome.action.onClicked.addListener(function (tab) {
  chrome.sidePanel.open({ tabId: tab.id }).catch(function () {});
  LOGIKA.analiziray({ tab: tab, chrome: chrome, fetchFn: mreza });
});

chrome.runtime.onMessage.addListener(function (s, _izprashtach, otgovor) {
  if (s && s.vid === 'analiziray' && typeof s.tabId === 'number') {
    chrome.tabs.get(s.tabId).then(function (tab) {
      return LOGIKA.analiziray({ tab: tab, chrome: chrome, fetchFn: mreza, bezKesh: true });
    }).then(function () { otgovor({ ok: true }); }, function (e) { otgovor({ ok: false, greshka: e.message }); });
    return true;
  }
  if (s && s.vid === 'iztriy_istoriyata') {
    LOGIKA.iztriyIstoriyata(chrome).then(function () { otgovor({ ok: true }); });
    return true;
  }
  return false;
});
