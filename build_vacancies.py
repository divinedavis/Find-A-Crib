#!/usr/bin/env python3
"""Vacancies straight from the managers' own websites -> vacancies.json.

Owner, 2026-09-23, asking for the best ways to know a building has an
apartment free: "do number 2" — go to the companies that manage the
rent-stabilized stock and read what they are advertising, instead of waiting
for it to reach a listing site. The register's 205 organisations with 800+
stabilized units cover most of the city's stabilized housing, and the large
ones publish their own availability pages.

This reuses two things that already work:
  * featured_rerentals.sweep() — a headless pass over a page that pulls a
    record per apartment card (address, money, beds, link, photo).
  * scrape_listings.normalize_addr/build_index — the address -> BBL matcher
    the Zumper feed uses, so a vacancy lands on the same building the map
    already knows.

Output (docroot vacancies.json), shaped like listings.json so the map can
treat it as one more "advertised now" source:

  {"generated": …, "sources": <n companies scanned>, "matched": <n listings
   matched to a BBL>, "counts": {bbl: n}, "prices": {bbl: lowest},
   "urls": {bbl: page}, "by_company": {company: n}, "listings": [ … ]}

    python3 build_vacancies.py                    # scan, print, write nothing
    python3 build_vacancies.py --apply            # write vacancies.json
    python3 build_vacancies.py --apply --out /var/www/rent-map
    python3 build_vacancies.py --only "C&C"       # one company
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import featured_rerentals as FR                  # noqa: E402  (sweep, parse, filters)
from addr_match import normalize_addr, build_index          # noqa: E402

PAGES = os.path.join(HERE, "owner_vacancy_pages.json")
# The register. In the checkout on a laptop; only in the docroot on the
# droplet, where the first run died on its absence (2026-09-23).
BUILDINGS_CANDIDATES = [os.environ.get("BUILDINGS_FILE"),
                        os.path.join(HERE, "buildings.slim.json"),
                        "/var/www/rent-map/buildings.slim.json"]
OUT = os.path.join(HERE, "vacancies.json")


def free_mb():
    """Free + reclaimable memory, or None where that cannot be read (macOS)."""
    try:
        info = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            info[k] = int(v.strip().split()[0])
        return (info.get("MemAvailable") or info.get("MemFree", 0)) // 1024
    except Exception:
        return None


def load_pages(only=None):
    """{company: {url, …}} for every company with a live availability page."""
    try:
        data = json.load(open(PAGES))
    except FileNotFoundError:
        sys.exit(f"{PAGES} is missing — it holds the companies and their availability pages")
    pages = {}
    for name, meta in (data.get("pages") or {}).items():
        if not meta.get("url") or meta.get("skip"):
            continue
        if only and only.lower() not in name.lower():
            continue
        pages[name] = meta
    return pages, data


def match_to_buildings(records):
    """Attach the register's BBL to every listing whose address we recognise."""
    path = next((p for p in BUILDINGS_CANDIDATES if p and os.path.exists(p)), None)
    if not path:
        print("  (no buildings.slim.json found — listings are published unmatched)")
        for r in records:
            r["bbl"] = None
        return 0
    idx = build_index(json.loads(open(path).read()))
    matched = 0
    for r in records:
        norm = normalize_addr(r.get("address") or "")
        bbl = idx.get(norm)
        if not bbl:
            # "303-309 10th Ave" and "1514 60th Street, Suite 703" both reduce
            # to a first number + street; try the leading number alone.
            m = re.match(r"^(\d+)[-–](\d+)\s+(.*)$", norm)
            if m:
                bbl = idx.get(f"{m.group(1)} {m.group(3)}") or idx.get(f"{m.group(2)} {m.group(3)}")
        r["bbl"] = bbl
        if bbl:
            matched += 1
    return matched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write vacancies.json")
    ap.add_argument("--out", help="also write into this docroot (droplet-side)")
    ap.add_argument("--only", help="one company (substring match)")
    ap.add_argument("--limit", type=int, default=400, help="max listings to publish")
    ap.add_argument("--chunk", type=int, default=6,
                    help="pages per browser; a fresh browser hands memory back (default 6)")
    ap.add_argument("--min-free", type=int, default=250, dest="min_free",
                    help="stop when free memory drops below this many MB (default 250)")
    a = ap.parse_args()

    pages, registry = load_pages(a.only)
    if not pages:
        sys.exit("no companies with an availability page to scan")
    # In CHUNKS, each with its own browser. The droplet has 2 GB and also
    # serves the site: forty pages in one browser left 79 MB free, eleven
    # renderers alive and the run wedged at 0% CPU (2026-09-23). A browser
    # per chunk hands the memory back between them. The re-rental sweep gets
    # away with one browser because it walks half as many pages.
    names = list(pages)
    records, errors = [], {}
    for i in range(0, len(names), a.chunk):
        part = {n: pages[n] for n in names[i:i + a.chunk]}
        got, err = FR.sweep(part)
        records += got
        errors.update(err)
        free = free_mb()
        print(f"  …{min(i + a.chunk, len(names))}/{len(names)} pages, {len(records)} listings"
              + (f", {free} MB free" if free is not None else ""))
        if free is not None and free < a.min_free:
            errors["(stopped)"] = f"only {free} MB free after {i + a.chunk} pages; the rest were skipped"
            break
    offices = FR.office_addresses()
    records = [r for r in records if FR.is_real_listing(r, offices)]
    for r in records:
        r.pop("_card", None)
        r.pop("_amounts", None)
        r.pop("probe", None)
    matched = match_to_buildings(records)
    records = records[:a.limit]

    counts, prices, urls, by_company = {}, {}, {}, {}
    for r in records:
        by_company[r["agent"]] = by_company.get(r["agent"], 0) + 1
        bbl = r.get("bbl")
        if not bbl:
            continue
        counts[bbl] = counts.get(bbl, 0) + 1
        # Only a rent is a price. These pages also print income bands, and a
        # household income printed as rent is the worst thing this can do
        # (featured_rerentals.classify_money, same rule).
        if r.get("money_kind") == "rent" and r.get("money_low"):
            if bbl not in prices or r["money_low"] < prices[bbl]:
                prices[bbl] = r["money_low"]
        urls.setdefault(bbl, r.get("href") or pages[r["agent"]]["url"])

    data = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "source": "managers' own availability pages (HPD registrations, 800+ stabilized units)",
            "sources": len(pages), "scanned": len(records), "matched": matched,
            "counts": counts, "prices": prices, "urls": urls,
            "by_company": by_company, "listings": records}

    print(f"{len(records)} listings from {len(by_company)} of {len(pages)} companies; "
          f"{matched} matched to a building on the register ({len(counts)} buildings)")
    for c, n in sorted(by_company.items(), key=lambda kv: -kv[1])[:25]:
        print(f"  {n:3}  {c}")
    for c, e in errors.items():
        print(f"  ERR  {c}: {e}")

    if not a.apply:
        print("\n(dry run — pass --apply to write vacancies.json)")
        return 0
    json.dump(data, open(OUT, "w"), indent=1, ensure_ascii=False)
    print("wrote", OUT)
    if a.out:
        with open(os.path.join(a.out, "vacancies.json"), "w") as f:
            json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
        print("wrote", os.path.join(a.out, "vacancies.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
