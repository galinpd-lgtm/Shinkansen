// Общо за тестовете: пътища, очакваният изход на doverie и подменен chrome.* в паметта.
const fs = require('fs');
const path = require('path');

const LNA = path.resolve(__dirname, '..');
const FIX = path.join(__dirname, 'fixtures');
const OCAKVANO = require('./fixtures/ocakvano.json');

function procheti(...chasti) { return fs.readFileSync(path.join(...chasti), 'utf8'); }

function hranilishte() {
  let d = {};
  return {
    get: async (k) => {
      if (k === undefined || k === null) return JSON.parse(JSON.stringify(d));
      const kl = Array.isArray(k) ? k : [k];
      const o = {};
      kl.forEach((x) => { if (x in d) o[x] = JSON.parse(JSON.stringify(d[x])); });
      return o;
    },
    set: async (o) => { Object.assign(d, JSON.parse(JSON.stringify(o))); },
    remove: async (k) => { (Array.isArray(k) ? k : [k]).forEach((x) => delete d[x]); },
    _vsichko: () => d
  };
}

function falshivChrome(izvlecheno) {
  const vikaniya = { executeScript: 0, permissions: [] };
  const chrome = {
    storage: { local: hranilishte(), session: hranilishte(), onChanged: { addListener() {} } },
    scripting: {
      executeScript: async () => { vikaniya.executeScript += 1; return [{ result: izvlecheno }]; }
    },
    permissions: { request: async (p) => { vikaniya.permissions.push(p); return chrome._razreshi !== false; } },
    _vikaniya: vikaniya
  };
  return chrome;
}

module.exports = { LNA, FIX, OCAKVANO, procheti, falshivChrome };
