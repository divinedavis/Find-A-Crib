// The website's half of the owner's Monitor page (pipeline/monitor.py,
// 2026-11-15): which buttons and links are pressed, and how long each call
// to our API (/api/...) and to Supabase takes as the visitor waits. Sent in
// batches to /api/monitor. Errors, screens and the rest of the visit already
// reach the events table, which the monitor copies. The visitor id is the
// same fac_vid the visit count keeps; the server stores only a hash of it.
// Never sends what's typed into a field. Loaded before the page's own
// scripts so the Supabase client picks up the timed fetch.
(function () {
  // Automated browsers (the journey suite, crawlers) aren't visitors: the same test as the page's isBot().
  if (typeof window.fetch !== "function" || navigator.webdriver ||
      /bot|crawl|spider|slurp|headless|lighthouse|prerender|playwright|facebookexternal|mediapartners|google-inspectiontool|googleother/i.test(navigator.userAgent)) return;
  var ENDPOINT = "/api/monitor", queue = [], orig = window.fetch.bind(window);
  var sid = (function () {
    try {
      var s = sessionStorage.getItem("fac_mon_sid");
      if (!s) { s = Math.random().toString(36).slice(2, 12) + Date.now().toString(36); sessionStorage.setItem("fac_mon_sid", s); }
      return s;
    } catch (e) { return null; }
  })();
  function vid() {
    var m = document.cookie.match(/(?:^|;\s*)fac_vid=([\w-]+)/);
    if (m) return m[1];
    try { return localStorage.getItem("fac_vid"); } catch (e) { return null; }
  }
  function screen() {
    var seg = location.pathname.split("/").filter(Boolean)[0] || "home";
    return seg.replace(/\.html$/, "").replace(/[^a-z0-9_:-]/gi, "").toLowerCase().slice(0, 40) || "home";
  }
  function push(ev) {
    ev.t = Date.now(); ev.sc = ev.sc || screen();
    queue.push(ev);
    if (queue.length > 300) queue = queue.slice(-300);
    if (queue.length >= 40) flush(false);
  }
  function flush(beacon) {
    if (!queue.length) return;
    var id = vid();
    if (!id) { if (queue.length > 200) queue = []; return; }   // the page sets fac_vid once it starts
    var body = JSON.stringify({ id: id, s: sid, now: Date.now(), ev: queue.splice(0, 40) });
    try {
      if (beacon && navigator.sendBeacon && navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "application/json" }))) return;
      orig(ENDPOINT, { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: body }).catch(function () {});
    } catch (e) { /* a lost batch is fine */ }
    if (queue.length) flush(beacon);
  }
  window.fetch = function (input, init) {
    var url;
    try { url = new URL(typeof input === "string" ? input : (input && input.url) || String(input), location.href); } catch (e) { return orig(input, init); }
    var ours = url.origin === location.origin && /^\/api\//.test(url.pathname) && !/^\/api\/monitor\b/.test(url.pathname);
    var sb = /\.supabase\.co$/.test(url.hostname) && /^\/(rest|auth|functions|storage)\/v1\//.test(url.pathname);
    if (!ours && !sb) return orig(input, init);
    var method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
    var name = sb ? url.origin + url.pathname : url.pathname, t0 = performance.now();
    return orig(input, init).then(function (res) {
      var ev = { k: "api", n: name, m: method, st: res.status, ms: Math.round(performance.now() - t0) };
      if (res.status >= 500) ev.msg = method + " " + url.pathname + " answered " + res.status;
      push(ev);
      return res;
    }, function (err) {
      if (!err || err.name !== "AbortError")
        push({ k: "api", n: name, m: method, st: 0, ms: Math.round(performance.now() - t0), msg: method + " " + url.pathname + ": " + ((err && err.name) || "network error") });
      throw err;
    });
  };
  var TAPPABLE = 'button, a[href], [role="button"], [role="tab"], [role="menuitem"], summary, input[type="checkbox"], input[type="radio"], input[type="submit"]';
  document.addEventListener("click", function (e) {
    var el = e.target && e.target.closest && e.target.closest(TAPPABLE);
    if (!el || el.closest("[data-monitor-skip]")) return;
    var t = el.getAttribute("data-monitor") || el.getAttribute("aria-label") || el.getAttribute("title") || el.innerText || el.textContent || el.value || "";
    t = String(t).replace(/\s+/g, " ").trim();
    if (!t) { var img = el.querySelector && el.querySelector("img[alt]"); t = (img && img.getAttribute("alt")) || el.id || ""; }
    if (t) push({ k: "tap", n: t.slice(0, 80) });
  }, true);
  setInterval(function () { flush(false); }, 5000);
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "hidden") flush(true); });
  addEventListener("pagehide", function () { flush(true); });
})();
