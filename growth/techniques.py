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
import glob
import hashlib
import json
import os
import re
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

    def live_or_staged(self, relpath):
        """Is this path in the docroot, or will it be once this run rsyncs?

        A technique that links to a page another technique publishes cannot ask
        the docroot alone — the docroot only catches up after the driver rsyncs
        the staging dir across. Never true in a dry run, which stages nothing.
        Used so llms.txt never advertises a URL that would 404.
        """
        return (os.path.exists(os.path.join(self.docroot, relpath))
                or (not self.dry_run and os.path.exists(os.path.join(self.out, relpath))))

    # ---- page writing with honest lastmod

    def _url_for(self, relpath):
        return (SITE + "/" + relpath[:-len("index.html")] if relpath.endswith("index.html")
                else SITE + "/" + relpath)

    def unstage(self, relpath, url=None):
        """Forget a page this build published, so it stops being republished.

        The staging dir is never cleared and `deploy` is `rsync -a` with no
        --delete, so a file left in growth_out is pushed into the docroot again
        every single night — including over a copy another pipeline has since
        deployed. Any technique that publishes on another pipeline's behalf
        therefore has to be able to hand a page back: "the SEO build wins" is
        only true until the next rsync otherwise. Dropping the lastmod entry
        too is part of handing it back — the URL is no longer ours to list in
        our sitemap shard or to date.
        """
        if self.dry_run:
            return False
        url = url or self._url_for(relpath)
        removed = False
        try:
            os.remove(os.path.join(self.out, relpath))
            removed = True
        except OSError:
            pass
        lm = ledger.get_state("lastmod", {})
        if url in lm:
            del lm[url]
            ledger.set_state("lastmod", lm)
            removed = True
        return removed

    def write_page(self, relpath, html, url=None):
        """Write a page, tracking whether it is new / changed / identical.

        Only genuinely new or changed URLs are handed to IndexNow, and only
        changed pages get their <lastmod> bumped. Re-pinging unchanged URLs is
        how sites get their IndexNow key ignored.
        """
        url = url or self._url_for(relpath)
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
.faq-item{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.faq-item h3{font-size:15px;margin:0 0 4px}
.faq-item p{color:var(--ink2);font-size:14px;margin:0}
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


def _faq_html(pairs):
    """Render FAQ pairs as visible HTML matching the FAQPage JSON-LD.

    Structured data should describe what's actually on the page, not stand
    in for content that only exists in a hidden <script> block — and AI
    answer engines extract from rendered text, not JSON-LD, so an
    FAQPage schema with no visible counterpart earns neither.
    """
    items = "".join(
        f"<div class='faq-item'><h3>{_esc(q)}</h3><p>{_esc(a)}</p></div>"
        for q, a in pairs)
    return f"<h2>Frequently asked questions</h2><div class='faq'>{items}</div>"


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
        # The return leg of a reference that has only ever run one way: every
        # dated brief links here, nothing here linked back. Both sections are
        # orphans as of 2026-08-07, so this link buys nothing on its own — but
        # the crawl path added to the city browse hubs today reaches /section8/,
        # and this is what carries it the one further hop into /brief/. It is
        # deliberately NOT counted by t_crawl_paths: a pair of orphans linking
        # to each other is the orphan-cluster case that audit exists to catch,
        # and crediting it here would report both healthy the day they are not.
        + "<p class='sub'>What changed overnight: the <a href='/brief/'>daily brief</a> "
          "records which buildings came on and off this list each day.</p>"
        + SOI_NOTE
        + "<h2>All live listings, cheapest first</h2>"
        + _listing_table(rows)
        + "<div class='note'>Why this list is different: plenty of sites list voucher-friendly "
          "apartments, and plenty list rent-stabilized buildings. These are the ones that are "
          "<b>both</b> — a stabilized building means the rent is capped by the Rent Guidelines "
          "Board every year, so the apartment stays affordable after you move in. "
          "<a href='/'>Open the map</a> to see every stabilized building in the city.</div>"
        + _faq_html(SECTION8_FAQ))

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
    ]
    # The per-city guides by name, not just the hub. An answer engine asked
    # "is my apartment rent controlled in Los Angeles" needs the URL that
    # answers it, and the /guide/ hub in the docroot is written by the SEO
    # pipeline, which does not yet know these three pages exist. Listed only
    # when the page is actually live (or staged for this run's rsync) — a
    # citation map that advertises a 404 is worse than one that omits a page.
    for _city, _label in (("sf", "San Francisco"), ("la", "Los Angeles"),
                          ("dc", "Washington DC")):
        _rel = CITY_GUIDES[_city]
        if ctx.live_or_staged(_rel):
            lines.append(f"- Is my apartment rent controlled in {_label}? — what the city's rules "
                         f"cover, the main exemptions, and how to check an address: "
                         f"{SITE}/{_rel[:-len('index.html')]}")
    # The aggregate browse tier, on the same terms. An answer engine asked
    # "what rent-controlled housing is in the Mission" needs the page that
    # answers at neighborhood level; the map at /sf/ cannot be quoted.
    _hubs = [(c, l, f"{c}/buildings/index.html") for c, l in
             (("sf", "San Francisco, by neighborhood"), ("la", "Los Angeles, by ZIP code"),
              ("dc", "Washington DC, by neighborhood"))
             if ctx.live_or_staged(f"{c}/buildings/index.html")]
    if _hubs:
        lines += ["", "## Browse by area", ""]
        lines += [f"- {_label} — counts, unit sizes and what the city's rules cover for each "
                  f"area: {SITE}/{_c}/buildings/" for _c, _label, _rel in _hubs]
    lines += [
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


# Sitemaps in the docroot root that THIS build writes, and so carry a fresh
# mtime every night no matter what the separate SEO pipeline did. t_sitemap_daily
# writes sitemap-daily.xml outright and rewrites sitemap.xml to keep the daily
# shard's lastmod current. Neither can be used to date the SEO corpus
# (_seo_corpus_age); build_seo.py's own sitemap-main.xml / sitemap-<boro>.xml can.
GROWTH_OWNED_SITEMAPS = {"sitemap.xml", "sitemap-daily.xml"}


_SITEMAP_SHARD = re.compile(r"sitemap-[A-Za-z0-9_-]+\.xml")
_SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def _sitemap_covered(docroot):
    """Every URL already listed in a sitemap shard the SEO pipeline owns.

    Returns None — not an empty set — when the docroot has no readable sitemap
    index. The difference matters: an empty set means "the pipeline lists
    nothing", which would have this build list every page it knows about, and a
    missing index means "cannot tell", where the honest move is to change
    nothing. A dry run against a bare checkout takes the second path.
    """
    try:
        with open(os.path.join(docroot, "sitemap.xml")) as f:
            index = f.read()
    except OSError:
        return None
    covered = set()
    for loc in _SITEMAP_LOC.findall(index):
        name = loc.rsplit("/", 1)[-1]
        # Only ever open a file inside the docroot. sitemap.xml is generated,
        # but it is also web-served, and a <loc> should not be able to choose a
        # path for us. Our own shard is excluded — it is what we are rebuilding.
        if not _SITEMAP_SHARD.fullmatch(name) or name == "sitemap-daily.xml":
            continue
        try:
            with open(os.path.join(docroot, name)) as f:
                covered.update(_SITEMAP_LOC.findall(f.read()))
        except OSError:
            continue
    return covered


def t_sitemap_daily(ctx):
    """A dedicated sitemap for the daily-changing pages, plus any page in a
    family this build owns that no pipeline shard lists.

    The main sitemap is rebuilt monthly by build_seo.py and would otherwise
    never mention today's brief. Keeping the daily URLs in their own file means
    the monthly build and the daily build never fight over one another's output.

    The second half of that job was missing until 2026-08-17, and the gap had
    swallowed 252 pages. This shard was built purely from the lastmod state —
    the URLs THIS build wrote — and ctx.unstage() deletes a URL's lastmod entry
    when it hands a page back to the SEO pipeline, on the reasoning that "the
    URL is no longer ours to list". That reasoning holds only if the pipeline
    then lists it, and for the SF/LA/DC hub tier it does not: on 2026-08-17 the
    docroot held 103 DC, 112 LA and 37 SF hub pages while the docroot sitemaps
    carried exactly two URLs per city (/dc/ from sitemap-main.xml and
    /dc/buildings/ from this shard). The handover dropped them out of our
    sitemap and the pipeline's own shard never picked them up, so 252 finished
    pages sat in the docroot with no sitemap entry anywhere — and the URL
    Inspection sample that same morning came back "URL is unknown to Google" for
    80% of the URLs it read, never fetched at all.

    So the shard is now the union of two sets: URLs this build wrote (with the
    honest content-hash lastmod it tracks for them), and URLs in a family this
    build owns that are live in the docroot but absent from every pipeline
    shard. The second set is derived from the filesystem, never asserted: a page
    is listed only if it exists, dated by its own mtime rather than today, and
    it drops back out of this shard by itself on the day the pipeline starts
    listing it. No page is published to have a URL — these are already live.
    """
    lm = ledger.get_state("lastmod", {})

    def entry(u):
        """(changefreq, priority) for a URL the growth build published, else None."""
        if u == SITE + "/section8/":
            return ("daily", "0.9")
        if u.startswith(SITE + "/section8/"):
            return ("daily", "0.8")
        if u == SITE + "/brief/":
            return ("daily", "0.6")
        if u.startswith(SITE + "/brief/"):
            return ("daily", "0.4")
        # Cornerstone guides this build had to publish itself because the SEO
        # pipeline had not deployed them (t_city_guides). They appear in no
        # sitemap shard that pipeline owns, so without this line Google has no
        # crawl path to them at all. Declared monthly, not daily: they are
        # editorial pages and a sitemap that overstates change frequency is the
        # signal crawlers learn to discount.
        if u.startswith(SITE + "/guide/"):
            return ("monthly", "0.8")
        # The SF/LA/DC aggregate hub tier, for the same reason and on the same
        # terms (t_city_seo_expansion). Monthly: these summarise the SF Rent
        # Board inventory, the LA assessor roll and DC's RentRegistry, none of
        # which turn over nightly. Priorities match what build_seo.py assigns
        # them in its own shards, so nothing changes the day it deploys again.
        for _city, _rel in CITY_HUB_DIRS.items():
            if u == f"{SITE}/{_city}/buildings/":
                return ("monthly", "0.9")
            if u.startswith(f"{SITE}/{_rel}/"):
                return ("monthly", "0.7")
        return None

    daily = {u: v for u, v in lm.items() if entry(u)}

    # ---- pages in our families that are live but in nobody's sitemap
    # Enumerated from the docroot, so this can only ever list a page that really
    # exists. The globs are the families entry() knows how to price; anything
    # entry() would return None for is skipped even if a glob matched it.
    rescued = 0
    covered = _sitemap_covered(ctx.docroot)
    if covered is not None:
        globs = ["section8/index.html", "section8/*/index.html",
                 "brief/index.html", "brief/*/index.html",
                 "guide/index.html", "guide/*/index.html"]
        for _city, _rel in CITY_HUB_DIRS.items():
            globs += [f"{_city}/buildings/index.html", f"{_rel}/*/index.html"]
        for pattern in globs:
            for path in sorted(glob.glob(os.path.join(ctx.docroot, pattern))):
                rel = os.path.relpath(path, ctx.docroot)
                url = SITE + "/" + rel[:-len("index.html")]
                if url in daily or url in covered or not entry(url):
                    continue
                # The page's own mtime, not today. rsync -a preserves the source
                # mtime, so this is the date the deploying pipeline last wrote
                # the page — a real lastmod, and one that stays put on the nights
                # nothing changes. A shard that redates every page every night is
                # the signal crawlers learn to discount, which is the one thing
                # these pages cannot afford.
                try:
                    m = datetime.date.fromtimestamp(os.path.getmtime(path))
                except OSError:
                    continue
                today = datetime.date.fromisoformat(ledger.today())
                daily[url] = {"m": min(m, today).isoformat()}
                rescued += 1

    if not daily:
        return {"ok": False, "detail": "no daily pages written yet"}

    urls = "".join(
        f"<url><loc>{u}</loc><lastmod>{v['m']}</lastmod>"
        f"<changefreq>{entry(u)[0]}</changefreq><priority>{entry(u)[1]}</priority></url>"
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
        idx = re.sub(r"(<sitemap><loc>[^<]*sitemap-daily\.xml</loc><lastmod>)[^<]*(</lastmod>)",
                     rf"\g<1>{ledger.today()}\g<2>", idx)
        ctx.write_raw("sitemap.xml", idx)

    guides = sum(1 for u in daily if u.startswith(SITE + "/guide/"))
    hubs = sum(1 for u in daily if any(
        u == f"{SITE}/{c}/buildings/" or u.startswith(f"{SITE}/{r}/")
        for c, r in CITY_HUB_DIRS.items()))
    extra = ", ".join(x for x in (f"{guides} fallback-published guides" if guides else "",
                                  f"{hubs} city hub pages" if hubs else "") if x)
    # `rescued` is the number a future review needs, because it is the size of a
    # hole nothing else reports: pages live in the docroot that no sitemap listed
    # until this run. It should fall to 0 the day the SEO pipeline starts
    # emitting its own city shards, and a jump means the pipeline dropped a tier.
    note = ""
    if covered is None:
        note = " — could not read the docroot sitemap index, so listed only our own URLs"
    elif rescued:
        note = (f" — {rescued} of them live in the docroot but listed in no sitemap the SEO "
                f"pipeline owns, so they had no crawl path at all until this run")
    return {"ok": True, "urls": len(daily), "rescued": rescued,
            "detail": f"sitemap-daily.xml with {len(daily)} URLs"
                      + (f" (incl. {extra})" if extra else "") + note}


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
ANSWER_MARKER = "class='answer'"


def _answer_hub_families():
    """[(label, [globs relative to a docroot-shaped tree])] for every hub we publish.

    The NYC tier comes from build_seo.py's own pipeline; the SF/LA/DC tier is
    rendered by build_seo.city_hub_docs but deployed by this build
    (t_city_seo_expansion), and until 2026-08-09 it was not audited at all —
    "368 of 368 hub pages" was a green line covering 59% of the hub pages this
    site publishes, and it would have stayed green through a regression in the
    only tier whose deploy path still works.
    """
    fams = [("neighborhood", ["neighborhood/*/*/index.html"]),
            ("borough", ["borough/*/index.html"]),
            ("zip", ["zip/*/index.html"])]
    for city, rel in sorted(CITY_HUB_DIRS.items()):
        fams.append((f"{city} hub", [f"{rel}/*/index.html"]))
    # The browse hubs are one page per city, the highest-priority page in the
    # tier (0.9) and the page the guides, the other cities and the voucher
    # cross-link all point at. They carried no answer block until 2026-08-09.
    # Grouped under one label rather than three so the detail line stays
    # readable; glob has no brace expansion, hence the list.
    fams.append(("city browse hub",
                 [f"{c}/buildings/index.html" for c in sorted(CITY_HUB_DIRS)]))
    return fams


def t_hub_direct_answers(ctx):
    """Verify the hub pages actually carry their direct-answer block.

    The block is written by build_seo.py, not here, because that is what
    generates the hub pages. This technique exists so the ledger can hold the
    hypothesis and so the claim is checked against the live docroot every day
    rather than assumed — a generator change that silently drops the block
    would otherwise look identical to one that works.

    Pages this run stages are read from the staging dir when the docroot copy
    is behind, for the reason t_crawl_paths does the same: cmd_build runs every
    technique and rsyncs growth_out at the very end, so on the night a change
    to city_hub_docs ships, the docroot still holds the previous deploy and a
    docroot-only read would report the tier broken by its own fix. A staged
    page is never counted as healthy — it is reported separately and keeps ok
    False, because a block that exists only in growth_out is not one an answer
    engine can extract. It needs no staleness escalator of its own: these pages
    ride the same rsync as /section8/ and /brief/, and t_crawl_paths already
    escalates when that rsync stops landing.
    """
    import glob

    def has_block(root, rel):
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
                return ANSWER_MARKER in f.read()
        except OSError:
            return False

    counts, missing, pending = {}, [], []
    for label, patterns in _answer_hub_families():
        have = total = 0
        for pattern in patterns:
            for path in glob.glob(os.path.join(ctx.docroot, pattern)):
                rel = os.path.relpath(path, ctx.docroot)
                total += 1
                if has_block(ctx.docroot, rel):
                    have += 1
                elif not ctx.dry_run and has_block(ctx.out, rel):
                    pending.append(rel)
                elif len(missing) < 5:
                    missing.append(rel)
        counts[label] = (have, total)

    have = sum(h for h, _ in counts.values())
    total = sum(t for _, t in counts.values())
    if not total:
        return {"ok": False, "detail": "no hub pages found in the docroot — has the SEO build run?"}
    detail = ("answer block on " + f"{have:,} of {total:,} hub pages ("
              + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in counts.items()) + ")")
    if pending:
        shown = ", ".join(sorted(pending)[:5])
        detail += (f" — {len(pending)} awaiting this run's rsync, the block is in the page this "
                   f"run staged but not yet in the docroot: {shown}")
    if missing:
        detail += f" — missing e.g. {', '.join(missing)}"
    if have < total:
        return {"ok": False, "detail": detail, "pages": have}
    return {"ok": True, "detail": detail, "pages": have}


def _seo_corpus_age(docroot):
    """How stale the separately-built SEO corpus in the docroot is.

    The 47k-page corpus is built by build_seo.py in /root/dhcr-build and rsynced
    across by scripts/refresh_seo.sh; the daily growth build writes its own
    pages straight into the docroot. So "we shipped it" and "it is live" are
    different claims, and when a verifier below reports a page missing, the
    reader needs to know which one failed. rsync -a preserves mtimes, so the
    newest mtime in the corpus is the last time that pipeline wrote anything.

    Only files the SEO pipeline alone writes count as stamps — see
    GROWTH_OWNED_SITEMAPS. The first version of this globbed sitemap*.xml and
    excluded only sitemap-daily.xml, which left sitemap.xml in the set; but
    t_sitemap_daily rewrites sitemap.xml every night to refresh the daily
    shard's lastmod, so its mtime is always today and this always answered
    "0d ago". It reported a corpus written today on 2026-08-01 while the
    pipeline had in fact not deployed since 2026-07-29 — the opposite of the
    deploy signal it exists to give. Any new growth-written file in the docroot
    root must be added to that set, or this goes blind again.

    Returns (iso date, days old) or None when nothing recognisable is there.
    """
    import glob
    stamps = [p for p in glob.glob(os.path.join(docroot, "sitemap*.xml"))
              if os.path.basename(p) not in GROWTH_OWNED_SITEMAPS]
    # seo_guides.py writes the guide hub; nothing in the growth build touches it.
    stamps.append(os.path.join(docroot, "guide", "index.html"))
    newest = None
    for p in stamps:
        try:
            m = os.path.getmtime(p)
        except OSError:
            continue
        newest = m if newest is None else max(newest, m)
    if newest is None:
        return None
    when = datetime.datetime.fromtimestamp(newest, datetime.timezone.utc).date()
    return (when.isoformat(), (datetime.date.today() - when).days)


# Written by scripts/refresh_seo.sh at start and on exit — see the long comment
# there. It is the only thing that pipeline says about itself, and the docroot
# is the only place both it and this build can see.
SEO_STATUS_FILE = ".seo-build-status.json"

# Whitelist, because this record is copied into growth/last_run.json, which is
# committed to a public repo. A file that grew a field nobody reviewed here
# would be published unread; strings are truncated for the same reason.
SEO_STATUS_FIELDS = ("started", "at", "phase", "step", "rc", "head",
                     "changed_urls", "corpus_pages")

# The corpus has never been near this. A build that completes cleanly and writes
# a few hundred pages is a catastrophic failure that the docroot's mtime alone
# calls healthy — it deploys, so the corpus looks freshly written. Deliberately
# far below the real ~47,600 so this can only fire on an unambiguous break.
SEO_CORPUS_MIN_PAGES = 1000


def _seo_pipeline_status(docroot, now=None):
    """What refresh_seo.sh last said about its own run, or None if it never has.

    _seo_corpus_age() below answers "when did that pipeline last write?" from
    mtimes. It cannot answer "why did it stop?", and those are different
    questions with different owner actions: a cron that never fired, a
    build_seo.py that crashed, and an rsync that failed all look identical from
    a stale mtime. Between 2026-08-09 and 2026-08-12 the corpus went four days
    stale and no review could say which of the three it was.

    Returns a small dict with the raw fields plus a derived one-line `state`, or
    None when the file is absent (which now means only that the droplet is still
    running a refresh_seo.sh from before 2026-08-12 — it does not mean the
    pipeline is dead, and must not be read that way).
    """
    path = os.path.join(docroot, SEO_STATUS_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = json.loads(f.read(4096))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    rec = {}
    for k in SEO_STATUS_FIELDS:
        v = raw.get(k)
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            rec[k] = v
        elif isinstance(v, str):
            rec[k] = v[:64]

    hours = None
    try:
        at = datetime.datetime.fromisoformat(str(rec.get("at", "")).replace("Z", "+00:00"))
        now = now or datetime.datetime.now(datetime.timezone.utc)
        hours = (now - at).total_seconds() / 3600.0
    except ValueError:
        pass

    step, rc = rec.get("step", "?"), rec.get("rc")
    pages = rec.get("corpus_pages")
    if rec.get("phase") == "start":
        state = f"STARTED BUT NEVER FINISHED — died in step '{step}'"
    elif rc not in (0, None):
        state = f"FAILED rc={rc} in step '{step}'"
    elif isinstance(pages, (int, float)) and 0 < pages < SEO_CORPUS_MIN_PAGES:
        state = (f"completed, but built only {int(pages):,} pages — the corpus is "
                 f"normally ~47,600, so this deployed a truncated site")
    else:
        state = "ran clean"
    if hours is not None:
        # 04:10 nightly, read by the 05:40 build, so anything past ~26h is a
        # morning missed. Same shape as cron_liveness() for growth_run.sh.
        if hours > 26:
            state = f"NO RUN FOR {hours / 24:.1f} DAYS — cron, the host or the checkout. " + state
        rec["hours_ago"] = round(hours, 1)
    rec["state"] = state
    return rec


def _stale_note(docroot):
    """' — …' suffix naming when the SEO pipeline last wrote, or '' if unknown."""
    age = _seo_corpus_age(docroot)
    if not age:
        return ""
    when, days = age
    return f" — the docroot's SEO corpus was last written {when} ({days}d ago)"


CITY_GUIDES = {
    "sf": "guide/is-my-apartment-rent-controlled-san-francisco/index.html",
    "la": "guide/is-my-apartment-rent-controlled-los-angeles/index.html",
    "dc": "guide/is-my-apartment-rent-controlled-washington-dc/index.html",
}

# The coverage caveat each city guide is required to carry. These are not
# decoration: the LA layer is derived from assessor criteria and the SF layer is
# block-anonymized, and a guide that quietly loses its caveat while keeping its
# confident headline is worse than no guide. Checked against the built page every
# run, so an editorial change that drops one fails loudly instead of shipping.
GUIDE_CAVEATS = {
    "sf": "anonymized to the block",
    "la": "likely rso",
    "dc": "registration records",
}


# Marker embedded in any page this build published on the SEO pipeline's
# behalf. It answers the only question that matters when two pipelines can
# write the same path: who wrote the copy currently in the docroot. A page
# carrying it is ours and we keep it current; a page without it was written by
# the SEO build, and whether we may replace it is decided by
# _seo_page_is_current() below rather than by the marker alone.
# (Named FALLBACK_MARKER until 2026-08-03, when the city hub tier started
# using the same rule. The string itself has never changed — renaming it would
# have orphaned every page already published under it.)
FALLBACK_MARKER = "<!-- published by the daily growth build -->"

# refresh_seo.sh runs nightly at 04:10 UTC, before this build, so a corpus
# written yesterday is normal and one written two days ago has already missed a
# run. Same threshold report.py uses to call that pipeline stalled.
SEO_STALE_DAYS = 2


def _seo_page_is_current(live, ours, docroot):
    """Should a page the SEO pipeline deployed be left exactly as it is?

    Ownership used to be decided by FALLBACK_MARKER alone: a docroot page
    without our marker had been written by the SEO pipeline, so we never touched
    it again. That conflates two different claims — "that pipeline published
    this page once" and "that pipeline's copy is what the committed code
    renders" — and the gap between them silently strands real work.

    It already did. On 2026-08-09 a review added an extractable answer block and
    FAQ to build_seo.city_hub_docs(). The SEO pipeline had deployed the three
    city browse hubs on 2026-08-08, so from 08-09 on every nightly growth build
    re-rendered the improved page, saw no marker, said "hands off" and threw the
    render away. On 2026-08-11 t_hub_direct_answers still read "city browse hub
    0/3", and would have read it indefinitely: the only other path to the
    docroot, refresh_seo.sh, had not written since 08-08.

    So the test is content, not provenance. Identical bytes mean the two
    pipelines agree and the handover is real — nothing to do either way.
    Different bytes mean the live page is behind this checkout, and we take it
    over only once that pipeline has demonstrably missed a night. A pipeline
    still deploying daily therefore wins every disagreement and the two never
    fight over one file; when a stalled one catches up it rsyncs the same bytes
    we render, and the next run hands the page back on its own.

    `ours` is the unmarked render; `live` never carries the marker here. When
    the corpus cannot be dated at all we cannot prove that pipeline missed
    anything, so the SEO copy stands.
    """
    if live == ours:
        return True
    age = _seo_corpus_age(docroot)
    return age is None or age[1] < SEO_STALE_DAYS


def _publish_stranded_guides(ctx):
    """Publish any city guide the SEO pipeline has not deployed. Returns {city: state}.

    Why this exists. The SEO corpus is built by a second pipeline
    (/root/dhcr-build → build_seo.py → rsync) that this review agent cannot
    reach; the daily growth build is the one path from git to the docroot that
    demonstrably works. On 2026-08-02 the SEO pipeline had been writing the
    docroot nightly while running code from before 2026-07-29 — its checkout is
    not taking pushes — so the three city guides, the whole non-NYC editorial
    tier, had been finished and committed for four days and were live nowhere.
    Content stranded in git earns nothing.

    So this publishes them through the working channel, using build_seo's own
    renderer so the bytes match what the SEO build would have deployed. It is
    deliberately a fallback, not a takeover: a guide already in the docroot
    without our marker was written by the SEO pipeline, and we leave it alone.
    """
    import importlib
    try:
        bs = importlib.import_module("build_seo")
        guides = {g["slug"]: g for g in importlib.import_module("seo_guides").GUIDES}
    except Exception as e:                    # noqa: BLE001 - never break the build
        return {c: f"unavailable ({e.__class__.__name__})" for c in CITY_GUIDES}

    out = {}
    for city, rel in CITY_GUIDES.items():
        slug = rel.split("/")[1]
        g = guides.get(slug)
        if g is None:
            out[city] = "no such guide in seo_guides.GUIDES"
            continue
        path = os.path.join(ctx.docroot, rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                live = f.read()
        except OSError:
            live = None
        seo_owned = live is not None and FALLBACK_MARKER not in live
        # The guide links into /<city>/buildings/, which the same dead pipeline
        # owns. Only offer that link if the target is actually live.
        browse_ok = os.path.exists(os.path.join(ctx.docroot, city, "buildings", "index.html"))
        try:
            canonical, doc = bs.guide_page(g, browse_ok=browse_ok)
        except Exception as e:                # noqa: BLE001
            # A render failure is only this technique's problem when there is no
            # live copy behind it; the SEO pipeline's page still serves.
            out[city] = "seo" if seo_owned else f"render failed ({e.__class__.__name__})"
            continue
        if seo_owned and _seo_page_is_current(live, doc, ctx.docroot):
            # The real pipeline got there and its copy is what this code
            # renders. Hands off — and unstage our own copy: growth_out is
            # never cleared and deploy is rsync without --delete, so a leftover
            # would be pushed back over the SEO build's page every night and
            # this fallback would never end.
            out[city] = "seo"
            ctx.unstage(rel, url=SITE + "/" + rel[:-len("index.html")])
            continue
        doc = doc.replace("</body>", FALLBACK_MARKER + "</body>")
        if GUIDE_CAVEATS[city] not in doc.lower():
            # Never publish a guide that lost its coverage caveat — that is the
            # credibility bug this technique already fails the run over.
            out[city] = "caveat missing from render, not published"
            continue
        state, _url, _lm = ctx.write_page(rel, doc, url=canonical)
        out[city] = "growth-" + state
    return out


def t_city_guides(ctx):
    """Publish the SF / LA / DC guides if the SEO build hasn't, then verify them.

    The content lives in seo_guides.py and is rendered by build_seo.guide_page().
    Ownership is by marker (see _publish_stranded_guides): the SEO pipeline's
    copy always wins, and this only fills the gap when that pipeline has not
    deployed. The verification below still reads the docroot rather than what we
    just rendered, and the detail names which pipeline published each page —
    "3 of 3 live" would otherwise become a self-fulfilling reading the moment
    this technique started writing the files it checks.
    """
    published = _publish_stranded_guides(ctx)

    missing, uncaveated, ok = [], [], 0
    for city, rel in CITY_GUIDES.items():
        path = os.path.join(ctx.docroot, rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                html = f.read().lower()
        except OSError:
            # A page written this run is in the staging dir, not the docroot —
            # the driver rsyncs afterwards. Count it as live only if we really
            # wrote it (and never in a dry run, which writes nothing).
            if not ctx.dry_run and str(published.get(city, "")).startswith("growth-"):
                ok += 1
            else:
                missing.append(city)
            continue
        if GUIDE_CAVEATS[city] not in html:
            uncaveated.append(city)
            continue
        ok += 1

    by_us = sorted(c for c, s in published.items() if str(s).startswith("growth-"))
    verb = "would be published (dry run)" if ctx.dry_run else "published"
    note = (f" — {len(by_us)} {verb} by the daily growth build "
            f"({', '.join(by_us)}) because the SEO pipeline has not deployed them"
            + _stale_note(ctx.docroot)) if by_us else ""
    broken = sorted(f"{c}: {s}" for c, s in published.items()
                    if not str(s).startswith("growth-") and s != "seo")
    if broken:
        note += " — could not publish: " + "; ".join(broken)

    detail = f"{ok} of {len(CITY_GUIDES)} city guides live with their data caveat"
    if missing:
        return {"ok": False, "detail": detail + f" — missing: {', '.join(sorted(missing))}"
                                              + _stale_note(ctx.docroot) + note}
    if uncaveated:
        return {"ok": False,
                "detail": detail + f" — caveat text gone from: {', '.join(sorted(uncaveated))}" + note}
    return {"ok": not broken, "detail": detail + note, "pages": ok}


# Where the non-NYC browse tier lives in the docroot, and how many pages each
# city should have. Counts are a floor, not an assertion: a city gains a hub
# whenever a place crosses MIN_CITY_HUB records, so the check is ">= 1 and the
# browse hub exists", and the real count is reported for the review to read.
CITY_HUB_DIRS = {
    "sf": "sf/neighborhood",
    "la": "la/zip",
    "dc": "dc/neighborhood",
}


def _publish_stranded_city_hubs(ctx):
    """Publish any city hub page the SEO pipeline has not deployed.

    Returns {city: {"docs": [(kind, relpath)], "published": n, "seo": n,
                    "error": str|None}}.

    The same fallback as _publish_stranded_guides, for the tier underneath it.
    The guides were the three pages a reader lands on; these 255 are the pages
    that make the non-NYC data browsable at all, and on 2026-08-03 they had been
    finished and committed for five days while /root/dhcr-build refused to pull.
    Every one of them is an aggregate over data already in this repo, rendered
    by build_seo's own city_hub_docs() so the bytes match what that pipeline
    would have deployed.

    Ownership is by FALLBACK_MARKER, exactly as for the guides: a page in the
    docroot without it was written by the SEO build and we never touch it, so
    the day /root/dhcr-build starts pulling again this steps aside on its own.
    """
    import importlib
    try:
        bs = importlib.import_module("build_seo")
    except Exception as e:                        # noqa: BLE001 - never break the build
        err = f"build_seo unavailable ({e.__class__.__name__})"
        return {c: {"docs": [], "published": 0, "refreshed": 0, "seo": 0,
                    "handed_back": 0, "error": err}
                for c in CITY_HUB_DIRS}

    out = {}
    for city in CITY_HUB_DIRS:
        rec = {"docs": [], "published": 0, "refreshed": 0, "seo": 0,
               "handed_back": 0, "error": None}
        out[city] = rec
        # These pages are the contextual path into the city guide. Only offer
        # that link when the guide is live (or staged by t_city_guides earlier
        # this run) — the same rule the guides apply to their link back here.
        guide_ok = ctx.live_or_staged(CITY_GUIDES[city])
        try:
            docs = bs.city_hub_docs(city, guide_ok=guide_ok)
        except Exception as e:                    # noqa: BLE001
            rec["error"] = f"render failed ({e.__class__.__name__})"
            continue
        if not docs:
            # city_hub_docs returns nothing when the data is unreadable or no
            # place clears MIN_CITY_HUB. Publishing a near-empty tier to have
            # URLs is exactly what this build does not do.
            rec["error"] = "no page cleared the minimum record count"
            continue
        for d in docs:
            rec["docs"].append((d["kind"], d["relpath"]))
            path = os.path.join(ctx.docroot, d["relpath"])
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    live = f.read()
            except OSError:
                live = None
            if live is not None and FALLBACK_MARKER not in live:
                if _seo_page_is_current(live, d["html"], ctx.docroot):
                    # The real pipeline got there and its copy is what this
                    # code renders. Hands off — and drop our own stale copy, or
                    # the nightly rsync would push it back over the top and the
                    # handover would never actually happen.
                    rec["seo"] += 1
                    if ctx.unstage(d["relpath"], url=d["canonical"]):
                        rec["handed_back"] += 1
                    continue
                # Live, but behind the committed renderer, and that pipeline
                # has missed at least one night. Counted apart from the
                # stranded-page case: "published because it was missing" and
                # "republished because it was out of date" are different
                # failures of the SEO pipeline and the detail line says which.
                rec["refreshed"] += 1
            doc = d["html"].replace("</body>", FALLBACK_MARKER + "</body>")
            ctx.write_page(d["relpath"], doc, url=d["canonical"])
            rec["published"] += 1
    return out


def t_city_seo_expansion(ctx):
    """Publish the SF / LA / DC aggregate hub pages if the SEO build hasn't, then verify.

    Rendered by build_seo.py:city_hub_docs(). This was a checker until
    2026-08-03: the SEO build is a separate pipeline (/root/dhcr-build → rsync)
    and "shipped" and "live" are not the same claim, so the technique read the
    docroot rather than trusting the commit. It read ok=False for five straight
    days while that pipeline ran pre-2026-07-29 code, which is long enough to
    stop reporting a blocker and route around it.

    The verification still reads the filesystem rather than what we just
    rendered — every page is counted only if it is in the docroot or staged for
    this run's rsync — and the detail names which pipeline published each city,
    because "255 pages live" must not become a self-fulfilling reading now that
    this technique writes the files it checks.
    """
    import glob
    published = _publish_stranded_city_hubs(ctx)

    counts, browse, notes = {}, {}, []
    for city, rel in CITY_HUB_DIRS.items():
        rec = published[city]
        if rec["docs"]:
            counts[city] = sum(1 for k, p in rec["docs"]
                               if k == "place" and ctx.live_or_staged(p))
            browse[city] = any(k == "browse" and ctx.live_or_staged(p) for k, p in rec["docs"])
        else:
            # Nothing rendered (build_seo unimportable, or no data): fall back to
            # reporting what the docroot holds, which is what this check did
            # before it could publish.
            counts[city] = len(glob.glob(os.path.join(ctx.docroot, rel, "*", "index.html")))
            browse[city] = os.path.exists(os.path.join(ctx.docroot, city, "buildings", "index.html"))
        if rec["error"]:
            notes.append(f"{city}: {rec['error']}")

    by_us = {c: published[c]["published"] for c in published if published[c]["published"]}
    verb = "would be published (dry run)" if ctx.dry_run else "published"
    note = ""
    refreshed = sum(published[c]["refreshed"] for c in published)
    if by_us:
        # Counts here include each city's browse hub, so they read one higher
        # than the place-page counts above. Say so rather than leave a reader
        # to reconcile "sf 37" with "sf 38".
        why = ("the SEO pipeline has not deployed them" if refreshed < sum(by_us.values())
               else "the SEO pipeline is behind this checkout")
        note = (f" — {sum(by_us.values())} pages {verb} by the daily growth build, browse hubs "
                f"included ({', '.join(f'{c} {n}' for c, n in sorted(by_us.items()))}), because "
                f"{why}" + _stale_note(ctx.docroot))
        if refreshed:
            # The distinction a future review needs: these paths were already
            # live, so nothing looked missing, and the improvement was being
            # discarded nightly rather than waiting to be published.
            note += (f" — {refreshed} of them were live but stale, still serving the SEO "
                     f"pipeline's older render of the same page")
    handed_back = sum(published[c]["handed_back"] for c in published)
    if handed_back:
        # The one signal that /root/dhcr-build started pulling again. Worth a
        # line of its own: it is how a future review learns the fallback can go.
        note += (f" — handed {handed_back} pages back to the SEO pipeline, which has "
                 f"deployed its own copies")
    if notes:
        note += " — could not publish: " + "; ".join(sorted(notes))

    total = sum(counts.values())
    detail = "hub pages live: " + ", ".join(
        f"{c} {counts[c]}{'' if browse[c] else ' (no browse hub)'}" for c in sorted(counts))
    if total == 0:
        stale = os.path.exists(os.path.join(ctx.docroot, "guide", "index.html"))
        return {"ok": False,
                "detail": detail + (" — docroot has no city hub pages at all; the SEO rebuild "
                                    "has not deployed this change yet" + _stale_note(ctx.docroot)
                                    if stale else " — no SEO build output in the docroot") + note}
    missing = [c for c in counts if not counts[c] or not browse[c]]
    if missing:
        return {"ok": False,
                "detail": detail + f" — incomplete: {', '.join(sorted(missing))}" + note}
    return {"ok": not notes, "detail": detail + note, "pages": total + sum(browse.values())}


# ------------------------------------------------------- crawl-path auditing

# Pages that stand in for the whole site's link graph. Every page in a
# generated family shares one template, so a link present on one is present on
# all of them; reading a capped, sorted sample of each family answers the
# question in a few dozen file reads instead of 47,600. The cap is per family
# and the sample is sorted, so this is deterministic — two runs on an unchanged
# docroot read the same files and reach the same answer.
def _crawl_sources():
    """[(family label, glob relative to the docroot, how many to read)]."""
    src = [("home shell", "index.html", 1),
           ("guide hub", "guide/index.html", 1),
           ("nyc browse hub", "buildings/index.html", 1),
           ("borough hub", "borough/*/index.html", 5),
           ("zip hub", "zip/*/index.html", 8),
           ("neighborhood hub", "neighborhood/*/*/index.html", 8),
           ("building page", "building/*/*/index.html", 8)]
    for city, rel in CITY_HUB_DIRS.items():
        src += [(f"{city} shell", f"{city}/index.html", 1),
                (f"{city} browse hub", f"{city}/buildings/index.html", 1),
                (f"{city} hub page", f"{rel}/*/index.html", 8)]
    return src


def _crawl_link_audit(root, prefixes):
    """Which URL prefixes have a crawlable inbound link, and from which families.

    Returns ({prefix: {family labels}}, pages read).

    `root` is a docroot-shaped tree: either the live docroot or this run's
    staging dir, which mirrors the same layout.

    A page inside the prefix it is being scored for does not count as an
    inbound link. That exclusion is the whole point: the pages of one generated
    family link to each other, so counting those self-links would report a
    family as reachable at exactly the moment the family is collectively
    orphaned — the failure this exists to catch.
    """
    import glob
    found = {p: set() for p in prefixes}
    read = 0
    for label, pattern, cap in _crawl_sources():
        for path in sorted(glob.glob(os.path.join(root, pattern)))[:cap]:
            rel = os.path.relpath(path, root)
            own = "/" + (rel[:-len("index.html")] if rel.endswith("index.html") else rel)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    html = f.read()
            except OSError:
                continue
            read += 1
            for p in prefixes:
                if own.startswith(p):
                    continue
                if f'href="{p}' in html or f"href='{p}" in html:
                    found[p].add(label)
    return found, read


# How long a prefix may sit "linked in the staging dir but not in the docroot"
# before that stops being deploy lag and becomes a deploy failure. One night:
# cmd_build rsyncs at the end of the same run that stages the page, so a link
# staged today is live before tomorrow's audit reads the docroot.
STAGED_GRACE_DAYS = 1


def _staged_since(prefix, staged_now, dry_run):
    """First date this prefix was seen linked-in-staging-but-not-live, or None.

    The audit runs before the driver rsyncs, so the night a crawl-path fix
    ships through the growth build the docroot cannot possibly show it yet.
    That one-night lag and a broken rsync look identical in a single run's
    output, and telling them apart is the difference between "wait" and "the
    only deploy path left is dead" — so the first sighting is remembered.
    """
    seen = ledger.get_state("crawl_staged_since", {})
    if not staged_now:
        if prefix in seen and not dry_run:
            del seen[prefix]
            ledger.set_state("crawl_staged_since", seen)
        return None
    since = seen.get(prefix)
    if since is None:
        since = ledger.today()
        if not dry_run:
            seen[prefix] = since
            ledger.set_state("crawl_staged_since", seen)
    return since


def _staged_age(since):
    """Whole days between an ISO date and today, or 0 if unparseable."""
    try:
        d = datetime.date.fromisoformat(since)
    except (TypeError, ValueError):
        return 0
    return (datetime.date.today() - d).days


def t_crawl_paths(ctx):
    """Verify every section we publish is reachable by an internal link, not just a sitemap.

    Why this is a technique and not a note. On 2026-08-05 /section8/ had been
    live and rebuilt nightly for ten days, was in sitemap-daily.xml with an
    honest lastmod, was submitted to IndexNow every night, and had never once
    earned a Search Console impression — nor had /brief/. Meanwhile every URL
    that HAS served (131 building pages, 6 ZIP hubs, one neighborhood hub, and
    /sf/ /la/ /dc/) sits in the interlinked SEO corpus or is linked from the
    homepage nav. A grep of the corpus found the reason: nothing on this site
    linked to /section8/ or /brief/ at all. They were orphans, discoverable
    only from a sitemap, and current indexing guidance is consistent that
    Google treats a URL with no internal link as unimportant and may never
    index it however often it is submitted.

    So the rule this enforces: if an active technique claims a URL prefix, some
    page outside that prefix must link into it. The prefixes come from the
    ledger rather than a list here, so a technique added tomorrow is audited
    the night it goes live without anyone remembering to add it.

    Writes nothing. It scores the live docroot, which is deliberate — the fix
    for an orphaned section usually lives in the app shells, and this is how a
    review running on a bare checkout learns whether that fix ever deployed.
    It reads this run's staging dir too, but only ever to explain a docroot
    orphan ("the link is staged, the rsync has not happened yet"), never to
    call one healthy: a link that exists solely in growth_out is not a link
    Google can follow.
    """
    import glob
    claimed = {}
    for t in ledger.active():
        for p in t.get("prefixes") or []:
            claimed.setdefault(p, t["slug"])
    if not claimed:
        return {"ok": True, "detail": "no active technique claims a URL prefix"}

    # Only audit sections that exist. A prefix with nothing published under it
    # is not an orphan, it is unbuilt, and reporting the two the same way would
    # bury the one that can be fixed. Directories only: "/sf/buildings/" globs
    # to sf/buildings.min.json otherwise, and a section would read as built
    # because a data file happens to share its name.
    live = [p for p in claimed
            if any(os.path.isdir(m) for m in
                   glob.glob(os.path.join(ctx.docroot, p.strip("/").replace("/", os.sep) + "*")))]
    unbuilt = sorted(set(claimed) - set(live))
    if not live:
        return {"ok": False,
                "detail": "no claimed section exists in the docroot" + _stale_note(ctx.docroot)}

    found, read = _crawl_link_audit(ctx.docroot, live)
    if not read:
        return {"ok": False, "detail": "no docroot pages readable — has anything deployed?"}

    # Also audit the staging dir. cmd_build runs every technique first and
    # rsyncs growth_out at the very end, so the docroot this reads is the one
    # the PREVIOUS run deployed: a crawl-path fix that ships through the growth
    # build is guaranteed to read as orphaned on the night it lands. That is
    # exactly what happened on 2026-08-08 — the three city browse hubs carrying
    # the links to /section8/ and /brief/ were staged and rsynced by the same
    # run that reported both sections ORPHANED — and a reader has no way to
    # tell that from a fix that is simply wrong. Skipped in a dry run, which
    # stages nothing this run but may still hold a previous run's growth_out.
    staged = {p: set() for p in live}
    if not ctx.dry_run and os.path.isdir(ctx.out):
        staged, _ = _crawl_link_audit(ctx.out, live)

    orphaned = sorted(p for p in live if not found[p])
    for p in live:                     # linked in the docroot: forget any lag we recorded
        if found[p]:
            _staged_since(p, False, ctx.dry_run)
    pending = {p: _staged_since(p, bool(staged.get(p)), ctx.dry_run) for p in orphaned}
    pending = {p: s for p, s in pending.items() if s}
    stuck = sorted(p for p, s in pending.items() if _staged_age(s) > STAGED_GRACE_DAYS)
    dead = [p for p in orphaned if p not in pending]
    detail = (f"{len(live) - len(orphaned)} of {len(live)} published sections have an inbound "
              f"internal link ({read} docroot pages read)")
    # The unbuilt list can run to nine prefixes on a checkout with no corpus,
    # so it goes last: the orphan names are the finding and must not be pushed
    # off the end of a phone-width line by a list of things that are merely
    # absent.
    tail = f" — not built yet, not audited: {', '.join(unbuilt)}" if unbuilt else ""
    # A prefix whose only inbound link is on a page this run stages gets its own
    # sentence, naming the source page and how long it has been waiting. Within
    # the grace window that is ordinary deploy lag and the reader should wait
    # one night; past it, the growth build's own rsync is not landing, which is
    # the most serious finding this audit can produce — it is the last deploy
    # path from this repo into the docroot.
    def _pend(ps):
        return ", ".join(
            f"{p} ({claimed[p]}) ← {', '.join(sorted(staged[p]))}"
            f"{f', {_staged_age(pending[p])}d' if _staged_age(pending[p]) else ''}"
            for p in ps)

    if stuck:
        return {"ok": False, "pages": read,
                "detail": detail + " — STAGED BUT NOT DEPLOYED, the growth build's own rsync is "
                "not reaching the docroot: " + _pend(stuck)
                + (" — ORPHANED with no inbound link anywhere: "
                   + ", ".join(f"{p} ({claimed[p]})" for p in dead) if dead else "") + tail}
    if dead:
        # Say how old the corpus is, because "still orphaned" has two very
        # different causes and the reader cannot tell them apart otherwise: the
        # fix is wrong, or the fix has not deployed. The inbound links now live
        # in build_seo.py's hub tier (VOUCHER_XLINK), which reaches the docroot
        # only when refresh_seo.sh runs — and on 2026-08-06 that pipeline had
        # not written for 5 days. Without this the next review re-derives the
        # deploy gap from scratch, which has already cost one cycle.
        return {"ok": False, "pages": read,
                "detail": detail + " — ORPHANED, reachable only from sitemap-daily.xml: "
                + ", ".join(f"{p} ({claimed[p]})" for p in dead)
                + _stale_note(ctx.docroot) + tail
                + (" — awaiting this run's rsync: " + _pend(sorted(pending)) if pending else "")}
    if pending:
        return {"ok": False, "pages": read,
                "detail": detail + " — awaiting this run's rsync, linked from a page staged "
                "minutes ago and not yet in the docroot: " + _pend(sorted(pending))
                + " — this audit reads the docroot before the deploy, so expect it to clear "
                "on the next run" + tail}
    # Name where the link comes from when there is exactly one source family:
    # a single thread is the one worth knowing about before it breaks.
    thin = sorted(f"{p} ← {next(iter(found[p]))}" for p in live if len(found[p]) == 1)
    if thin:
        detail += " — single inbound source: " + ", ".join(thin)
    return {"ok": True, "detail": detail + tail, "pages": read}


REGISTRY = {
    "city_guides": t_city_guides,
    "city_seo_expansion": t_city_seo_expansion,
    "hub_direct_answers": t_hub_direct_answers,
    "fresh_section8": t_fresh_section8,
    "daily_brief": t_daily_brief,
    "llms_txt": t_llms_txt,
    "sitemap_daily": t_sitemap_daily,
    "crawl_paths": t_crawl_paths,
    "indexnow": t_indexnow,
}

# Order matters: content first, then the audits of that content, then the
# sitemap that lists it, then the ping that announces it. crawl_paths runs after
# the content techniques so it audits what they published, and before indexnow
# so a run that is about to submit an orphan says so in the same log.
#
# hub_direct_answers is an audit and was mis-slotted at position 3, ahead of the
# two techniques that publish the pages it audits. It reads the docroot and
# falls back to ctx.out for pages this run staged but has not rsynced yet — and
# that fallback could never fire for the city hub tier, because nothing had been
# staged when it ran. So the audit reported LAST night's docroot as though it
# were tonight's result. That is not cosmetic: two consecutive reviews
# (2026-08-09, 2026-08-11) predicted "3 awaiting this run's rsync" from reading
# the fallback, got a flat "missing dc/la/sf buildings/index.html" instead, and
# the 08-09 one spent its follow-up chasing a staging bug that did not exist.
# Moved after city_guides and city_seo_expansion, which is where an audit
# belongs.
ORDER = ["fresh_section8", "daily_brief", "city_guides", "city_seo_expansion",
         "hub_direct_answers", "llms_txt", "sitemap_daily", "crawl_paths", "indexnow"]
