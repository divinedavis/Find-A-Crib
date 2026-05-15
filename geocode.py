#!/usr/bin/env python3
"""Look up lat/lon for each BBL in buildings.json using NYC OpenData PLUTO (64uk-42ks)."""
import json
import urllib.parse
import urllib.request
import time
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "buildings.json"
OUT = HERE / "buildings_geo.json"
ENDPOINT = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
BATCH = 200


def fetch_batch(bbls):
    where = "bbl in (" + ",".join(bbls) + ")"
    qs = urllib.parse.urlencode({
        "$select": "bbl,latitude,longitude,address,bldgclass,unitsres,yearbuilt",
        "$where": where,
        "$limit": str(len(bbls) * 2),
    })
    url = f"{ENDPOINT}?{qs}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read())


def main():
    records = json.loads(SRC.read_text())
    by_bbl = {r["bbl"]: r for r in records}
    bbls = list(by_bbl.keys())
    print(f"Looking up {len(bbls)} BBLs in PLUTO...")

    found = {}
    for i in range(0, len(bbls), BATCH):
        chunk = bbls[i:i + BATCH]
        for attempt in range(3):
            try:
                rows = fetch_batch(chunk)
                break
            except Exception as e:
                print(f"  retry {attempt+1} after error: {e}")
                time.sleep(2 ** attempt)
        else:
            print(f"  giving up on batch {i}")
            continue
        for row in rows:
            bbl_int = str(int(float(row["bbl"])))
            if "latitude" in row and "longitude" in row:
                found[bbl_int] = {
                    "lat": float(row["latitude"]),
                    "lon": float(row["longitude"]),
                    "pluto_address": row.get("address"),
                    "bldgclass": row.get("bldgclass"),
                    "unitsres": row.get("unitsres"),
                    "yearbuilt": row.get("yearbuilt"),
                }
        if (i // BATCH) % 10 == 0:
            print(f"  batch {i//BATCH+1}/{(len(bbls)+BATCH-1)//BATCH}, total matched: {len(found)}")

    enriched = []
    for r in records:
        g = found.get(r["bbl"])
        if not g:
            continue
        r2 = dict(r)
        r2.update(g)
        enriched.append(r2)
    print(f"Matched {len(enriched)} / {len(records)} buildings")
    OUT.write_text(json.dumps(enriched))
    print(f"Wrote {OUT} ({OUT.stat().st_size/1024/1024:.1f} MB)")


if __name__ == "__main__":
    main()
