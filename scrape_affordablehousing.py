#!/usr/bin/env python3
"""Scrape AffordableHousing.com (ex-GoSection8) live NYC voucher listings
into the "avail" half of s8.json (stdlib only — plain POSTs, no browser).

AffordableHousing.com is the site NYCHA/HPD point Housing Choice Voucher
holders to; landlords list there specifically to reach voucher tenants. The
site's search runs through a JSON endpoint (v4/AjaxHandler?message=
SearchListings) that pages 32 results at a time per county, no auth or
cookies required. We page through the five borough counties, address-match
each listing to a DHCR BBL (same normalizer as the listings pipeline), and
record per building: listing count, lowest advertised rent, the cheapest
listing's detail URL, and whether any listing carries the site's explicit
"accepts Section 8" badge.

Output (merged into s8.json, preserving fetch_section8.py's "bldg" half):
  "avail": {bbl: {"n": count, "p": min_rent, "url": path, "b8": 0/1}},
  "avail_updated": epoch seconds

Usage:  python3 scrape_affordablehousing.py
"""
import json
import time
import urllib.request
from pathlib import Path

from parse_apify import build_index, normalize_addr

HERE = Path(__file__).parent
BUILDINGS = HERE / "buildings.min.json"
OUT = HERE / "s8.json"

API = "https://www.affordablehousing.com/v4/AjaxHandler?message=SearchListings"
SITE = "https://www.affordablehousing.com"
COUNTY_TO_BOROUGH = {"New York": "M", "Bronx": "Bx", "Kings": "Bk",
                     "Queens": "Q", "Richmond": "SI"}
PER_PAGE = 32
PAUSE = 1.0          # seconds between requests — stay polite
RENT_MIN, RENT_MAX = 300, 50000


def search(county, page):
    body = {"searchParameters": {
        "landlordUserId": 0, "state": "ny", "county": county, "city": "",
        "zip": "", "brand": "", "minPrice": 0, "maxPrice": 0,
        "hasSection8Voucher": False, "yearlyIncome": 0, "familySize": -1,
        "voucherSize": -1, "isExcludeExceedsEligibility": False,
        "bedCounts": "", "requiredMoreBedCounts": 0, "bathCount": 0,
        "sortExpression": "LastUpdate Desc", "itemsPerPage": PER_PAGE,
        "page": page, "returnOnlyCount": False, "minLivingArea": 0,
        "maxLivingArea": 0, "propertyTypeCategories": "", "keywordSearch": "",
        "returnIdsOnly": False, "isNewLocation": 0, "isIncludeMapListing": False,
        "maxLatitude": "0", "maxLongitude": "0", "minLatitude": "0",
        "minLongitude": "0", "maxMarkerToShow": 500, "schoolId": 0,
        "NCESSchoolID": 0, "education": "", "pos": "", "zoom": "",
        "center": "", "isNearOrMeetIncomeResultsOnly": False,
        "enterpriseId": ""}}
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{SITE}/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/126.0.0.0 Safari/537.36",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    records = json.loads(BUILDINGS.read_text())
    addr_idx = {b: build_index([r for r in records if r["b"] == b])
                for b in ("M", "Bx", "Bk", "Q", "SI")}

    avail = {}
    total = matched = 0
    for county, boro in COUNTY_TO_BOROUGH.items():
        page, pages = 1, 1
        while page <= pages:
            for attempt in range(3):
                try:
                    d = search(county, page)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    print(f"{county} p{page}: {e} — retrying")
                    time.sleep(10 * (attempt + 1))
            params = d.get("searchListingsParameters") or {}
            pages = params.get("PageCount") or 1
            listings = d.get("listings") or []
            for l in listings:
                total += 1
                bbl = addr_idx[boro].get(normalize_addr(l.get("AddressLine1") or ""))
                if not bbl:
                    continue
                matched += 1
                rent = l.get("MinAskingRent") or 0
                cur = avail.setdefault(bbl, {"n": 0, "p": None, "url": None, "b8": 0})
                cur["n"] += 1
                if l.get("ShowSection8Badge"):
                    cur["b8"] = 1
                if RENT_MIN <= rent <= RENT_MAX and (cur["p"] is None or rent < cur["p"]):
                    cur["p"] = int(rent)
                    if l.get("SeoFriendlyRentalUrl"):
                        cur["url"] = SITE + l["SeoFriendlyRentalUrl"]
            if not listings:
                break
            page += 1
            time.sleep(PAUSE)
        print(f"{county} ({boro}): scanned through p{page - 1}/{pages}")

    payload = {"avail": avail, "avail_updated": int(time.time())}
    if OUT.exists():  # keep the building half from fetch_section8.py
        old = json.loads(OUT.read_text())
        payload["updated"] = old.get("updated")
        payload["bldg"] = old.get("bldg", {})
    else:
        payload["updated"] = None
        payload["bldg"] = {}
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"listings scanned: {total}  matched to DHCR map: {matched}  "
          f"buildings with live voucher listings: {len(avail)}")


if __name__ == "__main__":
    main()
