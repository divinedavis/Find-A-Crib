#!/usr/bin/env python3
"""
Re-rental sources that publish JSON (or plain server-rendered HTML) instead of
a page that needs a browser to render.

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

  python3 pipeline/rerental_feeds.py            # fetch every feed, print what it yields
"""
import html
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


def hdc_flyer(row):
    """Absolute URL of the row's PDF flyer on HDC's own host, or None."""
    pdf = row.get("pdf")
    if not pdf or not isinstance(pdf, str):
        return None
    url = urllib.parse.urljoin(HDC_HOST + "/", pdf.strip())
    if not url.startswith(HDC_HOST + "/") or not urllib.parse.urlsplit(url).path.lower().endswith(".pdf"):
        return None
    return url


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
            # The development's own flyer, not the board (owner, 2026-10-01:
            # the button "took me to this generic link, not the actual
            # listing"). HDC has no page per development, but every row has a
            # flyer: the unit sizes, rent, income bands and how to apply
            # (email / phone / mail to the marketing agent). That IS the
            # listing; the board stays the fallback for a row without one.
            "href": hdc_flyer(row) or page_url,
            "href_kind": "flyer" if hdc_flyer(row) else "agent_page",
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


# ------------------------------------------------------------ Progressive
# Progressive Management of NY's "Vacant Apartments" page (HPD-listed marketing
# agent). Every building on it is income-restricted (LIHTC, 55% AMI, a 62+
# senior building), so it is a re-rental source, not a market-rate one — it sat
# in owner_vacancy_pages.json for seven weeks and produced nothing there,
# because the index is five building names with "Learn more" and the details
# live in Squarespace lightboxes that innerText never sees (checked 2026-11-11).
#
# Each lightbox is the building's own page, served as plain HTML, so no browser
# is needed: read the index for the lightbox slugs, then fetch each building.
# robots.txt allows both (it disallows only ?format=json and friends, which
# are not used here). A building is a record only when its page says a unit is
# open — "2-bedroom unit (1 available)" or "Applications are being accepted";
# Grant Forbell's page describes the building and claims no vacancy, so it is
# left out rather than shown as available.
PROG_HOST = "https://www.progressivemgmt.net"
PROG_PAGE = PROG_HOST + "/vacant-apartments"
PROG_MAX = 20                # 5 today; a bound, not a guess at the count
PROG_SLUG = re.compile(r'href="/?#lightbox_([a-z0-9][a-z0-9-]{0,79})"')
PROG_AVAIL = re.compile(r'\((\d{1,3})\s+available\)', re.I)
PROG_OPEN = re.compile(r'applications\s+are\s+(?:now\s+)?being\s+accepted', re.I)
PROG_BEDS = re.compile(r'\b(studio|\d)\s*-?\s*(?:bed(?:room)?s?|br)\b', re.I)
STREET = (r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Place|Pl|Parkway|Pkwy"
          r"|Drive|Dr|Lane|Ln|Terrace|Court|Ct)\b\.?")
# An address on a short line of its own, wherever it starts on the line:
# "3035 White Plains Road, Bronx, NY 10467", "Address: 533-539 Bay St 533-539
# Bay St, ..." (the site repeats it; the first copy is taken), "ARCHER MERRICK
# 92-61 165TH Street, Jamaica, NY 11433" (the name runs into it). The tail is
# kept only when it follows a comma, so a repeated street is never swallowed.
PROG_ADDR_LINE = re.compile(r'(?<![\w-])(\d[\d-]*\s+[A-Za-z0-9 .\'-]+?' + STREET
                            + r')(,[A-Za-z0-9 .,]{0,60})?', re.I)
PROG_LINE_MAX = 100
# "...consisting of 83 units located at 886 Westchester Avenue between..."
PROG_ADDR_PROSE = re.compile(r'\b(?:located\s+)?at\s+(\d[\d-]*\s+[A-Z][A-Za-z0-9 .\'-]*?'
                             + STREET + r')')


def fetch_html(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise FeedError(f"HTTP {e.code} from {url}") from None
    except Exception as e:  # noqa: BLE001
        raise FeedError(f"{type(e).__name__} fetching {url}: {str(e)[:60]}") from None
    if len(body) > MAX_BYTES:
        raise FeedError(f"response from {url} is over {MAX_BYTES:,} bytes")
    return body.decode("utf-8", "replace")


def html_lines(markup):
    """The text of an HTML fragment, one line per block element."""
    import html as htmlmod
    s = re.sub(r'(?is)<(script|style|noscript|template)\b.*?</\1>', ' ', markup)
    s = re.sub(r'(?i)<br\s*/?>|</(?:p|h[1-6]|li|div|section|tr)>', '\n', s)
    s = htmlmod.unescape(re.sub(r'<[^>]*>', ' ', s)).replace("​", "")
    return [l for l in (re.sub(r'\s+', ' ', x).strip() for x in s.split("\n")) if l]


def progressive_fetch(fetch=fetch_html, max_pages=PROG_MAX):
    """[(slug, page HTML)] for every building the index links a lightbox to."""
    index = fetch(PROG_PAGE)
    slugs = list(dict.fromkeys(PROG_SLUG.findall(index)))
    if not slugs:
        raise FeedError("Progressive: no buildings on the vacant-apartments page")
    return [(s, fetch(f"{PROG_HOST}/{s}")) for s in slugs[:max_pages]]


def progressive_records(rows, agent, page_url=PROG_PAGE):
    """Building pages -> featured_rerentals records, only where a unit is open."""
    import featured_rerentals as fr
    out = []
    for slug, markup in rows:
        m = re.search(r'(?is)<main\b.*?</main>', markup)
        lines = html_lines(m.group(0) if m else markup)
        # The building's name is the page's first heading (an <h4> today, so
        # any level), and the first line of the page when there is none.
        h = re.search(r'(?is)<h([1-6])[^>]*>(.*?)</h\1>', m.group(0) if m else markup)
        heading = html_lines(h.group(2)) if h else []
        title = tidy_case(text((heading or lines or [""])[0], 80))
        if not lines or not title:
            continue
        status = next((l for l in lines if PROG_AVAIL.search(l) or PROG_OPEN.search(l)), None)
        if not status:
            continue                              # describes the building, claims no vacancy
        blob = " ".join(lines)
        address = None
        for line in lines:
            a = len(line) <= PROG_LINE_MAX and PROG_ADDR_LINE.search(line)
            if a:
                address = a.group(1) + (a.group(2) or "")
                break
        if not address:
            a = PROG_ADDR_PROSE.search(blob)
            address = a.group(1) if a else None
        if not address:
            continue
        address = text(address, 120)
        zm = fr.ZIP.search(address)
        boro = fr.borough_of(address, blob, zm.group(1) if zm else None)
        avail = PROG_AVAIL.findall(blob)
        bm = PROG_BEDS.search(status) or PROG_BEDS.search(blob)
        beds = None if not bm else ("studio" if bm.group(1).lower() == "studio" else bm.group(1))
        # "Applications are now being accepted for" breaks the sentence over
        # two blocks on Archer Merrick; a short status line takes the next one.
        i = lines.index(status)
        if len(status) < 60 and i + 1 < len(lines):
            status = f"{status} {lines[i + 1]}"
        status_copy = text(status, 160)
        out.append({
            "agent": agent,
            "agent_page": page_url,
            "title": title,
            "address": address,
            "borough": boro,
            "zip": zm.group(1) if zm else None,
            # Rents are not published; Bay Street's "$50,062" is a minimum
            # income, and printing it as an income limit would be wrong.
            "money_kind": None,
            "money_low": None,
            "money_high": None,
            "income_1p_max": None,
            "units": sum(int(n) for n in avail) if avail else None,
            "beds": beds,
            "href": f"{PROG_HOST}/{slug}",
            "href_kind": "listing",
            "image_src": None,
            "_card": [x for x in (title, address, status_copy) if x],
            "_amounts": [],
            "_key": f"progressive {slug}",
        })
    return out


# ------------------------------------------------------------------ WordPress
# Reside New York's board (/property-status/open-market/) is a WordPress
# taxonomy archive. Its first page is exactly this REST query: open-market
# properties, most recently modified first, 20 a page (checked slug for slug
# on 2026-11-13). Rendering the page in a browser gave 7 of those 20 for days,
# then all of them at once on 2026-11-12, and 18 listings posted Nov 5-11 went
# out as "18 new". The REST answer is the same set every time and carries each
# listing's publish date and its own page.
#
# Only the titles go to rerental_daily, which keys and filters them with the
# same listings_from() as a rendered board, so the switch re-keys nothing.
WP_PER_PAGE = 20             # one board page; WordPress caps per_page at 100
WP_TITLE_MAX = 90            # listings_from skips longer lines anyway


def wp_board(site, taxonomy, term, post_type="property", fetch=fetch_json, per_page=WP_PER_PAGE):
    """[{title, link, posted, modified}] for one WordPress board, as its first
    page shows it. Raises FeedError when the site does not answer as expected,
    so the caller can fall back to rendering the page."""
    parts = urllib.parse.urlsplit(site)
    if parts.scheme != "https" or not parts.hostname:
        raise FeedError(f"wp site must be https: {site!r}")
    host = parts.hostname
    base = f"https://{host}/wp-json/wp/v2"
    q = urllib.parse.urlencode
    terms = fetch(f"{base}/{urllib.parse.quote(taxonomy)}?" + q({"slug": term, "_fields": "id,slug"}))
    ids = [t.get("id") for t in terms if isinstance(t, dict) and isinstance(t.get("id"), int)] \
        if isinstance(terms, list) else []
    if not ids:
        raise FeedError(f"{host}: no {taxonomy} term {term!r}")
    rows = fetch(f"{base}/{urllib.parse.quote(post_type)}?" + q({
        taxonomy: ids[0], "per_page": max(1, min(int(per_page), 100)),
        "orderby": "modified", "order": "desc", "status": "publish",
        "_fields": "date,modified,link,title,status"}))
    if not isinstance(rows, list):
        raise FeedError(f"{host}: {post_type} list is not a list")
    out = []
    for r in rows[:per_page]:
        if not isinstance(r, dict) or r.get("status", "publish") != "publish":
            continue
        title = text(html.unescape(str((r.get("title") or {}).get("rendered") or "")), WP_TITLE_MAX)
        link = str(r.get("link") or "")
        lp = urllib.parse.urlsplit(link)
        # Somebody else's data: a title is plain text, and a link must be a
        # page on the agent's own site or it is dropped.
        if lp.scheme != "https" or lp.hostname != host:
            link = None
        if not title:
            continue
        out.append({"title": title, "link": link,
                    "posted": _wp_date(r.get("date")), "modified": _wp_date(r.get("modified"))})
    if not out:
        raise FeedError(f"{host}: board is empty over REST")
    return out


def _wp_date(v):
    """'2026-11-05T21:35:10' -> '2026-11-05'; anything else -> None."""
    m = re.match(r'(\d{4}-\d{2}-\d{2})T', str(v or ""))
    return m.group(1) if m else None


FEEDS = {
    "hdc": {"fetch": hdc_fetch, "records": hdc_records},
    "progressive": {"fetch": progressive_fetch, "records": progressive_records},
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
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if os.path.basename(os.path.dirname(os.path.abspath(__file__))) == "pipeline" else os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    pages = json.load(open(os.path.join(here, "data" if here != os.path.dirname(os.path.abspath(__file__)) else "", "rerental_pages.json")))["pages"]
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
