#!/usr/bin/env python3
"""Generate static, crawlable SEO pages from the building dataset.

For every rent-stabilized building and every neighborhood we emit a real HTML
page so search engines can index "is <address> rent stabilized" and
"rent-stabilized buildings in <neighborhood>" queries — the map alone is a
single JS page Google can't read.

Output goes to ./seo/ (gitignored) mirroring the docroot layout, so deploy is a
plain `rsync seo/ /var/www/rent-map/`. Pages are <dir>/index.html so the
existing nginx `try_files $uri $uri/` serves clean extensionless URLs with no
config change.

    python3 build_seo.py
"""
import json
import os
import re
import html
import datetime
from collections import defaultdict

SITE = "https://findacrib.com"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seo")
BUILD_DATE = datetime.date.today().isoformat()  # sitemap <lastmod>


def breadcrumb(items):
    """schema.org BreadcrumbList from [(name, absolute_url), ...] for rich results."""
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": name, "item": url}
                for i, (name, url) in enumerate(items)]}

BORO_NAME = {"M": "Manhattan", "Bk": "Brooklyn", "Q": "Queens",
             "Bx": "the Bronx", "SI": "Staten Island"}
BORO_SLUG = {"M": "manhattan", "Bk": "brooklyn", "Q": "queens",
             "Bx": "bronx", "SI": "staten-island"}


def slugify(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-") or "x"


def esc(s):
    return html.escape(str(s if s is not None else ""))


def titlecase_addr(a):
    """'246 10TH AVE' -> '246 10th Ave' (keep ordinals lowercase-suffixed)."""
    out = []
    for w in (a or "").split():
        m = re.match(r"^(\d+)(ST|ND|RD|TH)$", w)
        if m:
            out.append(m.group(1) + m.group(2).lower())
        elif w.isdigit():
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)


# ---- shared chrome ---------------------------------------------------------
CSS = """
:root{--blue:#006aff;--ink:#0a0a23;--ink2:#4a4a68;--line:#e2e6ea;--bg:#f7f8fa}
*{box-sizing:border-box}
body{margin:0;font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
header.site{background:#fff;border-bottom:1px solid var(--line);padding:14px 20px}
header.site a.brand{font-weight:700;color:var(--ink);font-size:18px}
main{max-width:880px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:28px;line-height:1.2;margin:.2em 0 .4em}
h2{font-size:20px;margin:1.6em 0 .5em}
.lead{font-size:18px;color:var(--ink2)}
.cta{display:inline-block;background:var(--blue);color:#fff;padding:11px 18px;border-radius:10px;font-weight:600;margin:14px 0}
.cta:hover{text-decoration:none;opacity:.92}
table.facts{border-collapse:collapse;width:100%;margin:8px 0 4px;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}
table.facts td{padding:10px 14px;border-top:1px solid var(--line);vertical-align:top}
table.facts tr:first-child td{border-top:0}
table.facts td.k{color:var(--ink2);width:42%;font-weight:600}
.badge{display:inline-block;background:#e8f7ec;color:#137333;border:1px solid #b7e0c2;padding:3px 9px;border-radius:999px;font-size:13px;font-weight:600}
.badge.warn{background:#fff4e5;color:#a15c00;border-color:#f3d9a8}
.cols{columns:2;column-gap:28px}@media(max-width:640px){.cols{columns:1}}
.cols a{display:block;padding:3px 0}
.crumbs{font-size:14px;color:var(--ink2);margin-bottom:6px}
footer.site{border-top:1px solid var(--line);margin-top:40px;padding:22px 20px;color:var(--ink2);font-size:13px;max-width:880px;margin-left:auto;margin-right:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px}
"""


def page(title, desc, canonical, body, jsonld=None):
    ld = ""
    if jsonld:
        ld = '<script type="application/ld+json">%s</script>' % json.dumps(jsonld)
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canonical}">
<link rel="icon" href="/favicon.ico" sizes="any">
<meta property="og:type" content="website"><meta property="og:site_name" content="Find A Crib">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canonical}"><meta property="og:image" content="{SITE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<style>{CSS}</style>{ld}</head><body>
<header class="site"><a class="brand" href="/">🏠 Find A Crib</a> &nbsp;·&nbsp;
<a href="/buildings/">All neighborhoods</a></header>
<main>{body}</main>
<footer class="site">Data: NYC DHCR 2024 rent-stabilized building files, NYC PLUTO (coordinates),
and NYC HPD Open Data (owner, violations, complaints). A building's rent-stabilized status reflects
DHCR registration; it is not a guarantee that a specific unit is available or currently stabilized.
&copy; Find A Crib. <a href="/">Open the interactive map →</a></footer>
</body></html>"""


def write(relpath, contents):
    full = os.path.join(OUT, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(contents)


def main():
    blds = json.load(open("buildings.min.json"))
    try:
        listings = json.load(open("listings.json"))
        listed = set(str(k) for k in (listings.get("counts") or {}).keys())
    except Exception:
        listed = set()

    # index buildings by (borough, neighborhood) for neighborhood pages + nearby links
    by_nb = defaultdict(list)
    for b in blds:
        if b.get("nb"):
            by_nb[(b["b"], b["nb"])].append(b)
    for k in by_nb:
        by_nb[k].sort(key=lambda x: x.get("a", ""))

    def bld_url(b):
        return f"/building/{BORO_SLUG.get(b['b'],'nyc')}/{slugify(b.get('a'))}-{b['bbl']}/"

    def nb_url(boro, nb):
        return f"/neighborhood/{BORO_SLUG.get(boro,'nyc')}/{slugify(nb)}/"

    urls = []  # (loc, priority) for sitemaps

    # ---- building pages ----
    for b in blds:
        addr = titlecase_addr(b.get("a"))
        boro = BORO_NAME.get(b["b"], "New York")
        nb = b.get("nb") or boro
        url = bld_url(b)
        canonical = SITE + url
        h = b.get("h") or {}
        units = b.get("u")
        yr = b.get("yr")
        adv = b["bbl"] in listed

        # unique, data-driven lead sentence (avoids thin/duplicate content)
        bits = [f"<strong>{esc(addr)}</strong> is a registered NYC rent-stabilized building in "
                f"<a href=\"{nb_url(b['b'], b.get('nb') or boro)}\">{esc(nb)}</a>, {esc(boro)}"]
        if b.get("z"):
            bits[0] += f" ({esc(b['z'])})"
        bits[0] += "."
        if units:
            bits.append(f"It has about {esc(units)} apartment{'s' if units != 1 else ''}"
                        + (f", built in {esc(yr)}." if yr else "."))
        if adv:
            bits.append("A unit here was <strong>recently advertised for rent</strong>.")
        lead = " ".join(bits)

        rows = [("Borough", boro), ("Neighborhood", esc(nb)), ("ZIP", b.get("z")),
                ("Year built", yr), ("Apartments", units),
                ("Rent-stabilized", "Yes — DHCR registered"),
                ("Stabilization code", ", ".join(b.get("s") or []) or "—"),
                ("BBL", b["bbl"])]
        facts = "".join(f"<tr><td class='k'>{esc(k)}</td><td>{esc(v)}</td></tr>"
                        for k, v in rows if v not in (None, "", "—") or k == "Stabilization code")

        owner_html = ""
        o = h.get("owner") or {}
        m = h.get("manager") or {}
        if o.get("name") or m.get("name"):
            parts = []
            if o.get("name"):
                parts.append(f"<tr><td class='k'>Owner</td><td>{esc(o['name'])}"
                             + (f"<br><span style='color:#4a4a68'>{esc(o.get('address'))}</span>" if o.get("address") else "")
                             + "</td></tr>")
            if m.get("name"):
                parts.append(f"<tr><td class='k'>Managing agent</td><td>{esc(m['name'])}</td></tr>")
            owner_html = "<h2>Owner &amp; management</h2><table class='facts'>" + "".join(parts) + "</table>"

        cond_html = ""
        v = h.get("violations") or {}
        c = h.get("complaints") or {}
        if v or c:
            vr = (f"<tr><td class='k'>HPD violations</td><td>{esc(v.get('open',0))} open / "
                  f"{esc(v.get('total',0))} total"
                  + (f" · {esc(v.get('last_12mo',0))} in last 12 mo" if v.get('last_12mo') else "")
                  + "</td></tr>") if v else ""
            cr = (f"<tr><td class='k'>HPD complaints</td><td>{esc(c.get('open',0))} open / "
                  f"{esc(c.get('total',0))} total</td></tr>") if c else ""
            link = (f"<tr><td class='k'>City record</td><td><a href=\"{esc(h['hpd_url'])}\" "
                    f"rel=\"nofollow noopener\" target=\"_blank\">View on HPD Online ↗</a></td></tr>") if h.get("hpd_url") else ""
            cond_html = "<h2>Building conditions</h2><table class='facts'>" + vr + cr + link + "</table>"

        # nearby buildings in same neighborhood for internal linking / crawl depth
        nearby = [x for x in by_nb.get((b["b"], b.get("nb")), []) if x["bbl"] != b["bbl"]][:12]
        near_html = ""
        if nearby:
            items = "".join(f"<a href=\"{bld_url(x)}\">{esc(titlecase_addr(x.get('a')))}</a>" for x in nearby)
            near_html = (f"<h2>Other rent-stabilized buildings in {esc(nb)}</h2><div class='cols'>{items}</div>"
                         f"<p><a href=\"{nb_url(b['b'], b.get('nb') or boro)}\">See all in {esc(nb)} →</a></p>")

        faq = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{
            "@type": "Question", "name": f"Is {addr} rent stabilized?",
            "acceptedAnswer": {"@type": "Answer",
                "text": f"Yes. {addr} in {nb}, {boro} is a DHCR-registered rent-stabilized building"
                        + (f" with about {units} apartments." if units else ".")}}]}
        crumb = breadcrumb([
            ("Home", SITE + "/"),
            (boro, SITE + f"/borough/{BORO_SLUG.get(b['b'],'nyc')}/"),
            (nb, SITE + nb_url(b['b'], b.get('nb') or boro)),
            (addr, canonical),
        ])
        jsonld = [faq, crumb]

        body = (f"<div class='crumbs'><a href='/'>Home</a> › "
                f"<a href='/borough/{BORO_SLUG.get(b['b'],'nyc')}/'>{esc(boro)}</a> › "
                f"<a href='{nb_url(b['b'], b.get('nb') or boro)}'>{esc(nb)}</a></div>"
                f"<h1>Is {esc(addr)} rent stabilized?</h1>"
                f"<p class='lead'>{lead}</p>"
                + (f"<p><span class='badge'>Recently advertised for rent</span></p>" if adv else "")
                + f"<a class='cta' href='/#d={b['bbl']}'>View {esc(addr)} on the map →</a>"
                f"<h2>Building details</h2><table class='facts'>{facts}</table>"
                + owner_html + cond_html + near_html)

        write(url.strip("/") + "/index.html",
              page(f"Is {addr} rent stabilized? — {nb}, {boro} | Find A Crib",
                   f"{addr} in {nb}, {boro} is a NYC rent-stabilized building. See units, year built, owner, and HPD violations.",
                   canonical, body, jsonld))
        urls.append((canonical, "0.6", b["b"]))

    # ---- neighborhood pages ----
    for (boro, nb), items in by_nb.items():
        boroname = BORO_NAME.get(boro, "New York")
        url = nb_url(boro, nb)
        canonical = SITE + url
        n = len(items)
        yrs = [x["yr"] for x in items if x.get("yr")]
        med = sorted(yrs)[len(yrs) // 2] if yrs else None
        links = "".join(f"<a href=\"{bld_url(x)}\">{esc(titlecase_addr(x.get('a')))}</a>" for x in items)
        body = (f"<div class='crumbs'><a href='/'>Home</a> › "
                f"<a href='/borough/{BORO_SLUG.get(boro,'nyc')}/'>{esc(boroname)}</a></div>"
                f"<h1>Rent-stabilized buildings in {esc(nb)}, {esc(boroname)}</h1>"
                f"<p class='lead'>There are <strong>{n:,}</strong> registered rent-stabilized buildings in "
                f"{esc(nb)}"
                + (f", most built around {esc(med)}" if med else "")
                + f". Tap any address to check its rent-stabilized status, owner, and HPD record.</p>"
                f"<a class='cta' href='/'>Explore {esc(nb)} on the map →</a>"
                f"<h2>All {n:,} buildings</h2><div class='cols'>{links}</div>")
        nb_crumb = breadcrumb([
            ("Home", SITE + "/"),
            (boroname, SITE + f"/borough/{BORO_SLUG.get(boro,'nyc')}/"),
            (nb, canonical),
        ])
        write(url.strip("/") + "/index.html",
              page(f"Rent-stabilized buildings in {nb}, {boroname} ({n}) | Find A Crib",
                   f"All {n} rent-stabilized buildings in {nb}, {boroname}. Check any address for status, owner, and violations.",
                   canonical, body, nb_crumb))
        urls.append((canonical, "0.7", boro))

    # ---- borough hub pages ----
    nbs_by_boro = defaultdict(list)
    for (boro, nb), items in by_nb.items():
        nbs_by_boro[boro].append((nb, len(items)))
    for boro, nbs in nbs_by_boro.items():
        boroname = BORO_NAME.get(boro, "New York")
        url = f"/borough/{BORO_SLUG.get(boro,'nyc')}/"
        canonical = SITE + url
        total = sum(c for _, c in nbs)
        links = "".join(f"<a href=\"{nb_url(boro, nb)}\">{esc(nb)} ({c:,})</a>"
                        for nb, c in sorted(nbs))
        body = (f"<div class='crumbs'><a href='/'>Home</a></div>"
                f"<h1>Rent-stabilized buildings in {esc(boroname)}</h1>"
                f"<p class='lead'>{total:,} registered rent-stabilized buildings across "
                f"{len(nbs)} {esc(boroname)} neighborhoods.</p>"
                f"<a class='cta' href='/'>Open the map →</a>"
                f"<h2>Neighborhoods</h2><div class='cols'>{links}</div>")
        boro_crumb = breadcrumb([("Home", SITE + "/"), (boroname, canonical)])
        write(url.strip("/") + "/index.html",
              page(f"Rent-stabilized buildings in {boroname} ({total}) | Find A Crib",
                   f"Browse {total} rent-stabilized buildings across {boroname} by neighborhood.",
                   canonical, body, boro_crumb))
        urls.append((canonical, "0.8", boro))

    # ---- master hub /buildings/ ----
    hub_links = ""
    for boro in ["M", "Bk", "Q", "Bx", "SI"]:
        if boro not in nbs_by_boro:
            continue
        boroname = BORO_NAME.get(boro)
        nl = "".join(f"<a href=\"{nb_url(boro, nb)}\">{esc(nb)} ({c:,})</a>"
                     for nb, c in sorted(nbs_by_boro[boro]))
        hub_links += (f"<h2><a href='/borough/{BORO_SLUG[boro]}/'>{esc(boroname)}</a></h2>"
                      f"<div class='cols'>{nl}</div>")
    write("buildings/index.html",
          page("NYC rent-stabilized buildings by neighborhood | Find A Crib",
               "Browse every NYC rent-stabilized building by borough and neighborhood — Manhattan, Brooklyn, Queens, the Bronx, Staten Island.",
               SITE + "/buildings/",
               f"<h1>NYC rent-stabilized buildings</h1><p class='lead'>Browse all "
               f"{len(blds):,} DHCR rent-stabilized buildings by borough and neighborhood, "
               f"or <a href='/'>open the interactive map</a>.</p>" + hub_links))
    urls.append((SITE + "/buildings/", "0.9", "hub"))

    # ---- sitemaps (sharded by borough, < 50k each) + index ----
    by_boro_urls = defaultdict(list)
    for loc, pri, key in urls:
        by_boro_urls[key].append((loc, pri))
    smaps = []
    for key, locs in by_boro_urls.items():
        name = f"sitemap-{key}.xml"
        body = "".join(f"<url><loc>{loc}</loc><lastmod>{BUILD_DATE}</lastmod><priority>{pri}</priority></url>" for loc, pri in locs)
        write(name, f'<?xml version="1.0" encoding="UTF-8"?>'
                    f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>')
        smaps.append(name)
    idx = "".join(f"<sitemap><loc>{SITE}/{n}</loc><lastmod>{BUILD_DATE}</lastmod></sitemap>" for n in sorted(smaps))
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>'
          f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          f'<sitemap><loc>{SITE}/sitemap-main.xml</loc><lastmod>{BUILD_DATE}</lastmod></sitemap>{idx}</sitemapindex>')
    # main sitemap = homepage + hub
    write("sitemap-main.xml", f'<?xml version="1.0" encoding="UTF-8"?>'
          f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          f'<url><loc>{SITE}/</loc><lastmod>{BUILD_DATE}</lastmod><priority>1.0</priority></url></urlset>')
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")

    print(f"Generated {len(urls):,} pages + {len(smaps)+2} sitemaps into {OUT}/")


if __name__ == "__main__":
    main()
