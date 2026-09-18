#!/usr/bin/env python3
"""Marracat, for the owner dashboard's fifth tab.

Unlike the other four sites, Marracat does not live on this droplet — it runs
on 167.71.170.219 beside CAP Recruiting. Its numbers are computed THERE, every
five minutes, by web/metrics/marracat_metrics.py in the Marracat repo (it needs
that box's nginx log and the storefront's SQLite), and handed out by the
storefront at /api/owner/metrics behind a shared key. This module only fetches
and caches that payload.

The key is MARRACAT_METRICS_KEY in this service's .env; it must equal
METRICS_KEY in /etc/marracat/web.env on the Marracat droplet. Without it the
tab renders a setup card rather than a 503. Counts only — no shopper's name,
email or order crosses either hop.
"""
import datetime
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ.get("MARRACAT_METRICS_URL", "https://marracat.com/api/owner/metrics")
KEY = os.environ.get("MARRACAT_METRICS_KEY", "")
RANGE_DAYS = {"today": 1, "month": 30, "3m": 90, "6m": 182, "all": None}

CACHE_TTL = 60.0
_LOCK = threading.Lock()
_CACHE = {}


def build(rng="all"):
    base = {"__site__": "marracat", "range": rng}
    if not KEY:
        return {**base, "ok": False, "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
                "warnings": ["MARRACAT_METRICS_KEY is not set on the dashboard API."]}
    req = urllib.request.Request(f"{URL}?range={urllib.parse.quote(rng)}",
                                 headers={"X-Metrics-Key": KEY, "User-Agent": "divinedavis-dashboard"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            body = json.load(r)
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as e:
        # A Marracat outage must read as "Marracat unreachable", not as a
        # broken dashboard.
        return {**base, "ok": False, "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
                "warnings": [f"marracat.com metrics unreachable ({type(e).__name__})."]}
    return {**base, **body, "ok": True}


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
    if data.get("ok"):
        with _LOCK:
            _CACHE[rng] = (now, data)
    return data


if __name__ == "__main__":
    print(json.dumps(build_cached("all"), indent=2)[:1500])
