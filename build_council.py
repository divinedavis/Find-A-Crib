#!/usr/bin/env python3
"""Join every rent-stabilized building to its NYC City Council district.

Nobody publishes "how many rent-stabilized buildings, owned by whom, carrying how
many open HPD violations, sit in Council District 35". Borough, neighborhood and
ZIP hubs all restate a geography somebody else already covers; a council district
is a unit with a named officeholder who has a standing reason to cite the number,
which is what makes this tier worth linking to rather than just worth publishing.

Reads buildings.min.json (lat/lng + the HPD counts banked by fetch_hpd.py) and
council_districts.geojson (NYC Open Data 872g-cjhh); pulls the sitting member per
district from the City Council roster (uvw5-9znb). Writes council_districts.json.

    python3 build_council.py            # rebuild the aggregate
    python3 build_council.py --check    # re-derive from source and diff, no write
"""
import argparse
import datetime
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

HERE = Path(__file__).parent
BUILDINGS = HERE / "buildings.min.json"
DISTRICTS = HERE / "council_districts.geojson"
CONTACTS = HERE / "hpd_contacts.json"
OUT = HERE / "council_districts.json"

MEMBERS = "https://data.cityofnewyork.us/resource/uvw5-9znb.json"

# A landlord is only worth naming when the portfolio inside the district is big
# enough that the number says something about them rather than about one bad
# building. Below this the district page names nobody.
MIN_OWNER_BUILDINGS = 3
TOP_OWNERS = 5


def fetch_json(url, params=None):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers={"User-Agent": "rentmap-council/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def sitting_members(today=None):
    """district (str) -> member name, for the term covering `today`."""
    today = today or datetime.date.today().isoformat()
    rows = fetch_json(MEMBERS, {"$limit": "2000"})
    out = {}
    for r in rows:
        start = (r.get("term_start") or "")[:10]
        end = (r.get("term_end") or "")[:10]
        if not (start and end and start <= today <= end):
            continue
        d = str(r.get("district") or "").strip()
        name = (r.get("name") or "").strip()
        if not d or not name:
            continue
        # A district with two rows covering today means a mid-term change; keep
        # the later term rather than whichever the API happened to return first.
        prev = out.get(d)
        if prev and prev[1] >= start:
            continue
        out[d] = (name, start)
    return {d: n for d, (n, _) in out.items()}


def assign(records, districts_path=DISTRICTS):
    """Return {bbl: district}. Point-in-polygon, prepared-geometry indexed."""
    g = json.loads(Path(districts_path).read_text())
    geoms, ids = [], []
    for f in g["features"]:
        if not f.get("geometry"):
            continue
        geoms.append(shape(f["geometry"]))
        ids.append(str(f["properties"]["coundist"]))
    tree = STRtree(geoms)
    out = {}
    for r in records:
        lat, lng = r.get("lat"), r.get("lng")
        if lat is None or lng is None:
            continue
        p = Point(lng, lat)
        for i in tree.query(p):
            if geoms[i].contains(p):
                out[r["bbl"]] = ids[i]
                break
    return out


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def aggregate(records, by_bbl, members, contacts=None):
    """One dict per district: the counts a council office would actually quote."""
    groups = defaultdict(list)
    for r in records:
        d = by_bbl.get(r["bbl"])
        if d:
            groups[d].append(r)

    out = {}
    for d, recs in groups.items():
        units = [r["u"] for r in recs if isinstance(r.get("u"), int)]
        years = [r["yr"] for r in recs if isinstance(r.get("yr"), int)]
        v_open = c_open = v_total = classc = 0
        clean = 0
        for r in recs:
            h = r.get("h") or {}
            v = h.get("violations") or {}
            c = h.get("complaints") or {}
            v_open += v.get("open", 0)
            v_total += v.get("total", 0)
            # oc is the open class C count (fetch_hpd.py); the all-time c would
            # describe the building's history, not what a tenant faces today.
            classc += v.get("oc", 0)
            c_open += c.get("open", 0)
            if not v.get("open"):
                clean += 1

        owners = defaultdict(lambda: {"buildings": 0, "units": 0, "open_violations": 0})
        if contacts:
            for r in recs:
                info = contacts.get(r["bbl"]) or {}
                who = (info.get("owner") or {}).get("name") or (info.get("manager") or {}).get("name")
                if not who:
                    continue
                o = owners[who.strip()]
                o["buildings"] += 1
                o["units"] += r.get("u") or 0
                o["open_violations"] += ((r.get("h") or {}).get("violations") or {}).get("open", 0)

        ranked = sorted(
            ({"name": k, **v} for k, v in owners.items() if v["buildings"] >= MIN_OWNER_BUILDINGS),
            key=lambda o: (-o["open_violations"], -o["buildings"], o["name"]),
        )[:TOP_OWNERS]

        nbs = defaultdict(int)
        for r in recs:
            if r.get("nb"):
                nbs[r["nb"]] += 1

        out[d] = {
            "district": int(d),
            "member": members.get(d),
            "buildings": len(recs),
            "units": sum(units),
            "median_year": _median(years),
            "open_violations": v_open,
            "total_violations": v_total,
            "open_class_c": classc,
            "open_complaints": c_open,
            "buildings_no_open_violations": clean,
            "boroughs": sorted({r["b"] for r in recs if r.get("b")}),
            "neighborhoods": [n for n, _ in sorted(nbs.items(), key=lambda kv: (-kv[1], kv[0]))],
            "top_owners": ranked,
        }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="re-derive and compare against the committed JSON; write nothing")
    args = ap.parse_args()

    records = json.loads(BUILDINGS.read_text())
    contacts = json.loads(CONTACTS.read_text()) if CONTACTS.exists() else {}
    print(f"{len(records):,} buildings, {len(contacts):,} with HPD contacts")

    members = sitting_members()
    print(f"{len(members)} sitting council members")

    by_bbl = assign(records)
    print(f"{len(by_bbl):,} buildings fell inside a district "
          f"({len(records) - len(by_bbl):,} did not)")

    data = aggregate(records, by_bbl, members, contacts)
    payload = {
        "generated": datetime.date.today().isoformat(),
        "source": "NYC Open Data 872g-cjhh (districts), uvw5-9znb (members), "
                  "wvxf-dwi5 + ygpa-z7cr via fetch_hpd.py (HPD)",
        "districts": {k: data[k] for k in sorted(data, key=int)},
        "by_bbl": by_bbl,
    }

    if args.check:
        if not OUT.exists():
            raise SystemExit(f"{OUT.name} does not exist yet — run without --check")
        prior = json.loads(OUT.read_text())
        diff = [d for d in payload["districts"]
                if prior["districts"].get(d, {}).get("buildings")
                != payload["districts"][d]["buildings"]]
        print(f"districts whose building count moved: {len(diff)} {diff[:10]}")
        return

    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    covered = sum(v["buildings"] for v in data.values())
    print(f"\nWrote {OUT.name}: {len(data)} districts, {covered:,} buildings")
    top = sorted(data.values(), key=lambda v: -v["open_violations"])[:5]
    for t in top:
        print(f"  D{t['district']:<3} {(t['member'] or '?'):<26} "
              f"{t['buildings']:>5} buildings  {t['open_violations']:>7,} open violations")


if __name__ == "__main__":
    main()
