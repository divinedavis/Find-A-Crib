#!/usr/bin/env python3
"""Build nj/rentcontrol.json — the New Jersey answer, by ZIP.

WHY THIS IS NOT A BUILDING MAP
------------------------------
Every other Find A Crib map is building-level because a register of covered
buildings exists: NYC has the RGB lists, Westchester has HCR's ETPA layer, DC
has DHCD's RentRegistry, SF has the Rent Board inventory. New Jersey has no
such thing and cannot: rent control there is MUNICIPAL, roughly 120 separate
ordinances, each administered by its own town's rent leveling board, with the
property files kept for in-person public inspection. There is no statewide
registry to load and no per-town bulk export to gather.

What DOES exist statewide is the answer one level up, and it is a good answer:
the NJ DCA's annual Rent Control Survey names, for every municipality, whether
it has an ordinance, what the increase cap is, which building sizes it covers,
the board's name and phone number, and a link to the ordinance itself. For a
tenant asking "can my landlord raise it this much", that is most of the way
there — and it is the whole way for the 444 municipalities whose answer is
"there is no rent control here", which no building map could ever have told
them.

    Survey: https://www.nj.gov/dca/home/misc/Rent_Control_Survey.xlsx

Joined to ZIPs through the Census 2020 ZCTA-to-county-subdivision relationship
file. That join is exact in New Jersey, where county subdivisions ARE the
municipalities (every acre of the state sits in a borough, township, city or
town), unlike states where they are statistical areas.

    https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/
      tab20_zcta520_cousub20_natl.txt

A ZIP can straddle several municipalities, so each ZIP keeps every municipality
it touches, ordered by how much of the ZIP's land each one holds. The UI shows
the largest and says how many others there are — quietly picking one would be
wrong in exactly the towns where the ordinance differs across the line.

Usage:  python3 build_nj.py [--out nj]
"""
import argparse
import json
import re
import sys
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).parent
SURVEY_URL = "https://www.nj.gov/dca/home/misc/Rent_Control_Survey.xlsx"
XWALK_URL = ("https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
             "tab20_zcta520_cousub20_natl.txt")
UA = "findacrib.com building map (+https://findacrib.com)"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
T = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NJ_FIPS = "34"


def get(url, timeout=240):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def read_xlsx(blob):
    z = zipfile.ZipFile(BytesIO(blob))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(T + "t")))

    def sheet(part):
        root = ET.fromstring(z.read(part))
        out = []
        for row in root.iter(T + "row"):
            vals = []
            for c in row:
                v = c.find("m:v", NS)
                if v is None:
                    vals.append("")
                elif c.get("t") == "s":
                    vals.append(shared[int(v.text)])
                else:
                    vals.append(v.text or "")
            out.append(vals)
        return out

    return sheet


# New Jersey municipality names are NOT unique on their own — Franklin
# Township, Hamilton Township and Washington Township each exist in several
# counties — so every key here is (name, county). Keying on name alone silently
# merged them, which is what first produced "547 municipalities, 547 with rent
# control" out of a state that has 564 and 120.
NJ_COUNTY_FIPS = {
    "001": "Atlantic", "003": "Bergen", "005": "Burlington", "007": "Camden",
    "009": "Cape May", "011": "Cumberland", "013": "Essex", "015": "Gloucester",
    "017": "Hudson", "019": "Hunterdon", "021": "Mercer", "023": "Middlesex",
    "025": "Monmouth", "027": "Morris", "029": "Ocean", "031": "Passaic",
    "033": "Salem", "035": "Somerset", "037": "Sussex", "039": "Union",
    "041": "Warren",
}
# The DCA writes "Atlantic City", the Census writes "Atlantic City city"; the
# DCA writes "Harrison Town", the Census "Harrison town". Stripping the type
# word from BOTH sides is what makes them the same place.
TYPE_WORD = re.compile(r"\b(township|twp|borough|boro|city|town|village)\b")
TYPE_CANON = {"township": "twp", "twp": "twp", "borough": "boro", "boro": "boro",
              "city": "city", "town": "town", "village": "village"}


def base(name):
    """Name with every type word removed: 'Freehold Township' -> 'freehold'."""
    n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    return " ".join(TYPE_WORD.sub(" ", n).split())


def full(name):
    """Name with type words kept but spelled one way: 'Freehold Township' and
    Census's 'Freehold township' both -> 'freehold twp'."""
    n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    return " ".join(TYPE_CANON.get(w, w) for w in n.split())


# Dropping the type word alone is not safe. Four Monmouth/Camden pairs differ
# ONLY by it and give OPPOSITE answers — Freehold Borough has no rent control
# while Freehold Township does, likewise Gloucester, Neptune and Shrewsbury.
# Merging those told a Freehold Borough tenant they were covered when they are
# not, which is the worst error this file can make. So: match on the full name
# including type first, and fall back to the bare name only when that name is
# unambiguous within its county (which is what rescues DCA's "Atlantic City"
# against the Census's "Atlantic City city").
class Munis:
    def __init__(self):
        self.strict = {}
        self.loose = {}
        self.all = {}

    def add(self, name, county, rec):
        c = (county or "").lower().strip()
        self.all[(full(name), c)] = rec
        self.strict[(full(name), c)] = rec
        self.loose.setdefault((base(name), c), []).append(rec)

    def get(self, name, county):
        c = (county or "").lower().strip()
        hit = self.strict.get((full(name), c))
        if hit:
            return hit
        cands = self.loose.get((base(name), c), [])
        return cands[0] if len(cands) == 1 else None


def cell(row, i):
    return (row[i].strip() if len(row) > i and row[i] else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="nj")
    args = ap.parse_args()

    print("fetching the NJ DCA Rent Control Survey …", flush=True)
    sheet = read_xlsx(get(SURVEY_URL))
    survey = sheet("xl/worksheets/sheet2.xml")
    status = sheet("xl/worksheets/sheet4.xml")

    # --- every municipality's yes/no, which is the sheet that is COMPLETE ----
    # The survey sheet only holds towns that answered; the status sheet holds
    # all 685. A town missing from the survey but marked "No" here is a real
    # answer, not a gap, and it is the answer most New Jersey searchers get.
    muni = Munis()
    for r in status[3:]:
        name, county, has = cell(r, 0), cell(r, 1), cell(r, 2).lower()
        if not name or not has.startswith(("y", "n")):
            continue
        muni.add(name, county, {
            "name": name,
            "county": county,
            "rc": has.startswith("y"),
        })

    # --- detail for the ones that have an ordinance -------------------------
    # The Survey sheet lists EVERY municipality too, not only the controlled
    # ones — an uncontrolled town is present with "--" in every detail column.
    # So presence in the survey proves nothing; the status sheet's Yes/No is
    # the only thing that decides `rc`, and detail is attached on top of it.
    def real(v):
        return "" if v in ("--", "-", "N/A", "n/a", "NA") else v

    detail = 0
    for r in survey[3:]:
        name, county = cell(r, 2), cell(r, 3)
        if not name:
            continue
        m = muni.get(name, county)
        if not m or not m["rc"]:
            continue
        for field, col in (("board", 4), ("site", 5), ("ordinance", 6),
                           ("phone", 7), ("applies", 8), ("cap", 9),
                           ("exceptions", 10)):
            v = real(cell(r, col))
            if v:
                m[field] = " ".join(v.split())
        detail += 1
    everyone = list(muni.all.values())
    print(f"  {len(everyone):,} municipalities, {sum(1 for m in everyone if m['rc']):,} "
          f"with rent control, {detail:,} with full detail")

    # --- ZIP -> municipality via the Census relationship file ---------------
    print("fetching the Census ZCTA/county-subdivision crosswalk …", flush=True)
    raw = get(XWALK_URL).decode("utf-8-sig", "replace").splitlines()
    hdr = raw[0].split("|")
    ix = {h: i for i, h in enumerate(hdr)}
    zips = {}
    unmatched = set()
    for line in raw[1:]:
        f = line.split("|")
        if len(f) < len(hdr):
            continue
        cousub = f[ix["GEOID_COUSUB_20"]]
        if not cousub.startswith(NJ_FIPS):
            continue
        z = f[ix["GEOID_ZCTA5_20"]]
        if not z or not z.isdigit():
            continue
        name = f[ix["NAMELSAD_COUSUB_20"]]
        county = NJ_COUNTY_FIPS.get(cousub[2:5], "")
        m = muni.get(name, county)
        if not m:
            unmatched.add(f"{name} ({county})")
            continue
        try:
            share = int(f[ix["AREALAND_PART"]] or 0)
        except ValueError:
            share = 0
        zips.setdefault(z, []).append((share, m))

    out = {}
    for z, parts in zips.items():
        # Biggest land share first: the municipality that holds most of the ZIP
        # is the one a person typing that ZIP most likely lives in.
        parts.sort(key=lambda p: -p[0])
        seen, munis = set(), []
        for _, m in parts:
            if m["name"] in seen:
                continue
            seen.add(m["name"])
            munis.append({k: v for k, v in m.items() if v not in ("", None)})
        out[z] = munis

    dest = HERE / args.out
    dest.mkdir(exist_ok=True)
    path = dest / "rentcontrol.json"
    path.write_text(json.dumps(
        {"source": "NJ DCA Rent Control Survey (2026) + Census 2020 ZCTA/county-subdivision",
         "survey_url": SURVEY_URL,
         "zips": out},
        separators=(",", ":")))

    with_rc = sum(1 for v in out.values() if any(m["rc"] for m in v))
    split = sum(1 for v in out.values() if len(v) > 1)
    print(f"\nWrote {path} ({path.stat().st_size/1e6:.2f} MB)")
    print(f"  {len(out):,} New Jersey ZIPs")
    print(f"  {with_rc:,} touch at least one municipality WITH rent control")
    print(f"  {split:,} straddle more than one municipality")
    if unmatched:
        print(f"  {len(unmatched)} county subdivisions had no survey row "
              f"(e.g. {sorted(unmatched)[:3]}) — these are almost all "
              f"'not defined' water areas", file=sys.stderr)


if __name__ == "__main__":
    main()
