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
        # Operator contacts (owner/manager/officer) were 79% of this file.
        # They now live in the hpd_contacts Supabase table (uploaded by
        # build_hpd_contacts.py) and are lazy-loaded per building; h.op=1
        # tells the frontend contacts exist. Keep only what the map needs:
        # violation/complaint counts (filters, sort, cards), the HPD link,
        # and the registration date.
        slim_h = {}
        for k in ("violations", "complaints"):
            counts = h.get(k)
            if isinstance(counts, dict):
                # "closed" is never used by the frontend; drop it
                slim_h[k] = {ck: cv for ck, cv in counts.items() if ck != "closed"}
        if h.get("lastregistration"):
            slim_h["lastregistration"] = h["lastregistration"]
        # hpd_url is reconstructed client-side from the building id (saves ~2.5MB)
        if h.get("buildingid"):
            slim_h["bid"] = h["buildingid"]
        if any(h.get(role) for role in ("owner", "manager", "officer")):
            slim_h["op"] = 1
        # ph=1 means the managing agent has a phone on file. The number itself
        # is never published — it lives in the private agent_phones table behind
        # the Plus-gated get_agent_phone(). The flag is what the map's
        # "managing agent has a phone listed" filter tests, and it is the same
        # fact the building panel already exposes as has_phone.
        mgr = h.get("manager")
        if isinstance(mgr, dict) and mgr.get("phone"):
            slim_h["ph"] = 1
        rec["h"] = slim_h
    slim.append(rec)

OUT.write_text(json.dumps(slim, separators=(",", ":")))
hpd_matched = sum(1 for s in slim if "h" in s)
print(f"Wrote {OUT} ({OUT.stat().st_size/1024/1024:.2f} MB) with {len(slim)} records "
      f"({hpd_matched:,} with HPD data)")
