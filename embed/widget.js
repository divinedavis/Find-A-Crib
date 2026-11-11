/*!
 * Find A Crib — embeddable rent-stabilization lookup.
 *
 * Drop-in address checker for tenant organisations, legal-aid sites, housing
 * reporters and anyone else who repeatedly has to answer "is this building
 * rent-stabilized". Free, no key, no tracking.
 *
 *   <div id="findacrib-check">
 *     <p>Rent-stabilization lookup by
 *        <a href="https://findacrib.com/" rel="nofollow">Find A Crib</a>
 *        — NY State DHCR registrations and NYC HPD open data.</p>
 *   </div>
 *   <script src="https://findacrib.com/embed/widget.js" async></script>
 *
 * The credit line inside the mount element is part of the snippet, not
 * decoration. It puts the attribution in the HOST PAGE'S OWN HTML, so it is
 * there before this script runs and still there if the script is blocked or
 * never loads; attaching a shadow root below stops it from rendering, so a
 * reader sees the widget and not both.
 *
 * Every link this widget puts on a third-party page is rel="nofollow", and
 * that is deliberate rather than modest (2026-11-11). Google's spam policies
 * name "keyword-rich, hidden, or low-quality links embedded in widgets that
 * are distributed across various sites" as link spam and exempt links
 * qualified with rel="nofollow" or rel="sponsored"; its 2016 Search Central
 * reminder asks for nofollow on widget links, and in 2017 it said it
 * recognises a widget across sites and nofollows those links automatically.
 * So a followed credit here would buy nothing and could cost an embedder a
 * manual action on their own site. The anchor text is the brand name alone
 * for the same reason — the descriptive words sit outside the link.
 *
 * Design constraints, and why:
 *   - No dependencies and no build step. Sites that need this most are
 *     WordPress pages and legal-aid CMSes where a bundler is not an option.
 *   - Renders into a Shadow DOM so the host page's CSS cannot break it and
 *     ours cannot leak out.
 *   - Data comes from a keyless, heavily capped /api/embed/search endpoint.
 *     Requiring an API key would kill adoption; a shared key baked into the JS
 *     would give every embedder one 1,000/day quota to fight over.
 *   - Every answer carries the same caveat the site does: registration is at
 *     the building level and does not guarantee a specific unit is stabilized.
 *     A widget that implies otherwise would be worse than no widget.
 */
(function () {
  "use strict";
  var API = "https://findacrib.com/api/embed";
  var SITE = "https://findacrib.com";
  var MOUNT = "findacrib-check";

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  }

  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}",
    ".w{border:1px solid #e3e8ef;border-radius:12px;padding:16px;background:#fff;color:#1a1f36;max-width:520px}",
    ".t{font-weight:700;font-size:15px;margin:0 0 2px}",
    ".s{color:#5b6472;font-size:13px;margin:0 0 12px}",
    ".r{display:flex;gap:8px;flex-wrap:wrap}",
    "input{flex:1 1 220px;min-width:0;padding:10px 12px;border:1px solid #d7dce5;border-radius:9px;font-size:14px;color:#1a1f36;background:#fff}",
    "input:focus{outline:2px solid #1a63d6;outline-offset:1px}",
    "button{padding:10px 16px;border:0;border-radius:9px;background:#1a63d6;color:#fff;font-weight:600;font-size:14px;cursor:pointer}",
    "button:disabled{opacity:.6;cursor:default}",
    ".o{margin-top:12px;font-size:14px;line-height:1.55}",
    ".hit{border:1px solid #bfe0cc;background:#f0fdf4;border-radius:10px;padding:12px}",
    ".miss{border:1px solid #e3e8ef;background:#f8f9fc;border-radius:10px;padding:12px}",
    ".addr{font-weight:700;margin:0 0 4px}",
    ".meta{color:#5b6472;font-size:13px}",
    ".cav{color:#5b6472;font-size:12px;margin-top:10px;line-height:1.5}",
    "a{color:#1a63d6}",
    ".by{margin-top:10px;font-size:11px;color:#9aa3af}",
    "ul{margin:8px 0 0;padding-left:18px}li{margin:3px 0}"
  ].join("");

  var CAVEAT = "Registration is at the building level. It does not guarantee a " +
    "specific apartment is stabilized — only the DHCR rent history for that unit does, " +
    "and it is free to request.";

  function mount(host) {
    var shadow = !!host.attachShadow;
    var root = shadow ? host.attachShadow({ mode: "open" }) : host;
    // The snippet ships a static credit line inside the mount element. With a
    // shadow root that light-DOM child simply stops being rendered, which is
    // exactly what we want: it stays in the host's markup for readers without
    // JavaScript and for anything reading the HTML, and the widget takes its
    // place on screen. Without attachShadow there is no such switch, so clear
    // it by hand rather than show the credit above the widget as well.
    if (!shadow) { while (host.firstChild) host.removeChild(host.firstChild); }
    var style = el("style"); style.textContent = CSS; root.appendChild(style);

    var w = el("div", { class: "w" });
    w.appendChild(el("p", { class: "t" }, "Is this building rent-stabilized?"));
    w.appendChild(el("p", { class: "s" }, "Search a NYC address against the DHCR registration files."));

    var row = el("div", { class: "r" });
    var input = el("input", {
      type: "text", placeholder: "e.g. 816 Ocean Ave", "aria-label": "Building address"
    });
    var btn = el("button", { type: "button" }, "Check");
    row.appendChild(input); row.appendChild(btn); w.appendChild(row);

    var out = el("div", { class: "o", "aria-live": "polite" }); w.appendChild(out);
    var by = el("div", { class: "by" });
    by.appendChild(document.createTextNode("Data from "));
    var a = el("a", {
      href: SITE + "/", target: "_blank", rel: "nofollow noopener"
    }, "Find A Crib");
    by.appendChild(a);
    by.appendChild(document.createTextNode(" · NY State DHCR + NYC HPD open data"));
    w.appendChild(by);
    root.appendChild(w);

    function show(node) { out.innerHTML = ""; out.appendChild(node); }

    function render(results, q) {
      if (!results || !results.length) {
        var m = el("div", { class: "miss" });
        m.appendChild(el("p", { class: "addr" }, "No rent-stabilized building found for that address"));
        var p = el("p", { class: "meta" });
        p.textContent = "That doesn't prove the building isn't regulated — it may be " +
          "registered under a different address format, or covered by a program other " +
          "than DHCR rent stabilization. Try the street number and name only.";
        m.appendChild(p);
        show(m); return;
      }
      var frag = document.createDocumentFragment();
      results.slice(0, 3).forEach(function (b) {
        var h = el("div", { class: "hit" });
        h.appendChild(el("p", { class: "addr" }, b.address + " — rent stabilized"));
        var bits = [];
        if (b.neighborhood) bits.push(b.neighborhood);
        if (b.borough) bits.push(b.borough.replace(/_/g, " "));
        if (b.units) bits.push(b.units + " units");
        if (b.year_built) bits.push("built " + b.year_built);
        h.appendChild(el("p", { class: "meta" }, bits.join(" · ")));
        if (b.hpd && b.hpd.open_violations != null) {
          h.appendChild(el("p", { class: "meta" },
            b.hpd.open_violations + " open HPD violations"));
        }
        var link = el("p", { class: "meta" });
        var la = el("a", {
          href: SITE + "/#d=" + encodeURIComponent(b.bbl), target: "_blank",
          rel: "nofollow noopener"
        }, "See it on the map →");
        link.appendChild(la); h.appendChild(link);
        frag.appendChild(h);
      });
      var c = el("p", { class: "cav" }, CAVEAT);
      frag.appendChild(c);
      show(frag);
    }

    function search() {
      var q = (input.value || "").trim();
      if (!q) { input.focus(); return; }
      btn.disabled = true; btn.textContent = "Checking…";
      show(el("p", { class: "meta" }, "Searching…"));
      fetch(API + "/search?q=" + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (d) { render(d.results || d.buildings || [], q); })
        .catch(function () {
          show(el("p", { class: "meta" },
            "Couldn't reach the lookup service. Try again in a moment, or search on findacrib.com."));
        })
        .then(function () { btn.disabled = false; btn.textContent = "Check"; });
    }

    btn.addEventListener("click", search);
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") search(); });
  }

  function init() {
    var hosts = document.querySelectorAll("#" + MOUNT + ", [data-findacrib-check]");
    for (var i = 0; i < hosts.length; i++) {
      if (!hosts[i].__facMounted) { hosts[i].__facMounted = true; mount(hosts[i]); }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }
})();
