#!/usr/bin/env python3
"""findacrib.com/rent-report/ — the NYC rent-stabilized rent report + index.

Runs on the droplet every morning after the Zumper scrape (03:30 UTC; cron in
deploy/cron-rentmap-report). Three jobs, in order:

1. ARCHIVE today's scrape. listings_zumper.json is overwritten every night and
   listings.json is a sticky master whose prices never refresh, so neither can
   show a change over time. Each run copies the fresh scrape's {bbl: [price,
   beds]} into HISTORY/YYYY-MM-DD.json. That archive IS the index: nothing
   before the first archived day (2026-09-19) exists anywhere.
2. MEASURE. Asking rents come from the fresh scrape only (never the sticky
   master). A building's number is the LOWEST advertised rent in it that day,
   so bedroom cuts use only buildings advertising a single unit size. The
   index compares the SAME buildings with the SAME unit sizes 7 and 30 days
   apart, so a month when only cheap buildings list does not read as a drop.
3. DEMAND, from our own usage events: which neighborhoods people looked at in
   the last 30 days. Counted in distinct visitors, and a row is only published
   when at least MIN_VISITORS different visitors are behind it (the privacy
   policy promises this). No email, account, query text or alert income is
   ever read here.

Writes DOCROOT/rent-report/index.html and rent-report.csv (aggregates only;
the raw archive stays private in HISTORY).

  python3 build_rent_report.py                  # archive + build
  python3 build_rent_report.py --no-archive     # rebuild the page only
  python3 build_rent_report.py --no-demand      # skip the events query

Needs SUPABASE_SERVICE_ROLE_KEY in the environment for the demand section
(the cron sources /root/findacrib-api/.env); without it that section is left
out and the rest still builds.
"""
import argparse
import csv
import datetime
import html
import io
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

DOCROOT = os.environ.get("GROWTH_DOCROOT", "/var/www/rent-map")
HISTORY = os.environ.get("RENT_HISTORY_DIR", "/var/lib/findacrib/rent_history")
SUPABASE_URL = "https://dbaifotzwlxjvsxjohjt.supabase.co"
SITE = "https://findacrib.com"

MIN_BORO = 15        # listings needed before a borough/bedroom median is shown
MIN_NB = 5           # ... a neighborhood median
MIN_INDEX = 30       # matched buildings needed before an index change is shown
MIN_VISITORS = 10    # distinct visitors behind any published demand row

BORO = {"1": "Manhattan", "2": "Bronx", "3": "Brooklyn", "4": "Queens", "5": "Staten Island"}
BEDS = {0: "Studio", 1: "1 bedroom", 2: "2 bedrooms", 3: "3 bedrooms", 4: "4+ bedrooms"}


def load(name, default=None):
    try:
        with open(os.path.join(DOCROOT, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def money(n):
    return f"${n:,.0f}"


def pct(x):
    return f"{x:+.1f}%"


def e(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- 1. archive

def snapshot(scrape):
    prices, beds = scrape.get("prices", {}), scrape.get("beds", {})
    return {bbl: [p, beds.get(bbl, [])] for bbl, p in prices.items()}


def archive(snap, day):
    os.makedirs(HISTORY, exist_ok=True)
    path = os.path.join(HISTORY, f"{day}.json")
    with open(path + ".tmp", "w") as f:
        json.dump(snap, f, separators=(",", ":"))
    os.replace(path + ".tmp", path)


def history():
    out = {}
    if not os.path.isdir(HISTORY):
        return out
    for name in sorted(os.listdir(HISTORY)):
        if name.endswith(".json") and len(name) == 15:
            try:
                with open(os.path.join(HISTORY, name)) as f:
                    out[name[:10]] = json.load(f)
            except (OSError, ValueError):
                pass
    return out


def change(hist, today, days, slack):
    """Median same-building change vs the archived day closest to `days` ago
    (within ±slack). None when there is no such day or too few matches."""
    t = datetime.date.fromisoformat(today)
    best = None
    for d in hist:
        gap = (t - datetime.date.fromisoformat(d)).days
        if abs(gap - days) <= slack and (best is None or abs(gap - days) < abs(best[1] - days)):
            best = (d, gap)
    if not best:
        return None
    then, now = hist[best[0]], hist[today]
    moves = [(now[b][0] - then[b][0]) / then[b][0] * 100
             for b in now if b in then and then[b][0] and sorted(now[b][1]) == sorted(then[b][1])]
    if len(moves) < MIN_INDEX:
        return {"since": best[0], "n": len(moves), "too_few": True}
    return {"since": best[0], "n": len(moves), "median": statistics.median(moves),
            "up": sum(m > 0.5 for m in moves), "down": sum(m < -0.5 for m in moves),
            "flat": sum(-0.5 <= m <= 0.5 for m in moves)}


# ---------------------------------------------------------------- 2. measure

def measure(snap, bldg, fmr):
    by_boro, by_beds, by_nb = defaultdict(list), defaultdict(list), defaultdict(list)
    under_fmr = over_fmr = 0
    for bbl, (price, beds) in snap.items():
        b = bldg.get(bbl, {})
        by_boro[BORO.get(bbl[:1], "Other")].append(price)
        if b.get("nb"):
            by_nb[(b["nb"], BORO.get(bbl[:1], ""))].append(price)
        if len(beds) == 1:
            by_beds[beds[0]].append(price)
            f = fmr.get(b.get("z") or "")
            if f and beds[0] < len(f) and f[beds[0]]:
                if price <= f[beds[0]]:
                    under_fmr += 1
                else:
                    over_fmr += 1
    return by_boro, by_beds, by_nb, under_fmr, over_fmr


# ---------------------------------------------------------------- 3. demand

def demand(bldg, since_days=30):
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        return None
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = urllib.parse.urlencode({"select": "visitor_id,bbl:props->>bbl", "event": "eq.building_view",
                                "created_at": f"gte.{since}", "order": "id.asc"})
    seen, start, page = defaultdict(set), 0, 1000
    while True:
        req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/events?{q}", headers={
            "apikey": key, "Authorization": f"Bearer {key}",
            "Range-Unit": "items", "Range": f"{start}-{start + page - 1}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.load(r)
        for row in rows:
            b = bldg.get(row.get("bbl") or "")
            if b and b.get("nb") and row.get("visitor_id"):
                seen[(b["nb"], BORO.get(row["bbl"][:1], ""))].add(row["visitor_id"])
        if len(rows) < page or start > 400_000:
            break
        start += page
    visitors = set().union(*seen.values()) if seen else set()
    rows = sorted(((k, len(v)) for k, v in seen.items() if len(v) >= MIN_VISITORS), key=lambda x: -x[1])
    return {"rows": rows[:15], "visitors": len(visitors)}


# ---------------------------------------------------------------- page

CSS = """
:root{--ink:#1a1a1a;--ink2:#5d6570;--line:#e4e4e4;--head:#163c47;--bg:#fff;--soft:#f5f7f8;--up:#b3261e;--down:#1e7a46}
*{box-sizing:border-box}body{margin:0;font:17px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:var(--ink);background:var(--bg)}
header.site{background:var(--head);color:#fff;padding:14px 16px;font-weight:700}header.site a{color:#fff;text-decoration:none}
main{max-width:860px;margin:0 auto;padding:24px 16px 60px}h1{font-size:32px;line-height:1.2;margin:0 0 6px}h2{font-size:22px;margin:36px 0 8px}
.note{color:var(--ink2);font-size:15px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:20px 0}
.tile{background:var(--soft);border-radius:8px;padding:14px 16px}.tile b{display:block;font-size:28px;line-height:1.2}.tile span{color:var(--ink2);font-size:14px}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:10px 0;font-size:16px}td,th{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left}
th{font-size:14px;color:var(--ink2);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.up{color:var(--up)}.down{color:var(--down)}a{color:#1f5f8b}ul{padding-left:20px}li{margin:4px 0}
footer.site{border-top:1px solid var(--line);padding:18px 16px;color:var(--ink2);font-size:14px;text-align:center}
"""


def table(head, rows, numeric=()):
    th = "".join(f'<th class="n">{e(h)}</th>' if i in numeric else f"<th>{e(h)}</th>" for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(f'<td class="n">{c}</td>' if i in numeric else f"<td>{c}</td>"
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="wrap"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def index_line(label, c):
    if not c:
        return f"<li><b>{label}:</b> first reading once the archive is old enough.</li>"
    if c.get("too_few"):
        return (f"<li><b>{label}:</b> only {c['n']} buildings listed on both {e(c['since'])} and today with the "
                f"same unit sizes — fewer than {MIN_INDEX}, so no figure yet.</li>")
    cls = "up" if c["median"] > 0 else "down" if c["median"] < 0 else ""
    return (f'<li><b>{label}:</b> median asking rent <span class="{cls}">{pct(c["median"])}</span> in the '
            f"{c['n']} buildings listed on both {e(c['since'])} and today — {c['up']} up, {c['down']} down, "
            f"{c['flat']} unchanged.</li>")


def build(today, snap, hist, bldg, fmr, hcr, hc, featured, s8, dem):
    by_boro, by_beds, by_nb, under, over = measure(snap, bldg, fmr)
    allp = [p for p, _ in snap.values()]
    month = datetime.date.fromisoformat(today).strftime("%B %Y")
    first_day = min(hist) if hist else today
    wk, mo = change(hist, today, 7, 1), change(hist, today, 30, 3)

    open_lotteries = [l for l in (hc or {}).get("lotteries", []) if (l.get("closes") or "") >= today]
    hcr_open = [l for l in (hcr or {}).get("listings", []) if l.get("status") == "Open"]
    rerentals = (featured or {}).get("count", 0)
    vouchers = len((s8 or {}).get("avail", {}))

    tiles = [
        (money(statistics.median(allp)) if allp else "—", f"median lowest asking rent, {len(allp)} buildings"),
        (money(statistics.median(by_beds[1])) if len(by_beds[1]) >= MIN_BORO else "—", "median 1-bedroom"),
        (f"{round(100 * under / (under + over))}%" if under + over >= MIN_BORO else "—",
         "at or under HUD Fair Market Rent"),
        (str(len(open_lotteries) + len(hcr_open) + rerentals), "lotteries, waitlists & re-rentals open today"),
    ]
    tiles_html = "".join(f'<div class="tile"><b>{e(v)}</b><span>{e(l)}</span></div>' for v, l in tiles)

    boro_rows = []
    for name in ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]:
        ps = by_boro.get(name, [])
        med = money(statistics.median(ps)) if len(ps) >= MIN_BORO else f"too few (<{MIN_BORO})"
        boro_rows.append([e(name), med, str(len(ps))])

    bed_rows = []
    for k in sorted(by_beds):
        ps = by_beds[k]
        if len(ps) >= MIN_BORO:
            bed_rows.append([e(BEDS.get(k, k)), money(statistics.median(ps)),
                             f"{money(min(ps))} – {money(max(ps))}", str(len(ps))])

    nbs = sorted(((k, statistics.median(v), len(v)) for k, v in by_nb.items() if len(v) >= MIN_NB), key=lambda x: x[1])
    nb_rows = lambda xs: [[e(f"{nb}, {boro}"), money(m), str(n)] for (nb, boro), m, n in xs]

    pipeline = table(["What's open", "Count", "Where"], [
        ["Housing Connect lotteries accepting applications", str(len(open_lotteries)), '<a href="https://housingconnect.nyc.gov/">NYC Housing Connect</a>'],
        ["State (HCR) lotteries & waitlists open", str(len(hcr_open)), "HousingSearch.ny.gov"],
        ["Re-rentals posted by HPD-approved marketing agents", str(rerentals), '<a href="/marketing-agents/">Agents\' own pages</a>'],
        ["Listings that accept housing vouchers", str(vouchers), '<a href="/section8/">Section 8 & CityFHEPS</a>'],
    ], numeric=(1,))

    if dem and dem["rows"]:
        supply = Counter((bldg.get(b, {}).get("nb"), BORO.get(b[:1], "")) for b in snap)
        demand_html = (f"<p>Neighborhoods whose rent-stabilized buildings Find A Crib visitors opened most in the last "
                       f"30 days ({dem['visitors']:,} visitors in total). Counted in people, not clicks; a neighborhood "
                       f"appears only when at least {MIN_VISITORS} different people looked.</p>"
                       + table(["Neighborhood", "People who looked", "Buildings advertising today"],
                               [[e(f"{nb}, {boro}"), f"{n:,}", str(supply.get((nb, boro), 0))] for (nb, boro), n in dem["rows"]],
                               numeric=(1, 2)))
    else:
        demand_html = (f"<p class=\"note\">Not enough visitors yet to publish this without identifying anyone "
                       f"(each row needs at least {MIN_VISITORS} different people).</p>")

    desc = (f"NYC rent-stabilized rent report for {month}: median lowest asking rent {tiles[0][0]} across "
            f"{len(allp)} rent-stabilized buildings advertising today, by borough, bedroom and neighborhood, "
            f"plus open lotteries and re-rentals. Updated daily.")
    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": "NYC Rent-Stabilized Rent Report", "description": desc,
          "url": f"{SITE}/rent-report/", "dateModified": today, "temporalCoverage": f"{first_day}/{today}",
          "spatialCoverage": "New York, NY", "creator": {"@type": "Organization", "name": "Find A Crib", "url": SITE},
          "isAccessibleForFree": True,
          "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv",
                            "contentUrl": f"{SITE}/rent-report/rent-report.csv"}]}

    page = f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NYC Rent-Stabilized Rent Report — {e(month)} | Find A Crib</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{SITE}/rent-report/">
<meta property="og:title" content="NYC Rent-Stabilized Rent Report — {e(month)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{SITE}/rent-report/"><meta property="og:image" content="{SITE}/og-image.png">
<link rel="icon" href="/favicon.ico" sizes="any">
<script type="application/ld+json">{json.dumps(ld)}</script>
<style>{CSS}</style></head><body>
<header class="site"><a href="/">🏠 Find A Crib</a></header>
<main>
<h1>NYC Rent-Stabilized Rent Report</h1>
<p class="note">{e(month)} · updated {e(today)} from that morning's listings · <a href="rent-report.csv">download the numbers (CSV)</a></p>
<p>What apartments in New York's rent-stabilized buildings are being advertised for right now, where the affordable openings are, and — from Find A Crib's own visitors — where people are looking.</p>
<div class="tiles">{tiles_html}</div>

<h2>Rent index</h2>
<p>The same buildings, with the same unit sizes, compared with themselves — so a week when only cheaper buildings advertise doesn't look like rents fell.</p>
<ul>{index_line("Last 7 days", wk)}{index_line("Last 30 days", mo)}</ul>
<p class="note">Tracking began {e(first_day)}.</p>

<h2>Asking rents by borough</h2>
{table(["Borough", "Median lowest asking rent", "Buildings advertising"], boro_rows, numeric=(1, 2))}

<h2>By apartment size</h2>
<p class="note">Only buildings advertising a single unit size, so each price belongs to that size.</p>
{table(["Size", "Median", "Range", "Buildings"], bed_rows, numeric=(1, 3)) if bed_rows else '<p class="note">Too few single-size listings today.</p>'}
<p>{f"<b>{round(100 * under / (under + over))}%</b> of those are priced at or under HUD's Small Area Fair Market Rent for their ZIP code and size — a rough guide to what a housing voucher can reach." if under + over >= MIN_BORO else ""}</p>

<h2>Cheapest and priciest neighborhoods</h2>
<p class="note">Neighborhoods with at least {MIN_NB} rent-stabilized buildings advertising today.</p>
{table(["Lowest", "Median", "Buildings"], nb_rows(nbs[:8]), numeric=(1, 2)) if nbs else ""}
{table(["Highest", "Median", "Buildings"], nb_rows(list(reversed(nbs[-8:]))), numeric=(1, 2)) if len(nbs) > 8 else ""}

<h2>Affordable openings today</h2>
{pipeline}

<h2>Where renters are looking</h2>
{demand_html}

<h2>How this is measured</h2>
<ul>
<li><b>Which buildings:</b> buildings on New York State's rent-stabilization register (DHCR) that have an apartment advertised on Zumper the morning of the report. A building on the register can also contain apartments that are no longer stabilized, so an advertised rent is not proof of a stabilized lease — check a unit's rent history with <a href="https://hcr.ny.gov/">HCR</a>.</li>
<li><b>Which price:</b> the lowest advertised rent in each building that day. Medians are of those building prices, not of every unit.</li>
<li><b>The index</b> compares only buildings advertised on both dates with the same set of unit sizes. Changes under ±0.5% count as unchanged.</li>
<li><b>Coverage</b> is thinnest outside Manhattan and Brooklyn; a borough or size with fewer than {MIN_BORO} buildings shows no median.</li>
<li><b>Visitor data</b> is counted in people over 30 days and published only above {MIN_VISITORS} people per row. See our <a href="/privacy/">privacy policy</a>.</li>
<li><b>Fair Market Rents:</b> <a href="https://www.huduser.gov/portal/datasets/fmr/smallarea/index.html">HUD FY2026 Small Area FMRs</a>. Lotteries: NYC Housing Connect and HousingSearch.ny.gov.</li>
</ul>
<p>Reporters and researchers: the numbers are free to use with a link to this page.</p>
</main>
<footer class="site">&copy; Find A Crib · <a href="/">Map</a> · <a href="/alerts/">Lottery alerts</a> · <a href="/privacy/">Privacy</a></footer>
</body></html>"""

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "section", "label", "median_lowest_asking_rent", "buildings"])
    w.writerow([today, "all", "NYC", round(statistics.median(allp)) if allp else "", len(allp)])
    for name, ps in by_boro.items():
        w.writerow([today, "borough", name, round(statistics.median(ps)) if len(ps) >= MIN_BORO else "", len(ps)])
    for k, ps in sorted(by_beds.items()):
        w.writerow([today, "size", BEDS.get(k, k), round(statistics.median(ps)) if len(ps) >= MIN_BORO else "", len(ps)])
    for (nb, boro), m, n in nbs:
        w.writerow([today, "neighborhood", f"{nb}, {boro}", round(m), n])
    for label, c in (("7-day change %", wk), ("30-day change %", mo)):
        if c and not c.get("too_few"):
            w.writerow([today, "index", label, round(c["median"], 2), c["n"]])
    return page, buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-archive", action="store_true")
    ap.add_argument("--no-demand", action="store_true")
    a = ap.parse_args()

    scrape = load("listings_zumper.json")
    if not scrape or not scrape.get("prices"):
        sys.exit("no fresh scrape in listings_zumper.json — nothing to report")
    today = (scrape.get("updated_iso") or "")[:10] or datetime.date.today().isoformat()
    snap = snapshot(scrape)
    if not a.no_archive:
        archive(snap, today)
    hist = history()
    hist[today] = snap

    bldg = {b["bbl"]: b for b in (load("buildings.min.json") or []) if b.get("bbl")}
    dem = None if a.no_demand else demand(bldg)
    page, csv_text = build(today, snap, hist, bldg, load("fmr.json", {}), load("hcr.json"),
                           load("housing_connect.json"), load("featured.json"), load("s8.json"), dem)
    out = os.path.join(DOCROOT, "rent-report")
    os.makedirs(out, exist_ok=True)
    for name, text in (("index.html", page), ("rent-report.csv", csv_text)):
        with open(os.path.join(out, name + ".tmp"), "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(os.path.join(out, name + ".tmp"), os.path.join(out, name))
    print(f"rent report {today}: {len(snap)} buildings, {len(hist)} archived days, "
          f"demand rows {len(dem['rows']) if dem else 'skipped'}")


if __name__ == "__main__":
    main()
