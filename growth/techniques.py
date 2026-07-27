#!/usr/bin/env python3
"""The executable growth techniques.

Every technique is a function named `t_<slug>` taking a Context and returning a
dict describing what it did. The slug matches the ledger record, so the ledger
alone decides what runs — flipping a technique to "retired" stops it without a
code change, which is what lets review.py prune autonomously.

A technique must be:
  * idempotent — it runs every day, and a re-run the same day changes nothing
  * honest — it never fabricates data, and never publishes an empty page just
    to have a URL to submit
  * attributable — it declares URL prefixes so metrics.py can tell whether it
    actually earned traffic
"""
import datetime
import hashlib
import json
import os
import statistics
import urllib.request

from . import ledger

SITE = "https://findacrib.com"

# Search engines that consume IndexNow. Google does not participate; it
# re-crawls from sitemap <lastmod>, which is why lastmod stays honest below.
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"

BORO_NAME = {"M": "Manhattan", "Bk": "Brooklyn", "Q": "Queens",
             "Bx": "the Bronx", "SI": "Staten Island"}
BORO_SLUG = {"M": "manhattan", "Bk": "brooklyn", "Q": "queens",
             "Bx": "bronx", "SI": "staten-island"}


# --------------------------------------------------------------- the context

class Context:
    """Everything a technique needs: paths, loaded data, and page writing.

    `out` is the staging dir (mirrors the docroot layout); the driver rsyncs it
    across afterwards. Nothing here writes to the live docroot directly.
    """

    def __init__(self, build_dir, docroot, dry_run=False, log=print):
        self.build_dir = build_dir
        self.docroot = docroot
        self.out = os.path.join(build_dir, "growth_out")
        self.dry_run = dry_run
        self.log = log
        self.new_urls = []        # brand-new URLs created this run
        self.changed_urls = []    # URLs whose content actually changed
        self._buildings = None
        self._by_bbl = None
        self._s8 = None

    # ---- data (lazy; buildings.min.json is 16 MB)

    def _load(self, name):
        for base in (self.docroot, self.build_dir):
            p = os.path.join(base, name)
            if os.path.exists(p):
                with open(p) as f:
                    return json.load(f)
        raise FileNotFoundError(f"{name} not found in {self.docroot} or {self.build_dir}")

    @property
    def buildings(self):
        if self._buildings is None:
            self._buildings = self._load("buildings.min.json")
        return self._buildings

    @property
    def by_bbl(self):
        if self._by_bbl is None:
            self._by_bbl = {str(b["bbl"]): b for b in self.buildings}
        return self._by_bbl

    @property
    def s8(self):
        if self._s8 is None:
            self._s8 = self._load("s8.json")
        return self._s8

    # ---- page writing with honest lastmod

    def write_page(self, relpath, html, url=None):
        """Write a page, tracking whether it is new / changed / identical.

        Only genuinely new or changed URLs are handed to IndexNow, and only
        changed pages get their <lastmod> bumped. Re-pinging unchanged URLs is
        how sites get their IndexNow key ignored.
        """
        url = url or (SITE + "/" + relpath[:-len("index.html")] if relpath.endswith("index.html")
                      else SITE + "/" + relpath)
        h = hashlib.sha1(html.encode("utf-8")).hexdigest()
        lm = ledger.get_state("lastmod", {})
        prev = lm.get(url)
        state = "same"
        if prev is None:
            state = "new"
            self.new_urls.append(url)
        elif prev.get("h") != h:
            state = "changed"
            self.changed_urls.append(url)

        if state == "same":
            lastmod = prev["m"]
        else:
            lastmod = ledger.today()

        if not self.dry_run:
            full = os.path.join(self.out, relpath)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(html)
            lm[url] = {"h": h, "m": lastmod}
            ledger.set_state("lastmod", lm)
        return state, url, lastmod

    def write_raw(self, relpath, text):
        if self.dry_run:
            return
        full = os.path.join(self.out, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)


# ------------------------------------------------------------------ shell/UI

def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _slugify(s):
    import re
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-") or "x"


def _titlecase_addr(a):
    return " ".join(w.capitalize() if not w.isdigit() else w for w in (a or "").split())


def _bld_url(b):
    return f"/building/{BORO_SLUG.get(b['b'], 'nyc')}/{_slugify(b.get('a'))}-{b['bbl']}/"


CSS = """
:root{--ink:#111;--ink2:#5a5f6a;--line:#e3e6ec;--bg:#f7f8fa;--accent:#1a56db}
*{box-sizing:border-box}
body{margin:0;font:16px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:var(--ink);background:var(--bg)}
header.site,footer.site{max-width:960px;margin:0 auto;padding:16px 20px}
header.site{border-bottom:1px solid var(--line);font-size:14px}
header.site a{color:var(--accent);text-decoration:none}
.brand{font-weight:700;color:var(--ink)!important}
main{max-width:960px;margin:0 auto;padding:20px}
h1{font-size:28px;line-height:1.25;margin:.2em 0 .3em}
h2{font-size:20px;margin:1.4em 0 .4em}
.sub{color:var(--ink2);font-size:15px;margin:0 0 18px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.stat{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.stat b{display:block;font-size:24px;line-height:1.1}
.stat span{color:var(--ink2);font-size:13px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);font-size:14px;vertical-align:top}
th{background:#fbfcfd;font-weight:600;color:var(--ink2)}
tr:last-child td{border-bottom:0}
td a{color:var(--accent)}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;background:#e7f3ec;color:#136c3a;border:1px solid #bfe0cc;white-space:nowrap}
.crumbs{font-size:14px;color:var(--ink2);margin-bottom:6px}
.crumbs a{color:var(--accent);text-decoration:none}
.note{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:14px 0;font-size:14px;color:var(--ink2)}
.cols{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:6px;margin:10px 0}
.cols a{color:var(--accent);text-decoration:none;font-size:14px}
footer.site{border-top:1px solid var(--line);margin-top:36px;color:var(--ink2);font-size:13px}
.scroll{overflow-x:auto}
"""

TRACK = """<script src="/config.js"></script>
<script>
(function(){try{
  if(navigator.webdriver||/bot|crawl|spider|slurp|headless|lighthouse|prerender|facebookexternal/i.test(navigator.userAgent))return;
  if(!window.SUPABASE_URL||!window.SUPABASE_ANON_KEY)return;
  var m=document.cookie.match(/(?:^|;\\s*)fac_vid=([\\w-]+)/),vid=m?m[1]:null;
  if(!vid){try{vid=localStorage.getItem('fac_vid')}catch(e){}}
  if(!vid)vid=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():'v'+Date.now().toString(36)+Math.random().toString(36).slice(2);
  try{localStorage.setItem('fac_vid',vid)}catch(e){}
  var tok=null,uid=null;
  try{
    var ref=window.SUPABASE_URL.split('//')[1].split('.')[0];
    var s=JSON.parse(localStorage.getItem('sb-'+ref+'-auth-token'));
    if(s&&s.access_token&&(s.expires_at||0)*1000>Date.now()+60000){tok=s.access_token;uid=(s.user&&s.user.id)||null}
  }catch(e){}
  fetch(window.SUPABASE_URL+'/rest/v1/visits',{method:'POST',keepalive:true,
    headers:{apikey:window.SUPABASE_ANON_KEY,'Authorization':'Bearer '+(tok||window.SUPABASE_ANON_KEY),
             'Content-Type':'application/json','Prefer':'return=minimal'},
    body:JSON.stringify({visitor_id:vid,user_id:uid,path:location.pathname+location.search,referrer:document.referrer||null})});
}catch(e){}})();
</script>"""


def _page(title, desc, canonical, body, jsonld=None):
    ld = ""
    if jsonld:
        blocks = jsonld if isinstance(jsonld, list) else [jsonld]
        ld = "".join('<script type="application/ld+json">%s</script>' % json.dumps(b) for b in blocks)
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
<link rel="canonical" href="{canonical}">
<link rel="icon" href="/favicon.ico" sizes="any">
<meta property="og:type" content="website"><meta property="og:site_name" content="Find A Crib">
<meta property="og:title" content="{_esc(title)}"><meta property="og:description" content="{_esc(desc)}">
<meta property="og:url" content="{canonical}"><meta property="og:image" content="{SITE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<style>{CSS}</style>{ld}</head><body>
<header class="site"><a class="brand" href="/">🏠 Find A Crib</a> &nbsp;·&nbsp;
<a href="/section8/">Voucher listings</a> &nbsp;·&nbsp;
<a href="/buildings/">All neighborhoods</a> &nbsp;·&nbsp;
<a href="/guide/">Guides</a></header>
<main>{body}</main>
<footer class="site">Live voucher listings via AffordableHousing.com; rent-stabilized status from the
NYC DHCR registration files; owner, violation and complaint data from NYC HPD Open Data.
A building's rent-stabilized status reflects DHCR registration and is not a guarantee that a
specific unit is available, stabilized, or still listed.
&copy; Find A Crib. <a href="/">Open the interactive map →</a></footer>
{TRACK}
</body></html>"""


def _breadcrumb(items):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": u}
                                for i, (n, u) in enumerate(items)]}


def _dataset_jsonld(name, description, url, date_modified, spatial, item_count):
    """A conservative Dataset record — factual fields only, no license claim
    (the site has never stated a data license, so asserting one would be a
    fabrication schema.org markup makes machine-readable, not a harmless one).
    """
    return {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": name, "description": description, "url": url,
        "dateModified": date_modified,
        "creator": {"@type": "Organization", "name": "Find A Crib", "url": SITE + "/"},
        "spatialCoverage": {"@type": "Place", "name": spatial},
        "variableMeasured": ["asking rent", "unit count", "accepts housing voucher",
                              "rent-stabilization status"],
        "isBasedOn": "https://www.affordablehousing.com/",
        "distribution": {"@type": "DataDownload", "encodingFormat": "text/html", "contentUrl": url},
    }


def _faq_jsonld(pairs):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a}}
                           for q, a in pairs]}


SECTION8_FAQ = [
    ("Does the absence of an “accepts vouchers” tag mean this apartment refuses Section 8?",
     "No. The tag only appears when the landlord said so in their listing. Source-of-income "
     "discrimination is illegal in New York City, so its absence never means vouchers are refused."),
    ("What makes this different from other Section 8 apartment lists?",
     "Every building shown is independently confirmed as registered rent-stabilized with NY State "
     "DHCR, not just marked voucher-friendly. A stabilized building means the rent is capped by the "
     "Rent Guidelines Board every year, so the apartment stays affordable after you move in."),
]


# ----------------------------------------------------------- voucher listings

def _live_listings(ctx):
    """Join the nightly AffordableHousing.com feed onto our building records.

    Returns [{bbl, addr, boro, boro_slug, nb, zip, n, price, url, b8, bld_url}]
    for listings we can actually place on a known rent-stabilized building.
    Unmatched BBLs are dropped rather than rendered without an address.
    """
    avail = (ctx.s8 or {}).get("avail") or {}
    rows = []
    for bbl, v in avail.items():
        b = ctx.by_bbl.get(str(bbl))
        if not b:
            continue
        rows.append({
            "bbl": str(bbl),
            "addr": _titlecase_addr(b.get("a")),
            "boro": b.get("b"),
            "boro_name": BORO_NAME.get(b.get("b"), ""),
            "boro_slug": BORO_SLUG.get(b.get("b"), "nyc"),
            "nb": b.get("nb") or "",
            "zip": b.get("z") or "",
            "units": b.get("u"),
            "n": v.get("n") or 1,
            "price": v.get("p"),
            "url": v.get("url"),
            "b8": bool(v.get("b8")),
        })
    rows.sort(key=lambda r: (r["price"] is None, r["price"] or 0))
    return rows


def _listing_table(rows, show_boro=True):
    head = ("<tr><th>Building</th>" + ("<th>Borough</th>" if show_boro else "")
            + "<th>Neighborhood</th><th>From</th><th>Listings</th><th></th></tr>")
    out = []
    for r in rows:
        price = f"${r['price']:,}/mo" if r.get("price") else "—"
        tag = ' <span class="tag">accepts vouchers</span>' if r["b8"] else ""
        boro_td = f"<td>{_esc(r['boro_name'])}</td>" if show_boro else ""
        out.append(
            f"<tr><td><a href='{_bld_url({'b': r['boro'], 'a': r['addr'], 'bbl': r['bbl']})}'>"
            f"{_esc(r['addr'])}</a>{tag}</td>{boro_td}"
            f"<td>{_esc(r['nb'])}</td><td>{price}</td><td>{r['n']}</td>"
            f"<td><a href='{_esc(r['url'])}' rel='nofollow noopener' target='_blank'>View listing →</a></td></tr>")
    return f"<div class='scroll'><table>{head}{''.join(out)}</table></div>"


def _stats_block(rows):
    prices = [r["price"] for r in rows if r.get("price")]
    med = int(statistics.median(prices)) if prices else None
    cheapest = min(prices) if prices else None
    total = sum(r["n"] for r in rows)
    b8 = sum(1 for r in rows if r["b8"])
    cells = [
        (f"{len(rows):,}", "rent-stabilized buildings with live listings"),
        (f"{total:,}", "individual units listed"),
        (f"${med:,}" if med else "—", "median asking rent"),
        (f"${cheapest:,}" if cheapest else "—", "cheapest listing"),
        (f"{b8:,}", "explicitly accepting vouchers"),
    ]
    return "<div class='stats'>" + "".join(
        f"<div class='stat'><b>{v}</b><span>{_esc(l)}</span></div>" for v, l in cells) + "</div>"


SOI_NOTE = (
    "<div class='note'><b>Source-of-income discrimination is illegal in New York City.</b> "
    "A landlord may not refuse you because you pay with a Section 8 voucher, CityFHEPS, or any "
    "other housing subsidy. The absence of an “accepts vouchers” tag here only means the landlord "
    "did not say so in their listing — it never means vouchers are refused. If a landlord turns you "
    "away over a voucher, you can file with the "
    "<a href='https://www.nyc.gov/site/cchr/about/report-discrimination.page' rel='nofollow noopener' "
    "target='_blank'>NYC Commission on Human Rights</a>.</div>")


def t_fresh_section8(ctx):
    """Daily-rebuilt voucher-listing pages: /section8/ and /section8/<borough>/.

    This is the only data on the site that genuinely changes every day (the
    AffordableHousing.com feed refreshes nightly at 04:15 UTC), so it is the one
    honest reason to give crawlers a daily visit. Search intent here is high and
    commercial: "section 8 apartments nyc", "apartments that accept vouchers
    brooklyn". Our differentiator is the cross-reference — every listing shown
    sits in a building we know is rent-stabilized.
    """
    rows = _live_listings(ctx)
    if len(rows) < 10:
        return {"ok": False, "detail": f"only {len(rows)} matched listings — refusing to publish a thin page"}

    updated = ctx.s8.get("avail_updated")
    when = (datetime.datetime.fromtimestamp(updated, datetime.timezone.utc).strftime("%B %-d, %Y")
            if updated else ledger.today())

    made = []

    # ---- NYC hub
    by_boro = {}
    for r in rows:
        by_boro.setdefault(r["boro"], []).append(r)

    boro_links = "".join(
        f"<a href='/section8/{BORO_SLUG[k]}/'>{_esc(BORO_NAME[k])} ({len(v)})</a>"
        for k, v in sorted(by_boro.items(), key=lambda kv: -len(kv[1])) if k in BORO_SLUG)

    body = (
        f"<h1>Section 8 &amp; voucher-friendly apartments in NYC — updated {_esc(when)}</h1>"
        f"<p class='sub'>Every building below is <b>registered rent-stabilized with DHCR</b> "
        f"and has at least one apartment listed right now on AffordableHousing.com, the site "
        f"NYCHA and HPD point voucher holders to. Rebuilt daily from the overnight feed.</p>"
        + _stats_block(rows)
        + f"<div class='cols'>{boro_links}</div>"
        + SOI_NOTE
        + "<h2>All live listings, cheapest first</h2>"
        + _listing_table(rows)
        + "<div class='note'>Why this list is different: plenty of sites list voucher-friendly "
          "apartments, and plenty list rent-stabilized buildings. These are the ones that are "
          "<b>both</b> — a stabilized building means the rent is capped by the Rent Guidelines "
          "Board every year, so the apartment stays affordable after you move in. "
          "<a href='/'>Open the map</a> to see every stabilized building in the city.</div>")

    lastmod = ctx.s8.get("avail_updated")
    date_modified = (datetime.datetime.fromtimestamp(lastmod, datetime.timezone.utc)
                     .strftime("%Y-%m-%d") if lastmod else ledger.today())
    jsonld = [
        _breadcrumb([("Home", SITE + "/"), ("Voucher listings", SITE + "/section8/")]),
        {"@context": "https://schema.org", "@type": "ItemList",
         "name": "Rent-stabilized NYC buildings with live voucher listings",
         "numberOfItems": len(rows),
         "itemListElement": [
             {"@type": "ListItem", "position": i + 1,
              "name": f"{r['addr']}, {r['boro_name']}",
              "url": SITE + _bld_url({'b': r['boro'], 'a': r['addr'], 'bbl': r['bbl']})}
             for i, r in enumerate(rows[:50])]},
        _dataset_jsonld(
            "Rent-stabilized NYC buildings with live Section 8 / voucher listings",
            f"{len(rows)} NYC buildings registered rent-stabilized with DHCR that currently have an "
            f"apartment listed on AffordableHousing.com, refreshed nightly.",
            SITE + "/section8/", date_modified, "New York City", len(rows)),
        _faq_jsonld(SECTION8_FAQ),
    ]
    st, url, _ = ctx.write_page(
        "section8/index.html",
        _page(f"Section 8 apartments in NYC — {len(rows)} rent-stabilized buildings listed now",
              f"{len(rows)} rent-stabilized NYC buildings with apartments listed for voucher holders "
              f"right now. Updated daily. Median asking rent and direct listing links by borough.",
              SITE + "/section8/", body, jsonld))
    made.append((st, url))

    # ---- one page per borough
    for k, brows in by_boro.items():
        if k not in BORO_SLUG or len(brows) < 3:
            continue
        name = BORO_NAME[k]
        slug = BORO_SLUG[k]
        disp = name if name.startswith("the ") else name
        crumbs = (f"<div class='crumbs'><a href='/'>Home</a> › "
                  f"<a href='/section8/'>Voucher listings</a> › {_esc(disp)}</div>")
        bbody = (
            crumbs
            + f"<h1>Section 8 apartments in {_esc(disp)} — updated {_esc(when)}</h1>"
            + f"<p class='sub'>{len(brows)} rent-stabilized {_esc(disp)} buildings have an apartment "
              f"listed for voucher holders right now.</p>"
            + _stats_block(brows) + SOI_NOTE
            + _listing_table(brows, show_boro=False)
            + f"<div class='note'><a href='/borough/{slug}/'>Every rent-stabilized building in "
              f"{_esc(disp)} →</a></div>")
        bjsonld = [
            _breadcrumb([("Home", SITE + "/"), ("Voucher listings", SITE + "/section8/"),
                         (disp, f"{SITE}/section8/{slug}/")]),
            _dataset_jsonld(
                f"Rent-stabilized {disp} buildings with live Section 8 / voucher listings",
                f"{len(brows)} {disp} buildings registered rent-stabilized with DHCR that currently "
                f"have an apartment listed on AffordableHousing.com, refreshed nightly.",
                f"{SITE}/section8/{slug}/", date_modified, disp, len(brows)),
        ]
        st, url, _ = ctx.write_page(
            f"section8/{slug}/index.html",
            _page(f"Section 8 apartments in {disp} — {len(brows)} stabilized buildings listed now",
                  f"Rent-stabilized buildings in {disp} with apartments listed for Section 8 and "
                  f"other voucher holders right now. Updated daily.",
                  f"{SITE}/section8/{slug}/", bbody, bjsonld))
        made.append((st, url))

    counts = {}
    for st, _ in made:
        counts[st] = counts.get(st, 0) + 1
    return {"ok": True, "pages": len(made), "states": counts,
            "detail": f"{len(rows)} buildings across {len(by_boro)} boroughs",
            "listings": len(rows)}


def t_daily_brief(ctx):
    """A dated daily brief at /brief/<YYYY-MM-DD>/ plus the archive at /brief/.

    Each brief is a genuine dated record of the voucher market: what came on,
    what came off, and where. It only publishes when there is real movement to
    report, so the archive stays a data series rather than filler.
    """
    rows = _live_listings(ctx)
    if len(rows) < 10:
        return {"ok": False, "detail": f"only {len(rows)} matched listings — no brief published"}

    date = ledger.today()
    today_set = {r["bbl"] for r in rows}
    prev = ledger.get_state("brief_prev", {})
    prev_set = set(prev.get("bbls") or [])
    prev_date = prev.get("date")

    added = [r for r in rows if r["bbl"] not in prev_set] if prev_set else []
    removed = sorted(prev_set - today_set) if prev_set else []

    if prev_set and not added and not removed:
        ledger.set_state("brief_prev", {"date": date, "bbls": sorted(today_set)})
        return {"ok": True, "skipped": True,
                "detail": "no movement since yesterday — no brief published (avoids filler)"}

    by_boro = {}
    for r in rows:
        by_boro.setdefault(r["boro"], []).append(r)
    boro_rows = "".join(
        f"<tr><td><a href='/section8/{BORO_SLUG[k]}/'>{_esc(BORO_NAME[k])}</a></td>"
        f"<td>{len(v)}</td><td>{sum(x['n'] for x in v)}</td>"
        f"<td>{('$%s' % format(int(statistics.median([x['price'] for x in v if x['price']])), ',')) if [x for x in v if x['price']] else '—'}</td></tr>"
        for k, v in sorted(by_boro.items(), key=lambda kv: -len(kv[1])) if k in BORO_SLUG)

    delta = ""
    if prev_set:
        delta = (f"<p class='sub'>Since {_esc(prev_date or 'the previous brief')}: "
                 f"<b>{len(added)}</b> building{'s' if len(added) != 1 else ''} newly listed, "
                 f"<b>{len(removed)}</b> no longer listed.</p>")
    else:
        delta = "<p class='sub'>First brief — this is the opening snapshot of the series.</p>"

    body = (
        f"<div class='crumbs'><a href='/'>Home</a> › <a href='/brief/'>Daily briefs</a> › {_esc(date)}</div>"
        f"<h1>NYC rent-stabilized voucher listings — {_esc(date)}</h1>"
        + delta
        + _stats_block(rows)
        + "<h2>By borough</h2>"
        + f"<div class='scroll'><table><tr><th>Borough</th><th>Buildings listed</th>"
          f"<th>Units listed</th><th>Median asking</th></tr>{boro_rows}</table></div>"
        + (("<h2>Newly listed today</h2>" + _listing_table(added)) if added else "")
        + f"<div class='note'>This is a dated snapshot. For the current list, see "
          f"<a href='/section8/'>today's voucher listings</a>.</div>")

    brief_jsonld = [
        _breadcrumb([("Home", SITE + "/"), ("Daily briefs", SITE + "/brief/"),
                     (date, f"{SITE}/brief/{date}/")]),
        _dataset_jsonld(
            f"NYC rent-stabilized voucher listing snapshot — {date}",
            f"Dated snapshot of {len(rows)} NYC buildings registered rent-stabilized with DHCR that "
            f"had an apartment listed on AffordableHousing.com on {date}.",
            f"{SITE}/brief/{date}/", date, "New York City", len(rows)),
    ]
    st, url, _ = ctx.write_page(
        f"brief/{date}/index.html",
        _page(f"NYC rent-stabilized voucher listings — {date}",
              f"Daily snapshot for {date}: {len(rows)} rent-stabilized NYC buildings with apartments "
              f"listed for voucher holders, {len(added)} newly listed, by borough.",
              f"{SITE}/brief/{date}/", body, brief_jsonld))

    # ---- archive index
    archive = ledger.get_state("brief_archive", [])
    entry = {"date": date, "buildings": len(rows), "added": len(added), "removed": len(removed)}
    archive = [a for a in archive if a["date"] != date] + [entry]
    archive.sort(key=lambda a: a["date"], reverse=True)
    ledger.set_state("brief_archive", archive[:400])

    arows = "".join(
        f"<tr><td><a href='/brief/{a['date']}/'>{a['date']}</a></td><td>{a['buildings']}</td>"
        f"<td>{a.get('added', '—')}</td><td>{a.get('removed', '—')}</td></tr>"
        for a in archive[:180])
    abody = (
        "<div class='crumbs'><a href='/'>Home</a> › Daily briefs</div>"
        "<h1>Daily briefs: the NYC voucher + rent-stabilized market</h1>"
        "<p class='sub'>A dated record of how many rent-stabilized NYC buildings had apartments "
        "listed for voucher holders each day, and what changed. Built from the overnight "
        "AffordableHousing.com feed.</p>"
        f"<div class='scroll'><table><tr><th>Date</th><th>Buildings listed</th><th>Newly listed</th>"
        f"<th>Delisted</th></tr>{arows}</table></div>")
    ctx.write_page("brief/index.html",
                   _page("Daily briefs — NYC rent-stabilized voucher listings",
                         "A dated daily record of rent-stabilized NYC buildings with apartments "
                         "listed for Section 8 and other voucher holders.",
                         SITE + "/brief/", abody,
                         _breadcrumb([("Home", SITE + "/"), ("Daily briefs", SITE + "/brief/")])))

    ledger.set_state("brief_prev", {"date": date, "bbls": sorted(today_set)})
    return {"ok": True, "detail": f"brief {date}: {len(added)} added, {len(removed)} removed",
            "state": st, "url": url, "added": len(added), "removed": len(removed)}


def t_llms_txt(ctx):
    """llms.txt + explicit AI-crawler permissions + a Dataset record.

    AI answer engines already send us traffic (visits carry
    utm_source=chatgpt.com). They cite sources they can parse cheaply and
    attribute confidently, so we hand them a plain-text map of what this site
    knows, refreshed with live counts.
    """
    nyc = len(ctx.buildings)
    rows = _live_listings(ctx)

    def city_count(name):
        try:
            with open(os.path.join(ctx.docroot, name, "buildings.min.json")) as f:
                return len(json.load(f))
        except Exception:
            return None

    sf, la, dc = city_count("sf"), city_count("la"), city_count("dc")

    lines = [
        "# Find A Crib",
        "",
        "> A property-level map of rent-stabilized and rent-controlled housing in the United",
        "> States. Coverage is limited to cities whose governments publish data at the",
        "> individual-property level; everywhere else, no such list exists publicly.",
        "",
        f"Last updated: {ledger.today()}",
        "",
        "## Coverage",
        "",
        f"- New York City — {nyc:,} rent-stabilized buildings registered with NY State DHCR "
        f"(2024 building files), all five boroughs. Authoritative registry. https://findacrib.com/",
    ]
    if sf:
        lines.append(f"- San Francisco — {sf:,} block-sides from the SF Rent Board Housing "
                     f"Inventory (owner-reported, anonymized to the block). https://findacrib.com/sf/")
    if la:
        lines.append(f"- Los Angeles — {la:,} parcels meeting LAHD's RSO criteria, derived from "
                     f"LA County Assessor rolls. Labelled \"likely RSO\", not an official list. "
                     f"https://findacrib.com/la/")
    if dc:
        lines.append(f"- Washington DC — {dc:,} properties registered with DHCD as holding "
                     f"rent-controlled units, from RentRegistry public exports. "
                     f"https://findacrib.com/dc/")
    lines += [
        "",
        "## What each building record contains",
        "",
        "Address, BBL/parcel id, coordinates, neighborhood, ZIP, year built, unit count,",
        "registered owner and managing agent, open and closed HPD violations by severity",
        "class, HPD complaint history, and whether the building was recently advertised.",
        "",
        "## Live listings",
        "",
        f"- Voucher-friendly listings, refreshed nightly: {len(rows):,} rent-stabilized NYC "
        f"buildings currently have an apartment listed on AffordableHousing.com. "
        f"https://findacrib.com/section8/",
        "- Dated daily snapshots of that market: https://findacrib.com/brief/",
        "",
        "## Guides",
        "",
        "- Plain-English explainers on rent stabilization, succession rights, overcharge",
        "  complaints, and how to check a specific apartment: https://findacrib.com/guide/",
        "",
        "## Data provenance",
        "",
        "- NY: NY State Homes and Community Renewal (DHCR) rent-stabilized building files, 2024",
        "- NY: NYC HPD Open Data — registrations, contacts, violations, complaints",
        "- NY: NYC PLUTO for coordinates; NTA 2020 for neighborhoods",
        "- SF: DataSF gdc7-dmcn, SF Rent Board Housing Inventory",
        "- LA: LA County Assessor parcel rolls filtered by LAHD RSO criteria",
        "- DC: DC DHCD RentRegistry public data exports",
        "",
        "## Important caveats to repeat when citing this data",
        "",
        "- Rent-stabilized status reflects a building's registration. It does not guarantee",
        "  that a particular unit is stabilized, available, or currently listed.",
        "- The Los Angeles layer is derived from assessor criteria, not an official RSO list.",
        "- San Francisco data is anonymized to the block, not the individual address.",
        "- Source-of-income discrimination is illegal in New York City; the absence of an",
        "  \"accepts vouchers\" tag never means vouchers are refused.",
        "",
        "## Contact",
        "",
        "- Developer API: https://findacrib.com/developers/",
        "- Terms: https://findacrib.com/terms.html · Privacy: https://findacrib.com/privacy.html",
        "",
    ]
    ctx.write_raw("llms.txt", "\n".join(lines))

    # robots.txt — name the AI crawlers explicitly. `User-agent: *` already
    # allows them, but several operators only honour a named group, and an
    # explicit Allow for Google-Extended keeps us eligible for AI Overviews.
    sitemaps = ["sitemap.xml", "sitemap-daily.xml"]
    bots = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User",
            "anthropic-ai", "PerplexityBot", "Perplexity-User", "Google-Extended",
            "Applebot", "Applebot-Extended", "CCBot", "Bingbot", "Amazonbot", "meta-externalagent"]
    robots = ["User-agent: *", "Allow: /", ""]
    for b in bots:
        robots += [f"User-agent: {b}", "Allow: /", ""]
    robots += [f"Sitemap: {SITE}/{s}" for s in sitemaps] + [""]
    ctx.write_raw("robots.txt", "\n".join(robots))

    return {"ok": True, "detail": f"llms.txt ({len(lines)} lines), robots.txt naming {len(bots)} AI crawlers",
            "cities": {"nyc": nyc, "sf": sf, "la": la, "dc": dc}}


def t_sitemap_daily(ctx):
    """A dedicated sitemap for the daily-changing pages.

    The main sitemap is rebuilt monthly by build_seo.py and would otherwise
    never mention today's brief. Keeping the daily URLs in their own file means
    the monthly build and the daily build never fight over one another's output.
    """
    lm = ledger.get_state("lastmod", {})
    daily = {u: v for u, v in lm.items()
             if u.startswith(SITE + "/section8/") or u.startswith(SITE + "/brief/")}
    if not daily:
        return {"ok": False, "detail": "no daily pages written yet"}

    def prio(u):
        if u == SITE + "/section8/":
            return "0.9"
        if u.startswith(SITE + "/section8/"):
            return "0.8"
        if u == SITE + "/brief/":
            return "0.6"
        return "0.4"

    urls = "".join(
        f"<url><loc>{u}</loc><lastmod>{v['m']}</lastmod>"
        f"<changefreq>daily</changefreq><priority>{prio(u)}</priority></url>"
        for u, v in sorted(daily.items()))
    ctx.write_raw("sitemap-daily.xml",
                  '<?xml version="1.0" encoding="UTF-8"?>'
                  '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                  f'{urls}</urlset>')

    # Splice sitemap-daily.xml into the live sitemap index without disturbing
    # the shards build_seo.py owns.
    idx_path = os.path.join(ctx.docroot, "sitemap.xml")
    try:
        with open(idx_path) as f:
            idx = f.read()
    except FileNotFoundError:
        idx = None
    if idx and "sitemap-daily.xml" not in idx:
        entry = (f"<sitemap><loc>{SITE}/sitemap-daily.xml</loc>"
                 f"<lastmod>{ledger.today()}</lastmod></sitemap>")
        idx = idx.replace("</sitemapindex>", entry + "</sitemapindex>")
        ctx.write_raw("sitemap.xml", idx)
    elif idx:
        # keep the index's lastmod for our shard current
        import re
        idx = re.sub(r"(<sitemap><loc>[^<]*sitemap-daily\.xml</loc><lastmod>)[^<]*(</lastmod>)",
                     rf"\g<1>{ledger.today()}\g<2>", idx)
        ctx.write_raw("sitemap.xml", idx)

    return {"ok": True, "urls": len(daily), "detail": f"sitemap-daily.xml with {len(daily)} URLs"}


def t_indexnow(ctx):
    """Submit genuinely new or changed URLs to IndexNow (Bing, Yandex, Seznam, Naver).

    Deliberately does NOT resubmit unchanged URLs. IndexNow is a trust-based
    channel: publishers who re-ping static pages get their key quietly ignored,
    which would cost us the one indexing lever that needs no account at all.
    Google does not consume IndexNow — it re-crawls from sitemap <lastmod>.
    """
    urls = sorted(set(ctx.new_urls) | set(ctx.changed_urls))
    if not urls:
        return {"ok": True, "submitted": 0, "detail": "nothing new or changed today"}

    key = None
    for p in (os.path.join(ctx.build_dir, "indexnow.key"),
              os.path.join(ctx.docroot, "indexnow.key")):
        if os.path.exists(p):
            key = open(p).read().strip()
            break
    if not key:
        # fall back to the key file already hosted at the docroot
        import glob
        for p in glob.glob(os.path.join(ctx.docroot, "*.txt")):
            base = os.path.basename(p)[:-4]
            if len(base) == 32 and all(c in "0123456789abcdef" for c in base):
                key = base
                break
    if not key:
        return {"ok": False, "detail": "no IndexNow key found"}

    payload = {"host": "findacrib.com", "key": key,
               "keyLocation": f"{SITE}/{key}.txt",
               "urlList": urls[:10000]}
    if ctx.dry_run:
        return {"ok": True, "submitted": 0, "detail": f"dry run — would submit {len(urls)} URLs",
                "urls": urls[:20]}
    req = urllib.request.Request(
        INDEXNOW_ENDPOINT, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return {"ok": True, "submitted": len(urls), "http": r.status,
                "detail": f"submitted {len(urls)} URLs → HTTP {r.status}"}
    except Exception as e:
        return {"ok": False, "submitted": 0, "detail": f"IndexNow submit failed: {e}"}


# The registry the driver walks. Slug → function.
REGISTRY = {
    "fresh_section8": t_fresh_section8,
    "daily_brief": t_daily_brief,
    "llms_txt": t_llms_txt,
    "sitemap_daily": t_sitemap_daily,
    "indexnow": t_indexnow,
}

# Order matters: content first, then the sitemap that lists it, then the ping
# that announces it.
ORDER = ["fresh_section8", "daily_brief", "llms_txt", "sitemap_daily", "indexnow"]
