// Въпросници: проверка в браузъра и изпращане като JSON към api/submit.php.
// Без JS формулярът пак се изпраща обикновено (POST), а сървърът проверява всичко наново.
(function () {
  "use strict";
  var started = Date.now();
  Array.prototype.forEach.call(document.querySelectorAll("form.survey"), function (form) {
    var status = form.querySelector(".status");
    var demo = document.body.hasAttribute("data-demo");
    var t = form.querySelector("input[name=_t]");

    function say(text, ok) { status.textContent = text; status.className = "status " + (ok ? "ok" : "bad"); }

    function collect() {
      var data = {}, fd = new FormData(form);
      fd.forEach(function (v, k) {
        if (/\[\]$/.test(k)) { k = k.slice(0, -2); (data[k] = data[k] || []).push(v); }
        else data[k] = v;
      });
      return data;
    }

    function validate() {
      var bad = [];
      Array.prototype.forEach.call(form.querySelectorAll(".field"), function (f) { f.classList.remove("invalid"); });
      Array.prototype.forEach.call(form.querySelectorAll("fieldset[data-max]"), function (fs) {
        var max = parseInt(fs.getAttribute("data-max"), 10);
        if (fs.querySelectorAll("input[type=checkbox]:checked").length > max) { fs.classList.add("invalid"); bad.push(fs); }
      });
      Array.prototype.forEach.call(form.querySelectorAll("[data-required-if]"), function (f) {
        var deps = f.getAttribute("data-required-if").split(",");
        var need = deps.some(function (d) { var x = form.elements[d]; return x && x.value && x.value.trim(); });
        var box = f.querySelector("input[type=checkbox]");
        if (need && !box.checked) { f.classList.add("invalid"); bad.push(f); }
      });
      Array.prototype.forEach.call(form.querySelectorAll("[required]"), function (x) {
        var ok = x.type === "radio" ? !!form.querySelector("input[name='" + x.name + "']:checked")
          : x.type === "checkbox" ? x.checked : x.checkValidity() && x.value.trim() !== "";
        if (!ok) { var f = x.closest(".field"); f.classList.add("invalid"); bad.push(f); }
      });
      Array.prototype.forEach.call(form.querySelectorAll("input[type=email]"), function (x) {
        if (x.value && !x.checkValidity()) { var f = x.closest(".field"); f.classList.add("invalid"); bad.push(f); }
      });
      return bad;
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var bad = validate();
      if (bad.length) { say("Провери отбелязаните въпроси.", false); bad[0].scrollIntoView({ block: "center" }); return; }
      if (demo) { say("Демо: отговорите не се изпращат.", true); return; }
      if (t) t.value = String(Math.round((Date.now() - started) / 1000));
      var btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      say("Изпращам…", true);
      fetch(form.action, { method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" },
                           body: JSON.stringify(collect()) })
        .then(function (r) { return r.json().catch(function () { return { ok: false }; }).then(function (j) { j.status = r.status; return j; }); })
        .then(function (j) {
          if (j.ok) { form.reset(); say("Благодарим! Отговорите са записани.", true); }
          else { say(j.error || "Не успях да запиша отговорите. Опитай пак след малко.", false); btn.disabled = false; }
        })
        .catch(function () { say("Няма връзка. Опитай пак след малко.", false); btn.disabled = false; });
    });
  });
})();
