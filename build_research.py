#!/usr/bin/env python3
"""
Build the owner/agent portfolio index for the Plus "Research" feature.

Reads buildings_hpd.json (owner + managing-agent names, violations, complaints)
and buildings_geo_nta.json (borough, residential unit count), aggregates per
normalized owner/agent name, and uploads to the private research_names /
research_portfolios tables via the Supabase Data API (service role).

Names are matched by exact normalized string (uppercased, punctuation
stripped). Shell LLCs that differ per building won't merge — the numbers are
"at least this many", which is the honest floor for public HPD data.

Re-run after each HPD refresh (fetch_hpd.py):
  python3 build_research.py
"""
import json, re, subprocess, sys, urllib.request

PROJECT_URL = "https://dbaifotzwlxjvsxjohjt.supabase.co"
BATCH = 4000

GENERIC = {"", "N/A", "NA", "NONE", "SAME", "SAME AS OWNER", "OWNER", "SELF"}


def keychain(service):
    return subprocess.check_output(
        ["security", "find-generic-password", "-s", service, "-w"],
        stderr=subprocess.DEVNULL).decode().strip()


def norm(name):
    if not name:
        return None
    k = re.sub(r"[^A-Z0-9 ]+", " ", name.upper())
    k = re.sub(r"\s+", " ", k).strip()
    return None if k in GENERIC else k


def rest(token, method, path, body=None, prefer=None):
    headers = {"apikey": token, "Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(
        f"{PROJECT_URL}/rest/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} failed ({e.code}): {e.read().decode()[:300]}")


def main():
    hpd = json.load(open("buildings_hpd.json"))
    geo = json.load(open("buildings_geo_nta.json"))
    meta = {}
    for rec in (geo if isinstance(geo, list) else geo.values()):
        units = rec.get("unitsres")
        meta[rec["bbl"]] = (rec.get("borough") or "unknown",
                            int(units) if str(units or "").isdigit() else 0)

    hpd_items = hpd.items() if isinstance(hpd, dict) else ((r["bbl"], r) for r in hpd)
    names, ports = [], {}
    for bbl, h in hpd_items:
        boro, units = meta.get(bbl, ("unknown", 0))
        v, c = h.get("violations") or {}, h.get("complaints") or {}
        row = {"bbl": bbl, "owner_key": None, "agent_key": None}
        for kind, contact_field, key_field in (("owner", "owner", "owner_key"),
                                               ("agent", "manager", "agent_key")):
            contact = h.get(contact_field) or {}
            key = norm(contact.get("name"))
            if not key:
                continue
            row[key_field] = key
            p = ports.setdefault((kind, key), {
                "kind": kind, "key": key, "display_name": contact["name"].strip(),
                "buildings": 0, "units": 0, "by_boro": {},
                "open_violations": 0, "open_complaints": 0, "class_c": 0})
            p["buildings"] += 1
            p["units"] += units
            p["by_boro"][boro] = p["by_boro"].get(boro, 0) + 1
            p["open_violations"] += v.get("open") or 0
            p["open_complaints"] += c.get("open") or 0
            p["class_c"] += v.get("c") or 0
        if row["owner_key"] or row["agent_key"]:
            names.append(row)

    print(f"{len(names)} buildings, {len(ports)} portfolios "
          f"({sum(1 for k in ports if k[0]=='owner')} owners, "
          f"{sum(1 for k in ports if k[0]=='agent')} agents)")

    token = keychain("rent-map-supabase-service-role")
    # full rebuild: names/portfolios can disappear between HPD refreshes
    rest(token, "DELETE", "research_names?bbl=neq.__none__")
    rest(token, "DELETE", "research_portfolios?key=neq.__none__")
    rows = list(ports.values())
    for i in range(0, len(rows), BATCH):
        rest(token, "POST", "research_portfolios", rows[i:i+BATCH])
        print(f"portfolios {min(i+BATCH, len(rows))}/{len(rows)}")
    for i in range(0, len(names), BATCH):
        rest(token, "POST", "research_names", names[i:i+BATCH])
        print(f"names {min(i+BATCH, len(names))}/{len(names)}")
    print("done")


if __name__ == "__main__":
    main()
