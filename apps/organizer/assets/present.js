// Прожекция: P — вкл./изкл., → ↓ PageDown Space — напред, ← ↑ PageUp — назад, Home/End, F — цял екран, Esc — изход.
// Кликерите пращат PageDown/PageUp. Без мрежа и без библиотеки. Позицията стои в адреса (#p3), за да оцелее при презареждане.
(function () {
  "use strict";
  var root = document.documentElement, slides = [], i = 0, counter = null;

  function show(n) {
    i = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach(function (s, k) { s.classList.toggle("on", k === i); });
    if (slides[i]) slides[i].scrollTop = 0;
    if (counter) counter.textContent = (i + 1) + " / " + slides.length;
    try { history.replaceState(null, "", "#p" + (i + 1)); } catch (e) { /* file:// */ }
  }

  function start(n) {
    slides = Array.prototype.slice.call(document.querySelectorAll("[data-slide]"));
    if (!slides.length) return;
    if (!counter) {
      counter = document.createElement("div");
      counter.className = "present-count";
      counter.setAttribute("aria-live", "polite");
      document.body.appendChild(counter);
    }
    root.classList.add("present");
    show(n || 0);
  }

  function stop() {
    root.classList.remove("present");
    slides.forEach(function (s) { s.classList.remove("on"); });
    try { history.replaceState(null, "", location.pathname + location.search); } catch (e) { /* file:// */ }
    if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen();
  }

  function on() { return root.classList.contains("present"); }

  document.addEventListener("keydown", function (e) {
    var t = e.target;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    var k = e.key;
    if (k === "p" || k === "P" || k === "з" || k === "З") { on() ? stop() : start(0); e.preventDefault(); return; }
    if (!on()) return;
    if (k === "ArrowRight" || k === "ArrowDown" || k === "PageDown" || k === " ") show(i + 1);
    else if (k === "ArrowLeft" || k === "ArrowUp" || k === "PageUp") show(i - 1);
    else if (k === "Home") show(0);
    else if (k === "End") show(slides.length - 1);
    else if (k === "Escape") stop();
    else if ((k === "f" || k === "F") && root.requestFullscreen) {
      document.fullscreenElement ? document.exitFullscreen() : root.requestFullscreen();
    } else return;
    e.preventDefault();
  });

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-present-toggle]");
    if (b) { on() ? stop() : start(0); }
  });

  var m = /^#p(\d+)$/.exec(location.hash);
  if (m) start(parseInt(m[1], 10) - 1);
})();
