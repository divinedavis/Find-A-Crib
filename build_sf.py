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
API = "https://data.sfgov.org/resource/gdc7-dmcn.json"
PAGE = 100_000


def fetch_all():
    rows, offset = [], 0
    while True:
        url = f"{API}?$limit={PAGE}&$offset={offset}&$order=unique_id"
        print(f"  fetching offset {offset:,} …", flush=True)
        with urllib.request.urlopen(url, timeout=300) as r:
            chunk = json.load(r)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="dir with sf_raw_*.json chunks (skips download)")
    args = ap.parse_args()

    rows = load_src(args.src) if args.src else fetch_all()
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
        years = Counter()
        nbs = Counter()
        for r, _ in members:
            if r.get("occupancy_type") == "Occupied by non-owner":
                mid = rent_midpoint(r.get("monthly_rent"))
                if mid:
                    rents.append(mid)
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
        slim.append(rec)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(slim, separators=(",", ":")))
    with_rent = sum(1 for s in slim if "mr" in s)
    print(f"Wrote {OUT} ({OUT.stat().st_size/1024/1024:.2f} MB) with {len(slim):,} "
          f"block records ({with_rent:,} with median rent)")


if __name__ == "__main__":
    sys.exit(main())
