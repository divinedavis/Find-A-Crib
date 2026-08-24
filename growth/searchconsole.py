#!/usr/bin/env python3
"""Search Console feed — turns the 90%-share goal from a proxy into a measurement.

Until this existed, "share of searches" was estimated by *coverage*: does a page
exist that targets each tracked query. That answers whether we tried, not
whether we won. This answers whether we won.

Three things get pulled daily:

  positions     the actual rank for every tracked query in keywords.json, so
                share = (queries ranking in the top 10) / (queries tracked)
  serving pages how many distinct URLs earned an impression. NOT an indexing
                number, though this docstring called it one until 2026-08-15 and
                three weeks of reviews took it at its word: an impression needs
                the page indexed AND somebody to have searched for something it
                answers, and on 47k single-address pages the second condition is
                what almost every page fails. Read it as the site's search
                *footprint*. growth/indexstatus.py asks Google for the actual
                index state of a sampled cohort; that is the indexing number.
  page-2 wins   queries at rank 11-20, the cheapest rankings available
  per-page      which URLs earn impressions, and for which queries — written to
                growth/gsc_pages.json
  churn         how much of that serving set is the same set as yesterday's.
                The daily count cannot tell a stable 89 from a rotating sample
                of 89 out of 47,600; `stable`, `entered`, `left` and `ever` can.
                See _churn() for why this was added on 2026-08-04.
  tiers         which page family those serving URLs belong to, now and ever.
                Added 2026-08-24, when the history already in this file turned
                out to say that 258 of the 271 URLs ever served were building
                pages and 12 were hubs — the opposite of what the ledger had
                been assuming. See SERVING_TIERS.

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

# ---- which tier of the corpus actually earns impressions -------------------
#
# _churn() below separates "N pages hold their ranking" from "Google rotates N
# through a 47,600-page corpus". It still cannot answer the question that
# decides where the next content goes: WHICH pages. Its own docstring noticed
# the answer in passing on 2026-08-04 — "80 of the 89 were single-address
# building pages" — and then nobody turned it into a number, so eight weeks of
# reviews reasoned about "the hub tier" and "the building tier" from verdicts
# built on owned_visitors, which at ~2 organic clicks a day site-wide cannot
# distinguish a search arrival from an internal click.
#
# It matters because the two tiers point opposite ways. If the hubs are what
# serve, the answer is more hubs and fewer addresses. If the addresses are what
# serve, every hub-shaped proposal in the ledger is being justified by a tier
# Google has barely shown, and the honest move is to make the address pages
# survive rather than to publish another hub.
#
# Ordered, first match wins, catch-all last. Nothing is silently dropped: a URL
# matching no rule lands in "other" and shows up in the table, because a tier
# that disappears from the arithmetic is the failure mode this whole record
# exists to prevent.
SERVING_TIERS = (
    ("home",       lambda p: p == "/"),
    ("building",   lambda p: p.startswith("/building/")),
    # The NYC aggregate tier: neighborhood, borough, ZIP and the borough
    # listicles. Built by build_seo.py's main(), all carrying answer_block().
    ("nyc_hub",    lambda p: p.startswith(("/neighborhood/", "/borough/",
                                           "/zip/", "/buildings/"))),
    # The SF / LA / DC aggregate tier: /<city>/neighborhood/, /<city>/zip/,
    # /<city>/buildings/ — city_hub_docs(). Same shape, different generator.
    ("city_hub",   lambda p: p.startswith(("/sf/", "/la/", "/dc/", "/nyc/"))),
    ("council",    lambda p: p.startswith("/council-district/")),
    ("guide",      lambda p: p.startswith("/guide/")),
    # The two sections retired on 2026-08-16 for earning zero impressions.
    # Kept as their own tier so the revisit can read the claim rather than
    # inherit it.
    ("voucher",    lambda p: p.startswith(("/section8/", "/brief/"))),
    ("available",  lambda p: p.startswith("/available/")),
    ("developers", lambda p: p.startswith("/developers/")),
)
TIER_OTHER = "other"

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
    page_rows = _page_rows(pages)
    saved = _save_pages(sc, token, start, end, page_rows, by_query)
    record_owned_visibility(page_rows)

    clicks, impressions, avg_pos = sc.totals(rows)   # returns a 3-tuple, not a dict

    # Search Console's QUERY dimension silently drops anonymized (rare) queries,
    # and on a corpus of 47k single-address pages almost every query is rare. Over
    # 2026-08-05..08-12 the query dimension totalled 11 impressions and 1 click;
    # the page dimension, identical window, totalled 137 and 6. Every journal
    # entry that has ever quoted "impressions" quoted the query number, so the
    # site's real search footprint has been understated by about 12x for weeks,
    # and the CTR arithmetic built on it was wrong in both directions.
    #
    # Record the page dimension alongside it. Do NOT redefine gsc_impressions to
    # mean this: that series goes back to the start and would stop being
    # comparable to itself, and the query total is still the right number for
    # "which named queries do we appear for". Two metrics, two meanings.
    page_impressions = sum(r.get("impressions", 0) for r in page_rows)
    page_clicks = sum(r.get("clicks", 0) for r in page_rows)
    top10 = sum(1 for k in kws if (k.get("position") or 999) <= 10)
    top3 = sum(1 for k in kws if (k.get("position") or 999) <= 3)
    share = round(100.0 * top10 / len(kws), 1) if kws else 0.0

    today = ledger.today()
    for metric, value in (
            ("gsc_clicks", clicks),
            ("gsc_impressions", impressions),
            ("gsc_page_clicks", page_clicks),
            ("gsc_page_impressions", page_impressions),
            ("gsc_position", round(avg_pos, 1)),
            ("gsc_serving_pages", serving),
            ("search_share_pct", share),
            ("tracked_top10", top10),
            ("tracked_top3", top3),
            ("tracked_ranking", matched)):
        ledger.record_result(today, "__site__", metric, value)

    # ---- how much of that serving set is the same set as yesterday's.
    # gsc_serving_pages alone cannot tell 89 pages that hold their ranking
    # from a rotating sample of 89 out of 47,600 — see _churn().
    ch = (saved or {}).get("churn") or {}
    for metric in ("gsc_serving_stable", "gsc_serving_entered",
                   "gsc_serving_left", "gsc_serving_ever"):
        if ch.get(metric) is not None:
            ledger.record_result(today, "__site__", metric, ch[metric])

    # ---- and which tier those pages are. Only the daily count goes into the
    # series: `ever`, the medians and the never-served tiers are all
    # recomputable from the history in gsc_pages.json, which is committed every
    # night, so writing them nightly would be storing a derivation. A tier that
    # has never served once is not recorded at all — there is no series to
    # start until Google shows the family for the first time, and a nightly
    # zero for /developers/ is noise in a file that is read by eye.
    tiers = (saved or {}).get("serving_tiers") or {}
    for name, t in tiers.items():
        if t.get("ever"):
            ledger.record_result(today, "__site__", f"gsc_serving_{name}", t.get("now"))

    ledger.write_last_run("searchconsole", {
        "window": f"{start}..{end}", "clicks": clicks,
        "impressions": impressions, "serving_pages": serving,
        "page_clicks": page_clicks, "page_impressions": page_impressions,
        "tracked_ranking": matched, "share_pct": share,
        "serving_stable": ch.get("gsc_serving_stable"),
        "serving_ever": ch.get("gsc_serving_ever")})

    return {"clicks": clicks, "impressions": impressions,
            "page_clicks": page_clicks, "page_impressions": page_impressions,
            "serving_pages": serving, "tracked_ranking": matched,
            "top10": top10, "top3": top3, "share_pct": share,
            "serving_stable": ch.get("gsc_serving_stable"),
            "serving_ever": ch.get("gsc_serving_ever")}


def _page_rows(pages):
    """Search Console's page dimension, flattened and sorted by impressions."""
    rows = []
    for r in pages:
        url = (r.get("keys") or [""])[0]
        rows.append({"url": url, "clicks": r.get("clicks", 0),
                     "impressions": r.get("impressions", 0),
                     "position": round(r.get("position", 0), 1)})
    rows.sort(key=lambda x: -x["impressions"])
    return rows


def _path(url):
    """The path part of a served URL, so it can be matched against a prefix."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).path or "/"
    except Exception:
        return url


def owned_visibility(rows, techs=None):
    """Per-technique search visibility: which of a technique's own URLs Google
    actually serves, and how often.

    A technique declares the URL prefixes it owns; `rows` is every URL that
    earned an impression in the window. The intersection is the only
    leading indicator this site has. `owned_visitors` — the metric the 21-day
    review retires on — is a *lagging* one, and at ~2 organic clicks a day
    site-wide it has no resolution at all: every content technique reads zero
    whether it is invisible in search or ranking well for a query nobody types.
    Impressions move weeks earlier and separate those two cases.
    """
    out = {}
    for t in (techs if techs is not None else ledger.load_techniques()):
        prefixes = tuple(t.get("prefixes") or ())
        if not prefixes:
            continue
        mine = [r for r in rows if _path(r["url"]).startswith(prefixes)]
        best = min((r["position"] for r in mine if r.get("position")), default=None)
        out[t["slug"]] = {
            "pages": len(mine),
            "impressions": sum(r["impressions"] for r in mine),
            "clicks": sum(r["clicks"] for r in mine),
            "best_position": best,
        }
    return out


def record_owned_visibility(rows, date=None):
    """Fold owned_visibility() into the ledger, one row per technique+metric.

    Recorded even when it is all zeros: "this technique's pages earned no
    impressions" is the finding, and a missing row would be read as "not
    measured" by the review, which deliberately refuses to retire on that.
    """
    date = date or ledger.today()
    vis = owned_visibility(rows)
    for slug, v in vis.items():
        ledger.record_result(date, slug, "gsc_owned_pages", v["pages"])
        ledger.record_result(date, slug, "gsc_owned_impressions", v["impressions"])
        ledger.record_result(date, slug, "gsc_owned_clicks", v["clicks"])
        if v["best_position"] is not None:
            ledger.record_result(date, slug, "gsc_owned_best_position", v["best_position"])
    return vis


def recent_visibility(slug, since=None, window=7):
    """Read a technique's owned search visibility back out of the ledger.

    Takes the best of the last `window` readings rather than the latest one.
    Each reading is already a rolling 8-day Search Console window, so a single
    low day is noise — and the decision this feeds (retire or keep) should never
    turn on one flaky pull. `measured` is False when nothing has been recorded
    yet, which is not the same as zero and must not be treated as one.
    """
    def best(metric, fn=max):
        vals = [v for _, v in ledger.series(slug, metric, since=since)[-window:]]
        return fn(vals) if vals else None

    pages = best("gsc_owned_pages")
    impressions = best("gsc_owned_impressions")
    return {"measured": impressions is not None,
            "pages": pages or 0,
            "impressions": impressions or 0,
            "clicks": best("gsc_owned_clicks") or 0,
            "best_position": best("gsc_owned_best_position", min)}


# How many URLs of serving history to keep in gsc_pages.json. The file is
# committed every night, so this is a git-size decision, not a memory one: at
# ~9 newly-serving URLs a day the cap is years away, and when it is ever hit
# the least-recently-served entries go first and the count of what was dropped
# is written into the payload. A silently truncated history would read as
# "these are all the pages that have ever served", which is the exact wrong
# conclusion this whole record exists to prevent.
HISTORY_CAP = 4000


def _churn(prev, rows, today):
    """Fold today's serving set into the persistent per-URL history.

    Why this exists. On 2026-08-04 gsc_serving_pages read 89 for the second day
    running and looked like a plateau. It was not a plateau: nine URLs had
    entered the set and nine had left it overnight, and 80 of the 89 were
    single-address building pages with one or two impressions each. A count of
    distinct URLs served in a rolling window cannot tell "89 pages hold their
    ranking" from "Google rotates a sample of 89 through a 47,600-page corpus",
    and those two call for opposite decisions — the first says publish more of
    what works, the second says the corpus is too big to be crawled and should
    be consolidated. So the count is kept, and three numbers that disambiguate
    it are kept beside it:

      stable   served today AND in the previous snapshot — visibility that
               survived a day, which is the honest read on what ranks
      entered  / left   the size of the nightly rotation
      ever     distinct URLs seen serving since this record began — monotone,
               so it measures how much of the corpus Google has *ever* shown,
               which the daily count cannot

    History is {url: [first_seen, last_seen, days_seen]}. `days_seen` counts
    distinct dates, so re-running the measurement twice in a day does not
    inflate it, and churn is skipped entirely on a same-day re-run because
    comparing a snapshot against itself would report a fictional zero rotation.

    Returns (history, churn-metrics dict). Any metric it cannot honestly
    compute is left out rather than defaulted to zero, because the ledger reads
    a missing row as "not measured" and a zero as "measured, and it was zero".
    """
    hist = dict((prev or {}).get("history") or {})
    prev_date = (prev or {}).get("date")
    today_urls = {r["url"] for r in rows}

    out = {"gsc_serving_entered": None, "gsc_serving_left": None,
           "gsc_serving_stable": None, "gsc_serving_ever": None}

    # The comparison set is "URLs whose last sighting was the previous
    # snapshot", taken from history rather than from prev["pages"] — that list
    # is capped at 300 for readability and would understate churn the day the
    # serving set grows past it.
    if prev_date and prev_date != today and hist:
        prev_urls = {u for u, v in hist.items() if v and v[1] == prev_date}
        if prev_urls:
            out["gsc_serving_stable"] = len(today_urls & prev_urls)
            out["gsc_serving_entered"] = len(today_urls - prev_urls)
            out["gsc_serving_left"] = len(prev_urls - today_urls)

    for url in today_urls:
        rec = hist.get(url)
        if not rec:
            hist[url] = [today, today, 1]
        elif rec[1] != today:
            hist[url] = [rec[0], today, rec[2] + 1]

    # Evicted URLs still happened. Carry the running total forward so
    # `ever` stays monotone — a count that can go *down* because the record
    # was trimmed is worse than no count, since the only thing it is read for
    # is whether the corpus is being discovered over time.
    dropped_before = int(((prev or {}).get("churn") or {}).get("history_dropped_total") or 0)
    dropped = 0
    if len(hist) > HISTORY_CAP:
        keep = sorted(hist.items(), key=lambda kv: (kv[1][1], kv[1][2]),
                      reverse=True)[:HISTORY_CAP]
        dropped = len(hist) - len(keep)
        hist = dict(keep)
    out["gsc_serving_ever"] = len(hist) + dropped_before + dropped
    out["history_dropped"] = dropped
    out["history_dropped_total"] = dropped_before + dropped
    return hist, out


def stable_pages(limit=25):
    """URLs that have served on the most distinct days — what actually holds.

    The page-level answer to "ignore the rotation, what does this site reliably
    rank for". Empty until the history in gsc_pages.json has a few days in it.
    """
    hist = (load_pages() or {}).get("history") or {}
    rank = sorted(hist.items(), key=lambda kv: (-kv[1][2], kv[1][0]))
    return [{"url": u, "days": v[2], "first_seen": v[0], "last_seen": v[1]}
            for u, v in rank[:limit]]


def _tier(url):
    """Which page family a served URL belongs to. See SERVING_TIERS."""
    p = _path(url)
    for name, match in SERVING_TIERS:
        if match(p):
            return name
    return TIER_OTHER


def serving_tiers(rows=None, history=None):
    """Split the serving set by page family, now and over the whole record.

    Three numbers per tier, because one of them alone always misleads:

      now         distinct URLs in this tier that earned an impression in the
                  current window. This is the rotating sample, so a low number
                  is not by itself a verdict on the tier.
      ever        distinct URLs in this tier seen serving since the record
                  began. Monotone, so it is the honest read on how much of the
                  tier Google has *ever* shown — and a tier sitting at a
                  handful after weeks is one Google has declined, not one that
                  happened to miss tonight's rotation.
      days        median / max distinct days a URL in this tier held its place.
                  Separates "shown once and dropped" from "holds".

    `now` is None when rows is not supplied — the caller asked about history
    only, and a zero there would read as a measurement rather than an absence.
    Tiers with nothing in either column are still returned: "Google has never
    once served this family" is the finding, not a gap.
    """
    import statistics

    hist = history if history is not None else ((load_pages() or {}).get("history") or {})
    order = [name for name, _ in SERVING_TIERS] + [TIER_OTHER]
    out = {n: {"now": (0 if rows is not None else None), "ever": 0,
               "median_days": None, "max_days": None} for n in order}

    if rows is not None:
        for r in rows:
            out[_tier(r.get("url") or "")]["now"] += 1

    days = {n: [] for n in order}
    for url, rec in (hist or {}).items():
        n = _tier(url)
        out[n]["ever"] += 1
        # rec is [first_seen, last_seen, days_seen]; tolerate a short record
        # rather than dropping the URL out of the count it belongs in.
        if rec and len(rec) >= 3 and isinstance(rec[2], int):
            days[n].append(rec[2])
    for n in order:
        if days[n]:
            out[n]["median_days"] = round(statistics.median(days[n]), 1)
            out[n]["max_days"] = max(days[n])
    return out


def _save_pages(sc, token, start, end, rows, by_query):
    """Write growth/gsc_pages.json: the served URLs, their queries, and the
    queries we are not tracking at all.

    Kept small deliberately. The whole point is that a person or an agent reads
    it and decides something, and a 5,000-row dump of every long-tail
    impression does not get read.
    """
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

    today = ledger.today()
    # Read the previous snapshot before overwriting it: it carries the serving
    # history, and losing it would reset "ever" to today's count every night.
    history, churn = _churn(load_pages(), rows, today)

    payload = {
        "date": today,
        "window": f"{start}..{end}",
        "serving_pages": len(rows),
        "churn": churn,
        # Computed against the history this run just folded today's rows into,
        # not the previous snapshot, so `now` and `ever` are the same night.
        "serving_tiers": serving_tiers(rows, history),
        "history": history,
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

    Aggregate pages sort ahead of single-address building pages even when they
    have fewer impressions. A building page's only query is its own street
    address (measured 2026-07-30: 75 served building pages, 1.4 impressions
    each over eight days), so moving one from position 12 to position 1 wins a
    fraction of a click a week — the ranking is not the constraint, the query
    volume is. Address pages stay in the list rather than being hidden, because
    the count of them is itself the finding.
    """
    data = load_pages()
    out = [p for p in data.get("pages", [])
           if HEADROOM_MIN <= (p.get("position") or 999) <= HEADROOM_MAX
           and p.get("impressions", 0) > 0]
    return sorted(out, key=lambda p: (_path(p["url"]).startswith("/building/"),
                                      -p["impressions"]))[:limit]


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
