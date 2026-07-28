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
  per-page      which URLs earn impressions, and for which queries — written to
                growth/gsc_pages.json

That last one is tracked in git on purpose. `serving_pages` being 89 says the
corpus is not indexed; it does not say *which* 89 pages Google chose to serve,
and that is the difference between guessing at what works and reading it. It is
also the only honest source for "the questions people actually ask this page",
which is what a direct-answer block or an FAQ should be written against.

No PII: these are public URLs and public search queries, so the file is safe in
a public repo and the 6am review agent — which has the repo and nothing else —
can read it.

Reuses seo_search_console.py for auth and querying rather than reimplementing
the service-account JWT dance.
"""
import json
import os
import sys

from . import ledger, keywords

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES_PATH = os.path.join(HERE, "gsc_pages.json")

# A page ranking 11-30 has proven demand and headroom: Google is willing to
# serve it, just not on page one. Those are worth rewriting before anything
# that has never been served at all.
HEADROOM_MIN, HEADROOM_MAX = 10.5, 30.0

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

    # ---- serving pages: the indexing read, and which pages they actually are
    pages = sc.query(token, start, end, ["page"], row_limit=5000)
    serving = len(pages)
    _save_pages(sc, token, start, end, pages, by_query)

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


def _save_pages(sc, token, start, end, pages, by_query):
    """Write growth/gsc_pages.json: the served URLs, their queries, and the
    queries we are not tracking at all.

    Kept small deliberately. The whole point is that a person or an agent reads
    it and decides something, and a 5,000-row dump of every long-tail
    impression does not get read.
    """
    rows = []
    for r in pages:
        url = (r.get("keys") or [""])[0]
        rows.append({"url": url, "clicks": r.get("clicks", 0),
                     "impressions": r.get("impressions", 0),
                     "position": round(r.get("position", 0), 1)})
    rows.sort(key=lambda x: -x["impressions"])

    # Which queries each of the busiest pages actually earns. Capped: the
    # page+query dimension multiplies rows fast and most of the tail is noise.
    per_page = {}
    try:
        pq = sc.query(token, start, end, ["page", "query"], row_limit=5000)
        for r in pq:
            keys = r.get("keys") or ["", ""]
            per_page.setdefault(keys[0], []).append(
                {"query": keys[1], "impressions": r.get("impressions", 0),
                 "clicks": r.get("clicks", 0), "position": round(r.get("position", 0), 1)})
        for url in per_page:
            per_page[url] = sorted(per_page[url], key=lambda q: -q["impressions"])[:10]
    except Exception as e:
        per_page = {"__error__": str(e)}

    # Queries we earn impressions for but never chose to track. Free demand
    # signal, and the honest input to "what should the next page be about".
    tracked = {k["query"].strip().lower() for k in keywords.load()}
    discovered = sorted(
        ({"query": q, **v} for q, v in by_query.items()
         if q not in tracked and v.get("impressions", 0) > 0),
        key=lambda x: -x["impressions"])[:60]

    payload = {
        "date": ledger.today(),
        "window": f"{start}..{end}",
        "serving_pages": len(rows),
        "pages": rows[:300],
        "queries_by_page": {r["url"]: per_page.get(r["url"], []) for r in rows[:60]},
        "discovered_untracked": discovered,
    }
    try:
        with open(PAGES_PATH, "w") as f:
            json.dump(payload, f, indent=1, sort_keys=True)
    except OSError:
        pass          # never let a reporting write break the measurement run
    return payload


def load_pages():
    try:
        with open(PAGES_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def headroom(limit=15):
    """Served pages ranking 11-30 — proven demand, not yet on page one.

    This is the page-level twin of page2(): page2 asks which *queries* are
    close, this asks which *URLs* are close, which is what you need when the
    fix is rewriting a page rather than adding one.
    """
    data = load_pages()
    out = [p for p in data.get("pages", [])
           if HEADROOM_MIN <= (p.get("position") or 999) <= HEADROOM_MAX
           and p.get("impressions", 0) > 0]
    return sorted(out, key=lambda p: -p["impressions"])[:limit]


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
