#!/usr/bin/env python3
"""Reduce buildings_geo.json to a compact, map-ready format."""
import json
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "buildings_geo_nta.json"
OUT = HERE / "buildings.min.json"

records = json.loads(SRC.read_text())
slim = []
for r in records:
    addr = r.get("address") or r.get("address_alt") or r.get("pluto_address") or ""
    slim.append({
        "bbl": r["bbl"],
        "b": "M" if r["borough"] == "manhattan" else "Bk",
        "a": addr,
        "z": r.get("zip", ""),
        "lat": round(r["lat"], 6),
        "lng": round(r["lon"], 6),
        "s": r.get("statuses") or [],
        "yr": int(r["yearbuilt"]) if r.get("yearbuilt") and str(r["yearbuilt"]).isdigit() else None,
        "u": int(r["unitsres"]) if r.get("unitsres") and str(r["unitsres"]).isdigit() else None,
        "nb": r.get("nb"),
    })

OUT.write_text(json.dumps(slim, separators=(",", ":")))
print(f"Wrote {OUT} ({OUT.stat().st_size/1024/1024:.2f} MB) with {len(slim)} records")
