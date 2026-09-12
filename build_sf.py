#!/usr/bin/env python3
"""Build sf/buildings.min.json from the SF Rent Board Housing Inventory.

Source: DataSF dataset gdc7-dmcn (Socrata), ~550k rows, one row per unit per
submission year. Owners of units covered by the SF Rent Ordinance must report
annually; DataSF refreshes the extract every 24h.

Privacy note baked into the source: addresses are anonymized to the BLOCK level
("1000 Block Of Fulton St") and lat/lng is the nearest mid-block point — so one
record here is a block-side, not a single building. The frontend discloses this.

Usage:
  python3 build_sf.py                 # downloads ~550k rows (6 requests)
  python3 build_sf.py --src DIR       # reuse previously downloaded sf_raw_*.json
"""
import argparse
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

HERE = Path(__file__).parent
OUT = HERE / "sf" / "buildings.min.json"
# data.sfgov.org 301s to data.sf.gov as of 2026-09; point at the new host
# directly so a redirect-follow is not load-bearing.
API = "https://data.sf.gov/resource/gdc7-dmcn.json"
PAGE = 100_000


def fetch_all(cache_dir=None):
    rows, offset = [], 0
    if cache_dir:
        Path(cache_dir).mkdir(exist_ok=True)
    while True:
        url = f"{API}?$limit={PAGE}&$offset={offset}&$order=unique_id"
        print(f"  fetching offset {offset:,} …", flush=True)
        with urllib.request.urlopen(url, timeout=300) as r:
            chunk = json.load(r)
        if cache_dir:
            (Path(cache_dir) / f"sf_raw_{offset:08d}.json").write_text(
                json.dumps(chunk, separators=(",", ":")))
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return rows
        offset += PAGE


def load_src(src_dir):
    rows = []
    for p in sorted(Path(src_dir).glob("sf_raw_*.json")):
        rows.extend(json.loads(p.read_text()))
    return rows


def slugify(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())[:16]


# Which utilities the Rent Board asks about, in the order a renter cares.
UTILITIES = [
    ("water", "base_rent_includes_water_sewer"),
    ("gas", "base_rent_includes_natural_gas"),
    ("electric", "base_rent_includes_electricity"),
    ("refuse", "base_rent_includes_refuse_recycling"),
]

# bedroom_count is free-ish text: the form's own options ("Studio",
# "One-Bedroom", "5+") sit alongside stray numerals and spellings from earlier
# submission years. Everything above four collapses into the 4 bucket, which is
# how the app labels it ("4+ bed").
_BED_WORDS = {
    "studio": 0, "0": 0, "zero": 0,
    "one-bedroom": 1, "one bedroom": 1, "1": 1, "one": 1,
    "two-bedroom": 2, "two bedroom": 2, "2": 2, "two": 2,
    "three-bedroom": 3, "three bedroom": 3, "3": 3, "three": 3,
}


def bed_key(text):
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in _BED_WORDS:
        return _BED_WORDS[t]
    m = re.match(r"(\d+)", t)
    if m:
        return min(int(m.group(1)), 4)
    if t.startswith("four"):
        return 4
    if t.startswith("five") or t.startswith("six") or t.startswith("seven"):
        return 4
    return None


def sq_midpoint(text):
    # reported in 250 sq ft bands: "751-1000" -> 875
    nums = [int(n) for n in re.findall(r"\d+", (text or "").replace(",", ""))]
    nums = [n for n in nums if 50 <= n < 20000]
    if not nums:
        return None
    return sum(nums[:2]) / len(nums[:2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="dir with sf_raw_*.json chunks (skips download)")
    ap.add_argument("--cache", default="sf_raw",
                    help="dir to write the raw chunks into (default sf_raw/)")
    args = ap.parse_args()

    rows = load_src(args.src) if args.src else fetch_all(args.cache)
    print(f"{len(rows):,} raw unit-year rows")

    # Rows are unit-year submissions with no stable unit id across years, so per
    # block we count units within a single submission year (the dataset's own
    # guidance: "select a year then count") and take the largest year — robust
    # when different owners on a block last reported in different years.
    groups = defaultdict(list)
    for r in rows:
        if r.get("occupancy_type") == "Non-Residential":
            continue
        block = r.get("block_num") or ""
        addr = (r.get("block_address") or "").strip()
        if not addr:
            addr = f"Block {block}" if block else None
        coords = (r.get("point") or {}).get("coordinates")
        if not addr or not coords:
            continue
        groups[(block, addr)].append((r, coords))

    def rent_midpoint(text):
        # "$3251-$3500" -> 3375; "$501-$750" -> 625; single figures pass through
        nums = [int(n) for n in re.findall(r"\d+", (text or "").replace(",", ""))]
        nums = [n for n in nums if 100 <= n < 20000]
        if not nums:
            return None
        return sum(nums[:2]) / len(nums[:2])

    slim = []
    for (block, addr), members in sorted(groups.items()):
        lats = [c[1] for _, c in members]
        lngs = [c[0] for _, c in members]
        per_year = Counter(r.get("submission_year") for r, _ in members)
        rents = []
        by_bed = defaultdict(list)
        sqfts = []
        years = Counter()
        nbs = Counter()
        util = Counter()
        for r, _ in members:
            if r.get("occupancy_type") == "Occupied by non-owner":
                mid = rent_midpoint(r.get("monthly_rent"))
                if mid:
                    rents.append(mid)
                    bed = bed_key(r.get("bedroom_count"))
                    if bed is not None:
                        by_bed[bed].append(mid)
                # "included in the base rent" is part of what a rent MEANS: a
                # block reporting $2,400 with heat and power in it is not the
                # same offer as $2,400 without, and the Rent Board asks per
                # utility. Counted per unit so the block can say "most".
                for key, field in UTILITIES:
                    if str(r.get(field) or "").strip().lower() in ("yes", "true", "1"):
                        util[key] += 1
                util["n"] += 1
            sq = sq_midpoint(r.get("square_footage"))
            if sq:
                sqfts.append(sq)
            yb = r.get("year_property_built") or ""
            if yb.isdigit() and 1850 <= int(yb) <= 2026:
                years[int(yb)] += 1
            if r.get("analysis_neighborhood"):
                nbs[r["analysis_neighborhood"]] += 1
        rec = {
            "bbl": f"SF-{block}-{slugify(addr)}",
            "b": "SF",
            "a": addr,
            "z": "",
            "lat": round(sum(lats) / len(lats), 6),
            "lng": round(sum(lngs) / len(lngs), 6),
            "s": ["SF RENT BOARD INVENTORY"],
            "yr": years.most_common(1)[0][0] if years else None,
            "u": max(per_year.values()),
            "nb": nbs.most_common(1)[0][0] if nbs else None,
        }
        # median owner-reported rent, only with a decent sample (block privacy)
        if len(rents) >= 5:
            rec["mr"] = int(median(rents))
        # …and the same median split by bedroom count, which is the number a
        # renter can actually use: a block median mixing studios with 3-beds
        # answers nobody's question. Same privacy floor per bucket.
        br = {str(k): int(median(v)) for k, v in sorted(by_bed.items()) if len(v) >= 5}
        if br:
            rec["br"] = br
        if len(sqfts) >= 5:
            rec["sq"] = int(median(sqfts))
        # Only claim a utility is included when most reporting units say so —
        # one landlord on the block including power is not a block fact.
        if util["n"] >= 5:
            inc = [k for k, _ in UTILITIES if util[k] * 2 > util["n"]]
            if inc:
                rec["ui"] = inc
        slim.append(rec)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(slim, separators=(",", ":")))
    with_rent = sum(1 for s in slim if "mr" in s)
    with_br = sum(1 for s in slim if "br" in s)
    with_sq = sum(1 for s in slim if "sq" in s)
    print(f"Wrote {OUT} ({OUT.stat().st_size/1024/1024:.2f} MB) with {len(slim):,} "
          f"block records ({with_rent:,} with median rent, {with_br:,} with rent "
          f"by bedroom, {with_sq:,} with median size)")
    print("next: python3 build_sf_records.py   # ZIPs, evictions, buyouts, petitions")


if __name__ == "__main__":
    sys.exit(main())
