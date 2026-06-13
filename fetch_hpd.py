#!/usr/bin/env python3
"""Pull HPD Registrations + Contacts + Complaints + Violations from NYC Open Data,
join to each BBL in buildings.min.json, write buildings_hpd.json."""
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
BUILDINGS = HERE / "buildings.min.json"
OUT = HERE / "buildings_hpd.json"

REGISTRATIONS = "https://data.cityofnewyork.us/resource/tesw-yqqr.json"
CONTACTS = "https://data.cityofnewyork.us/resource/feu5-w2e2.json"
VIOLATIONS = "https://data.cityofnewyork.us/resource/wvxf-dwi5.json"
COMPLAINTS = "https://data.cityofnewyork.us/resource/ygpa-z7cr.json"

BORO_NAME = {"1": "manhattan", "2": "bronx", "3": "brooklyn", "4": "queens", "5": "staten_island"}
NAME_BORO = {v: k for k, v in BORO_NAME.items()}
ONE_YEAR_AGO = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00")

CONTACT_PRIORITY = [
    "HeadOfficer", "IndividualOwner", "CorporateOwner", "JointOwner",
    "Officer", "Shareholder", "SiteManager", "Agent", "Lessee",
]


def fetch(url, params, retries=3):
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "rentmap-hpd/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ! giving up on {full[:120]}... — {e}")
                return []
            time.sleep(2 ** attempt)


def bbl_to_parts(bbl):
    """'3013610043' -> ('3', '1361', '43') with leading zeros stripped."""
    s = str(bbl).zfill(10)
    return s[0], str(int(s[1:6])), str(int(s[6:10]))


def parts_to_bbl(boroid, block, lot):
    return f"{int(boroid)}{int(block):05d}{int(lot):04d}"


def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def quote_csv(values):
    return ",".join(f"'{v}'" for v in values)


def fetch_registrations(by_boro):
    """Returns dict BBL -> {registrationid, buildingid, lastregistrationdate}."""
    out = {}
    for boroid, parts in by_boro.items():
        blocks = sorted({p[0] for p in parts})
        lots = sorted({p[1] for p in parts})
        parts_set = set(parts)
        total = 0
        for i, blk_chunk in enumerate(chunked(blocks, 60)):
            for lot_chunk in chunked(lots, 60):
                where = (f"boroid='{boroid}' AND block in ({quote_csv(blk_chunk)}) "
                         f"AND lot in ({quote_csv(lot_chunk)})")
                rows = fetch(REGISTRATIONS, {
                    "$select": "registrationid,buildingid,boroid,block,lot,lastregistrationdate,registrationenddate",
                    "$where": where,
                    "$limit": "50000",
                })
                for row in rows:
                    blk = str(int(row["block"]))
                    lt = str(int(row["lot"]))
                    if (blk, lt) not in parts_set:
                        continue
                    bbl = parts_to_bbl(boroid, blk, lt)
                    prev = out.get(bbl)
                    if prev and prev.get("lastregistrationdate", "") >= row.get("lastregistrationdate", ""):
                        continue
                    out[bbl] = {
                        "registrationid": row["registrationid"],
                        "buildingid": row.get("buildingid"),
                        "lastregistrationdate": row.get("lastregistrationdate", ""),
                        "registrationenddate": row.get("registrationenddate", ""),
                    }
                total += len(rows)
            if i % 5 == 0:
                print(f"  registrations boro {boroid}: blocks {i*60}/{len(blocks)}, "
                      f"rows seen {total}, matched {len(out)}")
    return out


def fetch_contacts(registration_ids):
    """Returns dict registrationid -> [contact dicts]."""
    out = defaultdict(list)
    rids = list(registration_ids)
    for i, chunk in enumerate(chunked(rids, 100)):
        rows = fetch(CONTACTS, {
            "$select": ("registrationid,type,contactdescription,firstname,lastname,"
                        "corporationname,businesshousenumber,businessstreetname,"
                        "businessapartment,businesscity,businessstate,businesszip"),
            "$where": f"registrationid in ({quote_csv(chunk)})",
            "$limit": "50000",
        })
        for row in rows:
            out[row["registrationid"]].append(row)
        if i % 20 == 0:
            print(f"  contacts: {i*100}/{len(rids)} regs, total contacts {sum(len(v) for v in out.values())}")
    return out


def fetch_violations(by_boro):
    """Returns dict BBL -> aggregates."""
    out = defaultdict(lambda: {"open": 0, "closed": 0, "total": 0,
                                "a": 0, "b": 0, "c": 0, "last_12mo": 0})
    for boroid, parts in by_boro.items():
        blocks = sorted({p[0] for p in parts})
        lots = sorted({p[1] for p in parts})
        parts_set = set(parts)
        total = 0
        for i, blk_chunk in enumerate(chunked(blocks, 60)):
            for lot_chunk in chunked(lots, 60):
                where = (f"boroid='{boroid}' AND block in ({quote_csv(blk_chunk)}) "
                         f"AND lot in ({quote_csv(lot_chunk)})")
                rows = fetch(VIOLATIONS, {
                    "$select": "boroid,block,lot,class,currentstatus,novissueddate",
                    "$where": where,
                    "$limit": "50000",
                })
                for row in rows:
                    blk = str(int(row["block"]))
                    lt = str(int(row["lot"]))
                    if (blk, lt) not in parts_set:
                        continue
                    bbl = parts_to_bbl(boroid, blk, lt)
                    agg = out[bbl]
                    agg["total"] += 1
                    cls = (row.get("class") or "").lower()
                    if cls in ("a", "b", "c"):
                        agg[cls] += 1
                    status = (row.get("currentstatus") or "").upper()
                    if "CLOSED" in status:
                        agg["closed"] += 1
                    else:
                        agg["open"] += 1
                    issued = row.get("novissueddate", "")
                    if issued and issued >= ONE_YEAR_AGO:
                        agg["last_12mo"] += 1
                total += len(rows)
            if i % 5 == 0:
                print(f"  violations boro {boroid}: blocks {i*60}/{len(blocks)}, "
                      f"rows seen {total}, BBLs matched {len(out)}")
    return out


def fetch_complaints(bbls):
    out = defaultdict(lambda: {"open": 0, "closed": 0, "total": 0, "last_12mo": 0})
    bbl_list = list(bbls)
    for i, chunk in enumerate(chunked(bbl_list, 200)):
        rows = fetch(COMPLAINTS, {
            "$select": "bbl,complaint_status,received_date",
            "$where": f"bbl in ({quote_csv(chunk)})",
            "$limit": "50000",
        })
        for row in rows:
            bbl = row.get("bbl")
            if not bbl:
                continue
            agg = out[bbl]
            agg["total"] += 1
            status = (row.get("complaint_status") or "").upper()
            if status == "CLOSE":
                agg["closed"] += 1
            else:
                agg["open"] += 1
            received = row.get("received_date", "")
            if received and received >= ONE_YEAR_AGO:
                agg["last_12mo"] += 1
        if i % 10 == 0:
            print(f"  complaints: {i*200}/{len(bbl_list)} BBLs, total complaints "
                  f"{sum(v['total'] for v in out.values())}")
    return out


def pick_contact(contacts, types):
    """Return first contact matching any type in `types`, in order."""
    for t in types:
        for c in contacts:
            if c.get("type") == t:
                return c
    return None


def format_name(contact):
    if not contact:
        return None
    corp = contact.get("corporationname")
    if corp:
        return corp.strip()
    first = (contact.get("firstname") or "").strip()
    last = (contact.get("lastname") or "").strip()
    full = f"{first} {last}".strip()
    return full or None


def format_address(contact):
    if not contact:
        return None
    parts = []
    house = (contact.get("businesshousenumber") or "").strip()
    street = (contact.get("businessstreetname") or "").strip()
    line1 = f"{house} {street}".strip()
    apt = (contact.get("businessapartment") or "").strip()
    if apt and apt.upper() not in ("N/A", "NONE"):
        line1 = f"{line1} #{apt}".strip()
    if line1:
        parts.append(line1)
    city = (contact.get("businesscity") or "").strip()
    state = (contact.get("businessstate") or "").strip()
    zipc = (contact.get("businesszip") or "").strip()
    line2 = ", ".join(x for x in [city, state] if x)
    if zipc:
        line2 = f"{line2} {zipc}".strip()
    if line2:
        parts.append(line2)
    return " · ".join(parts) or None


def main():
    buildings = json.loads(BUILDINGS.read_text())
    bbls = [b["bbl"] for b in buildings]
    print(f"Loading HPD data for {len(bbls):,} buildings")

    by_boro = defaultdict(list)
    for bbl in bbls:
        boroid, block, lot = bbl_to_parts(bbl)
        if boroid not in BORO_NAME:
            continue
        by_boro[boroid].append((block, lot))

    print("\n[1/4] Fetching HPD registrations...")
    regs = fetch_registrations(by_boro)
    print(f"  -> {len(regs):,} buildings registered with HPD")

    print("\n[2/4] Fetching HPD contacts...")
    contacts_by_reg = fetch_contacts({r["registrationid"] for r in regs.values()})
    print(f"  -> contacts for {len(contacts_by_reg):,} registrations")

    print("\n[3/4] Fetching HPD violations...")
    violations = fetch_violations(by_boro)
    print(f"  -> violation records for {len(violations):,} buildings")

    print("\n[4/4] Fetching HPD complaints...")
    complaints = fetch_complaints(bbls)
    print(f"  -> complaint records for {len(complaints):,} buildings")

    result = {}
    for bbl in bbls:
        entry = {}
        reg = regs.get(bbl)
        if reg:
            entry["registrationid"] = reg["registrationid"]
            entry["lastregistration"] = reg.get("lastregistrationdate", "")[:10]
            entry["registrationend"] = reg.get("registrationenddate", "")[:10]
            if reg.get("buildingid"):
                entry["buildingid"] = reg["buildingid"]
                entry["hpd_url"] = f"https://hpdonline.nyc.gov/hpdonline/building/{reg['buildingid']}/overview"
            contacts = contacts_by_reg.get(reg["registrationid"], [])
            owner = pick_contact(contacts, ["IndividualOwner", "CorporateOwner", "JointOwner", "HeadOfficer"])
            manager = pick_contact(contacts, ["Agent", "SiteManager"])
            officer = pick_contact(contacts, ["HeadOfficer", "Officer", "Shareholder"])
            if owner:
                entry["owner"] = {
                    "name": format_name(owner),
                    "type": owner.get("type"),
                    "address": format_address(owner),
                }
            if manager:
                entry["manager"] = {
                    "name": format_name(manager),
                    "type": manager.get("type"),
                    "address": format_address(manager),
                }
            if officer and (not owner or officer.get("type") != owner.get("type")):
                entry["officer"] = {
                    "name": format_name(officer),
                    "type": officer.get("type"),
                    "address": format_address(officer),
                }
        v = violations.get(bbl)
        if v:
            entry["violations"] = dict(v)
        c = complaints.get(bbl)
        if c:
            entry["complaints"] = dict(c)
        if entry:
            result[bbl] = entry

    OUT.write_text(json.dumps(result, separators=(",", ":")))
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"\nWrote {OUT} ({size_mb:.2f} MB) for {len(result):,} buildings")


if __name__ == "__main__":
    main()
