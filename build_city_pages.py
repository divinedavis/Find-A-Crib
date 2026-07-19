#!/usr/bin/env python3
"""Generate sf/index.html and la/index.html from the NYC index.html.

index.html is city-aware at runtime via <html data-city="…"> (see the CITIES
config in its script), but each city still needs its own static head metadata
for SEO. This script stamps the data-city attribute and swaps titles, meta
descriptions, canonical/og URLs, the header tagline, and the crawlable footer
nav. Run it after any index.html change:

    python3 build_city_pages.py

Each city dir also holds its buildings.min.json (from build_sf.py/build_la.py);
NYC-only data files (listings.json, s8.json, fmr.json) don't exist there and
the frontend fails soft to empty.
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "index.html"

NYC_TITLE = "Rent-Stabilized NYC — Manhattan, Bronx, Brooklyn, Queens + Staten Island"
NYC_DESC = "Find NYC rent-stabilized apartments across Manhattan, Bronx, Brooklyn, Queens & Staten Island."
NYC_OG_TITLE = "Rent-Stabilized NYC — Find A Crib"
NYC_TAGLINE = "(NYC Rent Stabilized Homes)"
NYC_SEO_NAV = """<nav class="seo-nav" aria-label="Browse rent-stabilized buildings by neighborhood">
  <h2>Find rent-stabilized apartments in NYC</h2>
  <p>Find A Crib maps every DHCR-registered rent-stabilized building in New York City.
     Browse all <a href="/buildings/">neighborhoods</a>, or by borough:
     <a href="/borough/manhattan/">Manhattan</a>, <a href="/borough/brooklyn/">Brooklyn</a>,
     <a href="/borough/queens/">Queens</a>, <a href="/borough/bronx/">the Bronx</a>,
     <a href="/borough/staten-island/">Staten Island</a>.
     Also on Find A Crib: <a href="/sf/">rent-controlled San Francisco</a> and
     <a href="/la/">rent-stabilized (RSO) Los Angeles</a>.</p>
</nav>"""

CITY_META = {
    "sf": {
        "title": "Rent-Controlled San Francisco — Map of SF Rent Board Inventory | Find A Crib",
        "og_title": "Rent-Controlled San Francisco — Find A Crib",
        "desc": ("Map 12,000+ San Francisco block-sides with rent-controlled apartments, "
                 "from official SF Rent Board owner reports — median reported rents, "
                 "unit counts, year built, by neighborhood."),
        "tagline": "(San Francisco Rent Controlled Homes)",
        "seo_nav": """<nav class="seo-nav" aria-label="About this map">
  <h2>Find rent-controlled apartments in San Francisco</h2>
  <p>Find A Crib maps the SF Rent Board's Housing Inventory — owner-reported,
     rent-controlled units across San Francisco, shown at the block level with
     median reported rents. Also on Find A Crib:
     <a href="/">rent-stabilized NYC</a> and <a href="/la/">rent-stabilized (RSO) Los Angeles</a>.</p>
</nav>""",
    },
    "la": {
        "title": "Rent-Stabilized (RSO) Los Angeles — 67,000+ Likely-Covered Buildings | Find A Crib",
        "og_title": "Rent-Stabilized (RSO) Los Angeles — Find A Crib",
        "desc": ("Map 67,000+ Los Angeles buildings that meet the Rent Stabilization "
                 "Ordinance criteria (2+ units, built before Oct 1979), derived from "
                 "LA County assessor rolls. Verify any address on ZIMAS."),
        "tagline": "(LA Rent-Stabilized · RSO)",
        "seo_nav": """<nav class="seo-nav" aria-label="About this map">
  <h2>Find likely rent-stabilized (RSO) apartments in Los Angeles</h2>
  <p>Find A Crib maps City of LA residential buildings that meet LAHD's RSO
     criteria — two or more units, built on or before Oct 1, 1978 — from LA
     County assessor parcel data. Confirm any building on ZIMAS. Also on
     Find A Crib: <a href="/">rent-stabilized NYC</a> and
     <a href="/sf/">rent-controlled San Francisco</a>.</p>
</nav>""",
    },
}


def substitute(html, old, new, what):
    n = html.count(old)
    if n != 1:
        sys.exit(f"FATAL: expected exactly 1 occurrence of {what!r}, found {n} — "
                 "index.html changed; update build_city_pages.py")
    return html.replace(old, new)


def main():
    src = SRC.read_text()
    for city, m in CITY_META.items():
        html = src
        html = substitute(html, '<html lang="en">', f'<html lang="en" data-city="{city}">', "html tag")
        html = substitute(html, f"<title>{NYC_TITLE}</title>", f"<title>{m['title']}</title>", "title")
        html = substitute(html, f'<meta name="description" content="{NYC_DESC}" />',
                          f'<meta name="description" content="{m["desc"]}" />', "meta description")
        html = substitute(html, '<link rel="canonical" href="https://findacrib.com/" />',
                          f'<link rel="canonical" href="https://findacrib.com/{city}/" />', "canonical")
        html = substitute(html, f'<meta property="og:title" content="{NYC_OG_TITLE}" />',
                          f'<meta property="og:title" content="{m["og_title"]}" />', "og:title")
        html = substitute(html, f'<meta property="og:description" content="{NYC_DESC}" />',
                          f'<meta property="og:description" content="{m["desc"]}" />', "og:description")
        html = substitute(html, '<meta property="og:url" content="https://findacrib.com/" />',
                          f'<meta property="og:url" content="https://findacrib.com/{city}/" />', "og:url")
        html = substitute(html, f'<meta name="twitter:title" content="{NYC_OG_TITLE}" />',
                          f'<meta name="twitter:title" content="{m["og_title"]}" />', "twitter:title")
        html = substitute(html, f'<meta name="twitter:description" content="{NYC_DESC}" />',
                          f'<meta name="twitter:description" content="{m["desc"]}" />', "twitter:description")
        html = substitute(html, f'<span class="brand-sub">{NYC_TAGLINE}</span>',
                          f'<span class="brand-sub">{m["tagline"]}</span>', "brand tagline")
        html = substitute(html, 'src="config.js?v=2"', 'src="../config.js?v=2"', "config.js path")
        html = substitute(html, NYC_SEO_NAV, m["seo_nav"], "seo nav")
        out = HERE / city / "index.html"
        out.parent.mkdir(exist_ok=True)
        out.write_text(html)
        print(f"Wrote {out} ({out.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
