#!/usr/bin/env python3
"""Crease, for the owner dashboard's third tab.

Two sources, and the split matters:

  nginx access log   who came to creasenyc.com. Counted from the server's own
                     log rather than a JavaScript tag, so an ad-blocker cannot
                     hide a visitor and a bot cannot inflate one.
  dispatch API       what they did — addresses checked, pickups requested,
                     orders placed, money actually kept. Read over loopback
                     from the Crease dispatcher, which owns that schema.

The dispatcher is asked rather than the database because the alternative is
this process holding Crease's service-role key: every row in that database, in
a Flask app that serves a public API, for the sake of a dozen counts. The
internal key it uses instead only reaches routes nginx already binds to
loopback.

Nothing here returns a person. Visits are counted, addresses are counted by
neighbourhood, and no name, phone or street crosses this module.
"""
import datetime
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

ACCESS_LOG = os.environ.get("CREASE_ACCESS_LOG", "/var/log/nginx/creasenyc.access.log")
DISPATCH_URL = os.environ.get("CREASE_DISPATCH_URL", "http://127.0.0.1:8011")
INTERNAL_KEY = os.environ.get("CREASE_INTERNAL_KEY", "")
HOSTS = {"creasenyc.com", "www.creasenyc.com", "usecreaseapp.com", "www.usecreaseapp.com"}

CACHE_TTL = 60.0
_LOCK = threading.Lock()
_CACHE = {}

# Deliberately broad. A crawler counted as a visitor is a lie the dashboard
# then repeats every day; a person wrongly excluded is one visit, once.
#
# The user-agent list is only the honest half of the problem. On this site's
# first day 62 "visitors" were counted and not one was a person: scanners
# probing /.env and /wp-admin behind ordinary Chrome and Safari strings, a
# LeakIX prober, and the owner's own browser automation. Two behavioural rules
# below do the work the UA string cannot.
BOT = re.compile(
    r"bot|crawl|spider|slurp|bing|yandex|baidu|duckduck|semrush|ahrefs|mj12|dotbot|"
    r"petal|bytespider|facebookexternalhit|whatsapp|telegram|preview|monitor|uptime|"
    r"curl|wget|python-requests|okhttp|headless|lighthouse|pingdom|scanner|nuclei",
    re.I,
)
# A page view is a page. Chunks, images and the robots file are not visits, and
# counting them turns one reader into thirty.
ASSET = re.compile(r"^/(?:_next/|assets/|favicon|robots\.txt|sitemap\.xml|.*\.(?:svg|png|jpg|ico|css|js|map)$)")

# Nobody browsing a dry cleaner asks for /.env. One of these from an address
# marks everything it did that day as a scan, not a visit.
PROBE = re.compile(
    r"\.env|/wp-|/admin|\.git|graphql|phpmyadmin|/vendor|/actuator|/telescope|"
    r"\.aws|/config\.json|/config/|/backend/|/\.well-known/security|xmlrpc|"
    r"/owa/|/autodiscover|\.php$",
    re.I,
)

# Your own machines. A dashboard that counts the person building the site is a
# dashboard that congratulates them for testing.
_ENV_OWNER_IPS = {ip.strip() for ip in os.environ.get("CREASE_OWNER_IPS", "").split(",") if ip.strip()}
# Addresses the site itself registered, from anyone who visited with ?owner=1.
# A hand-kept list loses every time a phone changes network; this one follows
# the devices around, the way NEMO's does.
OWNER_FILE = os.environ.get("CREASE_OWNER_FILE", "/var/lib/crease/owner-ips.json")


def owner_ips():
    ips = set(_ENV_OWNER_IPS)
    try:
        with open(OWNER_FILE) as f:
            for ip in json.load(f).get("ips", []):
                ips.add(str(ip))
    except (OSError, ValueError):
        pass
    return ips


# Kept for the tooling that inspects the filter interactively.
OWNER_IPS = owner_ips()

# Where a customer cannot be.
#
# The user-agent filter and the asset rule between them still left sixteen
# "visitors" on day one, and every one was a machine: three OVH addresses
# sharing a single Windows Chrome string, a Google Cloud range, AWS, and a
# rotating 103.196.9.x block wearing an iPhone. The tell was never the browser
# they claimed to be — it was the network. Somebody in Brooklyn booking a
# pickup arrives on Verizon, Spectrum or T-Mobile, not from a rack in Roubaix.
#
# Blunt on purpose: this also drops a real person browsing through a VPN, which
# for a neighbourhood laundry service is a rounding error against counting a
# crawler as demand. First octets are matched as prefixes, so the list stays
# readable rather than exact.
DATACENTER_PREFIXES = (
    "158.69.", "167.114.", "51.222.", "51.79.",            # OVH
    "34.", "35.",                                            # Google Cloud
    "54.", "52.", "18.", "3.",                              # AWS
    "164.90.", "167.172.", "165.227.", "104.236.", "159.203.",  # DigitalOcean
    "20.", "40.", "13.", "152.233.",                        # Azure
    "43.", "47.",                                           # Tencent / Alibaba
    "5.9.", "95.216.", "168.119.", "116.202.",              # Hetzner
    "62.210.", "51.15.", "163.172.", "212.83.",             # Scaleway / Online SAS
    "103.196.",                                             # rotating scraper block
    "45.88.", "136.0.74.", "149.19.255.",                   # seen probing this site
)


def _datacenter(ip):
    return ip.startswith(DATACENTER_PREFIXES)

LINE = re.compile(
    r'^(?P<host>\S+) (?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+) [^"]*" (?P<status>\d{3}) \S+ '
    r'"(?P<ref>[^"]*)" "(?P<ua>[^"]*)"'
)

RANGE_DAYS = {"today": 1, "month": 30, "3m": 90, "6m": 182, "all": None}


def _parse_day(ts):
    # 18/Aug/2026:23:07:40 +0000
    try:
        return datetime.datetime.strptime(ts.split()[0], "%d/%b/%Y:%H:%M:%S").date()
    except Exception:
        return None


def traffic(rng="all"):
    """Unique visitors, page views and today's numbers, from the access log.

    A visitor is one IP + browser per day: the site sets no tracking cookie, so
    switching from wifi to cell counts twice and an office behind one router
    counts once. Said plainly on the tile rather than dressed up as precision.
    """
    days = RANGE_DAYS.get(rng, None)
    today = datetime.datetime.utcnow().date()
    cutoff = today - datetime.timedelta(days=days - 1) if days else None

    owners = owner_ips()

    # Two passes, because both rules need to know what an address did across
    # the whole day before any of its hits can be judged.
    pages, assets, scanners = [], set(), set()
    referrers = {}

    try:
        with open(ACCESS_LOG, "r", errors="replace") as f:
            for line in f:
                m = LINE.match(line)
                if not m:
                    continue
                if m.group("host") not in HOSTS:
                    continue
                ip, ua = m.group("ip"), m.group("ua")
                day = _parse_day(m.group("ts"))
                if not day:
                    continue
                path = m.group("path").split("?")[0]
                who = (day, ip, ua)

                if PROBE.search(path):
                    scanners.add((day, ip))
                    continue
                if ip in owners or _datacenter(ip) or BOT.search(ua):
                    continue
                if m.group("method") not in ("GET", "HEAD"):
                    continue

                if ASSET.match(path):
                    # Not a page view, but proof a browser was rendering one.
                    assets.add(who)
                    continue

                pages.append((who, day, m.group("ref") or ""))
    except FileNotFoundError:
        pass

    seen, seen_today = set(), set()
    views = views_today = 0
    per_day = {}

    for who, day, ref in pages:
        # A scan and a visit look identical in one line of a log. They differ in
        # what else the address did: a browser fetches the stylesheet and the
        # script bundle the page asks for, and a scanner asks for the page and
        # leaves. Requiring one asset fetch is what separates them, and it is
        # why this counts lower than the raw log — deliberately.
        if (day, who[1]) in scanners or who not in assets:
            continue
        if cutoff and day < cutoff:
            continue

        seen.add(who)
        views += 1
        per_day[day.isoformat()] = per_day.get(day.isoformat(), 0) + 1
        if day == today:
            seen_today.add((who[1], who[2]))
            views_today += 1

        if ref and ref != "-" and "creasenyc.com" not in ref and "usecreaseapp.com" not in ref:
            host = ref.split("/")[2] if "://" in ref else ref
            referrers[host] = referrers.get(host, 0) + 1

    # Unique people, not unique person-days: somebody who came Monday and
    # Tuesday is one visitor and two visits.
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
        # Said out loud on the tile, because the first honest answer this
        # dashboard gave was "62 visitors" and the true answer was zero.
        "scanners_excluded": len({ip for _, ip in scanners}),
        # What the number means, in the payload rather than only in a comment:
        # this counts browsers on consumer networks that rendered a page.
        "basis": "consumer-network browsers that fetched the page and its assets",
    }


def _dispatch(rng):
    if not INTERNAL_KEY:
        return None
    url = f"{DISPATCH_URL}/v1/stats/dashboard?range={rng}"
    req = urllib.request.Request(url, headers={"x-crease-key": INTERNAL_KEY})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            body = json.load(r)
        return body.get("stats")
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        # A dispatcher that is down must not take the traffic tiles with it.
        return None


def build(rng="all"):
    stats = _dispatch(rng) or {}
    return {
        "__site__": "crease",
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "range": rng,
        "traffic": traffic(rng),
        "demand": stats.get("demand"),
        "requests": stats.get("requests"),
        "orders": stats.get("orders"),
        "customers": stats.get("customers"),
        "canvass": stats.get("canvass"),
        "partners": stats.get("partners"),
        "degraded": not stats,
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
    print(json.dumps(build_cached("all"), indent=2)[:1200])
