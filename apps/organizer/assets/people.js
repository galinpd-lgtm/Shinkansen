// Лектори и партньори в движение: страницата идва с профилите от сглобяването,
// а тук ги опресняваме от data/*.json — човек се добавя с един запис, без ново сглобяване.
// Запис с name е потвърден човек; запис само със slot е празно място („Лектор · Памет — очаква потвърждение“).
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
  function safeUrl(u) { return /^(https:\/\/|[\w][\w.\/#-]*$)/.test(u || "") && (u || "").indexOf("..") < 0 ? u : null; }

  function card(p, who) {
    var named = p && p.name;
    var a = el("article", named ? "person" : "person empty");
    var photo = named && safeUrl(p.photo);
    var av;
    if (photo) { av = el("img", "avatar"); av.src = photo; av.alt = p.name; av.loading = "lazy"; }
    else { av = el("div", "avatar"); av.setAttribute("aria-hidden", "true"); }
    a.appendChild(av);
    var h = el("h3");
    if (!named) {
      h.textContent = p && p.slot ? who + " · " + p.slot : who;
      a.appendChild(h);
      a.appendChild(el("p", "muted", "очаква потвърждение"));
      return a;
    }
    var link = safeUrl(p.link);
    if (link) { var l = el("a", null, p.name); l.href = link; l.rel = "noopener"; h.appendChild(l); } else h.textContent = p.name;
    a.appendChild(h);
    if (p.role) a.appendChild(el("p", "role", p.role));
    if (p.bio) a.appendChild(el("p", null, p.bio));
    return a;
  }

  Array.prototype.forEach.call(boxes, function (box) {
    var file = box.getAttribute("data-people");
    var min = parseInt(box.getAttribute("data-min") || "0", 10);
    var who = /partn/.test(file) ? "Партньор" : "Лектор";
    fetch(file, { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (list) {
      if (!Array.isArray(list)) return;
      list = list.filter(function (p) { return p && (p.name || p.slot); });
      while (list.length < min) list.push(null);
      box.textContent = "";
      list.forEach(function (p) { box.appendChild(card(p, who)); });
    }).catch(function () { /* без мрежа остават профилите от сглобяването */ });
  });
})();
