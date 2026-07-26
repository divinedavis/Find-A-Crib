#!/usr/bin/env python3
"""Build dc/buildings.min.json from the DC Rent Registry public data exports.

Unlike LA (no building-level list, so we derive one) this is the real thing:
DHCD's RentRegistry — live since June 2025 — publishes nightly CSV dumps of the
whole registry, unauthenticated, at

    https://rccd-rentregistry-export-prod-...azurewebsites.net/api/ListExports

which returns {entity: [{name, url, size, lastModified}]} for three entities:

  registrations              one row per housing-provider registration (address,
                             BBL, owner/agent, total units)
  registered_accommodations  one row per registered property (lat/lng, ward,
                             registered + exempt unit counts, rent range)
  housing_accommodation_units  one row per *unit* (registered rent, vacancy,
                             per-unit exemption) — ~194k rows, ~97 MB

Coverage under the Rental Housing Act is a per-unit determination, not a
building one: a property can hold both covered and exempt units (§ 2.05(a)(1)–
(7) — subsidized, new construction, small landlord ≤4 units, co-op, …). So we
count coverage from the unit file, keep any property with at least one
non-exempt unit, and report the median *registered* rent of just those units.
That rent is the legal registered rent on file with DHCD, not an asking rent.

DC publishes no zip on the accommodation record and no neighborhood polygons
(only cluster polygons + neighborhood label points), so zip comes from a Census
ZCTA point-in-polygon and `nb` from the nearest DC neighborhood label point.

Usage:
  python3 build_dc.py                 # downloads ~130 MB of CSV into dc_raw/
  python3 build_dc.py --src dc_raw    # reuse an earlier download
"""
import argparse
import csv
import json
import math
import statistics
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "dc" / "buildings.min.json"
CACHE = HERE / "dc_raw"

LIST_EXPORTS = ("https://rccd-rentregistry-export-prod-c4c8bndgambyfxg8"
                ".eastus-01.azurewebsites.net/api/ListExports")

# Census 2020 ZCTAs (for zips) and DC's neighborhood label points (for `nb`).
ZCTA = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
        "PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1/query"
        "?geometry=-77.13,38.78,-76.89,39.01&geometryType=esriGeometryEnvelope"
        "&inSR=4326&spatialRel=esriSpatialRelIntersects"
        "&outFields=BASENAME&returnGeometry=true&outSR=4326&f=geojson")
NBH = ("https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/"
       "Administrative_Other_Boundaries_WebMercator/MapServer/18/query"
       "?where=1%3D1&outFields=NAME&returnGeometry=true&outSR=4326&f=geojson")

csv.field_size_limit(10 ** 9)


def get_json(url, timeout=120):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def download(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  reuse {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
        return dest
    print(f"  fetching {dest.name} …", flush=True)
    with urllib.request.urlopen(url, timeout=900) as r, dest.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    print(f"    {dest.stat().st_size/1e6:.1f} MB")
    return dest


def fetch_exports(src_dir):
    """Return {entity: Path} for the newest export of each entity."""
    src_dir.mkdir(exist_ok=True)
    manifest = get_json(LIST_EXPORTS)
    paths = {}
    for entity, files in manifest.items():
        newest = max(files, key=lambda f: f.get("lastModified", ""))
        print(f"{entity}: {newest['name']} ({newest.get('lastModified','?')})")
        paths[entity] = download(newest["url"], src_dir / f"{entity}.csv")
    return paths


def rows(path):
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        yield from csv.DictReader(f)


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def to_money(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    # registered rents below ~$100 are placeholders/data entry noise
    return n if 100 <= n < 100_000 else None


def unit_stats(path):
    """Per-accommodation stats over the *covered* (non-exempt) units."""
    stats = defaultdict(lambda: {"covered": 0, "exempt": 0, "vacant": 0, "rents": []})
    for r in rows(path):
        key = r.get("dhcd_registeredaccommodationlookup_value")
        if not key:
            continue
        s = stats[key]
        if r.get("Exempt") == "1":
            s["exempt"] += 1
            continue
        s["covered"] += 1
        if r.get("Vacant") == "1":
            s["vacant"] += 1
        rent = to_money(r.get("Rent")) or to_money(r.get("Total Rent"))
        if rent:
            s["rents"].append(rent)
    return stats


def load_polys(url):
    """[(name, shapely geom)] from an ArcGIS geojson query."""
    from shapely.geometry import shape
    out = []
    for f in get_json(url)["features"]:
        if f.get("geometry"):
            out.append((f["properties"].get("BASENAME") or f["properties"].get("NAME"),
                        shape(f["geometry"])))
    return out


def load_points(url):
    return [(f["properties"]["NAME"], f["geometry"]["coordinates"])
            for f in get_json(url)["features"] if f.get("geometry")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(CACHE),
                    help="dir to cache the export CSVs in (default dc_raw/)")
    args = ap.parse_args()

    paths = fetch_exports(Path(args.src))

    print("\nreading registrations …", flush=True)
    reg = {r["Registration Id"]: r for r in rows(paths["registrations"])
           if r.get("Registration Id")}
    print(f"  {len(reg):,} registrations")

    print("reading units (this is the big one) …", flush=True)
    stats = unit_stats(paths["housing_accommodation_units"])
    print(f"  {len(stats):,} accommodations seen in the unit file")

    print("reading registered accommodations …", flush=True)
    accs = [a for a in rows(paths["registered_accommodations"])]
    print(f"  {len(accs):,} accommodations")

    print("\nloading geographies …", flush=True)
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    zctas = load_polys(ZCTA)
    ztree = STRtree([g for _, g in zctas])
    znames = [n for n, _ in zctas]
    nbh = load_points(NBH)
    print(f"  {len(zctas)} ZCTAs, {len(nbh)} neighborhood points")

    def zip_for(lat, lng):
        p = Point(lng, lat)
        for i in ztree.query(p):
            if zctas[i][1].covers(p):
                return znames[i]
        return ""

    def nb_for(lat, lng):
        # equirectangular is plenty at DC's scale and avoids a dependency
        best, bestd = None, 1e9
        clat = math.cos(math.radians(lat))
        for name, (nlng, nlat) in nbh:
            d = ((nlat - lat) ** 2) + ((nlng - lng) * clat) ** 2
            if d < bestd:
                best, bestd = name, d
        return best

    slim = {}
    skipped_geo = skipped_cov = skipped_inactive = 0
    for a in accs:
        if a.get("Status Code") != "1":       # 1 = active registration
            skipped_inactive += 1
            continue
        acc_id = a.get("Registered Accommodation Id")
        s = stats.get(acc_id)

        # Prefer the per-unit tally; fall back to the accommodation's own counts
        # for the handful of properties with no rows in the unit file.
        if s and (s["covered"] or s["exempt"]):
            covered = s["covered"]
        else:
            covered = max(to_int(a.get("No of Registered Unit"))
                          - to_int(a.get("No of Exempt Units")), 0)
        if covered < 1:
            skipped_cov += 1
            continue

        try:
            lat = round(float(a["Latitude"]), 6)
            lng = round(float(a["Longitude"]), 6)
        except (KeyError, TypeError, ValueError):
            skipped_geo += 1
            continue
        if not (38.7 < lat < 39.1 and -77.2 < lng < -76.8):
            skipped_geo += 1
            continue

        r = reg.get(a.get("Registration Lookup Value")) or {}
        addr = (r.get("BBL Site Address") or "").strip()
        if not addr:
            addr = (a.get("Commercial Name") or "").strip()
        if not addr:
            skipped_geo += 1
            continue

        rec = {
            "bbl": f"DC-{r.get('Registration Number') or acc_id[:12]}",
            "b": "DC",
            "a": " ".join(addr.split()),
            "z": "",
            "lat": lat,
            "lng": lng,
            "s": ["DC RENT CONTROL (REGISTERED)"],
            "yr": None,
            "u": covered,
            "nb": None,
        }
        if s and len(s["rents"]) >= 3:
            rec["mr"] = int(statistics.median(s["rents"]))
        if s and s["vacant"]:
            rec["vac"] = s["vacant"]

        # One property can re-register; keep the record with the most covered units.
        key = (rec["a"].upper(), round(lat, 5), round(lng, 5))
        if key not in slim or slim[key]["u"] < rec["u"]:
            slim[key] = rec

    out = sorted(slim.values(), key=lambda x: x["bbl"])
    print(f"\nassigning zip + neighborhood to {len(out):,} records …", flush=True)
    for rec in out:
        rec["z"] = zip_for(rec["lat"], rec["lng"])
        rec["nb"] = nb_for(rec["lat"], rec["lng"])

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))

    units = sum(r["u"] for r in out)
    with_rent = sum(1 for r in out if "mr" in r)
    with_zip = sum(1 for r in out if r["z"])
    print(f"\nWrote {OUT} ({OUT.stat().st_size/1e6:.2f} MB)")
    print(f"  {len(out):,} rent-controlled properties, {units:,} covered units")
    print(f"  {with_rent:,} with a median registered rent, {with_zip:,} with a zip")
    print(f"  skipped: {skipped_inactive:,} inactive, {skipped_cov:,} fully exempt, "
          f"{skipped_geo:,} missing address/coords")


if __name__ == "__main__":
    sys.exit(main())
