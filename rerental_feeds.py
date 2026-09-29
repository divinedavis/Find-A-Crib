#!/usr/bin/env python3
"""
Re-rental sources that publish JSON instead of a page to render.

rerental_daily.py and featured_rerentals.py both walk rerental_pages.json and
render every board in a headless browser, because that is the only thing the
small-office sites have in common. A few sources do better: they serve the
list their own page is drawn from as JSON. Rendering those would mean scraping
a page back into the data it was built from, so a page entry with a "feed" key
is fetched here instead and never opened in the browser:

    "NYC Housing Development Corporation (HDC)": {
        "url": "https://www.nychdc.com/find-re-rentals",   # the human page
        "feed": "hdc", ...}

`url` stays the page a person would open — it is what the /marketing-agents/
directory, the digest and every tile link to. The feed is only where the
numbers come from.

Each feed yields records in featured_rerentals' shape (one per development or
unit), and daily_items() turns those into the key/label rows the daily diff
and the borough alerts read. A feed that is down raises FeedError; both
callers catch it per source, so one source failing never costs the sweep.

Everything a feed returns is somebody else's text. It is kept as plain strings
here and escaped where it is rendered (esc() in index.html, SwiftUI Text in the
app, html.escape in the mailers) — nothing in this module builds markup.

  python3 rerental_feeds.py            # fetch every feed, print what it yields
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# The same identifying UA as featured_rerentals: a public agency reading its
# logs should be able to tell what this is and who to mail in one search.
UA = ("Mozilla/5.0 (compatible; FindACribBot/1.0; +https://findacrib.com/marketing-agents/) "
      "Chrome/126.0 Safari/537.36")
TIMEOUT = 20
MAX_BYTES = 2_000_000      # one page of HDC is ~15 KB; anything near this is wrong

# The borough names the tiles, the app (FeaturedListing.boroughCode) and the
# alert dispatcher (lottery_alerts.boro_code) all understand. HDC writes
# "The Bronx"; the rest of featured.json says "Bronx".
BOROUGHS = {"manhattan": "Manhattan", "brooklyn": "Brooklyn", "queens": "Queens",
            "bronx": "Bronx", "the bronx": "Bronx", "staten island": "Staten Island"}


class FeedError(Exception):
    """A feed could not be read. The caller records it and moves on."""


def fetch_json(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise FeedError(f"HTTP {e.code} from {url}") from None
    except Exception as e:  # noqa: BLE001 — DNS, TLS, timeout: all the same to the caller
        raise FeedError(f"{type(e).__name__} fetching {url}: {str(e)[:60]}") from None
    if len(body) > MAX_BYTES:
        raise FeedError(f"response from {url} is over {MAX_BYTES:,} bytes")
    try:
        return json.loads(body)
    except ValueError:
        raise FeedError(f"{url} did not return JSON") from None


def text(v, limit=160):
    """A feed string, flattened: no markup, no runs of whitespace, bounded.

    HDC's addresses carry stray asterisks ("*516 SCHROEDERS AVE") and its
    descriptions are HTML. None of that is rendered as markup anywhere, but a
    tile showing "<p>" or "*" is still broken, so it is stripped here.
    """
    if v is None:
        return ""
    s = re.sub(r'<[^>]*>', ' ', str(v))
    s = s.replace("*", " ")
    s = re.sub(r'\s+', ' ', s).strip(" ,")
    return s[:limit]


KEEP_UPPER = {"NY", "NYC", "LIC", "II", "III", "IV", "VI", "VII", "LLC", "HDFC", "AMI"}


def tidy_case(s):
    """"ATLANTIC CHESTNUT PHASE I" -> "Atlantic Chestnut Phase I".

    Only for a string that is shouting (no lowercase at all): half of HDC's
    developments are typed in capitals and the other half are not, and a grid
    of tiles alternating between the two reads as broken. Mixed-case input is
    left exactly as the source wrote it.
    """
    if not s or re.search(r'[a-z]', s):
        return s
    out = []
    for w in s.split(" "):
        core = w.strip(",.&()")
        if core in KEEP_UPPER or re.fullmatch(r'[IVX]+', core):
            out.append(w)                             # NY, Phase II
        elif re.fullmatch(r'\d+(ST|ND|RD|TH)', core):
            out.append(w.lower())                     # 39TH -> 39th
        elif re.search(r'\d', w):
            out.append(w)                             # 4B-2, 126-43
        else:
            m = re.search(r'[A-Z]', w)                # HUNTER’S -> Hunter’s
            out.append(w[:m.start() + 1] + w[m.start() + 1:].lower() if m else w)
    return " ".join(out)


def borough(name):
    return BOROUGHS.get((name or "").strip().lower())


# ------------------------------------------------------------------ HDC
# NYC Housing Development Corporation's own re-rental board. 24 developments on
# 2026-09-29, nine to a page; the page at /find-re-rentals is drawn from this
# endpoint. robots.txt disallows only admin paths. Each development carries a
# rent range (monthly rents — HDC's filter labels it "Rent"), the bedroom sizes
# on offer, the borough, a photo and a PDF flyer. There is no page per
# development (show_details is false on every row), so the apply link is the
# board itself; the flyer is a document, not a page you apply on, and the
# featured tiles already refuse PDFs as a listing link for that reason.
HDC_API = "https://www.nychdc.com/api/re-rentals?current-page={page}"
HDC_PAGE = "https://www.nychdc.com/find-re-rentals"
HDC_HOST = "https://www.nychdc.com"
HDC_MAX_PAGES = 8            # 3 today; a bound, not a guess at the count


def hdc_fetch(max_pages=HDC_MAX_PAGES, fetch=fetch_json):
    """Every row of HDC's board, following its own page-count."""
    rows, page, pages = [], 1, 1
    while page <= min(pages, max_pages):
        d = fetch(HDC_API.format(page=page))
        if not isinstance(d, dict) or not isinstance(d.get("json"), list):
            raise FeedError("HDC: unexpected response shape")
        rows.extend(r for r in d["json"] if isinstance(r, dict))
        try:
            pages = int((d.get("pagination") or {}).get("page-count") or 1)
        except (TypeError, ValueError):
            pages = 1
        page += 1
    return rows


def hdc_beds(copy):
    """"1-Bedroom, 2-Bedroom, Studio" -> None; "Studio" -> "studio"; "2-Bedroom" -> "2".

    The tile prints one bed count. A development offering three sizes has no
    single answer, and naming the first would be a claim about the others.
    """
    sizes = [s.strip().lower() for s in (copy or "").split(",") if s.strip()]
    if len(sizes) != 1:
        return None
    s = sizes[0]
    if s.startswith("studio"):
        return "studio"
    m = re.match(r'(\d+)\s*-?\s*bed', s)
    return m.group(1) if m else None


def hdc_image(row):
    img = row.get("image") if isinstance(row.get("image"), dict) else {}
    src = img.get("re_rental_card_2x") or img.get("re_rental_card") or img.get("url")
    if not src or not isinstance(src, str):
        return None
    src = urllib.parse.urljoin(HDC_HOST + "/", src)
    # Only HDC's own files: a feed pointing the photo fetcher somewhere else is
    # not something to follow.
    return src if src.startswith(HDC_HOST + "/") else None


def hdc_records(rows, agent, page_url=HDC_PAGE):
    """HDC rows -> featured_rerentals records (same keys, same money rules)."""
    import featured_rerentals as fr
    out = []
    for row in rows:
        nid = str(row.get("nid") or "").strip()
        address = tidy_case(text(row.get("address"), 120))
        if not nid.isdigit() or not address:
            continue
        title = tidy_case(text(row.get("title"), 80))
        rent_copy = text(row.get("rent_range"), 60)
        amounts = fr.amounts_in(rent_copy)
        # HDC's field is the monthly rent range, so the context says so — but
        # it still goes through classify_money: magnitude decides, and a figure
        # that could not be a monthly rent is dropped rather than printed.
        kind, low, high = fr.classify_money(amounts, "Monthly rent " + rent_copy)
        zm = fr.ZIP.search(address)
        boro = borough(row.get("borough")) or fr.borough_of(address, "", zm.group(1) if zm else None)
        beds_copy = text(row.get("bedrooms_copy"), 80)
        extras = [x for x in (text(row.get("age_restriction_copy"), 40),
                              text(row.get("adaptation_copy"), 60)) if x]
        out.append({
            "agent": agent,
            "agent_page": page_url,
            "title": title,
            "address": address,
            "borough": boro,
            "zip": zm.group(1) if zm else None,
            "money_kind": kind,
            "money_low": low,
            "money_high": high,
            "income_1p_max": None,
            "units": None,              # HDC lists developments, not a unit count
            "beds": hdc_beds(beds_copy),
            "href": page_url,
            "href_kind": "agent_page",
            "image_src": hdc_image(row),
            "_card": [x for x in (title, address, rent_copy and f"Monthly rent {rent_copy}",
                                  beds_copy, *extras) if x],
            "_amounts": amounts,
            # Not published (featured_rerentals strips keys starting "_"); it is
            # what the daily diff keys on, because HDC's own id survives an
            # address being retyped and a development can list three addresses.
            "_key": f"hdc {nid}",
        })
    return out


FEEDS = {
    "hdc": {"fetch": hdc_fetch, "records": hdc_records},
}


def feed_records(name, meta):
    """(records, error) for one page entry with a "feed" key."""
    spec = FEEDS.get(meta.get("feed"))
    if not spec:
        return [], f"unknown feed {meta.get('feed')!r}"
    try:
        rows = spec["fetch"]()
        return spec["records"](rows, name, meta["url"]), None
    except FeedError as e:
        return [], str(e)
    except Exception as e:  # noqa: BLE001 — a parser bug must not cost the other sources
        return [], f"{type(e).__name__}: {str(e)[:70]}"


def first_address(address):
    """(the first street address for a label, one geocodable address).

    "500 Vandalia Ave, East New York, NY 11239" -> ("500 Vandalia Ave", same).
    HDC also lists several buildings in one field: "1115, 1117 & 1123 Ashford
    Street, 516 Schroeders Ave, ..." — cutting at the first comma leaves "1115",
    so segments are taken until one names a street, and the geocoder is asked
    about the last house number in it ("1123 Ashford Street"), a real building
    in the development.
    """
    parts, acc = [p.strip() for p in address.split(",")], []
    for p in parts:
        acc.append(p)
        if re.search(r'[A-Za-z]{2}', p):
            break
    first = ", ".join(acc)
    m = re.search(r'(\d[\w-]*)\s+([A-Za-z].*)$', first)
    return first, (f"{m.group(1)} {m.group(2)}" if m else first)


def daily_items(records):
    """Featured-shape records -> the rows rerental_daily diffs and alerts on.

    Carries its own borough and rent, so the alert says where and how much on
    the day the listing first appears rather than waiting for the next
    featured pass. `geo` is the first address on the record — what the city
    geocoder is asked for the neighbourhood — while `label` is what a reader
    sees, and leads with the development's name.
    """
    out, seen = [], set()
    for r in records:
        key = r.get("_key")
        if not key or key in seen:
            continue
        seen.add(key)
        first, geo = first_address(r["address"])
        label = f"{r['title']} — {first}" if r.get("title") else r["address"]
        out.append({"key": key, "label": label[:80], "url": r["href"],
                    "geo": geo, "boro": r.get("borough"),
                    "rent_low": r["money_low"] if r.get("money_kind") == "rent" else None,
                    "income_max": r.get("income_1p_max")})
    return out


def main():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    pages = json.load(open(os.path.join(here, "rerental_pages.json")))["pages"]
    for name, meta in pages.items():
        if not meta.get("feed"):
            continue
        recs, err = feed_records(name, meta)
        if err:
            print(f"ERR  {name}: {err}")
            continue
        money = {}
        for r in recs:
            money[r["money_kind"]] = money.get(r["money_kind"], 0) + 1
        print(f"{name}: {len(recs)} records · money {money} · "
              f"{sum(1 for r in recs if r['image_src'])} with a photo")
        for r in recs:
            amt = f"{r['money_kind']} ${r['money_low']:,}-{r['money_high']:,}" if r["money_kind"] else "no price"
            print(f"   {r['address'][:48]:48} {str(r['borough']):10} {amt:24} {r['title'][:30]}")


if __name__ == "__main__":
    main()
