#!/usr/bin/env python3
"""Anthropic API spend and usage for the dashboard's Claude tab.

WHY THIS EXISTS
---------------
The thing that has actually broken this account's crons was not an empty
balance — it was a self-imposed spend cap. On 2026-07-28 credit was topped up,
the growth engines ran, and within the same day the cap tripped; NEMO's 06:00
scout failed with "You have reached your specified API usage limits. You will
regain access on 2026-08-01." A top-up does nothing against that. The point of
this tab is to see it coming.

WHAT THE API CAN AND CANNOT TELL US
-----------------------------------
Three Admin API endpoints are read here:

    GET /v1/organizations/cost_report              daily USD, 1d buckets only
    GET /v1/organizations/usage_report/messages    tokens, 1m/1h/1d buckets
    GET /v1/organizations/rate_limits              configured RPM/TPM

There is NO public endpoint for the remaining credit balance or for the
configured spend cap. That is the honest limit of this tab: `cost_report` gives
spend-to-date, and the cap it is measured against is CLAUDE_MONTHLY_CAP_USD, a
number a human types into the environment. If the cap is changed in the Console
and not here, this tab is wrong — so the payload carries `cap_is_manual: true`
and the UI says where the number came from rather than implying it was read.

CREDENTIALS
-----------
Requires an ADMIN key (`sk-ant-admin01-…`) in ANTHROPIC_ADMIN_KEY, created by an
org admin in the Console. The regular keys the apps send messages with are
rejected here, and an admin key is rejected by the Messages API — they are
disjoint. The Admin API is also unavailable to individual (non-organization)
accounts. When the key is absent this module returns ok=False with a reason
rather than raising, so the tab renders a "not configured" state instead of a
500 and the rest of the dashboard is unaffected.

These calls are not token-billed, so polling them costs nothing. The docs
support once-a-minute polling; the cache below is far more conservative.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.anthropic.com/v1/organizations"
VERSION = "2023-06-01"
UA = "findacrib-dashboard/1.0 (+https://findacrib.com)"
TIMEOUT = 25

# The cap is not readable from the API — see the module docstring. Set
# CLAUDE_MONTHLY_CAP_USD to whatever the Console's spend limit says.
CAP_USD = float(os.environ.get("CLAUDE_MONTHLY_CAP_USD") or 0)

# Cost data lands within ~5 minutes. Ten minutes of cache keeps the tab honest
# while making a dashboard reload free.
TTL = 600
_CACHE = {"at": 0, "payload": None}


def _key():
    return (os.environ.get("ANTHROPIC_ADMIN_KEY") or "").strip()


def _get(path, params):
    """One Admin API GET. Returns (data, error_string)."""
    url = f"{API}/{path}?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={
        "x-api-key": _key(),
        "anthropic-version": VERSION,
        "User-Agent": UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        # 401 here almost always means a regular key was pasted in place of an
        # admin key — worth saying so plainly rather than "unauthorized".
        if e.code in (401, 403):
            return None, ("not authorized — ANTHROPIC_ADMIN_KEY must be an "
                          "ADMIN key (sk-ant-admin01-…) from Console → "
                          "Settings, not a regular API key")
        return None, f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _pages(path, params, cap=12):
    """Follow `next_page` until exhausted or `cap` pages, whichever first."""
    out, page, err = [], None, None
    for _ in range(cap):
        p = dict(params)
        if page:
            p["page"] = page
        d, err = _get(path, p)
        if err:
            return out, err
        out += d.get("data") or []
        if not d.get("has_more"):
            return out, None
        page = d.get("next_page")
        if not page:
            return out, None
    return out, None


def _month_window(now=None):
    """Current UTC billing month, plus the day counts the UI needs."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt, (now - start).days + 1, (nxt - now).days


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cents_to_usd(v):
    """Cost amounts come back as decimal strings. The docs describe them as
    'lowest units (cents)' but the values returned are already dollars, so this
    parses defensively and never multiplies — a wrong scale here would put a
    100x error on the headline number."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def build():
    if not _key():
        return {"ok": False,
                "reason": "no_key",
                "message": "Set ANTHROPIC_ADMIN_KEY (an admin key from "
                           "Console → Settings → Organization) on the API "
                           "service to enable this tab."}

    now = datetime.now(timezone.utc)
    start, nxt, days_in, days_left = _month_window(now)
    # 31 buckets is the documented maximum for 1d granularity.
    since = min(start, now - timedelta(days=30))

    rows, err = _pages("cost_report", {
        "starting_at": _iso(since),
        "ending_at": _iso(now),
        "group_by[]": "description",
        "limit": 31,
    })
    if err:
        return {"ok": False, "reason": "cost_failed", "message": err}

    # --- daily spend, and the slice of it inside this billing month ---------
    by_day, by_desc = {}, {}
    for b in rows:
        day = (b.get("starting_at") or "")[:10]
        for item in (b.get("results") or []):
            amt = _cents_to_usd(item.get("amount"))
            if not amt:
                continue
            by_day[day] = by_day.get(day, 0.0) + amt
            desc = item.get("description") or "Other"
            by_desc[desc] = by_desc.get(desc, 0.0) + amt

    month_key = start.strftime("%Y-%m")
    mtd = round(sum(v for d, v in by_day.items() if d.startswith(month_key)), 2)
    spark = [{"date": d, "usd": round(v, 4)} for d, v in sorted(by_day.items())]
    recent = [v for d, v in sorted(by_day.items())][-7:]
    per_day = (sum(recent) / len(recent)) if recent else 0.0

    # --- tokens, for the "what is spending it" half -------------------------
    tok_rows, tok_err = _pages("usage_report/messages", {
        "starting_at": _iso(max(since, now - timedelta(days=7))),
        "ending_at": _iso(now),
        "group_by[]": "model",
        "bucket_width": "1d",
        "limit": 7,
    })
    models = {}
    if not tok_err:
        for b in tok_rows:
            for item in (b.get("results") or []):
                m = item.get("model") or "unknown"
                e = models.setdefault(m, {"model": m, "in": 0, "out": 0,
                                          "cache_read": 0, "cache_write": 0})
                e["in"] += (item.get("uncached_input_tokens") or 0)
                e["out"] += (item.get("output_tokens") or 0)
                e["cache_read"] += (item.get("cache_read_input_tokens") or 0)
                e["cache_write"] += (item.get("cache_creation_input_tokens") or 0)
    models = sorted(models.values(), key=lambda m: -(m["in"] + m["out"]))[:8]

    # --- configured rate limits (the OTHER kind of "limit") -----------------
    rl_rows, rl_err = _pages("rate_limits", {"limit": 20}, cap=3)

    cap = CAP_USD
    pct = round(100 * mtd / cap, 1) if cap else None
    # Straight-line projection from the last 7 days. Stated as an estimate in
    # the UI, because a projection presented as a fact is how a dashboard lies.
    projected = round(mtd + per_day * max(0, days_left), 2) if per_day else mtd

    return {
        "ok": True,
        "generated_at": int(time.time()),
        "month": month_key,
        "mtd_usd": mtd,
        "cap_usd": cap or None,
        "cap_is_manual": True,
        "pct_of_cap": pct,
        "days_elapsed": days_in,
        "days_left": days_left,
        "avg_per_day_7d": round(per_day, 2),
        "projected_month_usd": projected,
        "over_cap_on": None if not cap or per_day <= 0 or mtd >= cap else round(
            (cap - mtd) / per_day, 1),
        "by_description": sorted(
            [{"description": k, "usd": round(v, 2)} for k, v in by_desc.items()],
            key=lambda x: -x["usd"])[:8],
        "sparkline": spark[-30:],
        "models": models,
        "models_error": tok_err,
        "rate_limits": rl_rows if not rl_err else [],
        "rate_limits_error": rl_err,
    }


def build_cached():
    now = time.time()
    if _CACHE["payload"] and now - _CACHE["at"] < TTL:
        return _CACHE["payload"]
    p = build()
    # Never cache a transport failure: a blip would otherwise pin the tab to an
    # error for the whole TTL. A missing key IS stable, so that one caches.
    if p.get("ok") or p.get("reason") == "no_key":
        _CACHE.update(at=now, payload=p)
    return p


if __name__ == "__main__":
    print(json.dumps(build(), indent=1)[:4000])
