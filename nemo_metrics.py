#!/usr/bin/env python3
"""NEMO Seamless Gutter traffic, for the owner dashboard's second tab.

Both sites live on this droplet, so the Find A Crib API can read NEMO's numbers
directly instead of standing up a second dashboard app. The dashboard renders
whichever payload it is given through the same template; this module's job is to
hand it NEMO data in the shape that template already understands.

Three sources, in the order they are trusted:

  growth/results.jsonl   the append-only daily ledger the 6am growth engine
                         writes. Bot-filtered, owner-IP-filtered, already
                         judged — this is the history.
  nginx access log       parsed live for TODAY only, because the ledger is
                         written once a morning for the *previous* day and a
                         dashboard that says "live" must not be 18 hours stale.
  growth/snapshot.json   rank/GSC/goal state, refreshed each morning.

Today's live number is computed by importing NEMO's own growth.metrics rather
than reimplementing its bot regex and channel rules here — two copies of that
logic would drift, and then the dashboard and the morning report would disagree
about the same day. The import is done by file path under a private module name
(`nemo_growth`) because this API's own repo also contains a `growth` package;
a plain `import growth.metrics` would resolve to the wrong one.

Nothing here reads customer rows. Bookings and leads are counted, never listed:
this endpoint returns no names, phones or addresses.
"""
import datetime
import importlib.util
import json
import os
import sqlite3
import sys
import threading
import time

NEMO_ROOT = os.environ.get("NEMO_ROOT", "/var/www/nemo-seamless-gutter")
RESULTS = os.path.join(NEMO_ROOT, "growth", "results.jsonl")
SNAPSHOT = os.path.join(NEMO_ROOT, "growth", "snapshot.json")
BOOKINGS_DB = os.environ.get("NEMO_BOOKINGS_DB",
                             os.path.join(NEMO_ROOT, "server", "bookings.sqlite"))

# Parsing a day of access log on every dashboard load would make the page slow
# and the log re-read pointless — the numbers only move as fast as traffic does.
CACHE_TTL = 120
_CACHE = {"at": 0.0, "data": None}
_LOCK = threading.Lock()

CHANNELS = [
    ("organic", "Organic search", "#eda100"),
    ("local", "Local listings / maps", "#1baf7a"),
    ("ai", "AI assistants", "#8a5cf0"),
    ("direct", "Direct / typed-in", "#2a78d6"),
    ("referral", "Other referral", "#e87ba4"),
    ("campaign", "Tagged campaign", "#eb6834"),
    ("internal", "Internal / same-site", "#9a99a5"),   # derived, see build()
]


# ---------------------------------------------------------------- ledger read
def _daily_series():
    """{date: {metric: value}} for site-wide metrics, oldest first."""
    out = {}
    try:
        with open(RESULTS) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("technique") != "__site__":
                    continue
                # Append-only file: a later line for the same (date, metric)
                # is a correction, so last write wins.
                out.setdefault(r["date"], {})[r["metric"]] = r.get("value")
    except FileNotFoundError:
        return {}
    return out


def _snapshot():
    try:
        with open(SNAPSHOT) as f:
            return json.load(f)
    except Exception:
        return {}


# ------------------------------------------------------------------ live day
def _nemo_growth_metrics():
    """Import NEMO's growth.metrics under a private name, or None."""
    pkg_dir = os.path.join(NEMO_ROOT, "growth")
    init = os.path.join(pkg_dir, "__init__.py")
    if not os.path.exists(init):
        return None
    name = "nemo_growth"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, init, submodule_search_locations=[pkg_dir])
        if spec is None or spec.loader is None:
            return None
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[name] = pkg
        try:
            spec.loader.exec_module(pkg)
        except Exception:
            sys.modules.pop(name, None)
            return None
    try:
        return importlib.import_module(name + ".metrics")
    except Exception:
        return None


def _today_live():
    """Today so far, straight from the access log. ({} if unavailable.)"""
    m = _nemo_growth_metrics()
    if m is None:
        return {}
    today = datetime.date.today()
    try:
        data = m.collect(days=1, end=today)
    except Exception:
        return {}
    return data.get(today.isoformat(), {})


def _all_time_leads():
    """Bookings and phone leads ever taken. Counts only — no customer rows.

    Delegates to NEMO's own lead_totals when it imports, so the dashboard and
    the morning report apply the same owner/test-row exclusions. The direct
    read below is the fallback and deliberately counts everything: better an
    obviously-too-high number than a silently different one.
    """
    m = _nemo_growth_metrics()
    if m is not None:
        try:
            return m.lead_totals()
        except Exception:
            pass
    out = {"bookings_all_time": 0, "phone_leads_all_time": 0}
    if not os.path.exists(BOOKINGS_DB):
        return out
    try:
        con = sqlite3.connect(f"file:{BOOKINGS_DB}?mode=ro", uri=True, timeout=5)
    except Exception:
        return out
    try:
        for table, key in (("bookings", "bookings_all_time"),
                           ("leads", "phone_leads_all_time")):
            try:
                out[key] = con.execute(f"select count(*) from {table}").fetchone()[0]
            except sqlite3.Error:
                pass
    finally:
        con.close()
    return out


# ------------------------------------------------------------------ assembly
def _n(x):
    return x if isinstance(x, (int, float)) else 0


def build(days=14):
    """The dashboard view model for NEMO."""
    hist = _daily_series()
    today_key = datetime.date.today().isoformat()
    live = _today_live()
    warnings = []
    if not live:
        warnings.append("Today's live traffic could not be read from the access log.")

    # History, excluding today — today comes from the live parse so the two
    # never double-count the same visitors.
    traffic_days = sorted(d for d, m in hist.items()
                          if "visitors" in m and d != today_key)
    rows = [{"date": d,
             "visitors": _n(hist[d].get("visitors")),
             "views": _n(hist[d].get("pageviews"))} for d in traffic_days]
    if live:
        rows.append({"date": today_key,
                     "visitors": _n(live.get("visitors")),
                     "views": _n(live.get("pageviews"))})

    spark = rows[-days:]

    totals = {
        "visitors": sum(r["visitors"] for r in rows),
        "views": sum(r["views"] for r in rows),
        "bots": sum(_n(hist[d].get("bot_hits")) for d in traffic_days) + _n(live.get("bot_hits")),
    }

    channels = {}
    for key, _name, _hex in CHANNELS:
        if key == "internal":
            continue
        channels[key] = sum(_n(hist[d].get(key + "_visitors")) for d in traffic_days) \
            + _n(live.get(key + "_visitors"))
    # NEMO's growth engine classifies a same-site referrer as "internal" but
    # doesn't record that series, so the six named channels come up short of the
    # visitor count. The remainder is that bucket — derived rather than dropped,
    # so the donut adds up to the number on the tile instead of quietly losing
    # a third of the traffic.
    channels["internal"] = max(0, totals["visitors"] - sum(channels.values()))

    # Leads: the ledger has a per-day series, the database has the truth about
    # all-time. Both are shown, because "2 bookings ever" and "0 today" answer
    # different questions.
    leads_days = sorted(d for d, m in hist.items() if "total_leads" in m and d != today_key)
    period_bookings = sum(_n(hist[d].get("bookings")) for d in leads_days) + _n(live.get("bookings"))
    period_phone = sum(_n(hist[d].get("phone_leads")) for d in leads_days) + _n(live.get("phone_leads"))
    all_time = _all_time_leads()

    snap = _snapshot()
    goal = snap.get("goal") or {}
    gsc = snap.get("gsc") or {}
    pages = snap.get("pages") or {}
    page_counts = {k: len(v) for k, v in pages.items() if isinstance(v, list)}
    last_build = snap.get("last_build") or {}

    return {
        "site": "nemo",
        "domain": snap.get("site") or "nemoseamlessgutter.com",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "since": rows[0]["date"] if rows else None,
        "live": bool(live),
        "totals": totals,
        "today": {
            "visitors": _n(live.get("visitors")),
            "views": _n(live.get("pageviews")),
            "bookings": _n(live.get("bookings")),
            "phone_leads": _n(live.get("phone_leads")),
            "organic": _n(live.get("organic_visitors")),
            "bots": _n(live.get("bot_hits")),
        },
        "channels": channels,
        "sparkline": spark,
        "leads": {
            "period_bookings": period_bookings,
            "period_phone": period_phone,
            "bookings_all_time": _n(all_time.get("bookings_all_time")),
            "phone_leads_all_time": _n(all_time.get("phone_leads_all_time")),
            "own_rows_excluded": _n(all_time.get("own_rows_excluded")),
        },
        "search": {
            "share_pct": goal.get("share_pct"),
            "target_pct": goal.get("target_pct"),
            "top3": goal.get("top3"),
            "top10": goal.get("top10"),
            "tracked_queries": goal.get("tracked_queries"),
            "coverage_pct": goal.get("coverage_pct"),
            "statement": goal.get("statement"),
            "clicks": gsc.get("clicks"),
            "impressions": gsc.get("impressions"),
            "avg_position": gsc.get("avg_position"),
            "connected": bool(gsc.get("connected")),
            "gsc_date": gsc.get("date"),
        },
        "pages": {"counts": page_counts, "total": sum(page_counts.values())},
        "build": {
            "date": last_build.get("date"),
            "steps": [s.get("detail") for s in (last_build.get("log") or [])
                      if isinstance(s, dict) and s.get("ok") and s.get("detail")][:6],
        },
        "warnings": warnings,
    }


def build_cached(days=14):
    now = time.time()
    with _LOCK:
        if _CACHE["data"] is not None and now - _CACHE["at"] < CACHE_TTL:
            return _CACHE["data"]
    data = build(days=days)
    with _LOCK:
        _CACHE["at"] = time.time()
        _CACHE["data"] = data
    return data


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
