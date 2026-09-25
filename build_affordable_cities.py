#!/usr/bin/env python3
"""Build chi/ mia/ atl/ phl/ — income-restricted buildings for four new cities.

Owner, 2026-09-24: "lets add the four cities - lets only add cities" (Chicago,
Miami, Atlanta, Philadelphia), after research that found none of them runs a
lottery portal like NYC's Housing Connect: affordable units there are applied
for building by building. What each city DOES publish is where those
buildings are — so each gets a map, built by merging:

  every city   HUD Low-Income Housing Tax Credit register (ArcGIS)
               HUD Public Housing Developments (ArcGIS), by housing authority
  Chicago      City DOH Affordable Requirements Ordinance buildings (ArcGIS):
                 ARO units, manager, phone, website
               City DOH Affordable Rental Housing Developments (Socrata s6ha-ppgi)
  Miami-Dade   Florida Housing Finance Corp rental properties (ArcGIS, Shimberg):
                 status incl. "Active - In Lease-Up", units, owner
               HUD / USDA-RD assisted properties (same host): bedroom mix
  Atlanta      City Office of Housing Housing Tracker (ArcGIS): units by AMI band
               Atlanta Beltline affordable developments (ArcGIS): AMI bands, IZ units
  Philadelphia DHCD Affordable Housing Production (ArcGIS): city-funded projects

The same building turns up in several of these, so rows are merged on a
normalised address (house number + street + ZIP), then on being within ~40 m
with the same house number. A merged building keeps every program that
funds it and the richest value of each field.

Output per city (same keys as the other cities' files, Building.swift /
BuildingRecord.swift):
    <city>/buildings.slim.json.gz   map rows
    <city>/buildings.hpd.json.gz    per-building record
and <city>/leasing.json — Miami's FHFC "In Lease-Up" buildings, which
build_openings.py lists in the Lotteries tab.

Usage:  python3 build_affordable_cities.py [--out .] [--only chi,mia]
"""
import argparse
import gzip
import hashlib
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "findacrib.com building map (+https://findacrib.com)"
LIHTC = "https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/LIHTC/FeatureServer/0"
PUBHOUSING = "https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/Public_Housing_Developments/FeatureServer/0"
ARO = ("https://services7.arcgis.com/A03QrhyHnDaUmK0W/arcgis/rest/services/"
       "Geocoding_Result_ARO_Map_and_Dashboard_Data_Updated_02_06_2026_view/FeatureServer/0")
CHI_SOCRATA = "https://data.cityofchicago.org/resource/s6ha-ppgi.json"
FHFC = "https://services8.arcgis.com/GfH4uM8d7iVMXBlB/arcgis/rest/services/FHFC_Rental_Properties_as_of_05_15_2026/FeatureServer/0"
HUDRD = "https://services8.arcgis.com/GfH4uM8d7iVMXBlB/arcgis/rest/services/HUD_RD_Properties_as_of_2026_02_04/FeatureServer/0"
ATL_TRACKER = "https://services5.arcgis.com/5RxyIIJ9boPdptdo/arcgis/rest/services/Housing_Tracker_Public_View_092122/FeatureServer/0"
BELTLINE = "https://gis.beltline.org/server/rest/services/ABI_HPD_Developments_public/FeatureServer/0"
PHL_DHCD = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/AffordableHousingProduction/FeatureServer/0"

LIHTC_FIELDS = ("HUD_ID,PROJECT,PROJ_ADD,PROJ_CTY,PROJ_ST,PROJ_ZIP,N_UNITS,LI_UNITS,N_0BR,N_1BR,N_2BR,"
                "N_3BR,N_4BR,INC_CEIL,YR_PIS,TRGT_FAM,TRGT_ELD,TRGT_DIS,TRGT_HML,NON_PROF")
INCOME = {"1": "50% of area median income", "2": "60% of area median income",
          "3": "Income averaging (up to 80% of area median)"}
FIRST_YEAR = 1990

CITIES = {
    "chi": {"name": "Chicago", "st": "IL", "code": "CHI", "lihtc": "PROJ_ST='IL' AND PROJ_CTY='CHICAGO'",
            "pha": "IL002"},
    "mia": {"name": "Miami-Dade", "st": "FL", "code": "MIA", "lihtc": "PROJ_ST='FL'",
            # LIHTC carries no county on this layer: keep what falls in Miami-Dade's box.
            "bbox": (25.13, 25.98, -80.88, -80.11), "pha": "FL005"},
    "atl": {"name": "Atlanta", "st": "GA", "code": "ATL", "lihtc": "PROJ_ST='GA' AND PROJ_CTY='ATLANTA'",
            "pha": "GA006"},
    "phl": {"name": "Philadelphia", "st": "PA", "code": "PHL", "lihtc": "PROJ_ST='PA' AND PROJ_CTY='PHILADELPHIA'",
            "pha": "PA002"},
}


# ------------------------------------------------------------------ fetching

def http_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r)
            if isinstance(d, dict) and "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"cities: retry {url[:80]}… after {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))


def arcgis(layer, where="1=1", fields="*", page=1000):
    rows, off = [], 0
    while True:
        q = urllib.parse.urlencode({"where": where, "outFields": fields, "outSR": 4326, "f": "json",
                                    "resultOffset": off, "resultRecordCount": page})
        d = http_json(f"{layer}/query?{q}")
        got = d.get("features") or []
        for f in got:
            a = dict(f.get("attributes") or {})
            g = f.get("geometry") or {}
            if g.get("y") is not None:
                a["_lat"], a["_lng"] = g["y"], g["x"]
            rows.append(a)
        if len(got) < page and not d.get("exceededTransferLimit"):
            return rows
        off += len(got)
        time.sleep(0.3)


# ------------------------------------------------------------------ helpers

def title(s):
    s = re.sub(r"\s+", " ", (s or "").strip())
    return " ".join(w if re.match(r"^\d", w) else w.capitalize() for w in s.lower().split(" ")) if s else ""


def num(v):
    try:
        n = int(float(v))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def zip5(z):
    d = re.sub(r"\D", "", str(z or ""))
    return d.zfill(5)[:5] if d else None


def phone(p):
    d = re.sub(r"\D", "", p or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return f"{d[:3]}-{d[3:6]}-{d[6:]}" if len(d) == 10 else None


def web(u):
    u = (u or "").strip()
    if not u or " " in u:
        return None
    return u if u.startswith("http") else f"https://{u}"


SUFFIX = {"STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "BOULEVARD": "BLVD", "ROAD": "RD", "DRIVE": "DR",
          "PLACE": "PL", "COURT": "CT", "LANE": "LN", "PARKWAY": "PKWY", "TERRACE": "TER", "HIGHWAY": "HWY",
          "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHWEST": "NW", "NORTHEAST": "NE",
          "SOUTHWEST": "SW", "SOUTHEAST": "SE"}


def addr_key(addr, z):
    """'15-17 Lincoln Park Street' + 07102 -> ('15', 'LINCOLN PARK ST', '07102')."""
    a = re.sub(r"[.,#]", " ", (addr or "").upper())
    a = a.split(" UNIT ")[0].split(" APT ")[0].split(" STE ")[0]
    toks = [SUFFIX.get(t, t) for t in a.split()]
    if not toks or not re.match(r"^\d", toks[0]):
        return None
    house = re.match(r"\d+", toks[0]).group()
    street = " ".join(toks[1:4])
    return (house, street, zip5(z) or "")


def split_city_zip(s):
    """'835 OGLETHORPE AVE SW, ATLANTA, GA 30310' -> ('835 OGLETHORPE AVE SW', '30310')."""
    s = (s or "").strip()
    z = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", s)
    return s.split(",")[0].strip(), (z.group(1) if z else None)


def norm_name(n):
    n = re.sub(r"[^a-z0-9 ]", " ", (n or "").lower())
    n = re.sub(r"\b(the|apartments?|apts?|homes|residences|phase|ph|i+|iv|v|senior|lp|llc)\b", " ", n)
    return " ".join(n.split())


def metres(a, b):
    dy = (a[0] - b[0]) * 111_000
    dx = (a[1] - b[1]) * 111_000 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def fmt_ami(bands):
    """[("30%", 10), ("60%", 40)] -> "10 at 30% AMI · 40 at 60% AMI"."""
    parts = [f"{n} at {lbl} AMI" for lbl, n in bands if n]
    return " · ".join(parts) or None


# ------------------------------------------------------------------ sources
# Each yields dicts with: src, name, addr, zip, lat, lng, units, li, mix,
# inc, ami, serves, mgr, tel, web, yr, status, prog, vac, wait

def lihtc(city):
    c = CITIES[city]
    out = []
    for a in arcgis(LIHTC, c["lihtc"], LIHTC_FIELDS, page=2000):
        yr = str(a.get("YR_PIS") or "")
        if yr.isdigit() and yr not in ("8888", "9999") and int(yr) < FIRST_YEAR:
            continue
        mix = {k: n for k, f in (("0", "N_0BR"), ("1", "N_1BR"), ("2", "N_2BR"), ("3", "N_3BR"), ("4", "N_4BR"))
               if (n := num(a.get(f)))}
        who = [w for w, f in (("families", "TRGT_FAM"), ("seniors", "TRGT_ELD"),
                              ("people with disabilities", "TRGT_DIS"), ("people leaving homelessness", "TRGT_HML"))
               if str(a.get(f) or "") == "1"]
        name = re.sub(r"^(LITC|LIHTC)\s*#?\s*\d+\s*", "", a.get("PROJECT") or "", flags=re.I)
        out.append({"src": "tax credit", "name": title(name), "addr": a.get("PROJ_ADD"), "zip": a.get("PROJ_ZIP"),
                    "lat": a.get("_lat"), "lng": a.get("_lng"), "units": num(a.get("N_UNITS")),
                    "li": num(a.get("LI_UNITS")), "mix": mix or None, "inc": INCOME.get(str(a.get("INC_CEIL") or "")),
                    "serves": who or None, "np": 1 if str(a.get("NON_PROF") or "") == "1" else None,
                    "pis": int(yr) if yr.isdigit() and yr not in ("8888", "9999") else None,
                    "prog": ["Low-Income Housing Tax Credit"]})
    return out


def public_housing(city):
    out = []
    for a in arcgis(PUBHOUSING, f"PARTICIPANT_CODE='{CITIES[city]['pha']}'"):
        units = num(a.get("TOTAL_DWELLING_UNITS")) or num(a.get("TOTAL_UNITS"))
        wait = num(a.get("MONTHS_WAITING"))
        out.append({"src": "public housing", "name": title(a.get("PROJECT_NAME")), "addr": a.get("STD_ADDR"),
                    "zip": a.get("STD_ZIP5"), "lat": a.get("LAT") or a.get("_lat"), "lng": a.get("LON") or a.get("_lng"),
                    "units": units, "li": units, "mgr": title(a.get("FORMAL_PARTICIPANT_NAME")),
                    "tel": phone(a.get("HA_PHN_NUM")), "vac": num(a.get("REGULAR_VACANT")),
                    "wait": wait if wait and wait < 600 else None,
                    "inc": "Public housing: rent is about 30% of household income",
                    "prog": ["Public housing"]})
    return out


def chicago_aro():
    out = []
    for a in arcgis(ARO):
        addr = a.get("Project_Ad") or a.get("ShortLabel") or a.get("StAddr")
        out.append({"src": "ARO", "name": title(a.get("Name")), "addr": addr, "zip": a.get("Zip_Code") or a.get("Postal"),
                    "lat": a.get("_lat"), "lng": a.get("_lng"), "li": num(a.get("ARO_Units")),
                    "mgr": title(a.get("ManagComp")), "tel": phone(a.get("ManagPhone")), "web": web(a.get("ManagWebsi")),
                    "nb": a.get("Community"),
                    "inc": "Affordable Requirements Ordinance: set-aside units, usually up to 60% of area median income",
                    "prog": ["Affordable Requirements Ordinance (ARO)"]})
    return out


def chicago_socrata():
    out = []
    for a in http_json(f"{CHI_SOCRATA}?$limit=5000"):
        try:
            lat, lng = float(a.get("latitude")), float(a.get("longitude"))
        except (TypeError, ValueError):
            continue
        ptype = (a.get("property_type") or "").strip()
        out.append({"src": "city", "name": title(a.get("property_name")), "addr": a.get("address"), "zip": a.get("zip_code"),
                    "lat": lat, "lng": lng, "units": num(a.get("units")), "li": num(a.get("units")),
                    "mgr": title(a.get("management_company")), "tel": phone(a.get("phone_number")),
                    "nb": a.get("community_area"),
                    "serves": ["seniors"] if "senior" in ptype.lower() else None,
                    "prog": ["City of Chicago affordable rental"]})
    return out


def miami_fhfc():
    out, leasing = [], []
    for a in arcgis(FHFC, "County='Miami-Dade'"):
        status = a.get("Status") or ""
        if status == "Pipeline":
            continue
        who = [w for w, f in (("seniors", "Elderly"), ("families", "Family"), ("people leaving homelessness", "Homeless"),
                              ("people with special needs", "Special_Ne")) if num(a.get(f))]
        row = {"src": "FHFC", "name": title(a.get("Property")), "addr": a.get("Address"), "zip": a.get("ZIP_Code"),
               "lat": a.get("Latitude") or a.get("_lat"), "lng": a.get("Longitude") or a.get("_lng"),
               "units": num(a.get("Total_Unit")), "li": num(a.get("Affordable")), "serves": who or None,
               "mgr": title(a.get("Owner")), "yr": num(a.get("Yr_Built")),
               "status": "Leasing now" if "Lease-Up" in status else None,
               "prog": ["Florida Housing Finance Corporation"]}
        out.append(row)
        if "Lease-Up" in status:
            leasing.append(row)
    return out, leasing


def miami_hudrd():
    out = []
    for a in arcgis(HUDRD, "county='Miami-Dade' AND occupancy_status='Ready for Occupancy'"):
        mix = {k: n for k, f in (("0", "number_of_0_br"), ("1", "number_of_1_br"), ("2", "number_of_2_br"),
                                 ("3", "number_of_3_br"), ("4", "number_of_4_or_more_br")) if (n := num(a.get(f)))}
        tp = (a.get("target_population") or "").lower()
        out.append({"src": "HUD", "name": title(a.get("development_name")), "addr": a.get("street_address"),
                    "zip": a.get("zip_code"), "lat": a.get("latitude") or a.get("_lat"), "lng": a.get("longitude") or a.get("_lng"),
                    "units": num(a.get("total_units")), "li": num(a.get("assisted_units")), "mix": mix or None,
                    "serves": ["seniors"] if "elder" in tp else ["families"] if "famil" in tp else None,
                    "yr": num(a.get("year_built_property_appraiser")),
                    "prog": [p.strip() for p in (a.get("housing_programs") or "").split(",") if p.strip()][:4] or ["HUD assisted"]})
    return out


def atlanta_tracker():
    out = []
    for a in arcgis(ATL_TRACKER):
        pt = (a.get("Project_Type") or "").lower()
        if "down" in pt or pt.strip() in ("dpa", "") or "owner-occupied" in pt:
            continue
        li = num(a.get("Number_of_Affordable_Units"))
        if not li or (num(a.get("Total_Units")) or 0) < 5:
            continue
        bands = [("30%", num(a.get("Units_0_30__AMI"))), ("50%", num(a.get("Units_31_50__AMI"))),
                 ("60%", num(a.get("Units_51_60__AMI"))), ("80%", num(a.get("Units_61_80__AMI"))),
                 ("120%", num(a.get("Units_81_120__AMI")))]
        iz = (a.get("IZ_or_PSO_Project") or "").strip()
        addr, z = split_city_zip(a.get("Project_Address_Display"))
        out.append({"src": "Atlanta", "name": title(a.get("Project_Name")), "addr": addr,
                    "zip": z, "lat": a.get("_lat"), "lng": a.get("_lng"), "units": num(a.get("Total_Units")), "li": li,
                    "ami": fmt_ami(bands),
                    "prog": ["City of Atlanta"] + (["Inclusionary zoning"] if "IZ" in iz.upper() else [])})
    return out


def atlanta_beltline():
    out = []
    for a in arcgis(BELTLINE, "project_status='Completed'"):
        bands = [(f"{p}%", num(a.get(f"units_{p}_ami"))) for p in (30, 40, 50, 60, 70, 80, 90, 100)]
        out.append({"src": "Beltline", "name": title(a.get("devname")), "addr": a.get("address"), "zip": a.get("zip"),
                    "lat": a.get("_lat"), "lng": a.get("_lng"), "units": num(a.get("total_units")),
                    "li": num(a.get("affordable_units")), "ami": fmt_ami(bands), "web": web(a.get("development_link")),
                    "nb": a.get("neighborhood"), "yr": num(a.get("year_closed")),
                    "prog": ["Atlanta Beltline"] + (["Inclusionary zoning"] if num(a.get("coa_iz_units")) else [])})
    return out


def philly_dhcd():
    out = []
    for a in arcgis(PHL_DHCD, "status='Complete'"):
        pt = a.get("project_type") or ""
        if "Rental" not in pt and "Special Needs" not in pt:
            continue
        out.append({"src": "DHCD", "name": title(a.get("project_name")), "addr": a.get("address"), "zip": None,
                    "lat": a.get("_lat"), "lng": a.get("_lng"), "units": num(a.get("total_units")),
                    "li": num(a.get("total_units")), "mgr": title(a.get("developer_name")),
                    "yr": num(a.get("fiscal_year_complete")),
                    "serves": ["people with special needs"] if "Special" in pt else None,
                    "prog": ["City of Philadelphia (DHCD)"]})
    return out


# ------------------------------------------------------------------ merging

RICH = ("name", "zip", "units", "li", "mix", "inc", "ami", "serves", "mgr", "tel", "web", "yr", "pis", "status",
        "vac", "wait", "nb", "np")


def merge(rows, bbox=None):
    """Fold rows that are the same building. Earlier rows (richer sources come
    first) win a field; programs are unioned."""
    out, by_key = [], {}
    for r in rows:
        try:
            lat, lng = float(r.get("lat")), float(r.get("lng"))
        except (TypeError, ValueError):
            continue
        if abs(lat) < 1:
            continue
        if bbox and not (bbox[0] <= lat <= bbox[1] and bbox[2] <= lng <= bbox[3]):
            continue
        r = dict(r, lat=lat, lng=lng)
        k = addr_key(r.get("addr"), r.get("zip"))
        hit = by_key.get(k) if k and k[2] else None
        if hit is None and k:
            # no ZIP on one side, or two spellings: same house number within ~40 m
            for o in out:
                ok = o.get("_key")
                if ok and ok[0] == k[0] and metres((lat, lng), (o["lat"], o["lng"])) < 40:
                    hit = o
                    break
        if hit is None and norm_name(r.get("name")):
            # one development listed at two street addresses by two sources
            nn = norm_name(r.get("name"))
            for o in out:
                if norm_name(o.get("name")) == nn and metres((lat, lng), (o["lat"], o["lng"])) < 150:
                    hit = o
                    break
        if hit is None:
            r["_key"] = k
            r["prog"] = list(dict.fromkeys(r.get("prog") or []))
            out.append(r)
            if k and k[2]:
                by_key[k] = r
            continue
        for f in RICH:
            if not hit.get(f) and r.get(f):
                hit[f] = r[f]
        # the larger unit counts are the building's, not one program's slice
        for f in ("units", "li"):
            if r.get(f) and (hit.get(f) or 0) < r[f]:
                hit[f] = r[f]
        hit["prog"] = list(dict.fromkeys((hit.get("prog") or []) + (r.get("prog") or [])))
    return out


def rows_for(city, merged):
    code = CITIES[city]["code"]
    slim, recs = [], {}
    for r in merged:
        addr = re.sub(r"\s+", " ", (r.get("addr") or "").strip()).upper()
        if not addr:
            continue
        bid = f"{code}-" + hashlib.sha1(f"{addr}|{r['lat']:.4f}|{r['lng']:.4f}".encode()).hexdigest()[:10]
        status = "LEASING NOW" if r.get("status") == "Leasing now" else "INCOME-RESTRICTED"
        row = {"bbl": bid, "b": code, "a": addr, "z": zip5(r.get("zip")), "lat": round(r["lat"], 6),
               "lng": round(r["lng"], 6), "s": [status], "yr": r.get("yr") or r.get("pis"), "u": r.get("units") or r.get("li"),
               "nb": title(r.get("nb")) or None}
        slim.append({k: v for k, v in row.items() if v is not None})
        rec = {"name": r.get("name") or None, "li": r.get("li"), "units_total": r.get("units"), "mix": r.get("mix"),
               "inc": r.get("inc"), "ami": r.get("ami"), "serves": r.get("serves"), "mgr": r.get("mgr") or None,
               "tel": r.get("tel"), "web": r.get("web"), "pis": r.get("pis"), "np": r.get("np"),
               "prog": r.get("prog") or None, "leasing": 1 if r.get("status") == "Leasing now" else None,
               "vacant": r.get("vac"), "wait_mo": r.get("wait")}
        recs[bid] = {k: v for k, v in rec.items() if v not in (None, [], "")}
    # The city's ZIP picker needs a ZIP; DHCD and the Atlanta tracker give
    # none. Borrow the nearest building's within 500 m (a block or two).
    zipped = [r for r in slim if r.get("z")]
    for r in slim:
        if r.get("z"):
            continue
        best = min(zipped, key=lambda o: metres((r["lat"], r["lng"]), (o["lat"], o["lng"])), default=None)
        if best and metres((r["lat"], r["lng"]), (best["lat"], best["lng"])) < 500:
            r["z"] = best["z"]
    # no duplicate ids even for two rows at one address
    seen, uniq = set(), []
    for r in slim:
        if r["bbl"] not in seen:
            seen.add(r["bbl"]); uniq.append(r)
    return uniq, recs


def build_city(city):
    c = CITIES[city]
    rows, leasing = [], []
    # Richest first: local sources know names, managers, AMI bands.
    if city == "chi":
        rows += chicago_aro() + chicago_socrata()
    elif city == "mia":
        fh, leasing = miami_fhfc()
        rows += fh + miami_hudrd()
    elif city == "atl":
        rows += atlanta_beltline() + atlanta_tracker()
    elif city == "phl":
        rows += philly_dhcd()
    rows += lihtc(city) + public_housing(city)
    merged = merge(rows, c.get("bbox"))
    slim, recs = rows_for(city, merged)
    return slim, recs, leasing, len(rows)


def write_gz(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", compresslevel=9) as f:
        json.dump(obj, f, separators=(",", ":"))
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE))
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = [s.strip() for s in a.only.split(",") if s.strip()]
    failed = 0
    for city in CITIES:
        if only and city not in only:
            continue
        try:
            slim, recs, leasing, raw = build_city(city)
        except Exception as e:  # one city's source down: keep its last files
            print(f"cities {city}: FAILED ({e}); keeping last files", file=sys.stderr)
            failed += 1
            continue
        if len(slim) < 50:
            print(f"cities {city}: only {len(slim)} buildings — keeping last files", file=sys.stderr)
            failed += 1
            continue
        out = Path(a.out) / city
        write_gz(out / "buildings.slim.json.gz", slim)
        write_gz(out / "buildings.hpd.json.gz", recs)
        (out / "leasing.json").write_text(json.dumps([
            {k: r.get(k) for k in ("name", "addr", "zip", "lat", "lng", "units", "li", "mgr", "serves")}
            for r in leasing], separators=(",", ":")))
        print(f"cities {city}: {len(slim)} buildings from {raw} source rows; "
              f"{sum(1 for r in recs.values() if r.get('tel'))} with a phone; {len(leasing)} leasing now")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
