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
import bisect
import json
import os
import re
import html
import math
import hashlib
import datetime
from collections import defaultdict
from seo_guides import GUIDES, _related

SITE = "https://findacrib.com"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seo")
BUILD_DATE = datetime.date.today().isoformat()  # sitemap <lastmod>

# --- honest lastmod: only bump a page's <lastmod> when its HTML actually changes.
# State (url -> {h: content-hash, m: lastmod}) persists between runs next to this
# script so a nightly rebuild doesn't lie to crawlers about unchanged pages.
LM_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seo_lastmod.json")
try:
    LM_STATE = json.load(open(LM_STATE_PATH))
except Exception:
    LM_STATE = {}
LM_NEW = {}        # url -> {h, m} written back at the end
LASTMOD = {}       # url -> lastmod string, used when emitting sitemaps
LM_CHANGED = []     # urls whose content changed this run (for IndexNow)


def breadcrumb(items):
    """schema.org BreadcrumbList from [(name, absolute_url), ...] for rich results."""
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": name, "item": url}
                for i, (name, url) in enumerate(items)]}


def faq_jsonld(pairs):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a}}
                           for q, a in pairs]}


def faq_html(pairs):
    """Render FAQ pairs as visible HTML matching the FAQPage JSON-LD — structured
    data with no visible counterpart describes content that isn't there, and AI
    answer engines extract from rendered text, not hidden JSON-LD."""
    items = "".join(f"<div class='faq-item'><h3>{esc(q)}</h3><p>{esc(a)}</p></div>"
                     for q, a in pairs)
    return f"<h2>Frequently asked questions</h2><div class='faq'>{items}</div>"


# Roughly 50-70 words is the window that survives extraction: long enough to
# carry the number, the definition and the source, short enough to be quoted
# whole. These bounds are asserted at build time rather than trusted.
ANSWER_MIN_WORDS, ANSWER_MAX_WORDS = 45, 80


def answer_block(sentences):
    """The direct answer to the question the page's title asks.

    Hub pages already open with a lead line, but a lead assumes you have the
    page in front of you — "There are 1,204 buildings" means nothing lifted out
    of context. This block is written to be lifted: it names the place, gives
    the number, says what rent stabilization actually means for a tenant, and
    attributes the data, in one self-contained paragraph.

    That is the pattern behind the AI-answer-engine results other sites report,
    and unlike an FAQ it also serves the human who landed here from a search
    and wants the answer before the list of 1,204 addresses.

    Every sentence must come from real data. Callers pass finished sentences;
    this only assembles and checks the length, because a block that drifts long
    stops being extractable and one that drifts short stops being an answer.
    """
    text = " ".join(s.strip() for s in sentences if s and s.strip())
    n = len(text.split())
    if n < ANSWER_MIN_WORDS or n > ANSWER_MAX_WORDS:
        raise ValueError(f"answer block is {n} words, outside {ANSWER_MIN_WORDS}-{ANSWER_MAX_WORDS}: {text[:120]}…")
    return f"<div class='answer'><p>{esc(text)}</p></div>"


# The one-sentence definition every hub page carries. Deliberately identical
# everywhere: it is the load-bearing fact, and rewording it per page to look
# "unique" would be writing for a crawler rather than a reader.
STABILIZED_DEF = ("Rent stabilization caps how much the rent can rise each year — the "
                  "Rent Guidelines Board sets the limit — and gives the tenant the right "
                  "to renew the lease.")

# The crawl path from this corpus into the two sections the growth build
# publishes. Why it lives here and not in index.html: on 2026-08-06 /section8/
# and /brief/ had been rebuilt nightly for eleven days, sat in sitemap-daily.xml
# with an honest lastmod and were submitted to IndexNow every night, and had
# still never earned a single Search Console impression. The reason was that
# nothing a crawler reaches linked to either one. The 2026-08-05 review put the
# links in the repo's index.html, but neither droplet cron deploys that file —
# growth_daily.py rsyncs only growth_out/ and refresh_seo.sh only seo/ — so the
# fix could not reach production and the 2026-08-06 audit still reported both
# sections orphaned. This corpus is the part of the site Google actually crawls,
# and refresh_seo.sh does deploy it, so the link belongs here.
#
# It also repairs a one-way reference: /section8/<borough>/ already links out to
# /borough/<slug>/ and nothing linked back. A hub whose spokes never reinforce it
# is the shape that gets dropped from the index.
#
# Deliberately quotes no counts. The voucher pages are rebuilt by the growth
# build (growth/techniques.py t_fresh_section8) from a feed this pipeline never
# reads, hours after this one runs, so any number here would be a claim this
# build cannot substantiate. The destination carries the live figures; this
# block only has to be true and get a crawler there.
VOUCHER_XLINK = (
    "<h2>Renting with a housing voucher?</h2>"
    "<p>Find A Crib rebuilds a list every night of the DHCR-registered "
    "rent-stabilized buildings that have an apartment listed for Section 8 and "
    "other housing vouchers, from the overnight AffordableHousing.com feed — "
    "<a href='/section8/'>see the current voucher listings</a>, or read the "
    "<a href='/brief/'>daily brief</a> on which buildings came on and off the "
    "market.</p>")

# The same crawl path, for the three city browse hubs — and the reason it is a
# second string rather than a reuse of VOUCHER_XLINK.
#
# Why it exists at all: as of 2026-08-07 this is the ONLY inbound link into
# /section8/ and /brief/ that can actually reach production. VOUCHER_XLINK above
# lives in the NYC hub tier, which main() writes into seo/ and which reaches the
# docroot only when scripts/refresh_seo.sh runs — and that pipeline has not
# written since 2026-08-01. city_hub_docs() is different: the daily growth build
# imports it from a fresh git checkout every night and rsyncs the result into the
# docroot itself (growth/techniques.py: _publish_stranded_city_hubs), so a change
# here deploys on the next 05:40 UTC run whether or not the SEO pipeline ever
# recovers. Two consecutive reviews shipped this fix into files no cron deploys;
# this is the same fix routed through the path that demonstrably works.
#
# Why the wording differs. The voucher feed is New York City only — it is built
# from DHCR registrations and the AffordableHousing.com feed, and there is no
# equivalent for San Francisco, Los Angeles or Washington DC. Dropping the NYC
# block verbatim onto a San Francisco page would imply SF voucher coverage that
# does not exist, so the city and the gap are both named outright. A reader who
# is not in New York should be able to tell in one sentence that this is not for
# them; that is worth more than the click.
#
# On the three browse hubs only, not the 252 place pages under them. The browse
# hub already carries an "Other cities" section, so a cross-city block belongs
# there and nowhere else; repeating a New York block on every San Francisco
# neighborhood page would be boilerplate on the thinner tier, which is the
# duplication that plausibly drives the serving-set churn. One good link from a
# priority-0.9 page two clicks from /sf/ (which serves) beats 252 weak ones.
CITY_VOUCHER_XLINK = (
    "<h2>New York City: apartments listed for housing vouchers</h2>"
    "<p>Find A Crib's voucher feed covers New York City only — every night it "
    "rebuilds the list of DHCR-registered rent-stabilized buildings with an "
    "apartment listed for Section 8 and other housing vouchers, from the "
    "overnight AffordableHousing.com feed. "
    "<a href='/section8/'>See the current New York City voucher listings</a>, or "
    "read the <a href='/brief/'>daily brief</a> on which buildings came on and "
    "off the market. There is no equivalent feed for {city} yet.</p>")

BORO_NAME = {"M": "Manhattan", "Bk": "Brooklyn", "Q": "Queens",
             "Bx": "the Bronx", "SI": "Staten Island"}
BORO_SLUG = {"M": "manhattan", "Bk": "brooklyn", "Q": "queens",
             "Bx": "bronx", "SI": "staten-island"}


# ---- the non-NYC browse tier (SF / LA / DC) --------------------------------
# Why this exists, from growth/gsc_pages.json on 2026-07-30: of the 82 pages on
# this site earning any Search Console impression, 75 are single-building pages
# whose only query is the literal street address, and 58 of the 82 sit at
# position 10 or better. Ranking ability is not the constraint — addressable
# search volume is, and one address has almost none. The tier that aggregates
# (ZIP and neighborhood hubs) ranks at positions 2-4 where it serves, and three
# of the four cities on this site had none of it: /sf/, /la/ and /dc/ were a
# single JavaScript map shell each, which is also why 11 city queries were
# scored as "covered" by a page that cannot answer them.
#
# Each city is grouped on the dimension its data actually carries — SF and DC
# record a neighborhood, LA records only a ZIP — and every page states only
# stats that city holds: LA has no reported rents, DC has no build years.
MIN_CITY_HUB = 5      # below this a place gets no page rather than a thin one
CITY_LIST_CAP = 300   # addresses listed per page; overflow is stated, not hidden

CITY_HUBS = {
    "sf": dict(
        name="San Francisco", group="nb", path="neighborhood",
        thing="location", things="locations",
        h1="Rent-controlled apartments in {place}, San Francisco",
        browse_h1="Rent-controlled buildings in San Francisco by neighborhood",
        browse_link_text="rent-controlled San Francisco by neighborhood",
        guide="is-my-apartment-rent-controlled-san-francisco",
        list_h2="Block-sides reported in {place}",
        list_note="These are block-sides as the Rent Board publishes them, not individual addresses.",
    ),
    "la": dict(
        name="Los Angeles", group="z", path="zip",
        thing="building", things="buildings",
        h1="Rent-stabilized (RSO) buildings in ZIP {place}, Los Angeles",
        browse_h1="Rent-stabilized (RSO) buildings in Los Angeles by ZIP code",
        browse_link_text="likely-RSO Los Angeles by ZIP code",
        guide="is-my-apartment-rent-controlled-los-angeles",
        list_h2="Addresses meeting the RSO criteria in ZIP {place}",
        list_note="Derived from assessor records and labelled likely RSO — confirm any address "
                  "with LAHD or on ZIMAS before you rely on it.",
    ),
    "dc": dict(
        name="Washington, DC", group="nb", path="neighborhood",
        thing="property", things="properties",
        h1="Rent-controlled buildings in {place}, Washington DC",
        browse_h1="Rent-controlled buildings in Washington DC by neighborhood",
        browse_link_text="rent-controlled Washington DC by neighborhood",
        guide="is-my-apartment-rent-controlled-washington-dc",
        list_h2="Registered properties in {place}",
        list_note="A property is listed because its housing provider filed it as rent controlled.",
    ),
}


def _med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def _city_stats(items):
    """Only what the records actually hold — missing fields stay missing."""
    return {"n": len(items),
            "units": sum(x["u"] for x in items if x.get("u")),
            "yr": sorted(x["yr"] for x in items if x.get("yr")),
            "mr": sorted(x["mr"] for x in items if x.get("mr"))}


def _city_answer(key, place, st):
    """The extractable answer for a city hub. Wording differs per city because
    the underlying legal test and the data's authority differ per city, and
    flattening that into one template would mean saying something untrue about
    two of the three."""
    n, units = st["n"], st["units"]
    if key == "sf":
        return [f"{place}, San Francisco has {n:,} block-side locations with rent-controlled units "
                f"reported to the San Francisco Rent Board"
                + (f", covering about {units:,} apartments." if units else "."),
                "San Francisco rent control generally covers buildings occupied before 13 June 1979, "
                "capping the annual increase and requiring just cause to end a tenancy.",
                "This inventory is published anonymized to the block, not the individual address."]
    if key == "la":
        # "build year before 1979", not "before 1 October 1978": the assessor
        # records carry a year, not a date, so the tighter phrasing would assert
        # a precision the data does not have. The ordinance's real test is the
        # certificate-of-occupancy date, which is why the third sentence sends
        # the reader to LAHD rather than settling it here.
        return [f"ZIP code {place} in Los Angeles has {n:,} buildings that meet the Rent "
                f"Stabilization Ordinance criteria — two or more units and a build year before 1979"
                + (f" — about {units:,} apartments in total." if units else "."),
                "The RSO caps how much the rent can rise each year and requires just cause to evict.",
                "This list is derived from county assessor records, not the City's official RSO "
                "inventory, so confirm an address with LAHD or on ZIMAS."]
    return [f"{place} in Washington DC has {n:,} properties registered as rent controlled with the "
            f"District's Rental Accommodations Division"
            + (f", covering about {units:,} units." if units else "."),
            "DC rent control generally covers buildings built before 1976, and caps how much the "
            "rent can rise each year.",
            "Registration is the operative record: a unit its housing provider never registered is "
            "generally treated as covered rather than exempt."]


SIZE_BANDS = [(1, 1, "1 unit"), (2, 4, "2–4 units"), (5, 9, "5–9 units"),
              (10, 19, "10–19 units"), (20, None, "20+ units")]


def _band_table(items, label):
    """Distribution by reported unit count — a real per-page statistic, not a
    reworded version of the count above it."""
    rows = []
    for lo, hi, name in SIZE_BANDS:
        c = sum(1 for x in items
                if x.get("u") and x["u"] >= lo and (hi is None or x["u"] <= hi))
        if c:
            rows.append(f"<tr><td class='k'>{esc(name)}</td><td>{c:,} {esc(label)}</td></tr>")
    return (f"<h2>By building size</h2><table class='facts'>{''.join(rows)}</table>"
            if rows else "")


def _decade_table(items):
    counts = defaultdict(int)
    for x in items:
        if x.get("yr"):
            counts[(x["yr"] // 10) * 10] += 1
    rows = "".join(f"<tr><td class='k'>{d}s</td><td>{c:,} buildings</td></tr>"
                   for d, c in sorted(counts.items()))
    return f"<h2>By decade built</h2><table class='facts'>{rows}</table>" if rows else ""


DC_QUADRANTS = {"Nw": "NW", "Ne": "NE", "Sw": "SW", "Se": "SE"}


def _city_labels(key, items):
    """Deduplicated address labels for a city hub's list.

    Each city needs different handling, and none of them can use
    titlecase_addr's NYC assumptions unmodified — that helper is shared with
    47,000 NYC pages, so it is left alone rather than adjusted here (changing it
    would rewrite every NYC page and mass-bump their lastmod).

      * SF records a block-side ("1000 Block of REVERE AVE") once per reported
        building, so the raw list repeats the same block many times, and
        titlecase gives "Block Of".
      * DC records a full mailing address, sometimes down to a unit ("…, Ste
        501, Washington, DC, 20036"). The registry's claim is about the
        property, so the label stops at the street address — that also stops
        the page publishing a specific unit number.

    Sorted by street, then house number: a plain string sort files every
    "0 Block of …" first, which is not how anyone looks for their own street.
    """
    seen, out = set(), []
    for x in items:
        a = (x.get("a") or "").strip()
        if key == "dc":
            a = a.split(",")[0].strip()
        if not a:
            continue
        label = re.sub(r"\bOf\b", "of", titlecase_addr(a))
        if key == "dc":
            label = " ".join(DC_QUADRANTS.get(w, w) for w in label.split())
        if not re.search(r"[A-Za-z]", label):
            continue          # a bare "0" is not an address
        if re.match(r"^\d+\s+Block\s+of$", label):
            continue          # "0 Block of" with no street names nothing
        if label in seen:
            continue
        seen.add(label)
        m = re.match(r"^(\d+)\s+(.*)$", label)
        out.append(((m.group(2), int(m.group(1))) if m else (label, 0), label))
    out.sort(key=lambda t: t[0])
    return [label for _, label in out]


def _city_stat_table(key, st):
    cfg = CITY_HUBS[key]
    rows = [f"<tr><td class='k'>{esc(cfg['things'].capitalize())}</td><td>{st['n']:,}</td></tr>"]
    if st["units"]:
        rows.append(f"<tr><td class='k'>Units reported</td><td>{st['units']:,}</td></tr>")
    if st["yr"]:
        rows.append(f"<tr><td class='k'>Median year built</td>"
                    f"<td>{_med(st['yr'])} <span style='color:#4a4a68'>"
                    f"({len(st['yr']):,} with a recorded year)</span></td></tr>")
    if len(st["mr"]) >= MIN_CITY_HUB:
        rows.append(f"<tr><td class='k'>Median reported rent</td>"
                    f"<td>${_med(st['mr']):,} <span style='color:#4a4a68'>"
                    f"({len(st['mr']):,} reported one)</span></td></tr>")
    return f"<h2>The numbers here</h2><table class='facts'>{''.join(rows)}</table>"


def _city_faq(key, place, st):
    cfg = CITY_HUBS[key]
    n = st["n"]
    if key == "sf":
        faq = [(f"How many rent-controlled locations are in {place}, San Francisco?",
                f"The San Francisco Rent Board's housing inventory reports {n:,} rent-controlled "
                f"block-side locations in {place}. The inventory is anonymized to the block, so a "
                f"location is a block-side rather than a single address.")]
        if st["yr"]:
            pre = sum(1 for y in st["yr"] if y < 1979)
            faq.append((f"Were most rent-controlled buildings in {place} built before 1979?",
                        f"{pre:,} of the {len(st['yr']):,} locations in {place} with a recorded "
                        f"build year were built before 1979. The legal test is the date the "
                        f"certificate of occupancy was issued — before 13 June 1979 — not the "
                        f"assessor's build year, so treat this as an indication, not a ruling."))
        return faq
    if key == "la":
        faq = [(f"How many RSO buildings are in ZIP code {place}?",
                f"{n:,} buildings in ZIP code {place} meet the Los Angeles Rent Stabilization "
                f"Ordinance criteria — two or more units and a build year before 1979 — according "
                f"to county assessor records. The ordinance's own test is a certificate of "
                f"occupancy issued on or before 1 October 1978, so this is a close proxy rather "
                f"than a determination. LAHD holds the City's official RSO inventory.")]
        if st["yr"]:
            faq.append((f"How old are the RSO buildings in {place}?",
                        f"The median build year of the {len(st['yr']):,} buildings with a recorded "
                        f"year in ZIP {place} is {_med(st['yr'])}. Every building on this list has "
                        f"a build year before 1979, which is what puts it inside the criteria used "
                        f"here."))
        return faq
    faq = [(f"How many rent-controlled properties are in {place}, Washington DC?",
            f"{n:,} properties in {place} are registered as rent controlled with the District's "
            f"Rental Accommodations Division.")]
    if len(st["mr"]) >= MIN_CITY_HUB:
        faq.append((f"What rent is reported for rent-controlled units in {place}?",
                    f"The median rent reported to the Rental Accommodations Division across the "
                    f"{len(st['mr']):,} {place} properties that reported one is "
                    f"${_med(st['mr']):,}. That is what housing providers filed, not the market "
                    f"rent and not what a specific unit will cost."))
    return faq


# The three sentences a city-level answer is assembled from. Split out per city
# rather than templated because the authority behind each dataset is different
# and one wording would be untrue of two of the three: SF is an owner-reported
# inventory anonymized to the block, LA is a derived proxy for a list the City
# holds, DC is a registration record. `source` is a noun phrase that reads after
# "from"; `rule` states the legal test; `caveat` is the limit of the data and is
# never optional.
CITY_BROWSE_COPY = {
    "sf": dict(
        unit="apartments",
        source="the San Francisco Rent Board's housing inventory",
        rule="San Francisco rent control generally covers buildings occupied before 13 June 1979, "
             "capping the annual increase and requiring just cause to end a tenancy.",
        caveat="The inventory is published anonymized to the block, not the individual address.",
    ),
    "la": dict(
        unit="apartments",
        source="Los Angeles County Assessor parcel records filtered to the Rent Stabilization "
               "Ordinance criteria",
        rule="The RSO caps how much the rent can rise each year and requires just cause to evict.",
        caveat="This is a derived list labelled likely RSO, not the City's official inventory, "
               "which LAHD holds.",
    ),
    "dc": dict(
        unit="units",
        source="registration filings held by the District's Rental Accommodations Division",
        rule="DC rent control generally covers buildings built before 1976 and caps how much the "
             "rent can rise each year.",
        caveat="A property is listed because its housing provider filed it as covered, so "
               "registration is the operative record.",
    ),
}


def _place_word(cfg, plural=False):
    """'ZIP code' / 'neighborhood', matching how the city is grouped."""
    if cfg["path"] == "zip":
        return "ZIP codes" if plural else "ZIP code"
    return "neighborhoods" if plural else "neighborhood"


def _city_browse_answer(key, cfg, n, places, agg):
    """The extractable answer for a city's browse hub.

    Scoped to the index, not to the city: `n` is the sum over places that clear
    MIN_CITY_HUB, so "San Francisco has n" would overstate it. "This index
    covers n" is the claim the data actually supports, and it is the claim an
    answer engine would be quoting.
    """
    units = agg["units"]
    return [f"This index covers {n:,} {cfg['things']} across {places} "
            f"{_place_word(cfg, plural=True)} in {cfg['name']}, from {CITY_BROWSE_COPY[key]['source']}"
            + (f", about {units:,} {CITY_BROWSE_COPY[key]['unit']} in total." if units else "."),
            CITY_BROWSE_COPY[key]["rule"],
            CITY_BROWSE_COPY[key]["caveat"]]


def _city_browse_faq(key, cfg, n, places, small, counts, agg):
    """City-level Q&A for a browse hub — facts no single place page can state.

    Deliberately not a rewrite of the place-page FAQ: the two questions here are
    "how big is this index and what is left out of it" and "where is the data
    concentrated", both of which are answerable only across the whole tier.
    """
    copy = CITY_BROWSE_COPY[key]
    left_off = (f" A further {small:,} {_place_word(cfg, plural=small != 1)} had fewer than "
                f"{MIN_CITY_HUB} {cfg['things']} and are not broken out here, rather than "
                f"published as near-empty pages." if small else "")
    faq = [(f"How many {cfg['things']} in {cfg['name']} does this index list?",
            f"{n:,} {cfg['things']} across {places} {_place_word(cfg, plural=True)}, from "
            f"{copy['source']}.{left_off} {copy['caveat']}")]

    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    if len(ranked) >= 2:
        (top, top_n), (nxt, nxt_n) = ranked[0], ranked[1]
        lead = f"{'ZIP code ' if cfg['path'] == 'zip' else ''}{top}"
        faq.append((f"Which {_place_word(cfg)} in {cfg['name']} has the most {cfg['things']}?",
                    f"{lead}, with {top_n:,} of the {n:,} {cfg['things']} listed here "
                    f"({top_n * 100.0 / n:.1f}%). "
                    f"{'ZIP code ' if cfg['path'] == 'zip' else ''}{nxt} follows with {nxt_n:,}. "
                    f"That is where this dataset records them, which is not the same as where "
                    f"every regulated unit in {cfg['name']} is."))

    # The third question is whichever city-wide statistic that city's data
    # actually carries. Not one template: build year is the near-test in SF and
    # LA and is the wrong frame in DC, where coverage turns on registration and
    # a pre-1976 build, and where the filings carry a reported rent instead.
    if key in ("sf", "la") and agg["yr"]:
        faq.append((f"How old are the {cfg['things']} in this index?",
                    f"The median build year across the {len(agg['yr']):,} with a recorded year is "
                    f"{_med(agg['yr'])}. Build year is what the assessor recorded; the ordinance "
                    f"turns on when the certificate of occupancy was issued, so treat it as an "
                    f"indication rather than a ruling."))
    elif key == "dc" and len(agg["mr"]) >= MIN_CITY_HUB:
        faq.append(("What rent is reported for rent-controlled units in Washington DC?",
                    f"The median rent reported to the Rental Accommodations Division across the "
                    f"{len(agg['mr']):,} properties in this index that reported one is "
                    f"${_med(agg['mr']):,}. That is what housing providers filed, not the market "
                    f"rent and not what a specific unit will cost."))
    return faq


def city_hub_docs(key, guide_ok=True):
    """Render one city's aggregate hub tier. Returns a list of page dicts.

    Each dict is {kind, relpath, canonical, html, priority}: kind "place" for
    the per-neighborhood / per-ZIP pages and "browse" for the single hub that
    links them all. Returns [] when the city's data is unreadable or no place
    clears MIN_CITY_HUB — a city with nothing to say publishes nothing.

    These are deliberately not building-level pages. SF is anonymized to the
    block and LA is a derived "likely RSO" list, so the honest unit of
    publication for those two is the aggregate, and a per-address page would
    assert more than the data supports.

    Lifted out of city_hub_pages() for the same reason guide_page() was lifted
    out of main(): the daily growth build (growth/techniques.py:
    t_city_seo_expansion) publishes this tier through its own rsync when this
    pipeline has not deployed it, and two independent renderers would overwrite
    each other's bytes every night, churning lastmod on pages that never
    changed. Import this; do not copy it.

    guide_ok=False drops the "is my apartment rent controlled in <city>?" link.
    The growth build passes False when that guide is not live: these pages are
    the contextual path into the guides, and a hub tier does not ship pointing
    at a 404.
    """
    cfg = CITY_HUBS[key]
    try:
        recs = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           key, "buildings.min.json")))
    except Exception as e:
        print(f"city hubs: skipping {key} ({e})")
        return []

    groups = defaultdict(list)
    for r in recs:
        g = r.get(cfg["group"])
        if g not in (None, ""):
            groups[str(g)].append(r)
    big = {k: sorted(v, key=lambda x: x.get("a") or "")
           for k, v in groups.items() if len(v) >= MIN_CITY_HUB}
    if not big:
        return []
    small = len(groups) - len(big)
    city, footer = cfg["name"], CITY_FOOTER[key]
    browse_url = f"/{key}/buildings/"
    counts = {k: len(v) for k, v in big.items()}
    others = [(o, CITY_HUBS[o]) for o in CITY_HUBS if o != key]
    guide_link = (f"<p><a href='/guide/{cfg['guide']}/'>Read: is my apartment rent controlled "
                  f"in {esc(city)}? →</a></p>") if guide_ok else ""

    docs = []
    for place, items in sorted(big.items()):
        slug = place if cfg["path"] == "zip" else slugify(place)
        url = f"/{key}/{cfg['path']}/{slug}/"
        canonical = SITE + url
        st = _city_stats(items)
        h1 = cfg["h1"].format(place=place)

        labels = _city_labels(key, items)
        listing = ""
        if labels:
            shown = labels[:CITY_LIST_CAP]
            # State the cap rather than truncating quietly: a list that
            # silently stops at 300 reads as "this is all of them".
            count = (f"{len(labels):,} distinct, showing the first {len(shown):,}."
                     if len(labels) > len(shown) else
                     f"{len(labels):,} distinct.")
            listing = (f"<h2>{esc(cfg['list_h2'].format(place=place))}</h2>"
                       f"<p class='disclaimer'>{esc(count)} {esc(cfg['list_note'])}</p>"
                       f"<div class='cols'>"
                       + "".join(f"<span>{esc(a)}</span>" for a in shown)
                       + "</div>")

        extra = _decade_table(items) if key == "la" else _band_table(items, cfg["things"])
        sibs = "".join(
            f"<a href=\"/{key}/{cfg['path']}/"
            f"{p if cfg['path'] == 'zip' else slugify(p)}/\">{esc(p)} ({c:,})</a>"
            for p, c in sorted(counts.items(), key=lambda kv: -kv[1])[:12] if p != place)
        body = (f"<div class='crumbs'><a href='/'>Home</a> › "
                f"<a href='/{key}/'>{esc(city)}</a> › "
                f"<a href='{browse_url}'>All {esc(cfg['things'])}</a></div>"
                f"<h1>{esc(h1)}</h1>"
                + answer_block(_city_answer(key, place, st))
                + f"<a class='cta' href='/{key}/'>Open the {esc(city)} map →</a>"
                + _city_stat_table(key, st) + extra
                + guide_link
                + listing
                + (f"<h2>Nearby in {esc(city)}</h2><div class='cols'>{sibs}</div>"
                   f"<p><a href='{browse_url}'>All {esc(cfg['things'])} in {esc(city)} →</a></p>"
                   if sibs else ""))
        faq = _city_faq(key, place, st)
        body += faq_html(faq)
        crumb = breadcrumb([("Home", SITE + "/"), (city, SITE + f"/{key}/"),
                            (h1, canonical)])
        docs.append({
            "kind": "place", "relpath": url.strip("/") + "/index.html",
            "canonical": canonical, "priority": "0.7",
            "html": page(f"{h1} ({st['n']}) | Find A Crib",
                         f"{st['n']} {cfg['things']} in {place}, {city} — counts, unit sizes and "
                         f"what rent regulation there actually means. Check any address on the map.",
                         canonical, body, [crumb, faq_jsonld(faq)], footer=footer)})

    # ---- the city's browse hub: the page that makes the rest non-orphans
    total_places = len(big)
    total_recs = sum(counts.values())
    links = "".join(
        f"<a href=\"/{key}/{cfg['path']}/"
        f"{p if cfg['path'] == 'zip' else slugify(p)}/\">{esc(p)} ({c:,})</a>"
        for p, c in sorted(counts.items()))
    # Reworded when the count sentence moved into the answer block above: "N
    # more" had an antecedent while this opened with the total and has none now.
    skipped = (f"{small} {_place_word(cfg, plural=small != 1)} with fewer than {MIN_CITY_HUB} "
               f"{cfg['things']} were left off rather than published as near-empty pages. "
               if small else "")
    # The browse hub is the highest-priority page in this tier (0.9) and the one
    # the guides, the other cities and the voucher cross-link all point at, but
    # until 2026-08-09 it was the only page here with no extractable answer and
    # no FAQ — the pattern that holds the site's best measured position. The
    # count sentence moved out of the lead and into the answer block rather than
    # being repeated in both: two adjacent paragraphs saying the same number is
    # the boilerplate this tier does not need.
    agg = _city_stats([x for v in big.values() for x in v])
    browse_faq = _city_browse_faq(key, cfg, total_recs, total_places, small, counts, agg)
    body = (f"<div class='crumbs'><a href='/'>Home</a> › <a href='/{key}/'>{esc(city)}</a></div>"
            f"<h1>{esc(cfg['browse_h1'])}</h1>"
            + answer_block(_city_browse_answer(key, cfg, total_recs, total_places, agg))
            + f"<p class='lead'>{esc(skipped)}Start with your "
            f"{'ZIP code' if cfg['path'] == 'zip' else 'neighborhood'}, or "
            f"<a href='/{key}/'>open the map</a>.</p>"
            + guide_link
            + f"<div class='cols'>{links}</div>"
            + "<h2>Other cities on Find A Crib</h2><div class='cols'>"
            + "<a href='/buildings/'>New York City by neighborhood</a>"
            + "".join(f"<a href='/{o}/buildings/'>{esc(oc['browse_h1'])}</a>"
                      for o, oc in others)
            + "</div>"
            + CITY_VOUCHER_XLINK.format(city=esc(city))
            + faq_html(browse_faq))
    crumb = breadcrumb([("Home", SITE + "/"), (city, SITE + f"/{key}/"),
                        (cfg["browse_h1"], SITE + browse_url)])
    docs.append({
        "kind": "browse", "relpath": browse_url.strip("/") + "/index.html",
        "canonical": SITE + browse_url, "priority": "0.9",
        "html": page(f"{cfg['browse_h1']} | Find A Crib",
                     f"Browse {total_recs:,} {cfg['things']} across {total_places} "
                     f"{'ZIP codes' if cfg['path'] == 'zip' else 'neighborhoods'} in {city}.",
                     SITE + browse_url, body, [crumb, faq_jsonld(browse_faq)], footer=footer)})
    return docs


COUNCIL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "council_districts.json")
COUNCIL_SOURCE = ("Council district boundaries: NYC Open Data 872g-cjhh. Sitting members: "
                  "NYC Open Data uvw5-9znb. Violations and complaints: HPD via NYC Open Data, "
                  "counted from HPD's own Open/Close flag.")


def council_url(d):
    return f"/council-district/{d}/"


def council_district_pages(urls):
    """A hub per NYC City Council district. Returns the district records used.

    Every other hub axis on this site — borough, neighborhood, ZIP — restates a
    geography somebody with more authority already publishes. A council district
    is the one unit of NYC geography where this data answers a question nobody
    else answers and a named officeholder has a standing reason to cite the
    answer. That is the difference between a page worth publishing and a page
    worth linking to.

    Returns [] when council_districts.json is missing (build_council.py owns it),
    so a checkout without the join still builds the rest of the site.
    """
    try:
        with open(COUNCIL_PATH) as f:
            data = json.load(f)
    except Exception as e:
        print(f"council districts: skipping ({e})")
        return []
    districts = data.get("districts") or {}
    if not districts:
        return []

    recs = sorted(districts.values(), key=lambda d: d["district"])
    ranked = sorted(recs, key=lambda d: -d["open_violations"])
    rank_of = {d["district"]: i + 1 for i, d in enumerate(ranked)}
    n_d = len(recs)

    for d in recs:
        num = d["district"]
        url = council_url(num)
        canonical = SITE + url
        member = d.get("member")
        who = (f"District {num} is represented by {member}."
               if member else
               f"District {num} has no sitting member on the Council's own roster.")
        boros = ", ".join(BORO_NAME.get(b, b) for b in d.get("boroughs") or [])
        clean = d["buildings_no_open_violations"]
        rank = rank_of[num]

        facts = [
            ("Rent-stabilized buildings", f"{d['buildings']:,}"),
            ("Apartments in them", f"{d['units']:,}" if d["units"] else "—"),
            ("Median year built", str(d["median_year"]) if d["median_year"] else "—"),
            ("Open HPD violations", f"{d['open_violations']:,}"),
            ("Of those, immediately hazardous (class C)", f"{d['open_class_c']:,}"),
            ("Buildings with no open violation", f"{clean:,} of {d['buildings']:,}"),
            ("Open HPD complaints", f"{d['open_complaints']:,}"),
        ]
        table = "".join(f"<tr><td class='k'>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in facts)

        owners = d.get("top_owners") or []
        if owners:
            rows = "".join(
                f"<tr><td>{esc(o['name'])}</td><td>{o['buildings']:,}</td>"
                f"<td>{o['units']:,}</td><td>{o['open_violations']:,}</td></tr>"
                for o in owners)
            owner_html = (
                f"<h2>The largest violation records in District {num}</h2>"
                f"<table class='facts'><tr><th>Owner or managing agent (HPD registration)</th>"
                f"<th>Buildings</th><th>Units</th><th>Open violations</th></tr>{rows}</table>"
                f"<p class='note'>Ranked by open HPD violations across the stabilized buildings "
                f"they have registered in this district, counting only owners with three or more. "
                f"HPD registration names the party responsible for the registration, which is not "
                f"always the beneficial owner.</p>")
        else:
            owner_html = ""

        nbs = (d.get("neighborhoods") or [])[:24]
        nb_html = ("<h2>Neighborhoods in this district</h2><div class='cols'>"
                   + "".join(f"<span>{esc(n)}</span>" for n in nbs) + "</div>") if nbs else ""

        per_bld = (d["open_violations"] / d["buildings"]) if d["buildings"] else 0
        body = (
            f"<div class='crumbs'><a href='/'>Home</a> › "
            f"<a href='/council-district/'>Council districts</a></div>"
            f"<h1>Rent-stabilized housing in NYC Council District {num}</h1>"
            + answer_block([
                f"NYC Council District {num} contains {d['buildings']:,} rent-stabilized "
                f"buildings registered with New York State DHCR"
                + (f", covering {d['units']:,} apartments" if d["units"] else "") + ".",
                f"HPD has {d['open_violations']:,} open violations against them, "
                f"{per_bld:.1f} per building, {d['open_class_c']:,} of them class C — the "
                f"immediately hazardous grade a landlord has 24 hours to fix.",
                (f"That is the largest open count of the {n_d} districts; " if rank == 1 else
                 f"That is the smallest open count of the {n_d} districts; " if rank == n_d else
                 f"That is the {ordinal(rank)}-largest open count of the {n_d} districts; ")
                + f"{clean:,} buildings here have none.",
                who,
            ])
            + f"<a class='cta' href='/'>Open the map →</a>"
            + f"<h2>The numbers</h2><table class='facts'>{table}</table>"
            + owner_html
            + nb_html
            + f"<p><a href='/council-district/'>Compare all {n_d} council districts →</a></p>"
        )
        faq = [
            (f"How many rent-stabilized buildings are in NYC Council District {num}?",
             f"{d['buildings']:,} buildings in Council District {num} are registered as rent "
             f"stabilized with New York State DHCR"
             + (f", covering {d['units']:,} apartments" if d["units"] else "") + "."),
            (f"How many open HPD violations are there in Council District {num}?",
             f"HPD has {d['open_violations']:,} open violations against the rent-stabilized "
             f"buildings in District {num}, {d['open_class_c']:,} of them class C — the "
             f"immediately hazardous grade. {clean:,} of the {d['buildings']:,} buildings "
             f"have no open violation at all."),
        ]
        if member:
            faq.append((f"Who represents NYC Council District {num}?",
                        f"{member}, according to the City Council's own roster of members."))
        body += faq_html(faq)
        crumb = breadcrumb([("Home", SITE + "/"),
                            ("Council districts", SITE + "/council-district/"),
                            (f"District {num}", canonical)])
        title = (f"Rent-stabilized buildings in NYC Council District {num}"
                 + (f" ({member})" if member else "") + " | Find A Crib")
        desc = (f"{d['buildings']:,} rent-stabilized buildings and {d['open_violations']:,} open "
                f"HPD violations in NYC Council District {num}"
                + (f", represented by {member}" if member else "") + ".")
        write(url.strip("/") + "/index.html",
              page(title, desc, canonical, body, [crumb, faq_jsonld(faq)],
                   footer=NYC_FOOTER + " " + COUNCIL_SOURCE))
        urls.append((canonical, "0.8", "council"))

    # ---- the index: all 51, ranked. This is the page meant to be cited. ----
    rows = "".join(
        f"<tr><td>{i + 1}</td><td><a href='{council_url(d['district'])}'>District "
        f"{d['district']}</a></td><td>{esc(d.get('member') or 'Vacant')}</td>"
        f"<td>{d['buildings']:,}</td><td>{d['units']:,}</td>"
        f"<td>{d['open_violations']:,}</td><td>{d['open_class_c']:,}</td></tr>"
        for i, d in enumerate(ranked))
    tot_b = sum(d["buildings"] for d in recs)
    tot_v = sum(d["open_violations"] for d in recs)
    tot_c = sum(d["open_class_c"] for d in recs)
    worst, best = ranked[0], ranked[-1]
    hub_body = (
        f"<div class='crumbs'><a href='/'>Home</a></div>"
        f"<h1>Rent-stabilized housing by NYC Council District</h1>"
        + answer_block([
            f"The {n_d} New York City Council districts contain {tot_b:,} DHCR-registered "
            f"rent-stabilized buildings, carrying {tot_v:,} open HPD violations, {tot_c:,} of "
            f"them class C — the immediately hazardous grade.",
            f"District {worst['district']} has the most open violations "
            f"({worst['open_violations']:,} across {worst['buildings']:,} buildings); "
            f"District {best['district']} the fewest ({best['open_violations']:,}).",
            "Council district is not a geography the housing portals publish, so these counts "
            "are not available elsewhere. Every figure is recomputed from the city's own open "
            "data on each build.",
        ])
        + f"<table class='facts'><tr><th>#</th><th>District</th><th>Council member</th>"
        f"<th>Buildings</th><th>Apartments</th><th>Open violations</th>"
        f"<th>Class C</th></tr>{rows}</table>"
        + f"<p class='note'>Ranked by open HPD violations. {COUNCIL_SOURCE} "
        f"Rebuilt {esc(data.get('generated', ''))}.</p>")
    hub_faq = [
        ("Which NYC Council district has the most open HPD violations in its rent-stabilized "
         "buildings?",
         f"District {worst['district']}"
         + (f", represented by {worst['member']}," if worst.get("member") else "")
         + f" has {worst['open_violations']:,} open HPD violations across its "
           f"{worst['buildings']:,} rent-stabilized buildings — the most of the {n_d} districts."),
        ("How many rent-stabilized buildings are there in New York City?",
         f"{tot_b:,} buildings across the {n_d} council districts are registered as rent "
         f"stabilized with New York State DHCR."),
    ]
    hub_body += faq_html(hub_faq)
    write("council-district/index.html",
          page(f"Rent-stabilized buildings and HPD violations by NYC Council District "
               f"| Find A Crib",
               f"All {n_d} NYC Council districts ranked by open HPD violations in their "
               f"rent-stabilized buildings — {tot_b:,} buildings, {tot_v:,} open violations.",
               SITE + "/council-district/", hub_body,
               [breadcrumb([("Home", SITE + "/"),
                            ("Council districts", SITE + "/council-district/")]),
                faq_jsonld(hub_faq)],
               footer=NYC_FOOTER + " " + COUNCIL_SOURCE))
    urls.append((SITE + "/council-district/", "0.9", "council"))
    return recs


# ---------------------------------------------------------------- index triage
# Measured 2026-08-27 by URL Inspection over a 450-URL sample of the 47,982
# published pages: 2 indexed, 80 crawled-and-declined, 44 discovered-never-
# crawled, 324 never discovered at all. Of the 37 URLs Google last fetched more
# than 21 days ago, ZERO are indexed. Nothing is blocked, noindexed, duplicated
# or mis-canonicalised — the markup is fine and always was.
#
# The finding that decides this function is the per-family split. Of 250 sampled
# building pages Google had fetched 55; of the guides, council districts,
# /section8/ and /brief/ it had fetched NOT ONE. The whole crawl allowance was
# going to a tier that is 53-71% identical page to page and converts at 1.8%,
# and the pages actually worth ranking had never been looked at.
#
# So the building tier stops being submitted wholesale. A page is promoted only
# if it can say something no template can generate:
#   * a unit in it is advertised right now      — live, changing, high intent
#   * 100+ open class-C violations              — immediately hazardous, citable
#   * 300+ apartments                           — among the largest in the city
# Everything else stays live, stays linked and stays useful to a person who
# lands on it, but carries noindex,follow and is left out of the sitemap.
# ~844 of 47,165 promoted. This is the "ship 50-100 high-conviction pages,
# validate, then scale" shape, and the ledger to widen it is accept_pct_mature
# in growth/index_status.json — not a hunch.
PROMOTE_CLASS_C = 100
PROMOTE_UNITS = 300


def promoted_building(b, advertised):
    """True if this building page earns a place in the sitemap."""
    if advertised:
        return True
    v = (b.get("h") or {}).get("violations") or {}
    if (v.get("oc") or 0) >= PROMOTE_CLASS_C:
        return True
    return (b.get("u") or 0) >= PROMOTE_UNITS


def ordinal(n):
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def city_hub_pages(urls):
    """Write every city's hub tier into this build. Returns {city: place count}."""
    built = {}
    for key in CITY_HUBS:
        docs = city_hub_docs(key)
        for d in docs:
            write(d["relpath"], d["html"])
            urls.append((d["canonical"], d["priority"], key))
        built[key] = sum(1 for d in docs if d["kind"] == "place")
    return built


def slugify(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-") or "x"


def esc(s):
    return html.escape(str(s if s is not None else ""))


# HPD and DHCR write addresses the way a clerk types them — "200 W 72ND ST" —
# and Search Console shows people typing the long form: "200 west 72", "228 e 3rd
# st ny", '"481 4th ave" "brooklyn ny"'. Those are the only non-brand queries this
# site has ever surfaced for, so the expanded forms belong on the page as visible
# text rather than left for a search engine to infer from an abbreviation.
ADDR_EXPAND = {
    "N": "North", "S": "South", "E": "East", "W": "West",
    "NE": "Northeast", "NW": "Northwest", "SE": "Southeast", "SW": "Southwest",
    "ST": "Street", "AVE": "Avenue", "AV": "Avenue", "RD": "Road", "DR": "Drive",
    "BLVD": "Boulevard", "PL": "Place", "PKWY": "Parkway", "CT": "Court",
    "LN": "Lane", "TER": "Terrace", "PLZ": "Plaza", "SQ": "Square",
    "HTS": "Heights", "EXPY": "Expressway", "CIR": "Circle", "BRDG": "Bridge",
}


def address_variants(raw, boro, zipc=None):
    """Other ways the same address gets typed. Empty when nothing expands.

    Returns at most three, deduped against the address as printed, because the
    point is to cover the abbreviation a searcher spelled out — not to stack
    every permutation into a keyword list.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    words = raw.split()
    expanded = [ADDR_EXPAND.get(w.upper(), w) for w in words]
    out = []
    long_form = titlecase_addr(" ".join(expanded))
    printed = titlecase_addr(raw)
    if long_form != printed:
        out.append(long_form)
    # the form people actually type into Google: address + borough, + ZIP when
    # we have one. Only one located variant — the same address twice with and
    # without a ZIP reads as padding, which is what it would be.
    located = f"{printed}, {boro}, NY" + (f" {zipc}" if zipc else "")
    out.append(located)
    seen, uniq = set(), []
    for v in out:
        if v and v not in seen and v != printed:
            seen.add(v)
            uniq.append(v)
    return uniq[:2]


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
header.site .cities{display:block;margin-top:5px;font-size:13px;color:var(--ink2)}
main{max-width:880px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:28px;line-height:1.2;margin:.2em 0 .4em}
h2{font-size:20px;margin:1.6em 0 .5em}
.lead{font-size:18px;color:var(--ink2)}
.aka{font-size:14px;color:var(--ink2);margin:-.4em 0 1em}
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
.guide-body p,.guide-body li{font-size:16px;line-height:1.6}
.guide-body ul{padding-left:20px}
.disclaimer{font-size:13px;color:var(--ink2);background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-top:10px}
.hook{background:#f0f5ff;border:1px solid #cfe0ff;border-radius:12px;padding:12px 14px;margin:12px 0;font-size:14px;line-height:1.5}
.answer{background:#fff;border:1px solid var(--line);border-left:3px solid var(--blue);border-radius:10px;padding:14px 16px;margin:14px 0}
.answer p{margin:0;font-size:16px;line-height:1.6}
.compare{background:#fff;border:1px solid var(--line);border-left:3px solid var(--blue);border-radius:10px;padding:14px 16px;margin:14px 0}
.compare p{margin:0;font-size:16px;line-height:1.6}
.faq-item{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.faq-item h3{font-size:15px;margin:0 0 4px}
.faq-item p{color:var(--ink2);font-size:14px;margin:0}
"""


# Same first-party pageview ping as index.html (public.visits), minus the
# supabase-js dependency: plain fetch with the anon key from /config.js.
# Cookie-first visitor id (nginx sets fac_vid; server-set cookies survive
# Safari's 7-day script-storage cap), localStorage fallback, bot guard, and
# the Supabase session token attached when one exists so user_id passes the
# "user_id = auth.uid()" RLS check (that mapping powers the owner-exclusion
# in traffic_report.py). Plain string on purpose: page() is an f-string and
# this JS is full of braces.
TRACK_SNIPPET = """<script src="/config.js"></script>
<script>
(function(){try{
  if(navigator.webdriver||/bot|crawl|spider|slurp|headless|lighthouse|prerender|facebookexternal/i.test(navigator.userAgent))return;
  if(!window.SUPABASE_URL||!window.SUPABASE_ANON_KEY)return;
  var m=document.cookie.match(/(?:^|;\\s*)fac_vid=([\\w-]+)/),vid=m?m[1]:null;
  if(!vid){try{vid=localStorage.getItem('fac_vid')}catch(e){}}
  if(!vid)vid=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():'v'+Date.now().toString(36)+Math.random().toString(36).slice(2);
  try{localStorage.setItem('fac_vid',vid)}catch(e){}
  var tok=null,uid=null;
  try{
    var ref=window.SUPABASE_URL.split('//')[1].split('.')[0];
    var s=JSON.parse(localStorage.getItem('sb-'+ref+'-auth-token'));
    if(s&&s.access_token&&(s.expires_at||0)*1000>Date.now()+60000){tok=s.access_token;uid=(s.user&&s.user.id)||null}
  }catch(e){}
  fetch(window.SUPABASE_URL+'/rest/v1/visits',{method:'POST',keepalive:true,
    headers:{apikey:window.SUPABASE_ANON_KEY,'Authorization':'Bearer '+(tok||window.SUPABASE_ANON_KEY),
             'Content-Type':'application/json','Prefer':'return=minimal'},
    body:JSON.stringify({visitor_id:vid,user_id:uid,path:location.pathname+location.search,referrer:document.referrer||null})});
}catch(e){}})();
</script>"""


# The data-provenance footer. Every page states where its numbers came from,
# and a page outside New York must not claim New York sources: the NYC footer
# names DHCR, PLUTO and HPD, none of which have anything to do with a San
# Francisco block or a Los Angeles parcel. Pages pass their own footer; the
# NYC one stays the default because it is the overwhelming majority.
# ---- schema.org/Dataset -------------------------------------------------
# Google Dataset Search, and the LLM crawlers that increasingly follow it, index
# schema.org/Dataset. The corpus genuinely is one — every NYC building DHCR has
# on the rent-stabilization rolls — but only the pages that present a
# *collection* are allowed to say so. A single address is not a dataset; see the
# note where the building pages pick ApartmentComplex instead.
#
# Every field below has to be true or the markup is worse than none: Dataset
# Search shows description, coverage and distribution verbatim to people
# deciding whether to trust the data. Two deliberate omissions:
#   - no `license`. The underlying records are public NY State and NYC data, but
#     stamping a licence on the derived corpus is a legal claim, and /terms.html
#     is a terms-of-use page, not a licence. `conditionsOfAccess` says what is
#     actually true instead.
#   - no `datePublished` on the slices. The DHCR file is annual; a per-page
#     publish date would imply a freshness the rolls do not have.
DATA_CATALOG = {
    "@type": "DataCatalog",
    "@id": SITE + "/developers/#catalog",
    "name": "Find A Crib rent-regulation data",
    "url": SITE + "/developers/",
}
# The variables actually present in buildings.min.json + the HPD join.
DATA_VARIABLES = ["Street address", "Borough", "Neighborhood (NTA)", "ZIP code",
                  "Borough-Block-Lot (BBL)", "Latitude", "Longitude", "Year built",
                  "Apartment count", "DHCR stabilization code", "Registered owner",
                  "HPD-registered managing agent", "Open HPD violations",
                  "Open HPD complaints"]


def dataset_jsonld(name, description, url, spatial, size=None, part_of_catalog=True):
    """A Dataset node for a page that presents a collection of buildings.

    `size` is the building count, published as a QuantitativeValue so a consumer
    can see the slice's scale without downloading 16 MB to find out.
    """
    d = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": name,
        "description": description,
        "url": url,
        "isAccessibleForFree": True,
        "creator": {"@type": "Organization", "name": "Find A Crib", "url": SITE + "/"},
        # Provenance, not decoration: these are the agencies whose records this
        # is derived from, and the reason the data can be trusted at all.
        "sourceOrganization": [
            {"@type": "GovernmentOrganization",
             "name": "New York State Division of Housing and Community Renewal"},
            {"@type": "GovernmentOrganization", "name": "NYC Department of City Planning"},
            {"@type": "GovernmentOrganization",
             "name": "NYC Department of Housing Preservation and Development"},
        ],
        "temporalCoverage": "2024",
        "spatialCoverage": spatial,
        "variableMeasured": DATA_VARIABLES,
        "conditionsOfAccess":
            "Free to read on the site. Bulk JSON is public; the REST API requires a free key.",
        "distribution": [
            {"@type": "DataDownload",
             "name": "Bulk JSON — every registered building",
             "encodingFormat": "application/json",
             "contentUrl": SITE + "/buildings.min.json"},
            {"@type": "DataDownload",
             "name": "REST API (free key required)",
             "encodingFormat": "application/json",
             "contentUrl": SITE + "/api/v1/buildings"},
        ],
    }
    if size:
        d["size"] = {"@type": "QuantitativeValue", "value": size,
                     "unitText": "buildings"}
    if part_of_catalog:
        d["includedInDataCatalog"] = DATA_CATALOG
    return d


NYC_FOOTER = """Data: NYC DHCR 2024 rent-stabilized building files, NYC PLUTO (coordinates),
and NYC HPD Open Data (owner, violations, complaints). A building's rent-stabilized status reflects
DHCR registration; it is not a guarantee that a specific unit is available or currently stabilized."""

CITY_FOOTER = {
    "sf": """Data: San Francisco Rent Board housing inventory — units their owners reported
as rent controlled, published anonymized to the block rather than the individual address, plus
San Francisco Assessor build years. Coverage reflects what owners reported; it is not a
determination that a specific unit is rent controlled.""",
    "la": """Data: Los Angeles County Assessor parcel records, filtered to the Rent
Stabilization Ordinance criteria (two or more units, built before 1 October 1978). This is a
derived list labelled "likely RSO" — it is not the City of Los Angeles's official RSO inventory,
which LAHD holds. Verify an address with LAHD or on ZIMAS before relying on it.""",
    "dc": """Data: District of Columbia Rental Accommodations Division registration and
exemption filings (RentRegistry). A property appears here because its housing provider filed it as
covered by rent control; registration is per property, and a unit its provider never registered is
generally treated as covered rather than exempt.""",
}


# The three non-NYC city hubs, linked from the header of every page this
# pipeline writes. Two reasons, and the second one is the measured one.
#
# For a reader: a Brooklyn address page offered exactly two onward links —
# "All neighborhoods" and "Guides" — and no route at all to the other three
# cities this site covers. Someone reading about a Bed-Stuy building because
# they are moving to LA had nowhere to go.
#
# For crawling: /building/ is the ONLY tier Googlebot is currently fetching —
# on 2026-08-18 it was 51 of the 65 fetched URLs in the sampled cohort, with
# fresh crawls on 08-16, 08-17 and 08-18, while /dc/ and /la/ had never been
# fetched at all and /sf/ not since 07-28. The root index.html has linked all
# three from its city nav for weeks and Google has not followed it, so this is
# not a new signal — it is the same signal from 47,165 pages instead of one,
# which is a different weight rather than a different idea. Judge it on
# index_fetched_pct for the dc/la/sf families (growth/indexstatus.py), not on
# traffic, and give it a fortnight: at 1-5 fetches a night the crawler needs
# time to arrive. If those families are still 0% fetched in two weeks, link
# volume is not the constraint and the next thing to suspect is site-level
# crawl rationing, which no amount of internal linking fixes.
#
# Anchor text is the wording the homepage already uses for these three, which
# is accurate for each: SF and DC are rent CONTROL registries, LA is the RSO.
# The coverage caveats — LA derived and "likely RSO", SF anonymized to the
# block — live on the hub pages themselves, which is where a caveat belongs;
# naming a destination is not asserting a claim about its contents.
CITY_NAV = (
    '<span class="cities">Also mapped: '
    '<a href="/sf/">rent-controlled San Francisco</a> &nbsp;·&nbsp; '
    '<a href="/la/">rent-stabilized (RSO) Los Angeles</a> &nbsp;·&nbsp; '
    '<a href="/dc/">rent-controlled Washington DC</a></span>')


def page(title, desc, canonical, body, jsonld=None, footer=None, robots=None):
    ld = ""
    if jsonld:
        ld = '<script type="application/ld+json">%s</script>' % json.dumps(jsonld)
    # `robots` is only ever set to noindex,follow, and only on the building tier
    # that index_triage() declines to promote — see the note there. follow, not
    # nofollow, because the page still passes a reader and a crawler onward to
    # the neighbourhood and borough hubs, which is the tier we want crawled.
    rb = f'<meta name="robots" content="{robots}">' if robots else ""
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">{rb}
<link rel="canonical" href="{canonical}">
<link rel="icon" href="/favicon.ico" sizes="any">
<meta property="og:type" content="website"><meta property="og:site_name" content="Find A Crib">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canonical}"><meta property="og:image" content="{SITE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<style>{CSS}</style>{ld}</head><body>
<header class="site"><a class="brand" href="/">🏠 Find A Crib</a> &nbsp;·&nbsp;
<a href="/buildings/">All neighborhoods</a> &nbsp;·&nbsp;
<a href="/guide/">Guides</a>{CITY_NAV}</header>
<main>{body}</main>
<footer class="site">{footer or NYC_FOOTER}
&copy; Find A Crib. <a href="/">Open the interactive map →</a></footer>
{TRACK_SNIPPET}
</body></html>"""


def _lastmod_body(contents):
    """The part of a page whose change means the page changed.

    lastmod is a promise to a crawler that the *content* moved. The stylesheet
    is inlined into all 47,596 pages, so adding one CSS rule rewrites every
    file byte-for-byte and — hashing the whole document — would bump every
    lastmod on the site to today. Mass-bumping lastmod on a corpus that did not
    change is precisely the signal Google learns to distrust, and it would have
    buried the few hundred pages that genuinely did change.

    So the hash covers everything except the <style> block.
    """
    return re.sub(r"<style>.*?</style>", "", contents, flags=re.S)


def write(relpath, contents):
    full = os.path.join(OUT, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(contents)
    # track lastmod for crawlable HTML pages (…/index.html) only
    if relpath.endswith("index.html"):
        loc = SITE + "/" + relpath[:-len("index.html")]  # …/foo/index.html -> …/foo/
        h = hashlib.sha1(_lastmod_body(contents).encode("utf-8")).hexdigest()
        prev = LM_STATE.get(loc)
        if prev and prev.get("h") == h:
            lastmod = prev["m"]                 # unchanged -> keep old date (honest)
        else:
            lastmod = BUILD_DATE                # new or changed -> bump
            if prev is not None:
                LM_CHANGED.append(loc)          # changed (not brand-new) -> ping IndexNow
        LM_NEW[loc] = {"h": h, "m": lastmod}
        LASTMOD[loc] = lastmod


def guide_page(g, browse_ok=True):
    """Render one cornerstone guide from seo_guides.GUIDES. Returns (canonical, html).

    Lifted out of main() so there is exactly one renderer for these pages. The
    daily growth build (growth/techniques.py:t_city_guides) publishes a guide
    through its own rsync when this pipeline has not deployed it — on
    2026-08-02 the SF/LA/DC guides had been sitting in git for four days — and
    two independent renderers would overwrite each other's bytes every night,
    churning lastmod on a page that never changed. Import this; do not copy it.

    browse_ok=False drops the "browse this city" link. The growth build passes
    False when /<city>/buildings/ is not live in the docroot: a cornerstone page
    is a trust page, and it does not ship pointing at a 404.
    """
    canonical = SITE + f"/guide/{g['slug']}/"
    crumb = breadcrumb([("Home", SITE + "/"), ("Guides", SITE + "/guide/"), (g["h1"], canonical)])
    # Article schema helps these rank as informational content.
    article = {"@context": "https://schema.org", "@type": "Article",
               "headline": g["title"], "description": g["desc"],
               "mainEntityOfPage": canonical, "author": {"@type": "Organization", "name": "Find A Crib"},
               "publisher": {"@type": "Organization", "name": "Find A Crib",
                             "logo": {"@type": "ImageObject", "url": SITE + "/icon-512.png"}}}
    gcity = g.get("city", "nyc")
    # A guide about San Francisco footed "Data: NYC DHCR…" is simply wrong,
    # and these three shipped that way on 2026-07-29. Each non-NYC guide now
    # carries its own city's provenance, and links into that city's browse
    # tier — the contextual link the new hubs need to not be orphans.
    body = (f"<div class='crumbs'><a href='/'>Home</a> › <a href='/guide/'>Guides</a> › {esc(g['h1'])}</div>"
            f"<h1>{esc(g['h1'])}</h1>"
            f"<div class='guide-body'>{g['body']}</div>"
            + (f"<p><a href='/{gcity}/buildings/'>Browse "
               f"{esc(CITY_HUBS[gcity]['browse_link_text'])} →</a></p>"
               if browse_ok and gcity in CITY_HUBS else "")
            + _related(g["slug"], GUIDES))
    return canonical, page(g["title"] + " | Find A Crib", g["desc"], canonical, body,
                           [article, crumb], footer=CITY_FOOTER.get(gcity))


# --- the sibling-link ring on building pages -------------------------------
# Every building page carries a short list of other stabilized buildings in the
# same neighborhood. Until 2026-08-13 that list was `sorted_by_address[:12]`,
# recomputed identically on every page in the neighborhood — so it was a STAR,
# not a mesh: in Bushwick (West) the same 13 addresses collected 1,196 inbound
# links each and the other 1,184 building pages had exactly one inbound link on
# the whole site, their neighborhood hub. Measured over buildings.min.json:
# 44,738 of 47,165 building pages (94.9%) had two or fewer inbound internal
# links, 11,294 had exactly one, and only 2,430 buildings — 5.2% — were ever
# linked from a sibling page. Google will not crawl 47,600 pages it reaches
# only through 198 hub pages carrying up to 1,197 links each, and 66 pages
# earning a Search Console impression is what that looks like from outside.
#
# A window that follows the page's own position turns the star into a ring:
# every page links to the NEAR_LINKS entries around it, so every page is also
# linked FROM that many, and the neighborhood becomes one connected cycle a
# crawler can walk. In-degree goes from {1 for 94.9%, ~n for 13} to a flat 12.
#
# Ordered geographically rather than alphabetically, because the same window
# then reads as a real neighbour list to a human: addresses sort lexically
# ("1180 Gerard" next to "119 E 149th"), which is nothing to a reader, while a
# snaked column sort puts physically adjacent buildings next to each other.
# The heading stays "Other rent-stabilized buildings in <neighborhood>" — a
# claim the ordering cannot falsify — rather than "nearby", which a snake's
# column boundaries would occasionally make untrue.
#
# Deterministic, and no randomness anywhere: seo_lastmod.json only bumps a
# page's <lastmod> when its HTML really changed, so a shuffled list would
# rewrite 47,165 lastmods every night and turn that honesty into noise. This
# does change every building page once, which is a real change and an honest
# one-time bump.
NEAR_LINKS = 12
GEO_COL_DEG = 0.0035   # ~295 m of longitude at NYC's latitude


def _geo_ring_order(items):
    """One neighborhood's buildings, ordered so consecutive entries are close.

    Snaked column sort: bucket by longitude into ~295 m columns, then sort by
    latitude, alternating direction column to column so the end of one column
    is adjacent to the start of the next instead of diagonally across the
    neighborhood. Buildings with no coordinates sort last, by address, so they
    still take part in the ring. BBL breaks every tie, so the order is stable
    across runs.
    """
    def key(x):
        lat, lng = x.get("lat"), x.get("lng")
        if lat is None or lng is None:
            return (1, 0, 0.0, x.get("a") or "", str(x["bbl"]))
        col = int(math.floor(lng / GEO_COL_DEG))
        return (0, col, lat if col % 2 == 0 else -lat, x.get("a") or "", str(x["bbl"]))
    return sorted(items, key=key)


def _ring_window(order, i, k=NEAR_LINKS):
    """The k entries around position i in `order`, wrapping, excluding i itself.

    Half before and half after, so the lists of adjacent buildings overlap and
    the ring is walkable in both directions. With len(order) <= k the window is
    simply every other building in the neighborhood, which is what the old
    slice already did for small neighborhoods.
    """
    n = len(order)
    if n <= 1:
        return []
    if n <= k + 1:
        return [x for j, x in enumerate(order) if j != i]
    half = k // 2
    offsets = list(range(-half, 0)) + list(range(1, k - half + 1))
    return [order[(i + o) % n] for o in offsets]


# ---- computed per-building facts (T046) ------------------------------------
# The building tier is the only one Googlebot fetches in any volume — 51 of the
# 65 ever-fetched URLs in the 2026-08-18 index sample were /building/ — and it
# is also the tier Google is rejecting: 2 of the 71 URLs fetched since
# 2026-07-01 were kept, and on 2026-08-19/20 two pages that had been indexed
# since June were re-crawled and came back "Crawled - currently not indexed".
#
# The reason is visible in the generator above. A building page is a template
# with six variable tokens — address, ZIP, neighborhood, year built, unit count,
# violation count — and every other word on it is identical 47,165 times over.
# That is the documented shape of a corpus that gets crawled and dropped.
#
# So these sentences add text, and deliberately not the SAME text: every one of
# them carries a number computed for THIS building against the neighborhood it
# sits in, and a building with no such number gets no sentence rather than a
# filler one. Four rules keep it honest, because a tenant makes a housing
# decision on this page:
#
#   - Every comparison names its base set. "larger than 78% of the 1,204
#     rent-stabilized buildings this site tracks in Chelsea-Hudson Yards" is a
#     claim the dataset supports; "larger than 78% of buildings in Chelsea" is
#     not, because the base is DHCR-registered stabilized buildings only.
#   - Ties belong to neither side of a percentile. Hundreds of buildings in a
#     neighborhood share a unit count, so "larger than X%" counts only the ones
#     strictly smaller and "smaller than Y%" only the ones strictly larger.
#   - The HPD class counters count only violations whose class field is literally
#     A, B or C, while `total` counts every row (fetch_hpd.fetch_violations) —
#     a+b+c falls short of total for 33,218 of the 46,245 buildings that have
#     any. So the class sentence says "N of the M violations on record are class
#     C" and never implies what the other M-N are.
#   - Fewer than FACTS_MIN_SENTENCES computable sentences and the block is
#     omitted outright. A page with nothing to say should say nothing.
FACTS_MIN_SENTENCES = 3
FACTS_MAX_SENTENCES = 5
# PLUTO records a placeholder year for buildings whose date it does not know;
# 218 rows sit below this line and none of them should produce a date sentence.
PLUTO_MIN_YEAR = 1850
# Below this many buildings a neighborhood percentile is noise, not a comparison.
FACTS_MIN_BASE = 20


def _count_below_above(sorted_vals, v):
    """(count strictly below v, count strictly above v) within a sorted list."""
    if not sorted_vals:
        return None, None
    return (bisect.bisect_left(sorted_vals, v),
            len(sorted_vals) - bisect.bisect_right(sorted_vals, v))


def _floor_pct(part, whole):
    """Percent, rounded DOWN.

    Rounding to nearest turned 499 of 500 into "larger than 100% of the 500
    buildings this site tracks", which is false on its face — the page cannot be
    larger than itself. A share quoted about the reader's own building has to
    round in the direction that keeps it true.
    """
    return int(math.floor(100.0 * part / whole)) if whole else 0


def neighborhood_norms(items):
    """The comparison base for one (borough, neighborhood) group.

    Computed once per group and shared by every building page in it — 198 groups
    against 47,165 pages — so the per-page cost is a dict lookup and a bisect.
    """
    units = sorted(x["u"] for x in items if x.get("u"))
    years = sorted(x["yr"] for x in items if (x.get("yr") or 0) >= PLUTO_MIN_YEAR)
    rates = [(((x.get("h") or {}).get("violations") or {}).get("open") or 0) / x["u"]
             for x in items if x.get("u")]
    rates.sort()
    # `clean` counts every tracked building with no open violation on file,
    # including the ones with no unit count — the claim it backs is about the
    # neighborhood, not about the subset that happens to have a denominator.
    clean = sum(1 for x in items
                if not (((x.get("h") or {}).get("violations") or {}).get("open") or 0))
    return {"n": len(items), "units": units, "unit_med": _med(units),
            "year_med": _med(years), "rate_med": _med(rates), "rate_n": len(rates),
            "clean": clean}


def _rate_phrase(rate):
    """A violations-per-apartment rate in words that never round to nothing.

    "{rate:.1f} per apartment" reads as "0.0 per apartment" for a 198-unit
    building with 8 open violations — a sentence that contradicts its own first
    half and reads as "none" to someone deciding whether to take the apartment.
    Below one violation per two apartments the honest form is the reciprocal.
    Callers guarantee rate > 0.
    """
    if rate >= 0.5:
        return f"{rate:.1f} per apartment"
    return f"one for every {max(2, int(round(1 / rate))):,} apartments"


# Sentences are written with {PLACE} and resolved by _name_place(): the full
# neighborhood name the first time, "the neighborhood" after that. Some of these
# names are four hyphenated neighborhoods long, and repeating
# "Carroll Gardens-Cobble Hill-Gowanus-Red Hook" three times in one paragraph
# reads like a template filling itself in, which is the impression this block
# exists to undo.
def _name_place(sentences, nb):
    out, seen = [], False
    for s in sentences:
        if "{PLACE}" in s and seen:
            out.append(s.replace("{PLACE}", "the neighborhood"))
        else:
            if "{PLACE}" in s:
                seen = True
            out.append(s.replace("{PLACE}", nb))
    return out


def building_facts(b, nb, norms):
    """Sentences about THIS building that no other page on the site repeats.

    Each sentence carries its own number, comparison and source, because the
    point is to be liftable one sentence at a time by an answer engine, not only
    readable in place.
    """
    out = []
    h = b.get("h") or {}
    v = h.get("violations") or {}
    cm = h.get("complaints") or {}
    units = b.get("u")
    yr = b.get("yr") if (b.get("yr") or 0) >= PLUTO_MIN_YEAR else None
    big_enough = norms.get("n", 0) >= FACTS_MIN_BASE

    # 1. size, against the stabilized buildings around it
    if units and big_enough and norms.get("units"):
        # The base is the buildings the percentile was actually computed over —
        # the ones with a unit count on file — not the whole neighborhood, or
        # the sentence quotes a denominator it did not use.
        peers = len(norms["units"])
        below, above = _count_below_above(norms["units"], units)
        base = f"the {peers:,} rent-stabilized buildings this site tracks in {{PLACE}}"
        # 184 rows in the registry carry a single unit, so "1 apartments" is a
        # real output, not a hypothetical. Every count in this block agrees with
        # its noun for the same reason.
        apts = f"{units:,} apartment{'' if units == 1 else 's'}"
        if below == peers - 1:
            out.append(f"With about {apts} it is the largest of {base}.")
        elif above == peers - 1:
            out.append(f"With about {apts} it is the smallest of {base}.")
        elif _floor_pct(below, peers) >= 60:
            out.append(f"With about {apts} it is larger than {_floor_pct(below, peers)}% of {base}.")
        elif _floor_pct(above, peers) >= 60:
            out.append(f"With about {apts} it is smaller than {_floor_pct(above, peers)}% of {base}.")
        elif norms.get("unit_med"):
            out.append(f"With about {apts} it sits near the middle of {base}, where the "
                       f"median building has {norms['unit_med']:,}.")

    # 2. age, against the same set
    if yr and big_enough and norms.get("year_med"):
        d = yr - norms["year_med"]
        if d <= -15:
            out.append(f"It went up in {yr}, {abs(d)} years before the {norms['year_med']} median "
                       f"for stabilized buildings tracked in {{PLACE}}.")
        elif d >= 15:
            out.append(f"It went up in {yr}, {d} years after the {norms['year_med']} median for "
                       f"stabilized buildings tracked in {{PLACE}}.")
        else:
            out.append(f"Its {yr} construction date sits close to the {norms['year_med']} median "
                       f"for stabilized buildings tracked in {{PLACE}}.")

    # 3. open violations per apartment — the number that varies most, and the
    #    one a tenant deciding about an address actually wants
    openv = v.get("open") or 0
    if units and big_enough and norms.get("rate_n", 0) >= FACTS_MIN_BASE \
            and norms.get("rate_med") is not None:
        med = norms["rate_med"]
        plural = "" if openv == 1 else "s"
        if openv and med <= 0:
            out.append(f"HPD lists {openv:,} open violation{plural} here, about "
                       f"{_rate_phrase(openv / units)}, in a neighborhood where the median "
                       f"tracked building has none open at all.")
        elif openv:
            rate = openv / units
            here, there = _rate_phrase(rate), _rate_phrase(med)
            rel = "above" if rate > med * 1.25 else "below" if rate < med * 0.8 else "close to"
            if rel == "close to" and here == there:
                out.append(f"HPD lists {openv:,} open violation{plural} here, about {here} — "
                           f"matching the median for tracked buildings in {{PLACE}}.")
            else:
                out.append(f"HPD lists {openv:,} open violation{plural} here, about {here} — "
                           f"{rel} the {there} median for tracked buildings in {{PLACE}}.")
        elif norms.get("clean"):
            # Counts, not a percentage: 1 clean building in 527 rounds to 0%,
            # and "0% of the tracked buildings" on a page that is itself one of
            # them contradicts its own first clause.
            out.append(f"HPD lists no open violations at this address — one of {norms['clean']:,} "
                       f"such buildings among the {norms['n']:,} this site tracks in {{PLACE}}.")

    # 4. how severe the record is, in HPD's own vocabulary
    total_v, cv = v.get("total") or 0, v.get("c") or 0
    if cv and total_v:
        grade = "class C — HPD's immediately hazardous grade"
        if total_v == 1:
            out.append(f"The one violation on record at the address is {grade}.")
        elif cv >= total_v:
            out.append(f"All {total_v:,} violations on record at the address are {grade}.")
        else:
            out.append(f"Of the {total_v:,} violations on record at the address, {cv:,} "
                       f"{'is' if cv == 1 else 'are'} {grade}.")

    # 5. what tenants themselves reported
    ct = cm.get("total") or 0
    if ct:
        recent = cm.get("last_12mo") or 0
        tail = (f"{recent:,} of them in the last twelve months" if recent
                else "none of them in the last twelve months")
        out.append(f"Tenants have filed {ct:,} HPD complaint{'' if ct == 1 else 's'} at the "
                   f"address, {tail}.")

    return _name_place(out[:FACTS_MAX_SENTENCES], nb)


def hpd_registration_line(h):
    """'October 7, 2025' from the HPD lastregistrationdate, or None."""
    reg = (h or {}).get("lastregistration")
    if not reg:
        return None
    try:
        d = datetime.date.fromisoformat(str(reg)[:10])
    except ValueError:
        return None
    return f"{d.strftime('%B')} {d.day}, {d.year}"


# Google truncates around 155-160 characters; past that the tail is spent, not
# shown. The builder below fills the budget with facts and drops the ones that
# do not fit, rather than writing one sentence and padding it.
DESC_LIMIT = 158


def building_meta_desc(addr, nb, units, yr, open_viol, advertised, limit=DESC_LIMIT):
    """The <meta name="description"> for one building page.

    It used to be a template with one variable slot:

        "{addr} in {nb}, {boro} is a NYC rent-stabilized building.
         See units, year built, owner, and HPD violations."

    Every one of the 47,165 building pages carried the same 14-word tail, and
    the only thing that varied — the address — was already in the <title>, the
    <h1> and the URL. So the description, which is the only line of the page a
    searcher reads before deciding to click, added nothing to what the title
    already said, and it promised facts ("see units, year built…") instead of
    stating them. On 2026-08-14, 62 building pages held a median Search Console
    position of 6 with 111 impressions and 2 clicks; a low CTR at a good
    position is a snippet problem, not a ranking problem.

    So state the facts instead. Everything here is a field already displayed in
    the page body, from the same record, and nothing is asserted that the page
    does not also say:

      * "about N apartments" keeps the body's own hedge — the unit count comes
        from PLUTO and the body says "about". A meta description is not the
        place to quietly upgrade an approximation into a fact.
      * the DHCR registration is the claim the page exists to make.
      * a recently-advertised unit is the highest-intent thing we know about a
        building, so it wins the leftover budget when both extras fit.
      * open HPD violations are shown in the body's "Building conditions" table
        and are the other reason someone searches an address.

    Degrades on missing fields rather than emitting an empty slot: 99.6% of
    buildings have a unit count and 99.8% a year, but the remainder must still
    read as a sentence.
    """
    facts = []
    if units:
        facts.append(f"about {units} apartment{'' if units == 1 else 's'}")
    if yr:
        facts.append(f"built {yr}")
    def _lead(head):
        if facts:
            return head + ": " + ", ".join(facts) + ", registered as rent stabilized with NY State DHCR."
        return head + ": registered as rent stabilized with NY State DHCR."

    lead = _lead(f"{addr}, {nb}")
    # 19 of 47,165 buildings pair a long address with a long neighborhood name
    # ("114-15 To 114-19 Rockaway Beach Blvd, Breezy Point-Belle Harbor-Rockaway
    # Park-Broad Channel") and blow the budget on the lead alone, so the DHCR
    # claim — the whole point of the line — is what gets truncated away. Drop
    # the neighborhood in that case; the <title> carries it either way.
    if len(lead) > limit:
        lead = _lead(addr)

    extras = []
    if advertised:
        extras.append("A unit here was recently advertised for rent.")
    if open_viol:
        extras.append(f"{open_viol} open HPD violation{'' if open_viol == 1 else 's'} on file.")
    out = lead
    for e in extras:
        if len(out) + 1 + len(e) <= limit:
            out += " " + e
    return out


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

    # The sibling-link ring (see _geo_ring_order). Kept separate from by_nb:
    # the hub pages list their neighborhood alphabetically, which is how a
    # reader looks an address up, while the ring is ordered geographically.
    ring = {k: _geo_ring_order(v) for k, v in by_nb.items()}
    # The comparison base behind building_facts(): one pass per neighborhood,
    # not one per page.
    norms = {k: neighborhood_norms(v) for k, v in by_nb.items()}
    ring_pos = {}
    for k, v in ring.items():
        for i, x in enumerate(v):
            ring_pos[x["bbl"]] = i

    def bld_url(b):
        return f"/building/{BORO_SLUG.get(b['b'],'nyc')}/{slugify(b.get('a'))}-{b['bbl']}/"

    def nb_url(boro, nb):
        return f"/neighborhood/{BORO_SLUG.get(boro,'nyc')}/{slugify(nb)}/"

    def zip_url(z):
        return f"/zip/{z}/"

    def boro_list_url(boro, kind):  # kind = "largest" | "oldest"
        return f"/borough/{BORO_SLUG.get(boro,'nyc')}/{kind}/"

    def avail_url(boro, nb):
        return f"/available/{BORO_SLUG.get(boro,'nyc')}/{slugify(nb)}/"

    urls = []  # (loc, priority) for sitemaps
    promoted_bbls = set()   # building pages that earned a sitemap entry

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
        promoted = promoted_building(b, adv)

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

        # The abbreviation the city files an address under is often not the one a
        # searcher types. Rendered as visible text, not a hidden keyword list.
        aka = address_variants(b.get("a"), boro, b.get("z"))
        aka_html = (f"<p class='aka'>Also written as {esc(' — or '.join(aka))}.</p>"
                    if aka else "")

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
        reg_line = hpd_registration_line(h)
        if v or c or reg_line:
            vr = (f"<tr><td class='k'>HPD violations</td><td>{esc(v.get('open',0))} open / "
                  f"{esc(v.get('total',0))} total"
                  + (f" · {esc(v.get('last_12mo',0))} in last 12 mo" if v.get('last_12mo') else "")
                  + "</td></tr>") if v else ""
            cr = (f"<tr><td class='k'>HPD complaints</td><td>{esc(c.get('open',0))} open / "
                  f"{esc(c.get('total',0))} total</td></tr>") if c else ""
            # Owners of most multiple dwellings have to keep an HPD property
            # registration current, so the date one was last filed is a fact a
            # tenant can use. Reported as a date and nothing more — this build
            # cannot tell whether a registration is validly in force today.
            rr = (f"<tr><td class='k'>HPD registration last filed</td>"
                  f"<td>{esc(reg_line)}</td></tr>") if reg_line else ""
            link = (f"<tr><td class='k'>City record</td><td><a href=\"{esc(h['hpd_url'])}\" "
                    f"rel=\"nofollow noopener\" target=\"_blank\">View on HPD Online ↗</a></td></tr>") if h.get("hpd_url") else ""
            cond_html = "<h2>Building conditions</h2><table class='facts'>" + vr + cr + rr + link + "</table>"

        # The computed comparison block. Omitted, not padded, when this building
        # does not have enough on file to say three true things about it.
        compare_html = ""
        nb_norms = norms.get((b["b"], b.get("nb")))
        if nb_norms:
            sentences = building_facts(b, nb, nb_norms)
            if len(sentences) >= FACTS_MIN_SENTENCES:
                compare_html = ("<h2>How this building compares</h2>"
                                f"<div class='compare'><p>{esc(' '.join(sentences))}</p></div>")

        # ---- the one-time $9 Building Report, offered where the reader is ----
        #
        # Why this exists (2026-08-27): the report launched 2026-07-27 to test
        # whether a single purchase converts where the $4.99/mo Plus
        # subscription never has — and then was only ever offered inside the
        # map app (index.html's detail panel). These static /building/ pages
        # are the ONLY tier that earns search impressions: 260 of the 273 URLs
        # that have ever served a Search Console impression are building
        # pages, against 9 hubs and the home page. So for 30 days the product
        # built to convert search visitors was invisible to every one of them,
        # and the only offer they were shown was Plus, which has 0 conversions
        # for its entire lifetime. That is not evidence the $9 ask fails; it
        # is evidence it was never asked. This puts the ask where the readers
        # are.
        #
        # Gated on compare_html, deliberately. That flag means building_facts()
        # found at least FACTS_MIN_SENTENCES true comparative things to say,
        # which is exactly what section 1 of the report ("How this compares")
        # is built from — so where the block is absent, the report would be
        # thin and we do not offer it. Selling a $9 report on a building we
        # can say nothing about is the one version of this that trades the
        # site's credibility for revenue.
        #
        # The copy is deliberately WORD-FOR-WORD the description already
        # shipped beside the live button in index.html, so the two surfaces
        # cannot drift into making different claims about one product. It
        # promises the pre-filled DHCR request, not the rent history itself —
        # the history is free and the report says so.
        #
        # The link is the same /#d=<bbl> deep link the other CTAs on this page
        # use: it opens the map detail panel, where the real Stripe button
        # lives. A static page cannot POST to /api/reports/checkout, and
        # inventing a GET checkout route here would be a change to the payment
        # path, not to the page.
        report_html = ""
        if compare_html:
            report_html = (
                "<h2>Full building report — $9</h2>"
                "<div class='hook'>"
                "<strong>📄 Get the full building report — $9.</strong> "
                "How this building's violation record compares citywide, who "
                "owns it and what else they own, and a pre-filled DHCR "
                "rent-history request. One-time, no account needed. The report "
                "also states plainly what the data cannot tell you."
                f" <a href='/#d={b['bbl']}'>Get the report for {esc(addr)} &rarr;</a>"
                "</div>")

        # sibling buildings in the same neighborhood, as a ring rather than a
        # star, so every building page is linked from ~12 others instead of 94.9%
        # of them hanging off one hub link (see _geo_ring_order above).
        nb_ring = ring.get((b["b"], b.get("nb")), [])
        nearby = _ring_window(nb_ring, ring_pos.get(b["bbl"], 0)) if nb_ring else []
        near_html = ""
        if nearby:
            items = "".join(f"<a href=\"{bld_url(x)}\">{esc(titlecase_addr(x.get('a')))}</a>" for x in nearby)
            near_html = (f"<h2>Other rent-stabilized buildings in {esc(nb)}</h2><div class='cols'>{items}</div>"
                         f"<p><a href=\"{nb_url(b['b'], b.get('nb') or boro)}\">See all in {esc(nb)} →</a></p>")

        # broaden-search links to the ZIP hub + borough listicles (internal linking / crawl)
        more = [f"<a href=\"{boro_list_url(b['b'],'largest')}\">Largest buildings in {esc(boro)}</a>",
                f"<a href=\"{boro_list_url(b['b'],'oldest')}\">Oldest buildings in {esc(boro)}</a>"]
        if b.get("z"):
            more.insert(0, f"<a href=\"{zip_url(b['z'])}\">All rent-stabilized in ZIP {esc(b['z'])}</a>")
        area_html = "<h2>Explore more</h2><div class='cols'>" + "".join(more) + "</div>"

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
        # A building is a Place, not a Dataset. Marking these up as Dataset —
        # which is what "add Dataset schema to the building pages" would mean
        # literally — would tell every consumer that a single address is a
        # published data collection, which it isn't. ApartmentComplex is the
        # schema.org type that actually describes a multi-unit residential
        # building, and it carries the fields we genuinely hold.
        place = {
            "@context": "https://schema.org",
            "@type": "ApartmentComplex",
            "name": addr,
            "url": canonical,
            "address": {
                "@type": "PostalAddress",
                "streetAddress": addr,
                "addressLocality": boro,
                "addressRegion": "NY",
                "addressCountry": "US",
            },
            # Rent stabilization has no schema.org vocabulary, so it goes in an
            # additionalProperty rather than being crammed into a field that
            # means something else.
            "additionalProperty": [{
                "@type": "PropertyValue",
                "name": "Rent stabilized",
                "value": "Registered with NY State DHCR",
            }],
        }
        if b.get("z"):
            place["address"]["postalCode"] = str(b["z"])
        if b.get("lat") and b.get("lng"):
            place["geo"] = {"@type": "GeoCoordinates",
                            "latitude": b["lat"], "longitude": b["lng"]}
        if units:
            place["numberOfAccommodationUnits"] = {
                "@type": "QuantitativeValue", "value": units}
        if b.get("yr"):
            place["yearBuilt"] = b["yr"]
        # Only name an operator we actually have on file, and only as the
        # registered contact — not as an endorsement or a verified manager.
        operator = (m.get("name") or o.get("name") or "").strip()
        if operator:
            place["additionalProperty"].append({
                "@type": "PropertyValue",
                "name": "HPD-registered operator",
                "value": operator,
            })
        if aka:
            place["alternateName"] = aka
        jsonld = [place, faq, crumb]

        body = (f"<div class='crumbs'><a href='/'>Home</a> › "
                f"<a href='/borough/{BORO_SLUG.get(b['b'],'nyc')}/'>{esc(boro)}</a> › "
                f"<a href='{nb_url(b['b'], b.get('nb') or boro)}'>{esc(nb)}</a></div>"
                f"<h1>Is {esc(addr)} rent stabilized?</h1>"
                f"<p class='lead'>{lead}</p>"
                + aka_html
                + (f"<p><span class='badge'>Recently advertised for rent</span></p>" if adv else "")
                + compare_html
                + f"<a class='cta' href='/#d={b['bbl']}'>View {esc(addr)} on the map →</a>"
                # conversion hook: give organic readers a reason to act, not just leave
                + (f"<div class='hook'><strong>🔔 A unit here was recently advertised.</strong> "
                   f"See it on the map and get an email if another opens up — "
                   f"<a href='/#d={b['bbl']}'>save {esc(addr)} to a free account</a>.</div>"
                   if adv else
                   f"<div class='hook'><strong>🔔 Want to know if an apartment opens up here?</strong> "
                   f"<a href='/#d={b['bbl']}'>Save {esc(addr)} to a free Find A Crib account</a> and get a listing alert. "
                   f"Plus members also see the managing agent's phone number and the owner's full portfolio.</div>")
                + f"<h2>Building details</h2><table class='facts'>{facts}</table>"
                # report offer sits after the conditions table on purpose: the
                # reader has just seen the open-violation count and the whole
                # question the report answers is what that number means here.
                + owner_html + cond_html + report_html + near_html + area_html)

        write(url.strip("/") + "/index.html",
              page(f"Is {addr} rent stabilized? — {nb}, {boro} | Find A Crib",
                   building_meta_desc(addr, nb, units, yr,
                                      (h.get("violations") or {}).get("open"), adv),
                   canonical, body, jsonld,
                   robots=None if promoted else "noindex,follow"))
        if promoted:
            urls.append((canonical, "0.6", b["b"]))
            promoted_bbls.add(b["bbl"])

    # ---- neighborhood pages ----
    for (boro, nb), items in by_nb.items():
        boroname = BORO_NAME.get(boro, "New York")
        url = nb_url(boro, nb)
        canonical = SITE + url
        n = len(items)
        yrs = [x["yr"] for x in items if x.get("yr")]
        med = sorted(yrs)[len(yrs) // 2] if yrs else None
        links = "".join(f"<a href=\"{bld_url(x)}\">{esc(titlecase_addr(x.get('a')))}</a>" for x in items)
        # A flat list of 1,197 identical links spreads this page's weight across
        # 1,197 pages, and the handful that can actually rank are buried in it
        # alphabetically. The promoted buildings — advertised now, worst class-C
        # record, or largest — get their own block above it, with the reason
        # they are there written next to them.
        notable = [x for x in items if x["bbl"] in promoted_bbls][:40]
        notable_html = ""
        if notable:
            rows = []
            for x in notable:
                v = (x.get("h") or {}).get("violations") or {}
                why = ("advertised for rent now" if x["bbl"] in listed
                       else f"{v.get('oc'):,} open class-C violations"
                       if (v.get("oc") or 0) >= PROMOTE_CLASS_C
                       else f"{x.get('u'):,} apartments")
                rows.append(f"<tr><td><a href=\"{bld_url(x)}\">"
                            f"{esc(titlecase_addr(x.get('a')))}</a></td>"
                            f"<td>{esc(why)}</td></tr>")
            notable_html = (f"<h2>Notable buildings in {esc(nb)}</h2>"
                            f"<table class='facts'><tr><th>Building</th><th>Why</th></tr>"
                            + "".join(rows) + "</table>")
        body = (f"<div class='crumbs'><a href='/'>Home</a> › "
                f"<a href='/borough/{BORO_SLUG.get(boro,'nyc')}/'>{esc(boroname)}</a></div>"
                f"<h1>Rent-stabilized buildings in {esc(nb)}, {esc(boroname)}</h1>"
                + answer_block([
                    f"{nb}, {boroname} has {n:,} buildings registered as rent stabilized with "
                    f"New York State DHCR"
                    + (f", most of them built around {med}." if med else "."),
                    STABILIZED_DEF,
                    "Registration is per building, so an individual apartment can still be "
                    "deregulated — check the address below and ask the landlord for its "
                    "rent history.",
                ])
                + f"<a class='cta' href='/'>Explore {esc(nb)} on the map →</a>"
                + VOUCHER_XLINK
                + notable_html
                + f"<h2>All {n:,} buildings</h2><div class='cols'>{links}</div>")
        nb_faq = [(f"How many rent-stabilized buildings are in {nb}, {boroname}?",
                   f"There are {n:,} registered rent-stabilized buildings in {nb}, {boroname}, "
                   f"according to NY State DHCR registration data.")]
        if med:
            nb_faq.append((f"What year were most rent-stabilized buildings in {nb} built?",
                           f"Most rent-stabilized buildings in {nb}, {boroname} were built around {med}, "
                           f"based on NYC PLUTO records for the {n:,} DHCR-registered buildings tracked here."))
        body += faq_html(nb_faq)
        nb_crumb = breadcrumb([
            ("Home", SITE + "/"),
            (boroname, SITE + f"/borough/{BORO_SLUG.get(boro,'nyc')}/"),
            (nb, canonical),
        ])
        # This page IS a collection — every stabilized building in one
        # neighborhood — so it carries a Dataset node for that slice.
        nb_ds = dataset_jsonld(
            name=f"Rent-stabilized buildings in {nb}, {boroname}",
            description=(f"The {n:,} buildings in {nb}, {boroname} registered as rent "
                         f"stabilized with New York State DHCR, with address, BBL, year "
                         f"built, apartment count, registered owner and open HPD "
                         f"violations. A slice of the citywide Find A Crib dataset."),
            url=canonical,
            spatial={"@type": "Place", "name": f"{nb}, {boroname}, New York, NY",
                     "address": {"@type": "PostalAddress", "addressLocality": boroname,
                                 "addressRegion": "NY", "addressCountry": "US"}},
            size=n)
        write(url.strip("/") + "/index.html",
              page(f"Rent-stabilized buildings in {nb}, {boroname} ({n}) | Find A Crib",
                   f"All {n} rent-stabilized buildings in {nb}, {boroname}. Check any address for status, owner, and violations.",
                   canonical, body, [nb_crumb, faq_jsonld(nb_faq), nb_ds]))
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
                + answer_block([
                    f"{boroname} has {total:,} buildings registered as rent stabilized with "
                    f"New York State DHCR, spread across {len(nbs)} neighborhoods.",
                    STABILIZED_DEF,
                    "Registration is per building, so an individual apartment can still be "
                    "deregulated — find the address here and ask the landlord for its "
                    "rent history.",
                ])
                + f"<a class='cta' href='/'>Open the map →</a>"
                f"<p><a href='{boro_list_url(boro,'largest')}'>Largest buildings in {esc(boroname)}</a> "
                f"&nbsp;·&nbsp; <a href='{boro_list_url(boro,'oldest')}'>Oldest buildings</a></p>"
                + VOUCHER_XLINK
                + f"<h2>Neighborhoods</h2><div class='cols'>{links}</div>")
        boro_faq = [(f"How many rent-stabilized buildings are in {boroname}?",
                     f"There are {total:,} registered rent-stabilized buildings across {len(nbs)} "
                     f"neighborhoods in {boroname}, according to NY State DHCR registration data.")]
        body += faq_html(boro_faq)
        boro_crumb = breadcrumb([("Home", SITE + "/"), (boroname, canonical)])
        write(url.strip("/") + "/index.html",
              page(f"Rent-stabilized buildings in {boroname} ({total}) | Find A Crib",
                   f"Browse {total} rent-stabilized buildings across {boroname} by neighborhood.",
                   canonical, body, [boro_crumb, faq_jsonld(boro_faq)]))
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
                      f"<p><a href='{boro_list_url(boro,'largest')}'>Largest buildings</a> &nbsp;·&nbsp; "
                      f"<a href='{boro_list_url(boro,'oldest')}'>Oldest buildings</a></p>"
                      f"<div class='cols'>{nl}</div>")
    write("buildings/index.html",
          page("NYC rent-stabilized buildings by neighborhood | Find A Crib",
               "Browse every NYC rent-stabilized building by borough and neighborhood — Manhattan, Brooklyn, Queens, the Bronx, Staten Island.",
               SITE + "/buildings/",
               f"<h1>NYC rent-stabilized buildings</h1><p class='lead'>Browse all "
               f"{len(blds):,} DHCR rent-stabilized buildings by borough and neighborhood, "
               f"or <a href='/'>open the interactive map</a>. See which buildings were "
               f"<a href='/available/'>recently advertised for rent →</a></p>"
               + VOUCHER_XLINK
               # /buildings/ is one of the few pages a crawler reliably reaches,
               # so the council tier hangs off it rather than depending on the
               # homepage nav alone.
               + "<p><a href='/council-district/'>Rent-stabilized housing and open HPD "
                 "violations by NYC Council District →</a></p>"
               + hub_links
               # /buildings/ is a priority-0.9 page and one of the few places a
               # crawler reliably reaches. The other three cities' browse tiers
               # hang off it so they are not dependent on the city guides alone
               # for internal links.
               + "<h2>Other cities on Find A Crib</h2><div class='cols'>"
               + "".join(f"<a href='/{k}/buildings/'>{esc(c['browse_h1'])}</a>"
                         for k, c in CITY_HUBS.items())
               + "</div>"))
    urls.append((SITE + "/buildings/", "0.9", "hub"))

    # ===== long-tail hub + listicle pages (high-intent searches) =====
    # ---- ZIP-code hubs: "rent-stabilized buildings in ZIP 11221" ----
    by_zip = defaultdict(list)
    for b in blds:
        if b.get("z"):
            by_zip[str(b["z"])].append(b)
    for z, items in by_zip.items():
        if len(items) < 5:
            continue  # skip thin pages
        items = sorted(items, key=lambda x: x.get("a", ""))
        boro_counts = defaultdict(int)
        for x in items:
            boro_counts[x["b"]] += 1
        dom = max(boro_counts, key=boro_counts.get)  # dominant borough for breadcrumb
        boroname = BORO_NAME.get(dom, "New York")
        nbs = sorted({x["nb"] for x in items if x.get("nb")})
        url = zip_url(z)
        canonical = SITE + url
        n = len(items)
        links = "".join(f"<a href=\"{bld_url(x)}\">{esc(titlecase_addr(x.get('a')))}</a>" for x in items[:400])
        nb_links = "".join(f"<a href=\"{nb_url(dom, nb)}\">{esc(nb)}</a>" for nb in nbs)
        body = (f"<div class='crumbs'><a href='/'>Home</a> › "
                f"<a href='/borough/{BORO_SLUG.get(dom,'nyc')}/'>{esc(boroname)}</a></div>"
                f"<h1>Rent-stabilized buildings in ZIP {esc(z)}</h1>"
                + answer_block([
                    f"ZIP code {z} in {boroname} contains {n:,} buildings registered as rent "
                    f"stabilized with New York State DHCR.",
                    STABILIZED_DEF,
                    "Registration is per building, so an individual apartment can still be "
                    "deregulated — find the address below and ask the landlord for its "
                    "rent history.",
                ])
                + (f"<h2>Neighborhoods in {esc(z)}</h2><div class='cols'>{nb_links}</div>" if nb_links else "")
                + f"<a class='cta' href='/'>Explore ZIP {esc(z)} on the map →</a>"
                + VOUCHER_XLINK
                + f"<h2>All {n:,} buildings in {esc(z)}</h2><div class='cols'>{links}</div>")
        zip_faq = [(f"How many rent-stabilized buildings are in ZIP code {z}?",
                    f"There are {n:,} registered rent-stabilized buildings in ZIP code {z} "
                    f"({boroname}), according to NY State DHCR registration data.")]
        body += faq_html(zip_faq)
        crumb = breadcrumb([("Home", SITE + "/"),
                            (boroname, SITE + f"/borough/{BORO_SLUG.get(dom,'nyc')}/"),
                            (f"ZIP {z}", canonical)])
        write(url.strip("/") + "/index.html",
              page(f"Rent-stabilized buildings in ZIP {z}, {boroname} ({n}) | Find A Crib",
                   f"All {n} rent-stabilized buildings in ZIP code {z} ({boroname}). Check any address for status, owner, year built, and violations.",
                   canonical, body, [crumb, faq_jsonld(zip_faq)]))
        urls.append((canonical, "0.7", dom))

    # ---- borough "largest" + "oldest" listicles ----
    SUPER = [("largest", "Largest rent-stabilized buildings", lambda x: -(x.get("u") or 0), "u",
              lambda x: f"{x['u']:,} apartments", "apartment count", "Apartments"),
             ("oldest", "Oldest rent-stabilized buildings", lambda x: (x.get("yr") or 99999), "yr",
              lambda x: f"built {x['yr']}", "year built", "Year built")]
    for boro in ["M", "Bk", "Q", "Bx", "SI"]:
        bb = [x for x in blds if x["b"] == boro]
        if len(bb) < 10:
            continue
        boroname = BORO_NAME.get(boro, "New York")
        for kind, htext, keyf, field, label, by_phrase, col in SUPER:
            ranked = sorted([x for x in bb if x.get(field)], key=keyf)[:50]
            if len(ranked) < 5:
                continue
            url = boro_list_url(boro, kind)
            canonical = SITE + url
            rows = "".join(
                f"<tr><td>{i+1}</td><td><a href=\"{bld_url(x)}\">{esc(titlecase_addr(x.get('a')))}</a></td>"
                f"<td>{esc(x.get('nb') or '')}</td><td>{esc(label(x))}</td></tr>"
                for i, x in enumerate(ranked))
            body = (f"<div class='crumbs'><a href='/'>Home</a> › "
                    f"<a href='/borough/{BORO_SLUG.get(boro,'nyc')}/'>{esc(boroname)}</a></div>"
                    f"<h1>{htext} in {esc(boroname)}</h1>"
                    f"<p class='lead'>The {len(ranked)} {kind} DHCR rent-stabilized buildings in "
                    f"{esc(boroname)}, ranked by {by_phrase}.</p>"
                    f"<a class='cta' href='/'>Open the map →</a>"
                    f"<table class='facts'><thead><tr><th>#</th><th>Building</th>"
                    f"<th>Neighborhood</th><th>{col}</th></tr></thead><tbody>{rows}</tbody></table>")
            crumb = breadcrumb([("Home", SITE + "/"),
                                (boroname, SITE + f"/borough/{BORO_SLUG.get(boro,'nyc')}/"),
                                (htext, canonical)])
            write(url.strip("/") + "/index.html",
                  page(f"{htext} in {boroname} | Find A Crib",
                       f"The {len(ranked)} {kind} rent-stabilized buildings in {boroname}, ranked by {by_phrase}.",
                       canonical, body, crumb))
            urls.append((canonical, "0.6", boro))

    # ---- "no open violations" (best-maintained) borough pages ----
    # Renters search for well-maintained buildings; this cut refreshes as HPD
    # violation data updates each month, so it's naturally fresh content.
    def open_viol(x):
        return ((x.get("h") or {}).get("violations") or {}).get("open")
    for boro in ["M", "Bk", "Q", "Bx", "SI"]:
        boroname = BORO_NAME.get(boro, "New York")
        # buildings with an HPD record (so 0 is real, not "unknown") and 0 open violations
        clean = [x for x in blds if x["b"] == boro and open_viol(x) == 0]
        clean.sort(key=lambda x: -(x.get("u") or 0))   # biggest well-maintained first
        clean = clean[:60]
        if len(clean) < 5:
            continue
        url = f"/borough/{BORO_SLUG.get(boro,'nyc')}/no-violations/"
        canonical = SITE + url
        rows = "".join(
            f"<tr><td>{i+1}</td><td><a href=\"{bld_url(x)}\">{esc(titlecase_addr(x.get('a')))}</a></td>"
            f"<td>{esc(x.get('nb') or '')}</td><td>{esc(x.get('u') or '—')}</td></tr>"
            for i, x in enumerate(clean))
        body = (f"<div class='crumbs'><a href='/'>Home</a> › "
                f"<a href='/borough/{BORO_SLUG.get(boro,'nyc')}/'>{esc(boroname)}</a></div>"
                f"<h1>Rent-stabilized buildings with no open violations in {esc(boroname)}</h1>"
                f"<p class='lead'>{len(clean)} DHCR rent-stabilized buildings in {esc(boroname)} that currently "
                f"have <strong>zero open HPD violations</strong> on record — a useful signal of a well-maintained "
                f"building. Largest first. Always verify a building's current record before you sign.</p>"
                f"<a class='cta' href='/'>Open the map →</a>"
                f"<table class='facts'><thead><tr><th>#</th><th>Building</th>"
                f"<th>Neighborhood</th><th>Apartments</th></tr></thead><tbody>{rows}</tbody></table>"
                f"<p style='margin-top:16px'><a href='/guide/rent-stabilized-tenant-rights/'>"
                f"Learn your rights as a rent-stabilized tenant →</a></p>")
        crumb = breadcrumb([("Home", SITE + "/"),
                            (boroname, SITE + f"/borough/{BORO_SLUG.get(boro,'nyc')}/"),
                            ("No open violations", canonical)])
        write(url.strip("/") + "/index.html",
              page(f"Rent-stabilized buildings with no open violations in {boroname} | Find A Crib",
                   f"{len(clean)} rent-stabilized buildings in {boroname} with zero open HPD violations. "
                   f"A signal of well-maintained buildings — verify before you sign.",
                   canonical, body, crumb))
        urls.append((canonical, "0.6", boro))

    # ---- "recently advertised for rent" pages (high commercial intent) ----
    adv_by_nb = defaultdict(list)
    for b in blds:
        if b["bbl"] in listed and b.get("nb"):
            adv_by_nb[(b["b"], b["nb"])].append(b)
    if adv_by_nb:
        total_adv = sum(len(v) for v in adv_by_nb.values())
        nb_rows = "".join(
            f"<a href=\"{avail_url(boro, nb)}\">{esc(nb)}, {esc(BORO_NAME.get(boro,''))} ({len(v)})</a>"
            for (boro, nb), v in sorted(adv_by_nb.items(), key=lambda kv: -len(kv[1])) if len(v) >= 3)
        body = (f"<div class='crumbs'><a href='/'>Home</a></div>"
                f"<h1>Rent-stabilized apartments recently advertised in NYC</h1>"
                f"<p class='lead'><strong>{total_adv:,}</strong> rent-stabilized buildings across "
                f"{len(adv_by_nb)} neighborhoods have had a unit advertised for rent recently "
                f"(matched nightly against Zumper). Browse by neighborhood:</p>"
                f"<a class='cta' href='/'>Open the map →</a>"
                f"<h2>Neighborhoods with recent listings</h2><div class='cols'>{nb_rows}</div>")
        write("available/index.html",
              page("Rent-stabilized apartments recently advertised in NYC | Find A Crib",
                   f"{total_adv} rent-stabilized buildings recently advertised for rent across NYC, by neighborhood.",
                   SITE + "/available/", body,
                   breadcrumb([("Home", SITE + "/"), ("Recently advertised", SITE + "/available/")])))
        urls.append((SITE + "/available/", "0.8", "hub"))
    for (boro, nb), items in adv_by_nb.items():
        if len(items) < 3:
            continue
        boroname = BORO_NAME.get(boro, "New York")
        url = avail_url(boro, nb)
        canonical = SITE + url
        n = len(items)
        links = "".join(f"<a href=\"{bld_url(x)}\">{esc(titlecase_addr(x.get('a')))}</a>"
                        for x in sorted(items, key=lambda x: x.get("a", "")))
        body = (f"<div class='crumbs'><a href='/'>Home</a> › "
                f"<a href='/available/'>Recently advertised</a> › "
                f"<a href='{nb_url(boro, nb)}'>{esc(nb)}</a></div>"
                f"<h1>Rent-stabilized apartments recently advertised in {esc(nb)}, {esc(boroname)}</h1>"
                f"<p class='lead'>{n} rent-stabilized building{'s' if n != 1 else ''} in {esc(nb)} "
                f"had a unit advertised for rent recently. Rent-stabilized units come with regulated "
                f"rent increases — check each building's status, owner, and HPD record.</p>"
                f"<a class='cta' href='/'>See {esc(nb)} on the map →</a>"
                f"<h2>Buildings with recent listings</h2><div class='cols'>{links}</div>"
                f"<p><a href=\"{nb_url(boro, nb)}\">See all rent-stabilized buildings in {esc(nb)} →</a></p>")
        crumb = breadcrumb([("Home", SITE + "/"), ("Recently advertised", SITE + "/available/"), (nb, canonical)])
        write(url.strip("/") + "/index.html",
              page(f"Recently advertised rent-stabilized apartments in {nb}, {boroname} | Find A Crib",
                   f"{n} rent-stabilized buildings in {nb}, {boroname} recently advertised a unit for rent. Check status, owner, and violations.",
                   canonical, body, crumb))
        urls.append((canonical, "0.7", boro))

    # ---- cornerstone guide pages (/guide/ hub + one page per guide) ----
    for g in GUIDES:
        canonical, doc = guide_page(g)
        write(f"guide/{g['slug']}/index.html", doc)
        urls.append((canonical, "0.8", "guide"))

    # /guide/ hub linking every guide
    hub_canonical = SITE + "/guide/"
    # Grouped by city. A flat list of nine cards reads as one NYC pile with three
    # strays in it; the headings are also what tells a reader (and a crawler)
    # that SF/LA/DC are covered here at all.
    CITY_LABELS = [("nyc", "New York City"), ("sf", "San Francisco"),
                   ("la", "Los Angeles"), ("dc", "Washington, DC")]
    sections = []
    for key, label in CITY_LABELS:
        group = [g for g in GUIDES if g.get("city", "nyc") == key]
        if not group:
            continue
        cards = "".join(
            f"<a class='card' href='/guide/{g['slug']}/'><strong>{esc(g['h1'])}</strong>"
            f"<div style='color:#4a4a68;font-size:14px;margin-top:4px'>{esc(g['desc'])}</div></a>"
            for g in group)
        sections.append(f"<h2>{esc(label)}</h2><div class='grid'>{cards}</div>")
    hub_crumb = breadcrumb([("Home", SITE + "/"), ("Guides", hub_canonical)])
    hub_body = ("<div class='crumbs'><a href='/'>Home</a> › Guides</div>"
                "<h1>Rent stabilization &amp; rent control guides</h1>"
                "<p class='lead'>Plain-English answers to the most common questions about rent-regulated "
                "apartments in New York City, San Francisco, Los Angeles and Washington, DC — what the rules are, "
                "how to check your own unit, and what your rights are as a tenant. Each city's rules are different, "
                "so start with your city.</p>"
                + "".join(sections) +
                "<h2>Check a building</h2><p>Rent regulation is building-specific — look up any address on the map.</p>"
                "<a class='cta' href='/'>🔎 Open the Find A Crib map →</a>")
    write("guide/index.html",
          page("Rent Stabilization & Rent Control Guides — NYC, SF, LA, DC | Find A Crib",
               "Plain-English guides to rent regulation in NYC, San Francisco, Los Angeles and Washington DC: "
               "check if your apartment is covered, tenant rights, lease renewals, and the exemptions that matter.",
               hub_canonical, hub_body, hub_crumb))
    urls.append((hub_canonical, "0.9", "guide"))

    # ---- the SF / LA / DC browse tier (see CITY_HUBS above) ----
    # Sharded into its own sitemap per city by the loop below, because the key
    # in `urls` is the shard name: 2026 guidance on large sites is consistent
    # that mixing thousands of URLs into one sitemap makes it harder, not
    # easier, for a crawler to tell the important pages from the noise.
    city_built = city_hub_pages(urls)
    print("city hubs: " + ", ".join(f"{k}={v}" for k, v in sorted(city_built.items())))

    # ---- NYC Council district tier (see council_district_pages) ----
    council = council_district_pages(urls)
    print(f"council districts: {len(council)}")

    # ---- sitemaps (sharded by borough, < 50k each) + index ----
    by_boro_urls = defaultdict(list)
    for loc, pri, key in urls:
        by_boro_urls[key].append((loc, pri))
    smaps = []
    shard_lastmod = {}
    for key, locs in by_boro_urls.items():
        name = f"sitemap-{key}.xml"
        body = "".join(f"<url><loc>{loc}</loc><lastmod>{LASTMOD.get(loc, BUILD_DATE)}</lastmod>"
                       f"<priority>{pri}</priority></url>" for loc, pri in locs)
        write(name, f'<?xml version="1.0" encoding="UTF-8"?>'
                    f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>')
        shard_lastmod[name] = max((LASTMOD.get(loc, BUILD_DATE) for loc, _ in locs), default=BUILD_DATE)
        smaps.append(name)
    idx = "".join(f"<sitemap><loc>{SITE}/{n}</loc><lastmod>{shard_lastmod.get(n, BUILD_DATE)}</lastmod></sitemap>"
                  for n in sorted(smaps))
    # sitemap-daily.xml is owned by the daily growth engine (growth/techniques.py).
    # This monthly build must still list it, or a rebuild would silently drop the
    # daily section out of the index until the next growth run repaired it.
    idx += f"<sitemap><loc>{SITE}/sitemap-daily.xml</loc><lastmod>{BUILD_DATE}</lastmod></sitemap>"
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>'
          f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          f'<sitemap><loc>{SITE}/sitemap-main.xml</loc><lastmod>{BUILD_DATE}</lastmod></sitemap>{idx}</sitemapindex>')
    # main sitemap = homepage + hand-authored pages (developer API portal).
    # These aren't generated in the loop above, so list them here explicitly.
    static_pages = [("/", "1.0"), ("/developers/", "0.8"),
                    # HPD lottery-agent directory (hand-written page, data from
                    # build_marketing_agents.py)
                    ("/marketing-agents/", "0.8"),
                    # city maps (sf/la/dc pages are generated by build_city_pages.py)
                    ("/sf/", "0.9"), ("/la/", "0.9"), ("/dc/", "0.9")]
    main_urls = "".join(f'<url><loc>{SITE}{p}</loc><lastmod>{BUILD_DATE}</lastmod>'
                        f'<priority>{pr}</priority></url>' for p, pr in static_pages)
    write("sitemap-main.xml", f'<?xml version="1.0" encoding="UTF-8"?>'
          f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{main_urls}</urlset>')
    # robots.txt is deliberately NOT written here. The daily growth engine owns it
    # (growth/techniques.py:t_llms_txt) because it names the AI crawlers explicitly
    # and lists both sitemaps; writing the short version here would revert that
    # every month until the next daily run.

    # persist lastmod state + emit the list of changed URLs for IndexNow.
    # Only submitted URLs are worth pinging: the triage above put noindex on
    # ~46k building pages, which changes their bytes and so marks every one of
    # them "changed". Announcing 46,000 freshly-noindexed pages to IndexNow is
    # at best wasted quota and at worst the kind of bulk submission that makes
    # a small domain look like a spam farm — the pages we want crawled would be
    # a rounding error in the payload.
    submitted = {loc for loc, _, _ in urls} | {SITE + p for p, _ in static_pages}
    json.dump(LM_NEW, open(LM_STATE_PATH, "w"))
    ping = sorted(set(LM_CHANGED) & submitted)
    with open(os.path.join(OUT, "changed_urls.txt"), "w") as f:
        f.write("\n".join(ping))
    print(f"IndexNow: {len(ping):,} changed URLs to ping "
          f"({len(set(LM_CHANGED)):,} pages changed, {len(set(LM_CHANGED)) - len(ping):,} "
          f"not submitted so not announced)")

    n_bld = len(blds)
    print(f"index triage: {len(promoted_bbls):,} of {n_bld:,} building pages promoted "
          f"({len(promoted_bbls) * 100.0 / n_bld:.1f}%); the rest are noindex,follow "
          f"and out of the sitemap")
    print(f"Generated {len(urls):,} submitted URLs + {len(smaps)+2} sitemaps into {OUT}/ "
          f"({len(LM_CHANGED)} pages changed this run)")


if __name__ == "__main__":
    main()
