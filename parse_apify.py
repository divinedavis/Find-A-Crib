#!/usr/bin/env python3
"""Turn an Apify StreetEasy rentals export into listings.json (rent-only).

Replaces the Zumper/RentHop Playwright scrape: Apify returns structured
StreetEasy rental records, so we match address -> DHCR bbl and keep the
lowest GROSS rent per building. "Rent only" means we drop any record that
isn't a rental (e.g. the `__typename: "Building"` sales cards, which carry
no rent) and price on `rent` (the advertised monthly figure), NOT
`net_effective_rent` (which bakes in free-month concessions).

Usage:
    python3 parse_apify.py apify_export.json
    # writes listings.json next to this script

Input: a JSON array of Apify StreetEasy items (the actor's dataset export).
Output: listings.json — {updated, counts, urls, prices, beds} keyed by bbl,
        identical shape to scrape_listings.py so index.html needs no change.
"""
import json
import re
import sys
import time
from pathlib import Path

# --- address normalization (kept in sync with scrape_listings.py) ---
SUFFIX_MAP = {
    "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "PLACE": "PL",
    "ROAD": "RD", "DRIVE": "DR", "LANE": "LN", "TERRACE": "TER",
    "COURT": "CT", "PARKWAY": "PKWY", "SQUARE": "SQ", "HEIGHTS": "HTS",
}
DIRECTION_MAP = {"WEST": "W", "EAST": "E", "NORTH": "N", "SOUTH": "S"}
SPECIAL_NAME_MAP = {
    "AVENUE OF THE AMERICAS": "6TH AVE",
    "AVE OF THE AMERICAS": "6TH AVE",
}


def normalize_addr(s: str) -> str:
    """Return canonical 'NUMBER REST' string (e.g. '246 10TH AVE')."""
    if not s:
        return ""
    s = s.upper().strip()
    s = re.split(r"\s+(?:#|APT|UNIT|SUITE|STE)\b", s)[0].strip()
    s = re.sub(r"[#,.;]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for k, v in SPECIAL_NAME_MAP.items():
        if k in s:
            s = s.replace(k, v)
    out = []
    for tok in s.split(" "):
        out.append(SUFFIX_MAP.get(tok, DIRECTION_MAP.get(tok, tok)))
    return " ".join(out)


def build_index(records):
    """Return dict normalized_addr -> bbl, expanding DHCR address ranges."""
    idx = {}
    for r in records:
        if r["b"] not in ("M", "Bk", "Q", "Bx", "SI"):
            continue
        for raw in (r.get("a"), r.get("address_alt")):
            norm = normalize_addr(raw) if raw else ""
            if not norm:
                continue
            m = re.match(r"^(\d+)\s+TO\s+(\d+)\s+(.+)$", norm)
            if m:
                lo, hi, rest = int(m.group(1)), int(m.group(2)), m.group(3)
                step = 2 if (hi - lo) % 2 == 0 else 1
                for n in range(lo, hi + 1, step):
                    idx[f"{n} {rest}"] = r["bbl"]
            else:
                idx[norm] = r["bbl"]
    return idx


HERE = Path(__file__).parent
BUILDINGS = HERE / "buildings.min.json"
# Apify writes its own per-borough file; combine_listings.py overlays it onto
# the Zumper baseline to produce the listings.json the site serves.
OUT = HERE / "listings_apify.json"

RENT_MIN, RENT_MAX = 500, 50000


def is_rental(item: dict) -> bool:
    """Keep only true rental listings with a usable rent number."""
    if item.get("__typename") == "Building":
        return False  # sales building card — no rent
    if item.get("buildingType") and item["buildingType"] != "RENTAL":
        return False
    rent = item.get("rent", item.get("price"))
    return isinstance(rent, (int, float)) and RENT_MIN <= rent <= RENT_MAX


def street_of(item: dict) -> str:
    return (
        item.get("propertyDetails_address_street")
        or item.get("street")
        or item.get("addressWithoutUnit")
        or ""
    )


def match_bbl(norm, addr_idx):
    """Exact, then longest-prefix match against the DHCR address index."""
    if not norm:
        return None
    bbl = addr_idx.get(norm)
    if bbl:
        return bbl
    toks = norm.split(" ")
    for n in range(len(toks), 1, -1):
        cand = " ".join(toks[:n])
        if cand in addr_idx:
            return addr_idx[cand]
    return None


BOROUGH_CODE = {"MN": "1", "M": "1", "BX": "2", "BK": "3",
                "QN": "4", "Q": "4", "SI": "5"}


def parse_borough(argv):
    """--borough BK / MN / 3 / 1 ... -> single BBL prefix digit, or None."""
    for i, a in enumerate(argv):
        if a == "--borough" and i + 1 < len(argv):
            v = argv[i + 1].upper()
            return v if v in "12345" and len(v) == 1 else BOROUGH_CODE.get(v)
    return None


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python3 parse_apify.py <export.json> [--merge] "
                 "[--borough BK|MN|BX|QN|SI]")
    merge = "--merge" in sys.argv[2:]
    target = parse_borough(sys.argv[2:])  # restrict to one borough if given
    items = json.loads(Path(sys.argv[1]).read_text())
    if isinstance(items, dict):  # some exports wrap the array
        items = items.get("items") or items.get("results") or []

    addr_idx = build_index(json.loads(BUILDINGS.read_text()))

    counts, urls, prices, beds = {}, {}, {}, {}
    rentals = matched = 0
    for item in items:
        if not is_rental(item):
            continue
        rentals += 1
        bbl = match_bbl(normalize_addr(street_of(item)), addr_idx)
        if not bbl:
            continue
        if target and bbl[:1] != target:
            continue  # drop stray cross-borough matches (e.g. a BK run that
                      # address-matches into Manhattan) so a per-borough run
                      # never pollutes another borough's data
        matched += 1
        rent = int(item.get("rent", item.get("price")))

        counts[bbl] = counts.get(bbl, 0) + 1
        if bbl not in urls and item.get("urlPath"):
            urls[bbl] = "https://streeteasy.com" + item["urlPath"]
        if bbl not in prices or rent < prices[bbl]:
            prices[bbl] = rent
        bed = item.get("bedroomCount")
        if isinstance(bed, int) and 0 <= bed <= 12:
            beds.setdefault(bbl, set()).add(min(bed, 4))  # 4 == "4+"

    beds = {b: sorted(s) for b, s in beds.items()}

    # Merge mode (borough-rotation): refresh only the boroughs present in this
    # run (by BBL prefix 1=MN 2=BX 3=BK 4=QN 5=SI) and keep every other
    # borough's existing prices, so monthly per-borough runs accumulate instead
    # of overwriting each other. Stale same-borough entries are dropped.
    if merge and OUT.exists():
        old = json.loads(OUT.read_text())
        # Refresh exactly the borough we targeted. Fall back to inferring from
        # results only when no --borough was given (single-borough runs should
        # always pass --borough so a stray match can't clear another borough).
        run_boroughs = {target} if target else {b[0] for b in counts}

        def keep(bbl):  # keep old entry only if its borough wasn't re-run
            return bbl[:1] not in run_boroughs

        for key, new in (("counts", counts), ("urls", urls),
                         ("prices", prices), ("beds", beds)):
            merged = {b: v for b, v in old.get(key, {}).items() if keep(b)}
            merged.update(new)
            if key == "counts":
                counts = merged
            elif key == "urls":
                urls = merged
            elif key == "prices":
                prices = merged
            else:
                beds = merged
        print(f"merged: refreshed boroughs {sorted(run_boroughs)}, "
              f"kept {sum(1 for b in prices if b[:1] not in run_boroughs)} "
              f"prices from other boroughs")

    payload = {
        "updated": int(time.time()),
        "counts": counts,
        "urls": urls,
        "prices": prices,
        "beds": beds,
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"rentals: {rentals}  matched to DHCR: {matched}  "
          f"buildings in file: {len(counts)}  with rent: {len(prices)}")


if __name__ == "__main__":
    main()
