#!/usr/bin/env python3
"""Daily measurement: traffic, funnel, revenue — and attribution to techniques.

Everything the review loop judges comes from here. Two rules keep the year-end
"what worked" list honest:

  1. A technique is credited only for traffic landing on the URL prefixes it
     declares. Site-wide techniques (indexing, AI-crawler work) are judged on a
     global series instead, and the ledger says which.
  2. The owner's own visits are excluded everywhere, matching traffic_report.py.
     Without that, a day spent testing looks like growth.

Reads Supabase over PostgREST with the service-role key. Volumes are small
(hundreds of rows a day), so aggregation happens in Python rather than in SQL —
one fetch, many derived series, no RPC to keep in sync.
"""
import datetime
import json
import os
import urllib.parse
import urllib.request

from . import ledger

# The owner's own account + the anonymous visitors tied to it. Mirrors the
# exclusion in traffic_report.py; without it every metric is inflated.
OWNER_USER_ID = "af2629f7-1121-4bee-8a2b-cede9318c864"

SEARCH_HOSTS = ("google.", "bing.com", "duckduckgo.com", "yahoo.", "ecosia.org",
                "search.brave.com", "yandex.", "baidu.com", "startpage.com")
AI_HOSTS = ("chatgpt.com", "chat.openai.com", "openai.com", "perplexity.ai",
            "claude.ai", "anthropic.com", "copilot.microsoft.com", "gemini.google.com",
            "bard.google.com", "you.com", "phind.com")

# How long a visitor has to have been absent to count as "new".
#
# Thirty days is a choice, not a free parameter. The fac_vid cookie is set by
# nginx (index.html:2323), so it survives Safari's 7-day cap on script-written
# storage and a month is comfortably inside its life; and a month of one narrow
# column is a cheap nightly query.
#
# The window is in the metric NAME on purpose. "new_visitors" would be read, six
# months from now by someone with no memory of today, as "never seen before" —
# which this is not and cannot be: this loop can only see as far back as it
# queries. Both constants below are derived from the one number so the name and
# the window can never drift apart.
NEW_VISITOR_LOOKBACK_DAYS = 30
NEW_VISITORS_METRIC = f"new_visitors_{NEW_VISITOR_LOOKBACK_DAYS}d"
RETURNING_VISITORS_METRIC = f"returning_visitors_{NEW_VISITOR_LOOKBACK_DAYS}d"


def _env(name, *alts):
    for n in (name,) + alts:
        v = os.environ.get(n)
        if v:
            return v
    return None


class Supabase:
    def __init__(self, url=None, key=None):
        self.url = (url or _env("SUPABASE_URL", "RENTMAP_SUPABASE_URL") or "").rstrip("/")
        self.key = key or _env("SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE",
                               "RENTMAP_SUPABASE_SERVICE_KEY")
        if not self.url or not self.key:
            raise RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY to measure")

    def select(self, table, params, page=1000):
        """Paged PostgREST select. Returns all rows."""
        out = []
        offset = 0
        while True:
            qs = dict(params)
            qs["limit"] = page
            qs["offset"] = offset
            req = urllib.request.Request(
                f"{self.url}/rest/v1/{table}?{urllib.parse.urlencode(qs)}",
                headers={"apikey": self.key, "Authorization": f"Bearer {self.key}",
                         "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                batch = json.loads(r.read().decode())
            out.extend(batch)
            if len(batch) < page:
                return out
            offset += page


def _host(ref):
    if not ref:
        return None
    try:
        return (urllib.parse.urlparse(ref).hostname or "").lower()
    except Exception:
        return None


def _entry_src(path):
    """The channel tag on an entry URL, or "".

    Two tagging schemes reach this site and both land in visits.path:

      utm_source=  the standard one. AI engines increasingly send no referrer
                   header and tag the URL instead — that is how chatgpt.com
                   traffic shows up at all.
      src=         this site's own. nginx serves /tt, /ig, /yt and /rd as 302s
                   to /?src=<channel>, which is the ONLY attribution that
                   survives a link pasted into a social app: the reader arrives
                   with no referrer, so an untagged share is indistinguishable
                   from a bookmark. channel_report.py has read these since it
                   was written; classify() honoured utm_source alone, so every
                   visit from the one channel this site can actually track was
                   filed as "direct" — invisible to the loop that decides what
                   to do more of.
    """
    if not path or ("utm_source=" not in path and "src=" not in path):
        return ""
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse("http://x" + path).query)
    except Exception:
        return ""
    for key in ("utm_source", "src"):
        v = (q.get(key) or [""])[0].strip().lower()
        if v:
            return v[:24]
    return ""


def classify(referrer, path):
    """Which channel did this visit come from?"""
    # An explicit tag wins over the referrer header, which is usually absent.
    src = _entry_src(path)
    if src:
        if any(a.split(".")[0] in src for a in AI_HOSTS):
            return "ai"
        return "campaign"
    h = _host(referrer)
    if not h:
        return "direct"
    if any(a in h for a in AI_HOSTS):
        return "ai"
    if any(a in h for a in SEARCH_HOSTS):
        return "organic"
    if "findacrib.com" in h:
        return "internal"
    return "referral"


def _entry_rows(day_visits):
    """One row per visitor: the FIRST visit they made that day.

    A landing page is where somebody arrived, not every page they then opened,
    and a channel is decided by that first hit too — the second pageview of a
    session carries a findacrib.com referrer and would otherwise re-file the
    same person as "internal".
    """
    first = {}
    for v in sorted(day_visits, key=lambda r: str(r.get("created_at") or "")):
        vid = v.get("visitor_id")
        if vid and vid not in first:
            first[vid] = v
    return list(first.values())


def _clean_path(path):
    """Landing path without its query string, so ?src= tags do not split it."""
    p = (path or "/").split("?")[0].split("#")[0] or "/"
    return p[:80]


def census(day_visits, top=6, prior_vids=None):
    """Where one day's visitors entered, what sent them, and how many are new.

    Plain counts of distinct visitors, computed from rows already fetched — no
    extra query, so this cannot fail the day's measurement. Written into
    last_run.json (which is committed) rather than state.json (which is not),
    because the point of it is that a LATER review can read it: on 2026-09-06
    the site had its largest day ever — 247 visitors, 198 of them "direct" —
    and nothing anywhere recorded where they landed or what sent them.

    `prior_vids` is the set of visitor ids seen in the previous
    NEW_VISITOR_LOOKBACK_DAYS days, handed IN by collect() — this function still
    issues no query of its own. Pass None (the default, and what collect() does
    when its lookback query fails) and the new/returning keys are simply absent,
    which is the honest reading; a caller must never substitute an empty set,
    because that reports every visitor as new.
    """
    entries = _entry_rows(day_visits)
    chan, src, paths, refs = {}, {}, {}, {}
    deep = 0
    for v in entries:
        c = classify(v.get("referrer"), v.get("path"))
        chan[c] = chan.get(c, 0) + 1
        # A referrer-less arrival on a deep URL is a shared link: nobody types
        # /building/2023190002 or bookmarks it before they have been sent it.
        # A referrer-less arrival on "/" is genuinely ambiguous — typed,
        # bookmarked, or shared — so it is left out. This is a FLOOR under
        # link-sharing, never a total, and must not be reported as one.
        if c == "direct" and _clean_path(v.get("path")) not in ("/", "/index.html"):
            deep += 1
        t = _entry_src(v.get("path"))
        if t:
            src[t] = src.get(t, 0) + 1
        p = _clean_path(v.get("path"))
        paths[p] = paths.get(p, 0) + 1
        h = _host(v.get("referrer"))
        if h and "findacrib.com" not in h:
            refs[h] = refs.get(h, 0) + 1

    def rank(d):
        return [[k, n] for k, n in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]

    out = {"visitors": len(entries), "by_channel": dict(sorted(chan.items())),
           "by_src": dict(sorted(src.items())), "direct_deep": deep,
           "top_paths": rank(paths), "top_referrers": rank(refs)}
    if prior_vids is not None:
        vids = {v.get("visitor_id") for v in entries if v.get("visitor_id")}
        out["returning"] = len(vids & prior_vids)
        out["new"] = len(vids - prior_vids)
        out["new_window_days"] = NEW_VISITOR_LOOKBACK_DAYS
    return out


def _prior_visitor_ids(sb, before, days=NEW_VISITOR_LOOKBACK_DAYS):
    """Every visitor_id seen in the `days` before the ISO date `before`.

    One narrow column, paged by Supabase.select(), so nothing is silently
    truncated the way a single capped request would be — a truncated prior set
    would report the visitors it failed to fetch as brand new, which is exactly
    the direction of error that flatters the site.
    """
    lo = (datetime.date.fromisoformat(before) - datetime.timedelta(days=days)).isoformat()
    rows = sb.select("visits", {"select": "visitor_id",
                                "created_at": f"gte.{lo}",
                                "and": f"(created_at.lt.{before})"})
    return {r["visitor_id"] for r in rows if r.get("visitor_id")}


def collect(days=1, sb=None, end=None):
    """Measure the last `days` complete days. Returns {date: {metric: value}}.

    Default is yesterday only — today is still in progress, and a partial day
    recorded as a data point would poison every trend the review loop reads.
    """
    sb = sb or Supabase()
    end = end or (datetime.date.today() - datetime.timedelta(days=1))
    start = end - datetime.timedelta(days=days - 1)
    lo = start.isoformat()
    hi = (end + datetime.timedelta(days=1)).isoformat()

    visits = sb.select("visits", {
        "select": "visitor_id,user_id,path,referrer,created_at",
        "created_at": f"gte.{lo}", "and": f"(created_at.lt.{hi})"})
    events = sb.select("events", {
        "select": "visitor_id,user_id,event,path,created_at",
        "created_at": f"gte.{lo}", "and": f"(created_at.lt.{hi})"})

    # Owner exclusion: the owner's user_id, plus every visitor_id ever seen
    # signed in as the owner (their anonymous visits carry no user_id).
    owner_vids = set(ledger.get_state("owner_visitor_ids", []))
    for v in visits:
        if v.get("user_id") == OWNER_USER_ID and v.get("visitor_id"):
            owner_vids.add(v["visitor_id"])
    for e in events:
        if e.get("user_id") == OWNER_USER_ID and e.get("visitor_id"):
            owner_vids.add(e["visitor_id"])
    ledger.set_state("owner_visitor_ids", sorted(owner_vids))

    def keep(row):
        return row.get("user_id") != OWNER_USER_ID and row.get("visitor_id") not in owner_vids

    visits = [v for v in visits if keep(v)]
    events = [e for e in events if keep(e)]

    # New vs returning — the fork this loop could not read on 2026-09-07.
    # 380 visitors that day, 376 of them landing on "/", nothing shared, nothing
    # ranking and non-branded impressions still zero. That is either word of
    # mouth bringing new people in (brand demand compounding, so find the source
    # and feed it) or the same audience coming back (one event, decaying, so
    # stop treating the median as growth). Those point at opposite next actions
    # and nothing in this repo told them apart.
    #
    # One extra query, and the only one in collect() that is allowed to fail
    # without taking the day with it. On failure `prior` stays None and both
    # metrics are omitted — an absent day is honest, and the tempting
    # `except: prior = set()` would have published every visitor as new, which
    # would read as the best news this site has ever had.
    try:
        prior = _prior_visitor_ids(sb, lo) - owner_vids
    except Exception:
        prior = None

    techs = ledger.load_techniques()
    prefixed = [(t["slug"], t.get("prefixes") or []) for t in techs if t.get("prefixes")]

    out = {}
    for i in range(days):
        d = (start + datetime.timedelta(days=i)).isoformat()
        dv = [v for v in visits if (v["created_at"] or "")[:10] == d]
        de = [e for e in events if (e["created_at"] or "")[:10] == d]

        chan = {}
        for v in dv:
            chan.setdefault(classify(v.get("referrer"), v.get("path")), set()).add(v["visitor_id"])

        m = {
            "visitors": len({v["visitor_id"] for v in dv}),
            "pageviews": len(dv),
            "organic_visitors": len(chan.get("organic", ())),
            "ai_visitors": len(chan.get("ai", ())),
            "direct_visitors": len(chan.get("direct", ())),
            "referral_visitors": len(chan.get("referral", ())),
            "campaign_visitors": len(chan.get("campaign", ())),
        }
        for name in ("building_view", "search", "save", "signin", "outbound"):
            ev = [e for e in de if e.get("event") == name]
            m[f"ev_{name}"] = len(ev)
            m[f"ev_{name}_visitors"] = len({e["visitor_id"] for e in ev if e.get("visitor_id")})

        # Where they entered and what sent them. `_census` is not a
        # measurement — record_day() skips underscore keys — it is carried out
        # to cmd_measure, which files it in last_run.json where a later review
        # can still read it. The per-tag counts beside it ARE a series, one
        # metric per channel actually seen, so a tagged campaign that works
        # leaves fourteen days of evidence instead of one line in a report.
        cen = census(dv, prior_vids=prior)
        m["_census"] = cen
        m["direct_deep_visitors"] = cen["direct_deep"]
        if prior is not None:
            m[RETURNING_VISITORS_METRIC] = cen["returning"]
            m[NEW_VISITORS_METRIC] = cen["new"]
            # A multi-day window scores each day against everything before it,
            # this window's own earlier days included — otherwise somebody who
            # arrived on day 1 and came back on day 3 is counted as new twice.
            prior = prior | {v["visitor_id"] for v in dv if v.get("visitor_id")}
        for tag, n in cen["by_src"].items():
            m["src_" + "".join(c for c in tag if c.isalnum() or c in "-_")] = n

        # per-technique owned traffic
        for slug, prefixes in prefixed:
            vids = {v["visitor_id"] for v in dv
                    if any((v.get("path") or "").startswith(p) for p in prefixes)}
            m[f"owned::{slug}"] = len(vids)

        out[d] = m
    return out


# ------------------------------------------------------------------ revenue
#
# Until 2026-08-26 revenue was, in full: `mrr_usd = paying_subs * 4.99`. That
# is the price of the legacy Plus subscription and of nothing else this site
# sells, so the number was structurally blind to both products that were
# actually launched:
#
#   * the Developer API tiers. Their checkout lives in api_server.py and sets
#     api_keys.tier through the api_set_tier RPC — it never touches the
#     `subscriptions` table, so a $199/mo Business key would have been counted
#     as $0.00 and the loop would have kept reporting "no measurable lift".
#   * the one-time $9 Building Report. It has no recurring component at all,
#     so no amount of MRR arithmetic can ever see it, and T011 — a technique
#     whose entire audience is Building Report buyers — was being judged on
#     mrr_usd. It could not have registered its own revenue if it had worked
#     perfectly.
#
# Prices are the published ones and every figure here is sourced in-repo, not
# from memory: index.html offers "Get the full building report — $9";
# api_server.py sells tiers "pro" and "business"; the Plus subscription is the
# $4.99 plan the stripe-webhook function writes as plan="plus". If a price
# changes on the site, change it here in the same commit — a stale number here
# does not fail loudly, it quietly misreports the goal.
PLUS_MRR_USD = 4.99
API_TIER_MRR_USD = {"pro": 49.0, "business": 199.0}
REPORT_PRICE_USD = 9.0

# mrr_usd stays strictly RECURRING so its year of history keeps meaning the
# same thing. One-time sales are reported beside it, and revenue_usd_30d is the
# number to read against the $10,000/month goal, because that goal is about
# money arriving in a month, not about subscriptions specifically.


def _count_api_tiers(sb):
    """Paid API keys by tier. Returns {} if the tier column is not readable."""
    try:
        rows = sb.select("api_keys", {"select": "id,tier,status"})
    except Exception:
        return {}
    out = {}
    for r in rows:
        if str(r.get("status") or "active") not in ("active", "", "None"):
            continue
        tier = str(r.get("tier") or "free")
        if tier in API_TIER_MRR_USD:
            out[tier] = out.get(tier, 0) + 1
    return out


def _report_sales(sb, today=None):
    """(lifetime paid reports, paid in the trailing 30 days).

    building_reports is service-role only and carries no amount column — the
    price is the single published one, so units times price is exact rather
    than an estimate.
    """
    rows = sb.select("building_reports", {"select": "status,paid_at"})
    paid = [r for r in rows if r.get("status") == "paid"]
    today = today or datetime.date.today()
    cutoff = (today - datetime.timedelta(days=30)).isoformat()
    recent = [r for r in paid if str(r.get("paid_at") or "")[:10] >= cutoff]
    return len(paid), len(recent)


def snapshot_totals(sb=None):
    """Point-in-time totals against the standing goals: users and revenue.

    Every query beyond the two that have always worked is wrapped: a schema
    surprise on a new table must not cost the day its visitors, its signups
    and its subscription count. A missing extra reads as absent, not as zero
    — except the sales counts, where a real zero is the whole point and is
    reported as zero only when the table was actually read.
    """
    sb = sb or Supabase()
    users = sb.select("subscriptions", {"select": "user_id,status,plan,stripe_subscription_id"})
    paying = [u for u in users
              if u.get("status") == "active" and u.get("stripe_subscription_id")
              and u.get("user_id") != OWNER_USER_ID]
    comped = [u for u in users if u.get("status") == "active" and not u.get("stripe_subscription_id")]
    saved = sb.select("saved_buildings", {"select": "user_id"})
    try:
        api_keys = sb.select("api_keys", {"select": "id"})
    except Exception:
        api_keys = []

    tiers = _count_api_tiers(sb)
    api_mrr = sum(API_TIER_MRR_USD[k] * n for k, n in tiers.items())

    out = {
        "paying_subs": len(paying),
        "comped_subs": len(comped),
        "mrr_usd": round(len(paying) * PLUS_MRR_USD + api_mrr, 2),
        "accounts_with_saves": len({s["user_id"] for s in saved if s.get("user_id")}),
        "api_keys": len(api_keys),
    }
    for tier in API_TIER_MRR_USD:
        out[f"api_keys_{tier}"] = tiers.get(tier, 0)

    try:
        sold, sold_30d = _report_sales(sb)
    except Exception:
        return out                      # table unreadable: say nothing rather than "0 sold"
    out["reports_sold"] = sold
    out["reports_sold_30d"] = sold_30d
    out["revenue_usd_30d"] = round(out["mrr_usd"] + sold_30d * REPORT_PRICE_USD, 2)
    return out


def record_day(date, m):
    """Write one day's measurements into the ledger, attributing where we can."""
    for k, v in m.items():
        if k.startswith("_"):
            continue            # carried out to the caller, not a measurement
        if k.startswith("owned::"):
            ledger.record_result(date, k.split("::", 1)[1], "owned_visitors", v)
        else:
            ledger.record_result(date, "__site__", k, v)


def collect_and_record(days=1, sb=None):
    sb = sb or Supabase()
    data = collect(days=days, sb=sb)
    for d, m in sorted(data.items()):
        record_day(d, m)
    totals = snapshot_totals(sb)
    today = ledger.today()
    for k, v in totals.items():
        ledger.record_result(today, "__site__", k, v)
    return data, totals
