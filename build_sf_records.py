#!/usr/bin/env python3
"""Attach ZIPs and Rent Board case history to sf/buildings.min.json.

SF's answer to NYC's HPD blob, within the limit the source imposes: the Rent
Board anonymizes to the block, so every record here is a block-side. What makes
that workable is that the Rent Board's OTHER public datasets are anonymized the
exact same way — "600 Block Of Ellis Street" — so they join to our blocks on the
address string itself:

  5cei-gny5  Eviction notices    block address + 16 just-cause reason flags
  6swy-cmkq  Petitions           block address, landlord vs tenant, grounds
  wmam-7g8d  Buyout agreements   FULL street address + point, so bucketed to
                                 its block by number (336 Guerrero -> 300 Block)

SF publishes no housing-code violations that can be tied to a block — DBI cites
real addresses, and mapping those onto anonymized blocks would invent precision
the source deliberately removed. So SF gets eviction/petition history where NYC
gets violations, and the UI says which.

ZIPs: the inventory carries none at all (`z` has been "" on every SF record
since the city shipped), so they come from a Census 2020 ZCTA point-in-polygon,
the same way build_dc.py fills DC's.

Writes, in place:
    sf/buildings.min.json   + `z` and `h` on each block that has them

Then run `python3 split_hpd.py --docroot sf`.

Usage:
    python3 build_sf_records.py
    python3 build_sf_records.py --cache DIR   # reuse an earlier download
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
BUILDINGS = HERE / "sf" / "buildings.min.json"
CACHE = HERE / "sf_raw"

SOC = "https://data.sf.gov/resource/{}.json"
PAGE = 50_000

# Census 2020 ZCTAs over the SF peninsula.
ZCTA = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
        "PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1/query"
        "?geometry=-122.55,37.69,-122.32,37.84&geometryType=esriGeometryEnvelope"
        "&inSR=4326&spatialRel=esriSpatialRelIntersects"
        "&outFields=BASENAME&returnGeometry=true&outSR=4326&f=geojson")

NOW = datetime.now(timezone.utc)
YEAR_AGO = NOW - timedelta(days=365)
FIVE_YEARS_AGO = NOW - timedelta(days=365 * 5)

# The just-cause grounds an eviction notice can cite, as boolean columns.
# Grouped the way the Rent Ordinance does, because that is the distinction a
# sitting tenant needs: a no-fault ground means you can be made to leave
# without having done anything at all.
EVICTION_FAULT = [
    "non_payment", "breach", "nuisance", "illegal_use",
    "failure_to_sign_renewal", "access_denial", "unapproved_subtenant",
    "late_payments", "lead_remediation", "development", "good_samaritan_ends",
    "roommate_same_unit", "other_cause",
]
EVICTION_NO_FAULT = [
    "owner_move_in", "demolition", "capital_improvement", "substantial_rehab",
    "ellis_act_withdrawal", "condo_conversion",
]
REASON_LABEL = {
    "non_payment": "Non-payment of rent", "breach": "Breach of lease",
    "nuisance": "Nuisance", "illegal_use": "Illegal use",
    "failure_to_sign_renewal": "Refused to sign a renewal",
    "access_denial": "Denied access", "unapproved_subtenant": "Unapproved subtenant",
    "late_payments": "Habitual late payment", "lead_remediation": "Lead remediation",
    "development": "Development", "good_samaritan_ends": "Good Samaritan tenancy ended",
    "roommate_same_unit": "Roommate in the same unit", "other_cause": "Other",
    "owner_move_in": "Owner move-in", "demolition": "Demolition",
    "capital_improvement": "Capital improvement", "substantial_rehab": "Substantial rehab",
    "ellis_act_withdrawal": "Ellis Act withdrawal", "condo_conversion": "Condo conversion",
}

# Street-type words as the Rent Board spells them out in the eviction and
# petition files, against the abbreviations the inventory uses. Matching on the
# raw strings joins nothing: ours says "600 Block of ELLIS ST", theirs "600
# Block Of Ellis Street".
SUFFIX = {
    "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "DRIVE": "DR",
    "COURT": "CT", "PLACE": "PL", "ROAD": "RD", "TERRACE": "TER",
    "LANE": "LN", "CIRCLE": "CIR", "ALLEY": "ALY", "HIGHWAY": "HWY",
    "PARKWAY": "PKWY", "PLAZA": "PLZ", "SQUARE": "SQ", "WALK": "WALK",
    "WAY": "WAY", "STEPS": "STEPS", "ROW": "ROW", "PARK": "PARK",
}
BLOCK_RE = re.compile(r"^\s*(\d+)\s+BLOCK\s+OF\s+(.*)$", re.I)


def get(url, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "findacrib-sf/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def fetch_all(dataset, cache_dir):
    cached = cache_dir / f"{dataset}.json" if cache_dir else None
    if cached and cached.exists():
        rows = json.loads(cached.read_text())
        print(f"    {len(rows):,} rows (cached)", flush=True)
        return rows
    rows, offset = [], 0
    while True:
        qs = urllib.parse.urlencode({"$limit": PAGE, "$offset": offset, "$order": ":id"})
        chunk = get(f"{SOC.format(dataset)}?{qs}")
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE
    print(f"    {len(rows):,} rows", flush=True)
    if cached:
        cache_dir.mkdir(exist_ok=True)
        cached.write_text(json.dumps(rows, separators=(",", ":")))
    return rows


def norm_street(name):
    """"Ellis Street" -> "ELLIS ST". Directionals stay; only the type word is
    abbreviated, and only when it is the last word."""
    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper()).split()
    if not words:
        return ""
    if words[-1] in SUFFIX:
        words[-1] = SUFFIX[words[-1]]
    return " ".join(words)


def block_key(addr):
    """"600 Block Of Ellis Street" -> ("600", "ELLIS ST")."""
    m = BLOCK_RE.match(addr or "")
    if not m:
        return None
    return (str(int(m.group(1))), norm_street(m.group(2)))


def street_key(addr):
    """"336 Guerrero Street" -> ("300", "GUERRERO ST") — a full address bucketed
    into the hundred-block the inventory would have anonymized it to."""
    m = re.match(r"^\s*(\d+)\s+(.*)$", (addr or "").strip())
    if not m:
        return None
    num = int(m.group(1))
    return (str(num // 100 * 100), norm_street(m.group(2)))


def parse_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def truthy(v):
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    cache_dir = None if args.no_cache else Path(args.cache)

    if not BUILDINGS.exists():
        raise SystemExit(f"no {BUILDINGS} — run build_sf.py first")
    recs = json.loads(BUILDINGS.read_text())
    print(f"{len(recs):,} SF block records\n")

    # index our blocks by (number, normalized street)
    index = defaultdict(list)
    for rec in recs:
        k = block_key(rec["a"])
        if k:
            index[k].append(rec)
    print(f"{len(index):,} distinct block keys\n")

    print("fetching eviction notices (5cei-gny5) …", flush=True)
    evictions = fetch_all("5cei-gny5", cache_dir)
    print("fetching Rent Board petitions (6swy-cmkq) …", flush=True)
    petitions = fetch_all("6swy-cmkq", cache_dir)
    print("fetching buyout agreements (wmam-7g8d) …", flush=True)
    buyouts = fetch_all("wmam-7g8d", cache_dir)

    ev = defaultdict(lambda: {"total": 0, "nofault": 0, "last_12mo": 0,
                              "recent": 0, "reasons": defaultdict(int)})
    zips = {}
    miss_ev = 0
    for r in evictions:
        k = block_key(r.get("address"))
        if not k or k not in index:
            miss_ev += 1
            continue
        s = ev[k]
        s["total"] += 1
        if any(truthy(r.get(f)) for f in EVICTION_NO_FAULT):
            s["nofault"] += 1
        d = parse_dt(r.get("file_date"))
        if d:
            if d >= YEAR_AGO:
                s["last_12mo"] += 1
            if d >= FIVE_YEARS_AGO:
                s["recent"] += 1
        for f in EVICTION_FAULT + EVICTION_NO_FAULT:
            if truthy(r.get(f)):
                s["reasons"][f] += 1
        z = (r.get("zip") or "").strip()[:5]
        if z.isdigit():
            zips.setdefault(k, z)

    pet = defaultdict(lambda: {"total": 0, "landlord": 0, "tenant": 0, "recent": 0})
    miss_pet = 0
    for r in petitions:
        k = block_key(r.get("address"))
        if not k or k not in index:
            miss_pet += 1
            continue
        s = pet[k]
        s["total"] += 1
        party = (r.get("filing_party") or "").strip().lower()
        if party == "landlord":
            s["landlord"] += 1
        elif party == "tenant":
            s["tenant"] += 1
        d = parse_dt(r.get("date_filed"))
        if d and d >= FIVE_YEARS_AGO:
            s["recent"] += 1
        z = (r.get("petition_source_zipcode") or "").strip()[:5]
        if z.isdigit():
            zips.setdefault(k, z)

    by = defaultdict(lambda: {"n": 0, "amounts": [], "recent": 0})
    miss_by = 0
    for r in buyouts:
        k = street_key(r.get("address"))
        if not k or k not in index:
            miss_by += 1
            continue
        s = by[k]
        s["n"] += 1
        try:
            amt = int(float(str(r.get("buyout_amount") or "").replace(",", "").replace("$", "")))
        except ValueError:
            amt = 0
        if amt > 0:
            s["amounts"].append(amt)
        d = parse_dt(r.get("buyout_agreement_date") or r.get("pre_buyout_disclosure_declaration_date"))
        if d and d >= FIVE_YEARS_AGO:
            s["recent"] += 1
        z = (r.get("zip_code") or "").strip()[:5]
        if z.isdigit():
            zips.setdefault(k, z)

    print(f"\n  evictions: {len(evictions) - miss_ev:,} of {len(evictions):,} matched a block "
          f"({miss_ev:,} unmatched)")
    print(f"  petitions: {len(petitions) - miss_pet:,} of {len(petitions):,} matched")
    print(f"  buyouts:   {len(buyouts) - miss_by:,} of {len(buyouts):,} matched")

    print("\nloading ZCTAs for ZIPs …", flush=True)
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree
    feats = get(ZCTA)["features"]
    polys = [(f["properties"]["BASENAME"], shape(f["geometry"]))
             for f in feats if f.get("geometry")]
    tree = STRtree([g for _, g in polys])
    names = [n for n, _ in polys]
    print(f"  {len(polys)} ZCTAs")

    def zip_for(lat, lng):
        p = Point(lng, lat)
        for i in tree.query(p):
            if polys[i][1].covers(p):
                return names[i]
        return ""

    def med(xs):
        xs = sorted(xs)
        if not xs:
            return None
        m = len(xs) // 2
        return xs[m] if len(xs) % 2 else int(round((xs[m - 1] + xs[m]) / 2))

    counts = defaultdict(int)
    for rec in recs:
        k = block_key(rec["a"])
        h = {}
        if k and k in ev:
            s = ev[k]
            top = sorted(s["reasons"].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            h["ev"] = {"total": s["total"], "nofault": s["nofault"],
                       "last_12mo": s["last_12mo"], "recent": s["recent"],
                       "reasons": [[REASON_LABEL.get(f, f), n] for f, n in top]}
            counts["ev"] += 1
        if k and k in pet:
            h["pet"] = pet[k]
            counts["pet"] += 1
        if k and k in by:
            s = by[k]
            h["by"] = {"n": s["n"], "med": med(s["amounts"]), "recent": s["recent"]}
            counts["by"] += 1
        if h:
            rec["h"] = h
        elif "h" in rec:
            del rec["h"]
        # The source's own ZIP where a case on this block reported one, and the
        # ZCTA otherwise — the polygon is complete but a reported ZIP is
        # authoritative where the block straddles a boundary.
        z = zips.get(k) or zip_for(rec["lat"], rec["lng"])
        rec["z"] = z or ""
        if z:
            counts["z"] += 1

    BUILDINGS.write_text(json.dumps(recs, separators=(",", ":")))
    n = len(recs)
    print(f"\nwrote {BUILDINGS} ({BUILDINGS.stat().st_size/1e6:.2f} MB)")
    with_zip = sum(1 for r in recs if r.get("z"))
    for k, label in (("ev", "evictions"), ("pet", "petitions"), ("by", "buyouts")):
        print(f"  {label:12s} {counts[k]:6,} blocks ({counts[k]/n*100:5.1f}%)")
    print(f"  {'ZIP':12s} {with_zip:6,} blocks ({with_zip/n*100:5.1f}%)")
    print("\nnext: python3 split_hpd.py --docroot sf")


if __name__ == "__main__":
    sys.exit(main())
