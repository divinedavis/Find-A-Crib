// How fast this visit was, from the browser's own timings (owner, 2026-11-10:
// "real-visitor speed metrics"). Sent once as the page is left, to /vitals,
// which nginx writes to its own log with no address and no browser details
// (deploy/nginx). Every timing goes as a range, never the number itself;
// vitals_report.py reads the log.
(function () {
  if (typeof PerformanceObserver === "undefined" || !navigator.sendBeacon) return;
  var EDGES = { ttfb: [200, 800, 1800], fcp: [1000, 1800, 3000, 5000], lcp: [1500, 2500, 4000, 6000, 10000], inp: [100, 200, 500, 1000] };
  var range = function (x, edges) {
    if (typeof x !== "number" || !isFinite(x) || x < 0) return null;
    var lo = 0;
    for (var i = 0; i < edges.length; i++) { if (x < edges[i]) return lo + "-" + edges[i]; lo = edges[i]; }
    return lo + "+";
  };
  var v = {}, shifts = [];
  var observe = function (type, read, more) {
    try { new PerformanceObserver(function (l) { read(l.getEntries()); }).observe(Object.assign({ type: type, buffered: true }, more || {})); } catch (e) { /* not in this browser */ }
  };
  observe("paint", function (es) { es.forEach(function (e) { if (e.name === "first-contentful-paint") v.fcp = e.startTime; }); });
  observe("largest-contentful-paint", function (es) { if (es.length) v.lcp = es[es.length - 1].startTime; });
  observe("layout-shift", function (es) { shifts.push.apply(shifts, es); });
  observe("event", function (es) { es.forEach(function (e) { if (e.interactionId) v.inp = Math.max(v.inp || 0, e.duration); }); }, { durationThreshold: 40 });
  // The worst burst of layout shift (a burst ends after a 1 s pause or 5 s), as web.dev/cls scores it.
  var cls = function () {
    var worst = 0, burst = 0, first = 0, last = 0;
    shifts.forEach(function (e) {
      if (e.hadRecentInput) return;
      if (burst && e.startTime - last < 1000 && e.startTime - first < 5000) burst += e.value; else { burst = e.value; first = e.startTime; }
      last = e.startTime; worst = Math.max(worst, burst);
    });
    return worst;
  };
  var sent = false;
  var flush = function () {
    if (sent || document.visibilityState !== "hidden") return;
    sent = true;
    var nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
    if (nav && nav.responseStart > 0) v.ttfb = nav.responseStart;
    var q = ["p=" + (location.pathname.split("/")[1] || "nyc").replace(/[^a-z]/g, "").slice(0, 12)];
    Object.keys(EDGES).forEach(function (k) { var r = range(v[k], EDGES[k]); if (r) q.push(k + "=" + r); });
    if (shifts.length) { var c = cls(); q.push("cls=" + (c < 0.1 ? "0-0.1" : c < 0.25 ? "0.1-0.25" : "0.25+")); }
    var conn = navigator.connection && navigator.connection.effectiveType;
    if (/^(slow-2g|2g|3g|4g)$/.test(conn || "")) q.push("c=" + conn);
    if (matchMedia("(display-mode: standalone)").matches || navigator.standalone === true) q.push("i=1");
    if (nav && nav.transferSize === 0 && nav.decodedBodySize > 0) q.push("r=1");
    navigator.sendBeacon("/vitals?" + q.join("&"));
  };
  document.addEventListener("visibilitychange", flush);
  addEventListener("pagehide", flush);
})();
