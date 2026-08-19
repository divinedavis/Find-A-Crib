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
import socket
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
    # OVH / SoYouStart
    "158.69.", "167.114.", "51.222.", "51.79.", "51.91.", "57.128.", "139.99.",
    "141.94.", "149.202.", "51.68.", "51.75.", "51.83.", "54.36.", "54.37.",
    # Google Cloud
    "34.", "35.",
    # AWS
    "54.", "52.", "18.", "3.", "44.", "56.", "98.87.", "174.129.", "100.24.",
    "100.25.", "100.26.", "107.20.", "184.72.", "184.73.",
    # DigitalOcean
    "164.90.", "167.172.", "165.227.", "104.236.", "159.203.", "165.22.",
    "178.128.", "134.209.", "146.190.", "144.126.", "138.68.", "142.93.",
    "143.198.", "157.245.", "161.35.", "159.65.", "159.89.", "68.183.",
    # Azure
    "20.", "40.", "13.", "152.233.",
    # Tencent / Alibaba
    "43.", "47.",
    # Hetzner
    "5.9.", "95.216.", "168.119.", "116.202.", "49.12.", "78.46.", "88.99.",
    # Scaleway / Online SAS
    "62.210.", "51.15.", "163.172.", "212.83.",
    # Linode / Akamai
    "172.236.", "172.237.", "45.79.", "45.33.", "139.144.", "170.187.",
    # Fastly and other edge networks, which browse nothing
    "146.75.", "151.101.", "199.232.",
    # M247 / DataCamp / Datapacket and the consumer VPN exits that ride them
    "149.57.", "146.70.", "149.88.", "185.254.", "62.93.", "89.187.",
    "138.199.", "143.244.", "156.146.", "185.156.", "37.19.",
    # Zscaler and corporate proxy pools
    "165.225.", "216.73.", "104.129.",
    # rotating scraper and probe blocks seen on this site
    "103.196.", "45.88.", "136.0.74.", "149.19.255.", "205.169.39.",
    "216.38.230.", "194.36.25.", "192.253.209.", "204.101.161.", "23.27.145.",
    "89.248.", "80.82.", "198.44.138.", "111.248.200.", "104.164.218.",
)

# The prefix table above is a list somebody has to maintain, and the day-one
# wave that prompted it arrived from ranges nobody had written down yet. The
# network's own name is the durable tell: a rack in Ashburn answers to
# ec2-…​.amazonaws.com, a phone in Brooklyn answers to something with verizon,
# spectrum or t-mobile in it.
HOSTING_PTR = re.compile(
    r"amazonaws|googleusercontent|google\.com$|azure|cloudapp|digitalocean|"
    r"linode|vultr|ovh\.|hetzner|scaleway|online\.net|contabo|hostinger|"
    r"leaseweb|datapacket|m247|datacamp|choopa|quadranet|colocrossing|tzulo|"
    r"servers\.com|hosting|vps|dedicated|cloudapp|tor-exit",
    re.I,
)
# Deliberately not matched: "cloud", "relay", "proxy". iCloud Private Relay is
# how a large share of iPhone owners browse, and it exits through Cloudflare,
# Akamai and Fastly under names carrying all three words. Excluding those
# excludes exactly the Brooklyn customer this site is for. The cost is that
# some edge-network scrapers survive the filter; the demand tiles beside it
# come from the dispatcher, not the log, so a real customer is never lost —
# only miscounted here.

# Resolved lazily and kept, because a PTR record for an address does not change
# between dashboard refreshes and a blocking DNS lookup in a request handler is
# how a dashboard learns to hang.
PTR_FILE = os.environ.get("CREASE_PTR_FILE", "/var/lib/crease/ptr-cache.json")
_PTR = None
_PTR_LOCK = threading.Lock()
_PTR_WARMING = set()


def _ptr_cache():
    global _PTR
    if _PTR is None:
        try:
            with open(PTR_FILE) as f:
                _PTR = dict(json.load(f))
        except (OSError, ValueError):
            _PTR = {}
    return _PTR


def _ptr_save():
    try:
        os.makedirs(os.path.dirname(PTR_FILE), exist_ok=True)
        tmp = PTR_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_PTR, f)
        os.replace(tmp, PTR_FILE)
    except OSError:
        pass


def _ptr_warm(ips):
    """Resolve unknown addresses off the request path.

    An address whose name is not known yet is counted as a person this minute
    and judged on the next refresh. Erring towards counting for sixty seconds
    is the right way round: the alternative is a dashboard that stalls behind a
    resolver that is not answering.
    """
    for ip in ips:
        name = ""
        try:
            name = socket.gethostbyaddr(ip)[0]
        except (OSError, socket.herror, socket.gaierror):
            name = ""   # no PTR is not proof of anything; recorded as unknown
        with _PTR_LOCK:
            _PTR[ip] = name
            _PTR_WARMING.discard(ip)
    with _PTR_LOCK:
        _ptr_save()


def _hosting(ip):
    """True when the address is known to be a machine's, not a person's."""
    name = _ptr_cache().get(ip)
    if name is None:
        with _PTR_LOCK:
            # Bounded: a scan wave must not turn one dashboard refresh into a
            # thousand DNS queries from this box.
            if len(_PTR_WARMING) < 100:
                _PTR_WARMING.add(ip)
        return False
    return bool(name) and bool(HOSTING_PTR.search(name))


def _ptr_flush():
    """Hand whatever this pass could not name to a background resolver."""
    with _PTR_LOCK:
        pending = sorted(_PTR_WARMING)
    if pending:
        threading.Thread(target=_ptr_warm, args=(pending,), daemon=True).start()


# A browser that is a year behind is not a browser. Chrome ships a major
# version every four weeks and updates itself; the scan waves on this site
# wear Chrome 42, 45, 79, 83 and 92 while claiming to be Windows desktops.
# Bump this when it starts excluding people — it is deliberately about a year
# behind stable (151 in August 2026).
STALE_CHROME = 135
CHROME_VERSION = re.compile(r"Chrome/(\d+)")


def _stale_browser(ua):
    m = CHROME_VERSION.search(ua)
    return bool(m) and int(m.group(1)) < STALE_CHROME


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
    # One address wearing two browsers in a day is not a household, it is a
    # scanner rotating its user-agent. The pairs are collected first and the
    # whole day is dropped below.
    day_agents = {}

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
                # A browser a year out of date, on a network that sells racks:
                # both were counted as demand until the day this site had 49
                # "visitors", one order request between them, and none of them
                # a person.
                if _stale_browser(ua) or _hosting(ip):
                    continue

                if ASSET.match(path):
                    # Not a page view, but proof a browser was rendering one.
                    assets.add(who)
                    continue
                # A HEAD is a machine checking the page is there. It renders
                # nothing and reads nothing, so it is not a view.
                if m.group("method") != "GET":
                    continue

                day_agents.setdefault((day, ip), set()).add(ua)
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

        if ref and ref != "-" and "creasenyc.com" not in ref and "usecreaseapp.com" not in ref:
            host = ref.split("/")[2] if "://" in ref else ref
            referrers[host] = referrers.get(host, 0) + 1

    # Unique people, not unique person-days: somebody who came Monday and
    # Tuesday is one visitor and two visits.
    _ptr_flush()

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
        "basis": "consumer-network browsers, on a current build, that fetched "
                 "the page and its assets",
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
