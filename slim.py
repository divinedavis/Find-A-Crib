#!/usr/bin/env python3
"""Reduce buildings_geo.json to a compact, map-ready format and merge HPD data."""
import json
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "buildings_geo_nta.json"
HPD = HERE / "buildings_hpd.json"
OUT = HERE / "buildings.min.json"

records = json.loads(SRC.read_text())
hpd = json.loads(HPD.read_text()) if HPD.exists() else {}

# short borough codes used by the front end
BORO_SHORT = {"manhattan": "M", "bronx": "Bx", "brooklyn": "Bk", "queens": "Q", "staten_island": "SI"}

slim = []
for r in records:
    addr = r.get("address") or r.get("address_alt") or r.get("pluto_address") or ""
    rec = {
        "bbl": r["bbl"],
        "b": BORO_SHORT.get(r["borough"], "?"),
        "a": addr,
        "z": r.get("zip", ""),
        "lat": round(r["lat"], 6),
        "lng": round(r["lon"], 6),
        "s": r.get("statuses") or [],
        "yr": int(r["yearbuilt"]) if r.get("yearbuilt") and str(r["yearbuilt"]).isdigit() else None,
        "u": int(r["unitsres"]) if r.get("unitsres") and str(r["unitsres"]).isdigit() else None,
        "nb": r.get("nb"),
    }
    h = hpd.get(r["bbl"])
    if h:
        # Phone numbers are a paid feature: never ship the actual number in the
        # public file. Convert any contact phone to a has_phone boolean flag.
        for role in ("owner", "manager", "officer"):
            c = h.get(role)
            if isinstance(c, dict):
                c.pop("phone_confidence", None)
                if c.pop("phone", None):
                    c["has_phone"] = True
        rec["h"] = h
    slim.append(rec)

OUT.write_text(json.dumps(slim, separators=(",", ":")))
hpd_matched = sum(1 for s in slim if "h" in s)
print(f"Wrote {OUT} ({OUT.stat().st_size/1024/1024:.2f} MB) with {len(slim)} records "
      f"({hpd_matched:,} with HPD data)")
