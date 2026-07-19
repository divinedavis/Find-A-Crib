#!/usr/bin/env python3
"""Build la/buildings.min.json — Los Angeles buildings likely covered by the RSO.

LA publishes no building-level RSO list, but the city's own criteria are
mechanical: residential parcels in the City of Los Angeles with 2+ units built
on or before Oct 1, 1978 (LAHD, housing.lacity.gov/residents/rso-overview).
This script derives that set from the LA County Assessor parcel layer
(public.gis.lacounty.gov, refreshed monthly) — ~67k parcels.

Records are labeled "likely RSO" in the UI with a ZIMAS verification link:
year-built is tax-roll data and a handful of exemptions (e.g. luxury-exempt,
substantially renovated) can't be derived here.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "la" / "buildings.min.json"
LAYER = ("https://public.gis.lacounty.gov/public/rest/services/"
         "LACounty_Cache/LACounty_Parcel/MapServer/0/query")
WHERE = ("TaxRateCity='LOS ANGELES' AND UseType='Residential' "
         "AND Units1>=2 AND YearBuilt1<>'' AND YearBuilt1<='1978'")
FIELDS = ("AIN,SitusAddress,SitusZIP,YearBuilt1,Units1,Units2,Units3,Units4,"
          "CENTER_LAT,CENTER_LON,UseDescription")
PAGE = 1000


def fetch_page(offset):
    params = urllib.parse.urlencode({
        "where": WHERE,
        "outFields": FIELDS,
        "returnGeometry": "false",
        "resultOffset": offset,
        "resultRecordCount": PAGE,
        "orderByFields": "AIN",
        "f": "json",
    })
    # the county server is slow and drops connections under load — retry hard
    for attempt in range(5):
        try:
            with urllib.request.urlopen(f"{LAYER}?{params}", timeout=180) as r:
                return json.load(r).get("features", [])
        except Exception as e:
            if attempt == 4:
                raise
            wait = 5 * (attempt + 1)
            print(f"  offset {offset:,}: {e} — retrying in {wait}s", flush=True)
            time.sleep(wait)


def main():
    seen = set()
    slim = []
    offset = 0
    while True:
        feats = fetch_page(offset)
        for f in feats:
            a = f.get("attributes", {})
            ain = a.get("AIN")
            lat, lon = a.get("CENTER_LAT"), a.get("CENTER_LON")
            addr = " ".join((a.get("SitusAddress") or "").split())
            if not ain or ain in seen or not lat or not lon or not addr:
                continue
            seen.add(ain)
            units = sum(a.get(k) or 0 for k in ("Units1", "Units2", "Units3", "Units4"))
            yb = a.get("YearBuilt1") or ""
            rec = {
                "bbl": f"LA-{ain}",
                "b": "LA",
                "a": addr,
                "z": (a.get("SitusZIP") or "")[:5],
                "lat": round(lat, 6),
                "lng": round(lon, 6),
                "s": ["LIKELY RSO (PRE-1979, 2+ UNITS)"],
                "yr": int(yb) if yb.isdigit() else None,
                "u": units or None,
                "nb": None,
            }
            slim.append(rec)
        print(f"  {offset + len(feats):,} fetched", flush=True)
        if len(feats) < PAGE:
            break
        offset += PAGE

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(slim, separators=(",", ":")))
    print(f"Wrote {OUT} ({OUT.stat().st_size/1024/1024:.2f} MB) with {len(slim):,} parcels")


if __name__ == "__main__":
    sys.exit(main())
