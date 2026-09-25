#!/usr/bin/env python3
"""Affordable-housing openings outside New York -> openings.json.

Owner, 2026-09-24: "lets add every state/city that has income restricted and
lottery housing". The state maps (build_lihtc_states.py) say WHERE the
income-restricted buildings are; this says which ones are taking applications
now — lotteries, open waitlists and first-come units — from every city or
region that publishes its listings as open data.

Sources, each the public JSON behind the agency's own listings site, tested
2026-09-24 (no key, no login; none of the hosts' robots.txt disallows them):

  SF DAHLIA         housing.sfgov.org/api/v1/listings            SF Mayor's Office of Housing
  Boston Metrolist  boston.gov/metrolist/api/v1/developments     City of Boston — OFF: WAF blocks servers
  Access Housing LA access.housing.lacity.gov/api/adapter/...    LA Housing Department (Bloom)
  Doorway           housingbayarea.mtc.ca.gov/api/adapter/...    Bay Area Housing Finance Authority (Bloom)
  Florida Housing   mia/leasing.json (build_affordable_cities.py) Miami-Dade buildings in lease-up

Everything else surveyed that day is a login, a vendor whose terms forbid
copying (Emphasys' myhousingsearch.com, which runs ~25 states' registries), or
has nothing open. See the memory note reference_us_affordable_openings_sources.

Each opening keeps only facts the source publishes — name, place, how you get
in (lottery / waitlist / first come), rent or buy, the deadline, sizes, rent
and income ranges — and links back to the source's own page to apply. A source
that fails keeps its openings from the last good file, so one site being down
never empties another city's list.

    python3 build_openings.py [--out openings.json] [--dry-run]
"""
import argparse
import datetime as dt
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# A full browser string, still naming us: Boston's WAF answers a short one
# with an empty page and LA's host 403s a "compatible; bot" one.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
      "Version/18.0 Safari/605.1.15 findacrib.com")
TODAY = dt.date.today().isoformat()


def get(url, body=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers={
        "User-Agent": UA, "Accept": "application/json",
        **({"Content-Type": "application/json"} if data else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def day(s):
    """'2026-10-16T00:00:00.000+0000' / '2026-11-20' -> '2026-10-16'."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s or "")
    return m.group(1) if m else None


def money(s):
    """'$1,900' / 1900 / 't.n/a' -> 1900 or None."""
    if isinstance(s, (int, float)):
        return int(s) if s > 0 else None
    d = re.sub(r"[^\d.]", "", s or "")
    try:
        n = int(float(d))
        return n if n > 0 else None
    except ValueError:
        return None


BED_WORDS = {"studio": "Studio", "sro": "Studio", "onebdrm": "1-bed", "twobdrm": "2-bed", "threebdrm": "3-bed",
             "fourbdrm": "4-bed", "fivebdrm": "5-bed"}


def bed_label(n):
    return "Studio" if n == 0 else f"{n}-bed"


def span(values):
    v = [x for x in values if x]
    return (min(v), max(v)) if v else (None, None)


def sort_beds(beds):
    order = lambda b: -1 if b == "Studio" else int(re.match(r"\d+", b).group()) if re.match(r"\d+", b) else 99
    return sorted(set(beds), key=order)


def clean(o):
    return {k: v for k, v in o.items() if v not in (None, [], "")}


# ------------------------------------------------------------------ sources

def dahlia():
    out = []
    for x in get("https://housing.sfgov.org/api/v1/listings")["listings"]:
        if x.get("Status") != "Active":
            continue
        tenure = "buy" if "sale" in (x.get("Tenure") or "").lower() else "rent"
        lt = (x.get("Listing_Type") or "").lower()
        kind = "waitlist" if "waitlist" in lt else "first_come" if "first come" in lt else "lottery"
        units = (x.get("unitSummaries") or {}).get("general") or []
        units += (x.get("unitSummaries") or {}).get("reserved") or []
        beds = []
        for u in units:
            t = (u.get("unitType") or "").lower()
            if "studio" in t or "sro" in t:
                beds.append("Studio")
            elif m := re.match(r"(\d+)", t):
                beds.append(bed_label(int(m.group(1))))
        rent = span([u.get("minMonthlyRent") for u in units] + [u.get("maxMonthlyRent") for u in units])
        ami = span([u.get("maxQualifyingAMI") for u in units])[1]
        out.append(clean({
            "id": f"sf-{x['listingID']}", "src": "SF DAHLIA", "state": "CA",
            "city": x.get("Building_City") or "San Francisco", "name": x.get("Name"),
            "address": x.get("Building_Street_Address"), "zip": x.get("Building_Zip_Code"),
            "kind": kind, "tenure": tenure, "closes": day(x.get("Application_Due_Date")),
            "units": x.get("Units_Available") or None, "beds": sort_beds(beds),
            "rent_low": money(rent[0]), "rent_high": money(rent[1]),
            # DAHLIA's income fields mix monthly and yearly figures by listing
            # type, so only the AMI ceiling is kept — it is unambiguous.
            "ami": int(ami) if ami else None,
            "image": x.get("imageURL") or next((i.get("displayImageURL") or i.get("Image_URL")
                                                for i in sorted(x.get("Listing_Images") or [], key=lambda i: i.get("Display_Order") or 0)
                                                if (i.get("displayImageURL") or i.get("Image_URL") or "").startswith("http")), None),
            "href": f"https://housing.sfgov.org/listings/{x['listingID']}"}))
    return out


def metrolist():
    out = []
    for x in get("https://www.boston.gov/metrolist/api/v1/developments?_format=json"):
        if not x.get("incomeRestricted", True):
            continue
        units = x.get("units") or []
        kind = {"lottery": "lottery", "waitlist": "waitlist", "first": "first_come"}.get(
            (x.get("assignment") or "").lower(), "lottery")
        beds = [("Studio" if (u.get("bedrooms") or 0) == 0 else bed_label(u["bedrooms"])) for u in units]
        prices = [u.get("price") for u in units if (u.get("priceRate") or "monthly") == "monthly"]
        rent = span(prices)
        out.append(clean({
            "id": f"bos-{x['id']}", "src": "Boston Metrolist", "state": "MA",
            "city": x.get("city"), "neighborhood": x.get("neighborhood"), "name": x.get("title"),
            "address": x.get("streetAddress"),
            "kind": kind, "tenure": "buy" if (x.get("offer") or "") == "sale" else "rent",
            "closes": day(x.get("applicationDueDate")),
            "units": sum(u.get("count") or 0 for u in units) or None, "beds": sort_beds(beds),
            "rent_low": money(rent[0]), "rent_high": money(rent[1]),
            "income_min": money(span([u.get("incomeQualification") for u in units])[0]),
            "ami": span([u.get("amiQualification") for u in units])[1],
            "href": f"https://www.boston.gov/metrolist/search/housing/{x['slug']}"}))
    return out


BLOOM_KIND = {"lottery": "lottery", "waitlist": "waitlist", "waitlistLottery": "lottery",
              "firstComeFirstServe": "first_come"}


def first_image(x):
    """The listing's first photo (Bloom orders them by ordinal); spaces in the
    S3 key are escaped so the URL loads on iOS."""
    imgs = sorted(x.get("listingImages") or [], key=lambda i: i.get("ordinal") or 0)
    for i in imgs:
        u = ((i.get("assets") or {}).get("fileId") or "").strip()
        if u.startswith("http"):
            return urllib.parse.quote(u, safe=":/?=&%")
    return None


def bloom(items, base, src):
    out = []
    for x in items:
        if x.get("status") != "active":
            continue
        a = x.get("listingsBuildingAddress") or {}
        groups = (x.get("unitsSummarized") or {}).get("byUnitTypeAndRent") or []
        beds, rents, incomes = [], [], []
        for g in groups:
            t = g.get("unitTypes") or {}
            n = t.get("numBedrooms")
            beds.append(bed_label(n) if isinstance(n, int) else BED_WORDS.get((t.get("name") or "").lower()))
            rents += [money((g.get("rentRange") or {}).get(k)) for k in ("min", "max")]
            incomes.append(money((g.get("minIncomeRange") or {}).get("min")))
        rent = span(rents)
        city = (a.get("city") or "").strip().title()
        out.append(clean({
            "id": f"{src.split()[0].lower()}-{x['id']}", "src": src, "state": a.get("state") or "CA",
            "city": city, "neighborhood": x.get("neighborhood"), "name": x.get("name"),
            "address": a.get("street"), "zip": a.get("zipCode"), "lat": a.get("latitude"), "lng": a.get("longitude"),
            "kind": BLOOM_KIND.get(x.get("reviewOrderType"), "waitlist"), "tenure": "rent",
            "closes": day(x.get("applicationDueDate")),
            "units": x.get("unitsAvailable") or None, "beds": sort_beds([b for b in beds if b]),
            # Bloom's minimum income is per MONTH ("$3,098"), unlike Boston's yearly figure.
            "rent_low": rent[0], "rent_high": rent[1], "income_min_mo": span(incomes)[0], "image": first_image(x),
            "href": f"{base}/listing/{x['id']}/{x.get('urlSlug') or ''}"}))
    return out


def access_la():
    d = get("https://access.housing.lacity.gov/api/adapter/listings?limit=all&view=base"
            "&filter[0][$comparison]==&filter[0][status]=active")
    return bloom(d.get("items") or [], "https://access.housing.lacity.gov", "Access Housing LA")


def doorway():
    d = get("https://housingbayarea.mtc.ca.gov/api/adapter/listings/combined",
            {"page": 1, "limit": "all", "filter": [{"$comparison": "=", "status": "active"}]})
    return bloom(d.get("items") or [], "https://housingbayarea.mtc.ca.gov", "Doorway Bay Area")


LEASING_FILE = None   # set in main(): <docroot>/mia/leasing.json


def miami_leasing():
    """Miami-Dade buildings Florida Housing marks "Active - In Lease-Up" —
    taking their first tenants now. build_affordable_cities.py writes the
    list; there is no application portal, so the link searches for the
    building's leasing office — unless mia/leasing_links.json has the
    building's own leasing page (owner, 2026-09-24: "these should take users to
    the actual leasing site or availabilities")."""
    rows = json.loads(Path(LEASING_FILE).read_text())
    try:
        links = json.loads((HERE / "mia" / "leasing_links.json").read_text())["buildings"]
    except (OSError, ValueError, KeyError):
        links = {}
    out = []
    for r in rows:
        link = links.get(r.get("name") or "") or {}
        q = urllib.parse.quote_plus(f"{r.get('name') or ''} {r.get('addr') or ''} Miami leasing office")
        out.append(clean({
            "id": "mia-" + re.sub(r"[^a-z0-9]+", "-", (r.get("name") or r.get("addr") or "").lower()).strip("-"),
            "src": "Florida Housing", "state": "FL", "city": "Miami-Dade", "name": r.get("name"),
            "address": r.get("addr"), "zip": r.get("zip"), "lat": r.get("lat"), "lng": r.get("lng"),
            "kind": "leasing", "tenure": "rent", "units": r.get("li") or r.get("units"),
            "phone": link.get("phone"), "note": link.get("note"),
            "href": link.get("url") or f"https://www.google.com/search?q={q}"}))
    return out


SOURCES = {"SF DAHLIA": dahlia, "Access Housing LA": access_la, "Doorway Bay Area": doorway,
           "Florida Housing": miami_leasing}
# Boston's Metrolist answers from a laptop but its Imperva WAF serves a bot
# challenge to the droplet (2026-09-24). We do not work around a WAF; the
# adapter stays for when the City grants access (python3 build_openings.py
# --with-boston runs it anyway, e.g. to test).
OPTIONAL = {"Boston Metrolist": metrolist}


def still_open(o, today=TODAY):
    return not o.get("closes") or o["closes"] >= today


def build(previous, sources=SOURCES, today=TODAY):
    """Every source's openings; a source that fails or returns nothing keeps
    what the previous file had for it."""
    old = {}
    for o in (previous or {}).get("openings", []):
        old.setdefault(o.get("src"), []).append(o)
    out, status = [], {}
    for name, fn in sources.items():
        try:
            got = [o for o in fn() if still_open(o, today)]
            if not got:
                raise RuntimeError("no open listings")
            status[name] = {"ok": True, "n": len(got)}
        except Exception as e:
            got = [o for o in old.get(name, []) if still_open(o, today)]
            status[name] = {"ok": False, "n": len(got), "error": str(e)[:200]}
            print(f"openings: {name} failed ({e}); kept {len(got)} from the last file", file=sys.stderr)
        out += got
    out.sort(key=lambda o: (o.get("state") or "", o.get("closes") or "9999", o.get("name") or ""))
    return out, status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "openings.json"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--with-boston", action="store_true")
    a = ap.parse_args()
    global LEASING_FILE
    LEASING_FILE = Path(a.out).resolve().parent / "mia" / "leasing.json"
    try:
        previous = json.loads(Path(a.out).read_text())
    except (OSError, ValueError):
        previous = None
    openings, status = build(previous, {**SOURCES, **(OPTIONAL if a.with_boston else {})})
    if not openings:
        print("openings: nothing from any source, keeping the last file", file=sys.stderr)
        return 1
    payload = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "sources": status, "openings": openings}
    if a.dry_run:
        print(json.dumps(status, indent=1))
        for o in openings[:5]:
            print(o)
        return 0
    tmp = Path(a.out + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")))
    tmp.replace(a.out)
    print(f"openings: {len(openings)} -> {a.out} " + " ".join(f"{k}={v['n']}" for k, v in status.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
