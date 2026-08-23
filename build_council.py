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
import re
import unicodedata
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
# The Council's own district table is the authority on who currently holds a
# seat: the Open Data roster (uvw5-9znb) lags a succession, and on 2026-08-23 it
# carried no term covering today for District 3 while council.nyc.gov already
# listed Carl Wilson. A page that calls an occupied seat vacant is worse than a
# page with no name on it, so the roster is the fallback, not the source.
ROSTER = "https://council.nyc.gov/districts/"
OUTREACH = HERE / "council_outreach.csv"

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


def _fold(name):
    """Compare names ignoring accents, case, punctuation and middle initials."""
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c)).lower()
    n = re.sub(r"[^a-z ]", " ", n)
    parts = [w for w in n.split() if len(w) > 1]
    return " ".join(parts)


def roster_members():
    """district (int) -> {name, email, borough} scraped from council.nyc.gov.

    One request per build against one page. Returns {} on any failure so the
    Open Data roster still carries the build.
    """
    req = urllib.request.Request(ROSTER, headers={
        "User-Agent": "findacrib-council/1.0 (+https://findacrib.com)"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  ! council.nyc.gov roster unavailable ({e}); using Open Data only")
        return {}
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        # the per-district link is the one field every row has, Speaker included
        d = re.search(r"council\.nyc\.gov/district-(\d+)/", row)
        if not d:
            continue
        email = re.search(r"mailto:([^\"?]+)", row)
        name = re.search(r'aria-label="Send an email to Council Member ([^"]+)"', row)
        boro = re.search(r'class="sort-borough">([^<]*)<', row)
        who = (name.group(1).strip() if name else "")
        # The roster prefixes leadership titles and honorifics onto the name —
        # "Speaker Julie Menin", "Deputy Speaker Dr. Nantasha Williams". The
        # pages want the name; the title is not what identifies the seat.
        who = re.sub(r"^((Deputy\s+)?Speaker|(Majority|Minority)\s+(Leader|Whip)|"
                     r"Dr\.?|Rev\.?)\s+", "", who, flags=re.I)
        who = re.sub(r"^(Dr\.?|Rev\.?)\s+", "", who, flags=re.I).strip()
        out[int(d.group(1))] = {
            "name": who or None,
            "email": email.group(1).strip() if email else None,
            "borough": boro.group(1).strip() if boro else None,
        }
    return out


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


def _ordinal(n):
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def write_outreach(data, roster):
    """The pitch list: one row per district, the office that would cite it, and
    the number that makes it worth citing.

    Kept out of council_districts.json and off the published pages on purpose —
    these are public office addresses, and republishing a scraped contact table
    is not what the district pages are for.
    """
    rows = ["district,member,email,borough,buildings,units,open_violations,"
            "open_class_c,rank_by_open_violations,page,hook"]
    ranked = sorted(data.values(), key=lambda d: -d["open_violations"])
    rank = {d["district"]: i + 1 for i, d in enumerate(ranked)}
    for d in sorted(data.values(), key=lambda x: x["district"]):
        num = d["district"]
        info = roster.get(num, {})
        place = ("the highest of the" if rank[num] == 1 else
                 "the lowest of the" if rank[num] == len(data) else
                 f"the {_ordinal(rank[num])} highest of the")
        hook = (f"District {num} has {d['open_violations']:,} open HPD violations across its "
                f"{d['buildings']:,} rent-stabilized buildings, {d['open_class_c']:,} of them "
                f"immediately hazardous - {place} {len(data)} districts")
        cells = [str(num), d.get("member") or "", info.get("email") or "",
                 info.get("borough") or "", str(d["buildings"]), str(d["units"]),
                 str(d["open_violations"]), str(d["open_class_c"]), str(rank[num]),
                 f"https://findacrib.com/council-district/{num}/", hook]
        rows.append(",".join('"' + c.replace('"', '""') + '"' for c in cells))
    OUTREACH.write_text("\n".join(rows) + "\n")
    print(f"Wrote {OUTREACH.name}: {len(data)} offices")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="re-derive and compare against the committed JSON; write nothing")
    args = ap.parse_args()

    records = json.loads(BUILDINGS.read_text())
    contacts = json.loads(CONTACTS.read_text()) if CONTACTS.exists() else {}
    print(f"{len(records):,} buildings, {len(contacts):,} with HPD contacts")

    roster = roster_members()
    open_data = sitting_members()
    members = {}
    for d, info in roster.items():
        name, alt = info.get("name"), open_data.get(str(d))
        # The roster page is fresher but writes names without diacritics
        # ("Elsie Encarnacion"); Open Data spells them. When both name the same
        # person, keep the spelled version — this tier gets pitched to these
        # offices, and their own name is the last thing to get wrong.
        if name and alt and _fold(name) == _fold(alt):
            name = alt
        members[str(d)] = name or alt
    for d, name in open_data.items():          # districts the roster page missed
        members.setdefault(d, name)
    named = sum(1 for v in members.values() if v)
    print(f"{named} sitting council members "
          f"({len(roster)} from council.nyc.gov, {len(open_data)} from Open Data)")
    for d in sorted(members, key=int):
        r, o = roster.get(int(d), {}).get("name"), open_data.get(d)
        if r and o and _fold(r) != _fold(o):
            print(f"  district {d}: roster says {r}, Open Data says {o} — using the roster")
        elif r and not o:
            print(f"  district {d}: {r} holds the seat; Open Data has no current term")

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
    write_outreach(data, roster)
    covered = sum(v["buildings"] for v in data.values())
    print(f"\nWrote {OUT.name}: {len(data)} districts, {covered:,} buildings")
    top = sorted(data.values(), key=lambda v: -v["open_violations"])[:5]
    for t in top:
        print(f"  D{t['district']:<3} {(t['member'] or '?'):<26} "
              f"{t['buildings']:>5} buildings  {t['open_violations']:>7,} open violations")


if __name__ == "__main__":
    main()
