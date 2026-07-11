#!/usr/bin/env python3
"""Build the building half of s8.json — Section 8 / voucher signals per BBL
(stdlib only, same zero-dep style as fetch_apify.py so the droplet cron can
run it without a venv).

Two building-level sources, joined onto the DHCR rent-stabilized universe:

1. HPD "Affordable Housing Production by Building" (NYC Open Data hg8x-zxpr)
   -> city-financed income-restricted buildings, joined directly on BBL.
   Only projects with counted rental units are kept (homeownership projects
   say nothing about vouchers).
2. HUD "Multifamily Properties - Assisted" (HUD ArcGIS open data,
   IS_SEC8_IND='Y' in the five boroughs) -> buildings with a project-based
   Section 8 contract, address-matched to BBL with the same normalizer the
   listings pipeline uses (parse_apify.normalize_addr / build_index).

Output: s8.json — {"updated", "bldg": {bbl: {"f": flags, "u": units, "n": name?}}}
  flags: 1 = HPD city-financed affordable, 2 = HUD project-based Section 8
  (3 = both). "u" is the larger of the two unit counts, "n" the HUD property
  name when known.

The live-listings half ("avail", from AffordableHousing.com) is written by
scrape_affordablehousing.py; this script preserves it if already present.

Usage:  python3 fetch_section8.py
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from parse_apify import build_index, normalize_addr

HERE = Path(__file__).parent
BUILDINGS = HERE / "buildings.min.json"
OUT = HERE / "s8.json"

HPD_URL = "https://data.cityofnewyork.us/resource/hg8x-zxpr.json"
HUD_URL = ("https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/"
           "MULTIFAMILY_PROPERTIES_ASSISTED/FeatureServer/0/query")
# county FIPS -> DHCR borough code (36061 New York, 36005 Bronx, 36047 Kings,
# 36081 Queens, 36085 Richmond)
COUNTY_TO_BOROUGH = {"061": "M", "005": "Bx", "047": "Bk", "081": "Q", "085": "SI"}

FLAG_HPD, FLAG_HUD = 1, 2


def get_json(url, params):
    qs = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{qs}", timeout=120) as r:
        return json.loads(r.read())


def fetch_hpd():
    """Return {bbl: rental_units} for city-financed projects with rentals."""
    units = {}
    offset = 0
    while True:
        rows = get_json(HPD_URL, {
            "$select": "bbl,counted_rental_units",
            "$where": "bbl IS NOT NULL",
            "$limit": 5000, "$offset": offset,
        })
        for row in rows:
            n = int(row.get("counted_rental_units") or 0)
            if len(row.get("bbl", "")) == 10 and n > 0:
                units[row["bbl"]] = units.get(row["bbl"], 0) + n
        if len(rows) < 5000:
            return units
        offset += 5000


def fetch_hud():
    """Return [{addr, borough, name, units}] for NYC project-based Section 8."""
    out, offset = [], 0
    where = ("STATE2KX='36' AND CNTY2KX IN ('005','047','061','081','085') "
             "AND IS_SEC8_IND='Y'")
    while True:
        data = get_json(HUD_URL, {
            "where": where,
            "outFields": "PROPERTY_NAME_TEXT,STD_ADDR,CNTY2KX,"
                         "TOTAL_ASSISTED_UNIT_COUNT",
            "resultOffset": offset, "f": "json",
        })
        feats = data.get("features", [])
        for f in feats:
            a = f["attributes"]
            addr = (a.get("STD_ADDR") or "").strip()
            boro = COUNTY_TO_BOROUGH.get((a.get("CNTY2KX") or "").strip())
            if addr and boro:
                out.append({
                    "addr": addr, "borough": boro,
                    "name": (a.get("PROPERTY_NAME_TEXT") or "").strip().title(),
                    "units": a.get("TOTAL_ASSISTED_UNIT_COUNT") or 0,
                })
        if not feats or not data.get("exceededTransferLimit"):
            return out
        offset += len(feats)


def main():
    records = json.loads(BUILDINGS.read_text())
    known_bbls = {r["bbl"] for r in records}
    # per-borough address index so "100 Broadway" in Manhattan can't match
    # the Brooklyn building of the same name
    addr_idx = {b: build_index([r for r in records if r["b"] == b])
                for b in ("M", "Bx", "Bk", "Q", "SI")}

    bldg = {}

    hpd = fetch_hpd()
    hpd_on_map = 0
    for bbl, n in hpd.items():
        if bbl in known_bbls:
            hpd_on_map += 1
            bldg[bbl] = {"f": FLAG_HPD, "u": n}
    print(f"HPD affordable rentals: {len(hpd)} buildings, "
          f"{hpd_on_map} on the DHCR map")

    hud = fetch_hud()
    hud_matched = 0
    for p in hud:
        bbl = addr_idx[p["borough"]].get(normalize_addr(p["addr"]))
        if not bbl:
            continue
        hud_matched += 1
        cur = bldg.setdefault(bbl, {"f": 0, "u": 0})
        cur["f"] |= FLAG_HUD
        cur["u"] = max(cur["u"], p["units"])
        if p["name"]:
            cur["n"] = p["name"]
    print(f"HUD project-based Section 8: {len(hud)} NYC properties, "
          f"{hud_matched} matched to the DHCR map")

    payload = {"updated": int(time.time()), "bldg": bldg}
    if OUT.exists():  # keep the live-listings half from the scraper
        old = json.loads(OUT.read_text())
        if old.get("avail"):
            payload["avail"] = old["avail"]
            payload["avail_updated"] = old.get("avail_updated")
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"s8.json: {len(bldg)} voucher-friendly buildings")


if __name__ == "__main__":
    main()
