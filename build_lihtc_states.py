#!/usr/bin/env python3
"""Build states/<st>/ — every state's income-restricted buildings, from HUD.

Owner, 2026-09-24: "lets add every state/city that has income restricted and
lottery housing", then chose "State picker + map": every state in the city
picker, with a map of its income-restricted buildings.

WHY THIS SOURCE
---------------
Rent stabilization exists in a handful of places and publishes building lists
in fewer (see build_dc.py, build_westchester.py). Income-restricted housing is
everywhere, and one register covers all of it that a building map can: HUD's
Low-Income Housing Tax Credit database, the program behind most US affordable
rental built since 1987. HUD publishes it as a public ArcGIS feature service:

    https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/LIHTC/FeatureServer/0

50,566 projects in 56 states and territories (2026-09-24), each with an
address, a point, total and low-income units, units by bedroom count, the
income ceiling and — on some — the owner's contact and phone. The fuller
1987-2024 file on huduser.gov sits behind a bot challenge; this layer runs to
about 2021.

WHAT IT CAN AND CANNOT SAY
--------------------------
- A tax-credit building must keep its low-income units affordable for a
  compliance period plus an extended-use period: 15 years for projects before
  1990, at least 30 after. Projects placed in service before 1990 are dropped —
  most are past their 15 years. The rest are labelled "likely" income-
  restricted, because some leave early (the qualified-contract exit) and HUD's
  file does not say which.
- It is a register of buildings, not of openings. Whether a unit is free is a
  question for the building's manager, which is why the phone is kept.

Output, per state (lower-case postal code):
    states/<st>/buildings.slim.json.gz   the map rows (Building.swift keys)
    states/<st>/buildings.hpd.json.gz    the per-building record (BuildingRecord)
and states/index.json with each state's count, centre and span.

Usage:  python3 build_lihtc_states.py [--out states] [--only NJ,NY]
"""
import argparse
import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAYER = "https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/LIHTC/FeatureServer/0"
UA = "findacrib.com building map (+https://findacrib.com)"
FIELDS = ("HUD_ID,PROJECT,PROJ_ADD,PROJ_CTY,PROJ_ST,PROJ_ZIP,COMPANY,CONTACT,CO_TEL,N_UNITS,LI_UNITS,"
          "N_0BR,N_1BR,N_2BR,N_3BR,N_4BR,INC_CEIL,YR_PIS,TRGT_FAM,TRGT_ELD,TRGT_DIS,TRGT_HML,NON_PROF")
# The public layer above ships with COMPANY/CONTACT/CO_TEL emptied. HUD's
# older AFFH copy (projects to 2015) still carries them; merged by HUD_ID.
CONTACTS = "https://egis.hud.gov/arcgis/rest/services/affht/AffhtMapService/MapServer/30"
PAGE = 2000
FIRST_YEAR = 1990          # 30-year extended use began with the 1989 act
UNKNOWN_YEARS = {"8888", "9999"}
INCOME = {"1": "50% of area median income", "2": "60% of area median income",
          "3": "Income averaging (up to 80% of area median)"}
STATUS = "LIKELY INCOME-RESTRICTED (TAX CREDIT)"

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico",
}


def query(params, tries=4, layer=LAYER):
    q = urllib.parse.urlencode({**params, "f": "json"})
    for i in range(tries):
        try:
            req = urllib.request.Request(f"{layer}/query?{q}", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:  # transient ArcGIS hiccups: back off and retry
            if i == tries - 1:
                raise
            print(f"lihtc: retry after {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))


def pull(where):
    rows, off = [], 0
    while True:
        d = query({"where": where, "outFields": FIELDS, "outSR": 4326, "orderByFields": "OBJECTID",
                   "resultOffset": off, "resultRecordCount": PAGE})
        got = d.get("features") or []
        rows += got
        if len(got) < PAGE and not d.get("exceededTransferLimit"):
            return rows
        off += len(got)
        time.sleep(0.3)


def hud_key(h):
    """The two layers write one project's id differently: the older one pads
    the sequence to 3 digits (NJA2012412), the newer to 4 (NJA20120412)."""
    m = re.match(r"^([A-Z]{3})([0-9X]{4})(.*)$", h or "")
    return (m.group(1), m.group(2), m.group(3).lstrip("0")) if m else h


def words(*parts):
    return set(re.findall(r"[A-Z0-9]{3,}", " ".join(p or "" for p in parts).upper()))


def contacts(st):
    """{hud_key: (company, contact, phone, words)} from the older layer; {} if it
    fails — a missing phone is not a reason to drop a state."""
    out, off = {}, 0
    try:
        while True:
            d = query({"where": f"PROJ_ST='{st}'", "outFields": "HUD_ID,COMPANY,CONTACT,CO_TEL,PROJECT,PROJ_ADD",
                       "returnGeometry": "false", "orderByFields": "OBJECTID",
                       "resultOffset": off, "resultRecordCount": PAGE}, layer=CONTACTS)
            got = d.get("features") or []
            for f in got:
                a = f["attributes"]
                if a.get("HUD_ID"):
                    out[hud_key(a["HUD_ID"])] = (a.get("COMPANY"), a.get("CONTACT"), a.get("CO_TEL"),
                                                 words(a.get("PROJECT"), a.get("PROJ_ADD")))
            if len(got) < PAGE and not d.get("exceededTransferLimit"):
                return out
            off += len(got)
    except Exception as e:
        print(f"lihtc {st}: contacts unavailable ({e})", file=sys.stderr)
        return out


def title(s):
    """'NEWARK CITY' -> 'Newark City'; keeps 'McX' and ordinals readable enough."""
    s = re.sub(r"\s+", " ", (s or "").strip())
    return " ".join(w if re.match(r"^\d", w) else w.capitalize() for w in s.lower().split(" ")) if s else ""


def clean_name(s):
    # Several states prefix the allocation number: "LITC#0755 FRANKLIN SENIOR HOUSING".
    s = re.sub(r"^(LITC|LIHTC)\s*#?\s*\d+\s*", "", (s or "").strip(), flags=re.I)
    return title(s)


def zip5(z):
    z = re.sub(r"\D", "", z or "")
    return z.zfill(5)[:5] if z else None


def phone(p):
    d = re.sub(r"\D", "", p or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return f"{d[:3]}-{d[3:6]}-{d[6:]}" if len(d) == 10 else None


def num(v):
    try:
        n = int(v)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def rows_for(features, contact=None):
    contact = contact or {}
    slim, recs, skipped = [], {}, {"old": 0, "nopoint": 0, "noaddr": 0}
    for f in features:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        yr = str(a.get("YR_PIS") or "").strip()
        if yr and yr not in UNKNOWN_YEARS and yr.isdigit() and int(yr) < FIRST_YEAR:
            skipped["old"] += 1; continue
        lat, lng = g.get("y"), g.get("x")
        if not lat or not lng or abs(lat) < 1:
            skipped["nopoint"] += 1; continue
        addr = re.sub(r"\s+", " ", (a.get("PROJ_ADD") or "").strip()).upper()
        if not addr:
            skipped["noaddr"] += 1; continue
        bid = f"LIHTC-{a.get('HUD_ID')}"
        units, li = num(a.get("N_UNITS")), num(a.get("LI_UNITS"))
        row = {"bbl": bid, "b": a.get("PROJ_ST"), "a": addr, "z": zip5(a.get("PROJ_ZIP")),
               "lat": round(lat, 6), "lng": round(lng, 6), "s": [STATUS],
               "nb": title(a.get("PROJ_CTY")) or None}
        if yr.isdigit() and yr not in UNKNOWN_YEARS:
            row["yr"] = int(yr)
        if units or li:
            row["u"] = units or li
        slim.append({k: v for k, v in row.items() if v is not None})
        mix = {k: n for k, fld in (("0", "N_0BR"), ("1", "N_1BR"), ("2", "N_2BR"), ("3", "N_3BR"), ("4", "N_4BR"))
               if (n := num(a.get(fld)))}
        who = [w for w, fld in (("families", "TRGT_FAM"), ("seniors", "TRGT_ELD"),
                                ("people with disabilities", "TRGT_DIS"), ("people leaving homelessness", "TRGT_HML"))
               if str(a.get(fld) or "") == "1"]
        # Only when the name or address agrees too: on NJ, 489 of 490 id
        # matches did, and the odd one was a different development.
        c = contact.get(hud_key(a.get("HUD_ID")))
        co = person = tel = None
        if c and c[3] & words(a.get("PROJECT"), a.get("PROJ_ADD")):
            co, person, tel = c[:3]
        rec = {"name": clean_name(a.get("PROJECT")) or None, "li": li, "units_total": units,
               "mix": mix or None, "inc": INCOME.get(str(a.get("INC_CEIL") or "")),
               "serves": who or None, "mgr": title(co) or None,
               "tel": phone(tel),
               "pis": row.get("yr"), "np": 1 if str(a.get("NON_PROF") or "") == "1" else None}
        recs[bid] = {k: v for k, v in rec.items() if v is not None}
    return slim, recs, skipped


def frame(slim):
    """Centre and span that hold the middle 96% of the state's buildings, so
    one mis-geocoded row can't zoom the opening map out to a continent."""
    la = sorted(r["lat"] for r in slim); ln = sorted(r["lng"] for r in slim)
    cut = lambda v, p: v[min(len(v) - 1, max(0, int(p * (len(v) - 1))))]
    lo_la, hi_la, lo_ln, hi_ln = cut(la, .02), cut(la, .98), cut(ln, .02), cut(ln, .98)
    span = max(hi_la - lo_la, (hi_ln - lo_ln) * 0.75, 0.2) * 1.15
    return round((lo_la + hi_la) / 2, 4), round((lo_ln + hi_ln) / 2, 4), round(span, 3)


def write_gz(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", compresslevel=9) as f:
        json.dump(obj, f, separators=(",", ":"))
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "states"))
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    out = Path(a.out)
    only = [s.strip().upper() for s in a.only.split(",") if s.strip()]
    index_path = out / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"states": {}}
    total = 0
    for st, name in STATES.items():
        if only and st not in only:
            continue
        feats = pull(f"PROJ_ST='{st}'")
        slim, recs, skipped = rows_for(feats, contacts(st))
        if not slim:
            print(f"lihtc {st}: nothing usable ({len(feats)} raw), keeping last files", file=sys.stderr)
            continue
        write_gz(out / st.lower() / "buildings.slim.json.gz", slim)
        write_gz(out / st.lower() / "buildings.hpd.json.gz", recs)
        lat, lng, span = frame(slim)
        index["states"][st] = {"name": name, "n": len(slim),
                               "li": sum(r.get("li") or 0 for r in recs.values()),
                               "lat": lat, "lng": lng, "span": span}
        total += len(slim)
        print(f"lihtc {st}: {len(slim)} buildings (raw {len(feats)}, dropped {skipped})")
    index["source"] = "HUD Low-Income Housing Tax Credit database (ArcGIS layer)"
    index["source_url"] = LAYER
    index["generated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=1, sort_keys=True))
    print(f"lihtc: {total} buildings written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
