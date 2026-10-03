"""Is this rent fair? (2026-10-03, Find A Crib Plus)

Plain statistics, no model call: a building's advertised rent set against
  - HUD's Fair Market Rent for its ZIP at the advertised bedroom counts, and
  - the advertised rents of other rent-stabilized buildings in the same
    neighborhood that list the same bedroom counts.
The data has one advertised rent per building (listings.json), so the
comparison is building to building, and the answer says so. For a
rent-stabilized apartment the real check is the unit's registered rent
history, which the tenant can request from HCR; the answer always says how.
"""
import statistics


def check(bbl, buildings_by_bbl, listings, fmr):
    b = buildings_by_bbl.get(bbl)
    prices, beds = listings.get("prices") or {}, listings.get("beds") or {}
    p = prices.get(bbl)
    if not b or not p:
        return {"ok": False, "reason": "no_price"}
    bd = sorted(set(beds.get(bbl) or []))
    out = {"ok": True, "price": p, "beds": bd, "notes": []}
    # HUD FMR for the ZIP: [studio, 1BR, 2BR, 3BR]; 4+ uses the 3BR figure.
    f = fmr.get(b.get("z") or "")
    if f:
        want = [f[min(x, 3)] for x in bd] if bd else [f[0], f[2]]
        out["fmr_low"], out["fmr_high"] = min(want), max(want)
    # Same neighborhood, same bedroom counts (or any, if none listed).
    comps = []
    for k, q in prices.items():
        if k == bbl or not q:
            continue
        o = buildings_by_bbl.get(k)
        if not o or o.get("nb") != b.get("nb"):
            continue
        ob = set(beds.get(k) or [])
        if bd and not (ob & set(bd)):
            continue
        comps.append(q)
    out["comps"] = len(comps)
    if len(comps) >= 3:
        med = statistics.median(comps)
        out["nb_median"] = int(med)
        out["percentile"] = int(round(100 * sum(1 for q in comps if q < p) / len(comps)))
    # Verdict from whichever comparison exists, preferring local comps.
    ref = out.get("nb_median") or ((out["fmr_low"] + out["fmr_high"]) / 2 if f else None)
    if ref:
        r = p / ref
        out["ratio"] = round(r, 2)
        out["verdict"] = "high" if r >= 1.2 else ("low" if r <= 0.85 else "typical")
    else:
        out["verdict"] = "unknown"
    out["notes"].append("Rent-stabilized? Ask HCR for this apartment's rent history (free): "
                        "the legal rent can't jump past the registered rent plus allowed increases.")
    return out
