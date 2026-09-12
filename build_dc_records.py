#!/usr/bin/env python3
"""Attach assessor and owner-of-record detail to dc/buildings.min.json.

DHCD's RentRegistry knows a property is rent-controlled and what its units rent
for; it does not know when the building went up, how it is laid out, or who owns
it. DC's other open data does, and the registration carries the key: every
registration has a Master Address Repository id (`BBL MAR ID` — DC's "BBL" is a
Basic Business License, not a lot number), and DCGIS publishes an unauthenticated
MAR-to-lot cross-reference. So:

    MAR id ──▶ SSL (square/suffix/lot) ──▶ CAMA  year built, rooms, beds, baths
                                      └──▶ ITSPE owner of record, assessed value
                                      └──▶ vacant / blighted register

  Location_WebMercator/7   Address and Square Suffix Lot Cross Reference (240k)
  Property_and_Land/25     CAMA Residential      AYB/EYB, ROOMS, BEDRM, BATHRM
  Property_and_Land/24     CAMA Condominium      the same for condo units
  Property_and_Land/23     CAMA Commercial       AYB/EYB and unit count only
  ITSPE_08172026           Integrated Tax System OWNERNAME, assessed value
  Property_and_Land/82     Vacant and Blighted Building Addresses

What DC has no equivalent of: housing-code violations. The Department of
Buildings publishes none — that one NYC feature genuinely cannot be matched
here, and the UI says so rather than showing an empty panel.

Writes, in place:
    dc/buildings.min.json   + `yr` and `h` on each property that resolves

Then run `python3 split_hpd.py --docroot dc`.

Usage:
    python3 build_dc_records.py
    python3 build_dc_records.py --cache DIR   # reuse an earlier download
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
BUILDINGS = HERE / "dc" / "buildings.min.json"
CACHE = HERE / "dc_raw"

DCGIS = "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA"
XREF = f"{DCGIS}/Location_WebMercator/FeatureServer/7/query"
CAMA_RES = f"{DCGIS}/Property_and_Land_WebMercator/FeatureServer/25/query"
CAMA_CONDO = f"{DCGIS}/Property_and_Land_WebMercator/FeatureServer/24/query"
CAMA_COMM = f"{DCGIS}/Property_and_Land_WebMercator/FeatureServer/23/query"
VACANT = f"{DCGIS}/Property_and_Land_WebMercator/FeatureServer/82/query"
ITSPE = ("https://services.arcgis.com/neT9SoYxizqTHZPH/arcgis/rest/services/"
         "ITSPE_08172026/FeatureServer/0/query")

PAGE = 2000            # ArcGIS maxRecordCount on these services

# CAMA codes the assessor's condition as an integer. 0 and 1 are "unknown" and
# "poor"; the scale tops out at 6. Only shown when it is actually on file.
CONDITION = {1: "Poor", 2: "Fair", 3: "Average", 4: "Good",
             5: "Very good", 6: "Excellent"}

# ITSPE truncates PROPTYPE at 30 characters, so the wire carries half-words
# ("Residential-Multi-Family (3 to", "Residential-Apartment (Elevato"). Map the
# truncated forms back to whole English before either client shows one.
PROPTYPE = {
    "Residential-Apartment (Walkup)": "Walk-up apartment building",
    "Residential-Apartment (Elevato": "Elevator apartment building",
    "Residential-Multi-Family (3 to": "Multi-family (3 to 4 units)",
    "Residential-Conversion (2 Unit": "Converted house (2 units)",
    "Residential-Condominium (Horiz": "Condominium",
    "Residential-Condominium (Verti": "Condominium",
    "Residential-Flats (2 Units)": "Two-flat",
    "Residential-Cooperative (Horiz": "Housing cooperative",
    "Residential-Cooperative (Verti": "Housing cooperative",
    "Residential-Single Family (Row": "Rowhouse",
    "Residential-Single Family (Det": "Detached house",
    "Residential-Single Family (Sem": "Semi-detached house",
}


def proptype(raw):
    t = (raw or "").strip()
    if not t:
        return None
    if t in PROPTYPE:
        return PROPTYPE[t]
    # An unmapped value is still better than nothing, but never show a word cut
    # in half: drop a trailing fragment and any orphaned open bracket.
    t = t.split("(")[0].strip(" -")
    return t or None


def get(url, params, retries=4):
    qs = urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{url}?{qs}",
                                         headers={"User-Agent": "findacrib-dc/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"    {e} — retry {attempt + 1}", flush=True)
            time.sleep(3 * (attempt + 1))


def fetch_layer(url, fields, label, cache_dir, where="1=1"):
    """Every row of an ArcGIS layer, paged. resultOffset is honoured by both
    the DCGIS MapServer and the ArcGIS Online feature service."""
    slug = label.replace(" ", "_").lower()
    cached = cache_dir / f"dcgis_{slug}.json" if cache_dir else None
    if cached and cached.exists():
        rows = json.loads(cached.read_text())
        print(f"    {len(rows):,} rows (cached)", flush=True)
        return rows
    rows, offset = [], 0
    while True:
        d = get(url, {"where": where, "outFields": fields, "returnGeometry": "false",
                      "resultOffset": offset, "resultRecordCount": PAGE,
                      "orderByFields": "OBJECTID", "f": "json"})
        feats = d.get("features", [])
        rows.extend(f["attributes"] for f in feats)
        if len(feats) < PAGE:
            break
        offset += PAGE
        if offset % 50000 == 0:
            print(f"    {len(rows):,} …", flush=True)
    print(f"    {len(rows):,} rows", flush=True)
    if cached:
        cache_dir.mkdir(exist_ok=True)
        cached.write_text(json.dumps(rows, separators=(",", ":")))
    return rows


def as_int(v):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n


def year(v):
    n = as_int(v)
    return n if n and 1750 <= n <= 2030 else None


def clean_ssl(v):
    """SSLs arrive padded ("1125    0029"); collapse the run of spaces so the
    three sources agree on one spelling."""
    return " ".join(str(v or "").split())


def title_owner(name):
    """"TAGHEU, THIERRY W" -> "Taghreu, Thierry W". Company suffixes and short
    all-caps tokens (LLC, LP, DC, NW) stay upper — a name is a person's, and
    shouting it back at them looks like a data dump."""
    keep = {"LLC", "L.L.C.", "LP", "L.P.", "LLP", "INC", "INC.", "LTD", "CO",
            "CORP", "TR", "NA", "DC", "NE", "NW", "SE", "SW", "II", "III", "IV",
            "JR", "SR", "PLLC", "LC", "REIT", "USA", "HOA"}
    out = []
    for w in str(name or "").split():
        core = w.strip(",.")
        out.append(w if core.upper() in keep else w.capitalize())
    return " ".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    cache_dir = None if args.no_cache else Path(args.cache)

    if not BUILDINGS.exists():
        raise SystemExit(f"no {BUILDINGS} — run build_dc.py first")
    recs = json.loads(BUILDINGS.read_text())
    want = {r["mar"] for r in recs if r.get("mar")}
    print(f"{len(recs):,} DC properties, {len(want):,} with a MAR id\n")

    print("fetching MAR -> SSL cross reference …", flush=True)
    xref_rows = fetch_layer(XREF, "MARID,SSL", "xref", cache_dir)
    mar_ssl = {}
    for r in xref_rows:
        m, ssl = as_int(r.get("MARID")), clean_ssl(r.get("SSL"))
        if m is not None and ssl:
            mar_ssl.setdefault(m, ssl)
    resolved = sum(1 for m in want if m in mar_ssl)
    print(f"  {resolved:,} of {len(want):,} MAR ids resolve to a lot "
          f"({resolved/max(len(want),1)*100:.1f}%)\n")

    print("fetching CAMA residential …", flush=True)
    cama = {}
    for row in fetch_layer(CAMA_RES, "SSL,AYB,EYB,NUM_UNITS,ROOMS,BEDRM,BATHRM,CNDTN",
                           "cama_res", cache_dir):
        ssl = clean_ssl(row.get("SSL"))
        if ssl:
            cama.setdefault(ssl, row)
    # The condo layer has no CNDTN column, and ArcGIS answers a request naming
    # a field it does not have with an empty feature list rather than an error
    # — which reads exactly like "this layer is empty" (it has 61k rows).
    print("fetching CAMA condominium …", flush=True)
    for row in fetch_layer(CAMA_CONDO, "SSL,AYB,EYB,ROOMS,BEDRM,BATHRM,YR_RMDL",
                           "cama_condo", cache_dir):
        ssl = clean_ssl(row.get("SSL"))
        if ssl:
            cama.setdefault(ssl, row)
    print("fetching CAMA commercial …", flush=True)
    for row in fetch_layer(CAMA_COMM, "SSL,AYB,EYB,NUM_UNITS", "cama_comm", cache_dir):
        ssl = clean_ssl(row.get("SSL"))
        if ssl:
            cama.setdefault(ssl, row)
    print(f"  {len(cama):,} lots with assessor detail\n")

    print("fetching Integrated Tax System (owner of record) …", flush=True)
    itspe = {}
    for row in fetch_layer(ITSPE, "SSL,OWNERNAME,PROPTYPE,NEWLAND,NEWIMPR,LANDAREA",
                           "itspe", cache_dir):
        ssl = clean_ssl(row.get("SSL"))
        if ssl:
            itspe.setdefault(ssl, row)
    print(f"  {len(itspe):,} lots with an owner of record\n")

    print("fetching vacant & blighted register …", flush=True)
    vac = {}
    for row in fetch_layer(VACANT, "SSL,STATUS", "vacant", cache_dir):
        ssl = clean_ssl(row.get("SSL"))
        if ssl:
            vac.setdefault(ssl, (row.get("STATUS") or "").strip())
    print(f"  {len(vac):,} lots on the register\n")

    hit = defaultdict(int)
    for rec in recs:
        ssl = mar_ssl.get(rec.get("mar"))
        if not ssl:
            continue
        hit["lot"] += 1
        h = dict(rec.get("h") or {})
        h["ssl"] = ssl

        c = cama.get(ssl)
        if c:
            hit["assessor"] += 1
            yr = year(c.get("AYB"))
            if yr:
                rec["yr"] = yr
                hit["yr"] += 1
            ren = year(c.get("EYB"))
            # EYB is the "effective" year — the assessor's read of when the
            # structure was last brought up to date. Only worth showing when it
            # is meaningfully later than the build, which is what a renter would
            # read as "it has been renovated since".
            if ren and yr and ren >= yr + 10:
                h["renov"] = ren
            for key, col in (("rooms", "ROOMS"), ("beds", "BEDRM"), ("baths", "BATHRM")):
                n = as_int(c.get(col))
                if n and n > 0:
                    h[key] = n
            cond = CONDITION.get(as_int(c.get("CNDTN")) or 0)
            if cond:
                h["cond"] = cond
            tot = as_int(c.get("NUM_UNITS"))
            if tot and tot > 0:
                h["units_total"] = tot

        o = itspe.get(ssl)
        if o:
            hit["owner"] += 1
            name = title_owner(o.get("OWNERNAME"))
            if name:
                h["owner"] = name
                # `op` is the flag both clients already read to decide whether
                # there is an operator worth showing at all.
                h["op"] = 1
            land, impr = as_int(o.get("NEWLAND")), as_int(o.get("NEWIMPR"))
            if land or impr:
                h["assessed"] = (land or 0) + (impr or 0)
            ptype = proptype(o.get("PROPTYPE"))
            if ptype:
                h["ptype"] = ptype

        if ssl in vac:
            hit["vacant_register"] += 1
            h["vacreg"] = vac[ssl] or "On the register"

        if len(h) > 1 or "ssl" not in h:
            rec["h"] = h

    BUILDINGS.write_text(json.dumps(recs, separators=(",", ":")))
    n = len(recs)
    print(f"wrote {BUILDINGS} ({BUILDINGS.stat().st_size/1e6:.2f} MB)")
    for k, label in (("lot", "resolved to a lot"), ("assessor", "assessor detail"),
                     ("yr", "year built"), ("owner", "owner of record"),
                     ("vacant_register", "on vacant register")):
        print(f"  {label:22s} {hit[k]:6,} ({hit[k]/n*100:5.1f}%)")
    print("\nnext: python3 split_hpd.py --docroot dc")


if __name__ == "__main__":
    sys.exit(main())
