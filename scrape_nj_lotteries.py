#!/usr/bin/env python3
"""New Jersey affordable-housing drawings -> nj_lotteries.json.

Owner, 2026-09-24, with a screenshot of Affordable Homes New Jersey's list:
"are any of these able to be put on the find a crib app? new jersey has
affordable housing units?"

Source: the "WHAT'S NEW?" box on https://www.affordablehomesnewjersey.com/,
run by CGP&H, the administrator many NJ towns hire for their COAH/Mount Laurel
affordable units. It names each town holding a random drawing and the date to
be on that town's waiting list by, split into RENTALS and SALES:

    Washington Township – Bergen by 9/28/2026
    Wayne – COMING SOON

That is all it publishes publicly — no address, rent or income band; those are
shown only inside an applicant's profile. So the app shows town, county and
the join-by date, and sends people to CGP&H's pre-application. Towns are
matched to a county through nj/rentcontrol.json (NJ DCA municipality names).

The page is fetched once per run (daily cron), from the public home page that
robots.txt allows; the WordPress JSON API is disallowed and not used.

    python3 scrape_nj_lotteries.py                 # writes nj_lotteries.json here
    python3 scrape_nj_lotteries.py --out /var/www/rent-map/nj_lotteries.json
    python3 scrape_nj_lotteries.py --dry-run

A failed fetch, or a page where the list can't be found, never overwrites the
last good file.
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = "https://www.affordablehomesnewjersey.com/"
# Where a card sends people (owner, 2026-09-24: "these links take me to a
# generic website - i dont see the actual listing"). CGP&H's current-listings
# pages show the units themselves; ?lid= opens one listing. The lids come from
# nj/cgph_links.json, curated by hand, because the Salesforce host that serves
# them disallows automated fetching in its robots.txt.
LISTINGS = {"rent": URL + "rental-opportunities/current-listings/",
            "buy": URL + "ownership-opportunities/current-listings/"}
UA = "findacrib.com affordable-housing listings (+https://findacrib.com)"

# CGP&H's own live/work regions (profile page), for "Region 1" labels.
REGIONS = {1: ["Bergen", "Hudson", "Passaic", "Sussex"], 2: ["Essex", "Morris", "Union", "Warren"],
           3: ["Hunterdon", "Middlesex", "Somerset"], 4: ["Mercer", "Monmouth", "Ocean"],
           5: ["Burlington", "Camden", "Gloucester"], 6: ["Atlantic", "Cape May", "Cumberland", "Salem"]}
REGION_OF = {c: r for r, cs in REGIONS.items() for c in cs}
SUFFIXES = ("township", "borough", "city", "town", "village")


def fetch(url=URL):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def municipalities():
    """{lowercased name: [county, …]} from the NJ DCA survey join."""
    out = {}
    try:
        zips = json.load(open(HERE / "nj" / "rentcontrol.json"))["zips"]
    except (OSError, ValueError, KeyError):
        return out
    for ms in zips.values():
        for m in ms:
            name, county = (m.get("name") or "").strip(), (m.get("county") or "").strip()
            if name and county:
                out.setdefault(name.lower(), set()).add(county)
    return {k: sorted(v) for k, v in out.items()}


def town_key(t):
    """'Washington Township – Bergen' / 'Paramus Borough' / 'Paramus Rental' ->
    'washington township bergen' / 'paramus' / 'paramus'."""
    t = (t or "").lower().replace("–", " ").replace("—", " ").replace("-", " ")
    t = re.sub(r"\b(borough|rental|sale|sales)\b", " ", t)
    return " ".join(t.split())


def curated_links():
    try:
        return json.load(open(HERE / "nj" / "cgph_links.json"))["towns"]
    except (OSError, ValueError, KeyError):
        return {}


def county_for(town, hint, munis):
    """The county of a CGP&H town label, or None when it can't be told apart
    (NJ has six Washington Townships; the label then carries the county)."""
    base = town.lower()
    names = [base] + [f"{base} {s}" for s in SUFFIXES]
    found = set()
    for n in names:
        found.update(munis.get(n, []))
    if hint:
        h = hint.strip().title()
        if h in REGION_OF:
            return h
    return found.pop() if len(found) == 1 else None


ITEM = re.compile(r"^(?P<label>.+?)\s*(?:[–—-]\s*COMING SOON|\s+by\s+(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4}))\s*$", re.I)


def parse(page, munis=None, links=None):
    munis = munis if munis is not None else municipalities()
    links = links if links is not None else curated_links()
    i = page.find("WHAT")
    box = page[i:i + 20000] if i >= 0 else ""
    out = []
    # Each <ul> follows a <p> naming RENTALS or SALES.
    for kind, ul in re.findall(r"<strong>\s*(RENTALS|SALES)\s*:?\s*</strong>.*?<ul>(.*?)</ul>", box, re.S | re.I):
        tenure = "rent" if kind.upper() == "RENTALS" else "buy"
        for li in re.findall(r"<li[^>]*>(.*?)</li>", ul, re.S):
            t = text(li)
            m = ITEM.match(t)
            if not m:
                print(f"nj: skipped unparsed item {t!r}", file=sys.stderr)
                continue
            label = re.sub(r"\s+(Rental|Sale|Sales)$", "", m.group("label").strip(), flags=re.I)
            # "Washington Township – Bergen": the part after the dash is the county.
            town, _, hint = (s.strip() for s in (re.split(r"\s+([–—-])\s+", label, maxsplit=1) + ["", ""])[:3])
            closes = None
            if m.group("y"):
                closes = f"{int(m.group('y')):04d}-{int(m.group('m')):02d}-{int(m.group('d')):02d}"
            county = county_for(town, hint, munis)
            link = links.get(town_key(label))
            if link and link.get("tenure") != tenure:
                link = None
            href = LISTINGS[tenure] + (f"?lid={link['lid']}" if link and link.get("lid") else "")
            out.append({
                "id": f"{tenure}-{re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')}",
                "town": town,
                "county": county,
                "region": REGION_OF.get(county) if county else None,
                "tenure": tenure,
                "closes": closes,
                "coming_soon": closes is None,
                "development": (link or {}).get("development"),
                "href": href,
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "nj_lotteries.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        page = fetch()
    except Exception as e:  # network, TLS, HTTP error: keep the last good file
        print(f"nj: fetch failed, keeping last file: {e}", file=sys.stderr)
        return 1
    items = parse(page)
    if not items:
        print("nj: no drawings found on the page, keeping last file", file=sys.stderr)
        return 1
    payload = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Affordable Homes New Jersey (CGP&H)",
        "source_url": URL,
        "apply_url": URL + "apply-now/",
        "lotteries": items,
    }
    if a.dry_run:
        print(json.dumps(payload, indent=2))
        return 0
    tmp = Path(a.out + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")))
    tmp.replace(a.out)
    print(f"nj: {len(items)} drawings -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
