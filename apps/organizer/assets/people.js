// Лектори и партньори в движение: страницата идва с профилите от сглобяването,
// а тук ги опресняваме от people.json — човек се добавя с един ред, без ново сглобяване.
(function () {
  "use strict";
  var boxes = document.querySelectorAll("[data-people]");
  if (!boxes.length || !window.fetch) return;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }
  function safeUrl(u) { return /^(https:\/\/|[\w.\/-]+$)/.test(u || "") && !/^javascript:/i.test(u) ? u : null; }

  function card(p, kind) {
    var a = el("article", p ? "person" : "person empty");
    var photo = p && safeUrl(p.photo);
    var av;
    if (photo) { av = el("img", "avatar"); av.src = photo; av.alt = ""; av.loading = "lazy"; }
    else { av = el("div", "avatar"); av.setAttribute("aria-hidden", "true"); }
    a.appendChild(av);
    var h = el("h3");
    if (!p) { h.textContent = kind === "speakers" ? "Лектор" : "Партньор"; a.appendChild(h); a.appendChild(el("p", "muted", "Предстои")); return a; }
    var link = safeUrl(p.link);
    if (link) { var l = el("a", null, p.name); l.href = link; l.rel = "noopener"; h.appendChild(l); } else h.textContent = p.name;
    a.appendChild(h);
    if (p.role) a.appendChild(el("p", "role", p.role));
    if (p.bio) a.appendChild(el("p", null, p.bio));
    return a;
  }

  fetch("people.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
    if (!data) return;
    Array.prototype.forEach.call(boxes, function (box) {
      var kind = box.getAttribute("data-people");
      var list = (data[kind] || []).filter(function (p) { return p && p.name; });
      var n = Math.max(list.length, (data.placeholders || {})[kind] || 0);
      box.textContent = "";
      for (var k = 0; k < n; k++) box.appendChild(card(list[k] || null, kind));
    });
  }).catch(function () { /* без мрежа остават профилите от сглобяването */ });
})();
