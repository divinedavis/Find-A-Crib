#!/usr/bin/env python3
"""Open NYC Housing Connect lotteries, for the tiles in the results grid.

This is the city's own pipeline: HPD runs the affordable-housing lottery and
publishes every open one through a public API. No key, no scraping, no browser
— unlike the re-rental boards in featured_rerentals.py, which are 14 small
agency websites held together with a DOM heuristic.

    POST https://a806-housingconnectapi.nyc.gov/HPDPublicAPI/api/Lottery/SearchLotteries

WHY THIS IS NOT THE SAME AS THE "FEATURED" TILES, and must not be merged with
them: a Housing Connect listing is a LOTTERY — you apply by a deadline and are
picked by log number. A re-rental is a vacated affordable unit that does NOT go
back into a lottery, usually first-come first-served. Telling someone to "apply
now" on a lottery that closes Tuesday, or implying a first-come unit is a
lottery, is a materially different instruction. The two feeds stay separate and
carry different badges.

Deadlines are short — the closest in the current set expires in 2 days — so
this runs daily and every tile prints its own countdown. A stale lottery tile
is worse than no tile: it sends someone to an application they cannot file.

    python3 housing_connect.py                  # fetch, print what's open
    python3 housing_connect.py --apply          # write housing_connect.json
    python3 housing_connect.py --apply --deploy # ...and scp it to the droplet
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "housing_connect.json")
DROPLET = "root@104.236.120.144:/var/www/rent-map/"
API = ("https://a806-housingconnectapi.nyc.gov/HPDPublicAPI/api/Lottery/SearchLotteries")
DETAILS = "https://housingconnect.nyc.gov/PublicWeb/details/"

# The empty arrays are load-bearing. Omit UnitTypes / NearbyPlaces /
# NearbySubways / Amenities and the endpoint answers 500, not 400 — it took a
# packet capture of the real site to find that, so do not "tidy" them away.
SEARCH_BODY = {
    "UnitTypes": [], "NearbyPlaces": [], "NearbySubways": [], "Amenities": [],
    "Applied": None, "HPDUserId": None, "Boroughs": [], "Neighborhoods": [],
    "HouseholdSize": None, "Income": "", "HouseholdType": 1, "OwnerTypes": [],
    "PreferanceTypes": [], "LotteryTypes": [], "Min": None, "Max": None,
    "RentalSubsidy": None,
}
UA = ("Mozilla/5.0 (compatible; FindACribBot/1.0; +https://findacrib.com/) "
      "Chrome/126.0 Safari/537.36")


def fetch():
    req = urllib.request.Request(
        API, data=json.dumps(SEARCH_BODY).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 "Origin": "https://housingconnect.nyc.gov",
                 "Referer": "https://housingconnect.nyc.gov/"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def money(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def parse_rents(raw):
    """"1328,1660" -> (1328, 1660). One value means one rent, not a range."""
    vals = sorted(v for v in (money(x) for x in str(raw or "").split(",")) if v)
    if not vals:
        return None, None
    return vals[0], vals[-1]


def beds(rec):
    """Which unit sizes this lottery actually has. The API returns a count per
    size and 0/None for the ones it doesn't offer."""
    out = []
    for key, label in (("studios", "Studio"), ("oneBR", "1-bed"), ("twoBR", "2-bed"),
                       ("threeBR", "3-bed"), ("fourBR", "4-bed"), ("fiveBR", "5-bed"),
                       ("sixBR", "6-bed")):
        if rec.get(key):
            out.append(label)
    return out


def one(rec):
    lo, hi = parse_rents(rec.get("rents"))
    marks = rec.get("markers") or []
    m = marks[0] if marks else {}
    lat = lng = None
    try:
        lat, lng = float(m.get("lat")), float(m.get("lng"))
    except (TypeError, ValueError):
        pass
    return {
        "id": rec.get("lotteryId"),
        "name": (rec.get("lotteryName") or "").strip(),
        "borough": (rec.get("borough") or "").strip(),
        "neighborhood": (rec.get("neighborhood") or "").strip(),
        "address": (m.get("address") or "").strip().title() or None,
        "zip": (m.get("zip") or "").strip() or None,
        "lat": lat, "lng": lng,
        "rent_low": lo, "rent_high": hi,
        "income_min": money(rec.get("minIncome")),
        "income_max": money(rec.get("maxIncome")),
        "household_min": rec.get("minHouseholdSize"),
        "household_max": rec.get("maxHouseholdSize"),
        "beds": beds(rec),
        # Days left to apply. The tile prints this, because a lottery closing
        # on Tuesday and one closing in a month are not the same offer.
        "days_left": rec.get("endIn"),
        "closes": (rec.get("lotteryEndDate") or "")[:10] or None,
        "href": DETAILS + str(rec.get("lotteryId")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write housing_connect.json")
    ap.add_argument("--deploy", action="store_true", help="scp the result to the droplet")
    ap.add_argument("--out", help="write into this docroot directly (droplet-side)")
    args = ap.parse_args()

    try:
        data = fetch()
    except Exception as e:
        print(f"housing_connect: fetch failed — {type(e).__name__}: {str(e)[:120]}")
        return 1

    rentals = data.get("rentals") or []
    # Sales are ownership lotteries (HDFC co-ops etc). This site is about
    # renting, and mixing "buy this apartment" into a rental grid is noise.
    out = [one(r) for r in rentals]
    # Only what someone can still apply to, soonest deadline first — the tile
    # is a call to action and the urgent one should lead.
    out = [o for o in out if (o["days_left"] or 0) > 0]
    out.sort(key=lambda o: (o["days_left"], -(o["rent_low"] or 0)))

    payload = {"generated": __import__("datetime").date.today().isoformat(),
               "source": "NYC Housing Connect (HPD public API)",
               "count": len(out), "lotteries": out}

    print(f"{len(out)} open rental lotteries ({len(rentals)} returned, "
          f"{len(rentals) - len(out)} already closed)")
    for o in out[:8]:
        rent = (f"${o['rent_low']:,}" + (f"–${o['rent_high']:,}"
                if o["rent_high"] and o["rent_high"] != o["rent_low"] else "")
                if o["rent_low"] else "see listing")
        print(f"  {o['days_left']:>3}d  {o['borough'][:9]:9}  "
              f"{o['name'][:40]:40}  {rent}")

    if not args.apply:
        print("\n(dry run — pass --apply to write housing_connect.json)")
        return 0

    # An empty feed is written on purpose: it is how the grid learns that
    # nothing is open, rather than serving yesterday's expired lotteries.
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    print(f"wrote {OUT}")
    if args.out:
        with open(os.path.join(args.out, "housing_connect.json"), "w") as f:
            json.dump(payload, f, indent=1, ensure_ascii=False)
        print(f"wrote {os.path.join(args.out, 'housing_connect.json')}")
    if args.deploy:
        subprocess.run(["scp", "-q", OUT, DROPLET + "housing_connect.json"], check=True)
        print("deployed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
