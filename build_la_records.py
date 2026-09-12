#!/usr/bin/env python3
"""Attach LAHD enforcement records and neighborhood names to la/buildings.min.json.

LA's answer to NYC's HPD blob. The Los Angeles Housing Department publishes a
"Property Look-Up" family on data.lacity.org, every one of them keyed by APN —
which is the same number build_la.py already stores as the record id (`LA-<AIN>`).
So these join exactly, with no address matching at all:

  ds2y-sb5t  CCRIS cases            complaints, open complaints, inspections
  cr8f-uc4j  Violations             one row per cited violation type
  eagk-wq48  Investigation cases    LAHD enforcement case open/closed
  2u8b-eyuu  Eviction notices       at-fault vs no-fault, notice type
  ci3m-f23k  Tenant buyouts         with the compensation amount
  vpax-89xu  Landlord declarations  the RSO landlord-declaration cases

Coverage measured 2026-09-12 against the 67,511 parcels build_la.py emits:
CCRIS reaches 66,778 of them (98.9%) — the same near-total coverage HPD gives
NYC. The others are sparser by nature (7.5k parcels have an eviction filing).

Two things do NOT map onto the NYC shape, and the UI must not pretend they do:

  * LA does not grade violations A/B/C. There is no hazard class to colour by,
    so no class chips — the case type (SCEP / Complaint / TIER 2) is the
    closest thing and is carried as `types`.
  * cr8f-uc4j is a ROLLING WINDOW, not an all-time register. As of this writing
    it holds citations from 2025-11-04 to 2026-07-31 only. `total` therefore
    means "cited in the window", and `window` carries the dates so the client
    can say so rather than implying an all-time count. CCRIS, by contrast, does
    go back to 1986 and its totals are genuinely all-time.

Neighborhoods come from the LA Times Mapping L.A. boundaries on GeoHub — LA's
parcel source carries none at all, which is why every LA record has had
`nb: null` since the city shipped and the neighborhood filter has been empty.

Writes, in place:
    la/buildings.min.json   + `h` and `nb` on each parcel that has them

Then run `python3 split_hpd.py --docroot la` to produce the boot/lazy split,
exactly as NYC does.

Usage:
    python3 build_la_records.py              # fetch everything (~655k rows)
    python3 build_la_records.py --cache DIR  # reuse an earlier download
"""
import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
BUILDINGS = HERE / "la" / "buildings.min.json"
CACHE = HERE / "la_raw"

SOC = "https://data.lacity.org/resource/{}.json"
PAGE = 50_000          # Socrata's per-request ceiling

# LA Times Mapping L.A. neighborhoods, via the city's GeoHub ArcGIS service.
NBH = ("https://services5.arcgis.com/7nsPwEMP38bSkCjy/arcgis/rest/services/"
       "LA_Times_Neighborhoods/FeatureServer/0/query"
       "?where=1%3D1&outFields=name&returnGeometry=true&outSR=4326&f=geojson")

DATASETS = {
    "ccris":        ("ds2y-sb5t", "CCRIS cases (complaints)"),
    "violations":   ("cr8f-uc4j", "violations"),
    "cases":        ("eagk-wq48", "investigation & enforcement cases"),
    "evictions":    ("2u8b-eyuu", "eviction notices"),
    "buyouts":      ("ci3m-f23k", "tenant buyouts"),
    "declarations": ("vpax-89xu", "landlord declarations"),
}

NOW = datetime.now(timezone.utc)
YEAR_AGO = NOW - timedelta(days=365)


def get(url, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "findacrib-la/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 3 * (attempt + 1)
            print(f"    {e} — retrying in {wait}s", flush=True)
            time.sleep(wait)


def fetch_all(dataset, cache_dir):
    """Every row of a Socrata dataset, paged. A bare $limit is a silent
    truncation — Socrata returns the cap with no hint that there was more."""
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
        print(f"    {len(rows):,} …", flush=True)
    print(f"    {len(rows):,} rows", flush=True)
    if cached:
        cache_dir.mkdir(exist_ok=True)
        cached.write_text(json.dumps(rows, separators=(",", ":")))
    return rows


def parse_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def as_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def as_money(v):
    try:
        n = float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return int(round(n)) if n > 0 else None


def median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else int(round((xs[m - 1] + xs[m]) / 2))


# ---------------------------------------------------------------- aggregation

def agg_violations(rows):
    """One row per cited violation type. `violations_cleared` is a 1/0 flag,
    not a date — a row with "0" is a violation still outstanding."""
    out = defaultdict(lambda: {"open": 0, "total": 0, "last_12mo": 0, "types": defaultdict(int)})
    lo = hi = None
    for r in rows:
        apn = (r.get("apn") or "").strip()
        if not apn:
            continue
        s = out[apn]
        s["total"] += 1
        if str(r.get("violations_cleared") or "").strip() != "1":
            s["open"] += 1
        cited = parse_dt(r.get("violations_cited"))
        if cited:
            lo = cited if lo is None or cited < lo else lo
            hi = cited if hi is None or cited > hi else hi
            if cited >= YEAR_AGO:
                s["last_12mo"] += 1
        t = (r.get("violationtype") or "").strip()
        if t:
            s["types"][t] += 1
    window = [lo.date().isoformat(), hi.date().isoformat()] if lo and hi else None
    for s in out.values():
        # Top few types only: the point is "what is wrong here", not a ledger.
        top = sorted(s["types"].items(), key=lambda kv: (-kv[1], kv[0]))[:6]
        s["types"] = [[t, n] for t, n in top]
    return out, window


def agg_ccris(rows):
    """CCRIS is the all-time complaint record — cases run back to 1986."""
    out = defaultdict(lambda: {"open": 0, "total": 0, "last_12mo": 0, "insp": 0})
    for r in rows:
        apn = (r.get("apn") or "").strip()
        if not apn:
            continue
        s = out[apn]
        s["total"] += as_int(r.get("totalcomplaintscount"))
        s["open"] += as_int(r.get("opencomplaintscount"))
        s["insp"] += as_int(r.get("scheduledinspectionscount"))
        start = parse_dt(r.get("start_date"))
        if start and start >= YEAR_AGO:
            s["last_12mo"] += as_int(r.get("totalcomplaintscount"))
    return out


def agg_cases(rows, filed_key, closed_key):
    out = defaultdict(lambda: {"open": 0, "total": 0})
    for r in rows:
        apn = (r.get("apn") or "").strip()
        if not apn:
            continue
        s = out[apn]
        s["total"] += 1
        if not (r.get(closed_key) or "").strip():
            s["open"] += 1
    return out


def agg_evictions(rows):
    """LA landlords must file every eviction notice on an RSO unit with LAHD.
    No-fault is the one that matters to a sitting tenant — Ellis Act, owner
    move-in, demolition — so it is broken out rather than buried in a total."""
    out = defaultdict(lambda: {"total": 0, "nofault": 0, "last_12mo": 0})
    for r in rows:
        apn = (r.get("apn") or "").strip()
        if not apn:
            continue
        s = out[apn]
        s["total"] += 1
        if (r.get("eviction_category") or "").strip().lower().startswith("no-fault"):
            s["nofault"] += 1
        d = parse_dt(r.get("notice_date"))
        if d and d >= YEAR_AGO:
            s["last_12mo"] += 1
    return out


def agg_buyouts(rows):
    out = defaultdict(lambda: {"n": 0, "amounts": []})
    for r in rows:
        apn = (r.get("apn") or "").strip()
        if not apn:
            continue
        s = out[apn]
        s["n"] += 1
        amt = as_money(r.get("compensation_amount"))
        if amt:
            s["amounts"].append(amt)
    return {k: {"n": v["n"], "med": median(v["amounts"])} for k, v in out.items()}


# ------------------------------------------------------------- neighborhoods

def load_neighborhoods():
    from shapely.geometry import shape
    feats = get(NBH)["features"]
    polys = []
    for f in feats:
        g, p = f.get("geometry"), f.get("properties") or {}
        name = p.get("name") or p.get("NAME")
        if g and name:
            polys.append((name, shape(g)))
    return polys


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=str(CACHE),
                    help="dir to cache the Socrata pulls in (default la_raw/)")
    ap.add_argument("--no-cache", action="store_true", help="always re-download")
    args = ap.parse_args()
    cache_dir = None if args.no_cache else Path(args.cache)

    if not BUILDINGS.exists():
        raise SystemExit(f"no {BUILDINGS} — run build_la.py first")
    recs = json.loads(BUILDINGS.read_text())
    print(f"{len(recs):,} LA parcels\n")

    raw = {}
    for key, (ds, label) in DATASETS.items():
        print(f"fetching {label} ({ds}) …", flush=True)
        raw[key] = fetch_all(ds, cache_dir)

    print("\naggregating by APN …", flush=True)
    viol, vwindow = agg_violations(raw["violations"])
    ccris = agg_ccris(raw["ccris"])
    cases = agg_cases(raw["cases"], "case_filed_date", "closed_date")
    decls = agg_cases(raw["declarations"], "case_filed_date", "closed_date")
    evic = agg_evictions(raw["evictions"])
    buys = agg_buyouts(raw["buyouts"])

    print("loading LA Times neighborhood boundaries …", flush=True)
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    polys = load_neighborhoods()
    tree = STRtree([g for _, g in polys])
    names = [n for n, _ in polys]
    print(f"  {len(polys)} neighborhoods")

    def nb_for(lat, lng):
        p = Point(lng, lat)
        for i in tree.query(p):
            if polys[i][1].covers(p):
                return names[i]
        return None

    hit = defaultdict(int)
    nb_hits = 0
    for rec in recs:
        apn = rec["bbl"][3:]          # "LA-2010004040" -> "2010004040"
        h = {}
        if apn in viol:
            v = viol[apn]
            h["violations"] = {"open": v["open"], "total": v["total"],
                               "last_12mo": v["last_12mo"], "types": v["types"]}
            hit["violations"] += 1
        if apn in ccris:
            c = ccris[apn]
            h["complaints"] = {"open": c["open"], "total": c["total"],
                               "last_12mo": c["last_12mo"]}
            if c["insp"]:
                h["insp"] = c["insp"]
            hit["complaints"] += 1
        if apn in cases:
            h["cases"] = cases[apn]
            hit["cases"] += 1
        if apn in decls:
            h["decl"] = decls[apn]
            hit["declarations"] += 1
        if apn in evic:
            h["ev"] = evic[apn]
            hit["evictions"] += 1
        if apn in buys:
            h["by"] = buys[apn]
            hit["buyouts"] += 1
        if h:
            if vwindow:
                h["window"] = vwindow
            rec["h"] = h
        elif "h" in rec:
            del rec["h"]
        if rec.get("lat") and rec.get("lng"):
            nb = nb_for(rec["lat"], rec["lng"])
            rec["nb"] = nb
            if nb:
                nb_hits += 1

    BUILDINGS.write_text(json.dumps(recs, separators=(",", ":")))
    n = len(recs)
    print(f"\nwrote {BUILDINGS} ({BUILDINGS.stat().st_size/1e6:.2f} MB)")
    for k in ("complaints", "violations", "cases", "declarations", "evictions", "buyouts"):
        print(f"  {k:14s} {hit[k]:6,} parcels ({hit[k]/n*100:5.1f}%)")
    print(f"  {'neighborhood':14s} {nb_hits:6,} parcels ({nb_hits/n*100:5.1f}%)")
    if vwindow:
        print(f"\n  violations window: {vwindow[0]} .. {vwindow[1]} (rolling, not all-time)")
    print("\nnext: python3 split_hpd.py --docroot la")


if __name__ == "__main__":
    sys.exit(main())
