#!/usr/bin/env python3
"""
Build the "featured" tiles: real income-restricted apartments the HPD marketing
agents are advertising right now.

rerental_daily.py already renders these 14 pages every morning and answers "what
moved overnight" — but it only keeps a normalized key per listing ("881
lexington"), which is all a diff needs and nowhere near enough for a tile. This
walks the same pages and pulls a whole record per apartment: building name,
address, the money, how many units, the photo, and the link to apply.

Why this inventory is worth a tile: these are income-restricted re-rentals from
HPD-approved marketing agents. They are not on StreetEasy, they are not on
Zumper, and they vanish in days. It is the one kind of listing this site can
show that the big portals structurally do not have.

  python3 featured_rerentals.py                  # scan, print what it found
  python3 featured_rerentals.py --apply          # write featured.json + photos
  python3 featured_rerentals.py --apply --deploy # ...and push both to the droplet

THE MONEY IS NOT ALWAYS RENT. MGNY prints "$98,366 - $176,410" against a
listing; that is the household income you must earn to qualify, not what you
pay. Printing it as a rent would be the single most misleading thing this
feature could do, so every amount is classified before it is stored and the
tile says which one it is. See classify_money().
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RERENTALS = os.path.join(HERE, "rerental_pages.json")
OUT = os.path.join(HERE, "featured.json")
IMGDIR = os.path.join(HERE, "featured", "img")
DROPLET = "root@104.236.120.144:/var/www/rent-map/"

# Identifies the crawler and points at the page that explains it. These sites
# are small offices, not portals — someone reading their logs should be able to
# tell what this is and who to mail about it in one search.
UA = ("Mozilla/5.0 (compatible; FindACribBot/1.0; +https://findacrib.com/marketing-agents/) "
      "Chrome/126.0 Safari/537.36")

# A NYC monthly rent is not five figures and an income limit is not four. The
# split is wide enough that no real listing lands near it: the priciest thing
# these agents post is a few thousand a month, and the lowest income band is
# tens of thousands a year.
INCOME_FLOOR = 20000
# A monthly rent this side of either bound is not a rent. Tax Solute's page put
# "$154" next to a Crown Street listing — an application fee, a square footage,
# a footnote, something — and it published as "$154/mo", which is a more
# damaging thing to print than no price at all. Income-restricted units do go
# genuinely low, so the floor is set under the cheapest plausible one.
RENT_MIN, RENT_MAX = 400, 15000

MONEY = re.compile(r'\$\s?(\d[\d.,]*)')
# "1 PERSON $135,360.00 - $154.440.00" — the income band for a single-person
# household, which is the number someone looking at a studio actually needs.
ONE_PERSON = re.compile(r'\b1\s*(?:person|adult|occupant)\b', re.I)
UNITS = re.compile(r'\b(\d+)\s+units?\b', re.I)
BEDS = re.compile(r'\b(studio|\d+)\s*(?:bed|bd|br|bedroom)s?\b', re.I)
ZIP = re.compile(r'\b(\d{5})\b')
# "188-11 Hillside Avenue, Queens, NY 11423" / "410 W 126th St, New York, NY"
ADDRISH = re.compile(r'^\s*\d+[\w-]*\s+[A-Za-z0-9.\'-]', re.I)
# "5 Results", "10 results", "0 Active Listings", "1 PERSON $135,360", "1 hour",
# "1 year 1 month 4 days" — every one of these opens with a number followed by a
# word, which is also what an address looks like. Result counts and income-table
# rows sit right next to the listings and duration strings litter TF
# Cornerstone, so without this the grid fills with tiles for "5 Results".
NOT_A_STREET = re.compile(
    r'^\s*\d+[\w-]*\s+(results?|active|listings?|available|units?|bed|beds|bedrooms?|'
    r'studios?|person|people|household|applicants?|min(?:ute)?s?|hours?|days?|weeks?|'
    r'months?|years?|bath|baths|sq\.?\s*ft)\b', re.I)
# "1-Bedroom - 2-Bedroom" is a unit-type list, but the hyphen glues the stopword
# to the number so NOT_A_STREET's `\d+[\w-]*\s+` swallows it and the line reads
# as a street. It published as the headline of every Affordable for NY tile.
UNIT_TYPE = re.compile(r'^\s*(?:studio|\d+)\s*[-–]?\s*(?:bed|bd|br|bath|ba)\w*\b', re.I)
# MHANY leaves leased buildings on the page with the application closed. A tile
# for an apartment nobody can apply to is worse than no tile.
CLOSED = re.compile(r'application process is closed|no longer available|recently leased|'
                    r'waitlist closed|closed to new applic', re.I)
# The line above the address is usually the building's name ("Forten at
# Columbia", "OHM", "Rialto West") — but on some sites it is a section heading,
# and "600 Crown St · Units Available · Brooklyn" reads like the building is
# called Units Available.
GENERIC_TITLE = re.compile(
    r'^(units?\s*available|available\s*units?|available|now\s*leasing|leasing|'
    r'listings?|current\s*vacanc\w*|vacanc\w*|apartments?(\s*for\s*rent)?|'
    r'for\s*rent|new|featured|results?|re-?rentals?|outside\s*market|'
    r'unit\s*available\s*for\s*initial\s*occupancy|initial\s*occupancy|'
    r'affordable(\s*housing)?|our\s*\w+|properties|'
    # Several boards print the borough as a label above the address, which then
    # renders as "BROOKLYN · Brooklyn" — the borough twice, once pretending to
    # be the building's name.
    r'manhattan|brooklyn|queens|bronx|the\s*bronx|staten\s*island|new\s*york|nyc)$', re.I)
# The other thing that sits directly above an address is a table's header row —
# C+C's "Building Unit Beds Baths Rent Date Available Apply" published as the
# building's name. Any title made only of column words is a header, not a name.
COLUMN_WORDS = {"building", "buildings", "unit", "units", "apt", "apartment",
                "apartments", "bed", "beds", "bedroom", "bedrooms", "bath",
                "baths", "bathroom", "bathrooms", "rent", "price", "date",
                "available", "availability", "apply", "size", "type", "floor",
                "status", "income", "household", "name", "address", "no", "sq",
                "ft", "sqft", "move", "in", "term", "lease", "details", "view"}


def is_generic_title(t):
    """Is this a heading or a table header rather than a building's name?"""
    if not t or GENERIC_TITLE.match(t):
        return True
    words = [w for w in re.split(r'[^a-z0-9]+', t.lower()) if w]
    return bool(words) and all(w in COLUMN_WORDS for w in words)
INCOME_WORDS = re.compile(r'income|ami\b|household|earn|eligib', re.I)
RENT_WORDS = re.compile(r'/\s*mo|per month|monthly|rent\b', re.I)

BOROS = {"manhattan": "Manhattan", "new york": "Manhattan", "brooklyn": "Brooklyn",
         "queens": "Queens", "bronx": "Bronx", "the bronx": "Bronx",
         "staten island": "Staten Island", "long island city": "Queens",
         "astoria": "Queens", "jamaica": "Queens"}

# Pulls one record per listing card out of a rendered page. Written as one DOM
# pass rather than 14 bespoke parsers: these are 14 small-office websites on
# every CMS there is, and a per-site selector list would be broken by next
# month's redesign. The shape they DO share is a repeated block that holds an
# address, a photo and a link — so that is what this looks for, taking the
# smallest block that qualifies so a wrapper doesn't swallow the whole grid.
EXTRACT_JS = r"""() => {
  // "Apply on their site" has to land on THE apartment. Taking the first <a> in
  // the block sent six agents' tiles to the board they were scraped from and
  // C+C's to the company logo in the header, so every candidate link is scored
  // and the board itself is explicitly worth nothing.
  // Not "home": Tax Solute's whole board lives at a Google Sites path ending
  // /hpd/home, and denying it sent every one of their tiles to a Drive PDF.
  const NAVISH = /\/(about|contact|careers?|privacy|terms|login|sign-?in|team|news|blog|faq|accessibility|residents?|capabilities|vendors?)\b/i;
  const ACTION = /\b(apply|view|details?|more|learn|floor\s*plans?|availab|listings?|inquire|see)\b/i;
  const JUNK_HOST = /(facebook|twitter|x|instagram|linkedin|youtube|tiktok|pinterest|accessibe|google\.com\/maps)\./i;
  // A flyer is a document, not a page you can apply on. Tax Solute links both
  // the PDF and the building's own section of their board from the same card,
  // and the PDF names the building so it outscores everything — but "Apply on
  // their site" opening a Drive download is not what the button says.
  const DOCISH = /\.(pdf|docx?|xlsx?|pptx?)($|\?)|drive\.google\.com\/file|dropbox\.com\/s\//i;
  const words = s => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean);

  // Which link on this card points at this apartment?
  function pickHref(el, addr) {
    const here = new URL(location.href);
    const herePath = here.pathname.replace(/\/+$/, '');
    const cands = [];
    if (el.matches('a')) cands.push(el);
    el.querySelectorAll('a').forEach(a => cands.push(a));
    // Card grids often wrap the whole tile in the link rather than putting one
    // inside it, so an <a> a level or two up counts as this card's link.
    let hop = el.parentElement;
    for (let i = 0; i < 3 && hop; i++, hop = hop.parentElement) {
      if (hop.matches && hop.matches('a')) cands.push(hop);
    }
    // Words a listing's own URL or link text would repeat from the address.
    const aw = words(addr).filter(w => w.length > 2 && !/^\d+$/.test(w));
    const num = ((addr.match(/^\s*(\d+[\w-]*)/) || [])[1] || '').toLowerCase();

    let best = null, bestScore = 0;
    for (const a of cands) {
      let u;
      try { u = new URL(a.getAttribute('href') || '', location.href); } catch (e) { continue; }
      if (!/^https?:$/.test(u.protocol) || JUNK_HOST.test(u.hostname)) continue;
      const path = u.pathname.replace(/\/+$/, '');
      const isRoot = path === '';
      const samePage = path === herePath && !u.search;
      // The board a listing was scraped from is not that listing.
      if (isRoot || (samePage && u.hash.length < 3)) continue;
      if (NAVISH.test(path)) continue;
      const text = (a.innerText || '').trim();
      const hay = (path + ' ' + u.search + ' ' + text).toLowerCase();
      const hits = aw.filter(w => hay.includes(w)).length;

      let score;
      if (DOCISH.test(u.href)) score = 1;              // last resort: a flyer beats a grid
      else if (hits >= 2 || (hits === 1 && num && hay.includes(num))) score = 5;  // names the building
      else if (samePage) score = 2;                    // one-page board, deep-linked by fragment
      else score = ACTION.test(text) ? 4 : 3;
      if (score > bestScore) { bestScore = score; best = u.href; }
    }
    return best;
  }

  const ADDR = /^\s*\d+[\w-]*\s+[A-Za-z0-9.'-]/;
  // Same stopwords the Python side uses, and they have to be HERE too: "1
  // Unit", "10 results" and "3 Beds" all open with a number and a word, so
  // without this they count as addresses. On MGNY that put a phantom building
  // key next to the real one inside every card, every card looked like a
  // two-listing wrapper, and the whole site produced nothing.
  const NOPE = /^\s*\d+[\w-]*\s+(results?|active|listings?|available|units?|bed|beds|bedrooms?|studios?|person|people|household|applicants?|min(ute)?s?|hours?|days?|weeks?|months?|years?|bath|baths|sq\.?\s*ft)\b/i;
  const isAddr = l => ADDR.test(l) && !NOPE.test(l) && l.length < 90 && /[a-z]{3}/i.test(l);
  // LARGEST block that still holds exactly ONE address. Taking the smallest
  // instead collapses every card down to the bare address element and throws
  // away the rent, the unit count and the photo — which is the whole record.
  // One address is what makes a block a card: two or more and it is the grid.
  // Count BUILDINGS, not address-shaped lines. MGNY and Housing Partnership
  // both print the address twice per card — the building name on top ("188-11
  // Hillside Avenue") and the postal address under it ("188-11 Hillside
  // Avenue, Queens, NY 11423"). Counting lines makes every one of their cards
  // look like a two-listing wrapper and drops the whole site.
  const bldg = l => l.toLowerCase().replace(/[^a-z0-9 ]/g, ' ')
                     .split(/\s+/).filter(Boolean).slice(0, 2).join(' ');
  const best = new Map();
  document.querySelectorAll('a, article, li, div, section').forEach(el => {
    const txt = (el.innerText || '').trim();
    if (!txt || txt.length > 600) return;
    const lines = txt.split('\n').map(s => s.trim()).filter(Boolean);
    const addrs = lines.filter(isAddr);
    if (!addrs.length) return;
    if (new Set(addrs.map(bldg)).size !== 1) return;
    // Prefer the fullest spelling — the one carrying borough and ZIP.
    addrs.sort((a, b) => b.length - a.length);
    const key = bldg(addrs[0]);
    const prev = best.get(key);
    if (prev && prev.len >= txt.length) return;
    // The photo often sits on a sibling wrapper rather than inside the text
    // block, so walk up a couple of levels before giving up on it.
    let img = el.querySelector('img'), hop = el;
    for (let i = 0; i < 3 && !img && hop.parentElement; i++) {
      hop = hop.parentElement;
      if ((hop.innerText || '').length < 1500) img = hop.querySelector('img');
    }
    // The card's own headline, for the boards whose only street address is
    // buried inside it ("Greenpoint Central Apartments - 65 Dupont Street").
    const h = el.querySelector('h1, h2, h3, h4, [class*="title"], [class*="Title"]');
    best.set(key, {
      el,
      len: txt.length,
      addr: addrs[0],
      heading: h ? (h.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 120) : '',
      lines: lines.slice(0, 14),
      href: pickHref(el, addrs[0]),
      img: img ? (img.currentSrc || img.src) : null,
      imgW: img ? img.naturalWidth : 0,
      imgH: img ? img.naturalHeight : 0,
    });
  });
  // Hand each card a handle so the Python side can click the ones that turned
  // out to have no link at all (see resolve_by_click). Tag the tightest element
  // that still holds the address, not the block the record came from: with one
  // listing on the page the block is the whole page shell, and pressing that
  // does nothing (iAfford NY has exactly one). A click on something inside the
  // card bubbles up to the card's own handler, so going too deep is harmless.
  const tightest = (el, addr) => {
    let cur = el;
    for (let d = 0; d < 8; d++) {
      const kids = [...cur.children].filter(k => (k.innerText || '').includes(addr));
      if (kids.length !== 1) break;
      cur = kids[0];
    }
    return cur;
  };
  const out = [];
  [...best.entries()].forEach(([key, rec], i) => {
    const probe = 'fac' + i;
    try { tightest(rec.el, rec.addr).setAttribute('data-fac-probe', probe); } catch (e) {}
    delete rec.el;
    out.push({...rec, probe});
  });
  return out;
}"""


def money_val(raw):
    """"135,360.00" -> 135360. Returns None if it isn't a number.

    Separators cannot be trusted to be commas. Tax Solute prints its upper
    income limit as "$154.440.00" — periods where the commas belong — and
    reading that as a plain decimal gives $154, which is how a $154/mo rent
    reached the tile. Strip a two-digit cents tail, then strip every remaining
    separator, and both spellings land on the same integer.
    """
    s = raw.strip().rstrip(".,")
    s = re.sub(r'[.,]\d{2}$', '', s)      # cents
    s = re.sub(r'[.,]', '', s)            # thousands, whichever mark was used
    return int(s) if s.isdigit() else None


def amounts_in(text):
    return [v for v in (money_val(m.group(1)) for m in MONEY.finditer(text))
            if v is not None]


def one_person_income(lines):
    """Highest income a single-person household may earn, when stated.

    Only from a row that actually says one person. The overall range on a card
    spans every household size, so its top is the limit for the largest family
    — quoting that to someone looking at a studio would be wrong by tens of
    thousands.
    """
    best = None
    for line in lines:
        if not ONE_PERSON.search(line):
            continue
        vals = [v for v in amounts_in(line) if v >= INCOME_FLOOR]
        if vals:
            best = max(vals) if best is None else max(best, max(vals))
    return best


# NYC ZIP prefixes, for the listings whose card never names a borough.
ZIP_BORO = {"100": "Manhattan", "101": "Manhattan", "102": "Manhattan",
            "103": "Staten Island", "104": "Bronx", "112": "Brooklyn",
            "111": "Queens", "113": "Queens", "114": "Queens", "116": "Queens"}


def borough_of(address, blob, zipcode):
    """Which borough, from anything on the card that says so.

    The address line usually doesn't: Taxace writes "2187 Ryer Avenue. Unit 6D"
    and puts "Bronx, NY" on the line below. Reading only the address left two
    thirds of the listings with no borough at all, which makes a borough filter
    useless. Named boroughs beat the ZIP, and both beat a bare "New York" —
    that string is on every card in the city.
    """
    for text in (address, blob):
        low = text.lower()
        for k, v in BOROS.items():
            if k in ("new york", "manhattan") or v == "Manhattan":
                continue                       # too generic; handled last
            if re.search(r'\b' + re.escape(k) + r'\b', low):
                return v
    if zipcode and zipcode[:3] in ZIP_BORO:
        return ZIP_BORO[zipcode[:3]]
    for text in (address, blob):
        if re.search(r'\b(manhattan|new york)\b', text, re.I):
            return "Manhattan"
    return None


def classify_money(amounts, context):
    """Decide what the dollar figures on a listing actually mean.

    Returns (kind, low, high) where kind is 'rent', 'income' or None. Magnitude
    decides it — an amount over INCOME_FLOOR cannot be a monthly rent and an
    amount under it cannot be an annual income limit — and the surrounding words
    only break ties, because half these sites label nothing at all.
    """
    if not amounts:
        return None, None, None
    lo, hi = min(amounts), max(amounts)
    if lo >= INCOME_FLOOR:
        return "income", lo, hi
    # Whatever is left is either rent or noise. Keep only the figures that could
    # be a monthly rent; if none survive, say nothing rather than guess.
    rents = [a for a in amounts if RENT_MIN <= a <= RENT_MAX]
    if not rents:
        return None, None, None
    # Words still get a say: "30% AMI" pages print income figures small enough
    # to pass for rent, and nothing on the card calls them rent.
    if INCOME_WORDS.search(context) and not RENT_WORDS.search(context):
        return None, None, None
    return "rent", min(rents), max(rents)


def clean_address(line):
    """Trim a table row back down to an address.

    C+C renders its availability as a table, so the "address" line arrives as
    "55 South Essex Avenue 507 3 2 $2,100.00 Immediate" — the unit, the beds,
    the baths and the rent all ran together with the street. Cut at the first
    money or bare-number column and the street survives intact.
    """
    s = re.sub(r'\s+', ' ', line).strip()
    s = re.split(r'\s\$', s)[0]                     # everything from the rent on
    s = re.sub(r'\s+(?:\d{1,4}\s+){2,}.*$', '', s)  # trailing numeric columns
    return s.strip(" ,-·|")[:80]


def parse_card(c, agent, page_url):
    """A raw DOM candidate -> a listing record, or None if it isn't one."""
    lines = c["lines"]
    blob_all = " \n".join(lines)
    if CLOSED.search(blob_all):
        return None
    addr_i = next((i for i, l in enumerate(lines)
                   if ADDRISH.match(l) and not NOT_A_STREET.match(l) and len(l) < 90), None)
    if addr_i is None:
        return None
    address = clean_address(c.get("addr") or lines[addr_i])
    # Angular boards (afny.org, iaffordny.com) print no street on its own line —
    # the address is inside the headline and the only address-shaped line left
    # is the unit-type list. Take the headline rather than dropping the card.
    if UNIT_TYPE.match(address):
        heading = re.sub(r'\s+', ' ', c.get("heading") or "").strip()
        if len(heading) < 8 or is_generic_title(heading):
            return None
        address = clean_address(heading)
    # The building's name, when the site prints one above the address.
    title = ""
    if addr_i > 0:
        cand = re.sub(r'\s+', ' ', lines[addr_i - 1]).strip(" .·|-:")
        if (3 < len(cand) < 70 and not ADDRISH.match(cand) and not MONEY.search(cand)
                and not is_generic_title(cand)):
            title = cand
    blob = " \n".join(lines)
    kind, low, high = classify_money(amounts_in(blob), blob)
    um = UNITS.search(blob)
    bm = BEDS.search(blob)
    zm = ZIP.search(address) or ZIP.search(blob)
    zipcode = zm.group(1) if zm else None
    boro = borough_of(address, blob, zipcode)
    return {
        "agent": agent,
        "agent_page": page_url,
        "title": title,
        "address": address,
        "borough": boro,
        "zip": zm.group(1) if zm else None,
        "money_kind": kind,
        "money_low": low,
        "money_high": high,
        # What one person may earn, when the agent breaks it out by household
        # size. The tile falls back to this when there is no rent to show.
        "income_1p_max": one_person_income(lines),
        "units": int(um.group(1)) if um else None,
        "beds": bm.group(1).lower() if bm else None,
        "href": c["href"] or page_url,
        # Whether that link is the apartment or just the board it sits on. The
        # tile says which, because "Apply on their site" pointing at a grid of
        # 35 other apartments is a promise the link doesn't keep.
        "href_kind": "listing" if c["href"] else "agent_page",
        "probe": c.get("probe"),
        "image_src": c["img"] if (c.get("imgW") or 0) >= 240 else None,
    }


def addr_words(address):
    """The tokens of an address distinctive enough to recognise it elsewhere."""
    toks = [w for w in re.split(r'[^a-z0-9]+', address.lower()) if len(w) > 2]
    return [w for w in toks if not w.isdigit()], (re.match(r'\s*(\d+[\w-]*)', address) or [""])[0].strip().lower()


def looks_like(address, text):
    """Does this page look like it is about this address?

    The check that makes clicking safe. A click resolves to whatever the site
    navigates to, and if the grid re-rendered between tagging and pressing, that
    is a different apartment — a confidently wrong link, which is worse than the
    board it replaced. So the destination has to name the building.
    """
    words, num = addr_words(address)
    low = text.lower()
    hits = sum(1 for w in words[:6] if w in low)
    return hits >= 2 or (hits >= 1 and num and num in low)


def resolve_by_click(page, records, page_url, limit=10):
    """Cards with no link anywhere: press one and see where the site goes.

    afny.org and iaffordny.com render their boards as an Angular grid — the card
    is a bare <div id="project-3399348"> with no anchor in it, above it, or
    anywhere near it, and the router turns a click into /re-rentals/3399348.
    There is no href in the DOM to find, so pressing the card is the only way to
    learn the apartment's URL. Six of the site's tiles pointed at the board they
    came from because of this.

    Each click is verified against the address and rolled back, and the whole
    thing is best-effort: anything unexpected leaves the record on its board.
    """
    todo = [r for r in records if r["href_kind"] == "agent_page" and r.get("probe")][:limit]
    fixed = 0
    for rec in todo:
        sel = f'[data-fac-probe="{rec["probe"]}"]'
        try:
            if not page.query_selector(sel):
                page.evaluate(EXTRACT_JS)          # a back-navigation re-rendered the grid
                if not page.query_selector(sel):
                    continue
            page.click(sel, timeout=5000)
            page.wait_for_timeout(2500)
            dest, body = page.url, page.evaluate("() => document.body.innerText")[:4000]
            if dest.rstrip("/") != page_url.rstrip("/") and looks_like(rec["address"], body):
                rec["href"] = dest
                rec["href_kind"] = "listing"
                fixed += 1
            if page.url != page_url:
                page.go_back(wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1500)
        except Exception:
            # A click that misfires must not cost the rest of the board. Get
            # back to the grid if we can and move on.
            try:
                if page.url != page_url:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2500)
            except Exception:
                return fixed
    return fixed


def sweep(pages, only=None):
    from playwright.sync_api import sync_playwright
    out, errors = [], {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 1600}, user_agent=UA)
        for name, meta in pages.items():
            if only and only.lower() not in name.lower():
                continue
            if meta.get("waitlist"):
                continue          # a wait list has no apartment to feature
            page = ctx.new_page()
            try:
                page.goto(meta["url"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3500)
                for _ in range(5):            # several lazy-load the grid on scroll
                    page.mouse.wheel(0, 1600)
                    page.wait_for_timeout(700)
                page.wait_for_timeout(1200)
                cands = page.evaluate(EXTRACT_JS)
                seen, found = set(), []
                for c in cands:
                    rec = parse_card(c, name, meta["url"])
                    if not rec:
                        continue
                    k = re.sub(r'[^a-z0-9]', '', rec["address"].lower())[:24]
                    if not k or k in seen:
                        continue
                    seen.add(k)
                    found.append(rec)
                resolve_by_click(page, found, meta["url"])
                for rec in found:
                    rec.pop("probe", None)
                out.extend(found)
            except Exception as e:
                errors[name] = f"{type(e).__name__}: {str(e)[:70]}"
            finally:
                try:
                    page.close()
                except Exception:
                    pass
        browser.close()
    return out, errors


def office_addresses():
    """The agents' own office addresses, which every one of these sites prints
    in the footer where it reads exactly like a listing."""
    try:
        agents = json.load(open(os.path.join(HERE, "marketing_agents.json")))["agents"]
    except (FileNotFoundError, ValueError, KeyError):
        return set()
    out = set()
    for a in agents:
        addr = (a.get("address") or "").lower()
        m = re.match(r'\s*(\d+[\w-]*)\s+([a-z0-9.\'-]+)', addr)
        if m:
            out.add(f"{m.group(1)} {m.group(2)}")
    return out


def is_real_listing(rec, offices):
    """Filter the noise the DOM pass inevitably picks up."""
    a = rec["address"].lower()
    m = re.match(r'\s*(\d+[\w-]*)\s+([a-z0-9.\'-]+)', a)
    if m and f"{m.group(1)} {m.group(2)}" in offices:
        return False                                   # the agent's own office
    if NOT_A_STREET.match(a):
        return False
    if len(rec["address"]) < 8:
        return False
    if not re.search(r'[a-z]{3}', a):
        return False
    # A tile with no money and no unit count is a link, not an apartment.
    if rec["money_kind"] is None and rec["units"] is None and rec["beds"] is None:
        return False
    return True


def fetch_image(url, timeout=20):
    """Download the agent's photo. Bytes, not a hotlink.

    Hotlinking would spend their bandwidth on every visitor and break the tile
    the day they move a file. Re-hosting costs a few KB and stays fixed.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://findacrib.com/"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not ctype.startswith("image/"):
                return None, None
            data = r.read(3_000_000 + 1)
    except Exception:
        return None, None
    if len(data) > 3_000_000 or len(data) < 900:
        return None, None
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
           "image/gif": ".gif"}.get(ctype)
    if not ext:
        return None, None
    return shrink_image(data, ext)


# The tile shows the photo at ~360 px wide, and the agents publish it at
# whatever their CMS holds — 1600 px PNGs of 0.5-1.3 MB were the norm, and
# a phone decodes each one into 5+ MB of bitmap for every tile in the list.
# That is the same memory budget the map crash of 2026-09-06 came out of.
IMG_MAX_W = 800
IMG_QUALITY = 80


def shrink_image(data, ext):
    """Re-encode a listing photo as a JPEG no wider than IMG_MAX_W.

    GIFs and anything Pillow cannot read pass through unchanged (a broken
    image is the source's problem, and Pillow is optional on the droplet).
    """
    if ext == ".gif":
        return data, ext
    try:
        from PIL import Image, ImageOps
        import io
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        if im.width > IMG_MAX_W:
            im = im.resize((IMG_MAX_W, max(1, round(im.height * IMG_MAX_W / im.width))), Image.LANCZOS)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, "JPEG", quality=IMG_QUALITY, optimize=True, progressive=True)
        small = out.getvalue()
        if len(small) < len(data):
            return small, ".jpg"
        return data, ext
    except Exception:
        return data, ext


def save_images(records, apply_changes):
    """Re-host each listing photo under featured/img/. Returns how many stuck."""
    if apply_changes:
        os.makedirs(IMGDIR, exist_ok=True)
    on_disk = {}
    for f in (os.listdir(IMGDIR) if os.path.isdir(IMGDIR) else []):
        on_disk.setdefault(f.split(".")[0], f)
    kept = 0
    for rec in records:
        src = rec.pop("image_src", None)
        rec["image"] = None
        if not src:
            continue
        name = hashlib.sha1(src.encode()).hexdigest()[:16]
        if name in on_disk:              # already have it, don't refetch daily
            rec["image"] = "/featured/img/" + on_disk[name]
            kept += 1
            continue
        if not apply_changes:
            rec["image"] = "(would fetch)"
            kept += 1
            continue
        data, ext = fetch_image(src)
        if not data:
            continue
        with open(os.path.join(IMGDIR, name + ext), "wb") as f:
            f.write(data)
        on_disk[name] = name + ext
        rec["image"] = "/featured/img/" + name + ext
        kept += 1
    return kept


def prune_images(records, apply_changes):
    """Delete re-hosted photos no listing points at any more.

    Listings turn over constantly, so without this the directory only ever
    grows — a year of daily runs holding on to every apartment that was ever
    posted, none of which is ours to keep once the tile is gone.
    """
    if not apply_changes or not os.path.isdir(IMGDIR):
        return 0
    live = {os.path.basename(r["image"]) for r in records if r.get("image")}
    gone = 0
    for f in os.listdir(IMGDIR):
        if f not in live:
            try:
                os.remove(os.path.join(IMGDIR, f))
                gone += 1
            except OSError:
                pass
    return gone


def rank(records):
    """Order the tiles: a listing a visitor can act on beats one they can't.

    A specific rent outranks an income band, a photo outranks no photo, and
    among equals the agents rotate so one big board can't take every slot.
    """
    def score(r):
        s = 0
        if r["money_kind"] == "rent":
            s += 4
        elif r["money_kind"] == "income":
            s += 2
        if r.get("image"):
            s += 3
        # A tile whose button opens the apartment beats one that opens the board
        # and leaves the reader to find it again.
        if r.get("href_kind") == "listing":
            s += 2
        if r.get("borough"):
            s += 1
        if r.get("units"):
            s += 1
        return -s
    by_agent = {}
    for r in sorted(records, key=score):
        by_agent.setdefault(r["agent"], []).append(r)
    # round-robin across agents
    out, agents = [], list(by_agent)
    i = 0
    while any(by_agent.values()):
        a = agents[i % len(agents)]
        if by_agent[a]:
            out.append(by_agent[a].pop(0))
        i += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write featured.json + photos")
    ap.add_argument("--deploy", action="store_true",
                    help="scp the result to the droplet (run this from the laptop)")
    # The daily cron runs ON the droplet, where --deploy would be an scp to
    # itself over an ssh key it has no reason to hold. Same shape as
    # rerental_daily.py --out: write straight into the docroot instead.
    ap.add_argument("--out", help="write into this docroot directly (droplet-side)")
    ap.add_argument("--only", help="scan one agent (substring match)")
    ap.add_argument("--limit", type=int, default=60, help="max tiles to publish")
    args = ap.parse_args()

    global IMGDIR
    if args.out:
        IMGDIR = os.path.join(args.out, "featured", "img")

    pages = json.load(open(RERENTALS))["pages"]
    records, errors = sweep(pages, args.only)
    offices = office_addresses()
    records = [r for r in records if is_real_listing(r, offices)]
    kept_img = save_images(records, args.apply)
    records = rank(records)[:args.limit]
    dropped_img = prune_images(records, args.apply)

    today = datetime.date.today().isoformat()
    data = {"generated": today,
            "source": "HPD-approved marketing agents' own re-rental pages",
            "count": len(records), "listings": records}

    agents = {}
    for r in records:
        agents.setdefault(r["agent"], 0)
        agents[r["agent"]] += 1
    deep = sum(1 for r in records if r.get("href_kind") == "listing")
    print(f"{len(records)} listings from {len(agents)} agents · {kept_img} with a photo"
          + f" · {deep} link to the apartment, {len(records) - deep} to the agent's board"
          + (f" · {dropped_img} stale photo(s) removed" if dropped_img else ""))
    for a, n in sorted(agents.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3}  {a}")
    for a, e in errors.items():
        print(f"  ERR  {a}: {e}")
    money = {}
    for r in records:
        money[r["money_kind"]] = money.get(r["money_kind"], 0) + 1
    print("  money:", money)
    for r in records[:6]:
        amt = (f"{r['money_kind']} ${r['money_low']:,}" if r["money_kind"] else "no price")
        print(f"   · {r['address'][:44]:44} {amt:22} {r['agent'][:26]}")

    if not args.apply:
        print("\n(dry run — pass --apply to write featured.json and fetch photos)")
        return 0
    json.dump(data, open(OUT, "w"), indent=1, ensure_ascii=False)
    print(f"wrote {OUT}")
    if args.out:
        # Photos already went straight into the docroot via IMGDIR; only the
        # feed still has to be copied across from the checkout.
        with open(os.path.join(args.out, "featured.json"), "w") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        print(f"wrote {os.path.join(args.out, 'featured.json')}")
    if args.deploy:
        subprocess.run(["scp", "-q", OUT, DROPLET + "featured.json"], check=True)
        if os.path.isdir(IMGDIR):
            host, root = DROPLET.split(":", 1)
            # rsync creates only the last path component, so featured/ has to
            # exist already or the whole image sync fails on a fresh droplet.
            subprocess.run(["ssh", host, "mkdir", "-p", root + "featured/img"], check=True)
            # --delete so a photo pruned locally goes from the docroot too.
            subprocess.run(["rsync", "-az", "--delete", IMGDIR + "/",
                            DROPLET + "featured/img/"], check=True)
        print("deployed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
