#!/usr/bin/env python3
"""Build westchester/buildings.min.json from NYS HCR's public ArcGIS layer.

WHY THIS SOURCE, AND NOT A SCRAPER
----------------------------------
Outside New York City rent stabilization is ETPA (Emergency Tenant Protection
Act), and the NYC Rent Guidelines Board building lists — the source behind the
NYC map — are NYC-only. The obvious alternative was DHCR's Rent Regulated
Building Search at apps.hcr.ny.gov, which is what the one public scrape of this
data (fitnr/rentregulated) used. Two things ruled that out:

  1. apps.hcr.ny.gov/BuildingSearch/ no longer answers. Connection refused from
     two unrelated networks (a residential Mac and the droplet), so this is the
     host, not a block on one address.
  2. That scrape's newest registration is 2016. A decade-old snapshot would
     show a since-deregulated building as covered, which is the one error this
     site must not make.

HCR's own Rent Registration Data Dashboard turned out to be an ArcGIS
dashboard, and its "Registered Buildings" layer is a PUBLIC feature service:

    https://services8.arcgis.com/ek7Sxtay3Z4WZWvk/arcgis/rest/services
      /reg_bldg_table/FeatureServer/0

56,048 buildings statewide, official, paginated, and — the part that matters —
it already carries latitude/longitude, so there is no geocoding step and no
Google Places bill. It also carries last_year_registered, so freshness is a
field we can read rather than a thing we hope about: 1,555 of 1,706 Westchester
rows registered in 2025 when this was written.

This is a documented public API, not a scrape, but it is still someone else's
server: the whole county is 2 requests at 1,000 rows each, bounded below.

Usage:  python3 build_westchester.py [--county WESTCHESTER] [--out DIR]
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
SERVICE = ("https://services8.arcgis.com/ek7Sxtay3Z4WZWvk/arcgis/rest/services"
           "/reg_bldg_table/FeatureServer/0/query")
UA = "findacrib.com building map (+https://findacrib.com)"

# Politeness bounds. The county needs 2 pages; anything past MAX_PAGES means the
# layer grew by an order of magnitude or the offset stopped advancing, and
# either way stopping beats hammering a state server in a loop.
PAGE = 1000
MAX_PAGES = 40
PAUSE = 0.4
TIMEOUT = 60
RETRIES = 3

# Yonkers is the city people actually search for — 10701 was the query that
# started this — so it is named separately from the rest of the county.
YONKERS_ZIPS = {10701, 10702, 10703, 10704, 10705, 10706, 10707, 10708, 10710}

# ETPA covers pre-1974 buildings of 6+ units in localities that adopted it. The
# layer's bldg_status is a semicolon-joined list of DHCR building classes and
# programme flags; these are the ones worth surfacing as a status chip.
STATUS_LABEL = {
    "MULTIPLE DWELLING A": "ETPA RENT STABILIZED",
    "MULTIPLE DWELLING B": "ETPA RENT STABILIZED (SRO/ROOMING)",
    "GARDEN COMPLEX": "GARDEN COMPLEX",
    "NON-EVICT COOP/CONDO": "NON-EVICTION CO-OP/CONDO",
}


def fetch_page(where, offset):
    params = {
        "where": where,
        "outFields": "*",
        "returnGeometry": "false",
        "resultOffset": offset,
        "resultRecordCount": PAGE,
        "f": "json",
    }
    url = SERVICE + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(f"ArcGIS error: {d['error']}")
            return d
        except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
            last = e
            # Back off on the server's terms, not ours: a 429 or a 5xx wants a
            # longer wait than a dropped socket.
            code = getattr(e, "code", None)
            wait = (8 if code in (429, 503) else 2) * (attempt + 1)
            print(f"  attempt {attempt+1}/{RETRIES} failed ({e}); waiting {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
    raise SystemExit(f"giving up after {RETRIES} attempts: {last}")


def fetch_county(county):
    where = f"county='{county}'"
    rows, offset = [], 0
    for page in range(MAX_PAGES):
        d = fetch_page(where, offset)
        feats = d.get("features", [])
        rows += [f["attributes"] for f in feats]
        print(f"  page {page+1}: {len(feats)} rows (total {len(rows)})", flush=True)
        if len(feats) < PAGE:
            return rows
        offset += PAGE
        time.sleep(PAUSE)
    print(f"  stopped at MAX_PAGES={MAX_PAGES}; the layer may have grown — "
          f"raise the bound deliberately, don't loop", file=sys.stderr)
    return rows


def statuses(raw):
    """DHCR's bldg_status is 'A; GARDEN COMPLEX; 421-A (1-15)' — split it, map
    the ones we have words for, and keep the rest as-is rather than dropping
    them. A flag we don't recognise is still information."""
    out = []
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part:
            continue
        out.append(STATUS_LABEL.get(part, part.upper()))
    return out or ["ETPA REGISTERED"]


def clean_address(addr, zip_code):
    """'106 Oliver Ave, Yonkers, 10701' -> '106 OLIVER AVE'. The city and ZIP
    are separate fields on the record; repeating them in the address makes
    every search-box match noisier and every label longer."""
    a = (addr or "").strip()
    for tail in (f", {zip_code}", f" {zip_code}"):
        if a.endswith(tail):
            a = a[: -len(tail)].rstrip(" ,")
    parts = [p.strip() for p in a.split(",") if p.strip()]
    if len(parts) > 1:
        parts = parts[:-1]          # drop the city
    return " ".join(" ".join(parts).split()).upper()


def city_of(zip_code):
    if zip_code in YONKERS_ZIPS:
        return "Yonkers"
    return "Westchester"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", default="WESTCHESTER")
    ap.add_argument("--out", default="westchester")
    ap.add_argument("--min-year", type=int, default=0,
                    help="drop rows whose last registration predates this year")
    args = ap.parse_args()

    print(f"fetching {args.county} from HCR's Registered Buildings layer …", flush=True)
    rows = fetch_county(args.county)
    print(f"{len(rows):,} rows\n", flush=True)

    out, skipped_geo, skipped_year = [], 0, 0
    seen = {}
    for r in rows:
        lat, lng = r.get("latitude"), r.get("longitude")
        if not lat or not lng:
            skipped_geo += 1
            continue
        year = r.get("last_year_registered")
        if args.min_year and (year or 0) < args.min_year:
            skipped_year += 1
            continue
        zip_code = r.get("zip_code")
        rec = {
            # No BBL outside NYC — the layer's bbl column is null for every
            # Westchester row. HCR's building id is the stable key here.
            "bbl": f"WC-{r.get('bldg_id')}",
            "b": city_of(zip_code),
            "a": clean_address(r.get("address"), zip_code),
            "z": str(zip_code) if zip_code else "",
            "lat": round(float(lat), 6),
            "lng": round(float(lng), 6),
            "s": statuses(r.get("bldg_status")),
            "yr": None,          # the layer carries no year-built
            "u": None,           # nor a unit count
            # No neighbourhood tier out here: the county has no equivalent of
            # NYC's NTAs, and setting it to the city name only produced
            # "Yonkers · Yonkers" in the ZIP suggestions. Null also hides the
            # neighbourhood filter, which would otherwise be an empty control.
            "nb": None,
            # Freshness travels WITH the record, so the map can say how old a
            # given pin's registration is instead of stamping one date on the
            # whole city.
            "reg": year,
        }
        if not rec["a"]:
            skipped_geo += 1
            continue
        key = (rec["a"], rec["z"])
        if key not in seen or (seen[key].get("reg") or 0) < (year or 0):
            seen[key] = rec

    out = sorted(seen.values(), key=lambda x: (x["z"], x["a"]))
    dest = HERE / args.out
    dest.mkdir(exist_ok=True)
    path = dest / "buildings.min.json"
    path.write_text(json.dumps(out, separators=(",", ":")))

    yonkers = [r for r in out if r["b"] == "Yonkers"]
    years = {}
    for r in out:
        years[r.get("reg")] = years.get(r.get("reg"), 0) + 1
    recent = sum(n for y, n in years.items() if (y or 0) >= 2024)
    print(f"Wrote {path} ({path.stat().st_size/1e6:.2f} MB)")
    print(f"  {len(out):,} buildings — {len(yonkers):,} in Yonkers, "
          f"{len(out)-len(yonkers):,} elsewhere in Westchester")
    print(f"  {recent:,} ({100*recent/max(1,len(out)):.0f}%) registered 2024 or later")
    print(f"  deduped {len(rows)-len(out)-skipped_geo-skipped_year:,} repeat addresses, "
          f"skipped {skipped_geo:,} without usable address/coords"
          + (f", {skipped_year:,} older than {args.min_year}" if args.min_year else ""))


if __name__ == "__main__":
    main()
