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


def classify(referrer, path):
    """Which channel did this visit come from?"""
    # An explicit utm_source wins — AI engines increasingly send no referrer
    # header and tag the URL instead (that is how chatgpt.com traffic shows up).
    if path and "utm_source=" in path:
        try:
            src = urllib.parse.parse_qs(urllib.parse.urlparse("http://x" + path).query
                                        ).get("utm_source", [""])[0].lower()
        except Exception:
            src = ""
        if any(a.split(".")[0] in src for a in AI_HOSTS):
            return "ai"
        if src:
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

        # per-technique owned traffic
        for slug, prefixes in prefixed:
            vids = {v["visitor_id"] for v in dv
                    if any((v.get("path") or "").startswith(p) for p in prefixes)}
            m[f"owned::{slug}"] = len(vids)

        out[d] = m
    return out


def snapshot_totals(sb=None):
    """Point-in-time totals against the standing goals: users and revenue."""
    sb = sb or Supabase()
    users = sb.select("subscriptions", {"select": "user_id,status,plan,stripe_subscription_id"})
    paying = [u for u in users
              if u.get("status") == "active" and u.get("stripe_subscription_id")
              and u.get("user_id") != OWNER_USER_ID]
    comped = [u for u in users if u.get("status") == "active" and not u.get("stripe_subscription_id")]
    saved = sb.select("saved_buildings", {"select": "user_id"})
    api_keys = sb.select("api_keys", {"select": "id"})
    return {
        "paying_subs": len(paying),
        "comped_subs": len(comped),
        "mrr_usd": round(len(paying) * 4.99, 2),
        "accounts_with_saves": len({s["user_id"] for s in saved if s.get("user_id")}),
        "api_keys": len(api_keys),
    }


def record_day(date, m):
    """Write one day's measurements into the ledger, attributing where we can."""
    for k, v in m.items():
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
