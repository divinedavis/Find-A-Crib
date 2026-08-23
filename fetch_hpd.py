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


PAGE = 50000          # Socrata's per-request ceiling


def fetch_all(url, params):
    """fetch(), but paged. A bare $limit=50000 is a silent truncation: Socrata
    returns the cap and no indication there was more, so a dense block/lot chunk
    (the Bronx runs to 170k complaint rows per 200 BBLs) quietly dropped most of
    its rows and every count built from them came out low."""
    out = []
    offset = 0
    while True:
        page = fetch(url, {**params, "$limit": str(PAGE), "$offset": str(offset)})
        out.extend(page)
        if len(page) < PAGE:
            return out
        offset += PAGE


def counts(url, select, where, group):
    """One grouped COUNT instead of every matching row. The aggregate is what we
    actually want, it cannot be truncated at any volume we hit (the widest group
    here is 60 blocks x 60 lots x class x status), and it moves megabytes of rows
    off the wire."""
    rows = fetch_all(url, {
        "$select": f"{select},count(1) as n",
        "$where": where,
        "$group": group,
    })
    return rows


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
                rows = fetch_all(REGISTRATIONS, {
                    "$select": "registrationid,buildingid,boroid,block,lot,lastregistrationdate,registrationenddate",
                    "$where": where,
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
        rows = fetch_all(CONTACTS, {
            "$select": ("registrationid,type,contactdescription,firstname,lastname,"
                        "corporationname,businesshousenumber,businessstreetname,"
                        "businessapartment,businesscity,businessstate,businesszip"),
            "$where": f"registrationid in ({quote_csv(chunk)})",
        })
        for row in rows:
            out[row["registrationid"]].append(row)
        if i % 20 == 0:
            print(f"  contacts: {i*100}/{len(rids)} regs, total contacts {sum(len(v) for v in out.values())}")
    return out


def fetch_violations(by_boro):
    """Returns dict BBL -> aggregates."""
    # a/b/c count every violation on record; oa/ob/oc count only the ones HPD
    # still has open, so the class chips can sum to the open count instead of
    # sitting above a list of open violations that disagrees with them.
    out = defaultdict(lambda: {"open": 0, "closed": 0, "total": 0,
                                "a": 0, "b": 0, "c": 0,
                                "oa": 0, "ob": 0, "oc": 0, "last_12mo": 0})
    for boroid, parts in by_boro.items():
        blocks = sorted({p[0] for p in parts})
        lots = sorted({p[1] for p in parts})
        parts_set = set(parts)
        seen = 0
        for i, blk_chunk in enumerate(chunked(blocks, 60)):
            for lot_chunk in chunked(lots, 60):
                where = (f"boroid='{boroid}' AND block in ({quote_csv(blk_chunk)}) "
                         f"AND lot in ({quote_csv(lot_chunk)})")
                # class x status per building, then the last-12-months count on
                # its own: the date filter cuts across both of the other two.
                for row in counts(VIOLATIONS, "block,lot,class,violationstatus",
                                  where, "block,lot,class,violationstatus"):
                    blk = str(int(row["block"]))
                    lt = str(int(row["lot"]))
                    if (blk, lt) not in parts_set:
                        continue
                    n = int(row["n"])
                    seen += n
                    agg = out[parts_to_bbl(boroid, blk, lt)]
                    agg["total"] += n
                    cls = (row.get("class") or "").lower()
                    if cls in ("a", "b", "c"):
                        agg[cls] += n
                    # HPD's own Open/Close flag, not the free-text currentstatus:
                    # that one reads "VIOLATION DISMISSED" as still open, which
                    # inflated every count and disagreed with the per-violation
                    # list the site now shows in the building detail sheet.
                    if (row.get("violationstatus") or "").lower().startswith("open"):
                        agg["open"] += n
                        if cls in ("a", "b", "c"):
                            agg["o" + cls] += n
                    else:
                        agg["closed"] += n
                for row in counts(VIOLATIONS, "block,lot",
                                  where + f" AND novissueddate >= '{ONE_YEAR_AGO}'",
                                  "block,lot"):
                    blk = str(int(row["block"]))
                    lt = str(int(row["lot"]))
                    if (blk, lt) not in parts_set:
                        continue
                    out[parts_to_bbl(boroid, blk, lt)]["last_12mo"] += int(row["n"])
            if i % 5 == 0:
                print(f"  violations boro {boroid}: blocks {i*60}/{len(blocks)}, "
                      f"violations counted {seen}, BBLs matched {len(out)}")
    return out


def fetch_complaints(bbls):
    out = defaultdict(lambda: {"open": 0, "closed": 0, "total": 0, "last_12mo": 0})
    bbl_list = list(bbls)
    for i, chunk in enumerate(chunked(bbl_list, 200)):
        where = f"bbl in ({quote_csv(chunk)})"
        for row in counts(COMPLAINTS, "bbl,complaint_status", where, "bbl,complaint_status"):
            bbl = row.get("bbl")
            if not bbl:
                continue
            n = int(row["n"])
            agg = out[bbl]
            agg["total"] += n
            if (row.get("complaint_status") or "").upper() == "CLOSE":
                agg["closed"] += n
            else:
                agg["open"] += n
        for row in counts(COMPLAINTS, "bbl",
                          where + f" AND received_date >= '{ONE_YEAR_AGO}'", "bbl"):
            bbl = row.get("bbl")
            if bbl:
                out[bbl]["last_12mo"] += int(row["n"])
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


def main(counts_only=False):
    buildings = json.loads(BUILDINGS.read_text())
    bbls = [b["bbl"] for b in buildings]
    print(f"Loading HPD data for {len(bbls):,} buildings")

    by_boro = defaultdict(list)
    for bbl in bbls:
        boroid, block, lot = bbl_to_parts(bbl)
        if boroid not in BORO_NAME:
            continue
        by_boro[boroid].append((block, lot))

    # --counts-only refreshes just the violation and complaint aggregates and
    # keeps the registration + contact block already on disk. Those contacts are
    # mirrored into the hpd_contacts Supabase table by build_hpd_contacts.py, so
    # re-pulling them here without re-uploading would put the two out of step —
    # and the counts are what goes stale between owners changing.
    prior = {}
    if counts_only:
        if not OUT.exists():
            raise SystemExit(f"--counts-only needs an existing {OUT.name} to merge into")
        prior = json.loads(OUT.read_text())
        print(f"\n[1/2] Reusing registrations + contacts for {len(prior):,} "
              f"buildings from {OUT.name}")
        regs, contacts_by_reg = {}, {}
    else:
        print("\n[1/4] Fetching HPD registrations...")
        regs = fetch_registrations(by_boro)
        print(f"  -> {len(regs):,} buildings registered with HPD")

        print("\n[2/4] Fetching HPD contacts...")
        contacts_by_reg = fetch_contacts({r["registrationid"] for r in regs.values()})
        print(f"  -> contacts for {len(contacts_by_reg):,} registrations")

    print(f"\n[{'2/2' if counts_only else '3/4'}] Fetching HPD violations...")
    violations = fetch_violations(by_boro)
    print(f"  -> violation records for {len(violations):,} buildings")

    print(f"\n[{'2/2' if counts_only else '4/4'}] Fetching HPD complaints...")
    complaints = fetch_complaints(bbls)
    print(f"  -> complaint records for {len(complaints):,} buildings")

    result = {}
    for bbl in bbls:
        entry = {}
        if counts_only:
            # Carry the banked registration/contact fields over verbatim; the
            # count keys are rebuilt below from this run, so a building whose
            # last open violation closed loses the stale block rather than
            # keeping it.
            entry = {k: v for k, v in prior.get(bbl, {}).items()
                     if k not in ("violations", "complaints")}
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
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--counts-only", action="store_true",
                    help="refresh only violation + complaint counts, merging "
                         "into the existing buildings_hpd.json")
    main(counts_only=ap.parse_args().counts_only)
