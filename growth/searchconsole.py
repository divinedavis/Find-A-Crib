#!/usr/bin/env python3
"""Search Console feed — turns the 90%-share goal from a proxy into a measurement.

Until this existed, "share of searches" was estimated by *coverage*: does a page
exist that targets each tracked query. That answers whether we tried, not
whether we won. This answers whether we won.

Three things get pulled daily:

  positions     the actual rank for every tracked query in keywords.json, so
                share = (queries ranking in the top 10) / (queries tracked)
  serving pages how many distinct URLs earned an impression — the only honest
                read on whether the 47k-page corpus is actually indexed, which
                is the bottleneck the whole engine was built around
  page-2 wins   queries at rank 11-20, the cheapest rankings available

Reuses seo_search_console.py for auth and querying rather than reimplementing
the service-account JWT dance.
"""
import os
import sys

from . import ledger, keywords

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _api():
    import seo_search_console as sc
    return sc, sc.access_token(sc.load_key())


def collect(days=7):
    """Pull Search Console and fold it into the ledger + keyword universe.

    Search Console lags ~2 days, so the window ends 2 days back rather than
    today; asking for today would silently return a partial day and make every
    trend look like a cliff.
    """
    sc, token = _api()
    start, end = sc.d(days + 2), sc.d(2)

    # ---- per-query positions, matched against the tracked universe
    rows = sc.query(token, start, end, ["query"], row_limit=5000)
    by_query = {}
    for r in rows:
        q = (r.get("keys") or [""])[0].strip().lower()
        by_query[q] = {
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "position": round(r.get("position", 0), 1),
        }

    kws = keywords.load()
    matched = 0
    for k in kws:
        hit = by_query.get(k["query"])
        if not hit:
            # Absent from the report means it earned no impressions at all in
            # the window. Record that as a known zero rather than leaving the
            # previous number to go stale and read as current.
            k["impressions"] = 0
            k["clicks"] = 0
            k["position"] = None
            continue
        matched += 1
        k["position"] = hit["position"]
        k["impressions"] = hit["impressions"]
        k["clicks"] = hit["clicks"]
    k_checked = ledger.today()
    for k in kws:
        k["gsc_checked"] = k_checked
    keywords.save(kws)

    # ---- serving pages: the indexing read
    pages = sc.query(token, start, end, ["page"], row_limit=5000)
    serving = len(pages)

    clicks, impressions, avg_pos = sc.totals(rows)   # returns a 3-tuple, not a dict
    top10 = sum(1 for k in kws if (k.get("position") or 999) <= 10)
    top3 = sum(1 for k in kws if (k.get("position") or 999) <= 3)
    share = round(100.0 * top10 / len(kws), 1) if kws else 0.0

    today = ledger.today()
    for metric, value in (
            ("gsc_clicks", clicks),
            ("gsc_impressions", impressions),
            ("gsc_position", round(avg_pos, 1)),
            ("gsc_serving_pages", serving),
            ("search_share_pct", share),
            ("tracked_top10", top10),
            ("tracked_top3", top3),
            ("tracked_ranking", matched)):
        ledger.record_result(today, "__site__", metric, value)

    ledger.write_last_run("searchconsole", {
        "window": f"{start}..{end}", "clicks": clicks,
        "impressions": impressions, "serving_pages": serving,
        "tracked_ranking": matched, "share_pct": share})

    return {"clicks": clicks, "impressions": impressions,
            "serving_pages": serving, "tracked_ranking": matched,
            "top10": top10, "top3": top3, "share_pct": share}


def page2(limit=25):
    """Tracked queries sitting at rank 11-20 — the cheapest wins available."""
    return sorted(
        [k for k in keywords.load() if 10 < (k.get("position") or 999) <= 20],
        key=lambda k: k.get("position") or 999)[:limit]


def ranking(limit=25):
    """Everything currently ranking, best first."""
    return sorted(
        [k for k in keywords.load() if k.get("position")],
        key=lambda k: k["position"])[:limit]
