"""Everything public the city records say about one building, in one dict
(2026-10-03). The landlord report card and "Ask about this building" read
only this — their answers are grounded in it and cite its section names.

Sources: the register row the site serves (HPD violation/complaint counts,
registration date, units, year), HPD's registered owner/manager
(hpd_contacts), and the latest rows of five NYC Open Data sets — the same
queries the building page runs (index.html OPEN_DATA).
"""
import concurrent.futures, datetime, json, urllib.parse, urllib.request

OD = "https://data.cityofnewyork.us/resource/"
PEST_WHERE = ("(upper(novdescription) like '%INFESTATION CONSISTING OF%' OR upper(novdescription) like '%NUISANCE CONSISTING OF%')"
              " AND (upper(novdescription) like '%ROACH%' OR upper(novdescription) like '%MICE%' OR upper(novdescription) like '%RATS%'"
              " OR upper(novdescription) like '%BEDBUG%' OR upper(novdescription) like '%BED BUG%' OR upper(novdescription) like '%VERMIN%')")
DATASETS = {
    # name: (dataset id, where, order, fields kept per row)
    "evictions": ("6z8x-wfk4", "bbl='{b}'", "executed_date DESC", ["executed_date", "residential_commercial_ind", "eviction_possession"]),
    "housing_court": ("59kj-x8nc", "bbl='{b}'", "caseopendate DESC", ["caseopendate", "casetype", "casestatus", "findingofharassment", "penalty"]),
    "pest_violations": ("wvxf-dwi5", "bbl='{b}' AND " + PEST_WHERE, "novissueddate DESC", ["novissueddate", "class", "currentstatus", "novdescription"]),
    "bedbug_filings": ("wz6d-d3jb", "bbl='{b}'", "filing_date DESC", ["filing_date", "of_dwelling_units", "infested_dwelling_unit_count", "eradicated_unit_count"]),
    "rat_inspections": ("p937-wjvj", "bbl={n}", "inspection_date DESC", ["inspection_date", "inspection_type", "result"]),
}


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "FindACrib/1.0 (+https://findacrib.com)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _dataset(name, bbl):
    ds, where, order, keep = DATASETS[name]
    w = where.format(b=bbl, n=int(bbl))
    try:
        n = int(_get(f"{OD}{ds}.json?$select={urllib.parse.quote('count(*) as n')}&$where={urllib.parse.quote(w)}")[0]["n"])
        rows = _get(f"{OD}{ds}.json?$where={urllib.parse.quote(w)}&$order={urllib.parse.quote(order)}&$limit=8") if n else []
    except Exception:
        return name, {"unavailable": True}
    trimmed = [{k: (str(r.get(k))[:160] if r.get(k) is not None else None) for k in keep} for r in rows]
    return name, {"total": n, "latest": trimmed}


def gather(bbl, building, contacts=None):
    """`building` is the register row; `contacts` the hpd_contacts row."""
    h = building.get("h") or {}
    rec = {
        "as_of": datetime.date.today().isoformat(),
        "building": {"address": building.get("a"), "borough": building.get("b"), "zip": building.get("z"),
                     "neighborhood": building.get("nb"), "units": building.get("u"), "year_built": building.get("yr"),
                     "rent_stabilized": True, "status": building.get("s")},
        "hpd_violations": h.get("violations"),   # a/b/c = class A (non-hazardous) .. C (immediately hazardous); o* = open
        "hpd_complaints": h.get("complaints"),
        "hpd_last_registration": h.get("lastregistration"),
    }
    if contacts:
        rec["registered_owner_and_manager"] = {k: contacts.get(k) for k in ("owner", "manager") if contacts.get(k)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for name, val in ex.map(lambda n: _dataset(n, bbl), DATASETS):
            rec[name] = val
    return rec
