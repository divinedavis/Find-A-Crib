#!/usr/bin/env python3
"""Tenant clinics and housing events for the Events tab -> events.json.

Owner, 2026-09-22: "is it possible to get information on events like these?"
(a flyer for an HPD / Mayor's Public Engagement Unit tenant clinic) and then
"build that and call it Events ... make sure events dont duplicate".

Source: the City's Event Calendar API (api.nyc.gov/calendar/search), the feed
behind nyc.gov's "Find Local Events" and the HPD and PEU events pages. It
needs a free subscription key from api-portal.nyc.gov, kept in growth.env as
NYC_API_KEY — never in the app or this public repo.

    python3 build_events.py                   # writes events.json next to this file
    python3 build_events.py --out /var/www/rent-map/events.json
    python3 build_events.py --dry-run         # print, write nothing

Rules it does not bend:
- Only housing events: tenant clinics and fairs, HPD In Your District, owner
  clinics, rent / eviction / NYCHA help. PEU's calendar also carries benefits
  tabling with nothing to do with housing; those are dropped.
- No duplicates. The same clinic is often listed by two agencies (HPD and PEU
  co-host), or twice by one. Events on the same day at the same address with
  similar titles, or at the same start time and address, are merged into one,
  keeping every host and link.
- A failed or empty fetch never overwrites a good file: the app keeps showing
  yesterday's list rather than "no events".
- Facts only (title, time, place, host) with a link back to the City's page.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.nyc.gov/calendar/search"
AGENCIES = {"hpd": "NYC Housing Preservation & Development",
            "mayorspeu": "Mayor's Public Engagement Unit"}
DAYS_AHEAD = 60
TZ = dt.timezone(dt.timedelta(hours=-4))   # display only; dates are stored as local ET strings

HOUSING = re.compile(
    r"\b(tenant|tenants|housing|hpd|rent|renters?|landlord|eviction|lease|nycha|"
    r"homeowner|property owner|owner clinic|in your district|resource fair|"
    r"affordable|lottery|repairs?|heat|hot water)\b", re.I)

BOROUGHS = {"manhattan": "Manhattan", "brooklyn": "Brooklyn", "queens": "Queens",
            "bronx": "Bronx", "the bronx": "Bronx", "staten island": "Staten Island"}
# The feed's own borough codes (2026-09-22 payload): ["Bk"], ["Qn"], ["Bx"],
# ["Bk","Other"]. "Other" means online or unstated, not a place.
BORO_CODE = {"mn": "Manhattan", "m": "Manhattan", "bk": "Brooklyn", "bx": "Bronx",
             "qn": "Queens", "q": "Queens", "si": "Staten Island"}
# Addresses that are not addresses. HPD writes these on most outreach events,
# so they must never make two different events look like the same place.
NON_ADDRESS = re.compile(r"^\s*(zoom|online|virtual|webinar|tbd|to be (determined|announced)|n/?a|"
                         r"please see the flyer|see the flyer|see flyer)\b", re.I)


# ------------------------------------------------------------------ fetching

def fetch(agency, key, start, end, page):
    q = urllib.parse.urlencode({
        "agency": agency, "sort": "DATE", "pageNumber": page,
        "startDate": start.strftime("%m/%d/%Y 12:00 AM"),
        "endDate": end.strftime("%m/%d/%Y 11:59 PM")})
    req = urllib.request.Request(f"{API}?{q}", headers={
        "Ocp-Apim-Subscription-Key": key, "Accept": "application/json",
        "User-Agent": "findacrib.com events (+https://findacrib.com)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def items_of(payload):
    """The list of events in a response, whatever the wrapper is called."""
    if isinstance(payload, list):
        return payload
    for k in ("items", "events", "results", "data", "Items", "Events"):
        v = payload.get(k) if isinstance(payload, dict) else None
        if isinstance(v, list):
            return v
    return []


def pull(key, today):
    """Every page for each agency. The response carries pagination.numPages."""
    raw = []
    end = today + dt.timedelta(days=DAYS_AHEAD)
    for agency in AGENCIES:
        page, pages = 1, 1
        while page <= pages and page <= 40:
            payload = fetch(agency, key, today, end, page)
            got = items_of(payload)
            if not got:
                break
            pages = int((payload.get("pagination") or {}).get("numPages") or 1) if isinstance(payload, dict) else 1
            for it in got:
                it["_agency"] = agency
            raw += got
            page += 1
    return raw


# ------------------------------------------------------------- normalising

def pick(d, *names):
    """First non-empty value among several possible field names (case-insensitive)."""
    low = {k.lower(): v for k, v in d.items()} if isinstance(d, dict) else {}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, "", [], {}):
            return v
    return None


def parse_when(v):
    """'09/16/2026 10:00 AM', ISO strings or epoch ms -> naive local datetime."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v, TZ).replace(tzinfo=None)
    s = str(v).strip()
    for f in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, f)
        except ValueError:
            continue
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.astimezone(TZ).replace(tzinfo=None) if d.tzinfo else d
    except ValueError:
        return None


def text(v):
    if isinstance(v, list):
        v = ", ".join(str(x.get("name") if isinstance(x, dict) else x) for x in v)
    if isinstance(v, dict):
        v = v.get("name") or v.get("value") or ""
    s = re.sub(r"<[^>]+>", " ", str(v or ""))
    return re.sub(r"\s+", " ", s).strip()


def borough_of(*vals):
    for v in vals:
        t = text(v).lower()
        for k, name in BOROUGHS.items():
            if re.search(r"\b" + k + r"\b", t):
                return name
    return None


def normalise(it):
    title = text(pick(it, "name", "title", "eventName", "event_name"))
    start = parse_when(pick(it, "startDate", "start", "dateTimeStart", "start_date", "startDateTime"))
    end = parse_when(pick(it, "endDate", "end", "dateTimeEnd", "end_date", "endDateTime"))
    loc = pick(it, "address", "location", "venue", "street", "streetAddress")
    if isinstance(loc, dict):
        loc = ", ".join(text(loc.get(k)) for k in ("name", "street", "address", "city", "zip") if loc.get(k))
    address = text(loc)
    online = bool(NON_ADDRESS.match(address))
    if online:
        address = "Online" if re.match(r"^\s*(zoom|online|virtual|webinar)", address, re.I) else ""
    else:
        for part in (text(pick(it, "city")), text(pick(it, "state")), text(pick(it, "zip", "zipCode", "postalCode"))):
            if part and part.lower() not in address.lower():
                address = f"{address}, {part}" if part != text(pick(it, "zip", "zipCode", "postalCode")) else f"{address} {part}"
        address = re.sub(r"\s+,", ",", address).strip(" ,")
    cats = pick(it, "categories", "category", "eventCategories", "tags") or []
    cats = [text(c) for c in (cats if isinstance(cats, list) else str(cats).split(","))]
    cats = [c for c in cats if c]
    desc = text(pick(it, "shortDesc", "description", "desc", "summary"))[:600]
    url = text(pick(it, "permalink", "url", "link", "eventUrl", "website"))
    if url and url.startswith("/"):
        url = "https://www.nyc.gov" + url
    url = url.replace("http://", "https://").replace("https://www1.nyc.gov", "https://www.nyc.gov")
    if not url.startswith("https://"):
        url = ""      # the app opens this; nothing but https leaves the feed
    lat = pick(it, "lat", "latitude")
    lng = pick(it, "lng", "lon", "longitude")
    boros = pick(it, "boroughs", "borough", "boro") or []
    boros = [BORO_CODE.get(text(b).lower().strip(), None) for b in (boros if isinstance(boros, list) else [boros])]
    boro = next((b for b in boros if b), None)
    img = text(pick(it, "imageUrl", "image"))
    return {
        "title": title, "start": start, "end": end, "address": address,
        "online": online, "image": img if img.startswith("https://") else "",
        "borough": boro or borough_of(address, desc),
        "categories": cats, "description": desc, "url": url,
        "lat": float(lat) if lat not in (None, "") else None,
        "lng": float(lng) if lng not in (None, "") else None,
        "hosts": [text(pick(it, "agencyName")) or AGENCIES.get(it.get("_agency"), it.get("_agency") or "NYC")],
        "canceled": bool(pick(it, "canceled") or False),
        "all_day": bool(start and start.hour == 0 and start.minute == 0 and (not end or end.hour in (0, 23))),
    }


def is_housing(e):
    blob = " ".join([e["title"], e["description"], " ".join(e["categories"])])
    return bool(HOUSING.search(blob))


# -------------------------------------------------------------- dedupe

STOP = {"the", "a", "an", "at", "of", "and", "for", "in", "on", "to", "with", "nyc", "event", "clinic"}


def tokens(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1}


def norm_address(a):
    """'' for anything that is not a real address — "Zoom", "Please see the
    Flyer". Two events sharing a placeholder are NOT at the same place."""
    if not a or NON_ADDRESS.match(a) or a.strip().lower() == "online":
        return ""
    a = a.lower()
    a = re.sub(r"\b(avenue|ave\.?)\b", "ave", a)
    a = re.sub(r"\b(street|st\.?)\b", "st", a)
    a = re.sub(r"\b(road|rd\.?)\b", "rd", a)
    a = re.sub(r"\b(boulevard|blvd\.?)\b", "blvd", a)
    a = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", a)
    a = re.sub(r"[^a-z0-9 ]", " ", a)
    m = re.match(r"\s*([0-9-]+ [a-z0-9 ]+?)\s+(ave|st|rd|blvd|pl|place|way|pkwy|parkway|plaza)\b", a)
    return re.sub(r"\s+", " ", (m.group(0) if m else a)).strip()


def same_event(a, b):
    if not a["start"] or not b["start"] or a["start"].date() != b["start"].date():
        return False
    addr_a, addr_b = norm_address(a["address"]), norm_address(b["address"])
    same_place = bool(addr_a) and addr_a == addr_b
    if a["title"].strip().lower() == b["title"].strip().lower():
        # Same name, same day, same place (or neither states one): listed twice.
        # "Tenant Resource Fair" at two addresses is two fairs.
        return same_place or (not addr_a and not addr_b)
    # Different names only merge on evidence of the same place. Without a real
    # address there is none: HPD writes "Please see the Flyer" on most outreach
    # events, and council districts 38 and 40 on the same day are two events.
    if not same_place:
        return False
    ta, tb = tokens(a["title"]), tokens(b["title"])
    similar = bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.5
    return similar or a["start"] == b["start"]


def merge(a, b):
    out = dict(a)
    out["hosts"] = sorted(set(a["hosts"]) | set(b["hosts"]))
    out["categories"] = sorted(set(a["categories"]) | set(b["categories"]))
    if len(b["description"]) > len(a["description"]):
        out["description"] = b["description"]
    if len(b["title"]) > len(a["title"]):
        out["title"] = b["title"]
    out["start"] = min(a["start"], b["start"])
    ends = [x for x in (a["end"], b["end"]) if x]
    out["end"] = max(ends) if ends else None
    for k in ("url", "address", "borough", "lat", "lng", "image"):
        out[k] = a[k] or b[k]
    out["links"] = sorted({u for u in (a.get("links") or [a["url"]]) + (b.get("links") or [b["url"]]) if u})
    return out


def dedupe(events):
    out = []
    for e in sorted(events, key=lambda x: (x["start"] or dt.datetime.max, x["title"])):
        for i, kept in enumerate(out):
            if same_event(kept, e):
                out[i] = merge(kept, e)
                break
        else:
            out.append(dict(e, links=[e["url"]] if e["url"] else []))
    return out


def event_id(e):
    basis = f'{e["start"]:%Y-%m-%d}|{norm_address(e["address"])}|{" ".join(sorted(tokens(e["title"])))}'
    return hashlib.sha1(basis.encode()).hexdigest()[:12]


def serialise(e):
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:00") if d else None
    return {"id": event_id(e), "title": e["title"], "start": fmt(e["start"]), "end": fmt(e["end"]),
            "all_day": e["all_day"], "address": e["address"], "online": e.get("online", False),
            "image": e.get("image", ""), "borough": e["borough"],
            "lat": e["lat"], "lng": e["lng"], "hosts": e["hosts"], "categories": e["categories"],
            "description": e["description"], "url": e["url"], "links": e.get("links") or []}


def build(raw, today):
    evs = [normalise(it) for it in raw]
    evs = [e for e in evs if e["title"] and e["start"] and e["start"].date() >= today
           and not e.get("canceled") and is_housing(e)]
    return [serialise(e) for e in dedupe(evs)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "events.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    key = os.environ.get("NYC_API_KEY", "").strip()
    if not key:
        sys.exit("NYC_API_KEY is not set (free key from api-portal.nyc.gov, kept in growth.env)")
    today = dt.datetime.now(TZ).date()
    try:
        raw = pull(key, today)
    except Exception as e:
        sys.exit(f"fetch failed, keeping the existing file: {e}")
    events = build(raw, today)
    payload = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "source": "NYC Event Calendar (api.nyc.gov), HPD and the Mayor's Public Engagement Unit",
               "fetched": len(raw), "events": events}
    if a.dry_run:
        print(json.dumps(payload, indent=1)[:4000]); print(f"\n{len(raw)} fetched -> {len(events)} events"); return
    if not events:
        sys.exit(f"{len(raw)} fetched but no housing events kept; not overwriting {a.out}")
    tmp = a.out + ".tmp"
    Path(tmp).write_text(json.dumps(payload, separators=(",", ":")))
    os.replace(tmp, a.out)
    print(f"wrote {a.out}: {len(raw)} fetched -> {len(events)} events")


if __name__ == "__main__":
    main()
