#!/usr/bin/env python3
"""Assign each building a 2020 NTA via point-in-polygon, with a SoHo/Nolita override.

Reads buildings_geo.json + nta_2020.geojson; writes buildings_geo_nta.json adding
{ nta: 'MN0201', nb: 'SoHo' } per record.
"""
import json
from pathlib import Path
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

HERE = Path(__file__).parent
SRC = HERE / "buildings_geo.json"
NTA = HERE / "nta_2020.geojson"
OUT = HERE / "buildings_geo_nta.json"

# Within MN0201 (SoHo-Little Italy-Hudson Square), split into:
#   Nolita: bounded by Lafayette/Mulberry (west) and Bowery (east), Houston (north), Broome (south)
#   SoHo:   everything else west of Lafayette
# Coordinates are (lat_min, lat_max, lon_min, lon_max) for Nolita box.
NOLITA_BOX = (40.7200, 40.7270, -73.9985, -73.9908)

# Friendly display names. Anything not listed falls back to ntaname.
NB_RENAME = {
    "MN0201": None,  # handled by override below
    "MN0303": "East Village",
    "BK0102": "Williamsburg",
    "BK0103": "South Williamsburg",
    "BK0104": "East Williamsburg",
    "BK0301": "Bed-Stuy (West)",
    "BK0302": "Bed-Stuy (East)",
}


def load_polygons():
    g = json.loads(NTA.read_text())
    feats = []
    geoms = []
    for f in g["features"]:
        if not f.get("geometry"):
            continue
        props = f["properties"]
        if props.get("ntatype") != "0":  # 0 = residential NTA. parks/airports/cemeteries are non-zero
            # we still want all of them but residential is most relevant
            pass
        geom = shape(f["geometry"])
        geoms.append(geom)
        feats.append(props)
    tree = STRtree(geoms)
    return geoms, feats, tree


def main():
    records = json.loads(SRC.read_text())
    print(f"loaded {len(records)} buildings")
    geoms, feats, tree = load_polygons()
    print(f"loaded {len(geoms)} NTA polygons")

    out = []
    miss = 0
    nb_counts = {}
    for r in records:
        pt = Point(r["lon"], r["lat"])
        idxs = tree.query(pt)
        nta_code = None
        nta_name = None
        for i in idxs:
            if geoms[i].contains(pt):
                nta_code = feats[i].get("nta2020")
                nta_name = feats[i].get("ntaname")
                break
        if not nta_code:
            miss += 1

        # SoHo / Nolita override within MN0201
        if nta_code == "MN0201":
            lat, lon = r["lat"], r["lon"]
            if (NOLITA_BOX[0] <= lat <= NOLITA_BOX[1]
                    and NOLITA_BOX[2] <= lon <= NOLITA_BOX[3]):
                nb = "Nolita"
            else:
                nb = "SoHo"
        elif nta_code in NB_RENAME and NB_RENAME[nta_code]:
            nb = NB_RENAME[nta_code]
        else:
            nb = nta_name

        r2 = dict(r)
        r2["nta"] = nta_code
        r2["nb"] = nb
        out.append(r2)
        if nb:
            nb_counts[nb] = nb_counts.get(nb, 0) + 1

    print(f"buildings without an NTA hit: {miss}")
    print("top neighborhoods (by building count):")
    for nb, c in sorted(nb_counts.items(), key=lambda x: -x[1])[:25]:
        print(f"  {c:6d}  {nb}")

    OUT.write_text(json.dumps(out))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
