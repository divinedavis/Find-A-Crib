"""One address format on every re-rental card (owner, 2026-10-22: "all cards
should follow the same format … the 445 grand ave card is a good example",
and "55 willoughby st is a good example as well").

    kicker  "Arris Grand · Brooklyn"     title (a real name, or the unit) · borough
    address "445 Grand Avenue, Brooklyn, NY 11238"

Agents' pages give everything from that to "Greenpoint Central Apartments -
65 Dupont Street Units Still Available" and "183 Covert Street Unit 2F 1026"
(iAfford's MMYY posting code). tidy() splits the name off the street, moves
the unit into the title when there is no name, drops the posting codes and
"Multiple Units" tails, and rebuilds the line from street, borough and ZIP.
A missing ZIP comes from NYC Planning Labs' GeoSearch (free, no key; cached).
The agent's own text stays in address_src, which flyer_reader matches
against the agent's board.
"""
import json
import os
import re
import urllib.parse
import urllib.request

ZIP_CACHE = os.path.expanduser("~/.cache/findacrib/rerental_zip.json")
PLACES = ("Flushing", "Dumbo", "Brooklyn", "Bronx", "Queens", "Manhattan", "Long Island City", "Far Rockaway",
          "East New York", "Brownsville", "Concourse", "Jamaica", "Astoria", "Harlem")
BOROS = ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")
# Statuses and headings agents put where a building name would go.
NOT_A_NAME = re.compile(r"^(unit on hold|open market|upcoming project|now leasing|available|re-?rental)s?$", re.I)
SUFFIX = r"(?:Street|St|Avenue|Ave|Road|Rd|Place|Pl|Boulevard|Blvd|Drive|Dr|Parkway|Pkwy|Court|Ct|Terrace|Lane|Ln|Concourse|East|West|Way)\.?"
# "<name> - 65 Dupont Street …": a name, a dash, then a street number.
NAME_DASH = re.compile(r"^(?P<name>[A-Za-z][^0-9]{3,60}?)\s+[-–]\s+(?P<rest>\d.*)$")
POSTING_CODE = re.compile(r"(?:\s+[-–])?\s+(?:0[1-9]|1[0-2])2[5-9]\b")          # "1026", "- 0126"
TAILS = re.compile(r"\s*(?:[-–]\s*)?(?:Units?\s+Still\s+Available|Multiple\s+Units|apartments)\b.*$", re.I)
UNIT = re.compile(r"[\s.,]*(?:Apartment\s*[–-]\s*)?\b(?P<unit>(?:Unit|Apt\.?)\s+[A-Z0-9-]+)\b", re.I)
# A city / state / ZIP tail the agent already wrote: ", Brooklyn, NY 11238",
# " Flushing, NY 11368", ", Concourse, Bronx, 10452", ", NY 11208".
CITY_TAIL = re.compile(r"(?:,?\s+(?:[A-Z][A-Za-z ]+,\s*)*(?:NY|New York)\b,?\s*(?:\d{5})?|,\s*(?:[A-Z][A-Za-z ]+,\s*)*\d{5})\s*$")


def _cache():
    try:
        return json.load(open(ZIP_CACHE))
    except Exception:
        return {}


ABBR = {"ave": "avenue", "av": "avenue", "st": "street", "rd": "road", "pl": "place", "blvd": "boulevard",
        "dr": "drive", "pkwy": "parkway", "ct": "court", "ln": "lane", "e": "east", "w": "west",
        "n": "north", "s": "south"}


def street_key(text):
    """"2710 Decatur Ave." and "2710 DECATUR AVENUE, Bronx" -> "2710 decatur avenue";
    "148-37 88th Ave" and "148-37 88 AVENUE" agree too."""
    words = re.sub(r"[^a-z0-9 -]", " ", text.lower().split(",")[0]).split()[:3]
    return " ".join(ABBR.get(w, re.sub(r"^(\d+)(?:st|nd|rd|th)$", r"\1", w)) for w in words)


def lookup(street, borough, cache):
    """(zip, borough) from GeoSearch, or (None, None)."""
    q = f"{street}, {borough or 'New York'}, NY"
    if q in cache:
        return tuple(cache[q])
    try:
        url = "https://geosearch.planninglabs.nyc/v2/search?" + urllib.parse.urlencode({"text": q, "size": 5})
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "FindACrib/1.0"}), timeout=15) as r:
            feats = json.load(r).get("features") or []
        # Only a hit on this house number and street: a fuzzy match to a
        # neighborhood or another block would print another building's ZIP.
        # The agent's borough breaks a tie ("923 Broadway" is in three).
        want = street_key(street)
        hits = [f["properties"] for f in feats if street_key(f["properties"].get("label") or "") == want]
        p = next((h for h in hits if h.get("borough") == borough), hits[0] if hits else {})
        res = (p.get("postalcode"), p.get("borough"))
    except Exception:
        return (None, None)                       # not cached: try again next run
    cache[q] = list(res)
    return res


def split(address):
    """(name, street, unit, zip) from an agent's address line."""
    s = re.sub(r"\s+", " ", address or "").strip()
    name = None
    m = NAME_DASH.match(s)
    if m:
        name, s = m.group("name").strip(), m.group("rest")
    s = POSTING_CODE.sub("", s)
    s = TAILS.sub("", s)
    unit = None
    u = UNIT.search(s)
    if u:
        unit = re.sub(r"^apt\.?", "Apt", u.group("unit"), flags=re.I)
        unit = "Unit " + unit.split(None, 1)[1] if unit.lower().startswith("unit") else unit
        s = (s[:u.start()] + s[u.end():]).strip()
    z = re.search(r"\b(\d{5})\s*$", s)
    zipcode = z.group(1) if z else None
    # Peel the city / state / ZIP the agent wrote off the end, one piece at a
    # time: "…, Brooklyn, NY 11238", "…, Concourse, Bronx, 10452",
    # "… 39th Avenue Flushing, NY 11368", "…, East New York, NY 11239".
    s = re.sub(r",?\s*\d{5}$", "", s).strip(" ,")
    s = re.sub(r",?\s*\b(?:NY|New York)$", "", s).strip(" ,")
    for _ in range(3):
        parts = s.rsplit(",", 1)
        # A tail with no number is a place, unless it is the street's own end
        # ("…, 516 Schroeders Ave"): "Concourse" after "1164 River Avenue" goes.
        if len(parts) == 2 and not re.search(r"\d", parts[1]) and (
                not re.search(rf"\b{SUFFIX}$", parts[1].strip(), re.I) or re.search(rf"\b{SUFFIX}$", parts[0].strip(), re.I)):
            s = parts[0].strip(" ,")
    s = re.sub(rf"(\b{SUFFIX})\s+(?:{'|'.join(PLACES)})$", r"\1", s, flags=re.I)
    s = re.sub(rf"\b({SUFFIX})(?=\s|$)", lambda m: m.group(1)[0].upper() + m.group(1)[1:].lower(), s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,.-–")
    return name, s, unit, zipcode


def tidy(records, lookup_zip=lookup):
    cache = _cache()
    for r in records:
        src = r.get("address_src") or r.get("address") or ""
        name, street, unit, z = split(src)
        if not street or not re.match(r"^\d", street):
            continue                              # not an address we can read; leave it as written
        zipcode = r.get("zip") or z
        boro = r.get("borough")
        # The city's own answer wins over the agent's: Taxace lists 2710
        # Decatur Ave as Brooklyn; it is in the Bronx (10458).
        gz, gb = lookup_zip(street, boro, cache)
        zipcode = zipcode or gz
        boro = gb if gb in BOROS else boro
        if not boro and not zipcode:
            continue                              # can't place it (55 South Essex Ave is in New Jersey)
        title = (r.get("title") or "").strip()
        if not title or NOT_A_NAME.match(title):
            title = name or unit or ""
        elif unit and unit.lower() not in title.lower():
            title = f"{title} · {unit}"
        r["address_src"] = src
        r["title"] = title
        r["borough"] = boro
        r["zip"] = zipcode
        r["address"] = ", ".join(x for x in (street, boro, ("NY " + zipcode) if zipcode else "NY") if x)
    try:
        os.makedirs(os.path.dirname(ZIP_CACHE), exist_ok=True)
        json.dump(cache, open(ZIP_CACHE, "w"))
    except Exception:
        pass
    return records
