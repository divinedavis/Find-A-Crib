#!/usr/bin/env python3
"""Trent's Fresh Spaces, for the owner dashboard's fourth tab.

Three sources, and none of them is a JavaScript tag:

  nginx access log   who came to trentsfreshspaces.com. The site sits on this
                     droplet beside Find A Crib, NEMO and Crease, so the log is
                     read here rather than standing up a fourth dashboard.
  bookings.sqlite    what they did — the estimate/consultation bookings the
                     Node app on :3007 writes. Counts and dates only: no name,
                     phone, email or address crosses this module.
  Search Console     whether Google is sending anyone at all, via the
                     find-a-crib service account that reads every property in
                     the estate.

Two honest limits, stated here because the tiles state them too:

  * History starts 2026-08-20. Until then trentsfreshspaces.com wrote into the
    shared /var/log/nginx/access.log in the combined format, which carries no
    $host — there is no way to tell its lines from any other vhost's, so there
    is nothing to backfill. Same shape as NEMO's July gap.
  * The site has no first-party beacon, so a tel: tap is invisible here. On a
    contractor site that is the conversion that matters, and it is the obvious
    next thing to add — NEMO's dashboard counts them because NEMO's pages ship
    analytics.js.

The visitor filter is imported wholesale from crease_metrics rather than copied:
the bot list, the datacenter ranges, the reverse-DNS check and the stale-browser
rule are the same judgement about the same question, and two copies of it would
drift until two tabs of one dashboard disagreed about what a person is.
"""
import datetime
import glob
import gzip
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import crease_metrics as _cm

ACCESS_LOG = os.environ.get("TRENT_ACCESS_LOG", "/var/log/nginx/trents.access.log")
BOOKINGS_DB = os.environ.get(
    "TRENT_BOOKINGS_DB", "/var/www/trents-fresh-spaces/server/bookings.sqlite")
GSC_KEY = os.environ.get("TRENT_GSC_KEY", "/root/Find-A-Crib/growth/.gsc_key.json")
GSC_SITE = os.environ.get("TRENT_GSC_SITE", "https://trentsfreshspaces.com/")
HOSTS = {"trentsfreshspaces.com", "www.trentsfreshspaces.com"}

# The day per-site logging shipped. Anything the tiles say about "since" comes
# from the log itself; this is the floor the UI explains the gap with.
LOGGING_SINCE = "2026-08-20"

CACHE_TTL = 60.0
_LOCK = threading.Lock()
_CACHE = {}

RANGE_DAYS = _cm.RANGE_DAYS

# A static page site: the proof a browser rendered the page is that it came
# back for the scripts the page asks for. Both are served no-cache, so a repeat
# visitor revalidates and still leaves a line in the log.
SITE_JS = re.compile(r"^/(?:script|booking)\.js")

# Your own machines. Trent's site sets no owner cookie the way Crease and NEMO
# do — the `site` log format's last field is Crease's — so this is the only
# owner exclusion available here, and it is opt-in via the environment.
_OWNER_IPS = {ip.strip() for ip in os.environ.get("TRENT_OWNER_IPS", "").split(",") if ip.strip()}


# --------------------------------------------------------------- market size
# What demand actually exists in York, PA — the denominator every other number
# on this tab is a fraction of. Google does not publish this for free, so it is
# a third-party read of Keyword Planner data rather than a measurement of ours,
# and it is dated and sourced so it can be re-checked rather than trusted.
#
# Cross-checked against the same table for Harrisburg (270/mo) and Lancaster
# (260/mo) — two comparable central-PA cities that came back within 4% of York,
# which is what a real market size looks like rather than a made-up one.
#
# The list is hire-intent only: somebody typing "painters near me" is shopping.
# It excludes DIY queries ("how to paint a room"), brand searches for the
# franchises, and the long tail below 5 searches a month, so read it as a floor.
MARKET = {
    "geo": "York, PA",
    "monthly_searches": 265,
    "as_of": "2026-08",
    "source": "Home Service Base (Google Keyword Planner data), painting keywords, York PA",
    "source_url": "https://homeservicebase.com/painting-business/keywords?state=pennsylvania&city=york",
    "comparables": {"Harrisburg, PA": 270, "Lancaster, PA": 260},
    "top": [
        {"q": "painters near me", "vol": 75, "cpc": 3.78, "comp": "High"},
        {"q": "painting companies near me", "vol": 35, "cpc": 11.00, "comp": "Medium"},
        {"q": "house painters york", "vol": 30, "cpc": 18.05, "comp": "High"},
        {"q": "painting contractors", "vol": 15, "cpc": 3.46, "comp": "Low"},
        {"q": "interior painters near me", "vol": 10, "cpc": 0.51, "comp": "Low"},
        {"q": "house painters near me", "vol": 10, "cpc": 3.78, "comp": "High"},
    ],
    # Who is taking them today, from the same table's #1-ranked site per query.
    "incumbents": ["thumbtack.com", "yelp.com", "certapro.com", "angi.com"],
    "note": "Hire-intent searches per month in York city. Excludes DIY questions, "
            "brand searches and the tail under 5/mo, so it is a floor.",
}


# ------------------------------------------------------------------- traffic
def _log_lines():
    """Every line of the per-site log, rotated files included."""
    paths = sorted(glob.glob(ACCESS_LOG + ".*"), reverse=True) + [ACCESS_LOG]
    for path in paths:
        try:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", errors="replace") as f:
                for line in f:
                    yield line
        except OSError:
            continue


def traffic(rng="all"):
    """Unique visitors and page views, from the server's own log.

    A visitor is one IP + browser per day: the site sets no tracking cookie, so
    a phone that moves from wifi to cell counts twice and an office behind one
    router counts once. Two passes, because the scanner rules need to know what
    an address did across the whole day before any of its hits can be judged —
    the same shape as Crease's, and for the same reason.
    """
    days = RANGE_DAYS.get(rng, None)
    today = datetime.datetime.utcnow().date()
    cutoff = today - datetime.timedelta(days=days - 1) if days else None

    pages, assets, scanners, ran = [], set(), set(), set()
    referrers, day_agents = {}, {}
    first_day = None

    for line in _log_lines():
        m = _cm.LINE.match(line)
        if not m:
            continue
        if m.group("host") not in HOSTS:
            continue
        ip, ua = m.group("ip"), m.group("ua")
        day = _cm._parse_day(m.group("ts"))
        if not day:
            continue
        if first_day is None or day < first_day:
            first_day = day
        path = m.group("path").split("?")[0]
        who = (day, ip, ua)

        if _cm.PROBE.search(path):
            scanners.add((day, ip))
            continue
        if ip in _OWNER_IPS or _cm._datacenter(ip) or _cm.BOT.search(ua):
            continue
        if _cm._stale_browser(ua) or _cm._hosting(ip):
            continue

        if _cm.ASSET.match(path) or SITE_JS.match(path):
            assets.add(who)
            if SITE_JS.match(path):
                ran.add(who)
            continue
        if m.group("method") != "GET":
            continue

        day_agents.setdefault((day, ip), set()).add(ua)
        pages.append((who, day, m.group("ref") or ""))

    seen, seen_today = set(), set()
    views = views_today = 0
    per_day = {}

    for who, day, ref in pages:
        # A scan and a visit look identical in one line of a log. They differ in
        # what else the address did: a browser comes back for the stylesheet and
        # the scripts, a scanner asks for the page and leaves.
        if (day, who[1]) in scanners or who not in assets or who not in ran:
            continue
        if len(day_agents.get((day, who[1]), ())) > 1:
            continue
        if cutoff and day < cutoff:
            continue

        seen.add(who)
        views += 1
        per_day[day.isoformat()] = per_day.get(day.isoformat(), 0) + 1
        if day == today:
            seen_today.add((who[1], who[2]))
            views_today += 1

        if ref and ref != "-" and "trentsfreshspaces.com" not in ref:
            host = ref.split("/")[2] if "://" in ref else ref
            referrers[host] = referrers.get(host, 0) + 1

    _cm._ptr_flush()

    people = {(ip, ua) for _, ip, ua in seen}
    spark = [{"date": d, "views": n} for d, n in sorted(per_day.items())][-14:]
    top_ref = sorted(referrers.items(), key=lambda kv: -kv[1])[:5]

    return {
        "visitors": len(people),
        "visits": views,
        "visitors_today": len(seen_today),
        "views_today": views_today,
        "sparkline": spark,
        "referrers": [{"host": h, "hits": n} for h, n in top_ref],
        "scanners_excluded": len({ip for _, ip in scanners}),
        "since": first_day.isoformat() if first_day else None,
        "logging_since": LOGGING_SINCE,
        "basis": "consumer-network browsers that fetched a page and came back "
                 "for the scripts it asks for",
    }


# ------------------------------------------------------------------ bookings
def bookings(rng="all"):
    """Estimates and consultations booked. Counts and dates only.

    Read-only against the Node app's SQLite. The database is the truth about
    all-time; the range only scopes the period counts, because "one booking in
    the last month" and "twelve ever" answer different questions and the tile
    shows both.
    """
    out = {"total": 0, "confirmed": 0, "cancelled": 0, "upcoming": 0,
           "period": 0, "today": 0, "by_service": {}, "first": None,
           "last": None, "ok": False}
    if not os.path.exists(BOOKINGS_DB):
        return out
    try:
        con = sqlite3.connect(f"file:{BOOKINGS_DB}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return out
    try:
        days = RANGE_DAYS.get(rng, None)
        today = datetime.datetime.utcnow().date()
        cutoff = (today - datetime.timedelta(days=days - 1)).isoformat() if days else "0000"
        now = datetime.datetime.utcnow().isoformat()
        q = con.execute
        out["total"] = q("select count(*) from bookings").fetchone()[0]
        for status, count in q("select status, count(*) from bookings group by status"):
            if status in ("confirmed", "cancelled"):
                out[status] = count
        out["upcoming"] = q("select count(*) from bookings where status='confirmed' "
                            "and end_utc >= ?", (now,)).fetchone()[0]
        out["period"] = q("select count(*) from bookings where substr(created_at,1,10) >= ?",
                          (cutoff,)).fetchone()[0]
        out["today"] = q("select count(*) from bookings where substr(created_at,1,10) = ?",
                         (today.isoformat(),)).fetchone()[0]
        out["by_service"] = {s: c for s, c in
                             q("select service, count(*) from bookings group by service")}
        row = q("select min(substr(created_at,1,10)), max(substr(created_at,1,10)) "
                "from bookings").fetchone()
        out["first"], out["last"] = row[0], row[1]
        out["ok"] = True
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


# ------------------------------------------------------------ search console
def _gsc_token():
    """Sign a service-account JWT and exchange it for an access token.

    Written out here rather than imported from seo_search_console because that
    module is a CLI: it sys.exit()s on a bad key, and a gunicorn worker must
    raise instead of killing itself over a search tile.
    """
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    def b64(d):
        return base64.urlsafe_b64encode(d).rstrip(b"=")

    with open(GSC_KEY) as f:
        key = json.load(f)
    now = int(time.time())
    signing = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()) + b"." + b64(json.dumps({
        "iss": key["client_email"],
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now, "exp": now + 3600,
    }).encode())
    priv = serialization.load_pem_private_key(key["private_key"].encode(), password=None)
    sig = b64(priv.sign(signing, padding.PKCS1v15(), hashes.SHA256()))
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": (signing + b"." + sig).decode(),
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["access_token"]


def _gsc_query(token, start, end, dimensions, limit=25):
    url = ("https://searchconsole.googleapis.com/webmasters/v3/sites/"
           + urllib.parse.quote(GSC_SITE, safe="") + "/searchAnalytics/query")
    payload = {"startDate": start, "endDate": end, "rowLimit": limit}
    if dimensions:
        payload["dimensions"] = dimensions
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("rows", [])


def search(days=28):
    """Clicks, impressions and the queries that earned them.

    Search Console lags two to three days, so the window ends three days back;
    asking for today returns a partial day and makes every trend look like a
    cliff. `connected` separates "Google sent nobody" from "we could not ask",
    which are the same zero on the tile and opposite problems underneath.
    """
    out = {"connected": False, "clicks": 0, "impressions": 0, "ctr": None,
           "position": None, "queries": [], "pages": [], "start": None,
           "end": None, "days": days}
    end = datetime.date.today() - datetime.timedelta(days=3)
    start = end - datetime.timedelta(days=days - 1)
    out["start"], out["end"] = start.isoformat(), end.isoformat()
    try:
        token = _gsc_token()
        totals = _gsc_query(token, out["start"], out["end"], None, 1)
        queries = _gsc_query(token, out["start"], out["end"], ["query"], 10)
        pages = _gsc_query(token, out["start"], out["end"], ["page"], 10)
    except (OSError, ValueError, KeyError, ImportError, urllib.error.URLError):
        # ImportError is in the list on purpose: signing the service-account JWT
        # needs `cryptography`, which the API's venv did not have until this
        # shipped. A missing dependency must degrade to an unconnected search
        # tile, not take the whole tab down with a 503.
        return out
    out["connected"] = True
    if totals:
        t = totals[0]
        out["clicks"] = int(t.get("clicks") or 0)
        out["impressions"] = int(t.get("impressions") or 0)
        out["ctr"] = round(100.0 * (t.get("ctr") or 0), 1)
        out["position"] = round(t.get("position") or 0, 1)
    out["queries"] = [{"q": r["keys"][0], "clicks": int(r.get("clicks") or 0),
                       "impressions": int(r.get("impressions") or 0),
                       "position": round(r.get("position") or 0, 1)}
                      for r in queries]
    out["pages"] = [{"url": r["keys"][0].replace(GSC_SITE, "/"),
                     "clicks": int(r.get("clicks") or 0),
                     "impressions": int(r.get("impressions") or 0)}
                    for r in pages]
    return out


# ------------------------------------------------------------------ assembly
def build(rng="all"):
    t = traffic(rng)
    b = bookings(rng)
    s = search()
    market = dict(MARKET)
    # The one number that puts the rest in proportion: of the searches that
    # happen in this town every month, how many did this site even appear for.
    market["share_pct"] = (round(100.0 * s["impressions"] / market["monthly_searches"], 1)
                           if s["connected"] and market["monthly_searches"] else None)
    warnings = []
    if not b["ok"]:
        warnings.append("The booking database could not be read.")
    if not s["connected"]:
        warnings.append("Search Console could not be reached.")
    return {
        "__site__": "trent",
        "domain": "trentsfreshspaces.com",
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "range": rng,
        "since": t["since"],
        "traffic": t,
        "bookings": b,
        "search": s,
        "market": market,
        "warnings": warnings,
    }


def build_cached(rng="all"):
    rng = (rng or "all").lower()
    if rng not in RANGE_DAYS:
        rng = "all"
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(rng)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
    data = build(rng)
    with _LOCK:
        _CACHE[rng] = (now, data)
    return data


if __name__ == "__main__":
    print(json.dumps(build_cached("all"), indent=2))
