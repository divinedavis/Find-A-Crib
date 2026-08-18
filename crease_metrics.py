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
BOT = re.compile(
    r"bot|crawl|spider|slurp|bing|yandex|baidu|duckduck|semrush|ahrefs|mj12|dotbot|"
    r"petal|bytespider|facebookexternalhit|whatsapp|telegram|preview|monitor|uptime|"
    r"curl|wget|python-requests|okhttp|headless|lighthouse|pingdom|scanner|nuclei",
    re.I,
)
# A page view is a page. Chunks, images and the robots file are not visits, and
# counting them turns one reader into thirty.
ASSET = re.compile(r"^/(?:_next/|assets/|favicon|robots\.txt|sitemap\.xml|.*\.(?:svg|png|jpg|ico|css|js|map)$)")

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

    seen, seen_today = set(), set()
    views = views_today = 0
    per_day = {}
    referrers = {}

    try:
        with open(ACCESS_LOG, "r", errors="replace") as f:
            for line in f:
                m = LINE.match(line)
                if not m:
                    continue
                if m.group("host") not in HOSTS:
                    continue
                if m.group("method") not in ("GET", "HEAD"):
                    continue
                if BOT.search(m.group("ua")):
                    continue
                path = m.group("path").split("?")[0]
                if ASSET.match(path):
                    continue
                day = _parse_day(m.group("ts"))
                if not day or (cutoff and day < cutoff):
                    continue

                who = (m.group("ip"), m.group("ua"))
                seen.add((day, who))
                views += 1
                per_day[day.isoformat()] = per_day.get(day.isoformat(), 0) + 1
                if day == today:
                    seen_today.add(who)
                    views_today += 1

                ref = m.group("ref") or ""
                if ref and ref != "-" and "creasenyc.com" not in ref and "usecreaseapp.com" not in ref:
                    host = ref.split("/")[2] if "://" in ref else ref
                    referrers[host] = referrers.get(host, 0) + 1
    except FileNotFoundError:
        pass

    # Unique people, not unique person-days: somebody who came Monday and
    # Tuesday is one visitor and two visits.
    people = {who for _, who in seen}
    spark = [{"date": d, "views": n} for d, n in sorted(per_day.items())][-14:]
    top_ref = sorted(referrers.items(), key=lambda kv: -kv[1])[:5]

    return {
        "visitors": len(people),
        "visits": views,
        "visitors_today": len(seen_today),
        "views_today": views_today,
        "sparkline": spark,
        "referrers": [{"host": h, "hits": n} for h, n in top_ref],
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
